"""I/O layer — fetch skills from external sources.

Dispatch based on source type prefix:
  local:./path       → fetchers.local
  github:user/repo   → fetchers.github
  smithery:ns/skill  → external registry (metadata/provenance; fetch TBD)
  playbooks:ns/skill → external registry (metadata/provenance; fetch TBD)
  ./path or /path    → fetchers.local  (auto-detected)
  github.com URL     → fetchers.github (auto-detected)
"""

from __future__ import annotations

from pathlib import Path

from asm.core import paths
from asm.core.models import FetchPolicy
from asm.fetchers import github, local, playbooks, smithery
from asm.repo import config


def parse_source(raw: str) -> tuple[str, str]:
    """Classify a source string into (type, location)."""
    if "smithery.ai/skill/" in raw:
        return "smithery", raw
    if "playbooks.com/skills/" in raw:
        return "playbooks", raw
    if raw.startswith("sm:"):
        return "smithery", raw[3:]
    if raw.startswith("pb:"):
        return "playbooks", raw[3:]
    if raw.startswith("gh:"):
        return "github", raw[3:]
    if raw.startswith("local:"):
        return "local", raw[6:]
    if raw.startswith("github:"):
        return "github", raw[7:]
    if raw.startswith("smithery:"):
        return "smithery", raw[9:]
    if raw.startswith("playbooks:"):
        return "playbooks", raw[10:]
    if raw.startswith(("./", "/", "~")):
        return "local", raw
    if "github.com" in raw:
        return "github", raw
    return "github", raw


def _resolve_policy(root: Path | None, policy: FetchPolicy | None) -> FetchPolicy:
    if policy is not None:
        return policy
    if root is not None:
        cfg_path = root / paths.ASM_TOML
        if cfg_path.exists():
            return config.load(cfg_path).fetch
    return FetchPolicy.default_policy()


def fetch(
    source_type: str,
    location: str,
    dest: Path,
    *,
    root: Path | None = None,
    policy: FetchPolicy | None = None,
) -> dict:
    """Dispatch to the appropriate fetcher.

    *root* is passed to local fetcher for resolving relative paths.
    When *policy* is None and *root* is set, load ``[fetch]`` from asm.toml.
    Returns a dict with optional keys: commit, resolved.
    """
    pol = _resolve_policy(root, policy)

    if source_type == "local":
        local.fetch(location, dest, root=root, policy=pol)
        return {}

    if source_type == "github":
        commit = github.fetch(location, dest, policy=pol)
        repo_url, branch, subpath = github.parse_ref(location, pol)
        resolved = repo_url.replace(".git", "") + f"/tree/{branch}"
        if subpath:
            resolved += f"/{subpath}"
        return {"commit": commit, "resolved": resolved}

    if source_type == "smithery":
        gh_ref = smithery.fetch_ref(location)
        commit = github.fetch(gh_ref, dest, policy=pol)
        repo_url, branch, subpath = github.parse_ref(gh_ref, pol)
        resolved = repo_url.replace(".git", "") + f"/tree/{branch}"
        if subpath:
            resolved += f"/{subpath}"
        return {
            "commit": commit,
            "resolved": resolved,
            "registry_source": f"smithery:{location}",
            "upstream": gh_ref,
        }

    if source_type == "playbooks":
        gh_ref = playbooks.fetch_ref(location)
        commit = github.fetch(gh_ref, dest, policy=pol)
        repo_url, branch, subpath = github.parse_ref(gh_ref, pol)
        resolved = repo_url.replace(".git", "") + f"/tree/{branch}"
        if subpath:
            resolved += f"/{subpath}"
        return {
            "commit": commit,
            "resolved": resolved,
            "registry_source": f"playbooks:{location}",
            "upstream": gh_ref,
        }

    raise ValueError(f"Unsupported source type: {source_type}")
