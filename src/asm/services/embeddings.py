"""Embedding service with API-based vectors and local msgpack cache.

Uses LiteLLM for embedding API calls (same optional dependency as llm.py).
Falls back to BLAKE2b hash-based vectors when LiteLLM or API keys are unavailable.
Cache is content-addressed at ~/.asm-cli/embeddings.msgpack.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from pathlib import Path

import msgpack

_EMBED_DIM_HASH = 128
_EMBED_DIM_API = 1536
_CACHE_FILENAME = "embeddings.msgpack"
_DEFAULT_MODEL = "text-embedding-3-small"


def _cache_path() -> Path:
    home = os.environ.get("ASM_HOME", "").strip()
    base = Path(home).expanduser() if home else Path.home() / ".asm-cli"
    return base / _CACHE_FILENAME


def _load_cache() -> dict[str, list[float]]:
    path = _cache_path()
    if not path.exists():
        return {}
    try:
        raw = path.read_bytes()
        data = msgpack.unpackb(raw, raw=False)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save_cache(cache: dict[str, list[float]]) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    packed = msgpack.packb(cache, use_bin_type=True)
    path.write_bytes(packed)


def _content_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _litellm_available() -> bool:
    try:
        import litellm  # noqa: F401
        return True
    except ImportError:
        return False


def _has_api_key() -> bool:
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AZURE_API_KEY"):
        if os.environ.get(key, "").strip():
            return True
    return False


def _get_model() -> str:
    return os.environ.get("ASM_EMBED_MODEL", _DEFAULT_MODEL).strip()


def can_use_api() -> bool:
    """True when real API-based embeddings are available."""
    return _litellm_available() and _has_api_key()


def embed(text: str) -> list[float]:
    """Embed a single text. Uses API when available, hash fallback otherwise."""
    if not text.strip():
        return _zero_vector()

    cache = _load_cache()
    key = _content_key(text)

    if key in cache:
        return cache[key]

    if can_use_api():
        vec = _embed_api(text)
    else:
        vec = _hash_embedding(text)

    cache[key] = vec
    _save_cache(cache)
    return vec


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed multiple texts, using cache and batching API calls."""
    if not texts:
        return []

    cache = _load_cache()
    results: list[list[float] | None] = [None] * len(texts)
    uncached_indices: list[int] = []
    uncached_texts: list[str] = []

    for i, text in enumerate(texts):
        if not text.strip():
            results[i] = _zero_vector()
            continue
        key = _content_key(text)
        if key in cache:
            results[i] = cache[key]
        else:
            uncached_indices.append(i)
            uncached_texts.append(text)

    if uncached_texts:
        if can_use_api():
            vectors = _embed_api_batch(uncached_texts)
        else:
            vectors = [_hash_embedding(t) for t in uncached_texts]

        for idx, vec in zip(uncached_indices, vectors):
            results[idx] = vec
            cache[_content_key(texts[idx])] = vec

        _save_cache(cache)

    return [v if v is not None else _zero_vector() for v in results]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity between two vectors."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for va, vb in zip(a, b):
        dot += va * vb
        norm_a += va * va
        norm_b += vb * vb
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def embedding_dim() -> int:
    """Current embedding dimensionality (API or fallback)."""
    return _EMBED_DIM_API if can_use_api() else _EMBED_DIM_HASH


def _zero_vector() -> list[float]:
    return [0.0] * embedding_dim()


def _embed_api(text: str) -> list[float]:
    import litellm
    model = _get_model()
    try:
        response = litellm.embedding(model=model, input=[text])
        return response.data[0]["embedding"]
    except Exception:
        return _hash_embedding(text)


def _embed_api_batch(texts: list[str]) -> list[list[float]]:
    import litellm
    model = _get_model()
    batch_size = 100
    all_vectors: list[list[float]] = []

    for start in range(0, len(texts), batch_size):
        chunk = texts[start : start + batch_size]
        try:
            response = litellm.embedding(model=model, input=chunk)
            sorted_data = sorted(response.data, key=lambda d: d["index"])
            all_vectors.extend(d["embedding"] for d in sorted_data)
        except Exception:
            all_vectors.extend(_hash_embedding(t) for t in chunk)

    return all_vectors


# ── Hash-based fallback (moved from discovery.py) ───────────────────

def _hash_embedding(text: str) -> list[float]:
    """BLAKE2b hash-based pseudo-embedding. No API required."""
    vec = [0.0] * _EMBED_DIM_HASH
    for token in _tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, byteorder="little", signed=False)
        idx = value % _EMBED_DIM_HASH
        sign = -1.0 if ((value >> 7) & 1) else 1.0
        vec[idx] += sign
    return vec


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) >= 2}
