"""Claude Code adapter.

Claude Code persists every session under
  ~/.claude/projects/<encoded-cwd>/<session-id>.jsonl

`<encoded-cwd>` replaces path separators with hyphens and prefixes a leading
hyphen, e.g. `/Users/x/proj` -> `-Users-x-proj`. We mirror that encoding here
so we can find the right project directory for the user's current cwd.
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import FileTailHarness, Session


def _encode_cwd(cwd: Path) -> str:
    """Encode an absolute path the way Claude Code does for its projects dir.

    Claude Code sanitizes the resolved absolute path into a safe directory name
    by replacing the path separator AND other non-alphanumeric punctuation with
    `-`. Critically that includes `_` and `.`, so `/Users/x/my_proj.v2` becomes
    `-Users-x-my-proj-v2`. We mirror that here — replacing only `/` (the old
    behavior) silently fails to find sessions for any cwd containing `_` or `.`.
    """
    resolved = str(cwd.expanduser().resolve())
    # Replace every run of non-alphanumeric chars with a single hyphen, matching
    # Claude Code's slugify. Leading separator becomes a leading hyphen.
    return re.sub(r"[^A-Za-z0-9]+", "-", resolved)


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
            Session(path=jsonl, session_id=jsonl.stem, cwd=cwd) for jsonl in pdir.glob("*.jsonl")
        ]
