"""End-to-end tests for `tracecraft session` CLI.

Stack:
  - moto's @mock_aws for the S3 backend (in-process, no network)
  - tmp_path for a fake ~/.claude/projects/<encoded-cwd>/ tree
  - monkeypatch on tracecraft.cli.session.STATE_DIR so state files don't pollute $HOME
  - CliRunner to drive the actual CLI

What we prove here:
  1. mirror --once uploads the first part starting from offset 0
  2. mirror --once again on the same session uploads ONLY the new bytes as part-00001
  3. seq numbering survives state-file deletion (derived from bucket LIST)
  4. redaction default-on: a planted AWS key disappears from the bucket part and shows in meta counts
  5. --no-redact passes raw bytes through
  6. session list shows the session after upload
  7. session show <sid> --tail N concatenates parts and prints the right lines
  8. session stop clears local state and marks ended_at in meta
"""

from __future__ import annotations

import json

import boto3
import pytest
from click.testing import CliRunner
from moto import mock_aws

import tracecraft.cli.session as session_mod
from tracecraft.cli import cli
from tracecraft.harness.claude_code import _encode_cwd


BUCKET = "tc-session-test"
PROJECT = "demo"


# ---------- shared fixtures ----------


@pytest.fixture
def s3_env(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield


@pytest.fixture
def cli_env(tmp_path, monkeypatch, s3_env):
    """Wires up:
      - state dir under tmp_path (isolated from real $HOME)
      - tracecraft config pointing at moto bucket
      - fake ~/.claude/projects tree at tmp_path/dot-claude
      - a project cwd at tmp_path/proj with a starter JSONL session file
    Returns: (runner, cwd, session_file, session_id)
    """
    # 1. state dir
    state_dir = tmp_path / "mirror-state"
    monkeypatch.setattr(session_mod, "STATE_DIR", state_dir)

    # 2. tracecraft config -> point ~/.tracecraft/config.json at the moto bucket
    fake_home = tmp_path / "fake-home"
    (fake_home / ".tracecraft").mkdir(parents=True)
    cfg = {
        "backend": "s3",
        "endpoint": None,
        "bucket": BUCKET,
        "project": PROJECT,
        "agent_id": "tester",
        "access_key": "testing",
        "secret_key": "testing",
    }
    (fake_home / ".tracecraft" / "config.json").write_text(json.dumps(cfg))
    monkeypatch.setenv("HOME", str(fake_home))
    # tracecraft.config uses Path.home() which honors $HOME; good.

    # 3. fake Claude Code session under cwd
    dot_claude_root = tmp_path / "dot-claude" / "projects"
    cwd = tmp_path / "proj"
    cwd.mkdir()
    pdir = dot_claude_root / _encode_cwd(cwd)
    pdir.mkdir(parents=True)
    session_file = pdir / "sess-abc12345.jsonl"
    session_file.write_bytes(b"")

    # 4. Point ClaudeCodeHarness root at our fake tree.
    # The harness reads Path.home()/".claude"/"projects" by default — easier to
    # monkeypatch the class default by replacing the registry entry with a factory.
    from tracecraft.harness import REGISTRY
    from tracecraft.harness.claude_code import ClaudeCodeHarness

    original = REGISTRY["claude-code"]

    def factory():
        return ClaudeCodeHarness(root=dot_claude_root)

    monkeypatch.setitem(REGISTRY, "claude-code", factory)
    # get_harness instantiates with no args; we routed it through a callable
    # that captures `root` via closure, so the protocol contract is preserved.

    runner = CliRunner()
    yield runner, cwd, session_file, "sess-abc12345"

    # restore (monkeypatch teardown handles env/state_dir; restore registry too)
    REGISTRY["claude-code"] = original


def _bucket_keys():
    """Return all keys under PROJECT/ stripped of the project prefix."""
    client = boto3.client("s3")
    resp = client.list_objects_v2(Bucket=BUCKET, Prefix=f"{PROJECT}/")
    return [obj["Key"][len(PROJECT) + 1 :] for obj in resp.get("Contents", [])]


def _get_meta(session_id):
    client = boto3.client("s3")
    key = f"{PROJECT}/sessions/claude-code/{session_id}/meta.json"
    obj = client.get_object(Bucket=BUCKET, Key=key)
    return json.loads(obj["Body"].read())


# ---------- tests ----------


def test_mirror_uploads_first_part(cli_env):
    runner, cwd, sess, sid = cli_env
    sess.write_bytes(b'{"role":"user","content":"hi"}\n')

    r = runner.invoke(cli, ["session", "mirror", "--harness", "claude-code", "--cwd", str(cwd)])
    assert r.exit_code == 0, r.output
    assert "part-00000-" in r.output

    keys = _bucket_keys()
    parts = [k for k in keys if "/part-" in k]
    assert len(parts) == 1
    assert parts[0].startswith(f"sessions/claude-code/{sid}/part-00000-")
    assert f"sessions/claude-code/{sid}/meta.json" in keys


def test_mirror_second_call_uploads_only_new_bytes(cli_env):
    runner, cwd, sess, sid = cli_env
    sess.write_bytes(b'{"role":"user","content":"first"}\n')
    r1 = runner.invoke(cli, ["session", "mirror", "--harness", "claude-code", "--cwd", str(cwd)])
    assert r1.exit_code == 0, r1.output

    # Append more
    with open(sess, "ab") as f:
        f.write(b'{"role":"assistant","content":"second"}\n')
    r2 = runner.invoke(cli, ["session", "mirror", "--harness", "claude-code", "--cwd", str(cwd)])
    assert r2.exit_code == 0, r2.output
    assert "part-00001-" in r2.output

    keys = _bucket_keys()
    parts = sorted(k for k in keys if "/part-" in k)
    assert len(parts) == 2

    # Verify the second part contains only the appended line
    client = boto3.client("s3")
    p1 = client.get_object(Bucket=BUCKET, Key=f"{PROJECT}/{parts[1]}")["Body"].read()
    assert p1 == b'{"role":"assistant","content":"second"}\n'

    meta = _get_meta(sid)
    assert len(meta["parts"]) == 2
    assert meta["total_source_bytes"] == sess.stat().st_size


def test_mirror_skips_when_no_new_bytes(cli_env):
    runner, cwd, sess, _sid = cli_env
    sess.write_bytes(b'{"x":1}\n')
    r1 = runner.invoke(cli, ["session", "mirror", "--harness", "claude-code", "--cwd", str(cwd)])
    assert r1.exit_code == 0
    r2 = runner.invoke(cli, ["session", "mirror", "--harness", "claude-code", "--cwd", str(cwd)])
    assert r2.exit_code == 0
    assert "nothing new" in r2.output


def test_seq_derived_from_bucket_survives_state_loss(cli_env, tmp_path):
    runner, cwd, sess, sid = cli_env
    sess.write_bytes(b'{"a":1}\n')
    runner.invoke(cli, ["session", "mirror", "--harness", "claude-code", "--cwd", str(cwd)])

    # Nuke local state — simulating user wiped ~/.tracecraft or moved machines
    for p in session_mod.STATE_DIR.iterdir():
        p.unlink()

    with open(sess, "ab") as f:
        f.write(b'{"a":2}\n')
    r = runner.invoke(cli, ["session", "mirror", "--harness", "claude-code", "--cwd", str(cwd)])
    assert r.exit_code == 0, r.output
    # With no state file, offset resets to 0, so the "new" chunk is the WHOLE
    # file. That goes up as part-00001 (next seq from bucket LIST), NOT part-00000.
    assert "part-00001-" in r.output

    keys = sorted(_bucket_keys())
    parts = [k for k in keys if "/part-" in k]
    assert len(parts) == 2
    # Confirm both seqs are present and disjoint
    seqs = sorted(int(k.rsplit("/", 1)[-1].split("-")[1]) for k in parts)
    assert seqs == [0, 1]


def test_redaction_default_on_scrubs_aws_key(cli_env):
    runner, cwd, sess, sid = cli_env
    leak = b'{"tool":"bash","output":"export AWS_KEY=AKIAIOSFODNN7EXAMPLE\\n"}\n'
    sess.write_bytes(leak)

    r = runner.invoke(cli, ["session", "mirror", "--harness", "claude-code", "--cwd", str(cwd)])
    assert r.exit_code == 0, r.output

    client = boto3.client("s3")
    parts = [k for k in _bucket_keys() if "/part-" in k]
    body = client.get_object(Bucket=BUCKET, Key=f"{PROJECT}/{parts[0]}")["Body"].read()
    assert b"AKIAIOSFODNN7EXAMPLE" not in body
    assert b"[REDACTED:aws_access_key]" in body

    meta = _get_meta(sid)
    assert meta["redaction_counts"].get("aws_access_key") == 1


def test_no_redact_passes_raw_bytes(cli_env):
    runner, cwd, sess, sid = cli_env
    leak = b'{"k":"AKIAIOSFODNN7EXAMPLE"}\n'
    sess.write_bytes(leak)

    r = runner.invoke(
        cli,
        ["session", "mirror", "--harness", "claude-code", "--cwd", str(cwd), "--no-redact"],
    )
    assert r.exit_code == 0, r.output

    client = boto3.client("s3")
    parts = [k for k in _bucket_keys() if "/part-" in k]
    body = client.get_object(Bucket=BUCKET, Key=f"{PROJECT}/{parts[0]}")["Body"].read()
    assert b"AKIAIOSFODNN7EXAMPLE" in body
    meta = _get_meta(sid)
    assert meta["redaction_counts"] == {}


def test_session_list_shows_uploaded_session(cli_env):
    runner, cwd, sess, sid = cli_env
    sess.write_bytes(b'{"x":1}\n')
    runner.invoke(cli, ["session", "mirror", "--harness", "claude-code", "--cwd", str(cwd)])

    r = runner.invoke(cli, ["session", "list"])
    assert r.exit_code == 0, r.output
    assert "claude-code" in r.output
    assert sid[:8] in r.output


def test_session_show_tails_concatenated_parts(cli_env):
    runner, cwd, sess, sid = cli_env
    sess.write_bytes(b"line1\n")
    runner.invoke(cli, ["session", "mirror", "--harness", "claude-code", "--cwd", str(cwd)])
    with open(sess, "ab") as f:
        f.write(b"line2\nline3\n")
    runner.invoke(cli, ["session", "mirror", "--harness", "claude-code", "--cwd", str(cwd)])

    r = runner.invoke(cli, ["session", "show", sid, "--tail", "2"])
    assert r.exit_code == 0, r.output
    assert "--- tail ---" in r.output
    assert "line2" in r.output
    assert "line3" in r.output
    assert "line1" not in r.output.split("--- tail ---")[1]  # not in the tail block


def test_session_stop_clears_state_and_marks_ended(cli_env):
    runner, cwd, sess, sid = cli_env
    sess.write_bytes(b'{"x":1}\n')
    runner.invoke(cli, ["session", "mirror", "--harness", "claude-code", "--cwd", str(cwd)])

    state_files_before = list(session_mod.STATE_DIR.glob("*.json"))
    assert state_files_before, "expected state file to exist after mirror"

    r = runner.invoke(cli, ["session", "stop", sid])
    assert r.exit_code == 0, r.output
    assert "state_cleared=True" in r.output

    state_files_after = list(session_mod.STATE_DIR.glob("*.json"))
    assert not state_files_after

    meta = _get_meta(sid)
    assert meta.get("ended_at") is not None


def test_mirror_unknown_session_id_errors_cleanly(cli_env):
    runner, cwd, _sess, _sid = cli_env
    r = runner.invoke(
        cli,
        [
            "session",
            "mirror",
            "--harness",
            "claude-code",
            "--cwd",
            str(cwd),
            "--session-id",
            "does-not-exist",
        ],
    )
    assert r.exit_code != 0
    assert "No claude-code session found" in r.output


def test_show_unknown_session_errors_cleanly(cli_env):
    runner, _cwd, _sess, _sid = cli_env
    r = runner.invoke(cli, ["session", "show", "ghost-sid"])
    assert r.exit_code != 0
    assert "session not found" in r.output
