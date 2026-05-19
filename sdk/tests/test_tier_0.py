"""Backtests for the Tier 0 fixes shipped in PR #3.

Each test maps to one of the five fixes:
  - Fix 1: atomic claim via If-None-Match=*
  - Fix 2: list_keys paginates past 1000 objects
  - Fix 3: init refuses to write admin/secret defaults
  - Fix 4: init appends .tracecraft.json to .gitignore
  - Fix 5: server/ + empty integrations/transport/ removed from shipping surface

Run from repo root:
    .venv-test/bin/pytest sdk/tests/test_tier_0.py -v
"""

import importlib
import json
import pathlib

import boto3
import pytest
from click.testing import CliRunner
from moto import mock_aws

from tracecraft.cli.init_cmd import init_cmd
from tracecraft.cli.steps import claim
from tracecraft.s3 import S3, PreconditionFailed


# ---------- shared fixtures ----------

BUCKET = "tc-test"
PROJECT = "demo"
# moto's "default" endpoint — boto3 hits this when AWS_ENDPOINT_URL_S3 is set, or by URL
MOTO_ENDPOINT = "https://s3.amazonaws.com"


@pytest.fixture
def s3_env(monkeypatch):
    """Spin up a moto-mocked S3 endpoint and prime AWS env vars."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield


@pytest.fixture
def store(s3_env):
    return S3(
        endpoint=None,  # moto intercepts default endpoint
        bucket=BUCKET,
        project=PROJECT,
        access_key="testing",
        secret_key="testing",
    )


# ---------- Fix 1: atomic claim ----------

def test_fix1_atomic_put_first_writer_wins(store):
    """First put_json(if_none_match=True) succeeds; second raises PreconditionFailed."""
    store.put_json("steps/foo/claim.json", {"agent": "a"}, if_none_match=True)
    with pytest.raises(PreconditionFailed):
        store.put_json("steps/foo/claim.json", {"agent": "b"}, if_none_match=True)


def test_fix1_atomic_put_holder_unchanged(store):
    """Loser must not have overwritten winner."""
    store.put_json("steps/foo/claim.json", {"agent": "winner"}, if_none_match=True)
    try:
        store.put_json("steps/foo/claim.json", {"agent": "loser"}, if_none_match=True)
    except PreconditionFailed:
        pass
    after = store.get_json("steps/foo/claim.json")
    assert after["agent"] == "winner"


def test_fix1_claim_cli_blocks_second_caller(s3_env, monkeypatch, tmp_path):
    """Two `tracecraft claim foo` calls: second prints an explicit error."""
    cfg_file = tmp_path / ".tracecraft.json"

    def write_cfg(agent_id):
        cfg_file.write_text(json.dumps({
            "backend": "s3",
            "bucket": BUCKET,
            "project": PROJECT,
            "endpoint": None,
            "access_key": "testing",
            "secret_key": "testing",
            "agent_id": agent_id,
        }))

    monkeypatch.chdir(tmp_path)
    write_cfg("agent-a")

    runner = CliRunner()
    r1 = runner.invoke(claim, ["mystep"])
    assert r1.exit_code == 0, r1.output
    assert "Claimed step mystep as agent-a" in r1.output

    write_cfg("agent-b")
    r2 = runner.invoke(claim, ["mystep"])
    assert r2.exit_code != 0
    assert "already claimed by agent-a" in r2.output


# ---------- Fix 2: paginated list_keys ----------

def test_fix2_list_keys_returns_more_than_1000(store):
    """Write 1250 keys; ensure list_keys returns them all (not capped at 1000)."""
    for i in range(1250):
        store.put_json(f"memory/k{i:04d}.json", {"i": i})
    keys = store.list_keys("memory/")
    assert len(keys) == 1250, f"got {len(keys)} keys; should be 1250"
    # Spot-check a key past the 1000 boundary
    assert "memory/k1100.json" in keys


# ---------- Fix 3: no default admin/secret credentials ----------

def test_fix3_init_refuses_without_creds(monkeypatch, tmp_path):
    """`tracecraft init` without --access-key/--secret-key/env must error."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)

    runner = CliRunner()
    r = runner.invoke(init_cmd, [
        "--backend", "s3",
        "--endpoint", "http://localhost:9000",
        "--bucket", "x",
        "--project", "p",
        "--agent", "a",
    ])
    assert r.exit_code != 0
    assert "credentials required" in r.output.lower()
    # Critically, must NOT have written admin/secret to disk
    assert not (tmp_path / ".tracecraft.json").exists()


def test_fix3_init_reads_aws_env_vars(monkeypatch, tmp_path, s3_env):
    """When AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY are set, init succeeds."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")

    runner = CliRunner()
    r = runner.invoke(init_cmd, [
        "--backend", "s3",
        "--endpoint", MOTO_ENDPOINT,  # moto default
        "--bucket", BUCKET,
        "--project", PROJECT,
        "--agent", "a",
    ])
    assert r.exit_code == 0, r.output
    saved = json.loads((tmp_path / ".tracecraft.json").read_text())
    assert saved["access_key"] == "testing"
    assert saved["secret_key"] == "testing"
    # Definitely not the old defaults
    assert saved["access_key"] != "admin"
    assert saved["secret_key"] != "secret"


# ---------- Fix 4: .gitignore handling ----------

def test_fix4_gitignore_appended_in_git_repo(monkeypatch, tmp_path, s3_env):
    """When cwd is a git repo, init appends .tracecraft.json to .gitignore."""
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")

    runner = CliRunner()
    r = runner.invoke(init_cmd, [
        "--backend", "s3",
        "--endpoint", MOTO_ENDPOINT,
        "--bucket", BUCKET,
        "--project", PROJECT,
        "--agent", "a",
    ])
    assert r.exit_code == 0, r.output
    gi = (tmp_path / ".gitignore").read_text()
    assert ".tracecraft.json" in gi.splitlines()


def test_fix4_gitignore_not_duplicated(monkeypatch, tmp_path, s3_env):
    """If .gitignore already lists .tracecraft.json, init does not duplicate."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text("node_modules\n.tracecraft.json\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")

    runner = CliRunner()
    r = runner.invoke(init_cmd, [
        "--backend", "s3",
        "--endpoint", MOTO_ENDPOINT,
        "--bucket", BUCKET,
        "--project", PROJECT,
        "--agent", "a",
    ])
    assert r.exit_code == 0, r.output
    lines = (tmp_path / ".gitignore").read_text().splitlines()
    assert lines.count(".tracecraft.json") == 1


def test_fix4_no_gitignore_outside_repo(monkeypatch, tmp_path, s3_env):
    """When cwd is not a git repo, init does not create .gitignore."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")

    runner = CliRunner()
    r = runner.invoke(init_cmd, [
        "--backend", "s3",
        "--endpoint", MOTO_ENDPOINT,
        "--bucket", BUCKET,
        "--project", PROJECT,
        "--agent", "a",
    ])
    assert r.exit_code == 0, r.output
    assert not (tmp_path / ".gitignore").exists()


# ---------- Fix 5: dead scaffolding removed ----------

def test_fix5_no_empty_namespace_packages():
    """integrations/ and transport/ packages must not be importable."""
    with pytest.raises(ImportError):
        importlib.import_module("tracecraft.integrations")
    with pytest.raises(ImportError):
        importlib.import_module("tracecraft.transport")


def test_fix5_server_tree_archived():
    """server/ at repo root is gone; archived copy lives in plans/."""
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    assert not (repo_root / "server").exists(), "server/ should be archived"
    assert (repo_root / "plans" / "server-archive").exists(), "expected plans/server-archive/"


def test_fix5_pyproject_drops_dead_extras():
    """crewai/langgraph/claude-sdk/all extras must not be declared."""
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    text = (repo_root / "sdk" / "pyproject.toml").read_text()
    for forbidden in ('crewai = [', 'langgraph = [', 'claude-sdk = [', 'all = ['):
        assert forbidden not in text, f"pyproject still declares: {forbidden}"
