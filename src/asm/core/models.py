"""Data shapes for ASM configuration and skill metadata.

Skill structure follows the canonical SKILL.md format:
    skill-name/
    ├── SKILL.md          (required — YAML frontmatter + markdown body)
    ├── scripts/          (optional — executable code)
    ├── references/       (optional — docs loaded into context)
    └── assets/           (optional — files used in output)
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ── Skill layer ─────────────────────────────────────────────────────


@dataclass
class SkillMeta:
    """Metadata extracted from SKILL.md YAML frontmatter."""
    name: str
    description: str


@dataclass
class SkillEntry:
    """A skill registered in asm.toml [skills.<name>]."""
    name: str
    source: str  # "github:user/repo/path" | "local:./path" | "smithery:ns/skill"


@dataclass
class LockEntry:
    """A pinned skill in asm.lock."""
    name: str
    source: str
    integrity: str
    resolved: str = ""
    commit: str = ""


# ── Project layer ───────────────────────────────────────────────────


@dataclass
class ProjectConfig:
    """Mirrors the [project] table in asm.toml."""
    name: str
    version: str = "0.1.0"
    description: str = ""


@dataclass
class AsmMeta:
    """Mirrors the [asm] table — tool-level metadata."""
    version: str = "0.1.0"


@dataclass
class ExpertiseRef:
    """A reference to an active expertise namespace."""

    name: str
    description: str = ""
    skills: list[str] = field(default_factory=list)


@dataclass
class AgentsConfig:
    """Mirrors the [agents] table — which IDE integrations to sync."""

    cursor: bool = False
    claude: bool = False
    codex: bool = False


@dataclass
class AsmConfig:
    """Root configuration object for asm.toml."""

    project: ProjectConfig
    asm: AsmMeta = field(default_factory=AsmMeta)
    skills: dict[str, SkillEntry] = field(default_factory=dict)
    expertises: dict[str, ExpertiseRef] = field(default_factory=dict)
    agents: AgentsConfig = field(default_factory=AgentsConfig)
