"""Security regression tests for skill fetch / install hardening.

These encode known abuse patterns; they should keep failing (raising) as long
as the protection layer is in place.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from asm.core.models import FetchPolicy
from asm.fetchers import fetch as fetch_dispatch
from asm.fetchers.fetch_policy import parse_github_skill_ref, validate_subpath
from asm.fetchers.safe_tree import SkillInstallLimitsExceeded, copy_skill_tree
from asm.repo import lockfile


# ── URL / host abuse (SSRF-style, scheme smuggling, typosquat hosts) ─────────


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/org/repo",
        "https://[::1]/org/repo",
        "https://localhost/org/repo",
        "https://github.com.evil.corp/org/repo",
        "https://evil.github.com/org/repo",
        "https://api.github.com/orgs/foo",
        "file:///etc/passwd",
        "ftp://github.com/foo/bar",
    ],
)
def test_vuln_https_url_rejects_non_allowlisted_host(url: str) -> None:
    policy = FetchPolicy.default_policy()
    with pytest.raises(ValueError):
        parse_github_skill_ref(url, policy)


def test_vuln_http_not_https() -> None:
    policy = FetchPolicy.default_policy()
    with pytest.raises(ValueError, match="https"):
        parse_github_skill_ref("http://github.com/foo/bar", policy)


def test_vuln_empty_allowed_git_hosts_rejected() -> None:
    policy = FetchPolicy(allow_local=True, allowed_git_hosts=[])
    with pytest.raises(ValueError, match="allowed_git_hosts"):
        parse_github_skill_ref("https://github.com/a/b", policy)


def test_vuln_github_looking_path_on_evil_host() -> None:
    """Path looks like GitHub but host is attacker-controlled."""
    policy = FetchPolicy.default_policy()
    with pytest.raises(ValueError, match="not allowed"):
        parse_github_skill_ref(
            "https://attacker.example/github.com/foo/bar/tree/main/skill",
            policy,
        )


# ── Path traversal in repo subpath ───────────────────────────────────────────


@pytest.mark.parametrize(
    "subpath",
    [
        "..",
        "../etc",
        "foo/../../bar",
        "foo/..",
        "foo/./bar",
        "foo//bar",
    ],
)
def test_vuln_subpath_traversal_rejected(subpath: str) -> None:
    with pytest.raises(ValueError, match="Unsafe|empty"):
        validate_subpath(subpath)


@pytest.mark.parametrize(
    "raw",
    [
        "evil/repo/foo/../bar",
        "evil/repo/../other",
    ],
)
def test_vuln_short_form_traversal_rejected(raw: str) -> None:
    policy = FetchPolicy.default_policy()
    with pytest.raises(ValueError, match="Unsafe"):
        parse_github_skill_ref(raw, policy)


# ── Symlink / install limits ─────────────────────────────────────────────────


def test_vuln_symlink_file_rejected_on_install(tmp_path: Path) -> None:
    src = tmp_path / "skill"
    src.mkdir()
    secret = tmp_path / "secret"
    secret.write_text("PRIVATE", encoding="utf-8")
    (src / "SKILL.md").write_text(
        "---\nname: x\ndescription: y\n---\n", encoding="utf-8"
    )
    (src / "leak").symlink_to(secret)
    policy = FetchPolicy.default_policy()
    with pytest.raises(ValueError, match="symbolic link"):
        copy_skill_tree(src, tmp_path / "out", policy)


def test_vuln_max_total_bytes_prevents_large_tree(tmp_path: Path) -> None:
    src = tmp_path / "skill"
    src.mkdir()
    (src / "SKILL.md").write_text(
        "---\nname: x\ndescription: y\n---\n", encoding="utf-8"
    )
    (src / "big.bin").write_bytes(b"x" * 500)
    policy = FetchPolicy.default_policy()
    policy.max_total_bytes = 100
    with pytest.raises(SkillInstallLimitsExceeded, match="max_total_bytes"):
        copy_skill_tree(src, tmp_path / "out", policy)


def test_vuln_lockfile_integrity_skips_symlinks(tmp_path: Path) -> None:
    """Symlinked files must not contribute bytes from arbitrary targets."""
    body = "---\nname: x\ndescription: y\n---\n"
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(body, encoding="utf-8")
    secret = tmp_path / "secret"
    secret.write_text("NOT_IN_HASH", encoding="utf-8")
    (skill / "x").symlink_to(secret)

    clean = tmp_path / "skill_clean"
    clean.mkdir()
    (clean / "SKILL.md").write_text(body, encoding="utf-8")

    assert lockfile.compute_integrity(skill) == lockfile.compute_integrity(clean)


# ── Local source disabled ────────────────────────────────────────────────────


def test_vuln_fetch_dispatch_local_blocked_when_disabled(tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    dest.mkdir()
    skill_src = tmp_path / "srcskill"
    skill_src.mkdir()
    (skill_src / "SKILL.md").write_text(
        "---\nname: a\ndescription: b\n---\n", encoding="utf-8"
    )
    policy = FetchPolicy(allow_local=False, allowed_git_hosts=["github.com"])
    with pytest.raises(ValueError, match="allow_local"):
        fetch_dispatch("local", str(skill_src), tmp_path / "out", policy=policy)


# ── Registry returns malicious gitUrl (Smithery) ──────────────────────────────


def test_vuln_smithery_malicious_git_url_blocked(tmp_path: Path) -> None:
    """Resolved gitUrl must pass the same host policy before git runs."""
    policy = FetchPolicy.default_policy()
    fake = MagicMock()
    fake.raise_for_status = MagicMock()
    fake.json.return_value = {"gitUrl": "https://evil.example.com/a/b/tree/main/x"}

    with patch("asm.fetchers.smithery.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = fake
        with pytest.raises(ValueError, match="not allowed"):
            fetch_dispatch(
                "smithery",
                "ns/slug",
                tmp_path / "out",
                policy=policy,
            )


def test_vuln_smithery_git_url_http_scheme_rejected(tmp_path: Path) -> None:
    policy = FetchPolicy.default_policy()
    fake = MagicMock()
    fake.raise_for_status = MagicMock()
    fake.json.return_value = {"gitUrl": "http://github.com/foo/bar"}

    with patch("asm.fetchers.smithery.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = fake
        with pytest.raises(ValueError, match="https"):
            fetch_dispatch(
                "smithery",
                "ns/slug",
                tmp_path / "out",
                policy=policy,
            )


# ── Playbooks HTML exposes only allowlisted tree URL ─────────────────────────


def test_vuln_playbooks_resolved_github_url_respects_allowlist(tmp_path: Path) -> None:
    """Playbooks HTML only yields github.com URLs; policy must still gate the clone."""
    policy = FetchPolicy(allow_local=True, allowed_git_hosts=["git.enterprise.example"])
    html = '<a href="https://github.com/o/r/tree/main/skill">y</a>'
    fake = MagicMock()
    fake.raise_for_status = MagicMock()
    fake.text = html

    with patch("asm.fetchers.playbooks.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = fake
        with pytest.raises(ValueError, match="not allowed"):
            fetch_dispatch(
                "playbooks",
                "owner/repo/skill",
                tmp_path / "out",
                policy=policy,
            )


def test_vuln_playbooks_first_match_must_be_valid_for_policy(tmp_path: Path) -> None:
    """Regex returns first github.com/tree match — if it's evil path, subpath may still fail."""
    policy = FetchPolicy.default_policy()
    # Valid host/path shape but traversal in tree subpath
    html = 'href="https://github.com/o/r/tree/main/foo/../bar"'
    fake = MagicMock()
    fake.raise_for_status = MagicMock()
    fake.text = html

    with patch("asm.fetchers.playbooks.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = fake
        with pytest.raises(ValueError, match="Unsafe"):
            fetch_dispatch(
                "playbooks",
                "owner/repo/skill",
                tmp_path / "out",
                policy=policy,
            )
