"""Tracecraft CLI — coordination layer for multi-agent AI systems."""

import click

from tracecraft import __version__
from tracecraft.cli.init_cmd import init_cmd
from tracecraft.cli.memory import memory
from tracecraft.cli.agents import agents
from tracecraft.cli.messages import send, inbox
from tracecraft.cli.steps import claim, complete, step_status, wait_for
from tracecraft.cli.artifacts import artifact

BANNER = """
\033[36m  _                                  __ _
 | |_ _ __ __ _  ___ ___  ___ _ __ __ _ / _| |_
 | __| '__/ _` |/ __/ _ \\/ __| '__/ _` | |_| __|
 | |_| | | (_| | (_|  __/ (__| | | (_| |  _| |_
  \\__|_|  \\__,_|\\___\\___|\\___|_|  \\__,_|_|  \\__|\033[0m
"""


@click.group(invoke_without_command=True)
@click.version_option(version=__version__)
@click.pass_context
def cli(ctx):
    """Coordination layer for multi-agent AI systems."""
    if ctx.invoked_subcommand is None:
        click.echo(BANNER)
        click.echo("  \033[36mCoordination layer for multi-agent AI systems.\033[0m")
        click.echo()
        click.echo("  \033[1mCommands:\033[0m")
        click.echo("    init           Configure S3 backend + project + agent")
        click.echo("    memory         Shared key-value state (set/get/list)")
        click.echo("    agents         Who's online?")
        click.echo("    send           Message an agent (or _broadcast for all)")
        click.echo("    inbox          Check your messages")
        click.echo("    claim          Claim a task step")
        click.echo("    complete       Mark step done + handoff note")
        click.echo("    step-status    Check step progress")
        click.echo("    wait-for       Block until steps complete")
        click.echo("    artifact       Share files (upload/download/list)")
        click.echo()
        click.echo("  \033[2mRun 'tracecraft <command> --help' for details.\033[0m")
        click.echo()


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
