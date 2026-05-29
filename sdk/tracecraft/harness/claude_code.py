"""Claude Code adapter.

Claude Code persists every session under
  ~/.claude/projects/<encoded-cwd>/<session-id>.jsonl

`<encoded-cwd>` replaces path separators with hyphens and prefixes a leading
hyphen, e.g. `/Users/x/proj` -> `-Users-x-proj`. We mirror that encoding here
so we can find the right project directory for the user's current cwd.
"""

from __future__ import annotations

import os
from pathlib import Path

from .base import FileTailHarness, Session


def _encode_cwd(cwd: Path) -> str:
    """Encode an absolute path the way Claude Code does for its projects dir.

    Claude Code uses the resolved absolute path with `/` swapped for `-`,
    keeping the leading separator's effect (so `/foo/bar` -> `-foo-bar`).
    """
    resolved = cwd.expanduser().resolve()
    return str(resolved).replace(os.sep, "-")


class ClaudeCodeHarness(FileTailHarness):
    name = "claude-code"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or (Path.home() / ".claude" / "projects")

    def _project_dir(self, cwd: Path) -> Path:
        return self.root / _encode_cwd(cwd)

    def discover(self, cwd: Path) -> list[Session]:
        pdir = self._project_dir(cwd)
        if not pdir.is_dir():
            return []
        return [
            Session(path=jsonl, session_id=jsonl.stem, cwd=cwd)
            for jsonl in pdir.glob("*.jsonl")
        ]
