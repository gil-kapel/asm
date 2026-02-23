"""Fetch and extract text content from URLs (GitHub API contents, raw files)."""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx

# Max chars of context we inject into the LLM.
MAX_CONTEXT_CHARS = 50_000
# Max files to fetch when URL points to a directory (GitHub API).
MAX_FILES_FROM_DIR = 15
# Timeout for each request.
REQUEST_TIMEOUT = 30.0


def fetch_url_content(url: str, *, max_chars: int = MAX_CONTEXT_CHARS) -> str:
    """Fetch URL and return extracted text for use as skill source context.

    Supports:
    - GitHub API contents: api.github.com/repos/.../contents/...
      Single file: decodes base64 "content". Directory: fetches each file via download_url.
    - Raw or other URLs: returns response text (truncated to max_chars).
    """
    with httpx.Client(follow_redirects=True, timeout=REQUEST_TIMEOUT) as client:
        resp = client.get(url)
        resp.raise_for_status()
        content_type = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()

        if content_type == "application/json":
            return _extract_from_github_api(client, url, resp.json(), max_chars)

        text = resp.text
        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n[... truncated]"
        return text


def _extract_from_github_api(
    client: httpx.Client, base_url: str, data: Any, max_chars: int
) -> str:
    """Handle GitHub API contents response: single file (base64) or directory listing."""
    if isinstance(data, dict):
        # Single file
        if data.get("encoding") == "base64" and "content" in data:
            raw = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            if len(raw) > max_chars:
                return raw[:max_chars] + "\n\n[... truncated]"
            return raw
        # Unsupported (e.g. submodule)
        return f"[GitHub resource: {data.get('name', 'unknown')}]"

    if isinstance(data, list):
        # Directory: fetch files via download_url, prefer README and .md
        parts: list[str] = []
        total = 0
        files = [f for f in data if isinstance(f, dict) and f.get("type") == "file"]
        # Prefer README*.md and *.md then others
        def order_key(f: dict) -> tuple[int, str]:
            name = f.get("name", "")
            if name.upper().startswith("README"):
                return 0, name
            if name.endswith(".md"):
                return 1, name
            return 2, name
        files.sort(key=order_key)
        for f in files[:MAX_FILES_FROM_DIR]:
            if total >= max_chars:
                break
            download_url = f.get("download_url")
            if not download_url:
                continue
            try:
                r = client.get(download_url, timeout=REQUEST_TIMEOUT)
                r.raise_for_status()
                text = r.text
                take = min(len(text), max_chars - total)
                if take <= 0:
                    continue
                parts.append(f"### {f.get('name', '')}\n\n{text[:take]}")
                total += take
            except Exception:
                continue
        if not parts:
            return "[Directory: no files could be fetched]"
        return "\n\n".join(parts)

    return "[Unsupported GitHub API response]"
