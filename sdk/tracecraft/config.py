"""Config file management for tracecraft CLI."""

import json
import os
from pathlib import Path

import click


def get_config_path() -> Path:
    return Path.home() / ".tracecraft" / "config.json"


def load_config() -> dict:
    path = get_config_path()
    if not path.exists():
        raise click.ClickException(
            f"Config not found at {path}. Run 'tracecraft init' first."
        )
    with open(path) as f:
        return json.load(f)


def save_config(data: dict) -> None:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.chmod(path, 0o600)
