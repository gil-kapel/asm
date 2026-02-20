"""CLI entry point — Click command group."""

from __future__ import annotations

import click

from asm import __version__


@click.group()
@click.version_option(__version__, prog_name="asm")
def cli() -> None:
    """ASM — Agent Skill Manager.

    Manage SOTA expertise for IDE agents.
    """


# Register all sub-commands on import
from asm.cli import commands as _commands  # noqa: F401, E402
