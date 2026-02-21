"""Runtime environment helpers."""

from __future__ import annotations

import os
from pathlib import Path

_USER_ENV_LOADED = False


def load_user_env() -> None:
    """Load user-level ASM env files without overriding existing vars."""
    global _USER_ENV_LOADED
    if _USER_ENV_LOADED:
        return

    for env_file in _candidate_env_files():
        _load_env_file(env_file)

    _USER_ENV_LOADED = True


def _candidate_env_files() -> list[Path]:
    files: list[Path] = []
    env_override = os.environ.get("ASM_ENV_FILE", "").strip()
    if env_override:
        files.append(Path(env_override).expanduser())

    asm_home = os.environ.get("ASM_HOME", "").strip()
    if asm_home:
        files.append(Path(asm_home).expanduser() / ".env")

    home = Path.home()
    files.extend(
        [
            home / ".asm-cli" / ".env",
            home / ".config" / "asm" / "env",
            home / ".config" / "asm" / ".env",
        ]
    )
    return files


def _load_env_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value
