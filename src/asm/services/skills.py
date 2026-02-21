"""Skill service — high-level add / create / sync operations."""

from __future__ import annotations

import getpass
import shutil
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from asm.core import paths
from asm.core.frontmatter import extract_meta, validate
from asm.core.models import LockEntry, SkillEntry, SkillMeta
from asm.fetchers import fetch, parse_source
from asm.repo import config, lockfile, snapshots
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
    extra = fetch(source_type, location, dest_tmp, root=root)

    emit("Validating SKILL.md…")
    ok, msg = validate(dest_tmp)
    if not ok:
        shutil.rmtree(dest_tmp.parent, ignore_errors=True)
        raise ValueError(f"Skill validation failed: {msg}")

    meta = extract_meta(dest_tmp)
    skill_name = _resolve_name(name_override, meta.name, location, dest_tmp)
    meta = SkillMeta(name=skill_name, description=meta.description, version=meta.version)

    emit(f"Installing {skill_name}…")
    final_dest = _install(dest_tmp, paths.skills_dir(root) / skill_name)

    source_label = _normalise_source(source_raw, source_type)

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
    _register_lock(root, skill_name, source_label, skill_dir, {}, event_kind="create")

    return skill_dir


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

    ok, msg = validate(dest_tmp)
    if not ok:
        shutil.rmtree(dest_tmp.parent, ignore_errors=True)
        raise ValueError(f"Validation failed: {msg}")

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
    if raw.startswith(("local:", "github:", "smithery:", "playbooks:")):
        return raw
    return f"{source_type}:{raw}"


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
        msg = "Imported skill" if event_kind == "import" else "Created local skill"
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
        raise ValueError(f"Skill '{name}' has no lock entry. Run `asm sync` first.")

    snapshot_id = snapshots.ensure_snapshot(root, name, skill_dir)
    if snapshot_id == current.snapshot_id:
        raise ValueError("No changes to commit for this skill.")

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
        raise ValueError(f"Skill '{name}' has no lock entry. Run `asm sync` first.")

    sid = stash_id or snapshots.latest_stash_id(root, name)
    if not sid:
        raise ValueError(f"No stashes found for skill '{name}'.")
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
            raise ValueError(f"Skill '{name}' does not have a HEAD snapshot.")
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
        raise ValueError(f"Skill '{name}' has no lock entry. Run `asm sync` first.")

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
        raise ValueError(f"Skill '{name}' has no lock entry. Run `asm sync` first.")
    if not current.snapshot_id:
        raise ValueError(f"Skill '{name}' has no snapshot baseline yet.")

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
        raise ValueError(f"Skill '{name}' has no lock entry. Run `asm sync` first.")
    if not current.snapshot_id:
        raise ValueError(f"Skill '{name}' has no snapshot baseline yet.")
    return snapshots.diff_snapshot_to_working(
        root,
        current.snapshot_id,
        skill_dir,
        rel_path=rel_path,
    )


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
