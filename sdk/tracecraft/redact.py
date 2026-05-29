"""Redaction v0 — regex denylist applied before bytes leave the machine.

Goal: catch the obvious shapes of credentials and tokens in trace data so that
users mirroring sessions to a bucket don't accidentally publish keys. This is
NOT a real DLP system — it cannot catch arbitrary secrets, custom internal
token formats, or business-logic data. It catches well-known token shapes.

Every redaction is *counted*, never silent. Counts go into meta.json so users
can audit what was scrubbed.
"""

from __future__ import annotations

import re
from typing import Final

# Each (name, pattern) — name is what shows up in meta.json's redaction counter.
# Patterns intentionally on the strict side: prefer false-negative over false-positive
# (we'd rather miss a token than mangle source code that happens to look like one).
_PATTERNS: Final[list[tuple[str, re.Pattern[bytes]]]] = [
    ("aws_access_key", re.compile(rb"AKIA[0-9A-Z]{16}")),
    ("aws_session_token", re.compile(rb"ASIA[0-9A-Z]{16}")),
    ("anthropic_key", re.compile(rb"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai_key", re.compile(rb"sk-(?:proj-|svcacct-)?[A-Za-z0-9]{20,}")),
    ("hf_token", re.compile(rb"hf_[A-Za-z0-9]{30,}")),
    ("github_pat", re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}")),
    ("slack_token", re.compile(rb"xox[abprs]-[A-Za-z0-9-]{10,}")),
    ("bearer_token", re.compile(rb"Bearer\s+[A-Za-z0-9_.\-]{20,}")),
]


def redact(blob: bytes) -> tuple[bytes, dict[str, int]]:
    """Return (redacted_bytes, counts).

    counts maps pattern_name -> number of replacements made. Patterns not
    matched are absent from the dict (no zero entries).
    """
    counts: dict[str, int] = {}
    out = blob
    for name, pat in _PATTERNS:
        out, n = pat.subn(f"[REDACTED:{name}]".encode(), out)
        if n:
            counts[name] = n
    return out, counts


def merge_counts(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
    """Sum two redaction-count dicts. Used to accumulate across parts in meta.json."""
    out = dict(a)
    for k, v in b.items():
        out[k] = out.get(k, 0) + v
    return out
