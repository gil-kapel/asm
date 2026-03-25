"""CLI commands — init, search, add, create, sync, skill, lock."""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import click
from click.shell_completion import CompletionItem

from asm.cli import cli
from asm.cli.ui import spinner
from asm.core import paths
from asm.services import integrations

ASM_WHEEL_URL = "https://github.com/gil-kapel/asm/releases/latest/download/asm-py3-none-any.whl"
ASM_GIT_REPO = "https://github.com/gil-kapel/asm"


def _completion_root(ctx: click.Context) -> Path:
    root_value = ctx.params.get("root")
    if isinstance(root_value, str) and root_value.strip():
        return Path(root_value)
    return paths.resolve_root(Path.cwd())


def _complete_installed_skills(
    ctx: click.Context,
    _param: click.Parameter,
    incomplete: str,
) -> list[CompletionItem]:
    from asm.repo import config

    cfg_path = _completion_root(ctx) / paths.ASM_TOML
    if not cfg_path.exists():
        return []
    cfg = config.load(cfg_path)
    selected = set(ctx.params.get("skills_list", ()))
    return [
        CompletionItem(name)
        for name in sorted(cfg.skills)
        if name not in selected and name.startswith(incomplete)
    ]


def _complete_expertises(
    ctx: click.Context,
    _param: click.Parameter,
    incomplete: str,
) -> list[CompletionItem]:
    from asm.repo import config

    cfg_path = _completion_root(ctx) / paths.ASM_TOML
    if not cfg_path.exists():
        return []
    cfg = config.load(cfg_path)
    return [
        CompletionItem(name)
        for name in sorted(cfg.expertises)
        if name.startswith(incomplete)
    ]


def _complete_skill_refs(
    ctx: click.Context,
    _param: click.Parameter,
    incomplete: str,
) -> list[CompletionItem]:
    from asm.repo import snapshots

    skill_name = ctx.params.get("name")
    if not isinstance(skill_name, str) or not skill_name:
        return []
    history = snapshots.load_history(_completion_root(ctx), skill_name)
    refs = set(history.get("tags", {}).keys())
    refs.update(
        str(item.get("snapshot_id", ""))
        for item in history.get("commits", [])
        if item.get("snapshot_id")
    )
    return [
        CompletionItem(ref)
        for ref in sorted(refs)
        if ref.startswith(incomplete)
    ]


def _complete_stash_ids(
    ctx: click.Context,
    _param: click.Parameter,
    incomplete: str,
) -> list[CompletionItem]:
    skill_name = ctx.params.get("name")
    if not isinstance(skill_name, str) or not skill_name:
        return []
    stash_dir = paths.stash_dir(_completion_root(ctx)) / skill_name
    if not stash_dir.exists():
        return []
    return [
        CompletionItem(path.stem)
        for path in sorted(stash_dir.glob("*.json"))
        if path.stem.startswith(incomplete)
    ]


# ── init ────────────────────────────────────────────────────────────


@cli.command()
@click.option("--name", default=None, help="Project name (default: dir name).")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root.",
)
def init(name: str | None, root: str) -> None:
    """Initialize an ASM workspace."""
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
@click.option("--limit", default=10, type=int, show_default=True, help="Max results.")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project root (optional, biases ranking).",
)
def search(query: str, limit: int, root: str) -> None:
    """Search skill registries by natural-language query."""
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
    """Add resources to the workspace."""


@add.command("skill")
@click.argument("source")
@click.option("--name", default=None, help="Override installed skill name.")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root.",
)
def add_skill(source: str, name: str | None, root: str) -> None:
    """Add a skill from GitHub, path, or registry source."""
    from asm.services import bootstrap, skills

    root_path = _require_workspace(root)

    try:
        with spinner() as status:
            meta = skills.add_skill(root_path, source, name_override=name, on_progress=status)
    except (ValueError, FileNotFoundError, RuntimeError, subprocess.CalledProcessError) as exc:
        message = str(exc)
        hint = _hint_for_add_skill_source_error(source, message)
        if hint:
            message = f"{message}\n\n{hint}"
        raise click.ClickException(message) from exc

    bootstrap.regenerate(root_path)
    _auto_sync(root_path)
    click.echo(f"✔ Installed skill: {meta.name}")
    click.echo(f"  {meta.description[:80]}")
    click.echo(f"  → .asm/skills/{meta.name}/SKILL.md")


# ── create ──────────────────────────────────────────────────────────


@cli.group()
def create() -> None:
    """Create skills or expertises."""


@create.command("skill")
@click.argument("name_arg", metavar="NAME")
@click.argument("description")
@click.option("--from", "source_path", default=None, type=click.Path(exists=True, resolve_path=True), help="Source path to distill.")
@click.option("--ai", "use_llm", is_flag=True, default=False, help="Generate SKILL.md with LLM (requires API key).")
@click.option("--model", "llm_model", default=None, envvar="ASM_LLM_MODEL", help="OpenAI model.")
@click.option("--from-url", "source_url", default=None, metavar="URL", help="URL content as context for --ai.")
@click.option("--from-repo", "source_repo", default=None, metavar="OWNER/REPO", help="GitHub repo (DeepWiki) as context for --ai.")
@click.option(
    "--github-search",
    "github_search_query",
    default=None,
    metavar="QUERY",
    help="Search GitHub repos and enrich the skill with top matching repository context.",
)
@click.option(
    "--github-search-limit",
    default=3,
    type=int,
    show_default=True,
    help="Maximum GitHub repos to enrich from when --github-search is enabled.",
)
@click.option(
    "--improve",
    is_flag=True,
    default=False,
    help="Improve an existing local skill in place instead of recreating it.",
)
@click.option(
    "--override",
    is_flag=True,
    default=False,
    help="Replace an existing local skill with the newly generated version.",
)
@click.option(
    "--loop",
    "improvement_loop",
    is_flag=True,
    default=False,
    help="Iteratively build, locally analyze, and rewrite the skill until the target score or max tries.",
)
@click.option(
    "--target-score",
    default=0.9,
    type=float,
    show_default=True,
    help="Stop the loop once the local analysis overall score reaches this 0-1 threshold.",
)
@click.option(
    "--max-tries",
    default=5,
    type=int,
    show_default=True,
    help="Maximum build/analyze/rewrite attempts when --loop is enabled.",
)
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root.",
)
@click.option(
    "--verbose",
    is_flag=True,
    default=False,
    help="Print step-by-step create/loop progress instead of the inline spinner.",
)
def create_skill(
    name_arg: str,
    description: str,
    source_path: str | None,
    use_llm: bool,
    llm_model: str | None,
    source_url: str | None,
    source_repo: str | None,
    github_search_query: str | None,
    github_search_limit: int,
    improve: bool,
    override: bool,
    improvement_loop: bool,
    target_score: float,
    max_tries: int,
    root: str,
    verbose: bool,
) -> None:
    """Create or improve a skill (optionally from source, URL, or AI)."""
    from asm.services import bootstrap, skills

    root_path = _require_workspace(root)
    llm_enabled = use_llm or improvement_loop or improve

    deepwiki_context_parts: list[str] = []
    if source_repo:
        llm_enabled = True
        from asm.services.deepwiki import fetch_repo_docs, parse_repo_ref
        try:
            owner, repo = parse_repo_ref(source_repo)
            click.echo(f"  Fetching DeepWiki docs for {owner}/{repo}…")
            repo_context = fetch_repo_docs(owner, repo)
            if repo_context:
                deepwiki_context_parts.append(repo_context)
            else:
                click.echo("  ⚠ No DeepWiki content found, proceeding without it.")
        except (ValueError, RuntimeError) as exc:
            click.echo(f"  ⚠ DeepWiki fetch failed: {exc}")
    searched_repos: list[str] = []
    if github_search_query:
        llm_enabled = True
        from asm.services.deepwiki import fetch_search_context

        try:
            click.echo(f'  Searching GitHub for "{github_search_query}"…')
            search_context, matches = fetch_search_context(
                github_search_query,
                limit=github_search_limit,
            )
            if search_context:
                deepwiki_context_parts.append(search_context)
                searched_repos = [match.full_name for match in matches]
            else:
                click.echo("  ⚠ No GitHub repo context found, proceeding without it.")
        except (ValueError, RuntimeError) as exc:
            click.echo(f"  ⚠ GitHub search enrichment failed: {exc}")
    deepwiki_context = "\n\n".join(part for part in deepwiki_context_parts if part) or None

    def _verbose_progress(msg: str) -> None:
        click.echo(f"  {msg}")

    try:
        if verbose:
            create_result = skills.create_skill(
                root_path,
                name_arg,
                description,
                source_path,
                on_progress=_verbose_progress,
                use_llm=llm_enabled,
                llm_model=llm_model,
                source_url=source_url,
                deepwiki_context=deepwiki_context,
                improvement_loop=improvement_loop,
                target_score=target_score,
                max_tries=max_tries,
                improve=improve,
                override=override,
            )
        else:
            with spinner() as status:
                create_result = skills.create_skill(
                    root_path,
                    name_arg,
                    description,
                    source_path,
                    on_progress=status,
                    use_llm=llm_enabled,
                    llm_model=llm_model,
                    source_url=source_url,
                    deepwiki_context=deepwiki_context,
                    improvement_loop=improvement_loop,
                    target_score=target_score,
                    max_tries=max_tries,
                    improve=improve,
                    override=override,
                )
    except (FileExistsError, FileNotFoundError, ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc

    skill_dir = create_result.path if hasattr(create_result, "path") else create_result
    bootstrap.regenerate(root_path)
    _auto_sync(root_path)
    action_label = "Improved" if getattr(create_result, "action", "created") == "improved" else "Created"
    click.echo(f"✔ {action_label} skill: {name_arg}")
    click.echo(f"  → {skill_dir}/SKILL.md")
    if source_path:
        click.echo(f"  Source distilled from: {source_path}")
    if source_url:
        click.echo(f"  Context from URL: {source_url[:60]}…" if len(source_url) > 60 else f"  Context from URL: {source_url}")
    if source_repo:
        click.echo(f"  Context from DeepWiki: {source_repo}")
    if github_search_query:
        click.echo(f"  GitHub search query: {github_search_query}")
        if searched_repos:
            click.echo(f"  Enriched from repos: {', '.join(searched_repos)}")
    if llm_enabled:
        click.echo("  Content generated with LLM (OpenAI)")
    loop_summary = getattr(create_result, "loop", None)
    if loop_summary:
        if loop_summary.artifact_path:
            click.echo(
                f"  Loop score: {loop_summary.final_score:.2f} "
                f"(target {loop_summary.target_score:.2f}, tries {loop_summary.attempts}/{max_tries})"
            )
        else:
            click.echo(
                f"  Loop score: unavailable "
                f"(target {loop_summary.target_score:.2f}, tries {loop_summary.attempts}/{max_tries})"
            )
        click.echo(
            "  Loop status: reached target"
            if loop_summary.reached_target
            else "  Loop status: stopped before target"
        )
        if getattr(loop_summary, "stop_reason", ""):
            click.echo(f"  Loop stop reason: {loop_summary.stop_reason}")
        if loop_summary.artifact_path:
            click.echo(f"  Latest analysis artifact: {loop_summary.artifact_path}")


@create.command("expertise")
@click.argument("name_arg", metavar="NAME")
@click.argument(
    "skills_list",
    nargs=-1,
    required=True,
    metavar="SKILL...",
    shell_complete=_complete_installed_skills,
)
@click.option("--description", "--desc", "description", required=True, help="Expertise description.")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root.",
)
def create_expertise_cmd(name_arg: str, skills_list: tuple[str, ...], description: str, root: str) -> None:
    """Bundle installed skills into an expertise."""
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
    """Match tasks to expertises and run routing evals."""


@expertise_group.command("list")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root.",
)
def expertise_list(root: str) -> None:
    """List expertises defined in the workspace."""
    from asm.repo import config

    root_path = _require_workspace(root)
    cfg = config.load(root_path / paths.ASM_TOML)
    if not cfg.expertises:
        click.echo("ℹ No expertises. Create one with `asm create expertise`.")
        return
    for name in cfg.expertises:
        click.echo(f"- {name}")


@expertise_group.command("skills")
@click.argument("expertise_name", metavar="EXPERTISE", shell_complete=_complete_expertises)
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root.",
)
def expertise_skills(expertise_name: str, root: str) -> None:
    """List skills in an expertise."""
    from asm.repo import config

    root_path = _require_workspace(root)
    cfg = config.load(root_path / paths.ASM_TOML)
    ref = cfg.expertises.get(expertise_name)
    if not ref:
        available = ", ".join(cfg.expertises.keys()) or "none"
        raise click.ClickException(f"Expertise '{expertise_name}' not found. Available: {available}")
    if not ref.skills:
        click.echo("ℹ No skills in this expertise.")
        return
    for name in ref.skills:
        click.echo(f"- {name}")


@expertise_group.command("suggest")
@click.argument("task_description")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root.",
)
def expertise_suggest(task_description: str, root: str) -> None:
    """Suggest expertises for a task description."""
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
@click.option("--model", "llm_model", default=None, envvar="ASM_LLM_MODEL", help="OpenAI model.")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root.",
)
def expertise_auto(task_description: str, llm_model: str | None, root: str) -> None:
    """Auto-configure expertises for a task (install + sync)."""
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


@expertise_group.command("eval")
@click.option("--dataset", required=True, type=click.Path(exists=True, dir_okay=False, resolve_path=True), help="Benchmark file (.json/.jsonl).")
@click.option("--top-k", default=3, type=int, show_default=True, help="Top-k window.")
@click.option("--min-top1", default=None, type=float, help="Fail if top-1 below [0..1].")
@click.option("--min-topk", default=None, type=float, help="Fail if top-k below [0..1].")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root.",
)
def expertise_eval(
    dataset: str,
    top_k: int,
    min_top1: float | None,
    min_topk: float | None,
    root: str,
) -> None:
    """Run routing benchmark; optional min-top1/min-topk gates."""
    from asm.services import expertise

    if top_k < 1:
        raise click.ClickException("--top-k must be >= 1")
    _validate_gate_threshold("min-top1", min_top1)
    _validate_gate_threshold("min-topk", min_topk)

    root_path = _require_workspace(root)
    dataset_path = Path(dataset)

    try:
        with spinner() as status:
            status("Running routing benchmark…")
            report = expertise.evaluate_routing_dataset(root_path, dataset_path, top_k=top_k)
            expertise.enforce_routing_gates(report, min_top1=min_top1, min_topk=min_topk)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo("Routing benchmark report")
    click.echo(f"  dataset: {dataset_path}")
    click.echo(f"  cases: {report.total_cases}")
    click.echo(f"  top-1 accuracy: {report.top1_accuracy:.3f}")
    click.echo(f"  top-{report.top_k} hit-rate: {report.topk_hit_rate:.3f}")
    click.echo(f"  mean reciprocal rank: {report.mean_reciprocal_rank:.3f}")

    misses = [r for r in report.case_results if not r.is_top1_hit]
    if not misses:
        click.echo("  ✔ no top-1 misses")
        return

    click.echo(f"  ✗ top-1 misses: {len(misses)}")
    click.echo("  first 5 misses:")
    for row in misses[:5]:
        matched = row.matched_expertise or "none"
        topk = ", ".join(row.top_k_matches) if row.top_k_matches else "none"
        task_preview = row.task if len(row.task) <= 80 else f"{row.task[:77]}..."
        click.echo(f"    - expected={row.expected_expertise} matched={matched} topk=[{topk}]")
        click.echo(f"      task: {task_preview}")


# ── sync ────────────────────────────────────────────────────────────


@cli.command()
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root.",
)
def sync(root: str) -> None:
    """Install missing skills and regenerate agent config."""
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
    """Update asm from latest wheel or git."""

    try:
        subprocess.run(["uv", "tool", "uninstall", "asm"], check=False)

        # 1. Try wheel first
        result = subprocess.run(
            ["uv", "tool", "install", "--reinstall", ASM_WHEEL_URL],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            click.echo("✔ Updated asm from official release wheel")
        else:
            # 2. Fallback to git
            click.echo("  Release wheel not found or invalid. Updating from source (git)…")
            subprocess.run(
                ["uv", "tool", "install", "--reinstall", f"git+{ASM_GIT_REPO}"],
                check=True,
            )
            click.echo("✔ Updated asm from source (git)")

    except subprocess.CalledProcessError as exc:
        raise click.ClickException(f"Failed to update asm: {exc}") from exc

    click.echo("  verify with: asm --version")


# ── skill versioning ────────────────────────────────────────────────


@cli.group("skill")
def skill_group() -> None:
    """Skill versioning and snapshots."""


@skill_group.command("list")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root.",
)
def skill_list(root: str) -> None:
    """List skills registered in the workspace."""
    from asm.repo import config

    root_path = _require_workspace(root)
    cfg = config.load(root_path / paths.ASM_TOML)
    if not cfg.skills:
        click.echo("ℹ No skills. Add with `asm add skill` or create with `asm create skill`.")
        return
    for name in cfg.skills:
        click.echo(f"- {name}")


@skill_group.command("analyze")
@click.argument("name", shell_complete=_complete_installed_skills)
@click.option(
    "--local",
    "use_local",
    is_flag=True,
    default=False,
    help="Run local OpenAI-backed analysis using `ASM_LLM_MODEL`/`OPENAI_API_KEY`.",
)
@click.option(
    "--cloud",
    "use_cloud",
    is_flag=True,
    default=False,
    help="Run managed cloud analysis. Requires `ASM_CLOUD_API_URL` unless `--api-url` is passed.",
)
@click.option(
    "--api-url",
    default=None,
    help="Override the ASM cloud analyzer base URL for this run.",
)
@click.option(
    "--model",
    "llm_model",
    default=None,
    envvar="ASM_LLM_MODEL",
    help="OpenAI model for `--local` analysis. Defaults to `ASM_LLM_MODEL`.",
)
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root.",
)
def skill_analyze(
    name: str,
    use_local: bool,
    use_cloud: bool,
    api_url: str | None,
    llm_model: str | None,
    root: str,
) -> None:
    """Analyze and evaluate a skill locally or in the ASM cloud."""
    from asm.services import skill_analysis

    root_path = _require_workspace(root)
    if use_local and use_cloud:
        raise click.ClickException("Choose only one mode: `--local` or `--cloud`.")
    if not use_local and not use_cloud:
        raise click.ClickException(
            "Choose an analysis mode: `--local` or `--cloud`."
        )

    try:
        with spinner() as status:
            if use_local:
                status(f"Analyzing {name} with local LLM…")
                response, artifact_path = skill_analysis.analyze_skill_local(
                    root_path,
                    name,
                    model=llm_model,
                )
            else:
                status(f"Analyzing {name} in ASM cloud…")
                response, artifact_path = skill_analysis.analyze_skill_cloud(
                    root_path,
                    name,
                    api_url=api_url,
                )
    except (
        FileNotFoundError,
        ValueError,
        skill_analysis.LocalAnalysisError,
        skill_analysis.CloudAnalysisError,
    ) as exc:
        raise click.ClickException(str(exc)) from exc

    scorecard = response.scorecard
    click.echo(f"✔ Analyzed {name}")
    click.echo(f"  mode: {response.embedding_profile.analysis_mode}")
    click.echo(f"  status: {scorecard.status}")
    click.echo(
        "  scores: "
        f"trigger={scorecard.trigger_specificity:.2f} "
        f"novelty={scorecard.novelty:.2f} "
        f"grounding={scorecard.evidence_grounding:.2f} "
        f"duplication={scorecard.duplication_risk:.2f}"
    )
    click.echo(f"  analysis_id: {response.analysis_id}")
    click.echo(f"  analysis_version: {response.analysis_version}")
    if use_local:
        model_label = llm_model
        if not model_label and ":" in response.analysis_version:
            model_label = response.analysis_version.split(":", 1)[1]
        if model_label:
            click.echo(f"  model: {model_label}")
    if scorecard.improvement_prompt:
        click.echo("  improvement_prompt:")
        click.echo(textwrap.indent(scorecard.improvement_prompt, "    "))
    click.echo(f"  artifact: {artifact_path}")


@skill_group.command("share")
@click.argument("name", shell_complete=_complete_installed_skills)
@click.option(
    "--out",
    "out_dir",
    default=None,
    type=click.Path(file_okay=False, resolve_path=True),
    help="Output directory for share artifacts. Defaults to `dist/skills/` under the workspace root.",
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Replace an existing share folder/archive for this skill.",
)
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root.",
)
def skill_share(name: str, out_dir: str | None, overwrite: bool, root: str) -> None:
    """Package one local skill for sharing."""
    from asm.services import skills

    root_path = _require_workspace(root)
    try:
        share_dir, archive_path = skills.skill_share(
            root_path,
            name,
            out_dir=Path(out_dir) if out_dir else None,
            overwrite=overwrite,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"✔ Shared skill: {name}")
    click.echo(f"  folder: {share_dir}")
    click.echo(f"  archive: {archive_path}")
    click.echo("  next: publish the folder or zip to GitHub, a registry, or any public repo.")


@skill_group.command("commit")
@click.argument("name", shell_complete=_complete_installed_skills)
@click.option("-m", "--message", required=True, help="Commit message.")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root.",
)
def skill_commit(name: str, message: str, root: str) -> None:
    """Commit local skill changes."""
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
    """Stash or apply working snapshots."""


@skill_stash_group.command("push")
@click.argument("name", shell_complete=_complete_installed_skills)
@click.option("-m", "--message", default="", help="Stash note.")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root.",
)
def skill_stash_push(name: str, message: str, root: str) -> None:
    """Stash skill working tree."""
    from asm.services import skills

    root_path = _require_workspace(root)
    try:
        stash_id = skills.skill_stash_push(root_path, name, message)
    except (ValueError, FileNotFoundError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"✔ Stashed {name}: {stash_id}")


@skill_stash_group.command("apply")
@click.argument("name", shell_complete=_complete_installed_skills)
@click.argument("stash_id", required=False, shell_complete=_complete_stash_ids)
@click.option("--pop", is_flag=True, help="Drop stash after apply.")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root.",
)
def skill_stash_apply(name: str, stash_id: str | None, pop: bool, root: str) -> None:
    """Apply latest or selected stash."""
    from asm.services import skills

    root_path = _require_workspace(root)
    try:
        entry = skills.skill_stash_apply(root_path, name, stash_id, pop=pop)
    except (ValueError, FileNotFoundError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"✔ Applied stash to {name}")
    click.echo(f"  snapshot: {entry.snapshot_id}")


@skill_group.command("tag")
@click.argument("name", shell_complete=_complete_installed_skills)
@click.argument("tag")
@click.argument("ref", required=False, default="HEAD", shell_complete=_complete_skill_refs)
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root.",
)
def skill_tag(name: str, tag: str, ref: str, root: str) -> None:
    """Tag a skill snapshot (default HEAD)."""
    from asm.services import skills

    root_path = _require_workspace(root)
    try:
        snapshot_id = skills.skill_tag(root_path, name, tag, ref)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"✔ Tagged {name}:{tag} -> {snapshot_id}")


@skill_group.command("checkout")
@click.argument("name", shell_complete=_complete_installed_skills)
@click.argument("ref", shell_complete=_complete_skill_refs)
@click.option("--force", is_flag=True, help="Discard local changes.")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root.",
)
def skill_checkout(name: str, ref: str, force: bool, root: str) -> None:
    """Checkout snapshot/tag into skill dir."""
    from asm.services import skills

    root_path = _require_workspace(root)
    try:
        entry = skills.skill_checkout(root_path, name, ref, force=force)
    except (ValueError, FileNotFoundError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"✔ Checked out {name} -> {entry.snapshot_id}")
    click.echo(f"  local revision: r{entry.local_revision}")


@skill_group.command("history")
@click.argument("name", shell_complete=_complete_installed_skills)
@click.option("--limit", default=20, type=int, show_default=True, help="Max entries.")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root.",
)
def skill_history(name: str, limit: int, root: str) -> None:
    """Show skill commit/import history."""
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
@click.argument("name", shell_complete=_complete_installed_skills)
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root.",
)
def skill_status(name: str, root: str) -> None:
    """Show skill unstaged changes."""
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
@click.argument("name", shell_complete=_complete_installed_skills)
@click.argument("rel_path", required=False)
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root.",
)
def skill_diff(name: str, rel_path: str | None, root: str) -> None:
    """Show skill unstaged diff (optional: one file)."""
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
    """Lockfile schema and versioning."""


@lock_group.command("migrate")
@click.option("--registry-id", default="default", show_default=True, help="Registry id for lock entries.")
@click.option(
    "--path", "root", default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    show_default=True,
    help="Project root.",
)
def lock_migrate(registry_id: str, root: str) -> None:
    """Migrate asm.lock to current schema."""
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


def _validate_gate_threshold(name: str, value: float | None) -> None:
    if value is None:
        return
    if not 0.0 <= value <= 1.0:
        raise click.ClickException(f"--{name} must be between 0 and 1")


def _hint_for_add_skill_source_error(source: str, error_message: str) -> str:
    """Return a user-facing hint when add skill input looks like a bare name."""
    if "Cannot parse GitHub reference" not in error_message:
        return ""

    token = source.strip()
    if not token or "/" in token or ":" in token or "://" in token:
        return ""
    if token.startswith((".", "/", "~")):
        return ""

    return (
        "`asm add skill` expects a SOURCE reference, not a skill name.\n"
        "Try one of:\n"
        "  - asm add skill pb:openclaw/skills/sql\n"
        "  - asm add skill https://playbooks.com/skills/openclaw/skills/sql\n"
        "If the skill is already listed in `asm.toml`, run `asm sync`."
    )


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
