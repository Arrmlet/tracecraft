"""Harness protocol — the only contract a new coding-agent adapter needs to meet."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Session:
    """A discovered session: where it lives and what we call it."""

    path: Path
    session_id: str
    cwd: Path | None = None  # the project dir this session ran in, if knowable


@runtime_checkable
class Harness(Protocol):
    """Minimum surface a harness adapter must expose.

    Concrete harnesses are instantiated with no arguments; per-call context
    (cwd, session id, byte offset) is passed in. State belongs to the mirror
    loop, not the harness — adapters stay stateless and easy to test.
    """

    name: str

    def discover(self, cwd: Path) -> list[Session]:
        """Return every session this harness knows about for the given cwd.

        Implementations should be cheap to call repeatedly (the mirror loop
        polls); avoid network and avoid loading file contents.
        """
        ...

    def active_session(self, cwd: Path) -> Session | None:
        """Return the most recently active session for cwd, or None."""
        ...

    def read_new(self, session: Session, cursor: int) -> tuple[bytes, int]:
        """Return (new_jsonl_bytes, new_cursor) for everything after `cursor`.

        `cursor` is an opaque per-harness position. For file-backed harnesses
        it's a byte offset and the returned cursor is `offset + len(bytes)`.
        For SQLite (Hermes) it's a rowid and the returned cursor is the max
        rowid read; the bytes are synthesized JSONL of the new rows.

        Returning the new cursor alongside the bytes makes advancement
        race-free: the loop advances to exactly what was consumed, never to a
        separately-sampled `size()` that may have moved between calls.
        """
        ...

    def read_new_bytes(self, session: Session, offset: int) -> bytes:
        """Back-compat: bytes-only view of read_new(). Prefer read_new()."""
        ...

    def size(self, session: Session) -> int:
        """Return the current end-of-stream cursor for `session`.

        Used only for the cheap "is there anything new?" pre-check. The
        authoritative advancement comes from read_new()'s returned cursor.
        For file-backed harnesses this is `path.stat().st_size`; for SQLite
        it's the current max rowid.
        """
        ...
