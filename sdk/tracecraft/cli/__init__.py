"""Tracecraft CLI — coordination layer for multi-agent AI systems."""

import click

from tracecraft import __version__
from tracecraft.cli.init_cmd import init_cmd
from tracecraft.cli.memory import memory
from tracecraft.cli.agents import agents
from tracecraft.cli.messages import send, inbox
from tracecraft.cli.steps import claim, complete, step_status, wait_for
from tracecraft.cli.artifacts import artifact


@click.group()
@click.version_option(version=__version__)
def cli():
    """Coordination layer for multi-agent AI systems."""
    pass


cli.add_command(init_cmd, "init")
cli.add_command(memory)
cli.add_command(agents)
cli.add_command(send)
cli.add_command(inbox)
cli.add_command(claim)
cli.add_command(complete)
cli.add_command(step_status, "step-status")
cli.add_command(wait_for, "wait-for")
cli.add_command(artifact)


def main():
    cli()
