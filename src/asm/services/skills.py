"""Skill service — high-level add / create operations."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from asm.core import paths
from asm.core.frontmatter import extract_meta, validate
from asm.core.models import LockEntry, SkillEntry, SkillMeta
from asm.fetchers import fetch, parse_source
from asm.repo import config, lockfile
from asm.templates import build_skill_md


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

    emit("Fetching skill…" if source_type == "github" else "Copying from local path…")
    dest_tmp = Path(tempfile.mkdtemp()) / "staging"
    extra = fetch(source_type, location, dest_tmp)

    emit("Validating SKILL.md…")
    ok, msg = validate(dest_tmp)
    if not ok:
        shutil.rmtree(dest_tmp.parent, ignore_errors=True)
        raise ValueError(f"Skill validation failed: {msg}")

    meta = extract_meta(dest_tmp)
    skill_name = _resolve_name(name_override, meta.name, location, dest_tmp)
    meta = SkillMeta(name=skill_name, description=meta.description)

    emit(f"Installing {skill_name}…")
    final_dest = _install(dest_tmp, paths.skills_dir(root) / skill_name)

    source_label = _normalise_source(source_raw, source_type)

    emit("Updating asm.toml…")
    _register_config(root, skill_name, source_label)

    emit("Locking integrity hash…")
    _register_lock(root, skill_name, source_label, final_dest, extra)

    return meta


def create_skill(
    root: Path,
    skill_name: str,
    description: str,
    source_path: str | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> Path:
    """Scaffold a new SKILL.md package and register it."""
    emit = on_progress or (lambda _msg: None)

    skill_dir = paths.skills_dir(root) / skill_name
    if skill_dir.exists():
        raise FileExistsError(f"Skill already exists: {skill_dir}")

    emit("Scaffolding skill directory…")
    skill_dir.mkdir(parents=True)

    title = " ".join(w.capitalize() for w in skill_name.split("-"))
    (skill_dir / "SKILL.md").write_text(
        build_skill_md(skill_name, title, description, source_path)
    )

    if source_path:
        emit("Ingesting source code…")
        _ingest_source(Path(source_path).resolve(), skill_dir)

    source_label = f"local:.asm/skills/{skill_name}"

    emit("Updating asm.toml…")
    _register_config(root, skill_name, source_label)

    emit("Locking integrity hash…")
    _register_lock(root, skill_name, source_label, skill_dir, {})

    return skill_dir


# ── Private helpers ─────────────────────────────────────────────────


def _guard_duplicate(root: Path, location: str, name_override: str | None) -> None:
    cfg = config.load(root / paths.ASM_TOML)
    candidate = name_override or location.rstrip("/").split("/")[-1] or None
    if candidate and candidate in cfg.skills:
        installed = paths.skills_dir(root) / candidate
        if installed.exists() and (installed / "SKILL.md").exists():
            raise ValueError(
                f"Skill '{candidate}' is already installed. "
                f"Use 'asm remove skill {candidate}' first to reinstall."
            )


def _resolve_name(
    override: str | None, fm_name: str, location: str, staging: Path,
) -> str:
    name = override or fm_name
    if not name:
        name = location.rstrip("/").split("/")[-1]
    if not name:
        shutil.rmtree(staging.parent, ignore_errors=True)
        raise ValueError("Cannot determine skill name — use --name to specify one")
    return name


def _install(staging: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(staging, dest)
    shutil.rmtree(staging.parent, ignore_errors=True)
    return dest


def _normalise_source(raw: str, source_type: str) -> str:
    if raw.startswith(("local:", "github:")):
        return raw
    return f"{source_type}:{raw}"


def _register_config(root: Path, name: str, source: str) -> None:
    cfg_path = root / paths.ASM_TOML
    cfg = config.load(cfg_path)
    cfg.skills[name] = SkillEntry(name=name, source=source)
    config.save(cfg, cfg_path)


def _register_lock(
    root: Path, name: str, source: str, skill_dir: Path, extra: dict,
) -> None:
    lock_file = paths.lock_path(root)
    lock = lockfile.load(lock_file)
    lock[name] = LockEntry(
        name=name,
        source=source,
        integrity=lockfile.compute_integrity(skill_dir),
        resolved=extra.get("resolved", ""),
        commit=extra.get("commit", ""),
    )
    lockfile.save(lock, lock_file)


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
