"""tracecraft memory — shared key-value state via S3."""

from datetime import datetime, timezone

import click

from tracecraft.config import load_config
from tracecraft.s3 import S3


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


@memory.command("set")
@click.argument("key")
@click.argument("value")
def memory_set(key, value):
    """Set a memory key. Dots become path separators."""
    cfg = load_config()
    s3 = S3.from_config()
    now = datetime.now(timezone.utc).isoformat()
    s3.put_json(_key_to_path(key), {
        "value": value,
        "set_by": cfg["agent_id"],
        "set_at": now,
    })
    click.echo(f"Set {key} = {value}")


@memory.command("get")
@click.argument("key")
def memory_get(key):
    """Get a memory value by key."""
    s3 = S3.from_config()
    data = s3.get_json(_key_to_path(key))
    if data is None:
        raise click.ClickException(f"Key '{key}' not found")
    click.echo(data["value"])


@memory.command("list")
@click.argument("prefix", default="")
def memory_list(prefix):
    """List memory keys, optionally filtered by prefix."""
    s3 = S3.from_config()
    s3_prefix = "memory/"
    if prefix:
        s3_prefix += prefix.replace(".", "/")
    keys = s3.list_keys(s3_prefix)
    for k in keys:
        dot_key = _path_to_key(k)
        click.echo(dot_key)
