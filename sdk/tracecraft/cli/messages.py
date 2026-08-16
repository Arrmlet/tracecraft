"""tracecraft send/inbox — agent-to-agent messaging via S3."""

import click

from tracecraft.protocol import (
    advance_stream,
    append_key,
    cursor_key,
    direct_children,
    key_sender,
    load_stream_cursor,
    now_iso,
    unseen_keys,
)
from tracecraft.store import get_store


@click.command()
@click.argument("recipient")
@click.argument("message")
@click.option(
    "--step",
    "step_id",
    default=None,
    help="Thread this message to a step id — recorded in the message body and "
    "shown by inbox, so a step's conversation can be replayed later.",
)
def send(recipient, message, step_id):
    """Send a message to another agent (or '_broadcast' for all)."""
    recipient = recipient.strip()
    if not recipient:
        raise click.ClickException("Recipient cannot be empty")
    # '/' would nest a foreign object inside another agent's mailbox prefix;
    # leading '_' is the reserved namespace (_broadcast, _cursor.json).
    if "/" in recipient:
        raise click.ClickException("Recipient may not contain '/'")
    if recipient.startswith("_") and recipient != "_broadcast":
        raise click.ClickException(
            "Recipient names starting with '_' are reserved ('_broadcast' broadcasts to all)"
        )
    store, cfg = get_store()
    sender = cfg["agent_id"]

    doc = {
        "from": sender,
        "to": recipient,
        "message": message,
        "sent_at": now_iso(),
    }
    if step_id:
        doc["step"] = step_id
    store.put_json(append_key(f"messages/{recipient}/", sender), doc)
    click.echo(f"Sent to {recipient}: {message}")


@click.command()
@click.option(
    "--new",
    "only_new",
    is_flag=True,
    help="Show only messages that arrived since your last --new read, then "
    "advance your read cursor. Nothing is deleted.",
)
@click.option(
    "--delete",
    is_flag=True,
    help="[deprecated — prefer --new] Delete direct messages after reading. "
    "Broadcasts are never deleted — other agents still need to read them.",
)
def inbox(delete, only_new):
    """Read messages in your inbox and broadcasts."""
    if delete and only_new:
        raise click.ClickException("--delete and --new are mutually exclusive")
    if delete:
        click.echo(
            "warning: --delete is deprecated and will be removed in a future release; "
            "use `inbox --new` to read incrementally without destroying the message log.",
            err=True,
        )

    store, cfg = get_store()
    my_id = cfg["agent_id"]
    direct_prefix = f"messages/{my_id}/"
    broadcast_prefix = "messages/_broadcast/"

    # Without --new the cursor doc stays {}, both watermarks are None, and the
    # listings below are naturally full-range.
    cursor_doc = (store.get_json(cursor_key(my_id)) or {}) if only_new else {}
    direct_stream = load_stream_cursor(cursor_doc, "direct")
    broadcast_stream = load_stream_cursor(cursor_doc, "broadcast")

    # direct_children drops the cursor object and any nested junk — neither is
    # mail, and either would poison the cursor advance below.
    direct_listed = direct_children(
        store.list_keys(direct_prefix, start_after=direct_stream["watermark"]), direct_prefix
    )
    broadcast_listed = direct_children(
        store.list_keys(broadcast_prefix, start_after=broadcast_stream["watermark"]),
        broadcast_prefix,
    )

    if only_new:
        direct_keys = unseen_keys(direct_listed, direct_stream)
        broadcast_keys = unseen_keys(broadcast_listed, broadcast_stream)
    else:
        direct_keys, broadcast_keys = direct_listed, broadcast_listed

    # Merge direct + broadcast and sort by sent_at — raw list order interleaves
    # the two prefixes, so a broadcast could print before the direct message
    # that preceded it.
    messages = []
    for key in direct_keys + broadcast_keys:
        # Skip own broadcasts by the sender embedded in the key — no GET needed.
        if key.startswith(broadcast_prefix) and key_sender(key, broadcast_prefix) == my_id:
            continue
        data = store.get_json(key)
        if data is None:
            continue
        # Fallback for non-conforming keys the parser above couldn't classify.
        if key.startswith(broadcast_prefix) and data.get("from", "?") == my_id:
            continue
        messages.append((key, data))
    messages.sort(key=lambda kd: kd[1].get("sent_at", ""))

    deleted = 0
    for key, data in messages:
        sender = data.get("from", "?")
        msg = data.get("message", "")
        sent_at = data.get("sent_at", "?")
        target = "broadcast" if key.startswith(broadcast_prefix) else "direct"
        # Step-threaded messages carry a tag; the plain format is unchanged so
        # existing line-parsers keep working for untagged messages.
        step = data.get("step")
        tag = f" [step {step}]" if step else ""
        click.echo(f"[{sent_at}] ({target}) {sender}{tag}: {msg}")
        # Broadcasts are shared: the first reader deleting them would destroy
        # them for every other agent. Only the recipient's own direct messages
        # are safe to delete.
        if delete and target == "direct":
            store.delete(key)
            deleted += 1

    if not messages:
        click.echo("No new messages." if only_new else "No messages.")
    elif delete:
        click.echo(f"Deleted {deleted} direct message(s); broadcasts left in place.")

    # Advance the cursor only AFTER a successful read — at-least-once delivery.
    # A crash mid-print re-shows messages on the next --new; it never silently
    # skips them. The cursor advances over everything *listed* (even messages
    # filtered from display, like our own broadcasts): read position is about
    # what was seen, not what was shown.
    if only_new and (direct_keys or broadcast_keys):
        store.put_json(
            cursor_key(my_id),
            {
                "direct": advance_stream(direct_stream, direct_listed, direct_prefix),
                "broadcast": advance_stream(broadcast_stream, broadcast_listed, broadcast_prefix),
                "updated_at": now_iso(),
            },
        )
