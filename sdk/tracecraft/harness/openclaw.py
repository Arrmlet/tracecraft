"""OpenClaw adapter.

OpenClaw persists session transcripts as append-only JSONL under
  <stateDir>/agents/<agentId>/sessions/<sessionId>.jsonl

where <stateDir> resolves (highest precedence first):
  OPENCLAW_STATE_DIR  →  OPENCLAW_HOME  →  ~/.openclaw
(--dev and --profile <name> map to ~/.openclaw-dev / ~/.openclaw-<name>; a
caller using those can pass root= explicitly.)

Verified against OpenClaw source (src/config/sessions/paths.ts) May 2026.

Files in the sessions dir that are NOT transcripts and must be skipped:
  - sessions.json          mutable session index, rewritten atomically
  - *.tmp                  half-written atomic-store staging files

Topic sessions are named  <sessionId>-topic-<topicId>.jsonl  and compaction
successors  <sessionId>.checkpoint.<uuid>.jsonl  — both are real transcripts
and we surface them as-is. Session ids are only unique within an agentId, so
the stable key we expose is  <agentId>/<filename-stem>.
"""

from __future__ import annotations

import os
from pathlib import Path

from .base import FileTailHarness, Session


def _resolve_state_dir() -> Path:
    """OpenClaw state dir, honoring its env-var precedence."""
    if os.environ.get("OPENCLAW_STATE_DIR"):
        return Path(os.environ["OPENCLAW_STATE_DIR"])
    if os.environ.get("OPENCLAW_HOME"):
        return Path(os.environ["OPENCLAW_HOME"])
    return Path.home() / ".openclaw"


class OpenClawHarness(FileTailHarness):
    name = "openclaw"

    def __init__(self, root: Path | None = None) -> None:
        # `root` is the agents dir. Default derives from the active state dir.
        self.root = root or (_resolve_state_dir() / "agents")

    def _stable_id(self, path: Path) -> str:
        """<agentId>__<stem> — agentId is the dir between 'agents/' and 'sessions/'.

        Joined with '__' (not '/') so the id is safe as a single bucket-key
        path segment; OpenClaw sessionIds are only unique within an agentId,
        so the agentId prefix disambiguates across agents.
        """
        stem = path.stem  # filename without .jsonl
        # path = <root>/<agentId>/sessions/<file>.jsonl
        try:
            agent_id = path.parent.parent.name
        except Exception:
            agent_id = "unknown"
        return f"{agent_id}__{stem}"

    def _all_sessions(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        out: list[Path] = []
        for p in self.root.glob("*/sessions/*.jsonl"):
            name = p.name
            if name == "sessions.json" or name.endswith(".tmp"):
                continue
            out.append(p)
        return out

    def discover(self, cwd: Path) -> list[Session]:
        # OpenClaw shards by agentId, not cwd — cwd is ignored.
        del cwd
        return [Session(path=p, session_id=self._stable_id(p)) for p in self._all_sessions()]
