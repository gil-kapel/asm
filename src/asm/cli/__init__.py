"""CLI entry point — Click command group."""

from __future__ import annotations

import click

from asm import __version__
from asm.core.env import load_user_env

load_user_env()


def _quick_start(root_name: str) -> str:
    lines = [
        "Quick start:",
        f"  {root_name} init",
        f"  {root_name} search \"python cli\" --limit 5",
        f"  {root_name} add skill <source>",
        f"  {root_name} sync",
    ]
    return "\n".join(lines)


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


def _render_grouped_index(root: click.Command, root_name: str) -> str:
    if not isinstance(root, click.Group):
        return f"  {root_name}"

    groups: dict[str, list[str]] = {
        "Workspace": [],
        "Discovery": [],
        "Skills": [],
        "Versioning": [],
        "Lockfile": [],
    }
    fallback: list[str] = []

    def _push(path: str) -> None:
        if path.startswith(f"{root_name} init") or path.startswith(f"{root_name} sync"):
            groups["Workspace"].append(path)
            return
        if path.startswith(f"{root_name} search"):
            groups["Discovery"].append(path)
            return
        if path.startswith(f"{root_name} add") or path.startswith(f"{root_name} create"):
            groups["Skills"].append(path)
            return
        if path.startswith(f"{root_name} skill"):
            groups["Versioning"].append(path)
            return
        if path.startswith(f"{root_name} lock"):
            groups["Lockfile"].append(path)
            return
        fallback.append(path)

    for name in sorted(root.commands):
        cmd = root.commands[name]
        base = f"{root_name} {name}"
        _push(base)
        if isinstance(cmd, click.Group):
            for child_name in sorted(cmd.commands):
                _push(f"{base} {child_name}")

    lines: list[str] = []
    for section in ("Workspace", "Discovery", "Skills", "Versioning", "Lockfile"):
        entries = groups[section]
        if not entries:
            continue
        lines.append(f"{section}:")
        lines.extend(f"  {entry}" for entry in entries)
    if fallback:
        lines.append("Other:")
        lines.extend(f"  {entry}" for entry in fallback)

    return "\n".join(lines)


def _help_with_indexes(base: str, ctx: click.Context) -> str:
    root_ctx = ctx.find_root()
    root = root_ctx.command
    root_name = root_ctx.info_name or "asm"
    grouped = _render_grouped_index(root, root_name)
    full = _render_full_index(root, root_name)
    quick = _quick_start(root_name)
    return (
        f"{base}\n\n{quick}\n\nCommand index by workflow:\n{grouped}\n\n"
        f"Full command index:\n{full}"
    )


class ASMCommand(click.Command):
    """Click command that appends a full command index to help output."""

    def get_help(self, ctx: click.Context) -> str:
        base = super().get_help(ctx)
        return _help_with_indexes(base, ctx)


class ASMGroup(click.Group):
    """Click group that appends a full command index to help output."""

    command_class = ASMCommand
    group_class = type

    def get_help(self, ctx: click.Context) -> str:
        base = super().get_help(ctx)
        return _help_with_indexes(base, ctx)


@click.group(cls=ASMGroup)
@click.version_option(__version__, prog_name="asm")
def cli() -> None:
    """ASM — Agent Skill Manager.

    Manage SOTA expertise for IDE agents.
    """


# Register all sub-commands on import
from asm.cli import commands as _commands  # noqa: F401, E402
