"""Embedding service with API-based vectors and local msgpack cache.

Uses the OpenAI embeddings API for remote vectors.
Falls back to BLAKE2b hash-based vectors when OpenAI or API keys are unavailable.
Cache is content-addressed at ~/.asm-cli/embeddings.msgpack.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from pathlib import Path

import msgpack
from openai import OpenAI
from asm.core.models import EmbeddingProfile

_EMBED_DIM_HASH = 128
_EMBED_DIM_API = 1536
_CACHE_FILENAME = "embeddings.msgpack"
_DEFAULT_MODEL = "text-embedding-3-small"
_DISTANCE_METRIC = "cosine"
_NORMALIZED = False


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


def _content_key(text: str, profile: EmbeddingProfile) -> str:
    payload = "|".join(
        [
            profile.provider,
            profile.model,
            str(profile.dimension),
            str(profile.normalized).lower(),
            profile.distance_metric,
            profile.embedding_version,
            text,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _has_api_key() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def _get_model() -> str:
    return _normalize_openai_model(os.environ.get("ASM_EMBED_MODEL"))


def current_profile(*, analysis_mode: str = "local") -> EmbeddingProfile:
    """Return the active embedding profile for cache/version provenance."""
    api_enabled = can_use_api()
    provider = "openai" if api_enabled else "hash-fallback"
    model = _get_model() if api_enabled else "asm-hash-v1"
    dimension = _EMBED_DIM_API if api_enabled else _EMBED_DIM_HASH
    embedding_version = f"{provider}:{model}:{dimension}:{_DISTANCE_METRIC}:norm={str(_NORMALIZED).lower()}"
    return EmbeddingProfile(
        provider=provider,
        model=model,
        dimension=dimension,
        normalized=_NORMALIZED,
        distance_metric=_DISTANCE_METRIC,
        embedding_version=embedding_version,
        analysis_mode=analysis_mode,
    )


def profile_from_dict(raw: dict, *, analysis_mode: str = "local") -> EmbeddingProfile:
    """Parse an embedding profile payload with safe defaults."""
    fallback = current_profile(analysis_mode=analysis_mode)
    return EmbeddingProfile(
        provider=str(raw.get("provider", fallback.provider)),
        model=str(raw.get("model", fallback.model)),
        dimension=int(raw.get("dimension", fallback.dimension)),
        normalized=bool(raw.get("normalized", fallback.normalized)),
        distance_metric=str(raw.get("distance_metric", fallback.distance_metric)),
        embedding_version=str(raw.get("embedding_version", fallback.embedding_version)),
        analysis_mode=str(raw.get("analysis_mode", analysis_mode or fallback.analysis_mode)),
    )


def can_use_api() -> bool:
    """True when real API-based embeddings are available."""
    return _has_api_key() and _supports_openai_model(os.environ.get("ASM_EMBED_MODEL"))


def embed(text: str) -> list[float]:
    """Embed a single text. Uses API when available, hash fallback otherwise."""
    if not text.strip():
        return _zero_vector()

    cache = _load_cache()
    profile = current_profile()
    key = _content_key(text, profile)

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
    profile = current_profile()
    results: list[list[float] | None] = [None] * len(texts)
    uncached_indices: list[int] = []
    uncached_texts: list[str] = []

    for i, text in enumerate(texts):
        if not text.strip():
            results[i] = _zero_vector()
            continue
        key = _content_key(text, profile)
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
            cache[_content_key(texts[idx], profile)] = vec

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
    model = _get_model()
    try:
        response = _client().embeddings.create(model=model, input=[text])
        return response.data[0].embedding
    except Exception:
        return _hash_embedding(text)


def _embed_api_batch(texts: list[str]) -> list[list[float]]:
    model = _get_model()
    batch_size = 100
    all_vectors: list[list[float]] = []

    for start in range(0, len(texts), batch_size):
        chunk = texts[start : start + batch_size]
        try:
            response = _client().embeddings.create(model=model, input=chunk)
            sorted_data = sorted(response.data, key=lambda d: d.index)
            all_vectors.extend(d.embedding for d in sorted_data)
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


def _client() -> OpenAI:
    return OpenAI(
        api_key=os.environ.get("OPENAI_API_KEY"),
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
    )


def _normalize_openai_model(model: str | None) -> str:
    raw = (model or _DEFAULT_MODEL).strip()
    if not raw:
        return _DEFAULT_MODEL
    if "/" in raw:
        provider, _, candidate = raw.partition("/")
        if provider != "openai":
            raise ValueError(f"ASM embeddings only support OpenAI models now. Got: {raw}")
        normalized = candidate.strip()
        return normalized or _DEFAULT_MODEL
    return raw


def _supports_openai_model(model: str | None) -> bool:
    raw = (model or "").strip()
    return not raw or "/" not in raw or raw.startswith("openai/")
