"""ASM curated index provider.

Reads a curated JSON index (shipped in-repo or fetched remotely) and
returns quality-scored DiscoveryItems with embedding-based semantic search.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

from asm.core.models import DiscoveryItem
from asm.services import embeddings

_REMOTE_INDEX_URL = (
    "https://raw.githubusercontent.com/gil-kapel/asm/main/registry/index.json"
)
_CACHE_MAX_AGE_S = 3600 * 6  # refresh every 6 hours
_MIN_QUALITY = 0.0  # return all entries; let scoring handle ranking


def _user_cache_path() -> Path:
    home = os.environ.get("ASM_HOME", "").strip()
    base = Path(home).expanduser() if home else Path.home() / ".asm-cli"
    return base / "index.json"


def _bundled_index_path() -> Path:
    """Index shipped inside the repo (development / offline fallback)."""
    return Path(__file__).resolve().parents[3] / "registry" / "index.json"


def _load_index() -> list[dict]:
    """Load the curated index, preferring cached remote > bundled fallback."""
    cached = _user_cache_path()

    if cached.exists():
        age = time.time() - cached.stat().st_mtime
        if age < _CACHE_MAX_AGE_S:
            return _parse_index(cached)

    fetched = _fetch_remote(cached)
    if fetched is not None:
        return fetched

    if cached.exists():
        return _parse_index(cached)

    bundled = _bundled_index_path()
    if bundled.exists():
        return _parse_index(bundled)

    return []


def _fetch_remote(dest: Path) -> list[dict] | None:
    try:
        with httpx.Client(timeout=5.0, follow_redirects=True) as client:
            resp = client.get(_REMOTE_INDEX_URL)
            resp.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(resp.text, encoding="utf-8")
        return _parse_index(dest)
    except Exception:
        return None


def _parse_index(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("skills", []) if isinstance(data, dict) else []
    except Exception:
        return []


def search(query: str) -> list[DiscoveryItem]:
    """Search the curated index using embeddings + quality score."""
    entries = _load_index()
    if not entries:
        return []

    query_vec = embeddings.embed(query)

    haystacks = [
        f"{e.get('name', '')} {e.get('description', '')} {' '.join(e.get('tags', []))} {e.get('use_when', '')}"
        for e in entries
    ]
    entry_vecs = embeddings.embed_batch(haystacks)

    scored: list[tuple[float, dict]] = []
    for entry, h_vec in zip(entries, entry_vecs):
        quality = float(entry.get("quality_score", 0.5))
        sim = embeddings.cosine_similarity(query_vec, h_vec)
        score = 0.6 * sim + 0.4 * quality
        scored.append((score, entry))

    scored.sort(key=lambda t: t[0], reverse=True)

    out: list[DiscoveryItem] = []
    for score, entry in scored:
        name = entry.get("name", "")
        if not name:
            continue
        out.append(
            DiscoveryItem(
                provider="asm-index",
                identifier=name,
                name=f"[curated] {name}",
                description=entry.get("description", ""),
                url=entry.get("source", ""),
                install_source=entry.get("source", ""),
                stars=None,
                tags=entry.get("tags", []),
                score=score,
            )
        )
    return out


def healthcheck() -> bool:
    """Always healthy — falls back to bundled index."""
    return True
