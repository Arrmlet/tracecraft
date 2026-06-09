"""Tests for agent-to-agent messaging — especially the same-instant key collision.

The bug these guard against: message keys were `messages/<recip>/<int_seconds>_<sender>.json`,
so two messages from one sender to one recipient in the same wall-clock second collided on
the same key and the later one silently overwrote the earlier (a 5-message burst kept 1).
The fix uses nanosecond resolution + a uuid suffix, so every send is a distinct key.
"""

from __future__ import annotations

import json

import boto3
import pytest
from click.testing import CliRunner
from moto import mock_aws

from tracecraft.cli import cli


BUCKET = "tc-msg-test"
PROJECT = "demo"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    cfg = {
        "backend": "s3",
        "endpoint": None,
        "bucket": BUCKET,
        "project": PROJECT,
        "agent_id": "designer",
        "access_key": "testing",
        "secret_key": "testing",
    }
    (work / ".tracecraft.json").write_text(json.dumps(cfg))
    fake_home = tmp_path / "home"
    (fake_home / ".tracecraft").mkdir(parents=True)
    (fake_home / ".tracecraft" / "config.json").write_text(json.dumps(cfg))
    monkeypatch.setenv("HOME", str(fake_home))
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield CliRunner()


def _keys(prefix):
    c = boto3.client("s3")
    out = c.list_objects_v2(Bucket=BUCKET, Prefix=f"{PROJECT}/{prefix}")
    return [o["Key"] for o in out.get("Contents", [])]


def test_burst_to_same_recipient_keeps_every_message(env):
    """The regression: many messages from one sender to one recipient, sent back to
    back (same second), must ALL survive — not collapse onto one overwritten key."""
    n = 8
    for i in range(n):
        r = env.invoke(cli, ["send", "reviewer", f"update {i}"])
        assert r.exit_code == 0, r.output
    keys = _keys("messages/reviewer/")
    assert len(keys) == n, f"expected {n} distinct message keys, got {len(keys)}: {keys}"
    # and the bodies are all distinct (no overwrite)
    c = boto3.client("s3")
    bodies = {
        json.loads(c.get_object(Bucket=BUCKET, Key=k)["Body"].read())["message"] for k in keys
    }
    assert bodies == {f"update {i}" for i in range(n)}


def test_inbox_reads_the_whole_burst(env):
    """End-to-end: a burst sent by one agent is fully readable by the recipient."""
    for i in range(5):
        env.invoke(cli, ["send", "reviewer", f"msg {i}"])
    r = env.invoke(cli, ["inbox"], env={"TRACECRAFT_AGENT": "reviewer"})
    assert r.exit_code == 0, r.output
    for i in range(5):
        assert f"msg {i}" in r.output


def test_key_shape_is_unique_per_send(env):
    """Two sends to the same recipient produce two different keys even with no delay."""
    env.invoke(cli, ["send", "reviewer", "a"])
    env.invoke(cli, ["send", "reviewer", "b"])
    keys = _keys("messages/reviewer/")
    assert len(set(keys)) == 2


def test_broadcast_and_direct_are_separate(env):
    """A broadcast lands under _broadcast, a direct message under the recipient."""
    env.invoke(cli, ["send", "_broadcast", "hello all"])
    env.invoke(cli, ["send", "reviewer", "hello you"])
    assert len(_keys("messages/_broadcast/")) == 1
    assert len(_keys("messages/reviewer/")) == 1


def test_inbox_merges_direct_and_broadcast_chronologically(env):
    """inbox must interleave direct + broadcast messages by sent_at, not print
    one prefix's raw list order after the other."""
    import time as _time

    env.invoke(cli, ["send", "reviewer", "first-direct"])
    _time.sleep(0.01)
    env.invoke(cli, ["send", "_broadcast", "second-broadcast"])
    _time.sleep(0.01)
    env.invoke(cli, ["send", "reviewer", "third-direct"])
    r = env.invoke(cli, ["inbox"], env={"TRACECRAFT_AGENT": "reviewer"})
    assert r.exit_code == 0, r.output
    out = r.output
    assert out.index("first-direct") < out.index("second-broadcast") < out.index("third-direct")


def test_message_body_carries_sender_and_recipient(env):
    """The body (not the filename) is the source of truth for from/to — readers parse
    the body, so the key shape can change freely without breaking inbox or replay."""
    env.invoke(cli, ["send", "reviewer", "check"])
    c = boto3.client("s3")
    k = _keys("messages/reviewer/")[0]
    doc = json.loads(c.get_object(Bucket=BUCKET, Key=k)["Body"].read())
    assert doc["from"] == "designer"
    assert doc["to"] == "reviewer"
    assert doc["message"] == "check"
    assert "sent_at" in doc
