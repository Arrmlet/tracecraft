"""Harness adapters — each one knows how to find and read sessions from a
specific coding agent (Claude Code, Codex, OpenClaw, Pi, OpenCode, Hermes, …).

The base `Harness` protocol is intentionally tiny: discover sessions, parse a
session id from a path, and return the new bytes since a known offset. The
mirror loop in `tracecraft session mirror` is harness-agnostic.

Adding a new harness should be a single file under this package plus one entry
in `REGISTRY` below.
"""

from .base import Harness, Session
from .claude_code import ClaudeCodeHarness
from .codex import CodexHarness
from .hermes import HermesHarness
from .openclaw import OpenClawHarness

REGISTRY: dict[str, type[Harness]] = {
    ClaudeCodeHarness.name: ClaudeCodeHarness,
    CodexHarness.name: CodexHarness,
    OpenClawHarness.name: OpenClawHarness,
    HermesHarness.name: HermesHarness,
}


def get_harness(name: str) -> Harness:
    if name not in REGISTRY:
        known = ", ".join(sorted(REGISTRY)) or "(none registered)"
        raise ValueError(f"unknown harness '{name}'. Known: {known}")
    return REGISTRY[name]()


__all__ = [
    "Harness",
    "Session",
    "ClaudeCodeHarness",
    "CodexHarness",
    "OpenClawHarness",
    "HermesHarness",
    "REGISTRY",
    "get_harness",
]
