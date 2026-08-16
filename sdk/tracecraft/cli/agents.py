"""tracecraft agents — list registered agents and their status."""

import click

from tracecraft.protocol import collect_agents
from tracecraft.store import get_store


@click.command()
def agents():
    """List all registered agents and their status."""
    store, _ = get_store()
    rows = collect_agents(store)

    if not rows:
        click.echo("No agents found.")
        return

    click.echo(f"{'ID':<25} {'Status':<10} {'Step':<15} {'Heartbeat Age'}")
    click.echo("-" * 70)
    for a in rows:
        age = a["heartbeat_age_s"]
        hb_age = f"{age // 60}m ago" if age is not None else "unknown"
        click.echo(f"{a['id']:<25} {a['status']:<10} {a['step'] or '-':<15} {hb_age}")
