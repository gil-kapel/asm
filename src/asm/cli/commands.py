"""CLI commands — init, add, create, sync."""

from __future__ import annotations

import subprocess
from pathlib import Path

import click

from asm.cli import cli
from asm.cli.ui import spinner
from asm.core import paths
from asm.services import integrations


# ── init ────────────────────────────────────────────────────────────


@cli.command()
@click.option("--name", default=None, help="Project name (defaults to directory name).")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root directory.",
)
def init(name: str | None, root: str) -> None:
    """Initialise an ASM workspace."""
    from asm.services import bootstrap

    root_path = Path(root)
    try:
        result = bootstrap.init_workspace(root_path, name)
    except FileExistsError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"✔ Initialised ASM workspace in {result}")
    click.echo(f"  → {result / paths.ASM_TOML}")
    click.echo(f"  → {result / paths.ASM_DIR / paths.MAIN_ASM_MD}")


# ── add ─────────────────────────────────────────────────────────────


@cli.group()
def add() -> None:
    """Add remote resources to the workspace."""


@add.command("skill")
@click.argument("source")
@click.option("--name", default=None, help="Override the skill name.")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root directory.",
)
def add_skill(source: str, name: str | None, root: str) -> None:
    """Fetch a skill from GitHub, local path, or Smithery.

    SOURCE can be:

    \b
      ./local/path                      Local directory
      user/repo/path/to/skill           GitHub shorthand
      https://github.com/u/r/tree/b/p   Full GitHub URL
      local:./path                      Explicit local prefix
      github:user/repo/path             Explicit GitHub prefix
    """
    from asm.services import bootstrap, skills

    root_path = _require_workspace(root)

    try:
        with spinner() as status:
            meta = skills.add_skill(root_path, source, name_override=name, on_progress=status)
    except (ValueError, FileNotFoundError, RuntimeError, subprocess.CalledProcessError) as exc:
        raise click.ClickException(str(exc)) from exc

    bootstrap.regenerate(root_path)
    _auto_sync(root_path)
    click.echo(f"✔ Installed skill: {meta.name}")
    click.echo(f"  {meta.description[:80]}")
    click.echo(f"  → .asm/skills/{meta.name}/SKILL.md")


# ── create ──────────────────────────────────────────────────────────


@cli.group()
def create() -> None:
    """Create new skills or expertises."""


@create.command("skill")
@click.argument("name_arg", metavar="NAME")
@click.argument("description")
@click.option(
    "--from", "source_path", default=None,
    type=click.Path(exists=True, resolve_path=True),
    help="Source code to distil into the skill.",
)
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root directory.",
)
def create_skill(name_arg: str, description: str, source_path: str | None, root: str) -> None:
    """Create a new skill package from scratch or from existing code.

    NAME is the kebab-case skill identifier.
    DESCRIPTION is a concise explanation for agent triggering.
    """
    from asm.services import bootstrap, skills

    root_path = _require_workspace(root)

    try:
        with spinner() as status:
            skill_dir = skills.create_skill(
                root_path, name_arg, description, source_path, on_progress=status,
            )
    except (FileExistsError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    bootstrap.regenerate(root_path)
    _auto_sync(root_path)
    click.echo(f"✔ Created skill: {name_arg}")
    click.echo(f"  → {skill_dir}/SKILL.md")
    if source_path:
        click.echo(f"  Source distilled from: {source_path}")


@create.command("expertise")
@click.argument("skills_list", nargs=-1, required=True, metavar="SKILL...")
@click.option("--desc", required=True, help="Description of the expertise domain.")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root directory.",
)
def create_expertise(skills_list: tuple[str, ...], desc: str, root: str) -> None:
    """Bundle skills into a named expertise with relationship rules.

    Generates expertise.toml and relationships.md for agent navigation.
    """
    raise click.ClickException("Not implemented yet — coming in Phase 3.")


# ── sync ────────────────────────────────────────────────────────────


@cli.command()
@click.option(
    "--agent", "agent_name", default=None,
    type=click.Choice(integrations.AGENTS, case_sensitive=False),
    help="Sync only this agent (default: auto-detect all).",
)
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root directory.",
)
def sync(agent_name: str | None, root: str) -> None:
    """Sync .asm/ skills into IDE agent config files.

    Auto-detects agents present in the workspace, or use --agent to
    target a specific one.
    """
    from asm.repo import config

    root_path = _require_workspace(root)
    cfg = config.load(root_path / paths.ASM_TOML)
    targets = _resolve_sync_targets(root_path, cfg, agent_name)

    if not targets:
        click.echo("No agents detected. Use --agent to specify one explicitly.")
        return

    results = integrations.sync_all(root_path, cfg, targets)
    for name, dest in results.items():
        rel = dest.relative_to(root_path) if dest.is_relative_to(root_path) else dest
        click.echo(f"✔ Synced {name} → {rel}")


# ── helpers ─────────────────────────────────────────────────────────


def _require_workspace(root_str: str) -> Path:
    root = paths.resolve_root(Path(root_str))
    if not (root / paths.ASM_TOML).exists():
        raise click.ClickException(f"Not an ASM workspace. Run 'asm init' first in {root}")
    return root


def _resolve_sync_targets(root: Path, cfg, explicit: str | None) -> list[str]:
    """Determine which agents to sync: explicit flag > [agents] config > auto-detect."""
    if explicit:
        return [explicit]

    configured = [
        name for name in integrations.AGENTS
        if getattr(cfg.agents, name, False)
    ]
    if configured:
        return configured

    return integrations.detect_agents(root)


def _auto_sync(root: Path) -> None:
    """Run agent sync silently after skill mutations."""
    from asm.repo import config

    cfg = config.load(root / paths.ASM_TOML)
    targets = _resolve_sync_targets(root, cfg, explicit=None)
    if targets:
        results = integrations.sync_all(root, cfg, targets)
        for name, dest in results.items():
            rel = dest.relative_to(root) if dest.is_relative_to(root) else dest
            click.echo(f"  ↻ synced {name} → {rel}")
