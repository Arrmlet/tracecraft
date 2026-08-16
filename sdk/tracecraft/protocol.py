"""Shared bucket-protocol helpers: key formats, reserved names, cursors, state.

The bucket layout is a cross-invocation protocol — keys written by one command
are parsed by another, possibly on a different machine, possibly months later.
Everything that writes or interprets that layout lives here so a format change
is a one-file change, and so CLI modules never have to import each other.
This module must not import from tracecraft.cli.
"""

import time
import uuid
from datetime import datetime, timezone

import click


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ---------- reserved names / leaf hygiene ----------

# Leaves starting with '_' are bookkeeping, never data (e.g. the read cursor
# below). Nested paths under a data prefix are junk (e.g. written by a
# pre-validation client) — never data either. Every reader of a data prefix
# must apply this rule, or junk can masquerade as mail/history AND poison
# cursors (a nested key sorts above all timestamped leaves).
CURSOR_LEAF = "_cursor.json"


def is_data_leaf(leaf):
    return bool(leaf) and "/" not in leaf and not leaf.startswith("_")


def direct_children(keys, prefix):
    """Only data leaves directly under prefix."""
    return [k for k in keys if is_data_leaf(k[len(prefix) :])]


# ---------- append-key scheme ----------
# <prefix><ts_ns>_<agent>_<uuid8>.json
#
# Append keys MUST be unique per write: a whole-second timestamp collides when
# one writer fires twice in the same second and the later write silently
# overwrites the earlier (measured: a 5-message burst kept only 1). Nanosecond
# resolution gives chronological lexicographic order (constant 19-digit width
# until the year 2286); the uuid suffix guarantees uniqueness even on clock
# ties. Both messaging and memory history write this format, and the cursor
# machinery parses it back — keep writer and parsers in this file together.


def append_key(prefix, agent_id):
    return f"{prefix}{time.time_ns()}_{agent_id}_{uuid.uuid4().hex[:8]}.json"


def key_ts_ns(key, prefix):
    """The embedded timestamp, or None if the leaf doesn't conform."""
    head = key[len(prefix) :].split("_", 1)[0]
    return int(head) if head.isdigit() else None


def key_sender(key, prefix):
    """The embedded writer id, or None if the leaf doesn't conform.

    Lets readers skip a GET when they only need the sender (agent ids may
    themselves contain underscores; ts and uuid8 anchor the two ends).
    """
    leaf = key[len(prefix) :]
    if not leaf.endswith(".json"):
        return None
    parts = leaf.removesuffix(".json").split("_")
    if len(parts) < 3 or not parts[0].isdigit():
        return None
    return "_".join(parts[1:-1])


# ---------- step ids ----------


def normalize_step_id(step_id):
    """Step ids map to exactly one key segment: steps/<sid>/....

    A '/' would nest a phantom step that key-layout readers (status, listings)
    misparse; rejecting it here covers every command that takes a step id.
    """
    sid = step_id.lower().replace(".", "-")
    if not sid.strip():
        raise click.ClickException("Step id cannot be empty")
    if "/" in sid:
        raise click.ClickException("Step ids may not contain '/'")
    return sid


# ---------- read cursors (inbox --new) ----------

# Message keys are stamped from the SENDER's clock before upload, so keys can
# land out of order (slow/retried PUT, cross-host clock skew). A strict
# "start after the newest key I saw" cursor would skip those forever. Instead
# the cursor keeps a grace window: each --new read re-lists the last
# CURSOR_GRACE_NS of keys and dedupes against the bounded `seen` list, so a
# late-landing message is still delivered as long as its timestamp is within
# the window. Arrivals more than the grace window out of order are the
# documented limit of --new (a plain read always shows everything).
CURSOR_GRACE_NS = 300 * 1_000_000_000  # 5 minutes
SEEN_CAP = 1000  # bounds cursor size; ~minutes of backlog at any sane rate


def cursor_key(agent_id):
    return f"messages/{agent_id}/{CURSOR_LEAF}"


def load_stream_cursor(cursor_doc, name):
    """Read one stream's cursor ({watermark, seen}); tolerates the bare-key
    form (the format issue #15 originally described) or any malformed value
    by degrading to a full re-list (at-least-once)."""
    v = (cursor_doc or {}).get(name)
    if isinstance(v, str):
        return {"watermark": v, "seen": []}
    if isinstance(v, dict):
        seen = v.get("seen")
        return {
            "watermark": v.get("watermark"),
            "seen": [k for k in seen if isinstance(k, str)] if isinstance(seen, list) else [],
        }
    return {"watermark": None, "seen": []}


def unseen_keys(listed, stream):
    """Keys from a listing that this stream cursor hasn't shown yet."""
    seen = set(stream["seen"])
    wm = stream["watermark"]
    return [k for k in listed if (wm is None or k > wm) and k not in seen]


def advance_stream(stream, listed, prefix):
    """Next stream cursor after a read that listed `listed` (all keys seen in
    the listing, shown or deduped). Watermark trails the newest timestamp by
    the grace window and never regresses; `seen` holds every known key above
    the watermark so grace-window re-lists don't re-show."""
    if not listed:
        return stream

    known = sorted(set(stream["seen"]) | set(listed))
    timestamps = [t for k in listed if (t := key_ts_ns(k, prefix)) is not None]
    if not timestamps:
        return {"watermark": stream["watermark"], "seen": known[-SEEN_CAP:]}

    horizon = max(timestamps) - CURSOR_GRACE_NS
    watermark = f"{prefix}{horizon}" if horizon > 0 else None
    if stream["watermark"] and (watermark is None or watermark < stream["watermark"]):
        watermark = stream["watermark"]
    seen = [k for k in known if watermark is None or k > watermark]
    return {"watermark": watermark, "seen": seen[-SEEN_CAP:]}


# ---------- step state ----------


def effective_status(store, sid):
    """Resolve a step's status, tolerating the claim/status crash window.

    claim.json (atomic) and status.json are two separate writes; a crash
    between them leaves a claim with no status. Readers treat that state as
    in_progress by the claiming agent — the claim is the authoritative write.
    Returns (status, agent); status is 'pending' when neither file exists.
    """
    data = store.get_json(f"steps/{sid}/status.json")
    if data is not None:
        return data.get("status", "unknown"), data.get("agent", "?")
    claim_doc = store.get_json(f"steps/{sid}/claim.json")
    if claim_doc is not None:
        return "in_progress", claim_doc.get("agent", "?")
    return "pending", None


def effective_status_from_listing(store, sid, present):
    """Same resolution when a listing already proves which files exist —
    skips GETs guaranteed to 404 (one per pending/crash-window step).
    `present` is the set of keys from a `steps/` listing. Same LIST→GET race
    class as effective_status's GET→GET; the crash-window invariant holds.
    """
    if f"steps/{sid}/status.json" in present:
        data = store.get_json(f"steps/{sid}/status.json")
        if data is not None:
            return data.get("status", "unknown"), data.get("agent", "?")
    if f"steps/{sid}/claim.json" in present:
        claim_doc = store.get_json(f"steps/{sid}/claim.json")
        if claim_doc is not None:
            return "in_progress", claim_doc.get("agent", "?")
    return "pending", None


# ---------- agents ----------

STALE_AFTER_S = 300  # heartbeat older than this and the agent reads as stale


def heartbeat_age_s(heartbeat, now):
    if not heartbeat:
        return None
    try:
        return max(0, int((now - datetime.fromisoformat(heartbeat)).total_seconds()))
    except (ValueError, TypeError):
        return None


def collect_agents(store, now=None):
    """All registered agents with heartbeat age and the shared staleness rule
    applied — so every view (agents, status) agrees on who is stale."""
    now = now or datetime.now(timezone.utc)
    out = []
    for k in store.list_keys("agents/"):
        if not k.endswith(".json"):
            continue
        d = store.get_json(k)
        if not d:
            continue
        age = heartbeat_age_s(d.get("heartbeat"), now)
        status = d.get("status", "unknown")
        if age is not None and age > STALE_AFTER_S:
            status = "stale"
        out.append(
            {
                "id": d.get("id", "?"),
                "status": status,
                "step": d.get("step"),
                "heartbeat": d.get("heartbeat"),
                "heartbeat_age_s": age,
            }
        )
    return out


# ---------- sessions ----------


def session_totals(store):
    """Aggregate all mirrored sessions' meta.json docs."""
    metas = [
        m
        for k in store.list_keys("sessions/")
        if k.endswith("/meta.json") and (m := store.get_json(k))
    ]
    return {
        "count": len(metas),
        "total_uploaded_bytes": sum(m.get("total_uploaded_bytes", 0) for m in metas),
        "last_uploaded_at": max(
            (m["last_uploaded_at"] for m in metas if m.get("last_uploaded_at")), default=None
        ),
    }
