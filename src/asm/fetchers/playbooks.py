"""Fetch skills from Playbooks references by resolving backing GitHub URL."""

from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx

_GITHUB_TREE_RE = re.compile(r"https://github\.com/[^\"' <>()]+/tree/[^\"' <>()]+")


def fetch_ref(location: str) -> str:
    """Resolve Playbooks location into a concrete GitHub skill URL."""
    page_url = _to_skill_url(location)
    resp = httpx.get(page_url, timeout=10.0, follow_redirects=True)
    resp.raise_for_status()
    text = resp.text
    match = _GITHUB_TREE_RE.search(text)
    if not match:
        raise ValueError(
            f"Playbooks skill page '{page_url}' does not expose a GitHub tree URL."
        )
    return match.group(0)


def _to_skill_url(location: str) -> str:
    loc = location.strip()
    if loc.startswith(("http://", "https://")):
        parsed = urlparse(loc)
        if "playbooks.com" not in parsed.netloc:
            raise ValueError(f"Not a Playbooks URL: {location}")
        return loc

    parts = [p for p in loc.strip("/").split("/") if p]
    if len(parts) >= 3:
        return f"https://playbooks.com/skills/{parts[0]}/{parts[1]}/{parts[2]}"
    if len(parts) == 2:
        return f"https://playbooks.com/skills/{parts[0]}/{parts[1]}"
    raise ValueError(
        "Playbooks reference must be URL, 'owner/repo/skill', or 'owner/repo'."
    )
