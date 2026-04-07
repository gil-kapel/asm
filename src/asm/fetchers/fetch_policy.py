"""Parse and validate remote git skill references against FetchPolicy."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from asm.core.models import FetchPolicy

_SKILL_REF_PATH = re.compile(
    r"^/([^/]+)/([^/]+?)(?:\.git)?(?:/tree/([^/]+)(?:/(.+))?)?$",
    re.IGNORECASE,
)


def normalize_host(hostname: str) -> str:
    return (hostname or "").strip().lower().rstrip(".")


def host_allowlist(policy: FetchPolicy) -> set[str]:
    return {normalize_host(h) for h in policy.allowed_git_hosts if str(h).strip()}


def validate_subpath(subpath: str) -> None:
    if not subpath:
        return
    normalized = subpath.replace("\\", "/")
    for seg in normalized.split("/"):
        if seg in ("", ".", ".."):
            raise ValueError(
                f"Unsafe skill path segment in repository subpath: {subpath!r} "
                "(rejecting '.', '..', and empty segments)."
            )
        if "\\" in seg:
            raise ValueError(f"Backslashes are not allowed in skill subpath: {subpath!r}")


def parse_github_skill_ref(raw: str, policy: FetchPolicy) -> tuple[str, str, str]:
    """Parse a skill source into (https clone URL ending in .git, branch, subpath).

    *raw* may be a full https URL or shorthand ``owner/repo`` / ``owner/repo/subdir``.
    """
    raw = raw.strip()
    allowed = host_allowlist(policy)
    if not allowed:
        raise ValueError("[fetch] allowed_git_hosts must not be empty.")

    if "://" in raw:
        parsed = urlparse(raw)
        if parsed.scheme != "https":
            raise ValueError("Only https:// Git URLs are allowed for skill fetch.")
        host = normalize_host(parsed.hostname or "")
        if host not in allowed:
            raise ValueError(
                f"Git host {host!r} is not allowed. "
                f"Add it under [fetch].allowed_git_hosts in asm.toml "
                f"(allowed: {sorted(allowed)})."
            )
        match = _SKILL_REF_PATH.match(parsed.path or "")
        if not match:
            raise ValueError(f"Unrecognized Git skill URL path: {parsed.path!r}")
        user, repo = match.group(1), match.group(2)
        branch, subpath = match.group(3), match.group(4) or ""
        validate_subpath(subpath)
        repo_url = f"https://{host}/{user}/{repo}.git"
        return repo_url, (branch or "main"), subpath

    parts = [p for p in raw.split("/") if p]
    if len(parts) >= 2:
        if normalize_host("github.com") not in allowed:
            raise ValueError(
                "Short-form refs (owner/repo) assume github.com, which is not in "
                "[fetch].allowed_git_hosts — use a full https:// URL for your git host."
            )
        user, repo = parts[0], parts[1]
        subpath = "/".join(parts[2:]) if len(parts) > 2 else ""
        validate_subpath(subpath)
        return f"https://github.com/{user}/{repo}.git", "main", subpath

    raise ValueError(f"Cannot parse Git skill reference: {raw!r}")
