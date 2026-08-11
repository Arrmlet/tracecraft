"""Regression tests for the v0.2.4 fixes.

1. `inbox --delete` must never delete `_broadcast/` objects — the first reader
   was destroying broadcasts for every other agent.
2. `S3.exists()` must re-raise auth errors (403/AccessDenied) instead of
   returning False — bad credentials looked like an empty bucket.
3. `init` defaults: --project falls back to the cwd basename, --agent to the
   OS username, so the README quickstart is literally true.
"""

from __future__ import annotations

import getpass
import json

import boto3
import click
import pytest
from botocore.exceptions import ClientError
from click.testing import CliRunner
from moto import mock_aws

from tracecraft.cli import cli
from tracecraft.s3 import S3

BUCKET = "tc-v024-test"
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


# ---------- Fix 1: inbox --delete must not destroy broadcasts ----------


def test_inbox_delete_preserves_broadcasts(env):
    """First reader deletes with --delete; the broadcast must survive for others."""
    env.invoke(cli, ["send", "_broadcast", "all hands"])
    env.invoke(cli, ["send", "reviewer", "just you"])

    r = env.invoke(cli, ["inbox", "--delete"], env={"TRACECRAFT_AGENT": "reviewer"})
    assert r.exit_code == 0, r.output
    assert "all hands" in r.output
    assert "just you" in r.output

    # Direct message gone, broadcast intact.
    assert _keys("messages/reviewer/") == []
    assert len(_keys("messages/_broadcast/")) == 1

    # A second agent can still read the broadcast.
    r2 = env.invoke(cli, ["inbox"], env={"TRACECRAFT_AGENT": "tester"})
    assert "all hands" in r2.output


def test_inbox_delete_reports_direct_only_count(env):
    env.invoke(cli, ["send", "_broadcast", "b1"])
    env.invoke(cli, ["send", "reviewer", "d1"])
    env.invoke(cli, ["send", "reviewer", "d2"])
    r = env.invoke(cli, ["inbox", "--delete"], env={"TRACECRAFT_AGENT": "reviewer"})
    assert "Deleted 2 direct message(s)" in r.output


# ---------- Fix 2: exists() must surface auth errors ----------


class _FakeClient:
    def __init__(self, code="", status=403):
        self._code = code
        self._status = status

    def head_object(self, **kwargs):
        raise ClientError(
            {
                "Error": {"Code": self._code, "Message": "boom"},
                "ResponseMetadata": {"HTTPStatusCode": self._status},
            },
            "HeadObject",
        )


def _bare_s3(client):
    s3 = S3.__new__(S3)
    s3.client = client
    s3.bucket = BUCKET
    s3.project = PROJECT
    return s3


def test_exists_reraises_on_403():
    s3 = _bare_s3(_FakeClient(code="403", status=403))
    with pytest.raises(click.ClickException, match="auth error"):
        s3.exists("memory/x.json")


def test_exists_reraises_on_access_denied_code():
    s3 = _bare_s3(_FakeClient(code="AccessDenied", status=None))
    with pytest.raises(click.ClickException, match="auth error"):
        s3.exists("memory/x.json")


def test_exists_returns_false_on_404():
    s3 = _bare_s3(_FakeClient(code="404", status=404))
    assert s3.exists("memory/x.json") is False


# ---------- Fix 3: init defaults ----------


def test_init_defaults_agent_and_project(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    work = tmp_path / "my-cool-project"
    work.mkdir()
    monkeypatch.chdir(work)
    with mock_aws():
        runner = CliRunner()
        r = runner.invoke(
            cli,
            [
                "init",
                "--backend",
                "s3",
                "--endpoint",
                "https://s3.amazonaws.com",
                "--bucket",
                BUCKET,
            ],
        )
        assert r.exit_code == 0, r.output
        cfg = json.loads((work / ".tracecraft.json").read_text())
        assert cfg["project"] == "my-cool-project"
        assert cfg["agent_id"] == getpass.getuser()
