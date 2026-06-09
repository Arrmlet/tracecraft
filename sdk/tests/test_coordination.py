"""Tests for coordination correctness: claim races, complete ownership,
the claim/status crash window, and wait-for's blocked fast-fail.

All run against moto's in-process S3 — no network.
"""

from __future__ import annotations

import json
import time

import boto3
import pytest
from click.testing import CliRunner
from moto import mock_aws

from tracecraft.cli import cli

BUCKET = "tc-coord-test"
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
        "agent_id": "agent-a",
        "access_key": "testing",
        "secret_key": "testing",
    }
    (work / ".tracecraft.json").write_text(json.dumps(cfg))
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield CliRunner()


def _as(agent):
    return {"TRACECRAFT_AGENT": agent}


def _get(key):
    c = boto3.client("s3")
    return json.loads(c.get_object(Bucket=BUCKET, Key=f"{PROJECT}/{key}")["Body"].read())


# ---------- atomic claim: two claimers, exactly one wins ----------


def test_claim_race_exactly_one_winner(env):
    r1 = env.invoke(cli, ["claim", "build"], env=_as("agent-a"))
    r2 = env.invoke(cli, ["claim", "build"], env=_as("agent-b"))
    outcomes = [r.exit_code == 0 for r in (r1, r2)]
    assert outcomes.count(True) == 1, f"exactly one claimer must win: {r1.output} / {r2.output}"
    assert "already claimed by agent-a" in r2.output
    assert _get("steps/build/claim.json")["agent"] == "agent-a"


# ---------- complete: ownership enforced, --force overrides ----------


def test_complete_rejects_non_owner(env):
    env.invoke(cli, ["claim", "build"], env=_as("agent-a"))
    r = env.invoke(cli, ["complete", "build"], env=_as("agent-b"))
    assert r.exit_code != 0
    assert "claimed by 'agent-a'" in r.output
    assert "--force" in r.output
    # the step's status must be untouched
    assert _get("steps/build/status.json")["status"] == "in_progress"


def test_complete_owner_succeeds(env):
    env.invoke(cli, ["claim", "build"], env=_as("agent-a"))
    r = env.invoke(cli, ["complete", "build"], env=_as("agent-a"))
    assert r.exit_code == 0, r.output
    assert _get("steps/build/status.json")["status"] == "complete"


def test_complete_force_overrides_ownership(env):
    env.invoke(cli, ["claim", "build"], env=_as("agent-a"))
    r = env.invoke(cli, ["complete", "build", "--force"], env=_as("agent-b"))
    assert r.exit_code == 0, r.output
    doc = _get("steps/build/status.json")
    assert doc["status"] == "complete"
    assert doc["agent"] == "agent-b"


def test_complete_unclaimed_step_is_allowed(env):
    """No claim.json at all — nothing to own, complete goes through."""
    r = env.invoke(cli, ["complete", "adhoc"], env=_as("agent-a"))
    assert r.exit_code == 0, r.output


# ---------- crash window: claim.json exists, status.json missing ----------


def test_step_status_treats_claim_without_status_as_in_progress(env):
    env.invoke(cli, ["claim", "build"], env=_as("agent-a"))
    # simulate a crash between the two writes: claim landed, status didn't
    boto3.client("s3").delete_object(Bucket=BUCKET, Key=f"{PROJECT}/steps/build/status.json")
    r = env.invoke(cli, ["step-status", "build"])
    assert r.exit_code == 0, r.output
    assert "in_progress" in r.output
    assert "agent-a" in r.output


def test_wait_for_treats_claim_without_status_as_waiting(env):
    env.invoke(cli, ["claim", "build"], env=_as("agent-a"))
    boto3.client("s3").delete_object(Bucket=BUCKET, Key=f"{PROJECT}/steps/build/status.json")
    r = env.invoke(cli, ["wait-for", "build", "--timeout", "1"])
    # not complete, not blocked → waits, then times out (no crash, no false success)
    assert r.exit_code != 0
    assert "Timeout" in r.output


# ---------- wait-for: blocked fails fast, needs_review keeps waiting ----------


def test_wait_for_fast_fails_on_blocked(env):
    env.invoke(cli, ["claim", "build"], env=_as("agent-a"))
    env.invoke(cli, ["complete", "build", "--blocked"], env=_as("agent-a"))
    start = time.monotonic()
    r = env.invoke(cli, ["wait-for", "build", "--timeout", "300"])
    elapsed = time.monotonic() - start
    assert r.exit_code != 0
    assert "blocked" in r.output
    assert elapsed < 10, f"must fail fast, not spin toward the timeout (took {elapsed:.1f}s)"


def test_wait_for_mentions_needs_review_while_waiting(env):
    env.invoke(cli, ["claim", "build"], env=_as("agent-a"))
    env.invoke(cli, ["complete", "build", "--needs-review"], env=_as("agent-a"))
    r = env.invoke(cli, ["wait-for", "build", "--timeout", "1"])
    assert r.exit_code != 0  # still waiting → times out
    assert "needs review: build" in r.output
