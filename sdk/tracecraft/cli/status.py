"""`tracecraft status` — read-only, one-screen view of a project.

Aggregates what otherwise takes four commands (agents, step-status, inbox,
session list) into one snapshot: who's registered, what's claimed/complete,
how much mail is waiting, and what sessions are protected. Strictly read-only —
safe to run from anywhere with read credentials.
"""

import json
import time
from datetime import datetime, timezone

import click

from tracecraft.protocol import (
    CURSOR_LEAF,
    collect_agents,
    effective_status_from_listing,
    is_data_leaf,
    key_sender,
    load_stream_cursor,
    session_totals,
    unseen_keys,
)
from tracecraft.store import get_store

BROADCAST_PREFIX = "messages/_broadcast/"


def _gather(store, cfg):
    """Collect the full status snapshot as one JSON-serializable dict."""
    now = datetime.now(timezone.utc)

    agents = collect_agents(store, now)

    # Steps: derive ids from the key layout steps/<id>/<file>, then resolve
    # each honoring the claim/status crash window (claim.json present +
    # status.json missing = in_progress, never pending). The listing already
    # proves which files exist, so guaranteed-404 GETs are skipped.
    step_keys = store.list_keys("steps/")
    present = set(step_keys)
    step_ids = sorted({parts[1] for k in step_keys if len(parts := k.split("/")) >= 3})
    steps = []
    for sid in step_ids:
        st, agent = effective_status_from_listing(store, sid, present)
        steps.append({"id": sid, "status": st, "agent": agent})

    # Mailboxes: count per recipient; "unread" is relative to that agent's own
    # read cursor (from `inbox --new`) and only defined once a cursor exists.
    # It matches what `inbox --new` would show: unseen direct messages plus
    # unseen broadcasts from OTHER agents.
    boxes = {}
    have_cursor = set()
    for k in store.list_keys("messages/"):
        parts = k.split("/", 2)
        if len(parts) < 3:
            continue
        recipient, leaf = parts[1], parts[2]
        if leaf == CURSOR_LEAF:
            have_cursor.add(recipient)
            continue
        if not is_data_leaf(leaf):  # nested junk / reserved leaves are never mail
            continue
        boxes.setdefault(recipient, []).append(k)

    # Broadcast senders come from the key names — no per-broadcast GETs (which
    # would grow without bound, since broadcasts are never deleted). Fetch only
    # non-conforming keys, and only when someone with a cursor will consume it.
    broadcast_keys = sorted(boxes.get("_broadcast", []))
    broadcast_sender = {}
    if have_cursor - {"_broadcast"}:
        for k in broadcast_keys:
            sender = key_sender(k, BROADCAST_PREFIX)
            if sender is None:
                sender = (store.get_json(k) or {}).get("from")
            broadcast_sender[k] = sender

    mailboxes = []
    for recipient in sorted(set(boxes) | have_cursor):
        keys = boxes.get(recipient, [])
        unread = None
        if recipient != "_broadcast" and recipient in have_cursor:
            cur = store.get_json(f"messages/{recipient}/{CURSOR_LEAF}") or {}
            direct_new = unseen_keys(sorted(keys), load_stream_cursor(cur, "direct"))
            broadcast_new = unseen_keys(broadcast_keys, load_stream_cursor(cur, "broadcast"))
            unread = len(direct_new) + sum(
                1 for k in broadcast_new if broadcast_sender.get(k) != recipient
            )
        mailboxes.append({"agent": recipient, "total": len(keys), "unread": unread})

    return {
        "project": cfg.get("project"),
        "backend": cfg.get("backend"),
        "bucket": cfg.get("bucket"),
        "generated_at": now.isoformat(),
        "agents": agents,
        "steps": steps,
        "mailboxes": mailboxes,
        "sessions": session_totals(store),
    }


def _fmt_age(seconds):
    if seconds is None:
        return "unknown"
    if seconds < 90:
        return f"{seconds}s ago"
    if seconds < 5400:
        return f"{seconds // 60}m ago"
    return f"{seconds // 3600}h ago"


def _render(snap):
    out = []
    out.append(f"project {snap['project']} · backend {snap['backend']} · bucket {snap['bucket']}")

    agents = snap["agents"]
    out.append(f"\nAGENTS ({len(agents)})")
    if agents:
        for a in agents:
            step = a["step"] or "-"
            out.append(
                f"  {a['id']:<24} {a['status']:<10} step {step:<14} "
                f"heartbeat {_fmt_age(a['heartbeat_age_s'])}"
            )
    else:
        out.append("  (none registered)")

    steps = snap["steps"]
    counts = {}
    for s in steps:
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    tally = " · ".join(f"{v} {k}" for k, v in sorted(counts.items())) if counts else "none"
    out.append(f"\nSTEPS ({len(steps)}): {tally}")
    for s in steps:
        agent = f"  (agent: {s['agent']})" if s["agent"] else ""
        out.append(f"  {s['id']:<24} {s['status']}{agent}")

    mailboxes = snap["mailboxes"]
    out.append(f"\nMAILBOXES ({len(mailboxes)})")
    if mailboxes:
        for m in mailboxes:
            unread = "no cursor" if m["unread"] is None else f"{m['unread']} unread"
            out.append(f"  {m['agent']:<24} {m['total']} message(s) · {unread}")
    else:
        out.append("  (empty)")

    s = snap["sessions"]
    mb = s["total_uploaded_bytes"] / (1024 * 1024)
    last = s["last_uploaded_at"] or "never"
    out.append(f"\nSESSIONS: {s['count']} · {mb:.1f} MB · last upload {last}")
    return "\n".join(out)


@click.command()
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
@click.option("--watch", is_flag=True, help="Refresh in place until Ctrl-C.")
@click.option(
    "--interval",
    default=5.0,
    type=float,
    show_default=True,
    help="Seconds between refreshes in --watch mode.",
)
def status(as_json, watch, interval):
    """One-screen view: agents, steps, mailboxes, sessions. Read-only."""
    if as_json and watch:
        raise click.ClickException("--json and --watch are mutually exclusive")
    if interval <= 0:
        raise click.ClickException("--interval must be > 0")

    store, cfg = get_store()

    if not watch:
        snap = _gather(store, cfg)
        click.echo(json.dumps(snap, indent=2) if as_json else _render(snap))
        return

    try:
        while True:
            snap = _gather(store, cfg)
            click.clear()
            click.echo(_render(snap))
            click.echo(f"\n(refreshing every {interval:g}s — Ctrl-C to stop)")
            time.sleep(interval)
    except KeyboardInterrupt:
        click.echo("")
