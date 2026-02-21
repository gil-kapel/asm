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

from asm.fetchers import github, local


def parse_source(raw: str) -> tuple[str, str]:
    """Classify a source string into (type, location)."""
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


def fetch(source_type: str, location: str, dest: Path, *, root: Path | None = None) -> dict:
    """Dispatch to the appropriate fetcher.

    *root* is passed to local fetcher for resolving relative paths.
    Returns a dict with optional keys: commit, resolved.
    """
    if source_type == "local":
        local.fetch(location, dest, root=root)
        return {}

    if source_type == "github":
        commit = github.fetch(location, dest)
        repo_url, branch, subpath = github.parse_ref(location)
        resolved = repo_url.replace(".git", "") + f"/tree/{branch}"
        if subpath:
            resolved += f"/{subpath}"
        return {"commit": commit, "resolved": resolved}

    if source_type in {"smithery", "playbooks"}:
        raise ValueError(
            f"Source type '{source_type}' is parsed but not fetchable yet. "
            "Use registry import adapters first.",
        )

    raise ValueError(f"Unsupported source type: {source_type}")
