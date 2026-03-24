"""tracecraft artifact — upload, download, and list artifacts via S3."""

import os

import click

from tracecraft.store import get_store


@click.group()
def artifact():
    """Manage artifacts (files) shared between agents."""
    pass


@artifact.command("upload")
@click.argument("path", type=click.Path(exists=True))
@click.option("--step", default=None, help="Step ID that produced this artifact")
def artifact_upload(path, step):
    """Upload a file as an artifact."""
    store, _ = get_store()
    filename = os.path.basename(path)
    if step:
        sid = step.lower().replace(".", "-")
        key = f"artifacts/{sid}/{filename}"
    else:
        key = f"artifacts/shared/{filename}"

    store.put_file(key, path)
    click.echo(f"Uploaded {filename} -> {key}")


@artifact.command("download")
@click.argument("name")
@click.option("--step", default=None, help="Step ID to look in")
@click.option("--output", "-o", default=None, help="Output path (default: current dir)")
def artifact_download(name, step, output):
    """Download an artifact by name."""
    store, _ = get_store()
    if step:
        sid = step.lower().replace(".", "-")
        key = f"artifacts/{sid}/{name}"
    else:
        key = f"artifacts/shared/{name}"

    dest = output or name
    if not store.exists(key):
        raise click.ClickException(f"Artifact not found: {key}")
    store.get_file(key, dest)
    click.echo(f"Downloaded {key} -> {dest}")


@artifact.command("list")
@click.option("--step", default=None, help="List artifacts for a specific step")
def artifact_list(step):
    """List artifacts, optionally filtered by step."""
    store, _ = get_store()
    if step:
        sid = step.lower().replace(".", "-")
        prefix = f"artifacts/{sid}/"
    else:
        prefix = "artifacts/"

    keys = store.list_keys(prefix)
    if not keys:
        click.echo("No artifacts found.")
        return
    for k in keys:
        click.echo(k)
