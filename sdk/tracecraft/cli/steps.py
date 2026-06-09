"""tracecraft steps — claim, complete, and track coordination steps."""

import subprocess
import time
from datetime import datetime, timezone

import click

from tracecraft.s3 import PreconditionFailed
from tracecraft.store import get_store


def _git_changed_files() -> list[str]:
    """Return changed files from `git diff --name-only HEAD` (staged + unstaged),
    or [] if not a git repo / git unavailable. Never raises.

    Git is the source of truth for what changed — we never let an agent type
    the file list by hand (self-reported change lists are wrong ~half the time
    and go stale on the next commit).
    """
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode != 0:
            return []
        files = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
        return files
    except (OSError, subprocess.SubprocessError):
        return []


@click.command()
@click.argument("step_id")
def claim(step_id):
    """Claim a step for this agent (atomic via If-None-Match)."""
    store, cfg = get_store()
    agent = cfg["agent_id"]
    sid = step_id.lower().replace(".", "-")

    now = datetime.now(timezone.utc).isoformat()
    try:
        store.put_json(
            f"steps/{sid}/claim.json",
            {"agent": agent, "claimed_at": now},
            if_none_match=True,
        )
    except PreconditionFailed:
        existing = store.get_json(f"steps/{sid}/claim.json") or {}
        owner = existing.get("agent", "unknown")
        raise click.ClickException(f"Step {step_id} already claimed by {owner}")

    store.put_json(
        f"steps/{sid}/status.json",
        {
            "status": "in_progress",
            "agent": agent,
            "started_at": now,
        },
    )
    click.echo(f"Claimed step {step_id} as {agent}")


@click.command()
@click.argument("step_id")
@click.option("--note", default="", help="Handoff note for the next agent (free text)")
@click.option("--to", "next_agent", default=None, help="Agent this step hands off to")
@click.option("--next-action", default=None, help="One line: what the next agent should do first")
@click.option("--blocked", is_flag=True, help="Mark the step blocked rather than complete")
@click.option(
    "--needs-review", is_flag=True, help="Mark the step as needing review rather than complete"
)
@click.option(
    "--changed-files-from-git",
    is_flag=True,
    help="Record files changed (from `git diff`), so the next agent knows what moved. No-op outside a git repo.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Complete a step claimed by a different agent (e.g. the claim-holder crashed).",
)
def complete(
    step_id, note, next_agent, next_action, blocked, needs_review, changed_files_from_git, force
):
    """Mark a step complete (or blocked / needs-review) and write a handoff record.

    The handoff record is what the next agent sees instead of a shared
    conversation — so it carries machine-checkable state, not just a note.
    Fields that can be wrong if hand-typed (changed files) are sourced from
    git; fields that would be hallucinated if mandatory (assumptions) stay as
    optional free text in --note.
    """
    if blocked and needs_review:
        raise click.ClickException("Use at most one of --blocked / --needs-review")

    store, cfg = get_store()
    agent = cfg["agent_id"]
    sid = step_id.lower().replace(".", "-")
    now = datetime.now(timezone.utc).isoformat()

    # A step belongs to whoever claimed it — without this check any agent
    # could mark any step complete and silently steal/clobber someone's work.
    claim_doc = store.get_json(f"steps/{sid}/claim.json")
    if claim_doc and claim_doc.get("agent") not in (None, agent) and not force:
        raise click.ClickException(
            f"Step {step_id} is claimed by '{claim_doc['agent']}', not '{agent}'. "
            f"Pass --force to complete it anyway (e.g. if the claim-holder crashed)."
        )

    state = "blocked" if blocked else "needs_review" if needs_review else "complete"

    # Status reflects the real outcome (not always "complete").
    existing = store.get_json(f"steps/{sid}/status.json") or {}
    status_doc = {
        "status": state,
        "agent": agent,
        "started_at": existing.get("started_at", now),
    }
    if state == "complete":
        status_doc["completed_at"] = now
    store.put_json(f"steps/{sid}/status.json", status_doc)

    # Handoff record — schema v2. All v2 keys optional; old readers/handoffs
    # keep working. changed_files is git-derived (never agent-typed).
    handoff = {
        "schema": 2,
        "from_agent": agent,
        "from_step": step_id,
        "next_agent": next_agent,
        "state": state,
        "next_action": next_action,
        "note": note,
        "created_at": now,
    }
    if changed_files_from_git:
        handoff["changed_files"] = _git_changed_files()
    store.put_json(f"steps/{sid}/handoff.json", handoff)

    label = {"complete": "Completed", "blocked": "Blocked", "needs_review": "Needs review on"}[
        state
    ]
    msg = f"{label} step {step_id}"
    if next_agent:
        msg += f" → handed off to {next_agent}"
    if changed_files_from_git:
        msg += f" ({len(handoff['changed_files'])} changed file(s))"
    click.echo(msg)


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
