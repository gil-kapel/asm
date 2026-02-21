"""Path constants and root-resolution logic."""

from __future__ import annotations

from pathlib import Path

ASM_DIR = ".asm"
ASM_TOML = "asm.toml"
ASM_LOCK = "asm.lock"
MAIN_ASM_MD = "main_asm.md"
SKILLS_DIR = "skills"
OBJECTS_DIR = "objects"
HISTORY_DIR = "history"
STASH_DIR = "stash"


def resolve_root(start: Path | None = None) -> Path:
    """Walk up from *start* to locate an existing asm.toml, else return *start*."""
    start = start or Path.cwd()
    for parent in [start, *start.parents]:
        if (parent / ASM_TOML).exists():
            return parent
    return start


def asm_dir(root: Path) -> Path:
    return root / ASM_DIR


def skills_dir(root: Path) -> Path:
    return asm_dir(root) / SKILLS_DIR


def main_asm_path(root: Path) -> Path:
    return asm_dir(root) / MAIN_ASM_MD


def lock_path(root: Path) -> Path:
    return root / ASM_LOCK


def objects_dir(root: Path) -> Path:
    return asm_dir(root) / OBJECTS_DIR


def history_dir(root: Path) -> Path:
    return asm_dir(root) / HISTORY_DIR


def stash_dir(root: Path) -> Path:
    return asm_dir(root) / STASH_DIR
