"""CLI entry point — Click command group."""

from __future__ import annotations

import click

from asm import __version__


def _render_full_index(root: click.Command, root_name: str) -> str:
    lines: list[str] = []

    def _walk(cmd: click.Command, prefix: str) -> None:
        lines.append(prefix)
        if isinstance(cmd, click.Group):
            for child_name in sorted(cmd.commands):
                child = cmd.commands[child_name]
                _walk(child, f"{prefix} {child_name}")

    _walk(root, root_name)
    return "\n".join(f"  {line}" for line in lines)


class ASMCommand(click.Command):
    """Click command that appends a full command index to help output."""

    def get_help(self, ctx: click.Context) -> str:
        base = super().get_help(ctx)
        root_ctx = ctx.find_root()
        root = root_ctx.command
        root_name = root_ctx.info_name or "asm"
        index = _render_full_index(root, root_name)
        return f"{base}\n\nFull command index:\n{index}"


class ASMGroup(click.Group):
    """Click group that appends a full command index to help output."""

    command_class = ASMCommand
    group_class = type

    def get_help(self, ctx: click.Context) -> str:
        base = super().get_help(ctx)
        root_ctx = ctx.find_root()
        root = root_ctx.command
        root_name = root_ctx.info_name or "asm"
        index = _render_full_index(root, root_name)
        return f"{base}\n\nFull command index:\n{index}"


@click.group(cls=ASMGroup)
@click.version_option(__version__, prog_name="asm")
def cli() -> None:
    """ASM — Agent Skill Manager.

    Manage SOTA expertise for IDE agents.
    """


# Register all sub-commands on import
from asm.cli import commands as _commands  # noqa: F401, E402
