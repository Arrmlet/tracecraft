"""tracecraft agents — list registered agents and their status."""

from datetime import datetime, timezone

import click

from tracecraft.store import get_store


@click.command()
def agents():
    """List all registered agents and their status."""
    store, _ = get_store()
    keys = store.list_keys("agents/")

    if not keys:
        click.echo("No agents found.")
        return

    now = datetime.now(timezone.utc)
    click.echo(f"{'ID':<25} {'Status':<10} {'Step':<15} {'Heartbeat Age'}")
    click.echo("-" * 70)

    for key in keys:
        if not key.endswith(".json"):
            continue
        data = store.get_json(key)
        if data is None:
            continue

        agent_id = data.get("id", "?")
        status = data.get("status", "unknown")
        step = data.get("step") or "-"
        heartbeat = data.get("heartbeat")

        hb_age = "unknown"
        if heartbeat:
            try:
                hb_time = datetime.fromisoformat(heartbeat)
                delta = now - hb_time
                minutes = int(delta.total_seconds() / 60)
                if minutes > 5:
                    status = "stale"
                hb_age = f"{minutes}m ago"
            except (ValueError, TypeError):
                hb_age = "invalid"

        click.echo(f"{agent_id:<25} {status:<10} {step:<15} {hb_age}")
