"""tracecraft init — configure and register agent."""

from datetime import datetime, timezone

import click

from tracecraft.config import save_config
from tracecraft.s3 import S3


@click.command()
@click.option("--endpoint", required=True, help="S3 endpoint URL")
@click.option("--bucket", required=True, help="S3 bucket name")
@click.option("--project", required=True, help="Project namespace")
@click.option("--agent", required=True, help="Agent ID for this session")
@click.option("--access-key", default="admin", help="S3 access key")
@click.option("--secret-key", default="secret", help="S3 secret key")
def init_cmd(endpoint, bucket, project, agent, access_key, secret_key):
    """Initialize tracecraft config, create bucket, and register agent."""
    cfg = {
        "endpoint": endpoint,
        "bucket": bucket,
        "project": project,
        "agent_id": agent,
        "access_key": access_key,
        "secret_key": secret_key,
    }
    save_config(cfg)

    s3 = S3(endpoint, bucket, project, access_key, secret_key)
    s3.ensure_bucket()

    now = datetime.now(timezone.utc).isoformat()
    s3.put_json(f"agents/{agent}.json", {
        "id": agent,
        "status": "active",
        "step": None,
        "started_at": now,
        "heartbeat": now,
        "summary": "Initialized",
    })

    click.echo(f"Initialized project '{project}' as agent '{agent}'")
    click.echo(f"Endpoint: {endpoint}  Bucket: {bucket}")
