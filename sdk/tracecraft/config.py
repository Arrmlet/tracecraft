"""Config file management for tracecraft CLI."""

import json
import os
from pathlib import Path

import click


def get_config_path() -> Path:
    """Local .tracecraft.json in current dir takes priority, then global."""
    local = Path.cwd() / ".tracecraft.json"
    if local.exists():
        return local
    return Path.home() / ".tracecraft" / "config.json"


def get_init_config_path(local: bool = True) -> Path:
    """Where init writes the config — local by default."""
    if local:
        return Path.cwd() / ".tracecraft.json"
    return Path.home() / ".tracecraft" / "config.json"


def load_config() -> dict:
    path = get_config_path()
    if not path.exists():
        raise click.ClickException(
            f"Config not found. Run 'tracecraft init' in this directory first."
        )
    with open(path) as f:
        return json.load(f)


def save_config(data: dict, local: bool = True) -> None:
    path = get_init_config_path(local)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.chmod(path, 0o600)
