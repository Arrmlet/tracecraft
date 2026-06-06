"""tracecraft init — configure and register agent."""

import os
from datetime import datetime, timezone
from pathlib import Path

import click

from tracecraft.config import save_config


@click.command()
@click.option(
    "--backend",
    type=click.Choice(["s3", "hf"]),
    default="s3",
    help="Storage backend: s3 or hf (HuggingFace Buckets)",
)
@click.option("--endpoint", default=None, help="S3 endpoint URL (s3 backend only)")
@click.option(
    "--bucket",
    required=True,
    help="Bucket name (s3) or HF bucket handle e.g. username/my-bucket (hf)",
)
@click.option("--project", required=True, help="Project namespace")
@click.option("--agent", required=True, help="Agent ID for this session")
@click.option(
    "--access-key",
    default=None,
    envvar="AWS_ACCESS_KEY_ID",
    help="S3 access key (env: AWS_ACCESS_KEY_ID)",
)
@click.option(
    "--secret-key",
    default=None,
    envvar="AWS_SECRET_ACCESS_KEY",
    help="S3 secret key (env: AWS_SECRET_ACCESS_KEY)",
)
@click.option(
    "--hf-token", default=None, envvar="HF_TOKEN", help="HuggingFace token (env: HF_TOKEN)"
)
def init_cmd(backend, endpoint, bucket, project, agent, access_key, secret_key, hf_token):
    """Initialize tracecraft config, create bucket, and register agent."""
    cfg = {
        "backend": backend,
        "bucket": bucket,
        "project": project,
        "agent_id": agent,
    }

    if backend == "s3":
        if not endpoint:
            raise click.ClickException("--endpoint is required for s3 backend")
        if not access_key or not secret_key:
            raise click.ClickException(
                "S3 credentials required. Pass --access-key/--secret-key, or set "
                "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in the environment."
            )
        cfg["endpoint"] = endpoint
        cfg["access_key"] = access_key
        cfg["secret_key"] = secret_key
    elif backend == "hf":
        if hf_token:
            cfg["hf_token"] = hf_token

    save_config(cfg)
    _ensure_gitignore_entry()

    store = _get_store(cfg)
    store.ensure_bucket()

    now = datetime.now(timezone.utc).isoformat()
    store.put_json(
        f"agents/{agent}.json",
        {
            "id": agent,
            "status": "active",
            "step": None,
            "started_at": now,
            "heartbeat": now,
            "summary": "Initialized",
        },
    )

    click.echo(f"Initialized project '{project}' as agent '{agent}'")
    if backend == "s3":
        click.echo(f"Backend: S3  Endpoint: {endpoint}  Bucket: {bucket}")
    else:
        click.echo(f"Backend: HuggingFace Buckets  Bucket: {bucket}")
    click.echo("Note: .tracecraft.json contains credentials. Keep it out of version control.")


def _ensure_gitignore_entry():
    """If cwd is a git repo, append .tracecraft.json to .gitignore so creds don't leak."""
    cwd = Path.cwd()
    if not (cwd / ".git").exists():
        return
    gi = cwd / ".gitignore"
    entry = ".tracecraft.json"
    try:
        existing = gi.read_text() if gi.exists() else ""
    except OSError:
        return
    if entry in existing.splitlines():
        return
    sep = "" if existing.endswith("\n") or not existing else "\n"
    try:
        with gi.open("a") as f:
            f.write(f"{sep}{entry}\n")
        click.echo(f"Added {entry} to .gitignore")
    except OSError:
        click.echo(
            f"warning: could not write to .gitignore — add '{entry}' manually",
            err=True,
        )


def _get_store(cfg):
    """Create the right storage backend from config."""
    backend = cfg.get("backend", "s3")
    if backend == "hf":
        from tracecraft.hf import HF

        return HF(bucket=cfg["bucket"], project=cfg["project"], token=cfg.get("hf_token"))
    else:
        from tracecraft.s3 import S3

        return S3(
            endpoint=cfg["endpoint"],
            bucket=cfg["bucket"],
            project=cfg["project"],
            access_key=cfg["access_key"],
            secret_key=cfg["secret_key"],
        )
