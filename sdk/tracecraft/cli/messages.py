"""tracecraft send/inbox — agent-to-agent messaging via S3."""

import time
from datetime import datetime, timezone

import click

from tracecraft.store import get_store


@click.command()
@click.argument("recipient")
@click.argument("message")
def send(recipient, message):
    """Send a message to another agent (or '_broadcast' for all)."""
    store, cfg = get_store()
    sender = cfg["agent_id"]
    ts = int(time.time())
    now = datetime.now(timezone.utc).isoformat()

    key = f"messages/{recipient}/{ts}_{sender}.json"
    store.put_json(key, {
        "from": sender,
        "to": recipient,
        "message": message,
        "sent_at": now,
    })
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

    for key in all_keys:
        data = store.get_json(key)
        if data is None:
            continue
        sender = data.get("from", "?")
        msg = data.get("message", "")
        sent_at = data.get("sent_at", "?")
        target = "broadcast" if "_broadcast/" in key else "direct"
        click.echo(f"[{sent_at}] ({target}) {sender}: {msg}")

        if delete:
            store.delete(key)

    if delete:
        click.echo(f"Deleted {len(all_keys)} message(s).")
