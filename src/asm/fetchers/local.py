"""Fetch skills from the local filesystem."""

from __future__ import annotations

import shutil
from pathlib import Path


def fetch(source: str, dest: Path, *, root: Path | None = None) -> None:
    """Copy a skill directory from a local path to *dest*.

    Relative paths are resolved against *root* (project root) when given,
    otherwise against the current working directory.
    """
    src = Path(source).expanduser()
    if not src.is_absolute() and root:
        src = root / src
    src = src.resolve()
    if not src.exists():
        raise FileNotFoundError(f"Skill source not found: {src}")
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
