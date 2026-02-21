"""Immutable snapshot store for per-skill history and stashes."""

from __future__ import annotations

import hashlib
import json
import shutil
from difflib import unified_diff
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from asm.core import paths


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_tree(skill_dir: Path) -> str:
    hasher = hashlib.sha256()
    for path in sorted(skill_dir.rglob("*")):
        if path.is_file():
            hasher.update(path.relative_to(skill_dir).as_posix().encode())
            hasher.update(path.read_bytes())
    return hasher.hexdigest()


def _history_path(root: Path, skill_name: str) -> Path:
    return paths.history_dir(root) / f"{skill_name}.json"


def _stash_skill_dir(root: Path, skill_name: str) -> Path:
    return paths.stash_dir(root) / skill_name


def ensure_snapshot(root: Path, skill_name: str, skill_dir: Path) -> str:
    """Store skill tree as immutable object and return snapshot id."""
    digest = _hash_tree(skill_dir)
    snapshot_id = f"{skill_name}-{digest[:16]}"
    objects = paths.objects_dir(root)
    target = objects / snapshot_id
    if not target.exists():
        objects.mkdir(parents=True, exist_ok=True)
        shutil.copytree(skill_dir, target)
    return snapshot_id


def materialize_snapshot(root: Path, snapshot_id: str, dest_dir: Path) -> None:
    """Replace working skill tree with selected snapshot contents."""
    source = paths.objects_dir(root) / snapshot_id
    if not source.exists():
        raise FileNotFoundError(f"Snapshot not found: {snapshot_id}")
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    shutil.copytree(source, dest_dir)


def snapshot_dir(root: Path, snapshot_id: str) -> Path:
    """Return filesystem path for one snapshot object."""
    return paths.objects_dir(root) / snapshot_id


def compare_snapshot_to_working(root: Path, snapshot_id: str, working_dir: Path) -> dict[str, list[str]]:
    """Return added/modified/removed files relative to a snapshot."""
    base_dir = snapshot_dir(root, snapshot_id)
    if not base_dir.exists():
        raise FileNotFoundError(f"Snapshot not found: {snapshot_id}")

    base_files = {
        p.relative_to(base_dir).as_posix()
        for p in base_dir.rglob("*")
        if p.is_file()
    }
    working_files = {
        p.relative_to(working_dir).as_posix()
        for p in working_dir.rglob("*")
        if p.is_file()
    }

    added = sorted(working_files - base_files)
    removed = sorted(base_files - working_files)

    modified: list[str] = []
    for rel in sorted(base_files & working_files):
        if (base_dir / rel).read_bytes() != (working_dir / rel).read_bytes():
            modified.append(rel)

    return {"added": added, "modified": modified, "removed": removed}


def diff_snapshot_to_working(
    root: Path,
    snapshot_id: str,
    working_dir: Path,
    *,
    rel_path: str | None = None,
) -> str:
    """Build unified diff between snapshot and working tree."""
    base_dir = snapshot_dir(root, snapshot_id)
    if not base_dir.exists():
        raise FileNotFoundError(f"Snapshot not found: {snapshot_id}")

    changes = compare_snapshot_to_working(root, snapshot_id, working_dir)
    targets = changes["added"] + changes["modified"] + changes["removed"]
    if rel_path:
        targets = [p for p in targets if p == rel_path]

    chunks: list[str] = []
    for rel in targets:
        before = base_dir / rel
        after = working_dir / rel

        before_lines = _safe_text_lines(before) if before.exists() else []
        after_lines = _safe_text_lines(after) if after.exists() else []

        if before_lines is None or after_lines is None:
            chunks.append(f"Binary file changed: {rel}\n")
            continue

        diff = unified_diff(
            before_lines,
            after_lines,
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
            lineterm="",
        )
        text = "\n".join(diff)
        if text:
            chunks.append(text)

    return "\n\n".join(chunks).strip()


def _safe_text_lines(path: Path) -> list[str] | None:
    """Return file lines for textual diffing; None for binary-like data."""
    if not path.exists():
        return []
    raw = path.read_bytes()
    if b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None


def load_history(root: Path, skill_name: str) -> dict:
    """Load per-skill history; returns default structure if missing."""
    fp = _history_path(root, skill_name)
    if not fp.exists():
        return {"skill": skill_name, "commits": [], "tags": {}}
    return json.loads(fp.read_text())


def save_history(root: Path, skill_name: str, history: dict) -> None:
    """Persist per-skill history."""
    hp = paths.history_dir(root)
    hp.mkdir(parents=True, exist_ok=True)
    fp = _history_path(root, skill_name)
    fp.write_text(json.dumps(history, indent=2))


def head_commit(root: Path, skill_name: str) -> dict | None:
    """Return latest commit entry for skill."""
    history = load_history(root, skill_name)
    commits = history.get("commits", [])
    return commits[-1] if commits else None


def next_local_revision(root: Path, skill_name: str) -> int:
    """Compute next local revision for commit-like events."""
    history = load_history(root, skill_name)
    revisions = [int(c.get("local_revision", 0)) for c in history.get("commits", [])]
    return (max(revisions) if revisions else 0) + 1


def append_commit(
    root: Path,
    skill_name: str,
    *,
    snapshot_id: str,
    parent_snapshot_id: str,
    local_revision: int,
    message: str,
    author: str,
    kind: str = "commit",
) -> dict:
    """Append a commit/import event in history and return the entry."""
    history = load_history(root, skill_name)
    entry = {
        "id": uuid4().hex[:12],
        "kind": kind,
        "snapshot_id": snapshot_id,
        "parent_snapshot_id": parent_snapshot_id,
        "local_revision": local_revision,
        "message": message,
        "author": author,
        "created_at": _now_utc(),
    }
    history.setdefault("commits", []).append(entry)
    save_history(root, skill_name, history)
    return entry


def tag_snapshot(root: Path, skill_name: str, tag: str, snapshot_id: str) -> None:
    """Associate a human-friendly tag with a snapshot."""
    history = load_history(root, skill_name)
    history.setdefault("tags", {})[tag] = snapshot_id
    save_history(root, skill_name, history)


def resolve_ref(root: Path, skill_name: str, ref: str) -> str:
    """Resolve tag/snapshot ref into a concrete snapshot id."""
    history = load_history(root, skill_name)
    tags = history.get("tags", {})
    if ref in tags:
        return tags[ref]
    objects = paths.objects_dir(root)
    exact = objects / ref
    if exact.exists():
        return ref
    matches = [p.name for p in objects.glob(f"{ref}*")]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"Ambiguous snapshot ref: {ref}")
    raise ValueError(f"Unknown snapshot or tag: {ref}")


def revision_for_snapshot(root: Path, skill_name: str, snapshot_id: str) -> int | None:
    """Return local revision associated with a committed snapshot, if known."""
    history = load_history(root, skill_name)
    for item in reversed(history.get("commits", [])):
        if item.get("snapshot_id") == snapshot_id:
            return int(item.get("local_revision", 0))
    return None


def stash_push(
    root: Path,
    skill_name: str,
    *,
    snapshot_id: str,
    message: str,
    author: str,
) -> str:
    """Persist stash metadata for a snapshot. Returns stash id."""
    stash_id = uuid4().hex[:12]
    stash_dir = _stash_skill_dir(root, skill_name)
    stash_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": stash_id,
        "snapshot_id": snapshot_id,
        "message": message or "WIP",
        "author": author,
        "created_at": _now_utc(),
    }
    (stash_dir / f"{stash_id}.json").write_text(json.dumps(payload, indent=2))
    return stash_id


def latest_stash_id(root: Path, skill_name: str) -> str | None:
    """Return latest stash id for skill, if any."""
    stash_dir = _stash_skill_dir(root, skill_name)
    if not stash_dir.exists():
        return None
    items = sorted(stash_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not items:
        return None
    return items[-1].stem


def load_stash(root: Path, skill_name: str, stash_id: str) -> dict:
    """Load one stash entry."""
    fp = _stash_skill_dir(root, skill_name) / f"{stash_id}.json"
    if not fp.exists():
        raise FileNotFoundError(f"Stash not found: {stash_id}")
    return json.loads(fp.read_text())


def drop_stash(root: Path, skill_name: str, stash_id: str) -> None:
    """Delete stash metadata entry."""
    fp = _stash_skill_dir(root, skill_name) / f"{stash_id}.json"
    if fp.exists():
        fp.unlink()
