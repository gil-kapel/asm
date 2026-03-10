"""CLI entry point — Click command group."""

from __future__ import annotations

import click

from asm import __version__
from asm.core.env import load_user_env

load_user_env()


class ASMCommand(click.Command):
    """Click command; help shows only this command's options."""


class ASMGroup(click.Group):
    """Click group; help shows only this group's options and subcommands."""

    command_class = ASMCommand
    group_class = type


@click.group(cls=ASMGroup)
@click.version_option(__version__, prog_name="asm")
def cli() -> None:
    """ASM — Agent Skill Manager. Manage expertise for IDE agents."""


# Register all sub-commands on import
from asm.cli import commands as _commands  # noqa: F401, E402
