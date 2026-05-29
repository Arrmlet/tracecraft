"""Tests for the Harness adapter framework.

Covers:
  - Protocol conformance (registry + isinstance via @runtime_checkable)
  - Claude Code: cwd encoding, discovery, active-session picking, tail semantics
  - Codex: glob over YYYY/MM/DD tree, session id parsing from rollout filenames
  - Append semantics shared by both (read_new_bytes from arbitrary offset)
  - Bad-input handling (negative offset, missing directories)

Run from repo root:
    .venv-test/bin/pytest sdk/tests/test_harness.py -v
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import pytest

from tracecraft.harness import (
    REGISTRY,
    ClaudeCodeHarness,
    CodexHarness,
    HermesHarness,
    OpenClawHarness,
    get_harness,
)
from tracecraft.harness.base import Harness, Session
from tracecraft.harness.claude_code import _encode_cwd


# ---------- registry / protocol ----------


def test_registry_lists_known_harnesses():
    assert "claude-code" in REGISTRY
    assert "codex" in REGISTRY
    assert "openclaw" in REGISTRY
    assert "hermes" in REGISTRY


def test_get_harness_returns_instance():
    h = get_harness("claude-code")
    assert isinstance(h, ClaudeCodeHarness)
    assert h.name == "claude-code"


def test_get_harness_unknown_raises():
    with pytest.raises(ValueError, match="unknown harness"):
        get_harness("never-shipped")


def test_adapters_satisfy_protocol():
    # runtime_checkable Protocol — all adapters must structurally match
    assert isinstance(ClaudeCodeHarness(), Harness)
    assert isinstance(CodexHarness(), Harness)
    assert isinstance(OpenClawHarness(), Harness)
    assert isinstance(HermesHarness(), Harness)


def test_read_new_returns_bytes_and_advanced_cursor():
    # The race-free read_new contract: file harnesses return cursor+len(bytes).
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "s.jsonl"
        p.write_bytes(b"abc\n")
        cc = ClaudeCodeHarness()
        sess = Session(path=p, session_id="s")
        data, new_cursor = cc.read_new(sess, 0)
        assert data == b"abc\n"
        assert new_cursor == 4
        data2, new_cursor2 = cc.read_new(sess, new_cursor)
        assert data2 == b""
        assert new_cursor2 == 4


# ---------- Claude Code ----------


def test_claude_code_encode_cwd_matches_dotclaude_scheme(tmp_path):
    # Claude Code encodes absolute paths by replacing separators with hyphens.
    encoded = _encode_cwd(tmp_path)
    expected = str(tmp_path.resolve()).replace(os.sep, "-")
    assert encoded == expected
    assert encoded.startswith("-")  # leading separator becomes leading hyphen


def test_claude_code_discover_empty_when_no_project_dir(tmp_path):
    cc = ClaudeCodeHarness(root=tmp_path / "projects")
    assert cc.discover(tmp_path / "nonexistent-cwd") == []


def test_claude_code_discover_finds_sessions(tmp_path):
    cc_root = tmp_path / "projects"
    cwd = tmp_path / "my-proj"
    cwd.mkdir()
    project_dir = cc_root / _encode_cwd(cwd)
    project_dir.mkdir(parents=True)

    (project_dir / "sess-aaa.jsonl").write_text('{"role":"user"}\n')
    (project_dir / "sess-bbb.jsonl").write_text('{"role":"assistant"}\n')
    # Unrelated file should be ignored.
    (project_dir / "notes.txt").write_text("ignored")

    cc = ClaudeCodeHarness(root=cc_root)
    sessions = cc.discover(cwd)
    ids = {s.session_id for s in sessions}
    assert ids == {"sess-aaa", "sess-bbb"}
    for s in sessions:
        assert s.cwd == cwd
        assert s.path.suffix == ".jsonl"


def test_claude_code_active_session_picks_most_recent(tmp_path):
    cc_root = tmp_path / "projects"
    cwd = tmp_path / "proj"
    cwd.mkdir()
    pdir = cc_root / _encode_cwd(cwd)
    pdir.mkdir(parents=True)

    older = pdir / "sess-old.jsonl"
    newer = pdir / "sess-new.jsonl"
    older.write_text("old\n")
    # ensure distinct mtimes across filesystems with second-precision mtime
    time.sleep(0.01)
    newer.write_text("new\n")
    os.utime(older, (time.time() - 100, time.time() - 100))

    cc = ClaudeCodeHarness(root=cc_root)
    active = cc.active_session(cwd)
    assert active is not None
    assert active.session_id == "sess-new"


def test_claude_code_active_session_none_when_empty(tmp_path):
    cc = ClaudeCodeHarness(root=tmp_path / "projects")
    assert cc.active_session(tmp_path / "no-such-cwd") is None


# ---------- Codex ----------


def test_codex_discover_walks_date_tree(tmp_path):
    root = tmp_path / "sessions"
    day = root / "2026" / "05" / "21"
    day.mkdir(parents=True)
    (day / "rollout-2026-05-21T10-30-00-abc123.jsonl").write_text("{}\n")
    (day / "rollout-2026-05-21T11-00-00-def456.jsonl").write_text("{}\n")
    # noise files shouldn't be picked up
    (day / "scratch.txt").write_text("nope")

    cx = CodexHarness(root=root)
    sessions = cx.discover(tmp_path)  # cwd ignored for codex
    ids = {s.session_id for s in sessions}
    assert ids == {"abc123", "def456"}


def test_codex_discover_empty_when_no_root(tmp_path):
    cx = CodexHarness(root=tmp_path / "does-not-exist")
    assert cx.discover(tmp_path) == []


def test_codex_active_session_picks_newest_across_days(tmp_path):
    root = tmp_path / "sessions"
    d1 = root / "2026" / "05" / "20"
    d2 = root / "2026" / "05" / "21"
    d1.mkdir(parents=True)
    d2.mkdir(parents=True)
    old = d1 / "rollout-2026-05-20T09-00-00-old111.jsonl"
    new = d2 / "rollout-2026-05-21T09-00-00-new222.jsonl"
    old.write_text("o\n")
    time.sleep(0.01)
    new.write_text("n\n")
    os.utime(old, (time.time() - 100, time.time() - 100))

    cx = CodexHarness(root=root)
    active = cx.active_session(tmp_path)
    assert active is not None
    assert active.session_id == "new222"


# ---------- append / tail semantics (the contract the mirror loop relies on) ----------


@pytest.fixture
def claude_code_with_session(tmp_path):
    """A fully-wired Claude Code env with one session file."""
    cc_root = tmp_path / "projects"
    cwd = tmp_path / "proj"
    cwd.mkdir()
    pdir = cc_root / _encode_cwd(cwd)
    pdir.mkdir(parents=True)
    sess_path = pdir / "sess-tail.jsonl"
    sess_path.write_bytes(b"")  # empty
    cc = ClaudeCodeHarness(root=cc_root)
    session = Session(path=sess_path, session_id="sess-tail", cwd=cwd)
    return cc, session


def test_read_new_bytes_returns_everything_from_zero(claude_code_with_session):
    cc, session = claude_code_with_session
    session.path.write_bytes(b'{"a":1}\n{"a":2}\n')

    out = cc.read_new_bytes(session, 0)
    assert out == b'{"a":1}\n{"a":2}\n'


def test_read_new_bytes_returns_only_appended_bytes(claude_code_with_session):
    cc, session = claude_code_with_session
    session.path.write_bytes(b'{"a":1}\n')
    first_size = cc.size(session)

    # Append two more lines
    with open(session.path, "ab") as f:
        f.write(b'{"a":2}\n{"a":3}\n')

    out = cc.read_new_bytes(session, first_size)
    assert out == b'{"a":2}\n{"a":3}\n'


def test_read_new_bytes_at_eof_returns_empty(claude_code_with_session):
    cc, session = claude_code_with_session
    session.path.write_bytes(b'{"a":1}\n')
    out = cc.read_new_bytes(session, cc.size(session))
    assert out == b""


def test_read_new_bytes_offset_beyond_eof_returns_empty(claude_code_with_session):
    cc, session = claude_code_with_session
    session.path.write_bytes(b'{"a":1}\n')
    # offset > size: seek past EOF, read returns b""
    out = cc.read_new_bytes(session, 10_000)
    assert out == b""


def test_read_new_bytes_rejects_negative_offset(claude_code_with_session):
    cc, session = claude_code_with_session
    session.path.write_bytes(b"hello")
    with pytest.raises(ValueError, match="non-negative"):
        cc.read_new_bytes(session, -1)


def test_codex_read_new_bytes_same_contract(tmp_path):
    root = tmp_path / "sessions"
    day = root / "2026" / "05" / "21"
    day.mkdir(parents=True)
    p = day / "rollout-2026-05-21T10-00-00-xyz.jsonl"
    p.write_bytes(b"line-1\nline-2\n")

    cx = CodexHarness(root=root)
    sess = Session(path=p, session_id="xyz")

    assert cx.read_new_bytes(sess, 0) == b"line-1\nline-2\n"
    assert cx.read_new_bytes(sess, 7) == b"line-2\n"
    assert cx.read_new_bytes(sess, cx.size(sess)) == b""


# ---------- mirror-loop dry run (no S3 yet — just the read side) ----------


def test_simulated_tail_produces_disjoint_parts(claude_code_with_session):
    """Simulates what the mirror loop will do: tail in batches, each batch
    becomes one part. Verifies parts are disjoint and concatenate back to
    the source bytes exactly. This is the contract D5 (replay) depends on.
    """
    cc, session = claude_code_with_session
    parts: list[bytes] = []
    offset = 0

    # Batch 1
    session.path.write_bytes(b'{"step":1}\n')
    new = cc.read_new_bytes(session, offset)
    parts.append(new)
    offset += len(new)

    # Batch 2 (append two lines)
    with open(session.path, "ab") as f:
        f.write(b'{"step":2}\n{"step":3}\n')
    new = cc.read_new_bytes(session, offset)
    parts.append(new)
    offset += len(new)

    # Batch 3 (nothing happened)
    new = cc.read_new_bytes(session, offset)
    parts.append(new)  # will be b""
    offset += len(new)

    # Batch 4 (one more line)
    with open(session.path, "ab") as f:
        f.write(b'{"step":4}\n')
    new = cc.read_new_bytes(session, offset)
    parts.append(new)

    full = session.path.read_bytes()
    assert b"".join(parts) == full
    # Empty batch is preserved as a zero-length part; the mirror loop will
    # skip those before uploading. We just verify it doesn't lose bytes.
    assert any(p == b"" for p in parts)


# ---------- OpenClaw ----------


def _make_openclaw_session(root: Path, agent_id: str, sid: str, body: bytes) -> Path:
    sess_dir = root / agent_id / "sessions"
    sess_dir.mkdir(parents=True, exist_ok=True)
    p = sess_dir / f"{sid}.jsonl"
    p.write_bytes(body)
    return p


def test_openclaw_discover_finds_sessions_across_agents(tmp_path):
    root = tmp_path / "agents"
    _make_openclaw_session(root, "main", "sess-aaa", b'{"type":"session","id":"sess-aaa"}\n')
    _make_openclaw_session(root, "worker", "sess-bbb", b'{"type":"session","id":"sess-bbb"}\n')

    oc = OpenClawHarness(root=root)
    sessions = oc.discover(tmp_path)
    ids = {s.session_id for s in sessions}
    # stable id is <agentId>__<stem>
    assert ids == {"main__sess-aaa", "worker__sess-bbb"}


def test_openclaw_excludes_sessions_json_and_tmp(tmp_path):
    root = tmp_path / "agents"
    sess_dir = root / "main" / "sessions"
    sess_dir.mkdir(parents=True)
    (sess_dir / "real.jsonl").write_bytes(b'{"type":"session"}\n')
    (sess_dir / "sessions.json").write_bytes(b'{"index":true}\n')
    (sess_dir / "store.123.abc.tmp").write_bytes(b"half-written")

    oc = OpenClawHarness(root=root)
    ids = {s.session_id for s in oc.discover(tmp_path)}
    assert ids == {"main__real"}


def test_openclaw_topic_session_caught_by_glob(tmp_path):
    root = tmp_path / "agents"
    _make_openclaw_session(root, "main", "sess-x-topic-42", b'{"type":"session"}\n')
    oc = OpenClawHarness(root=root)
    ids = {s.session_id for s in oc.discover(tmp_path)}
    assert ids == {"main__sess-x-topic-42"}


def test_openclaw_active_session_picks_most_recent(tmp_path):
    root = tmp_path / "agents"
    old = _make_openclaw_session(root, "main", "old", b"o\n")
    time.sleep(0.01)
    _make_openclaw_session(root, "main", "new", b"n\n")
    os.utime(old, (time.time() - 100, time.time() - 100))
    oc = OpenClawHarness(root=root)
    active = oc.active_session(tmp_path)
    assert active is not None and active.session_id == "main__new"


def test_openclaw_read_new_tail_semantics(tmp_path):
    root = tmp_path / "agents"
    p = _make_openclaw_session(root, "main", "s", b"line1\n")
    oc = OpenClawHarness(root=root)
    sess = Session(path=p, session_id="main__s")
    data, cur = oc.read_new(sess, 0)
    assert data == b"line1\n" and cur == 6
    with open(p, "ab") as f:
        f.write(b"line2\n")
    data2, cur2 = oc.read_new(sess, cur)
    assert data2 == b"line2\n" and cur2 == 12


def test_openclaw_state_dir_env_override(tmp_path, monkeypatch):
    custom = tmp_path / "custom-state"
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(custom))
    _make_openclaw_session(custom / "agents", "main", "s", b"x\n")
    oc = OpenClawHarness()  # no explicit root → must resolve from env
    ids = {s.session_id for s in oc.discover(tmp_path)}
    assert ids == {"main__s"}


def test_openclaw_empty_when_no_root(tmp_path):
    oc = OpenClawHarness(root=tmp_path / "nope")
    assert oc.discover(tmp_path) == []
    assert oc.active_session(tmp_path) is None


# ---------- Hermes (SQLite) ----------

# Minimal subset of Hermes' real schema (verified against hermes_state.py).
_HERMES_SCHEMA = """
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    model TEXT,
    started_at REAL NOT NULL,
    ended_at REAL,
    title TEXT
);
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT,
    tool_calls TEXT,
    tool_name TEXT,
    timestamp REAL NOT NULL,
    token_count INTEGER
);
CREATE TABLE schema_version (version INTEGER NOT NULL);
"""


def _make_hermes_db(path: Path, sessions, messages):
    """sessions: list[(id, source, model, started_at, title)];
    messages: list[(session_id, role, content, timestamp)]."""
    conn = sqlite3.connect(str(path))
    conn.executescript(_HERMES_SCHEMA)
    conn.execute("INSERT INTO schema_version (version) VALUES (13)")
    for sid, source, model, started, title in sessions:
        conn.execute(
            "INSERT INTO sessions (id, source, model, started_at, title) VALUES (?,?,?,?,?)",
            (sid, source, model, started, title),
        )
    for sess_id, role, content, ts in messages:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?,?,?,?)",
            (sess_id, role, content, ts),
        )
    conn.commit()
    conn.close()


def test_hermes_discover_lists_sessions(tmp_path):
    db = tmp_path / "state.db"
    _make_hermes_db(
        db,
        sessions=[
            ("20260529_010101_aaa111", "cli", "hermes-4", 100.0, "first"),
            ("20260529_020202_bbb222", "gateway", "hermes-4", 200.0, "second"),
        ],
        messages=[],
    )
    h = HermesHarness(db_path=db)
    sessions = h.discover(tmp_path)
    ids = {s.session_id for s in sessions}
    assert ids == {"20260529_010101_aaa111", "20260529_020202_bbb222"}
    # all point at the same DB file
    assert all(s.path == db for s in sessions)


def test_hermes_read_new_synthesizes_jsonl_and_advances_rowid(tmp_path):
    db = tmp_path / "state.db"
    sid = "20260529_010101_aaa111"
    _make_hermes_db(
        db,
        sessions=[(sid, "cli", "hermes-4", 100.0, "t")],
        messages=[
            (sid, "user", "hello", 100.1),
            (sid, "assistant", "hi there", 100.2),
        ],
    )
    h = HermesHarness(db_path=db)
    sess = Session(path=db, session_id=sid)

    # size() == max messages.id == 2
    assert h.size(sess) == 2

    data, cursor = h.read_new(sess, 0)
    assert cursor == 2
    lines = data.decode().strip().split("\n")
    assert len(lines) == 2
    import json as _json

    first = _json.loads(lines[0])
    assert first["role"] == "user"
    assert first["content"] == "hello"
    assert first["id"] == 1

    # Reading again from the advanced cursor yields nothing.
    data2, cursor2 = h.read_new(sess, cursor)
    assert data2 == b"" and cursor2 == 2


def test_hermes_read_new_only_new_rows(tmp_path):
    db = tmp_path / "state.db"
    sid = "20260529_010101_aaa111"
    _make_hermes_db(
        db,
        sessions=[(sid, "cli", "hermes-4", 100.0, "t")],
        messages=[(sid, "user", "one", 100.1)],
    )
    h = HermesHarness(db_path=db)
    sess = Session(path=db, session_id=sid)
    _, cursor = h.read_new(sess, 0)
    assert cursor == 1

    # Append a second message
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?,?,?,?)",
        (sid, "assistant", "two", 100.2),
    )
    conn.commit()
    conn.close()

    data, cursor2 = h.read_new(sess, cursor)
    assert cursor2 == 2
    import json as _json

    rows = [_json.loads(line) for line in data.decode().strip().split("\n")]
    assert len(rows) == 1
    assert rows[0]["content"] == "two"


def test_hermes_decodes_multimodal_content_prefix(tmp_path):
    db = tmp_path / "state.db"
    sid = "20260529_010101_aaa111"
    # Hermes stores multimodal content as '\x00json:<json>'
    payload = '\x00json:[{"type":"text","text":"hi"}]'
    _make_hermes_db(
        db,
        sessions=[(sid, "cli", "hermes-4", 100.0, "t")],
        messages=[(sid, "user", payload, 100.1)],
    )
    h = HermesHarness(db_path=db)
    sess = Session(path=db, session_id=sid)
    data, _ = h.read_new(sess, 0)
    import json as _json

    row = _json.loads(data.decode().strip())
    # content should be decoded back into a list, not the sentinel string
    assert isinstance(row["content"], list)
    assert row["content"][0]["text"] == "hi"


def test_hermes_active_session_is_one_with_highest_message(tmp_path):
    db = tmp_path / "state.db"
    s1, s2 = "20260529_010101_aaa", "20260529_020202_bbb"
    _make_hermes_db(
        db,
        sessions=[(s1, "cli", "m", 100.0, "a"), (s2, "cli", "m", 200.0, "b")],
        messages=[(s1, "user", "x", 100.1), (s2, "user", "y", 200.1), (s1, "user", "z", 201.0)],
    )
    h = HermesHarness(db_path=db)
    # s1 owns the highest message id (the last insert), so it's "active"
    active = h.active_session(tmp_path)
    assert active is not None and active.session_id == s1


def test_hermes_missing_db_is_empty(tmp_path):
    h = HermesHarness(db_path=tmp_path / "nope.db")
    assert h.discover(tmp_path) == []
    assert h.active_session(tmp_path) is None
    sess = Session(path=tmp_path / "nope.db", session_id="x")
    assert h.size(sess) == 0
    assert h.read_new(sess, 0) == (b"", 0)


def test_hermes_read_new_rejects_negative_cursor(tmp_path):
    db = tmp_path / "state.db"
    _make_hermes_db(db, sessions=[("s", "cli", "m", 1.0, "t")], messages=[])
    h = HermesHarness(db_path=db)
    sess = Session(path=db, session_id="s")
    with pytest.raises(ValueError, match="non-negative"):
        h.read_new(sess, -1)
