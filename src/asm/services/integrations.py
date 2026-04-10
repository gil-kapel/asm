"""Agent integration — bridge .asm/ skills into IDE-native config files.

Strategy pattern: one sync function per agent.

Supported agents:
  - cursor   → .cursor/skills/asm/SKILL.md
  - claude   → CLAUDE.md (sentinel) + .claude/skills/asm/SKILL.md (Claude Code discovery)
  - codex    → AGENTS.md  (sentinel-guarded section)
  - copilot  → .github/skills/asm/SKILL.md (GitHub Copilot coding agent / VS Code)
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from asm.core.models import AsmConfig

SENTINEL_START = "<!-- ASM:START -->"
SENTINEL_END = "<!-- ASM:END -->"

AGENTS = ("cursor", "claude", "codex", "copilot")


# ── Shared SKILL.md content blocks ──────────────────────────────────


def _skill_md_header() -> list[str]:
    return [
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
    ]


def _skill_md_flow() -> list[str]:
    return [
        "## Mandatory Flow",
        "",
        "1. Open `.asm/main_asm.md` and choose one expertise group.",
        "2. Open `.asm/expertises/<group>/index.md` and `relationships.md`.",
        "3. Load only the selected skills in relationship-safe order.",
        "4. Prefer advanced, non-trivial skills when the group provides them.",
        "",
    ]


def _skill_md_discovery() -> list[str]:
    return [
        "## Skill Discovery & Installation",
        "",
        "**ALWAYS use `asm` for finding and installing skills. NEVER use `npx skills`, `npx playbooks`, or any other skill CLI directly.**",
        "",
        "- **Search:** `asm search <query>` — federated search across all registries.",
        "- **Install:** `asm add skill <source>` — install from the `source:` field shown by `asm search`.",
        "- **List installed:** `asm skill list`",
        "",
        "When the user asks to find, discover, or install a skill:",
        "",
        "1. Run `asm search <query>` to find candidates.",
        "2. Present results with the `source:` value from the output.",
        "3. Install with `asm add skill <source>` (use the `source:` value, NOT the raw identifier).",
        "4. Never suggest `npx skills add`, `npx playbooks add`, or manual GitHub cloning.",
        "",
    ]


# ── Per-agent strategies ────────────────────────────────────────────


def sync_cursor(root: Path, cfg: AsmConfig) -> Path:
    """Write .cursor/skills/asm/SKILL.md."""
    skill_dir = root / ".cursor" / "skills" / "asm"
    skill_dir.mkdir(parents=True, exist_ok=True)
    dest = skill_dir / "SKILL.md"

    lines = _skill_md_header()
    lines.extend(_skill_md_flow())
    lines.extend(_skill_md_discovery())
    lines.extend(_skill_md_expertises(cfg))
    lines.extend(_skill_md_installed(cfg))

    dest.write_text("\n".join(lines))
    return dest


def sync_claude(root: Path, cfg: AsmConfig) -> Path:
    """Update CLAUDE.md sentinel and write .claude/skills/asm/SKILL.md for Claude Code."""
    _sync_sentinel_file(root / "CLAUDE.md", cfg)
    return _write_claude_code_skill(root, cfg)


def _write_claude_code_skill(root: Path, cfg: AsmConfig) -> Path:
    """Write ASM router skill so Claude Code discovers it from .claude/skills/."""
    skill_dir = root / ".claude" / "skills" / "asm"
    skill_dir.mkdir(parents=True, exist_ok=True)
    dest = skill_dir / "SKILL.md"

    lines = _skill_md_header()
    lines.extend(_skill_md_flow())
    lines.extend(_skill_md_discovery())
    lines.extend(_skill_md_expertises(cfg))
    lines.extend(_skill_md_installed(cfg))

    dest.write_text("\n".join(lines))
    return dest


def sync_codex(root: Path, cfg: AsmConfig) -> Path:
    """Insert/update an ASM section in AGENTS.md."""
    return _sync_sentinel_file(root / "AGENTS.md", cfg)


def sync_copilot(root: Path, cfg: AsmConfig) -> Path:
    """Write .github/skills/asm/SKILL.md for GitHub Copilot (coding agent / VS Code)."""
    skill_dir = root / ".github" / "skills" / "asm"
    skill_dir.mkdir(parents=True, exist_ok=True)
    dest = skill_dir / "SKILL.md"

    lines = _skill_md_header()
    lines.extend(_skill_md_flow())
    lines.extend(_skill_md_discovery())
    lines.extend(_skill_md_expertises(cfg))
    lines.extend(_skill_md_installed(cfg))

    dest.write_text("\n".join(lines))
    return dest


def _skill_md_expertises(cfg: AsmConfig) -> list[str]:
    if not cfg.expertises:
        return []
    lines = ["## Expertise Groups", ""]
    for name, ref in cfg.expertises.items():
        purpose = ref.description or "No description provided."
        signals = ", ".join(ref.task_signals[:2]) if ref.task_signals else "n/a"
        lines.append(f"- **{name}** — {purpose}")
        lines.append(f"  - Signals: {signals}")
        lines.append(f"  - Router: `.asm/expertises/{name}/index.md`")
    lines.append("")
    return lines


def _skill_md_installed(cfg: AsmConfig) -> list[str]:
    if not cfg.skills:
        return []
    lines = [
        "## Installed Skills (Reference Only)",
        "",
        "Do not pick directly from this list before expertise routing.",
        "",
    ]
    for name in cfg.skills:
        lines.append(f"- **{name}**: `.asm/skills/{name}/SKILL.md`")
    lines.append("")
    return lines


# ── Shared helpers ──────────────────────────────────────────────────


_STRATEGY = {
    "cursor": sync_cursor,
    "claude": sync_claude,
    "codex": sync_codex,
    "copilot": sync_copilot,
}


def _build_sentinel_block(cfg: AsmConfig) -> str:
    lines = [
        SENTINEL_START,
        "Read `.asm/main_asm.md` before every task to identify active SOTA expertise.",
        "Follow the skill blueprints and relationship rules defined there.",
        "Use `asm search <query>` to find skills and `asm add skill <source>` to install them.",
        "Never use `npx skills`, `npx playbooks`, or other skill CLIs directly.",
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
    if (root / ".github" / "skills").is_dir():
        found.append("copilot")
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
