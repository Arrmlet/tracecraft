"""Tests for the v0.2.1 structured handoff record.

Schema v2 adds: state enum (complete/blocked/needs_review), next_action,
git-derived changed_files. All optional + backward compatible.
"""

from __future__ import annotations

import json

import boto3
import pytest
from click.testing import CliRunner
from moto import mock_aws

from tracecraft.cli import cli
import tracecraft.cli.steps as steps_mod


BUCKET = "tc-handoff-test"
PROJECT = "demo"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    # Run from an isolated empty dir. load_config() is CWD-first, so without
    # this a stray ./.tracecraft.json in the repo would shadow our test config
    # and point the CLI at a real endpoint.
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
    # Write to the CWD-local path load_config() checks first...
    (work / ".tracecraft.json").write_text(json.dumps(cfg))
    # ...and the global HOME fallback, so tests that chdir elsewhere (the git
    # tests below) still resolve a config.
    fake_home = tmp_path / "home"
    (fake_home / ".tracecraft").mkdir(parents=True)
    (fake_home / ".tracecraft" / "config.json").write_text(json.dumps(cfg))
    monkeypatch.setenv("HOME", str(fake_home))
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield CliRunner()


def _handoff(sid="design"):
    c = boto3.client("s3")
    obj = c.get_object(Bucket=BUCKET, Key=f"{PROJECT}/steps/{sid}/handoff.json")
    return json.loads(obj["Body"].read())


def _status(sid="design"):
    c = boto3.client("s3")
    obj = c.get_object(Bucket=BUCKET, Key=f"{PROJECT}/steps/{sid}/status.json")
    return json.loads(obj["Body"].read())


# ---------- backward compatibility ----------


def test_plain_complete_is_backward_compatible(env):
    r = env.invoke(cli, ["complete", "design"])
    assert r.exit_code == 0, r.output
    assert r.output.startswith("Completed step design")
    h = _handoff()
    # v1 keys still present
    assert h["from_agent"] == "designer"
    assert h["from_step"] == "design"
    assert h["note"] == ""
    assert "created_at" in h
    # v2 defaults
    assert h["schema"] == 2
    assert h["state"] == "complete"
    assert h["next_agent"] is None
    assert h["next_action"] is None
    assert "changed_files" not in h  # only present with the git flag
    # status reflects complete
    assert _status()["status"] == "complete"
    assert "completed_at" in _status()


# ---------- state enum ----------


def test_blocked_sets_state_and_status(env):
    r = env.invoke(cli, ["complete", "design", "--blocked", "--note", "stuck on auth"])
    assert r.exit_code == 0, r.output
    assert "Blocked step design" in r.output
    assert _handoff()["state"] == "blocked"
    assert _status()["status"] == "blocked"
    assert "completed_at" not in _status()  # not complete → no completed_at


def test_needs_review_sets_state(env):
    r = env.invoke(cli, ["complete", "design", "--needs-review"])
    assert r.exit_code == 0, r.output
    assert "Needs review on step design" in r.output
    assert _handoff()["state"] == "needs_review"
    assert _status()["status"] == "needs_review"


def test_blocked_and_needs_review_mutually_exclusive(env):
    r = env.invoke(cli, ["complete", "design", "--blocked", "--needs-review"])
    assert r.exit_code != 0
    assert "at most one" in r.output


# ---------- next_action + next_agent ----------


def test_next_action_and_to(env):
    r = env.invoke(
        cli,
        ["complete", "design", "--to", "developer", "--next-action", "wire api.py into search"],
    )
    assert r.exit_code == 0, r.output
    assert "handed off to developer" in r.output
    h = _handoff()
    assert h["next_agent"] == "developer"
    assert h["next_action"] == "wire api.py into search"


# ---------- changed_files from git ----------


def test_changed_files_git_in_repo(env, tmp_path, monkeypatch):
    # Make cwd a git repo with one modified tracked file
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "a.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    (repo / "a.py").write_text("x = 2\n")  # now modified vs HEAD

    r = env.invoke(cli, ["complete", "design", "--changed-files-from-git"])
    assert r.exit_code == 0, r.output
    h = _handoff()
    assert h["changed_files"] == ["a.py"]
    assert "1 changed file(s)" in r.output


def test_changed_files_git_outside_repo_is_empty(env, tmp_path, monkeypatch):
    # cwd is NOT a git repo → flag is a no-op (empty list), never crashes
    nonrepo = tmp_path / "plain"
    nonrepo.mkdir()
    monkeypatch.chdir(nonrepo)
    r = env.invoke(cli, ["complete", "design", "--changed-files-from-git"])
    assert r.exit_code == 0, r.output
    assert _handoff()["changed_files"] == []


def test_no_assumptions_field(env):
    # We deliberately do NOT add a mandatory unresolved_assumptions field.
    env.invoke(cli, ["complete", "design", "--note", "assumed v2 API"])
    h = _handoff()
    assert "unresolved_assumptions" not in h
    assert "assumptions" not in h
    # open questions live in the free-text note
    assert h["note"] == "assumed v2 API"


# ---------- helper direct test ----------


def test_git_changed_files_helper_never_raises(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # not a repo
    assert steps_mod._git_changed_files() == []
