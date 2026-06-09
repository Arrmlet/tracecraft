"""tracecraft send/inbox — agent-to-agent messaging via S3."""

import time
import uuid
from datetime import datetime, timezone

import click

from tracecraft.store import get_store


@click.command()
@click.argument("recipient")
@click.argument("message")
def send(recipient, message):
    """Send a message to another agent (or '_broadcast' for all)."""
    if not recipient.strip():
        raise click.ClickException("Recipient cannot be empty")
    store, cfg = get_store()
    sender = cfg["agent_id"]
    now = datetime.now(timezone.utc).isoformat()

    # Message keys MUST be unique per send. A whole-second timestamp collides when
    # one sender fires two messages to the same recipient in the same second — the
    # second silently overwrites the first (measured: a 5-message burst kept only 1).
    # Use nanosecond resolution for rough chronological ordering PLUS a uuid suffix
    # that guarantees uniqueness even at sub-nanosecond send rates or clock ties.
    # (Same approach the session mirror uses for its part keys.)
    ts_ns = time.time_ns()
    uniq = uuid.uuid4().hex[:8]
    key = f"messages/{recipient}/{ts_ns}_{sender}_{uniq}.json"
    store.put_json(
        key,
        {
            "from": sender,
            "to": recipient,
            "message": message,
            "sent_at": now,
        },
    )
    click.echo(f"Sent to {recipient}: {message}")


@click.command()
@click.option("--delete", is_flag=True, help="Delete messages after reading")
def inbox(delete):
    """Read messages in your inbox and broadcasts."""
    store, cfg = get_store()
    my_id = cfg["agent_id"]

    direct_keys = store.list_keys(f"messages/{my_id}/")
    broadcast_keys = store.list_keys("messages/_broadcast/")
    all_keys = direct_keys + broadcast_keys

    if not all_keys:
        click.echo("No messages.")
        return

    # Merge direct + broadcast and sort by sent_at — raw list order interleaves
    # the two prefixes, so a broadcast could print before the direct message
    # that preceded it.
    messages = []
    for key in all_keys:
        data = store.get_json(key)
        if data is None:
            continue
        # Skip own broadcasts
        if "_broadcast/" in key and data.get("from", "?") == my_id:
            continue
        messages.append((key, data))
    messages.sort(key=lambda kd: kd[1].get("sent_at", ""))

    for key, data in messages:
        sender = data.get("from", "?")
        msg = data.get("message", "")
        sent_at = data.get("sent_at", "?")
        target = "broadcast" if "_broadcast/" in key else "direct"
        click.echo(f"[{sent_at}] ({target}) {sender}: {msg}")
        if delete:
            store.delete(key)

    if not messages:
        click.echo("No messages.")
    elif delete:
        click.echo(f"Deleted {len(messages)} message(s).")
