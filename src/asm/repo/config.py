"""Repository for asm.toml read/write."""

from __future__ import annotations

from pathlib import Path

import tomlkit

from asm.core.models import (
    AgentsConfig,
    AsmConfig,
    AsmMeta,
    ExpertiseRef,
    ProjectConfig,
    SkillEntry,
)


def create_default(name: str) -> AsmConfig:
    """Factory for a fresh workspace config."""
    return AsmConfig(project=ProjectConfig(name=name))


# ── Serialization ───────────────────────────────────────────────────


def dump(cfg: AsmConfig) -> str:
    """Serialize an AsmConfig to a TOML string."""
    doc = tomlkit.document()
    doc.add(tomlkit.comment("ASM — Agent Skill Manager configuration"))
    doc.add(tomlkit.nl())

    proj = tomlkit.table()
    proj.add("name", cfg.project.name)
    proj.add("version", cfg.project.version)
    if cfg.project.description:
        proj.add("description", cfg.project.description)
    doc.add("project", proj)

    asm = tomlkit.table()
    asm.add("version", cfg.asm.version)
    doc.add("asm", asm)

    skills = tomlkit.table()
    for name, entry in cfg.skills.items():
        row = tomlkit.inline_table()
        row.append("source", entry.source)
        skills.add(name, row)
    doc.add("skills", skills)

    expertises = tomlkit.table()
    for name, ref in cfg.expertises.items():
        row = tomlkit.inline_table()
        if ref.description:
            row.append("description", ref.description)
        if ref.skills:
            row.append("skills", ref.skills)
        expertises.add(name, row)
    doc.add("expertises", expertises)

    if cfg.agents.cursor or cfg.agents.claude or cfg.agents.codex:
        agents = tomlkit.table()
        agents.add("cursor", cfg.agents.cursor)
        agents.add("claude", cfg.agents.claude)
        agents.add("codex", cfg.agents.codex)
        doc.add("agents", agents)

    return tomlkit.dumps(doc)


def load(path: Path) -> AsmConfig:
    """Deserialize asm.toml into an AsmConfig."""
    raw = tomlkit.loads(path.read_text())
    proj_raw = raw.get("project", {})
    asm_raw = raw.get("asm", {})
    skills_raw = raw.get("skills", {})
    exp_raw = raw.get("expertises", {})
    agents_raw = raw.get("agents", {})

    skills: dict[str, SkillEntry] = {}
    for name, meta in skills_raw.items():
        skills[name] = SkillEntry(name=name, source=meta.get("source", ""))

    expertises: dict[str, ExpertiseRef] = {}
    for name, meta in exp_raw.items():
        expertises[name] = ExpertiseRef(
            name=name,
            description=meta.get("description", ""),
            skills=list(meta.get("skills", [])),
        )

    return AsmConfig(
        project=ProjectConfig(
            name=proj_raw.get("name", ""),
            version=proj_raw.get("version", "0.1.0"),
            description=proj_raw.get("description", ""),
        ),
        asm=AsmMeta(version=asm_raw.get("version", "0.1.0")),
        skills=skills,
        expertises=expertises,
        agents=AgentsConfig(
            cursor=agents_raw.get("cursor", False),
            claude=agents_raw.get("claude", False),
            codex=agents_raw.get("codex", False),
        ),
    )


def save(cfg: AsmConfig, path: Path) -> None:
    """Write config to disk."""
    path.write_text(dump(cfg))
