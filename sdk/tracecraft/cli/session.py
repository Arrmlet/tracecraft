"""`tracecraft session` — mirror, list, show, stop.

Commands:
    mirror   Pull new bytes from a harness session into the bucket (one-shot).
    list     Browse sessions in the bucket.
    show     Inspect one session's meta + tail.
    stop     Clear local state for a session (placeholder; no daemon yet).

Bucket layout (additive — does not touch existing tracecraft keys):

    <project>/sessions/<harness>/<session-id>/
        part-NNNNN-<uuid8>.jsonl   ← one per mirror flush, append-disjoint
        meta.json                  ← cumulative metadata + redaction counts

State files live under ~/.tracecraft/mirror-state/<sid>.json and store the
byte offset into the source JSONL. Next-seq is derived from a bucket LIST
on every call, so losing the state file is recoverable.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import click

from tracecraft.harness import REGISTRY, get_harness
from tracecraft.redact import merge_counts, redact
from tracecraft.store import get_store


# Driven by the harness REGISTRY so adding an adapter auto-extends the CLI.
HARNESS_CHOICES = sorted(REGISTRY)
STATE_DIR = Path.home() / ".tracecraft" / "mirror-state"
PART_RE = re.compile(r"part-(\d{5})-[a-f0-9]{8}\.jsonl$")


# ---------- helpers ----------


def _state_path(session_id: str) -> Path:
    return STATE_DIR / f"{session_id}.json"


def _load_state(session_id: str) -> dict:
    p = _state_path(session_id)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        # Corrupt state file — treat as missing rather than crash.
        return {}


def _save_state(session_id: str, state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _state_path(session_id).write_text(json.dumps(state, indent=2))


def _session_prefix(harness_name: str, session_id: str) -> str:
    return f"sessions/{harness_name}/{session_id}/"


def _next_seq_for(store, harness_name: str, session_id: str) -> int:
    """Find the next unused part-NNNNN seq by listing the bucket."""
    prefix = _session_prefix(harness_name, session_id)
    keys = store.list_keys(prefix)
    seqs: list[int] = []
    for k in keys:
        name = k.rsplit("/", 1)[-1]
        m = PART_RE.match(name)
        if m:
            seqs.append(int(m.group(1)))
    return (max(seqs) + 1) if seqs else 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- group ----------


@click.group()
def session():
    """Mirror, browse, and inspect coding-agent sessions."""


# ---------- mirror ----------


@session.command("mirror")
@click.option(
    "--harness",
    "harness_name",
    required=True,
    type=click.Choice(HARNESS_CHOICES),
    help="Which coding agent's session format to read.",
)
@click.option(
    "--session-id",
    default=None,
    help="Explicit session id. If omitted, picks the most recently modified session for --cwd.",
)
@click.option(
    "--cwd",
    "cwd_str",
    default=None,
    help="Project directory the session ran in (claude-code only). Defaults to $PWD.",
)
@click.option(
    "--no-redact", is_flag=True, help="Skip redaction. Use only on fully-trusted buckets."
)
@click.option(
    "--min-bytes",
    default=1,
    type=int,
    show_default=True,
    help="Skip upload if fewer than this many new bytes are available.",
)
def mirror(harness_name, session_id, cwd_str, no_redact, min_bytes):
    """Pull new bytes from a harness session into the bucket (one-shot).

    Reads from the last known byte offset (or 0 on first run), applies regex
    redaction unless --no-redact, uploads the chunk as a new part object, and
    updates the session's meta.json. Idempotent and safe to re-run on a cron.
    """
    store, cfg = get_store()
    harness = get_harness(harness_name)
    cwd = Path(cwd_str).expanduser().resolve() if cwd_str else Path.cwd()

    # 1. Find the session
    if session_id:
        candidates = [s for s in harness.discover(cwd) if s.session_id == session_id]
        sess = candidates[0] if candidates else None
    else:
        sess = harness.active_session(cwd)

    if sess is None:
        raise click.ClickException(
            f"No {harness_name} session found"
            + (f" for id={session_id}" if session_id else f" in cwd={cwd}")
        )

    state = _load_state(sess.session_id)
    # `cursor` is an opaque per-harness position: a byte offset for file-backed
    # harnesses (claude-code, codex, openclaw), a rowid for SQLite (hermes).
    # The mirror loop never assumes it equals a byte count.
    cursor = state.get("cursor", 0)

    # Cheap pre-check: is there plausibly anything new? size() is sampled, not
    # authoritative — read_new() returns the real consumed cursor below.
    cur_size = harness.size(sess)
    if cur_size - cursor < min_bytes:
        click.echo(f"nothing new: session={sess.session_id} cursor={cursor:,} size={cur_size:,}")
        return

    # 2. Read everything new since `cursor`, race-free: read_new returns the
    # bytes AND the exact cursor we consumed up to. For SQLite the bytes are
    # synthesized JSONL of new rows; raw_len is byte length, not a cursor delta.
    chunk, next_cursor = harness.read_new(sess, cursor)
    raw_len = len(chunk)

    # 3. Redact (default on)
    if no_redact:
        out_bytes, counts = chunk, {}
    else:
        out_bytes, counts = redact(chunk)

    # 4. Upload as next part
    seq = _next_seq_for(store, harness_name, sess.session_id)
    uniq = uuid.uuid4().hex[:8]
    part_key = f"{_session_prefix(harness_name, sess.session_id)}part-{seq:05d}-{uniq}.jsonl"

    with tempfile.NamedTemporaryFile(delete=False, suffix=".jsonl") as tf:
        tf.write(out_bytes)
        tf_path = tf.name
    try:
        store.put_file(part_key, tf_path)
    finally:
        try:
            os.unlink(tf_path)
        except OSError:
            pass

    # 5. Update meta.json (cumulative)
    meta_key = f"{_session_prefix(harness_name, sess.session_id)}meta.json"
    existing = store.get_json(meta_key) or {}
    parts_log = existing.get("parts", [])
    parts_log.append(
        {
            "seq": seq,
            "uuid": uniq,
            "cursor_range": [cursor, next_cursor],
            "source_bytes": raw_len,
            "uploaded_bytes": len(out_bytes),
            "redactions": counts,
            "uploaded_at": _now_iso(),
        }
    )
    meta = {
        "schema_version": 1,
        "harness": harness_name,
        "session_id": sess.session_id,
        "source_path": str(sess.path),
        "cwd": str(sess.cwd) if sess.cwd else None,
        "agent_id": cfg.get("agent_id"),
        "started_at": existing.get("started_at", _now_iso()),
        "last_uploaded_at": _now_iso(),
        "ended_at": existing.get("ended_at"),
        "total_source_bytes": existing.get("total_source_bytes", 0) + raw_len,
        "total_uploaded_bytes": existing.get("total_uploaded_bytes", 0) + len(out_bytes),
        "redaction_counts": merge_counts(existing.get("redaction_counts", {}), counts),
        "parts": parts_log,
    }
    store.put_json(meta_key, meta)

    # 6. Persist local state. Advance the cursor to the position we read up to
    # (next_cursor), NOT cursor+raw_len — those differ for SQLite where the
    # cursor is a rowid and raw_len is synthesized-JSONL byte length.
    _save_state(
        sess.session_id,
        {
            "harness": harness_name,
            "session_id": sess.session_id,
            "source_path": str(sess.path),
            "cursor": next_cursor,
            "last_uploaded_seq": seq,
            "last_flush_at": _now_iso(),
        },
    )

    click.echo(
        f"uploaded part-{seq:05d}-{uniq}  "
        f"source={raw_len:,}B  upload={len(out_bytes):,}B  "
        f"redactions={counts or 'none'}"
    )


# ---------- list ----------


@session.command("list")
@click.option("--harness", "harness_filter", default=None, help="Filter by harness name.")
@click.option("--limit", default=20, type=int, show_default=True, help="Max sessions to show.")
@click.option(
    "--sort-by",
    type=click.Choice(["recent", "size"]),
    default="recent",
    show_default=True,
)
def list_(harness_filter, limit, sort_by):
    """List sessions in the bucket."""
    store, _ = get_store()
    keys = store.list_keys("sessions/")
    metas: list[dict] = []
    for k in keys:
        if not k.endswith("/meta.json"):
            continue
        meta = store.get_json(k)
        if not meta:
            continue
        if harness_filter and meta.get("harness") != harness_filter:
            continue
        metas.append(meta)

    if sort_by == "recent":
        metas.sort(key=lambda m: m.get("last_uploaded_at", ""), reverse=True)
    else:  # size
        metas.sort(key=lambda m: m.get("total_uploaded_bytes", 0), reverse=True)

    metas = metas[:limit]
    if not metas:
        click.echo("(no sessions)")
        return

    click.echo(f"{'HARNESS':<14} {'SESSION':<16} {'BYTES':>12} {'PARTS':>6} {'LAST UPLOAD':<25}")
    click.echo("-" * 80)
    for m in metas:
        sid = m.get("session_id", "?")
        short = sid[:8] + ("…" if len(sid) > 8 else "")
        click.echo(
            f"{m.get('harness', '?'):<14} {short:<16} "
            f"{m.get('total_uploaded_bytes', 0):>12,} "
            f"{len(m.get('parts', [])):>6} "
            f"{m.get('last_uploaded_at', '-')[:24]:<25}"
        )


# ---------- show ----------


@session.command("show")
@click.argument("session_id")
@click.option(
    "--tail",
    default=0,
    type=int,
    help="If >0, also fetch parts and print the last N lines.",
)
def show(session_id, tail):
    """Inspect one session's meta + optionally tail its parts."""
    store, _ = get_store()

    # Find which harness this session lives under (search every harness folder).
    all_meta_keys = [
        k for k in store.list_keys("sessions/") if k.endswith(f"/{session_id}/meta.json")
    ]
    if not all_meta_keys:
        raise click.ClickException(f"session not found: {session_id}")
    meta_key = all_meta_keys[0]
    meta = store.get_json(meta_key)
    click.echo(json.dumps(meta, indent=2))

    if tail <= 0:
        return

    # Fetch all parts (in seq order), concatenate, print last N lines.
    prefix = meta_key[: -len("meta.json")]
    part_keys = sorted(k for k in store.list_keys(prefix) if PART_RE.search(k.rsplit("/", 1)[-1]))
    body = bytearray()
    for k in part_keys:
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tmp = tf.name
        try:
            store.get_file(k, tmp)
            body.extend(Path(tmp).read_bytes())
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    lines = body.splitlines()
    click.echo("\n--- tail ---")
    for line in lines[-tail:]:
        try:
            click.echo(line.decode("utf-8", errors="replace"))
        except Exception:
            click.echo(repr(line))


# ---------- stop ----------


@session.command("stop")
@click.argument("session_id")
def stop(session_id):
    """Clear local mirror state for a session and mark ended_at in meta.

    This is a placeholder: when --detach lands later, this command will also
    kill the background mirror process. For now it just resets local state
    and records the end time.
    """
    state_file = _state_path(session_id)
    had_state = state_file.exists()
    if had_state:
        state_file.unlink()

    # Best-effort: mark ended_at in meta if a meta exists.
    store, _ = get_store()
    meta_keys = [k for k in store.list_keys("sessions/") if k.endswith(f"/{session_id}/meta.json")]
    marked = False
    if meta_keys:
        meta = store.get_json(meta_keys[0]) or {}
        if meta and not meta.get("ended_at"):
            meta["ended_at"] = _now_iso()
            store.put_json(meta_keys[0], meta)
            marked = True

    click.echo(
        f"stopped session={session_id}  state_cleared={had_state}  meta_marked_ended={marked}"
    )
