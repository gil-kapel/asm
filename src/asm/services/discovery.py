"""Discovery service for federated `asm search` lookups."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
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
_PLAYBOOKS_FIND_ADD_RE = re.compile(
    r"^- \[(?P<tier>[^\]]+)\]\s+"
    r"(?:(?:\((?P<installs>\d+)\s+installs\))\s+)?"
    r"npx\s+playbooks\s+add\s+skill\s+"
    r"(?P<owner>[a-zA-Z0-9._-]+)/(?P<repo>[a-zA-Z0-9._-]+)\s+"
    r"--skill\s+(?P<skill>[a-zA-Z0-9._-]+)\s*$"
)
SMITHERY_FIELDS = "namespace,slug,displayName,externalStars,categories,gitUrl"


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
    q = query.lower()
    score = 0.0
    haystack = f"{item.name} {item.description} {' '.join(item.tags)}".lower()
    if q in haystack:
        score += 3.0
    if item.name.lower().startswith(q):
        score += 2.0
    if "python" in haystack:
        score += 1.0
    if item.provider == "asm-index":
        score += 1.0
    if any(h in haystack for h in hints):
        score += 2.0
    return score
