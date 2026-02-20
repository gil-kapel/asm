"""Fetch skills from GitHub repositories."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path


def parse_ref(raw: str) -> tuple[str, str, str]:
    """Parse a GitHub reference into (repo_url, branch, subpath).

    Supports:
      https://github.com/user/repo/tree/branch/path
      user/repo/path
      user/repo
    """
    full = re.match(
        r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?"
        r"(?:/tree/([^/]+)(?:/(.+))?)?$",
        raw,
    )
    if full:
        user, repo, branch, subpath = full.groups()
        return (
            f"https://github.com/{user}/{repo}.git",
            branch or "main",
            subpath or "",
        )

    parts = raw.split("/")
    if len(parts) >= 2:
        user, repo = parts[0], parts[1]
        subpath = "/".join(parts[2:]) if len(parts) > 2 else ""
        return f"https://github.com/{user}/{repo}.git", "main", subpath

    raise ValueError(f"Cannot parse GitHub reference: {raw}")


def fetch(raw: str, dest: Path) -> str:
    """Clone a skill from GitHub. Returns the commit hash."""
    repo_url, branch, subpath = parse_ref(raw)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_repo = Path(tmp) / "repo"
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", branch,
             repo_url, str(tmp_repo)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git clone failed: {result.stderr.strip()}")

        source = tmp_repo / subpath if subpath else tmp_repo
        if not source.exists():
            raise FileNotFoundError(f"Path '{subpath}' not found in {repo_url}")

        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source, dest)

        git_dir = dest / ".git"
        if git_dir.exists():
            shutil.rmtree(git_dir)

        result = subprocess.run(
            ["git", "-C", str(tmp_repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
