"""Fetch skills from GitHub repositories.

Uses sparse checkout when a subpath is specified to avoid downloading
the entire repository — typically 10-50x faster than a full clone.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from asm.core.models import FetchPolicy
from asm.fetchers.fetch_policy import parse_github_skill_ref
from asm.fetchers.safe_tree import copy_skill_tree


def parse_ref(raw: str, policy: FetchPolicy) -> tuple[str, str, str]:
    """Parse a GitHub (or allowed-host) reference into (repo_url, branch, subpath)."""
    return parse_github_skill_ref(raw, policy)


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, **kwargs)


def _sparse_clone(repo_url: str, branch: str, subpath: str, tmp_repo: Path) -> None:
    """Clone only the needed subpath using sparse checkout + treeless filter."""
    args = [
        "git",
        "clone",
        "--filter=blob:none",
        "--no-checkout",
        "--depth",
        "1",
    ]
    if branch and branch != "HEAD":
        args.extend(["--branch", branch])
    args.extend([repo_url, str(tmp_repo)])
    r = _run(args)
    if r.returncode != 0:
        raise RuntimeError(f"git clone failed: {r.stderr.strip()}")

    _run(["git", "-C", str(tmp_repo), "sparse-checkout", "set", subpath])
    r = _run(["git", "-C", str(tmp_repo), "checkout"])
    if r.returncode != 0:
        raise RuntimeError(f"git checkout failed: {r.stderr.strip()}")


def _shallow_clone(repo_url: str, branch: str, tmp_repo: Path) -> None:
    """Full shallow clone (no subpath — need everything)."""
    args = ["git", "clone", "--depth", "1"]
    if branch and branch != "HEAD":
        args.extend(["--branch", branch])
    args.extend([repo_url, str(tmp_repo)])
    r = _run(args)
    if r.returncode != 0:
        raise RuntimeError(f"git clone failed: {r.stderr.strip()}")


def fetch(raw: str, dest: Path, *, policy: FetchPolicy) -> str:
    """Clone a skill from GitHub (or an allowed host). Returns the commit hash.

    Uses sparse checkout when a subpath is specified — only downloads
    the blobs for the needed directory.
    """
    repo_url, branch, subpath = parse_github_skill_ref(raw, policy)

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
        copy_skill_tree(source, dest, policy)

        git_dir = dest / ".git"
        if git_dir.exists():
            shutil.rmtree(git_dir)

        r = _run(["git", "-C", str(tmp_repo), "rev-parse", "HEAD"], check=True)
        return r.stdout.strip()
