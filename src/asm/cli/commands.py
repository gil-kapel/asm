"""CLI commands — init, search, add, create, sync, skill, lock."""

from __future__ import annotations

import subprocess
from pathlib import Path

import click

from asm.cli import cli
from asm.cli.ui import spinner
from asm.core import paths
from asm.services import integrations

ASM_WHEEL_URL = "https://github.com/gil-kapel/asm/releases/latest/download/asm-py3-none-any.whl"


# ── init ────────────────────────────────────────────────────────────


@cli.command()
@click.option("--name", default=None, help="Project name override (defaults to directory name).")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
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


# ── search ──────────────────────────────────────────────────────────


@cli.command()
@click.argument("query")
@click.option("--limit", default=10, type=int, show_default=True, help="Maximum results.")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root directory (optional context for ranking).",
)
def search(query: str, limit: int, root: str) -> None:
    """Federated skill discovery across curated index and remote providers.

    Matches query semantic similarity against verified skills (marked [curated])
    and remote providers (Smithery, Playbooks, GitHub, SkillsMP).

    Examples:
      asm search "python testing" --limit 5
      asm search "sqlmodel repository" --path /path/to/repo
    """
    from asm.services import discovery

    if limit < 1:
        raise click.ClickException("--limit must be >= 1")

    root_path = Path(root)
    with spinner() as status:
        status("Searching federated registries…")
        results = discovery.search(query, root=root_path, limit=limit)

    if not results:
        click.echo("ℹ No matches found.")
        click.echo("  Try broader keywords: 'python auth', 'react forms', or 'sql optimization'.")
        return

    click.echo(f"Found {len(results)} result(s):")
    for idx, item in enumerate(results, start=1):
        click.echo(f"{idx}. [{item.provider}] {item.name}")
        click.echo(f"   id: {item.identifier}")
        click.echo(f"   url: {item.url}")
        click.echo(f"   source: {item.install_source}")
        click.echo(f"   {item.description}")


# ── add ─────────────────────────────────────────────────────────────


@cli.group()
def add() -> None:
    """Add remote resources to the workspace."""


@add.command("skill")
@click.argument("source")
@click.option("--name", default=None, help="Override installed skill name, e.g. --name my-cli-skill.")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root directory.",
)
def add_skill(source: str, name: str | None, root: str) -> None:
    """Fetch a skill from GitHub, local path, or a registry prefix.

    SOURCE can be:

    \b
      ./local/path                      Local directory
      user/repo/path/to/skill           GitHub shorthand
      https://github.com/u/r/tree/b/p   Full GitHub URL
      local:./path                      Explicit local prefix
      github:user/repo/path             Explicit GitHub prefix
      gh:user/repo/path                 Short GitHub prefix
      smithery:namespace/skill          Smithery registry reference
      sm:namespace/skill                Short Smithery prefix
      playbooks:namespace/skill         Playbooks registry reference
      pb:namespace/skill                Short Playbooks prefix
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
    help="Source code to distill into the skill, e.g. --from ./src/asm/services/discovery.py.",
)
@click.option(
    "--ai",
    "use_llm",
    is_flag=True,
    default=False,
    help="Use LLM (LiteLLM) to generate SKILL.md content. Requires asm[llm] and API key.",
)
@click.option(
    "--model",
    "llm_model",
    default=None,
    envvar="ASM_LLM_MODEL",
    help="LiteLLM model string (e.g. openai/gpt-4o-mini, anthropic/claude-3-5-sonnet).",
)
@click.option(
    "--from-url",
    "source_url",
    default=None,
    metavar="URL",
    help="Fetch content from URL (e.g. GitHub API contents) and use as context for --ai.",
)
@click.option(
    "--from-repo",
    "source_repo",
    default=None,
    metavar="OWNER/REPO",
    help="Fetch DeepWiki docs for a GitHub repo and use as context for --ai.",
)
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root directory.",
)
def create_skill(
    name_arg: str,
    description: str,
    source_path: str | None,
    use_llm: bool,
    llm_model: str | None,
    source_url: str | None,
    source_repo: str | None,
    root: str,
) -> None:
    """Create a new skill package from scratch or distilled patterns.

    NAME is the kebab-case skill identifier.
    DESCRIPTION is a concise explanation for agent triggering.

    With --ai, uses LiteLLM to generate Instructions, Usage, and Examples.
    With --from-repo, analyzes a GitHub repo (README, structure, source)
    to extract sophisticated patterns into the skill.

    Examples:
      asm create skill cli-patterns "Reusable CLI command patterns"
      asm create skill discovery-notes "Discovery ranking guidance" --from ./src/asm/services/discovery.py
      asm create skill pdf-helper "Extract text from PDFs" --ai
      asm create skill sqlmodel-patterns "Async SQLModel usage" --from-repo tiangolo/sqlmodel
    """
    from asm.services import bootstrap, skills

    root_path = _require_workspace(root)

    deepwiki_context: str | None = None
    if source_repo:
        use_llm = True
        from asm.services.deepwiki import fetch_repo_docs, parse_repo_ref
        try:
            owner, repo = parse_repo_ref(source_repo)
            click.echo(f"  Fetching DeepWiki docs for {owner}/{repo}…")
            deepwiki_context = fetch_repo_docs(owner, repo)
            if not deepwiki_context:
                click.echo("  ⚠ No DeepWiki content found, proceeding without it.")
        except (ValueError, RuntimeError) as exc:
            click.echo(f"  ⚠ DeepWiki fetch failed: {exc}")

    try:
        with spinner() as status:
            skill_dir = skills.create_skill(
                root_path,
                name_arg,
                description,
                source_path,
                on_progress=status,
                use_llm=use_llm,
                llm_model=llm_model,
                source_url=source_url,
                deepwiki_context=deepwiki_context,
            )
    except (FileExistsError, ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc

    bootstrap.regenerate(root_path)
    _auto_sync(root_path)
    click.echo(f"✔ Created skill: {name_arg}")
    click.echo(f"  → {skill_dir}/SKILL.md")
    if source_path:
        click.echo(f"  Source distilled from: {source_path}")
    if source_url:
        click.echo(f"  Context from URL: {source_url[:60]}…" if len(source_url) > 60 else f"  Context from URL: {source_url}")
    if source_repo:
        click.echo(f"  Context from DeepWiki: {source_repo}")
    if use_llm:
        click.echo("  Content generated with LLM (LiteLLM)")


@create.command("expertise")
@click.argument("name_arg", metavar="NAME")
@click.argument("skills_list", nargs=-1, required=True, metavar="SKILL...")
@click.option("--description", "--desc", "description", required=True, help="Description of the expertise domain.")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root directory.",
)
def create_expertise_cmd(name_arg: str, skills_list: tuple[str, ...], description: str, root: str) -> None:
    """Bundle installed skills into a task-oriented expertise.

    NAME is the kebab-case expertise identifier.
    SKILL... are names of installed skills to bundle.

    Expertises provide a navigation index and relationship rules for agents.

    Examples:
      asm create expertise db-layer sql sqlmodel-database --desc "Database schema and migrations"
    """
    from asm.services import bootstrap, expertise

    root_path = _require_workspace(root)
    try:
        index_path = expertise.create_expertise(
            name_arg, description, list(skills_list), root_path,
        )
    except (ValueError, FileExistsError) as exc:
        raise click.ClickException(str(exc)) from exc

    bootstrap.regenerate(root_path)
    _auto_sync(root_path)
    click.echo(f"✔ Created expertise: {name_arg}")
    click.echo(f"  Skills: {', '.join(skills_list)}")
    click.echo(f"  → {index_path}")


# ── expertise ───────────────────────────────────────────────────────


@cli.group("expertise")
def expertise_group() -> None:
    """Expertise matching and autonomous skill selection."""


@expertise_group.command("suggest")
@click.argument("task_description")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root directory.",
)
def expertise_suggest(task_description: str, root: str) -> None:
    """Match a natural language task to existing expertises.

    Uses semantic similarity to rank bundles by relevance to your task.

    Examples:
      asm expertise suggest "write a database migration for users"
    """
    from asm.services import expertise

    root_path = _require_workspace(root)
    results = expertise.suggest(task_description, root_path)

    if not results:
        click.echo("ℹ No expertises found. Create one with `asm create expertise`.")
        return

    click.echo(f"Matching expertises for: \"{task_description}\"")
    for name, score in results:
        bar = "█" * int(score * 20) + "░" * (20 - int(score * 20))
        click.echo(f"  {bar} {score:.2f}  {name}")


@expertise_group.command("auto")
@click.argument("task_description")
@click.option(
    "--model",
    "llm_model",
    default=None,
    envvar="ASM_LLM_MODEL",
    help="LiteLLM model string for skill selection.",
)
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root directory.",
)
def expertise_auto(task_description: str, llm_model: str | None, root: str) -> None:
    """Autonomous expertise configuration: match, install, and sync.

    Finds the best matching expertise for your task. If no good match
    exists, uses AI to select relevant skills and creates a new bundle.
    Automatically installs missing skills and syncs agent context.

    Examples:
      asm expertise auto "build a REST API with database migrations"
    """
    from asm.services import bootstrap, expertise

    root_path = _require_workspace(root)

    try:
        with spinner() as status:
            status("Matching task to expertises…")
            name, skills_used = expertise.auto(
                task_description, root_path, model=llm_model,
            )
    except (ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc

    bootstrap.regenerate(root_path)
    _auto_sync(root_path)
    click.echo(f"✔ Expertise: {name}")
    click.echo(f"  Skills: {', '.join(skills_used)}")
    click.echo(f"  → .asm/expertises/{name}/index.md")


# ── sync ────────────────────────────────────────────────────────────


@cli.command()
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root directory.",
)
def sync(root: str) -> None:
    """Install missing skills and sync agent configuration.

    Reads the [skills] and [expertises] tables, fetches missing resources,
    verifies integrity, and regenerates IDE agent integration files.

    Like `uv sync` — run after cloning a repo or pulling changes.
    """
    import time

    from asm.services import bootstrap, skills
    from asm.services.skills import SkillSyncEvent

    root_path = _require_workspace(root)

    def _on_event(ev: SkillSyncEvent) -> None:
        ms = f" ({ev.elapsed_ms:.0f}ms)" if ev.elapsed_ms else ""
        match ev.action:
            case "verified":
                click.echo(f"  ✔ {ev.name}{ms}")
            case "up_to_date":
                click.echo(f"  ✔ {ev.name} (no lock entry)")
            case "drift":
                click.echo(f"  ⚠ {ev.name}: integrity drift{ms}")
            case "installing":
                click.echo(f"  ↓ {ev.name} ({ev.detail})…")
            case "installed":
                click.echo(f"  ✔ {ev.name} installed{ms}")
            case "failed":
                click.echo(f"  ✗ {ev.name}: {ev.detail}{ms}")

    t0 = time.monotonic()
    result = skills.sync_workspace(root_path, on_event=_on_event)
    dt = time.monotonic() - t0

    if result.removed_from_lock:
        click.echo(f"  • pruned {len(result.removed_from_lock)} stale lockfile entries")

    bootstrap.regenerate(root_path)
    _auto_sync(root_path)

    total = (
        len(result.installed) + len(result.up_to_date)
        + len(result.integrity_ok) + len(result.integrity_drift)
    )
    failed = len(result.failed)
    summary = f"✔ Synced {total} skill(s) in {dt:.1f}s"
    if failed:
        summary += f", {failed} failed"
    click.echo(summary)


# ── update ───────────────────────────────────────────────────────────


@cli.command("update")
def update() -> None:
    """Update ASM from official release wheel."""

    try:
        subprocess.run(["uv", "tool", "uninstall", "asm"], check=False)
        subprocess.run(
            ["uv", "tool", "install", "--reinstall", ASM_WHEEL_URL],
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise click.ClickException(f"Failed to update asm from release wheel: {exc}") from exc

    click.echo("✔ Updated asm from official release wheel")
    click.echo("  verify with: asm --version")


# ── skill versioning ────────────────────────────────────────────────


@cli.group("skill")
def skill_group() -> None:
    """Manage local skill versions and snapshots."""


@skill_group.command("commit")
@click.argument("name")
@click.option("-m", "--message", required=True, help="Commit message.")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root directory.",
)
def skill_commit(name: str, message: str, root: str) -> None:
    """Commit local changes of a skill.

    Examples:
      asm skill commit cli-builder -m "tighten option parsing checklist"
    """
    from asm.services import skills

    root_path = _require_workspace(root)
    try:
        entry = skills.skill_commit(root_path, name, message)
    except (ValueError, FileNotFoundError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"✔ Committed {name} r{entry.local_revision}")
    click.echo(f"  snapshot: {entry.snapshot_id}")


@skill_group.group("stash")
def skill_stash_group() -> None:
    """Save/apply temporary working snapshots."""


@skill_stash_group.command("push")
@click.argument("name")
@click.option("-m", "--message", default="", help="Optional stash note.")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root directory.",
)
def skill_stash_push(name: str, message: str, root: str) -> None:
    """Stash current skill working tree.

    Examples:
      asm skill stash push cli-builder -m "wip: improve examples"
    """
    from asm.services import skills

    root_path = _require_workspace(root)
    try:
        stash_id = skills.skill_stash_push(root_path, name, message)
    except (ValueError, FileNotFoundError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"✔ Stashed {name}: {stash_id}")


@skill_stash_group.command("apply")
@click.argument("name")
@click.argument("stash_id", required=False)
@click.option("--pop", is_flag=True, help="Drop the stash entry after applying it.")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root directory.",
)
def skill_stash_apply(name: str, stash_id: str | None, pop: bool, root: str) -> None:
    """Apply latest (or selected) stash for a skill.

    Examples:
      asm skill stash apply cli-builder
      asm skill stash apply cli-builder <stash-id> --pop
    """
    from asm.services import skills

    root_path = _require_workspace(root)
    try:
        entry = skills.skill_stash_apply(root_path, name, stash_id, pop=pop)
    except (ValueError, FileNotFoundError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"✔ Applied stash to {name}")
    click.echo(f"  snapshot: {entry.snapshot_id}")


@skill_group.command("tag")
@click.argument("name")
@click.argument("tag")
@click.argument("ref", required=False, default="HEAD")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root directory.",
)
def skill_tag(name: str, tag: str, ref: str, root: str) -> None:
    """Tag a skill snapshot (default: HEAD)."""
    from asm.services import skills

    root_path = _require_workspace(root)
    try:
        snapshot_id = skills.skill_tag(root_path, name, tag, ref)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"✔ Tagged {name}:{tag} -> {snapshot_id}")


@skill_group.command("checkout")
@click.argument("name")
@click.argument("ref")
@click.option("--force", is_flag=True, help="Discard uncommitted local changes.")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root directory.",
)
def skill_checkout(name: str, ref: str, force: bool, root: str) -> None:
    """Checkout a snapshot/tag into working skill dir."""
    from asm.services import skills

    root_path = _require_workspace(root)
    try:
        entry = skills.skill_checkout(root_path, name, ref, force=force)
    except (ValueError, FileNotFoundError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"✔ Checked out {name} -> {entry.snapshot_id}")
    click.echo(f"  local revision: r{entry.local_revision}")


@skill_group.command("history")
@click.argument("name")
@click.option("--limit", default=20, type=int, show_default=True, help="Maximum history entries.")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root directory.",
)
def skill_history(name: str, limit: int, root: str) -> None:
    """Show recent commit/import history for a skill.

    Examples:
      asm skill history cli-builder --limit 10
    """
    from asm.services import skills

    root_path = _require_workspace(root)
    entries = skills.skill_history(root_path, name, limit=limit)
    if not entries:
        click.echo("ℹ No history yet.")
        return
    for item in entries:
        click.echo(
            f"{item.get('created_at', '')} {item.get('kind', 'commit')} "
            f"r{item.get('local_revision', 0)} {item.get('snapshot_id', '')} "
            f"- {item.get('message', '')}",
        )


@skill_group.command("status")
@click.argument("name")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root directory.",
)
def skill_status(name: str, root: str) -> None:
    """Show unstaged changes for a skill."""
    from asm.services import skills

    root_path = _require_workspace(root)
    try:
        status = skills.skill_status(root_path, name)
    except (ValueError, FileNotFoundError) as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Skill: {status.name}")
    click.echo(f"Baseline snapshot: {status.snapshot_id}")
    if status.clean:
        click.echo("✔ Working tree clean")
        return

    for rel in status.added:
        click.echo(f"A  {rel}")
    for rel in status.modified:
        click.echo(f"M  {rel}")
    for rel in status.removed:
        click.echo(f"D  {rel}")


@skill_group.command("diff")
@click.argument("name")
@click.argument("rel_path", required=False)
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root directory.",
)
def skill_diff(name: str, rel_path: str | None, root: str) -> None:
    """Show unstaged unified diff for a skill (optionally one file)."""
    from asm.services import skills

    root_path = _require_workspace(root)
    try:
        diff_text = skills.skill_diff(root_path, name, rel_path=rel_path)
    except (ValueError, FileNotFoundError) as exc:
        raise click.ClickException(str(exc)) from exc

    if not diff_text:
        click.echo("✔ No unstaged changes")
        return
    click.echo(diff_text)


# ── lock ─────────────────────────────────────────────────────────────


@cli.group("lock")
def lock_group() -> None:
    """Manage asm.lock schema/versioning."""


@lock_group.command("migrate")
@click.option("--registry-id", default="default", show_default=True, help="Registry id to write in lock entries.")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root directory.",
)
def lock_migrate(registry_id: str, root: str) -> None:
    """Migrate asm.lock to the current lock schema."""
    from asm.repo import lockfile

    root_path = _require_workspace(root)
    changed = lockfile.migrate(paths.lock_path(root_path), registry_id=registry_id)
    if changed:
        click.echo("✔ Migrated asm.lock")
    else:
        click.echo("✔ asm.lock already up to date")


# ── helpers ─────────────────────────────────────────────────────────


def _require_workspace(root_str: str) -> Path:
    root = paths.resolve_root(Path(root_str))
    if not (root / paths.ASM_TOML).exists():
        raise click.ClickException(
            f"Not an ASM workspace: {root}\n"
            "Run `asm init --path <project-root>` first, then retry this command."
        )
    return root


def _resolve_sync_targets(root: Path, cfg, explicit: str | None) -> list[str]:
    """Determine sync targets by priority.

    Priority:
      1) explicit flag
      2) [agents] config
      3) runtime context inference
      4) project marker detection
      5) default to Cursor
    """
    if explicit:
        return [explicit]

    configured = [
        name for name in integrations.AGENTS
        if getattr(cfg.agents, name, False)
    ]
    if configured:
        return configured

    runtime_agents = integrations.detect_runtime_agents()
    if runtime_agents:
        return runtime_agents

    detected = integrations.detect_agents(root)
    if detected:
        return detected

    # Keep first-time UX simple: generate Cursor integration by default.
    return ["cursor"]


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
