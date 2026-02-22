"""Discovery service for federated `asm search` lookups."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
import hashlib
import math
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import quote_plus

import httpx

from asm.core import paths
from asm.repo import config

SMITHERY_SEARCH_URL = "https://api.smithery.ai/skills"
PLAYBOOKS_SEARCH_URL = "https://playbooks.com/skills"
GITHUB_SEARCH_URL = "https://github.com/search"
SKILLSMP_AI_SEARCH_URL = "https://skillsmp.com/api/v1/skills/ai-search"
SKILLSMP_SEARCH_URL = "https://skillsmp.com/api/v1/skills/search"
_PLAYBOOKS_FIND_ADD_RE = re.compile(
    r"^- \[(?P<tier>[^\]]+)\]\s+"
    r"(?:(?:\((?P<installs>\d+)\s+installs\))\s+)?"
    r"npx\s+playbooks\s+add\s+skill\s+"
    r"(?P<owner>[a-zA-Z0-9._-]+)/(?P<repo>[a-zA-Z0-9._-]+)\s+"
    r"--skill\s+(?P<skill>[a-zA-Z0-9._-]+)\s*$"
)
SMITHERY_FIELDS = "namespace,slug,displayName,externalStars,categories,gitUrl"
LEXICAL_WEIGHT = 0.75
SEMANTIC_WEIGHT = 0.20
STARS_WEIGHT = 0.05
_EMBED_DIM = 128


@dataclass
class DiscoveryItem:
    """Normalized search result across providers."""

    provider: str
    identifier: str
    name: str
    description: str
    url: str
    install_source: str
    stars: int | None = None
    tags: list[str] = field(default_factory=list)
    score: float = 0.0


@dataclass(frozen=True)
class ProviderSpec:
    """Provider contract with health check and search strategy."""

    name: str
    healthcheck: Callable[[httpx.Client, str], bool]
    searcher: Callable[[httpx.Client, str], list[DiscoveryItem]]


def resolve_registry_ref(ref: str) -> str:
    """Resolve provider short-hands to concrete URLs."""
    if ref.startswith("sm:"):
        return f"https://smithery.ai/skill/{ref[3:]}"
    if ref.startswith("pb:"):
        return f"{PLAYBOOKS_SEARCH_URL}?search={quote_plus(ref[3:])}&mode=semantic"
    if ref.startswith("gh:"):
        return f"https://github.com/{ref[3:]}"
    return ref


def search(query: str, *, root: Path | None = None, limit: int = 10) -> list[DiscoveryItem]:
    """Run federated provider search and return ranked results."""
    root = root or Path.cwd()
    hints = _load_context_hints(root)

    aggregated: list[DiscoveryItem] = []
    with httpx.Client(timeout=6.0, follow_redirects=True) as client:
        providers = _enabled_providers(client, query)
        if not providers:
            return []

        with ThreadPoolExecutor(max_workers=len(providers)) as pool:
            jobs = {
                pool.submit(spec.searcher, client, query): spec.name for spec in providers
            }
            for future in as_completed(jobs):
                try:
                    aggregated.extend(future.result())
                except Exception:
                    # Provider failures are isolated by design.
                    continue

    deduped = _dedupe(aggregated)
    for item in deduped:
        item.score = _score_item(item, query, hints)

    ranked = sorted(deduped, key=lambda i: i.score, reverse=True)
    return ranked[:limit]


def _enabled_providers(client: httpx.Client, query: str) -> list[ProviderSpec]:
    providers = (
        ProviderSpec("skillsmp", _health_skillsmp, _search_skillsmp),
        ProviderSpec("smithery", _health_smithery, _search_smithery),
        ProviderSpec("playbooks", _health_playbooks, _search_playbooks),
        ProviderSpec("github", _health_github, _search_github),
    )
    enabled: list[ProviderSpec] = []
    for provider in providers:
        try:
            if provider.healthcheck(client, query):
                enabled.append(provider)
        except Exception:
            continue
    return enabled


def _load_context_hints(root: Path) -> set[str]:
    hints: set[str] = set()
    cfg_path = root / paths.ASM_TOML
    if not cfg_path.exists():
        return hints

    cfg = config.load(cfg_path)
    hints.add(cfg.project.name.lower())
    hints.add(cfg.project.description.lower())
    for entry in cfg.skills.values():
        hints.add(entry.name.lower())
        hints.add(entry.source.lower())
    return {h for h in hints if h}


def _health_smithery(client: httpx.Client, query: str) -> bool:
    resp = client.get(
        SMITHERY_SEARCH_URL,
        params={
            "q": query,
            "pageSize": 1,
            "fields": SMITHERY_FIELDS,
        },
    )
    if resp.status_code >= 400:
        return False
    payload = resp.json()
    return isinstance(payload, dict) and isinstance(payload.get("skills"), list)


def _health_skillsmp(client: httpx.Client, query: str) -> bool:
    headers = _skillsmp_headers()
    if not headers:
        return False
    resp = client.get(SKILLSMP_AI_SEARCH_URL, params={"q": query}, headers=headers)
    if resp.status_code >= 400:
        return False
    return bool(_skillsmp_extract_rows(resp.json()))


def _search_skillsmp(client: httpx.Client, query: str) -> list[DiscoveryItem]:
    headers = _skillsmp_headers()
    if not headers:
        return []

    out: list[DiscoveryItem] = []
    seen: set[tuple[str, str]] = set()

    for url, params in (
        (SKILLSMP_AI_SEARCH_URL, {"q": query}),
        (SKILLSMP_SEARCH_URL, {"q": query, "page": 1, "limit": 20}),
    ):
        try:
            resp = client.get(url, params=params, headers=headers)
            resp.raise_for_status()
        except Exception:
            continue
        res = resp.json()

        for item in _skillsmp_parse_items(_skillsmp_extract_rows(res)):
            key = (item.identifier.lower(), item.url.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
    return out


def _search_smithery(client: httpx.Client, query: str) -> list[DiscoveryItem]:
    resp = client.get(
        SMITHERY_SEARCH_URL,
        params={
            "q": query,
            "pageSize": 20,
            "fields": SMITHERY_FIELDS,
        },
    )
    resp.raise_for_status()
    payload = resp.json()
    rows = payload.get("skills", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []

    out: list[DiscoveryItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        namespace = str(row.get("namespace", "")).strip()
        slug = str(row.get("slug") or "").strip()
        if not namespace or not slug:
            continue
        identifier = f"{namespace}/{slug}"
        name = str(row.get("displayName") or slug).strip()
        stars = row.get("externalStars")
        categories = row.get("categories", [])
        git_url = str(row.get("gitUrl", "")).strip()
        install_source = f"github:{git_url}" if git_url else f"sm:{identifier}"
        description = (
            f"Smithery skill {identifier}"
            + (f" • stars: {stars}" if stars is not None else "")
        )
        out.append(
            DiscoveryItem(
                provider="smithery",
                identifier=identifier,
                stars=stars,
                name=name,
                description=description or "No description provided.",
                url=git_url or resolve_registry_ref(f"sm:{identifier}"),
                install_source=install_source,
                tags=[str(t) for t in categories if isinstance(t, str)],
            )
        )
    out = sorted(out, key=lambda i: i.stars, reverse=True)
    return out


def _skillsmp_headers() -> dict[str, str] | None:
    token = os.environ.get("SKILLSMP_API_KEY", "").strip()
    if not token:
        return None
    return {"Authorization": f"Bearer {token}"}


def _skillsmp_extract_rows(payload: object) -> list[dict]:
    if not isinstance(payload, dict) or not payload.get("success"):
        return []

    data = payload.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if not isinstance(data, dict):
        return []

    # ai-search shape: data.data[] with nested row.skill
    ai_rows = data.get("data")
    if isinstance(ai_rows, list):
        out: list[dict] = []
        for row in ai_rows:
            if not isinstance(row, dict):
                continue
            skill_row = row.get("skill")
            if isinstance(skill_row, dict):
                out.append(skill_row)
            elif row:
                # Defensive fallback for potential envelope changes.
                out.append(row)
        return out

    # keyword-search shape: data.skills[]
    search_rows = data.get("skills")
    if isinstance(search_rows, list):
        return [row for row in search_rows if isinstance(row, dict)]
    return []

def _skillsmp_parse_items(rows: list[dict]) -> list[DiscoveryItem]:
    out: list[DiscoveryItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue

        identifier = str(row.get("id") or "").strip()
        name = str(row.get("name") or identifier).strip()
        if not identifier or not name:
            continue

        description = str(row.get("description") or "").strip()
        github_url = str(row.get("githubUrl") or "").strip()
        skill_url = str(row.get("skillUrl") or "").strip()
        url = github_url or skill_url or f"https://skillsmp.com/skills/{identifier}"
        stars_raw = row.get("stars")
        stars = stars_raw if isinstance(stars_raw, int) else None
        install_source = _skillsmp_install_source(row, url)

        out.append(
            DiscoveryItem(
                provider="skillsmp",
                identifier=identifier,
                name=name,
                description=description,
                url=url,
                install_source=install_source,
                stars=stars,
                tags=[],
            )
        )
    return out


def _skillsmp_install_source(row: dict, fallback_url: str) -> str:
    value = row.get("githubUrl")
    if isinstance(value, str) and "github.com/" in value:
        return f"github:{value.strip()}"
    return fallback_url


def _health_playbooks(client: httpx.Client, query: str) -> bool:
    del client, query
    try:
        completed = subprocess.run(
            ["npx", "playbooks", "find", "skill", "--help"],
            capture_output=True,
            text=True,
            check=False,
            timeout=8,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _search_playbooks(client: httpx.Client, query: str) -> list[DiscoveryItem]:
    del client
    try:
        completed = subprocess.run(
            ["npx", "playbooks", "find", "skill", query, "--semantic"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return []
    if completed.returncode != 0:
        return []

    seen: set[str] = set()
    out: list[DiscoveryItem] = []
    lines = completed.stdout.splitlines()
    for idx, line in enumerate(lines):
        match = _PLAYBOOKS_FIND_ADD_RE.match(line.strip())
        if not match:
            continue
        owner = match.group("owner")
        repo = match.group("repo")
        skill = match.group("skill")
        identifier = f"{owner}/{repo}/{skill}"
        if identifier in seen:
            continue
        seen.add(identifier)
        installs = match.group("installs")
        installs_suffix = f" • installs: {installs}" if installs else ""
        next_line = lines[idx + 1].strip() if idx + 1 < len(lines) else ""
        description = next_line if next_line and not next_line.startswith("- ") else ""
        out.append(
            DiscoveryItem(
                provider="playbooks",
                identifier=identifier,
                name=skill,
                description=description or f"Playbooks skill {identifier}{installs_suffix}",
                url=f"https://playbooks.com/skills/{identifier}",
                install_source=f"pb:{identifier}",
                tags=["playbooks"],
            )
        )
        if len(out) >= 20:
            break
    return out


def _health_github(client: httpx.Client, _query: str) -> bool:
    resp = client.get(
        GITHUB_SEARCH_URL,
        params={"q": "Skill.md", "type": "code"},
    )
    return resp.status_code < 400


def _search_github(client: httpx.Client, query: str) -> list[DiscoveryItem]:
    url = f"{GITHUB_SEARCH_URL}?q={quote_plus(f'{query} filename:Skill.md')}&type=code"
    resp = client.get(url)
    if resp.status_code >= 400:
        return []
    return [
        DiscoveryItem(
            provider="github",
            identifier=query,
            name=f"GitHub code search for '{query}'",
            description="Open GitHub code search results for Skill.md matches.",
            url=url,
            install_source=f"gh:search?q={quote_plus(query)}",
            tags=["github"],
        )
    ]


def _dedupe(items: list[DiscoveryItem]) -> list[DiscoveryItem]:
    seen: set[tuple[str, str, str]] = set()
    out: list[DiscoveryItem] = []
    for item in items:
        key = (item.provider, item.identifier.lower(), item.url.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _score_item(item: DiscoveryItem, query: str, hints: set[str]) -> float:
    if _is_search_query_url(item.url):
        return 0.0

    query_text = query.lower().strip()
    name = item.name.lower()
    description = item.description.lower()
    tags = " ".join(item.tags).lower()
    haystack = f"{name} {description} {tags}".strip()

    lexical = _lexical_score(item, query_text, haystack, name, hints)
    semantic = _semantic_similarity(query_text, haystack)
    stars = _stars_signal(item.stars)

    return (LEXICAL_WEIGHT * lexical) + (SEMANTIC_WEIGHT * semantic) + (STARS_WEIGHT * stars)


def _lexical_score(
    item: DiscoveryItem, query_text: str, haystack: str, name: str, hints: set[str],
) -> float:
    score = 0.0
    query_tokens = _tokens(query_text)
    name_tokens = _tokens(name)
    haystack_tokens = _tokens(haystack)
    token_overlap = len(query_tokens & haystack_tokens)
    query_token_count = max(len(query_tokens), 1)

    # Strong exact and prefix signals.
    if query_text and query_text in haystack:
        score += 4.0
    if query_text and name.startswith(query_text):
        score += 2.5

    # Token-level relevance: name matches weigh more than generic text matches.
    name_overlap = len(query_tokens & name_tokens)
    score += 2.0 * (name_overlap / query_token_count)
    score += 2.5 * (token_overlap / query_token_count)

    # Context hints from existing project config.
    if hints:
        hint_hits = sum(1 for h in hints if h and h in haystack)
        score += min(2.0, hint_hits * 0.5)

    # Keep ecosystem-fit as a small tie-breaker.
    if "python" in haystack and "python" in query_tokens:
        score += 0.5
    if item.provider == "asm-index":
        score += 0.5
    if item.provider == "github":
        score -= 1.0

    # "A bit of notice" to stars, but do not let popularity dominate relevance.
    if item.stars and item.stars > 0:
        score += min(1.2, (item.stars**0.5) / 100.0)

    # GitHub provider is a generic code-search fallback, not a direct skill card.
    if item.provider == "github" and item.install_source.startswith("gh:search"):
        score *= 0.35

    # Normalize lexical score into [0, 1] for blending.
    return max(0.0, min(1.0, score / 10.0))


def _semantic_similarity(query_text: str, haystack: str) -> float:
    if not query_text or not haystack:
        return 0.0
    q_vec = _light_embedding(query_text)
    h_vec = _light_embedding(haystack)
    sim = _cosine_similarity(q_vec, h_vec)
    return max(0.0, sim)


def _stars_signal(stars: int | None) -> float:
    if not stars or stars <= 0:
        return 0.0
    # Slow-growth signal, capped to avoid popularity dominating relevance.
    return min(1.0, math.sqrt(float(stars)) / 100.0)


def _light_embedding(text: str) -> list[float]:
    vec = [0.0] * _EMBED_DIM
    for token in _tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, byteorder="little", signed=False)
        idx = value % _EMBED_DIM
        sign = -1.0 if ((value >> 7) & 1) else 1.0
        vec[idx] += sign
    return vec


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for va, vb in zip(a, b, strict=False):
        dot += va * vb
        norm_a += va * va
        norm_b += vb * vb
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) >= 2}


def _is_search_query_url(url: str) -> bool:
    normalized = url.lower().strip()
    if not normalized:
        return False

    return (
        normalized.startswith("https://github.com/search?")
        and "type=code" in normalized
        and "q=" in normalized
    )
