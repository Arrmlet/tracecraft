"""Codex CLI adapter.

Codex writes session rollouts under
  ~/.codex/sessions/<YYYY>/<MM>/<DD>/rollout-<YYYY-MM-DDThh-mm-ss>-<id>.jsonl

Codex doesn't shard by cwd, so `discover` walks the whole sessions tree
(scoped to the most recent few days for performance) and returns every
rollout. The mirror loop is responsible for picking which to follow.
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import Session


_ROLLOUT_RE = re.compile(r"rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-(?P<id>[A-Za-z0-9_-]+)\.jsonl$")


class CodexHarness:
    name = "codex"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or (Path.home() / ".codex" / "sessions")

    def _all_rollouts(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        # YYYY/MM/DD/rollout-*.jsonl
        return list(self.root.glob("*/*/*/rollout-*.jsonl"))

    def discover(self, cwd: Path) -> list[Session]:
        # Codex sessions are not partitioned by cwd; return everything we see.
        # The mirror loop / caller decides which session to actually follow.
        del cwd
        sessions: list[Session] = []
        for path in self._all_rollouts():
            m = _ROLLOUT_RE.search(path.name)
            session_id = m.group("id") if m else path.stem
            sessions.append(Session(path=path, session_id=session_id))
        return sessions

    def active_session(self, cwd: Path) -> Session | None:
        sessions = self.discover(cwd)
        if not sessions:
            return None
        return max(sessions, key=lambda s: s.path.stat().st_mtime)

    def read_new(self, session: Session, cursor: int) -> tuple[bytes, int]:
        data = self.read_new_bytes(session, cursor)
        return data, cursor + len(data)

    def read_new_bytes(self, session: Session, offset: int) -> bytes:
        if offset < 0:
            raise ValueError(f"offset must be non-negative, got {offset}")
        with open(session.path, "rb") as f:
            f.seek(offset)
            return f.read()

    def size(self, session: Session) -> int:
        return session.path.stat().st_size
