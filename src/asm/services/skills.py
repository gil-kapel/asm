"""Skill service — high-level add / create / sync operations."""

from __future__ import annotations

import json
import getpass
import re
import shutil
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from asm.core import paths
from asm.core.frontmatter import extract_meta, validate
from asm.core.models import LockEntry, SkillEntry, SkillMeta
from asm.fetchers import fetch, parse_source
from asm.repo import config, lockfile, snapshots
from asm.templates import build_skill_md


@dataclass
class SkillCreationLoopSummary:
    """Summary of an optional local build/evaluate/improve loop."""

    attempts: int = 0
    target_score: float = 0.0
    final_score: float = 0.0
    reached_target: bool = False
    artifact_path: Path | None = None
    stop_reason: str = ""


@dataclass
class SkillCreateResult:
    """Return object for skill creation workflows."""

    path: Path
    loop: SkillCreationLoopSummary | None = None
    action: str = "created"


@dataclass
class SkillSourceContext:
    """Collected research context and existing support files for skill writing."""

    prompt_context: str | None = None
    supporting_files: list[str] = field(default_factory=list)


def _skill_md_from_llm(name: str, description: str, body: str) -> str:
    """Build full SKILL.md from LLM-generated description and body."""
    return "\n".join([
        "---",
        f"name: {name}",
        f"description: {description}",
        "---",
        "",
        body,
        "",
    ])


def _build_skill_source_context(
    skill_dir: Path,
    source_path: str | None,
    *,
    source_url: str | None,
    deepwiki_context: str | None,
    emit: Callable[[str], None],
) -> SkillSourceContext:
    """Collect optional source context for LLM-backed skill generation."""
    parts: list[str] = []
    supporting_files: list[str] = []
    if source_path:
        src = Path(source_path).resolve()
        if src.is_file():
            parts.append(src.read_text()[:8000])
        elif src.is_dir():
            for file_path in sorted(src.rglob("*"))[:30]:
                if file_path.is_file() and file_path.suffix in (".py", ".md", ".txt", ".toml"):
                    try:
                        parts.append(f"### {file_path.name}\n{file_path.read_text()[:1500]}")
                    except Exception:
                        continue
    if source_url:
        emit("Fetching content from URL…")
        from asm.services import url_content

        try:
            url_text = url_content.fetch_url_content(source_url, max_chars=40_000)
            parts.append(f"## Content from URL\n\n{url_text}")
            supporting_files.append(
                _write_generated_reference(
                    skill_dir,
                    "url-context.md",
                    f"# Source URL Context\n\nSource: {source_url}\n\n{url_text}\n",
                )
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch --from-url: {exc}") from exc
    if deepwiki_context:
        parts.append(f"## DeepWiki Documentation\n\n{deepwiki_context}")
        supporting_files.append(
            _write_generated_reference(
                skill_dir,
                "research-context.md",
                f"# GitHub Research Context\n\n{deepwiki_context}\n",
            )
        )
    if not parts:
        return SkillSourceContext(
            prompt_context=None,
            supporting_files=_supporting_skill_files(skill_dir),
        )
    return SkillSourceContext(
        prompt_context="\n\n".join(parts)[:50_000],
        supporting_files=_supporting_skill_files(skill_dir, seed_files=supporting_files),
    )


def _write_generated_reference(skill_dir: Path, filename: str, content: str) -> str:
    """Persist generated research context as a real file in the skill package."""
    references_dir = skill_dir / "references"
    references_dir.mkdir(parents=True, exist_ok=True)
    target = references_dir / filename
    target.write_text(content[:50_000], encoding="utf-8")
    return target.relative_to(skill_dir).as_posix()


def _supporting_skill_files(skill_dir: Path, *, seed_files: list[str] | None = None) -> list[str]:
    """List the real support files available for SKILL.md to reference."""
    files = set(seed_files or [])
    for folder_name in ("references", "examples", "scripts", "assets"):
        folder = skill_dir / folder_name
        if not folder.exists():
            continue
        for file_path in sorted(folder.rglob("*")):
            if file_path.is_file():
                files.add(file_path.relative_to(skill_dir).as_posix())
    return sorted(files)


def add_skill(
    root: Path,
    source_raw: str,
    name_override: str | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> SkillMeta:
    """Fetch, validate, and install a skill into .asm/skills/.

    Updates asm.toml and asm.lock.
    """
    emit = on_progress or (lambda _msg: None)

    source_type, location = parse_source(source_raw)

    _guard_duplicate(root, location, name_override)

    emit(
        "Copying from local path…"
        if source_type == "local"
        else "Fetching skill…"
    )
    dest_tmp = Path(tempfile.mkdtemp()) / "staging"
    extra = fetch(source_type, location, dest_tmp, root=root)

    emit("Validating SKILL.md…")
    ok, msg = _validate_with_name_fallback(dest_tmp, location)
    if not ok:
        shutil.rmtree(dest_tmp.parent, ignore_errors=True)
        raise ValueError(
            f"Skill validation failed: {msg}. "
            "Check SKILL.md frontmatter (name/description) or install with --name <kebab-case>."
        )

    meta = extract_meta(dest_tmp)
    skill_name = _resolve_name(name_override, meta.name, location, dest_tmp)
    meta = SkillMeta(name=skill_name, description=meta.description, version=meta.version)

    emit(f"Installing {skill_name}…")
    final_dest = _install(dest_tmp, paths.skills_dir(root) / skill_name)

    source_label = extra.get("registry_source") or _normalise_source(source_raw, source_type)

    emit("Updating asm.toml…")
    _register_config(root, skill_name, source_label)

    emit("Locking integrity hash…")
    _register_lock(root, skill_name, source_label, final_dest, extra, event_kind="import")

    return meta


def create_skill(
    root: Path,
    skill_name: str,
    description: str,
    source_path: str | None = None,
    on_progress: Callable[[str], None] | None = None,
    *,
    use_llm: bool = False,
    llm_model: str | None = None,
    source_url: str | None = None,
    deepwiki_context: str | None = None,
    improvement_loop: bool = False,
    target_score: float = 0.9,
    max_tries: int = 5,
    override: bool = False,
    improve: bool = False,
) -> SkillCreateResult:
    """Scaffold a new SKILL.md package and register it.

    When use_llm is True, calls the LLM service (LiteLLM) to generate
    description and body; requires provider API key (e.g. OPENAI_API_KEY).
    When source_url is set (e.g. GitHub API contents URL), fetches that
    content and uses it as additional context for the LLM.
    When deepwiki_context is set, includes DeepWiki-generated repo docs
    as additional context for the LLM.
    """
    emit = on_progress or (lambda _msg: None)
    if max_tries < 1:
        raise ValueError("--max-tries must be >= 1")
    if not 0.0 <= target_score <= 1.0:
        raise ValueError("--target-score must be between 0.0 and 1.0")
    if improve and override:
        raise ValueError("--improve and --override cannot be used together")
    if improvement_loop or improve:
        use_llm = True

    if improve:
        return _improve_skill(
            root,
            skill_name,
            description,
            source_path,
            emit=emit,
            llm_model=llm_model,
            source_url=source_url,
            deepwiki_context=deepwiki_context,
            improvement_loop=improvement_loop,
            target_score=target_score,
            max_tries=max_tries,
        )

    return _create_new_skill(
        root,
        skill_name,
        description,
        source_path,
        emit=emit,
        use_llm=use_llm,
        llm_model=llm_model,
        source_url=source_url,
        deepwiki_context=deepwiki_context,
        improvement_loop=improvement_loop,
        target_score=target_score,
        max_tries=max_tries,
        override=override,
    )


def _create_new_skill(
    root: Path,
    skill_name: str,
    description: str,
    source_path: str | None,
    *,
    emit: Callable[[str], None],
    use_llm: bool,
    llm_model: str | None,
    source_url: str | None,
    deepwiki_context: str | None,
    improvement_loop: bool,
    target_score: float,
    max_tries: int,
    override: bool,
) -> SkillCreateResult:
    skill_dir = paths.skills_dir(root) / skill_name
    if skill_dir.exists():
        if not override:
            raise FileExistsError(f"Skill already exists: {skill_dir}")
        emit("Overriding existing skill directory…")
        shutil.rmtree(skill_dir)
        analysis_dir = paths.skill_analysis_dir(root, skill_name)
        if analysis_dir.exists():
            emit("Clearing previous analysis artifact…")
            shutil.rmtree(analysis_dir)

    emit("Scaffolding skill directory…")
    skill_dir.mkdir(parents=True)

    source_context = _build_skill_source_context(
        skill_dir,
        source_path,
        source_url=source_url,
        deepwiki_context=deepwiki_context,
        emit=emit,
    )

    if source_path:
        emit("Ingesting source code…")
        _ingest_source(Path(source_path).resolve(), skill_dir)
        source_context.supporting_files = _supporting_skill_files(skill_dir, seed_files=source_context.supporting_files)

    loop_summary: SkillCreationLoopSummary | None = None
    if use_llm:
        from asm.services import llm, skill_analysis

        emit("Generating content with LLM…")
        desc, body = llm.generate_skill_content(
            skill_name,
            description,
            source_context.prompt_context,
            model=llm_model,
            supporting_files=source_context.supporting_files,
        )
        skill_md = _skill_md_from_llm(skill_name, desc, body)
        (skill_dir / "SKILL.md").write_text(skill_md)

        # Materialize any missing support files referenced by the freshly
        # generated SKILL.md. This prevents the "SKILL.md mentions files, but
        # files don't exist" failure mode when the loop stops before the
        # rewrite/materialize stage.
        _materialize_missing_support_files_from_skill_md(
            skill_dir,
            emit=emit,
            skill_name=skill_name,
            model=llm_model,
        )

        if improvement_loop:
            graph_result = skill_analysis.run_local_improvement_graph(
                root,
                skill_name,
                model=llm_model,
                target_score=target_score,
                max_tries=max_tries,
                on_progress=emit,
            )
            loop_summary = SkillCreationLoopSummary(
                attempts=graph_result.attempts,
                target_score=graph_result.target_score,
                final_score=graph_result.final_score,
                reached_target=graph_result.reached_target,
                artifact_path=graph_result.artifact_path,
                stop_reason=graph_result.stop_reason,
            )
    else:
        title = " ".join(w.capitalize() for w in skill_name.split("-"))
        (skill_dir / "SKILL.md").write_text(
            build_skill_md(skill_name, title, description, source_path)
        )

    _register_local_skill(root, skill_name, skill_dir, emit=emit, event_kind="create")
    return SkillCreateResult(path=skill_dir, loop=loop_summary, action="created")


def _improve_skill(
    root: Path,
    skill_name: str,
    improvement_goal: str,
    source_path: str | None,
    *,
    emit: Callable[[str], None],
    llm_model: str | None,
    source_url: str | None,
    deepwiki_context: str | None,
    improvement_loop: bool,
    target_score: float,
    max_tries: int,
) -> SkillCreateResult:
    from asm.services import llm

    skill_dir = _require_skill_dir(root, skill_name)
    source_context = _build_skill_source_context(
        skill_dir,
        source_path,
        source_url=source_url,
        deepwiki_context=deepwiki_context,
        emit=emit,
    )

    if source_path:
        emit("Ingesting source code…")
        _ingest_source(Path(source_path).resolve(), skill_dir)
        source_context.supporting_files = _supporting_skill_files(
            skill_dir,
            seed_files=source_context.supporting_files,
        )

    emit("Improving existing skill with LLM…")
    current_skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    revised_desc, revised_body = llm.revise_skill_content(
        skill_name,
        current_skill_md,
        _build_improvement_request(
            improvement_goal,
            source_context.prompt_context,
            current_skill_md=current_skill_md,
            supporting_files=source_context.supporting_files,
        ),
        model=llm_model,
        supporting_files=source_context.supporting_files,
    )
    (skill_dir / "SKILL.md").write_text(
        _skill_md_from_llm(skill_name, revised_desc, revised_body),
        encoding="utf-8",
    )
    _materialize_missing_support_files_from_skill_md(
        skill_dir,
        emit=emit,
        skill_name=skill_name,
        model=llm_model,
    )

    loop_summary = _run_skill_improvement_loop(
        root,
        skill_name,
        llm_model=llm_model,
        improvement_loop=improvement_loop,
        target_score=target_score,
        max_tries=max_tries,
        emit=emit,
    )
    _register_local_skill(root, skill_name, skill_dir, emit=emit, event_kind="update")
    return SkillCreateResult(path=skill_dir, loop=loop_summary, action="improved")


def _build_improvement_request(
    improvement_goal: str,
    prompt_context: str | None,
    *,
    current_skill_md: str,
    supporting_files: list[str],
) -> str:
    parts = [f"User-requested improvement goal:\n{improvement_goal.strip()}"]
    if prompt_context:
        parts.append(f"Additional fresh context:\n{prompt_context}")
    from asm.services import llm

    runtime_preference = llm.infer_runtime_preference(
        text_blobs=[improvement_goal, prompt_context or "", current_skill_md],
        supporting_files=supporting_files,
    )
    runtime_guidance = llm.render_runtime_guidance(runtime_preference).strip()
    if runtime_guidance:
        parts.append(f"Implementation/runtime constraint:\n{runtime_guidance}")
    return "\n\n".join(part for part in parts if part).strip()


def _run_skill_improvement_loop(
    root: Path,
    skill_name: str,
    *,
    llm_model: str | None,
    improvement_loop: bool,
    target_score: float,
    max_tries: int,
    emit: Callable[[str], None],
) -> SkillCreationLoopSummary | None:
    if not improvement_loop:
        return None

    from asm.services import skill_analysis

    graph_result = skill_analysis.run_local_improvement_graph(
        root,
        skill_name,
        model=llm_model,
        target_score=target_score,
        max_tries=max_tries,
        on_progress=emit,
    )
    return SkillCreationLoopSummary(
        attempts=graph_result.attempts,
        target_score=graph_result.target_score,
        final_score=graph_result.final_score,
        reached_target=graph_result.reached_target,
        artifact_path=graph_result.artifact_path,
        stop_reason=graph_result.stop_reason,
    )


def _register_local_skill(
    root: Path,
    skill_name: str,
    skill_dir: Path,
    *,
    emit: Callable[[str], None],
    event_kind: str,
) -> None:
    source_label = f"local:.asm/skills/{skill_name}"

    emit("Updating asm.toml…")
    _register_config(root, skill_name, source_label)

    emit("Locking integrity hash…")
    _register_lock(root, skill_name, source_label, skill_dir, {}, event_kind=event_kind)


def _materialize_missing_support_files_from_skill_md(
    skill_dir: Path,
    *,
    emit: Callable[[str], None],
    skill_name: str,
    model: str | None = None,
    max_files: int = 8,
) -> int:
    """Create missing `references/`, `examples/`, `scripts/`, `assets/` files mentioned in SKILL.md."""
    import re

    skill_md_path = skill_dir / "SKILL.md"
    if not skill_md_path.exists():
        return 0

    text = skill_md_path.read_text(encoding="utf-8", errors="ignore")

    # Extract niche examples block to seed materialized files with consistent usage guidance.
    niche_match = re.search(
        r"^##\s+Niche Examples\s*$\n(?P<body>.*?)(?=^##\s+|\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    niche_examples = niche_match.group("body").strip() if niche_match else ""

    # Extract referenced support paths (explicit relative paths).
    referenced_paths = []
    pattern = r"(?:references|examples|scripts|assets)/[A-Za-z0-9._/\-]+(?:\.[A-Za-z0-9]+)?"
    for p in re.findall(pattern, text):
        p = p.strip().strip("`").rstrip(").,:;")
        if not p:
            continue
        if p not in referenced_paths:
            referenced_paths.append(p)

    created = 0
    skill_dir_resolved = skill_dir.resolve()
    current_skill_md = text
    existing_supporting_files = _supporting_skill_files(skill_dir)
    referenced_paths, current_skill_md = _normalize_support_paths_for_runtime(
        referenced_paths,
        current_skill_md,
        existing_supporting_files,
    )
    if current_skill_md != text:
        skill_md_path.write_text(current_skill_md, encoding="utf-8")
    for rel_path in referenced_paths[:max_files]:
        target = skill_dir / rel_path
        try:
            if not str(target.resolve()).startswith(str(skill_dir_resolved) + "/"):
                continue
        except FileNotFoundError:
            # target doesn't exist yet; safe-check via parent
            if not str(target.parent.resolve()).startswith(str(skill_dir_resolved) + "/"):
                continue

        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        content = _fallback_materialized_support_content(
            rel_path,
            niche_examples=niche_examples,
        )
        try:
            from asm.services import llm

            content = llm.generate_support_file_content(
                skill_name,
                current_skill_md,
                rel_path,
                niche_examples=niche_examples,
                model=model,
                supporting_files=existing_supporting_files,
            )
        except Exception:
            pass
        target.write_text(content, encoding="utf-8")
        emit(f"Materialized support file: {rel_path}")
        created += 1
        existing_supporting_files = _supporting_skill_files(
            skill_dir,
            seed_files=existing_supporting_files + [rel_path],
        )

    return created


def _normalize_support_paths_for_runtime(
    referenced_paths: list[str],
    current_skill_md: str,
    supporting_files: list[str],
) -> tuple[list[str], str]:
    """Normalize conflicting script paths to the inferred runtime preference."""
    from asm.services import llm

    runtime_preference = llm.infer_runtime_preference(
        text_blobs=[current_skill_md],
        supporting_files=supporting_files,
    )
    normalized_paths: list[str] = []
    normalized_skill_md = current_skill_md
    for rel_path in referenced_paths:
        normalized = _normalize_support_path_for_runtime(rel_path, runtime_preference)
        if normalized != rel_path:
            normalized_skill_md = normalized_skill_md.replace(rel_path, normalized)
        if normalized not in normalized_paths:
            normalized_paths.append(normalized)
    return normalized_paths, normalized_skill_md


def _normalize_support_path_for_runtime(rel_path: str, runtime_preference: str) -> str:
    """Rewrite obviously conflicting runnable script paths for the inferred runtime."""
    if runtime_preference != "python":
        return rel_path
    path = Path(rel_path)
    if not path.parts or path.parts[0] != "scripts":
        return rel_path
    if path.suffix.lower() not in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
        return rel_path
    return path.with_suffix(".py").as_posix()


def _fallback_materialized_support_content(
    rel_path: str,
    *,
    niche_examples: str,
) -> str:
    """Fallback content when support-file LLM generation fails."""
    target = Path(rel_path)
    suffix = target.suffix.lower()
    if suffix in {".md", ".txt", ".markdown"}:
        title = target.stem.replace("-", " ").title()
        examples_block = niche_examples or "(No `## Niche Examples` section found in SKILL.md.)"
        return "\n".join(
            [
                f"# {title}",
                "",
                "Generated by ASM as a minimal, evidence-backed usage file.",
                "Edit/extend this file as you refine the skill.",
                "",
                "## Niche Examples",
                "",
                examples_block,
                "",
                "## Quick Start",
                "",
                "1) Locate the main entrypoint for this skill.",
                "2) Follow the niche example narrative for the exact workflow.",
                "3) Verify outputs by checking the referenced artifact paths.",
                "",
            ]
        )

    examples_block = niche_examples or "(No `## Niche Examples` section found in SKILL.md.)"
    if suffix == ".py":
        return "\n".join(
            [
                "#!/usr/bin/env python3",
                "\"\"\"Minimal runnable helper for replay/trace workflows.\"\"\"",
                "",
                "from __future__ import annotations",
                "",
                "import argparse",
                "import json",
                "from pathlib import Path",
                "",
                "",
                "def main():",
                "    ap = argparse.ArgumentParser()",
                "    ap.add_argument('--trace', required=True, help='CDP trace JSON file')",
                "    ap.add_argument('--out-dir', required=False, default='.', help='Output directory')",
                "    args = ap.parse_args()",
                "    trace_path = Path(args.trace)",
                "    out_dir = Path(args.out_dir)",
                "    out_dir.mkdir(parents=True, exist_ok=True)",
                "    data = json.loads(trace_path.read_text(encoding='utf-8'))",
                "    steps = len(data) if isinstance(data, list) else 1",
                "    out_path = out_dir / 'replay_summary.json'",
                "    out_path.write_text(json.dumps({'trace_path': trace_path.as_posix(), 'step_count_estimate': steps}, indent=2), encoding='utf-8')",
                "    print(f'Wrote {out_path.as_posix()}')",
                "",
                "",
                "if __name__ == '__main__':",
                "    main()",
                "",
            ]
        )
    if suffix == ".sh":
        return "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "",
                "scenario=\"\"",
                "out_dir=\".\"",
                "",
                "while [[ $# -gt 0 ]]; do",
                "  case \"$1\" in",
                "    --scenario) scenario=\"$2\"; shift 2 ;;",
                "    --out) out_dir=\"$2\"; shift 2 ;;",
                "    *) echo \"Unknown arg: $1\"; exit 2 ;;",
                "  esac",
                "done",
                "",
                "if [[ -z \"$scenario\" ]]; then",
                "  echo \"--scenario is required\"",
                "  exit 2",
                "fi",
                "",
                "mkdir -p \"$out_dir/artifacts\"",
                "echo \"{\\\"scenario\\\": \\\"$scenario\\\"}\" > \"$out_dir/artifacts/trace.json\"",
                "echo \"<html><body>placeholder</body></html>\" > \"$out_dir/artifacts/dom.html\"",
                "echo \"Wrote artifacts to $out_dir/artifacts\"",
                "",
            ]
        )
    return "\n".join(
        [
            "#!/usr/bin/env sh",
            "echo \"Generated minimal artifact.\"",
            *[f"# {line}" for line in examples_block.splitlines()[:10]],
            "",
        ]
    )


# ── Sync (like uv sync) ─────────────────────────────────────────────


@dataclass
class SkillSyncEvent:
    """Progress report for a single skill during sync."""

    name: str
    action: str  # "verified" | "up_to_date" | "installing" | "installed" | "drift" | "failed"
    detail: str = ""
    elapsed_ms: float = 0


@dataclass
class SyncResult:
    """Summary of a sync_workspace run."""

    installed: list[str] = field(default_factory=list)
    up_to_date: list[str] = field(default_factory=list)
    integrity_ok: list[str] = field(default_factory=list)
    integrity_drift: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    removed_from_lock: list[str] = field(default_factory=list)


@dataclass
class SkillWorkingStatus:
    """Unstaged change status for one skill working tree."""

    name: str
    snapshot_id: str
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (self.added or self.modified or self.removed)


def sync_workspace(
    root: Path,
    on_event: Callable[[SkillSyncEvent], None] | None = None,
    *,
    parallel: int = 4,
) -> SyncResult:
    """Reconcile .asm/skills/ with asm.toml — install missing, verify existing.

    Fetches missing skills in parallel (up to *parallel* workers).
    Calls *on_event* for each skill with structured progress updates.
    """
    import time

    emit = on_event or (lambda _e: None)
    result = SyncResult()

    cfg_path = root / paths.ASM_TOML
    cfg = config.load(cfg_path)
    lock = lockfile.load(paths.lock_path(root))

    skills_root = paths.skills_dir(root)
    skills_root.mkdir(parents=True, exist_ok=True)

    to_fetch: list[tuple[str, SkillEntry]] = []

    for name, entry in cfg.skills.items():
        skill_dir = skills_root / name
        installed = skill_dir.exists() and (skill_dir / "SKILL.md").exists()

        if installed:
            locked = lock.get(name)
            if locked and locked.integrity:
                t0 = time.monotonic()
                ok = lockfile.verify(skill_dir, locked.integrity)
                dt = (time.monotonic() - t0) * 1000
                if ok:
                    result.integrity_ok.append(name)
                    emit(SkillSyncEvent(name, "verified", elapsed_ms=dt))
                else:
                    result.integrity_drift.append(name)
                    emit(SkillSyncEvent(name, "drift", "integrity changed since lock", dt))
            else:
                result.up_to_date.append(name)
                emit(SkillSyncEvent(name, "up_to_date"))
            continue

        to_fetch.append((name, entry))

    if to_fetch:
        _parallel_fetch(root, to_fetch, lock, result, emit, parallel)

    stale = set(lock) - set(cfg.skills)
    for name in stale:
        del lock[name]
        result.removed_from_lock.append(name)

    lockfile.save(lock, paths.lock_path(root))

    return result


def _parallel_fetch(
    root: Path,
    skills: list[tuple[str, SkillEntry]],
    lock: dict[str, LockEntry],
    result: SyncResult,
    emit: Callable[[SkillSyncEvent], None],
    max_workers: int,
) -> None:
    """Fetch multiple skills concurrently."""
    import threading
    import time

    lock_mutex = threading.Lock()

    def _do_fetch(
        name: str, source: str, existing: LockEntry | None,
    ) -> tuple[str, LockEntry | None, str]:
        """Returns (name, lock_entry_or_None, error_msg)."""
        try:
            entry = _fetch_and_install_entry(root, name, source, existing)
            return name, entry, ""
        except Exception as exc:
            return name, None, str(exc)

    workers = min(max_workers, len(skills))

    for name, _ in skills:
        emit(SkillSyncEvent(name, "installing", parse_source(_.source)[0]))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_do_fetch, name, entry.source, lock.get(name)): (name, time.monotonic())
            for name, entry in skills
        }
        for future in as_completed(futures):
            name, t0 = futures[future]
            dt = (time.monotonic() - t0) * 1000
            skill_name, lock_entry, err = future.result()

            if err:
                result.failed[skill_name] = err
                emit(SkillSyncEvent(skill_name, "failed", err, dt))
            else:
                result.installed.append(skill_name)
                with lock_mutex:
                    lock[skill_name] = lock_entry
                emit(SkillSyncEvent(skill_name, "installed", elapsed_ms=dt))


def _fetch_and_install_entry(
    root: Path, name: str, source: str, existing: LockEntry | None = None,
) -> LockEntry:
    """Fetch, validate, install a single skill. Returns its LockEntry."""
    source_type, location = parse_source(source)

    dest_tmp = Path(tempfile.mkdtemp()) / "staging"
    extra = fetch(source_type, location, dest_tmp, root=root)

    ok, msg = _validate_with_name_fallback(dest_tmp, location)
    if not ok:
        shutil.rmtree(dest_tmp.parent, ignore_errors=True)
        raise ValueError(
            f"Validation failed: {msg}. "
            "Fix the source SKILL.md frontmatter, then run `asm sync` again."
        )

    meta = extract_meta(dest_tmp)
    final_dest = _install(dest_tmp, paths.skills_dir(root) / name)
    snapshot_id = snapshots.ensure_snapshot(root, name, final_dest)
    integrity = lockfile.compute_integrity(final_dest)
    return _build_lock_entry(
        meta, source_type, location, extra, existing, snapshot_id, integrity,
    )


# ── Private helpers ─────────────────────────────────────────────────


def _guard_duplicate(root: Path, location: str, name_override: str | None) -> None:
    cfg = config.load(root / paths.ASM_TOML)
    candidate = name_override or location.rstrip("/").split("/")[-1] or None
    if candidate and candidate in cfg.skills:
        installed = paths.skills_dir(root) / candidate
        if installed.exists() and (installed / "SKILL.md").exists():
            raise ValueError(
                f"Skill '{candidate}' is already installed. "
                f"To reinstall, update or remove it from asm.toml and run `asm sync`, "
                f"or install with a different name via --name."
            )


def _resolve_name(
    override: str | None, fm_name: str, location: str, staging: Path,
) -> str:
    name = override or fm_name
    if not name:
        name = location.rstrip("/").split("/")[-1]
    if not name:
        shutil.rmtree(staging.parent, ignore_errors=True)
        raise ValueError(
            "Cannot determine skill name from source. "
            "Use --name <kebab-case> to specify one, e.g. --name my-skill."
        )
    return name


def _install(staging: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(staging, dest)
    shutil.rmtree(staging.parent, ignore_errors=True)
    return dest


def _normalise_source(raw: str, source_type: str) -> str:
    if raw.startswith("sm:"):
        return f"smithery:{raw[3:]}"
    if raw.startswith("pb:"):
        return f"playbooks:{raw[3:]}"
    if raw.startswith("gh:"):
        return f"github:{raw[3:]}"
    if raw.startswith(("local:", "github:", "smithery:", "playbooks:")):
        return raw
    return f"{source_type}:{raw}"


def _derive_registry_name(location: str) -> str:
    loc = location.strip().rstrip("/")
    if not loc:
        return ""
    if "://" in loc:
        tail = loc.split("/")[-1]
    else:
        tail = loc.split("/")[-1]
    candidate = re.sub(r"[^a-z0-9-]+", "-", tail.lower()).strip("-")
    return candidate


def _validate_with_name_fallback(skill_dir: Path, location: str) -> tuple[bool, str]:
    """Validate frontmatter and normalize non-kebab names when possible."""
    ok, msg = validate(skill_dir)
    if ok:
        return True, msg

    if "must be kebab-case" in msg:
        fallback_name = _derive_registry_name(location)
        if fallback_name:
            _rewrite_skill_name(skill_dir, fallback_name)
            return validate(skill_dir)

    return ok, msg


def _rewrite_skill_name(skill_dir: Path, name: str) -> None:
    skill_md = skill_dir / "SKILL.md"
    content = skill_md.read_text()
    updated, count = re.subn(r"^name:\s*.+$", f"name: {name}", content, count=1, flags=re.MULTILINE)
    if count:
        skill_md.write_text(updated)


def _build_lock_entry(
    meta: SkillMeta,
    source_type: str,
    location: str,
    extra: dict,
    parent: LockEntry | None,
    snapshot_id: str,
    integrity: str,
) -> LockEntry:
    """Build a LockEntry from install/register context. Single place for defaulting rules."""
    return LockEntry(
        upstream_version=meta.version,
        local_revision=parent.local_revision if parent else 0,
        registry=source_type,
        integrity=integrity,
        resolved=extra.get("resolved", location),
        snapshot_id=snapshot_id,
        parent_snapshot_id=parent.snapshot_id if parent else "",
        commit=extra.get("commit", ""),
    )


def _register_config(root: Path, name: str, source: str) -> None:
    cfg_path = root / paths.ASM_TOML
    cfg = config.load(cfg_path)
    cfg.skills[name] = SkillEntry(name=name, source=source)
    config.save(cfg, cfg_path)


def _register_lock(
    root: Path,
    name: str,
    source: str,
    skill_dir: Path,
    extra: dict,
    *,
    event_kind: str,
) -> None:
    lock_file = paths.lock_path(root)
    lock = lockfile.load(lock_file)
    source_type, location = parse_source(source)
    meta = extract_meta(skill_dir)
    previous = lock.get(name)
    snapshot_id = snapshots.ensure_snapshot(root, name, skill_dir)
    parent_snapshot_id = previous.snapshot_id if previous else ""
    author = _current_actor()

    lock[name] = _build_lock_entry(
        meta, source_type, location, extra, previous, snapshot_id,
        lockfile.compute_integrity(skill_dir),
    )
    lockfile.save(lock, lock_file, registry_id=lockfile.DEFAULT_REGISTRY_ID)

    head = snapshots.head_commit(root, name)
    if not head or head.get("snapshot_id") != snapshot_id:
        if event_kind == "import":
            msg = "Imported skill"
        elif event_kind == "update":
            msg = "Updated local skill"
        else:
            msg = "Created local skill"
        snapshots.append_commit(
            root,
            name,
            snapshot_id=snapshot_id,
            parent_snapshot_id=parent_snapshot_id,
            local_revision=lock[name].local_revision,
            message=msg,
            author=author,
            kind=event_kind,
        )


def skill_commit(
    root: Path,
    name: str,
    message: str,
    *,
    author: str | None = None,
) -> LockEntry:
    """Commit local skill changes into snapshot history."""
    skill_dir = _require_skill_dir(root, name)
    lock = lockfile.load(paths.lock_path(root))
    current = lock.get(name)
    if not current:
        raise ValueError(
            f"Skill '{name}' has no lock entry. Run `asm sync`, then retry `asm skill commit {name} -m \"...\"`."
        )

    snapshot_id = snapshots.ensure_snapshot(root, name, skill_dir)
    if snapshot_id == current.snapshot_id:
        raise ValueError("No changes to commit for this skill. Edit files under .asm/skills first.")

    meta = extract_meta(skill_dir)
    revision = snapshots.next_local_revision(root, name)
    entry_author = author or _current_actor()
    entry = LockEntry(
        upstream_version=meta.version,
        local_revision=revision,
        registry=current.registry,
        integrity=lockfile.compute_integrity(skill_dir),
        resolved=current.resolved,
        snapshot_id=snapshot_id,
        parent_snapshot_id=current.snapshot_id,
        commit=current.commit,
    )
    lock[name] = entry
    lockfile.save(lock, paths.lock_path(root), registry_id=lockfile.DEFAULT_REGISTRY_ID)
    snapshots.append_commit(
        root,
        name,
        snapshot_id=snapshot_id,
        parent_snapshot_id=current.snapshot_id,
        local_revision=revision,
        message=message,
        author=entry_author,
        kind="commit",
    )
    return entry


def skill_stash_push(
    root: Path,
    name: str,
    message: str = "",
    *,
    author: str | None = None,
) -> str:
    """Save current working tree into stash storage without version bump."""
    skill_dir = _require_skill_dir(root, name)
    snapshot_id = snapshots.ensure_snapshot(root, name, skill_dir)
    return snapshots.stash_push(
        root,
        name,
        snapshot_id=snapshot_id,
        message=message,
        author=author or _current_actor(),
    )


def skill_stash_apply(
    root: Path,
    name: str,
    stash_id: str | None = None,
    *,
    pop: bool = False,
) -> LockEntry:
    """Apply a stash snapshot into working tree."""
    skill_dir = _require_skill_dir(root, name)
    lock_path = paths.lock_path(root)
    lock = lockfile.load(lock_path)
    current = lock.get(name)
    if not current:
        raise ValueError(
            f"Skill '{name}' has no lock entry. Run `asm sync`, then retry `asm skill stash push {name}`."
        )

    sid = stash_id or snapshots.latest_stash_id(root, name)
    if not sid:
        raise ValueError(f"No stashes found for skill '{name}'. Create one with `asm skill stash push {name}` first.")
    stash = snapshots.load_stash(root, name, sid)
    snapshots.materialize_snapshot(root, stash["snapshot_id"], skill_dir)

    current.integrity = lockfile.compute_integrity(skill_dir)
    current.parent_snapshot_id = current.snapshot_id
    current.snapshot_id = stash["snapshot_id"]
    lock[name] = current
    lockfile.save(lock, lock_path, registry_id=lockfile.DEFAULT_REGISTRY_ID)
    if pop:
        snapshots.drop_stash(root, name, sid)
    return current


def skill_tag(root: Path, name: str, tag: str, ref: str = "HEAD") -> str:
    """Create or move a tag to a snapshot reference."""
    lock = lockfile.load(paths.lock_path(root))
    current = lock.get(name)
    if ref == "HEAD":
        if not current or not current.snapshot_id:
            raise ValueError(
                f"Skill '{name}' does not have a HEAD snapshot. "
                f"Run `asm sync` or `asm skill commit {name} -m \"...\"` first."
            )
        snapshot_id = current.snapshot_id
    else:
        snapshot_id = snapshots.resolve_ref(root, name, ref)
    snapshots.tag_snapshot(root, name, tag, snapshot_id)
    return snapshot_id


def skill_checkout(root: Path, name: str, ref: str, *, force: bool = False) -> LockEntry:
    """Materialize an old/new snapshot by ref and update lock entry."""
    skill_dir = _require_skill_dir(root, name)
    lock_path = paths.lock_path(root)
    lock = lockfile.load(lock_path)
    current = lock.get(name)
    if not current:
        raise ValueError(
            f"Skill '{name}' has no lock entry. Run `asm sync`, then retry `asm skill checkout {name} <ref>`."
        )

    live_integrity = lockfile.compute_integrity(skill_dir)
    if not force and current.integrity and live_integrity != current.integrity:
        raise ValueError(
            "Working tree has uncommitted changes. Use `asm skill stash push` or --force.",
        )

    target_snapshot = snapshots.resolve_ref(root, name, ref)
    if target_snapshot == current.snapshot_id:
        raise ValueError(f"Skill '{name}' is already at snapshot '{target_snapshot}'.")
    snapshots.materialize_snapshot(root, target_snapshot, skill_dir)

    current.parent_snapshot_id = current.snapshot_id
    current.snapshot_id = target_snapshot
    target_revision = snapshots.revision_for_snapshot(root, name, target_snapshot)
    if target_revision is not None:
        current.local_revision = target_revision
    current.integrity = lockfile.compute_integrity(skill_dir)
    lock[name] = current
    lockfile.save(lock, lock_path, registry_id=lockfile.DEFAULT_REGISTRY_ID)
    return current


def skill_history(root: Path, name: str, *, limit: int = 20) -> list[dict]:
    """Return recent history entries for a skill."""
    history = snapshots.load_history(root, name)
    commits = history.get("commits", [])
    return commits[-limit:]


def skill_status(root: Path, name: str) -> SkillWorkingStatus:
    """Return unstaged working tree status against current lock snapshot."""
    skill_dir = _require_skill_dir(root, name)
    lock = lockfile.load(paths.lock_path(root))
    current = lock.get(name)
    if not current:
        raise ValueError(
            f"Skill '{name}' has no lock entry. Run `asm sync`, then retry `asm skill status {name}`."
        )
    if not current.snapshot_id:
        raise ValueError(
            f"Skill '{name}' has no snapshot baseline yet. "
            f"Run `asm sync` or create one with `asm skill commit {name} -m \"...\"`."
        )

    changes = snapshots.compare_snapshot_to_working(root, current.snapshot_id, skill_dir)
    return SkillWorkingStatus(
        name=name,
        snapshot_id=current.snapshot_id,
        added=changes["added"],
        modified=changes["modified"],
        removed=changes["removed"],
    )


def skill_diff(root: Path, name: str, rel_path: str | None = None) -> str:
    """Return unified diff for unstaged working changes."""
    skill_dir = _require_skill_dir(root, name)
    lock = lockfile.load(paths.lock_path(root))
    current = lock.get(name)
    if not current:
        raise ValueError(
            f"Skill '{name}' has no lock entry. Run `asm sync`, then retry `asm skill diff {name}`."
        )
    if not current.snapshot_id:
        raise ValueError(
            f"Skill '{name}' has no snapshot baseline yet. "
            f"Run `asm sync` or create one with `asm skill commit {name} -m \"...\"`."
        )
    return snapshots.diff_snapshot_to_working(
        root,
        current.snapshot_id,
        skill_dir,
        rel_path=rel_path,
    )


def skill_share(
    root: Path,
    name: str,
    *,
    out_dir: Path | None = None,
    overwrite: bool = False,
) -> tuple[Path, Path]:
    """Package one local skill into a shareable folder and zip archive."""
    skill_dir = _require_skill_dir(root, name)
    target_root = (out_dir or (root / "dist" / "skills")).resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    target_dir = target_root / name
    archive_path = target_root / f"{name}.zip"

    if target_dir.exists():
        if not overwrite:
            raise ValueError(
                f"Share folder already exists: {target_dir}. Re-run with --overwrite to replace it."
            )
        shutil.rmtree(target_dir)
    if archive_path.exists():
        if not overwrite:
            raise ValueError(
                f"Share archive already exists: {archive_path}. Re-run with --overwrite to replace it."
            )
        archive_path.unlink()

    shutil.copytree(skill_dir, target_dir)

    lock = lockfile.load(paths.lock_path(root))
    current = lock.get(name)
    meta = extract_meta(skill_dir)
    share_manifest = {
        "name": meta.name or name,
        "description": meta.description,
        "version": meta.version,
        "source": f"local:.asm/skills/{name}",
        "snapshot_id": current.snapshot_id if current else "",
        "integrity": lockfile.compute_integrity(skill_dir),
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "files": sorted(
            path.relative_to(target_dir).as_posix()
            for path in target_dir.rglob("*")
            if path.is_file()
        ),
    }
    (target_dir / "share.json").write_text(
        json.dumps(share_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    built_archive = shutil.make_archive(
        str(target_root / name),
        "zip",
        root_dir=target_root,
        base_dir=name,
    )
    return target_dir, Path(built_archive)


def _require_skill_dir(root: Path, name: str) -> Path:
    skill_dir = paths.skills_dir(root) / name
    if not skill_dir.exists() or not (skill_dir / "SKILL.md").exists():
        raise FileNotFoundError(f"Skill '{name}' is not installed in .asm/skills/{name}")
    return skill_dir


def _current_actor() -> str:
    return getpass.getuser()


def _ingest_source(src: Path, skill_dir: Path) -> None:
    """Copy source files into the skill's scripts/ or references/ dir."""
    if src.is_file():
        target_dir = skill_dir / ("scripts" if src.suffix == ".py" else "references")
        target_dir.mkdir(exist_ok=True)
        shutil.copy2(src, target_dir / src.name)
    elif src.is_dir():
        scripts = skill_dir / "scripts"
        references = skill_dir / "references"
        scripts.mkdir(exist_ok=True)
        references.mkdir(exist_ok=True)
        for f in src.rglob("*"):
            if not f.is_file():
                continue
            target = scripts if f.suffix in {".py", ".sh", ".bash"} else references
            dest = target / f.relative_to(src)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
