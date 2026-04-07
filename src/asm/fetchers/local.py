"""Fetch skills from the local filesystem."""

from __future__ import annotations

from pathlib import Path

from asm.core.models import FetchPolicy
from asm.fetchers.safe_tree import copy_skill_tree


def fetch(
    source: str,
    dest: Path,
    *,
    root: Path | None = None,
    policy: FetchPolicy,
) -> None:
    """Copy a skill directory from a local path to *dest*.

    Relative paths are resolved against *root* (project root) when given,
    otherwise against the current working directory.
    """
    if not policy.allow_local:
        raise ValueError(
            "Local skill sources are disabled ([fetch].allow_local = false in asm.toml)."
        )
    src = Path(source).expanduser()
    if not src.is_absolute() and root:
        src = root / src
    src = src.resolve()
    if not src.exists():
        raise FileNotFoundError(f"Skill source not found: {src}")
    copy_skill_tree(src, dest, policy)
