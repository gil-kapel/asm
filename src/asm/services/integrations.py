"""Agent integration — bridge .asm/ skills into IDE-native config files.

Strategy pattern: one sync function per agent.

Supported agents:
  - cursor   → .cursor/skills/asm/SKILL.md
  - claude   → CLAUDE.md  (sentinel-guarded section)
  - codex    → AGENTS.md  (sentinel-guarded section)
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from asm.core.models import AsmConfig

SENTINEL_START = "<!-- ASM:START -->"
SENTINEL_END = "<!-- ASM:END -->"

AGENTS = ("cursor", "claude", "codex")


# ── Per-agent strategies ────────────────────────────────────────────


def sync_cursor(root: Path, cfg: AsmConfig) -> Path:
    """Write .cursor/skills/asm/SKILL.md."""
    skill_dir = root / ".cursor" / "skills" / "asm"
    skill_dir.mkdir(parents=True, exist_ok=True)
    dest = skill_dir / "SKILL.md"

    lines = [
        "---",
        "name: asm",
        "description: ASM-managed advanced skill router. Always start here, then route via .asm/main_asm.md.",
        "---",
        "",
        "# ASM — Agent Skill Manager",
        "",
        "Always read `.asm/main_asm.md` first before selecting any skill.",
        "This skill is the required first-stop router for expertise selection.",
        "",
        "## Mandatory Flow",
        "",
        "1. Open `.asm/main_asm.md` and choose one expertise group.",
        "2. Open `.asm/expertises/<group>/index.md` and `relationships.md`.",
        "3. Load only the selected skills in relationship-safe order.",
        "4. Prefer advanced, non-trivial skills when the group provides them.",
        "",
    ]

    if cfg.expertises:
        lines.append("## Expertise Groups")
        lines.append("")
        for name, ref in cfg.expertises.items():
            purpose = ref.description or "No description provided."
            signals = ", ".join(ref.task_signals[:2]) if ref.task_signals else "n/a"
            lines.append(f"- **{name}** — {purpose}")
            lines.append(f"  - Signals: {signals}")
            lines.append(f"  - Router: `.asm/expertises/{name}/index.md`")
        lines.append("")

    if cfg.skills:
        lines.append("## Installed Skills (Reference Only)")
        lines.append("")
        lines.append("Do not pick directly from this list before expertise routing.")
        lines.append("")
        for name in cfg.skills:
            lines.append(f"- **{name}**: `.asm/skills/{name}/SKILL.md`")
        lines.append("")

    dest.write_text("\n".join(lines))
    return dest


def sync_claude(root: Path, cfg: AsmConfig) -> Path:
    """Insert/update an ASM section in CLAUDE.md."""
    return _sync_sentinel_file(root / "CLAUDE.md", cfg)


def sync_codex(root: Path, cfg: AsmConfig) -> Path:
    """Insert/update an ASM section in AGENTS.md."""
    return _sync_sentinel_file(root / "AGENTS.md", cfg)


# ── Shared helpers ──────────────────────────────────────────────────


_STRATEGY = {
    "cursor": sync_cursor,
    "claude": sync_claude,
    "codex": sync_codex,
}


def _build_sentinel_block(cfg: AsmConfig) -> str:
    lines = [
        SENTINEL_START,
        "Read `.asm/main_asm.md` before every task to identify active SOTA expertise.",
        "Follow the skill blueprints and relationship rules defined there.",
    ]
    if cfg.skills:
        lines.append("")
        lines.append("Installed skills:")
        for name in cfg.skills:
            lines.append(f"- {name}: `.asm/skills/{name}/SKILL.md`")
    if cfg.expertises:
        lines.append("")
        lines.append("Active expertises:")
        for name in cfg.expertises:
            lines.append(f"- {name}: `.asm/expertises/{name}/index.md`")
    lines.append(SENTINEL_END)
    return "\n".join(lines)


def _sync_sentinel_file(path: Path, cfg: AsmConfig) -> Path:
    block = _build_sentinel_block(cfg)
    if path.exists():
        content = path.read_text()
        pattern = re.compile(
            re.escape(SENTINEL_START) + r".*?" + re.escape(SENTINEL_END),
            re.DOTALL,
        )
        if pattern.search(content):
            content = pattern.sub(block, content)
        else:
            content = content.rstrip() + "\n\n" + block + "\n"
    else:
        content = block + "\n"
    path.write_text(content)
    return path


# ── Public API ──────────────────────────────────────────────────────


def detect_agents(root: Path) -> list[str]:
    """Auto-detect which agents are present based on directory/file markers."""
    found: list[str] = []
    if (root / ".cursor").is_dir():
        found.append("cursor")
    if (root / "CLAUDE.md").exists() or (root / ".claude").is_dir():
        found.append("claude")
    if (root / "AGENTS.md").exists():
        found.append("codex")
    return found


def detect_runtime_agents() -> list[str]:
    """Infer active agent context from runtime environment variables."""
    explicit = os.environ.get("ASM_AGENT", "").strip().lower()
    if explicit in AGENTS:
        return [explicit]

    found: list[str] = []
    if os.environ.get("CURSOR_TRACE_ID") or os.environ.get("CURSOR_SESSION_ID"):
        found.append("cursor")
    if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE"):
        found.append("claude")
    if os.environ.get("CODEX_HOME"):
        found.append("codex")
    return found


def sync_agent(root: Path, cfg: AsmConfig, agent: str) -> Path:
    fn = _STRATEGY.get(agent)
    if not fn:
        raise ValueError(f"Unknown agent: {agent!r}. Choose from: {', '.join(AGENTS)}")
    return fn(root, cfg)


def sync_all(
    root: Path, cfg: AsmConfig, agents: list[str] | None = None,
) -> dict[str, Path]:
    """Sync multiple agents. Auto-detects if *agents* is None."""
    targets = agents or detect_agents(root)
    return {name: sync_agent(root, cfg, name) for name in targets}
