"""tracecraft steps — claim, complete, and track coordination steps."""

import time
from datetime import datetime, timezone

import click

from tracecraft.store import get_store


@click.command()
@click.argument("step_id")
def claim(step_id):
    """Claim a step for this agent."""
    store, cfg = get_store()
    agent = cfg["agent_id"]
    sid = step_id.lower().replace(".", "-")

    # Check if already claimed
    if store.exists(f"steps/{sid}/claim.json"):
        existing = store.get_json(f"steps/{sid}/claim.json")
        owner = existing.get("agent", "unknown") if existing else "unknown"
        raise click.ClickException(f"Step {step_id} already claimed by {owner}")

    now = datetime.now(timezone.utc).isoformat()
    store.put_json(f"steps/{sid}/claim.json", {
        "agent": agent,
        "claimed_at": now,
    })
    store.put_json(f"steps/{sid}/status.json", {
        "status": "in_progress",
        "agent": agent,
        "started_at": now,
    })
    click.echo(f"Claimed step {step_id} as {agent}")


@click.command()
@click.argument("step_id")
@click.option("--note", default="", help="Handoff note for the next agent")
def complete(step_id, note):
    """Mark a step as complete and write handoff."""
    store, cfg = get_store()
    agent = cfg["agent_id"]
    sid = step_id.lower().replace(".", "-")
    now = datetime.now(timezone.utc).isoformat()

    # Update status
    existing = store.get_json(f"steps/{sid}/status.json") or {}
    store.put_json(f"steps/{sid}/status.json", {
        "status": "complete",
        "agent": agent,
        "started_at": existing.get("started_at", now),
        "completed_at": now,
    })

    # Write handoff
    store.put_json(f"steps/{sid}/handoff.json", {
        "from_agent": agent,
        "from_step": step_id,
        "note": note,
        "created_at": now,
    })
    click.echo(f"Completed step {step_id}")


@click.command()
@click.argument("step_id")
def step_status(step_id):
    """Check the status of a step."""
    store, _ = get_store()
    sid = step_id.lower().replace(".", "-")
    data = store.get_json(f"steps/{sid}/status.json")
    if data is None:
        click.echo(f"{step_id}: pending")
        return
    status = data.get("status", "unknown")
    agent = data.get("agent", "?")
    click.echo(f"{step_id}: {status} (agent: {agent})")


@click.command()
@click.argument("step_ids", nargs=-1, required=True)
@click.option("--timeout", default=300, help="Timeout in seconds (default 300)")
def wait_for(step_ids, timeout):
    """Poll until all specified steps are complete."""
    store, _ = get_store()
    deadline = time.time() + timeout

    while time.time() < deadline:
        all_done = True
        for step_id in step_ids:
            sid = step_id.lower().replace(".", "-")
            data = store.get_json(f"steps/{sid}/status.json")
            if data is None or data.get("status") != "complete":
                all_done = False
                break

        if all_done:
            click.echo(f"All steps complete: {', '.join(step_ids)}")
            return

        remaining = int(deadline - time.time())
        click.echo(f"Waiting... ({remaining}s remaining)", err=True)
        time.sleep(5)

    raise click.ClickException(
        f"Timeout after {timeout}s. Not all steps complete: {', '.join(step_ids)}"
    )
