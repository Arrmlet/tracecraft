"""Tests for the v0.2.5 features.

1. list_keys plumbing: detail=True dicts, start_after server-side skip,
   back-compat plain calls (S3 via moto; HF via a fake filesystem).
2. memory history: every set appends a snapshot; `memory history` replays
   them; `get --with-meta`; `list` excludes the _history namespace.
3. inbox cursor: `--new` shows only unseen messages and advances the cursor;
   the cursor object is never mail; `--delete` warns deprecated.
4. send --step threading: recorded in the body, tagged in inbox output.
5. status: honors the claim/status crash-window invariant, --json is parseable.
"""

from __future__ import annotations

import json

import boto3
import pytest
from click.testing import CliRunner
from moto import mock_aws

from tracecraft.cli import cli
from tracecraft.hf import HF
from tracecraft.s3 import S3

BUCKET = "tc-v025-test"
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


@pytest.fixture
def store(env):
    return S3(
        endpoint=None,
        bucket=BUCKET,
        project=PROJECT,
        access_key="testing",
        secret_key="testing",
    )


# ---------- 1. list_keys plumbing ----------


def test_list_keys_plain_still_returns_strings(store):
    store.put_json("memory/a.json", {"v": 1})
    keys = store.list_keys("memory/")
    assert keys == ["memory/a.json"]


def test_list_keys_detail_returns_size_and_mtime(store):
    store.put_json("memory/a.json", {"v": 1})
    (entry,) = store.list_keys("memory/", detail=True)
    assert entry["key"] == "memory/a.json"
    assert entry["size"] > 0
    assert entry["last_modified"]  # ISO string


def test_list_keys_start_after_skips_lexicographically(store):
    for name in ("m/1.json", "m/2.json", "m/3.json"):
        store.put_json(name, {})
    assert store.list_keys("m/", start_after="m/1.json") == ["m/2.json", "m/3.json"]
    assert store.list_keys("m/", start_after="m/3.json") == []


class _FakeHfFs:
    """Just enough of HfFileSystem for list_keys: exists + find.

    Like real fsspec filesystems, accepts hf:// URLs but stores and returns
    protocol-stripped paths (that's why HF.list_keys strips a bare
    'buckets/...' prefix from find() results).
    """

    def __init__(self, paths):
        self.paths = paths  # protocol-stripped paths -> info dict

    @staticmethod
    def _strip(path):
        return path.removeprefix("hf://")

    def exists(self, path):
        path = self._strip(path)
        return any(p.startswith(path) for p in self.paths)

    def find(self, path, detail=False):
        path = self._strip(path)
        hits = {p: i for p, i in self.paths.items() if p.startswith(path)}
        return hits if detail else list(hits)


def _fake_hf(paths):
    hf = HF.__new__(HF)
    hf.fs = _FakeHfFs(paths)
    hf.bucket = "user/bkt"
    hf.project = PROJECT
    hf.base = "hf://buckets/user/bkt"
    return hf


def test_hf_list_keys_start_after_and_detail():
    base = f"buckets/user/bkt/{PROJECT}"
    hf = _fake_hf(
        {
            f"{base}/m/1.json": {"size": 10, "last_commit": None},
            f"{base}/m/2.json": {"size": 20, "last_commit": None},
        }
    )
    assert hf.list_keys("m/") == ["m/1.json", "m/2.json"]
    assert hf.list_keys("m/", start_after="m/1.json") == ["m/2.json"]
    details = hf.list_keys("m/", detail=True, start_after="m/1.json")
    assert details == [{"key": "m/2.json", "size": 20, "last_modified": None}]


# ---------- 2. memory history ----------


def test_memory_set_appends_history_and_history_replays(env):
    env.invoke(cli, ["memory", "set", "phase1.status", "started"])
    env.invoke(cli, ["memory", "set", "phase1.status", "done"])

    r = env.invoke(cli, ["memory", "history", "phase1.status"])
    assert r.exit_code == 0, r.output
    lines = [ln for ln in r.output.splitlines() if ln.strip()]
    assert len(lines) == 2
    assert "started" in lines[0] and "done" in lines[1]  # oldest first
    assert "designer" in lines[0]


def test_memory_get_still_returns_current_value(env):
    env.invoke(cli, ["memory", "set", "k", "v1"])
    env.invoke(cli, ["memory", "set", "k", "v2"])
    r = env.invoke(cli, ["memory", "get", "k"])
    assert r.output.strip() == "v2"


def test_memory_get_with_meta(env):
    env.invoke(cli, ["memory", "set", "k", "v1"])
    r = env.invoke(cli, ["memory", "get", "k", "--with-meta"])
    doc = json.loads(r.output)
    assert doc["value"] == "v1"
    assert doc["set_by"] == "designer"
    assert doc["set_at"]


def test_memory_list_excludes_history(env):
    env.invoke(cli, ["memory", "set", "a.b", "1"])
    env.invoke(cli, ["memory", "set", "a.b", "2"])
    r = env.invoke(cli, ["memory", "list"])
    assert r.output.split() == ["a.b"]


def test_memory_history_reserved_namespace_rejected(env):
    r = env.invoke(cli, ["memory", "set", "_history.x", "boom"])
    assert r.exit_code != 0
    assert "reserved" in r.output


def test_memory_history_missing_key_exits_1(env):
    r = env.invoke(cli, ["memory", "history", "never.set"])
    assert r.exit_code == 1


def test_memory_history_limit(env):
    for i in range(5):
        env.invoke(cli, ["memory", "set", "k", f"v{i}"])
    r = env.invoke(cli, ["memory", "history", "k", "--limit", "2"])
    lines = [ln for ln in r.output.splitlines() if ln.strip()]
    assert len(lines) == 2
    assert "v3" in lines[0] and "v4" in lines[1]  # newest two, oldest first


# ---------- 3. inbox cursor ----------


def test_inbox_new_shows_then_silences_then_shows_only_new(env):
    env.invoke(cli, ["send", "reviewer", "first"])
    r1 = env.invoke(cli, ["inbox", "--new"], env={"TRACECRAFT_AGENT": "reviewer"})
    assert "first" in r1.output

    r2 = env.invoke(cli, ["inbox", "--new"], env={"TRACECRAFT_AGENT": "reviewer"})
    assert "first" not in r2.output
    assert "No new messages." in r2.output

    env.invoke(cli, ["send", "reviewer", "second"])
    r3 = env.invoke(cli, ["inbox", "--new"], env={"TRACECRAFT_AGENT": "reviewer"})
    assert "second" in r3.output
    assert "first" not in r3.output


def test_inbox_new_covers_broadcasts(env):
    env.invoke(cli, ["send", "_broadcast", "hear ye"])
    r1 = env.invoke(cli, ["inbox", "--new"], env={"TRACECRAFT_AGENT": "reviewer"})
    assert "hear ye" in r1.output
    r2 = env.invoke(cli, ["inbox", "--new"], env={"TRACECRAFT_AGENT": "reviewer"})
    assert "hear ye" not in r2.output


def test_plain_inbox_does_not_advance_cursor_and_hides_cursor_file(env):
    env.invoke(cli, ["send", "reviewer", "msg"])
    env.invoke(cli, ["inbox", "--new"], env={"TRACECRAFT_AGENT": "reviewer"})
    # Plain inbox still shows the full log, and never renders the cursor object.
    r = env.invoke(cli, ["inbox"], env={"TRACECRAFT_AGENT": "reviewer"})
    assert "msg" in r.output
    assert "_cursor" not in r.output


def test_inbox_new_is_per_agent(env):
    env.invoke(cli, ["send", "_broadcast", "to all"])
    env.invoke(cli, ["inbox", "--new"], env={"TRACECRAFT_AGENT": "reviewer"})
    # A different agent still sees it as new.
    r = env.invoke(cli, ["inbox", "--new"], env={"TRACECRAFT_AGENT": "tester"})
    assert "to all" in r.output


def test_inbox_delete_warns_deprecated_and_conflicts_with_new(env):
    env.invoke(cli, ["send", "reviewer", "m"])
    r = env.invoke(cli, ["inbox", "--delete"], env={"TRACECRAFT_AGENT": "reviewer"})
    assert "deprecated" in r.output
    r2 = env.invoke(cli, ["inbox", "--delete", "--new"], env={"TRACECRAFT_AGENT": "reviewer"})
    assert r2.exit_code != 0


def test_delete_does_not_remove_cursor(env):
    env.invoke(cli, ["send", "reviewer", "a"])
    env.invoke(cli, ["inbox", "--new"], env={"TRACECRAFT_AGENT": "reviewer"})
    env.invoke(cli, ["send", "reviewer", "b"])
    env.invoke(cli, ["inbox", "--delete"], env={"TRACECRAFT_AGENT": "reviewer"})
    c = boto3.client("s3")
    out = c.list_objects_v2(Bucket=BUCKET, Prefix=f"{PROJECT}/messages/reviewer/")
    keys = [o["Key"] for o in out.get("Contents", [])]
    assert keys == [f"{PROJECT}/messages/reviewer/_cursor.json"]


# ---------- 4. send --step threading ----------


def test_send_step_recorded_and_tagged(env):
    env.invoke(cli, ["send", "reviewer", "contract ready", "--step", "design"])
    c = boto3.client("s3")
    out = c.list_objects_v2(Bucket=BUCKET, Prefix=f"{PROJECT}/messages/reviewer/")
    (key,) = [o["Key"] for o in out.get("Contents", [])]
    doc = json.loads(c.get_object(Bucket=BUCKET, Key=key)["Body"].read())
    assert doc["step"] == "design"

    r = env.invoke(cli, ["inbox"], env={"TRACECRAFT_AGENT": "reviewer"})
    assert "[step design]" in r.output
    assert "contract ready" in r.output


def test_send_without_step_keeps_plain_format(env):
    env.invoke(cli, ["send", "reviewer", "plain"])
    r = env.invoke(cli, ["inbox"], env={"TRACECRAFT_AGENT": "reviewer"})
    assert "[step" not in r.output
    assert "designer: plain" in r.output


# ---------- 5. status ----------


def test_status_json_snapshot(env, store):
    # agent + step + message + a crash-window step (claim without status)
    env.invoke(cli, ["memory", "set", "seed", "x"])
    env.invoke(cli, ["send", "reviewer", "hello"])
    env.invoke(cli, ["claim", "design"])
    store.put_json("steps/orphan/claim.json", {"agent": "ghost", "claimed_at": "t"})
    store.put_json(
        "agents/designer.json",
        {
            "id": "designer",
            "status": "active",
            "step": None,
            "heartbeat": "2026-08-13T00:00:00+00:00",
        },
    )

    r = env.invoke(cli, ["status", "--json"])
    assert r.exit_code == 0, r.output
    snap = json.loads(r.output)

    assert snap["project"] == PROJECT
    assert [a["id"] for a in snap["agents"]] == ["designer"]

    by_id = {s["id"]: s for s in snap["steps"]}
    assert by_id["design"]["status"] == "in_progress"
    # The crash-window invariant: claim.json without status.json is in_progress
    # by the claiming agent — NEVER pending.
    assert by_id["orphan"] == {"id": "orphan", "status": "in_progress", "agent": "ghost"}

    (box,) = snap["mailboxes"]
    assert box["agent"] == "reviewer" and box["total"] == 1

    assert snap["sessions"]["count"] == 0


def test_status_text_render_and_flag_conflicts(env):
    r = env.invoke(cli, ["status"])
    assert r.exit_code == 0, r.output
    assert "AGENTS" in r.output and "STEPS" in r.output and "SESSIONS" in r.output

    r2 = env.invoke(cli, ["status", "--json", "--watch"])
    assert r2.exit_code != 0


def test_status_unread_uses_cursor(env):
    env.invoke(cli, ["send", "reviewer", "one"])
    env.invoke(cli, ["inbox", "--new"], env={"TRACECRAFT_AGENT": "reviewer"})
    env.invoke(cli, ["send", "reviewer", "two"])

    r = env.invoke(cli, ["status", "--json"])
    (box,) = json.loads(r.output)["mailboxes"]
    assert box["total"] == 2
    assert box["unread"] == 1


# ---------- regressions from the adversarial review ----------


def test_memory_history_isolated_from_nested_keys(env):
    """History of 'phase1' must not sweep in 'phase1.status' snapshots, and
    --limit must slice the requested key's OWN versions."""
    env.invoke(cli, ["memory", "set", "phase1", "P1-v1"])
    env.invoke(cli, ["memory", "set", "phase1.status", "SUB-v1"])
    env.invoke(cli, ["memory", "set", "phase1", "P1-v2"])

    r = env.invoke(cli, ["memory", "history", "phase1"])
    lines = [ln for ln in r.output.splitlines() if ln.strip()]
    assert len(lines) == 2
    assert "P1-v1" in lines[0] and "P1-v2" in lines[1]
    assert "SUB-v1" not in r.output

    r2 = env.invoke(cli, ["memory", "history", "phase1", "--limit", "1"])
    assert "P1-v2" in r2.output and "SUB-v1" not in r2.output

    r3 = env.invoke(cli, ["memory", "history", "phase1.status"])
    assert "SUB-v1" in r3.output and "P1-v" not in r3.output


def test_memory_set_rejects_slashes(env):
    """A literal '/' must not path-traverse into the _history audit namespace."""
    r = env.invoke(cli, ["memory", "set", "_history/target/175_forged_dead", "FORGED"])
    assert r.exit_code != 0
    assert "not allowed" in r.output
    r2 = env.invoke(cli, ["memory", "history", "target"])
    assert r2.exit_code == 1


def test_send_rejects_slash_and_reserved_recipients(env):
    assert env.invoke(cli, ["send", "victim/sub", "poison"]).exit_code != 0
    assert env.invoke(cli, ["send", "_cursor", "poison"]).exit_code != 0
    assert env.invoke(cli, ["send", "_broadcast", "fine"]).exit_code == 0


def test_step_ids_reject_slashes_everywhere(env):
    """'/' in a step id would write steps/a/b/... — a phantom step that
    key-layout readers (status) misparse. Rejected at the shared chokepoint."""
    assert env.invoke(cli, ["claim", "a/b"]).exit_code != 0
    assert env.invoke(cli, ["step-status", "a/b"]).exit_code != 0
    assert env.invoke(cli, ["complete", "a/b"]).exit_code != 0
    # dots still normalize to dashes as before
    r = env.invoke(cli, ["claim", "Phase.One"])
    assert r.exit_code == 0, r.output
    c = boto3.client("s3")
    c.head_object(Bucket=BUCKET, Key=f"{PROJECT}/steps/phase-one/claim.json")  # raises if absent


def test_inbox_new_ignores_nested_junk_in_mailbox(env, store):
    """A nested object (e.g. written by an old client) must not show as mail
    or poison the cursor into blinding future reads."""
    store.put_json(
        "messages/reviewer/sub/9999999999999999999_evil_deadbeef.json",
        {"from": "evil", "to": "reviewer", "message": "junk", "sent_at": "2099-01-01"},
    )
    env.invoke(cli, ["send", "reviewer", "legit-1"])
    r1 = env.invoke(cli, ["inbox", "--new"], env={"TRACECRAFT_AGENT": "reviewer"})
    assert "legit-1" in r1.output and "junk" not in r1.output
    env.invoke(cli, ["send", "reviewer", "legit-2"])
    r2 = env.invoke(cli, ["inbox", "--new"], env={"TRACECRAFT_AGENT": "reviewer"})
    assert "legit-2" in r2.output


def test_inbox_new_delivers_late_arrivals_within_grace(env, store):
    """A message stamped BEFORE the cursor's newest key but landing late (slow
    PUT / clock skew) must still be delivered once — the grace window."""
    import time as _time

    env.invoke(cli, ["send", "reviewer", "on-time"])
    r1 = env.invoke(cli, ["inbox", "--new"], env={"TRACECRAFT_AGENT": "reviewer"})
    assert "on-time" in r1.output

    late_ts = _time.time_ns() - 60 * 1_000_000_000  # 1 min ago — inside the 5-min grace
    store.put_json(
        f"messages/reviewer/{late_ts}_slowpoke_abcd1234.json",
        {
            "from": "slowpoke",
            "to": "reviewer",
            "message": "late but alive",
            "sent_at": "2026-08-13T00:00:00+00:00",
        },
    )
    r2 = env.invoke(cli, ["inbox", "--new"], env={"TRACECRAFT_AGENT": "reviewer"})
    assert "late but alive" in r2.output
    r3 = env.invoke(cli, ["inbox", "--new"], env={"TRACECRAFT_AGENT": "reviewer"})
    assert "late but alive" not in r3.output  # shown exactly once


def test_inbox_line_format_pinned_for_executor_parsers(env):
    """robot_executor.py and similar automation parse inbox stdout with this
    exact regex — plain (no --step) lines must keep matching it forever."""
    import re

    env.invoke(cli, ["send", "reviewer", "nod say hello"])
    r = env.invoke(cli, ["inbox"], env={"TRACECRAFT_AGENT": "reviewer"})
    m = re.match(r"\[(.*?)\] \((direct|broadcast)\) (\S+): (.+)", r.stdout.strip().splitlines()[0])
    assert m, f"executor regex must match plain inbox lines: {r.stdout!r}"
    assert m.group(2) == "direct"
    assert m.group(3) == "designer"
    assert m.group(4) == "nod say hello"


def test_deprecation_warning_goes_to_stderr_not_stdout(env):
    env.invoke(cli, ["send", "reviewer", "m"])
    r = env.invoke(cli, ["inbox", "--delete"], env={"TRACECRAFT_AGENT": "reviewer"})
    assert "deprecated" in r.stderr
    assert "deprecated" not in r.stdout  # stdout parsers must never see it


def test_legacy_bare_key_cursor_tolerated(env, store):
    """A cursor in the old bare-key format degrades gracefully (treated as a
    plain watermark), never crashes or blinds the mailbox."""
    env.invoke(cli, ["send", "reviewer", "old-1"])
    keys = [k for k in store.list_keys("messages/reviewer/") if not k.endswith("_cursor.json")]
    store.put_json("messages/reviewer/_cursor.json", {"direct": max(keys), "broadcast": None})
    env.invoke(cli, ["send", "reviewer", "new-1"])
    r = env.invoke(cli, ["inbox", "--new"], env={"TRACECRAFT_AGENT": "reviewer"})
    assert "new-1" in r.output


def test_status_unread_includes_foreign_broadcasts(env):
    env.invoke(cli, ["send", "reviewer", "d1"])
    env.invoke(cli, ["inbox", "--new"], env={"TRACECRAFT_AGENT": "reviewer"})
    env.invoke(cli, ["send", "_broadcast", "b1"])  # sent by designer, unseen by reviewer

    r = env.invoke(cli, ["status", "--json"])
    boxes = {b["agent"]: b for b in json.loads(r.output)["mailboxes"]}
    assert boxes["reviewer"]["unread"] == 1
    assert boxes["_broadcast"]["unread"] is None  # the shared box has no cursor of its own


def test_hf_detail_reads_bucket_mtime():
    """Bucket-backed HfFileSystem info carries 'mtime', not 'last_commit'."""
    from datetime import datetime, timezone

    base = f"buckets/user/bkt/{PROJECT}"
    dt = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    hf = _fake_hf({f"{base}/m/1.json": {"size": 10, "mtime": dt}})
    (entry,) = hf.list_keys("m/", detail=True)
    assert entry["last_modified"] == dt.isoformat()
