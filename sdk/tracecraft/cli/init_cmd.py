"""tracecraft init — configure and register agent."""

from datetime import datetime, timezone

import click

from tracecraft.config import save_config


@click.command()
@click.option("--backend", type=click.Choice(["s3", "hf"]), default="s3", help="Storage backend: s3 or hf (HuggingFace Buckets)")
@click.option("--endpoint", default=None, help="S3 endpoint URL (s3 backend only)")
@click.option("--bucket", required=True, help="Bucket name (s3) or HF bucket handle e.g. username/my-bucket (hf)")
@click.option("--project", required=True, help="Project namespace")
@click.option("--agent", required=True, help="Agent ID for this session")
@click.option("--access-key", default="admin", help="S3 access key (s3 backend only)")
@click.option("--secret-key", default="secret", help="S3 secret key (s3 backend only)")
@click.option("--hf-token", default=None, help="HuggingFace token (hf backend only)")
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
        cfg["endpoint"] = endpoint
        cfg["access_key"] = access_key
        cfg["secret_key"] = secret_key
    elif backend == "hf":
        if hf_token:
            cfg["hf_token"] = hf_token

    save_config(cfg)

    store = _get_store(cfg)
    store.ensure_bucket()

    now = datetime.now(timezone.utc).isoformat()
    store.put_json(f"agents/{agent}.json", {
        "id": agent,
        "status": "active",
        "step": None,
        "started_at": now,
        "heartbeat": now,
        "summary": "Initialized",
    })

    click.echo(f"Initialized project '{project}' as agent '{agent}'")
    if backend == "s3":
        click.echo(f"Backend: S3  Endpoint: {endpoint}  Bucket: {bucket}")
    else:
        click.echo(f"Backend: HuggingFace Buckets  Bucket: {bucket}")


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
