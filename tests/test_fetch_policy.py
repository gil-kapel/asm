"""Fetch policy, safe tree copy, and config wiring."""

from __future__ import annotations

from pathlib import Path
import pytest

from asm.core.models import FetchPolicy
from asm.fetchers.fetch_policy import parse_github_skill_ref, validate_subpath
from asm.fetchers.safe_tree import SkillInstallLimitsExceeded, copy_skill_tree
from asm.repo import config


def test_parse_github_skill_ref_https_rejects_disallowed_host() -> None:
    policy = FetchPolicy.default_policy()
    with pytest.raises(ValueError, match="not allowed"):
        parse_github_skill_ref("https://evil.example.com/a/b", policy)


def test_parse_github_skill_ref_rejects_http_scheme() -> None:
    policy = FetchPolicy.default_policy()
    with pytest.raises(ValueError, match="https"):
        parse_github_skill_ref("http://github.com/a/b", policy)


def test_parse_github_skill_ref_rejects_bad_subpath() -> None:
    policy = FetchPolicy.default_policy()
    with pytest.raises(ValueError, match="Unsafe"):
        parse_github_skill_ref("https://github.com/o/r/tree/main/a/../b", policy)


def test_validate_subpath_rejects_dot_dot() -> None:
    with pytest.raises(ValueError):
        validate_subpath("foo/../bar")


def test_parse_github_skill_ref_short_form_requires_github_in_allowlist() -> None:
    policy = FetchPolicy(allow_local=True, allowed_git_hosts=["git.enterprise.example"])
    with pytest.raises(ValueError, match="Short-form"):
        parse_github_skill_ref("org/repo", policy)


def test_copy_skill_tree_rejects_symlink(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    real = src / "SKILL.md"
    real.write_text("---\nname: x\ndescription: y\n---\n", encoding="utf-8")
    link = src / "bad"
    link.symlink_to(real)
    policy = FetchPolicy.default_policy()
    with pytest.raises(ValueError, match="symbolic link"):
        copy_skill_tree(src, dst, policy)


def test_copy_skill_tree_enforces_max_file_count(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    (src / "a.txt").write_text("a", encoding="utf-8")
    (src / "b.txt").write_text("b", encoding="utf-8")
    policy = FetchPolicy.default_policy()
    policy.max_file_count = 1
    with pytest.raises(SkillInstallLimitsExceeded):
        copy_skill_tree(src, dst, policy)


def test_config_roundtrip_fetch(tmp_path: Path) -> None:
    path = tmp_path / "asm.toml"
    path.write_text(
        '[project]\nname = "t"\n\n[fetch]\nallow_local = false\n'
        'allowed_git_hosts = ["github.com", "git.example.org"]\n'
        "max_total_bytes = 1000\nmax_file_count = 50\n",
        encoding="utf-8",
    )
    cfg = config.load(path)
    assert cfg.fetch.allow_local is False
    assert cfg.fetch.allowed_git_hosts == ["github.com", "git.example.org"]
    assert cfg.fetch.max_total_bytes == 1000
    assert cfg.fetch.max_file_count == 50
    config.save(cfg, path)
    again = config.load(path)
    assert again.fetch.allow_local is False
    assert again.fetch.allowed_git_hosts == ["github.com", "git.example.org"]


def test_local_fetch_disallowed_raises() -> None:
    from asm.fetchers import local as local_fetcher

    policy = FetchPolicy(allow_local=False, allowed_git_hosts=["github.com"])
    with pytest.raises(ValueError, match="allow_local"):
        local_fetcher.fetch("/tmp/nope", Path("/tmp/out"), policy=policy)


def test_github_fetch_rejects_host_before_git(tmp_path: Path) -> None:
    from asm.fetchers import github as gh

    policy = FetchPolicy(allow_local=True, allowed_git_hosts=["github.com"])
    dest = tmp_path / "out"
    with pytest.raises(ValueError, match="not allowed"):
        gh.fetch("https://gitlab.com/a/b", dest, policy=policy)
