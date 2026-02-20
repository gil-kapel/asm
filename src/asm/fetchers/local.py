"""Fetch skills from the local filesystem."""

from __future__ import annotations

import shutil
from pathlib import Path


def fetch(source: str, dest: Path) -> None:
    """Copy a skill directory from a local path to *dest*."""
    src = Path(source).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"Skill source not found: {src}")
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
