"""Fetch skills from Smithery registry references."""

from __future__ import annotations

from urllib.parse import urlparse

import httpx


def fetch_ref(location: str) -> str:
    """Resolve Smithery location into a concrete GitHub skill URL."""
    namespace, slug = _parse_location(location)
    api_url = f"https://api.smithery.ai/skills/{namespace}/{slug}"
    resp = httpx.get(api_url, timeout=10.0, follow_redirects=True)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        raise ValueError(f"Unexpected Smithery response for {namespace}/{slug}")
    git_url = str(payload.get("gitUrl", "")).strip()
    if not git_url:
        raise ValueError(
            f"Smithery skill '{namespace}/{slug}' does not expose a gitUrl."
        )
    return git_url


def _parse_location(location: str) -> tuple[str, str]:
    loc = location.strip().strip("/")
    if "smithery.ai/skill/" in loc:
        parsed = urlparse(loc if loc.startswith("http") else f"https://{loc}")
        marker = "/skill/"
        if marker not in parsed.path:
            raise ValueError(f"Invalid Smithery skill URL: {location}")
        tail = parsed.path.split(marker, 1)[1].strip("/")
        parts = [p for p in tail.split("/") if p]
    else:
        parts = [p for p in loc.split("/") if p]

    if len(parts) < 2:
        raise ValueError(
            "Smithery reference must be 'namespace/slug' or smithery skill URL."
        )
    return parts[0], parts[1]
