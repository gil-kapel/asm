"""Filesystem-safe copy of skill trees (no symlinks, optional size limits)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from asm.core.models import FetchPolicy


class SkillInstallLimitsExceeded(ValueError):
    """Raised when a skill tree exceeds configured size or file count."""


def copy_skill_tree(src: Path, dest: Path, policy: FetchPolicy) -> None:
    """Copy *src* to *dest* without following symlinks; enforce optional limits."""
    if not src.is_dir():
        raise FileNotFoundError(f"Skill source is not a directory: {src}")
    if dest.exists():
        shutil.rmtree(dest)

    max_bytes = policy.max_total_bytes
    max_files = policy.max_file_count
    total_bytes = 0
    file_count = 0

    for dirpath, _dirnames, filenames in os.walk(src, topdown=True, followlinks=False):
        rel = Path(dirpath).relative_to(src)
        target_dir = dest / rel
        target_dir.mkdir(parents=True, exist_ok=True)

        for name in filenames:
            sfile = Path(dirpath) / name
            if sfile.is_symlink():
                raise ValueError(
                    f"Refusing to install skill: symbolic links are not allowed ({sfile})"
                )
            if not sfile.is_file():
                continue
            st = sfile.stat()
            size = st.st_size
            if max_bytes is not None:
                total_bytes += size
                if total_bytes > max_bytes:
                    raise SkillInstallLimitsExceeded(
                        f"Skill exceeds [fetch].max_total_bytes ({max_bytes} bytes)."
                    )
            file_count += 1
            if max_files is not None and file_count > max_files:
                raise SkillInstallLimitsExceeded(
                    f"Skill exceeds [fetch].max_file_count ({max_files} files)."
                )
            shutil.copy2(sfile, target_dir / name)
