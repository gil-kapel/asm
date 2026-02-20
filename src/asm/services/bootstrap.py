"""Bootstrap service — implements `asm init`."""

from __future__ import annotations

from pathlib import Path

from asm.core import paths
from asm.repo import config
from asm.templates import render_main_asm


def init_workspace(root: Path, name: str | None = None) -> Path:
    """Create the .asm/ infrastructure and asm.toml in *root*.

    Returns the project root on success.
    Raises FileExistsError if already initialised.
    """
    name = name or root.name
    asm_toml = root / paths.ASM_TOML

    if asm_toml.exists():
        raise FileExistsError(f"Workspace already initialised: {asm_toml}")

    cfg = config.create_default(name)

    paths.asm_dir(root).mkdir(parents=True, exist_ok=True)
    paths.skills_dir(root).mkdir(parents=True, exist_ok=True)

    config.save(cfg, asm_toml)
    paths.main_asm_path(root).write_text(render_main_asm(cfg))

    return root


def regenerate(root: Path) -> None:
    """Regenerate main_asm.md from current asm.toml state."""
    cfg = config.load(root / paths.ASM_TOML)
    paths.main_asm_path(root).write_text(render_main_asm(cfg))
