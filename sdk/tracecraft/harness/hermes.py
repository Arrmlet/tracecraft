"""Hermes Agent adapter (Nous Research).

Hermes moved off per-session JSONL to a single SQLite database:
  ~/.hermes/state.db   (or $HERMES_HOME/state.db), WAL mode

So this adapter does NOT tail a file. It opens the DB read-only and reads new
rows from the `messages` table, synthesizing one JSON line per message. The
mirror loop treats the synthesized bytes exactly like a file tail.

Cursor semantics (the reason base.Harness decoupled cursor from byte count):
  cursor == the highest `messages.id` already mirrored.
  messages.id is INTEGER PRIMARY KEY AUTOINCREMENT — strictly increasing,
  never reused even after Hermes prunes old sessions, so it's a safe
  high-water mark. We read `WHERE session_id=? AND id>:cursor ORDER BY id`.

Verified against hermes_state.py (github.com/NousResearch/hermes-agent) May 2026:
  - sessions(id TEXT PK, source, model, started_at REAL, ended_at, title, ...)
  - messages(id INTEGER PK AUTOINCREMENT, session_id TEXT FK, role, content,
             tool_calls, tool_name, timestamp REAL, token_count, ...)
  - content may be sentinel-prefixed '\\x00json:' for multimodal payloads.
  - schema_version table; columns can be added across versions, so we read
    whatever columns exist rather than a hardcoded list.

Safety: open with mode=ro (NOT immutable — the DB is live). A short
busy_timeout rides out the brief moments Hermes holds the write lock. We never
write or checkpoint.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from .base import Session

# Sentinel Hermes uses to mark a JSON-encoded (multimodal) content payload.
_CONTENT_JSON_PREFIX = "\x00json:"
_BUSY_TIMEOUT_MS = 4000


def _resolve_db_path() -> Path:
    home = os.environ.get("HERMES_HOME")
    base = Path(home) if home else (Path.home() / ".hermes")
    return base / "state.db"


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    """Read-only connection safe to use against a live WAL database."""
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=_BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    return conn


def _decode_content(value):
    """Hermes stores multimodal content as '\\x00json:<json>'; scalars as-is."""
    if isinstance(value, str) and value.startswith(_CONTENT_JSON_PREFIX):
        try:
            return json.loads(value[len(_CONTENT_JSON_PREFIX):])
        except json.JSONDecodeError:
            return value
    return value


class HermesHarness:
    name = "hermes"

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or _resolve_db_path()

    # ---- discovery ----

    def discover(self, cwd: Path) -> list[Session]:
        # Hermes sessions aren't keyed by cwd. We surface every session row;
        # session.path is the DB (shared by all sessions), session_id is the
        # sessions.id TEXT value.
        del cwd
        if not self.db_path.exists():
            return []
        conn = _connect_ro(self.db_path)
        try:
            rows = conn.execute(
                "SELECT id FROM sessions ORDER BY started_at DESC"
            ).fetchall()
        except sqlite3.Error:
            return []
        finally:
            conn.close()
        return [Session(path=self.db_path, session_id=r["id"]) for r in rows]

    def active_session(self, cwd: Path) -> Session | None:
        if not self.db_path.exists():
            return None
        conn = _connect_ro(self.db_path)
        try:
            row = conn.execute(
                # Most-recently-active = the session owning the highest message id.
                "SELECT session_id FROM messages ORDER BY id DESC LIMIT 1"
            ).fetchone()
        except sqlite3.Error:
            row = None
        finally:
            conn.close()
        if not row:
            # Fall back to newest session even if it has no messages yet.
            sessions = self.discover(cwd)
            return sessions[0] if sessions else None
        return Session(path=self.db_path, session_id=row["session_id"])

    # ---- read ----

    def size(self, session: Session) -> int:
        """Current max messages.id for this session — the cursor high-water."""
        if not self.db_path.exists():
            return 0
        conn = _connect_ro(self.db_path)
        try:
            row = conn.execute(
                "SELECT MAX(id) AS m FROM messages WHERE session_id = ?",
                (session.session_id,),
            ).fetchone()
        except sqlite3.Error:
            return 0
        finally:
            conn.close()
        return int(row["m"]) if row and row["m"] is not None else 0

    def read_new(self, session: Session, cursor: int) -> tuple[bytes, int]:
        """Synthesize JSONL for messages with id > cursor; return (bytes, new_cursor)."""
        if cursor < 0:
            raise ValueError(f"cursor must be non-negative, got {cursor}")
        if not self.db_path.exists():
            return b"", cursor
        conn = _connect_ro(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? AND id > ? ORDER BY id ASC",
                (session.session_id, cursor),
            ).fetchall()
        except sqlite3.Error:
            return b"", cursor
        finally:
            conn.close()

        lines: list[str] = []
        max_id = cursor
        for r in rows:
            d = dict(r)
            if "content" in d:
                d["content"] = _decode_content(d["content"])
            # tool_calls / reasoning_details are JSON strings; leave as-is —
            # consumers can parse. We just emit the row faithfully.
            lines.append(json.dumps(d, default=str, ensure_ascii=False))
            if d.get("id") is not None:
                max_id = max(max_id, int(d["id"]))

        blob = ("\n".join(lines) + "\n").encode("utf-8") if lines else b""
        return blob, max_id

    def read_new_bytes(self, session: Session, offset: int) -> bytes:
        return self.read_new(session, offset)[0]
