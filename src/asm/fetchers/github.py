"""Fetch skills from GitHub repositories.

Uses sparse checkout when a subpath is specified to avoid downloading
the entire repository — typically 10-50x faster than a full clone.
"""

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


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, **kwargs)


def _sparse_clone(repo_url: str, branch: str, subpath: str, tmp_repo: Path) -> None:
    """Clone only the needed subpath using sparse checkout + treeless filter."""
    r = _run([
        "git", "clone",
        "--filter=blob:none", "--no-checkout",
        "--depth", "1", "--branch", branch,
        repo_url, str(tmp_repo),
    ])
    if r.returncode != 0:
        raise RuntimeError(f"git clone failed: {r.stderr.strip()}")

    _run(["git", "-C", str(tmp_repo), "sparse-checkout", "set", subpath])
    r = _run(["git", "-C", str(tmp_repo), "checkout"])
    if r.returncode != 0:
        raise RuntimeError(f"git checkout failed: {r.stderr.strip()}")


def _shallow_clone(repo_url: str, branch: str, tmp_repo: Path) -> None:
    """Full shallow clone (no subpath — need everything)."""
    r = _run([
        "git", "clone", "--depth", "1", "--branch", branch,
        repo_url, str(tmp_repo),
    ])
    if r.returncode != 0:
        raise RuntimeError(f"git clone failed: {r.stderr.strip()}")


def fetch(raw: str, dest: Path) -> str:
    """Clone a skill from GitHub. Returns the commit hash.

    Uses sparse checkout when a subpath is specified — only downloads
    the blobs for the needed directory.
    """
    repo_url, branch, subpath = parse_ref(raw)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_repo = Path(tmp) / "repo"

        if subpath:
            _sparse_clone(repo_url, branch, subpath, tmp_repo)
        else:
            _shallow_clone(repo_url, branch, tmp_repo)

        source = tmp_repo / subpath if subpath else tmp_repo
        if not source.exists():
            raise FileNotFoundError(f"Path '{subpath}' not found in {repo_url}")

        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source, dest)

        git_dir = dest / ".git"
        if git_dir.exists():
            shutil.rmtree(git_dir)

        r = _run(["git", "-C", str(tmp_repo), "rev-parse", "HEAD"], check=True)
        return r.stdout.strip()
