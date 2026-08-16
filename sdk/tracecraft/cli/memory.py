"""tracecraft memory — shared key-value state via S3."""

import json

import click

from tracecraft.protocol import append_key, direct_children, now_iso
from tracecraft.store import get_store

# Version snapshots live under memory/_history/<key-path>/. The leading
# underscore keeps the namespace out of dot-key space, but a user could still
# type it — so "_history" is reserved and rejected in `set`.
HISTORY_ROOT = "memory/_history/"


@click.group()
def memory():
    """Shared key-value memory (dots become path separators)."""
    pass


def _key_to_path(key):
    """Convert dot notation to S3 path: phase1.status -> memory/phase1/status.json"""
    return "memory/" + key.replace(".", "/") + ".json"


def _path_to_key(path):
    """Convert S3 path back to dot notation: memory/phase1/status.json -> phase1.status"""
    stripped = path.removeprefix("memory/").removesuffix(".json")
    return stripped.replace("/", ".")


def _history_prefix(key):
    return HISTORY_ROOT + key.replace(".", "/") + "/"


@memory.command("set")
@click.argument("key")
@click.argument("value")
def memory_set(key, value):
    """Set a memory key. Dots become path separators.

    Every set also appends an immutable snapshot under memory/_history/, so
    the current value is last-write-wins but no version is ever lost. See
    `memory history`.
    """
    if not key.strip():
        raise click.ClickException("Key cannot be empty")
    # Slashes would let a key path-traverse into other keys' storage — including
    # forging entries inside the _history audit namespace. Dots are the only
    # separator; the store layout is derived, never user-addressed.
    if "/" in key:
        raise click.ClickException("Memory keys use dots as separators; '/' is not allowed")
    if key == "_history" or key.startswith("_history."):
        raise click.ClickException("The '_history' key namespace is reserved for version snapshots")
    store, cfg = get_store()
    doc = {
        "value": value,
        "set_by": cfg["agent_id"],
        "set_at": now_iso(),
    }
    # History first, live key second: a crash in between leaves an extra audit
    # entry (harmless) rather than a live value with no record of who set it.
    store.put_json(append_key(_history_prefix(key), cfg["agent_id"]), {"key": key, **doc})
    store.put_json(_key_to_path(key), doc)
    click.echo(f"Set {key} = {value}")


@memory.command("get")
@click.argument("key")
@click.option(
    "--with-meta", is_flag=True, help="Print set_by/set_at metadata as JSON, not just the value."
)
def memory_get(key, with_meta):
    """Get a memory value by key. Exits with code 1 if not found."""
    store, _ = get_store()
    data = store.get_json(_key_to_path(key))
    if data is None:
        click.echo("", err=True)
        raise SystemExit(1)
    if with_meta:
        click.echo(
            json.dumps(
                {
                    "key": key,
                    "value": data.get("value"),
                    "set_by": data.get("set_by"),
                    "set_at": data.get("set_at"),
                },
                indent=2,
            )
        )
    else:
        click.echo(data["value"])


@memory.command("history")
@click.argument("key")
@click.option(
    "--limit",
    default=20,
    show_default=True,
    help="Show at most the newest N versions (0 = all).",
)
def memory_history(key, limit):
    """Show a key's version history, oldest first. Exits with code 1 if none.

    Every `memory set` appends here; the trail survives overwrites of the
    live value. Versions are ordered by the writer's nanosecond timestamp.
    """
    store, _ = get_store()
    prefix = _history_prefix(key)
    # Only direct children: the recursive prefix listing also matches nested
    # dotted keys (history of 'a' must not sweep in 'a.b' snapshots).
    hist_keys = sorted(direct_children(store.list_keys(prefix), prefix))
    if limit > 0:
        hist_keys = hist_keys[-limit:]
    if not hist_keys:
        click.echo(f"No history for {key}.", err=True)
        raise SystemExit(1)
    for hk in hist_keys:
        entry = store.get_json(hk)
        if entry is None:
            continue
        click.echo(f"[{entry.get('set_at', '?')}] {entry.get('set_by', '?')}: {entry.get('value')}")


@memory.command("list")
@click.argument("prefix", default="")
def memory_list(prefix):
    """List memory keys, optionally filtered by prefix."""
    store, _ = get_store()
    s3_prefix = "memory/"
    if prefix:
        s3_prefix += prefix.replace(".", "/")
    keys = store.list_keys(s3_prefix)
    for k in keys:
        # Version snapshots are not live keys.
        if k.startswith(HISTORY_ROOT):
            continue
        dot_key = _path_to_key(k)
        click.echo(dot_key)
