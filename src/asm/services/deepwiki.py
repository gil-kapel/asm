"""Deep repo fetcher — rich context from GitHub repos for advanced skill creation.

Fetches README, key source files, and documentation from a GitHub repo via the
GitHub API. Used by `asm create skill --from-repo` to provide rich context for
LLM-based skill generation.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

import httpx

_GITHUB_API = "https://api.github.com"
_MAX_CONTENT_CHARS = 60_000
_REQUEST_TIMEOUT = 15.0

_PRIORITY_FILES = [
    "README.md", "README.rst", "README.txt", "README",
    "CONTRIBUTING.md", "ARCHITECTURE.md",
    "docs/index.md", "docs/README.md", "docs/getting-started.md",
]
_SOURCE_EXTENSIONS = {".py", ".ts", ".js", ".go", ".rs", ".java", ".rb"}
_MAX_FILES = 20
_MAX_FILE_CHARS = 4000


@dataclass(frozen=True)
class GitHubRepoMatch:
    """Structured GitHub repository search result used for skill enrichment."""

    owner: str
    repo: str
    full_name: str
    description: str
    stars: int
    html_url: str


def fetch_repo_docs(
    owner: str,
    repo: str,
    *,
    max_chars: int = _MAX_CONTENT_CHARS,
) -> str:
    """Fetch documentation and key source files from a GitHub repo.

    Returns concatenated markdown with README, docs, and key source files.
    """
    headers = _github_headers()
    parts: list[str] = []
    total = 0

    with httpx.Client(timeout=_REQUEST_TIMEOUT, follow_redirects=True, headers=headers) as client:
        readme = _fetch_readme(client, owner, repo)
        if readme:
            section = f"# {owner}/{repo}\n\n{readme}"
            parts.append(section)
            total += len(section)

        tree = _fetch_tree(client, owner, repo)
        if tree:
            structure = _render_tree_summary(tree)
            parts.append(f"\n\n## Repository Structure\n\n```\n{structure}\n```")
            total += len(parts[-1])

            key_files = _select_key_files(tree)
            for path in key_files:
                if total >= max_chars:
                    break
                content = _fetch_file(client, owner, repo, path)
                if content:
                    section = f"\n\n## {path}\n\n```\n{content[:_MAX_FILE_CHARS]}\n```"
                    parts.append(section)
                    total += len(section)

    return "\n".join(parts)[:max_chars]


def search_github_repos(query: str, *, limit: int = 3) -> list[GitHubRepoMatch]:
    """Search GitHub repositories for enrichment candidates."""
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("GitHub search query cannot be empty.")
    if limit < 1:
        raise ValueError("GitHub search limit must be >= 1.")

    headers = _github_headers()
    try:
        with httpx.Client(timeout=_REQUEST_TIMEOUT, follow_redirects=True, headers=headers) as client:
            response = client.get(
                f"{_GITHUB_API}/search/repositories",
                params={
                    "q": normalized_query,
                    "sort": "stars",
                    "order": "desc",
                    "per_page": min(limit, 10),
                },
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"GitHub repository search failed: {exc}") from exc

    matches: list[GitHubRepoMatch] = []
    for item in payload.get("items", [])[:limit]:
        full_name = str(item.get("full_name", "")).strip()
        owner, repo = parse_repo_ref(full_name)
        matches.append(
            GitHubRepoMatch(
                owner=owner,
                repo=repo,
                full_name=full_name,
                description=str(item.get("description") or "").strip(),
                stars=int(item.get("stargazers_count") or 0),
                html_url=str(item.get("html_url") or "").strip(),
            )
        )
    return matches


def fetch_search_context(
    query: str,
    *,
    limit: int = 3,
    max_chars: int = _MAX_CONTENT_CHARS,
) -> tuple[str, list[GitHubRepoMatch]]:
    """Search GitHub repos, then fetch rich repo context for the top matches."""
    matches = search_github_repos(query, limit=limit)
    if not matches:
        return "", []

    parts = [f"# GitHub search context for: {query}"]
    total = len(parts[0])
    used_matches: list[GitHubRepoMatch] = []

    for match in matches:
        if total >= max_chars:
            break
        docs = fetch_repo_docs(match.owner, match.repo, max_chars=max_chars)
        if not docs:
            continue
        section = (
            f"\n\n## Search match: {match.full_name}\n"
            f"- stars: {match.stars}\n"
            f"- url: {match.html_url}\n"
            f"- description: {match.description or '(none)'}\n\n"
            f"{docs}"
        )
        remaining = max_chars - total
        if remaining <= 0:
            break
        parts.append(section[:remaining])
        total += len(parts[-1])
        used_matches.append(match)

    return "\n".join(parts)[:max_chars], used_matches


def parse_repo_ref(ref: str) -> tuple[str, str]:
    """Parse a repo reference into (owner, repo).

    Accepts:
      - "owner/repo"
      - "github.com/owner/repo"
      - "https://github.com/owner/repo"
      - "https://github.com/owner/repo/tree/main/..."
    """
    ref = ref.strip().rstrip("/")

    if ref.startswith("https://"):
        ref = ref.split("//", 1)[1]
    if ref.startswith("github.com/"):
        ref = ref[len("github.com/"):]

    parts = ref.split("/")
    if len(parts) < 2:
        raise ValueError(f"Invalid repo reference: expected 'owner/repo', got '{ref}'")

    return parts[0], parts[1]


def _github_headers() -> dict[str, str]:
    import os
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _fetch_readme(client: httpx.Client, owner: str, repo: str) -> str:
    """Fetch the repo's README via GitHub API."""
    try:
        resp = client.get(f"{_GITHUB_API}/repos/{owner}/{repo}/readme")
        if resp.status_code >= 400:
            return ""
        data = resp.json()
        content = data.get("content", "")
        encoding = data.get("encoding", "")
        if encoding == "base64" and content:
            return base64.b64decode(content).decode("utf-8", errors="replace")
        return content
    except Exception:
        return ""


def _fetch_tree(client: httpx.Client, owner: str, repo: str) -> list[dict]:
    """Fetch the repo's file tree (default branch, recursive)."""
    try:
        resp = client.get(
            f"{_GITHUB_API}/repos/{owner}/{repo}/git/trees/HEAD",
            params={"recursive": "1"},
        )
        if resp.status_code >= 400:
            return []
        data = resp.json()
        return data.get("tree", [])
    except Exception:
        return []


def _fetch_file(client: httpx.Client, owner: str, repo: str, path: str) -> str:
    """Fetch a single file's content via GitHub API."""
    try:
        resp = client.get(f"{_GITHUB_API}/repos/{owner}/{repo}/contents/{path}")
        if resp.status_code >= 400:
            return ""
        data = resp.json()
        content = data.get("content", "")
        encoding = data.get("encoding", "")
        if encoding == "base64" and content:
            return base64.b64decode(content).decode("utf-8", errors="replace")
        return content
    except Exception:
        return ""


def _render_tree_summary(tree: list[dict]) -> str:
    """Render a compact directory listing from the tree."""
    dirs: set[str] = set()
    files: list[str] = []

    for entry in tree:
        path = entry.get("path", "")
        if entry.get("type") == "tree":
            depth = path.count("/")
            if depth <= 1:
                dirs.add(path + "/")
        elif entry.get("type") == "blob":
            depth = path.count("/")
            if depth == 0 or (depth == 1 and any(path.startswith(d) for d in dirs)):
                files.append(path)

    lines = sorted(dirs) + sorted(files[:50])
    return "\n".join(lines)


def _select_key_files(tree: list[dict]) -> list[str]:
    """Pick the most informative files from the tree."""
    all_paths = [e["path"] for e in tree if e.get("type") == "blob"]
    selected: list[str] = []
    seen: set[str] = set()

    for priority in _PRIORITY_FILES:
        for path in all_paths:
            if path.lower() == priority.lower() and path not in seen:
                selected.append(path)
                seen.add(path)

    for path in all_paths:
        if len(selected) >= _MAX_FILES:
            break
        if path in seen:
            continue
        ext = _ext(path)
        if ext in _SOURCE_EXTENSIONS:
            depth = path.count("/")
            if depth <= 2:
                selected.append(path)
                seen.add(path)

    doc_paths = [p for p in all_paths if p not in seen and _is_doc(p)]
    for path in doc_paths[:5]:
        if len(selected) >= _MAX_FILES:
            break
        selected.append(path)

    return selected


def _ext(path: str) -> str:
    dot = path.rfind(".")
    return path[dot:].lower() if dot >= 0 else ""


def _is_doc(path: str) -> bool:
    lower = path.lower()
    return (
        lower.endswith(".md")
        and ("doc" in lower or "guide" in lower or "tutorial" in lower)
        and path.count("/") <= 2
    )
