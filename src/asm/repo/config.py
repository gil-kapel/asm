"""Repository for asm.toml read/write."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import tomlkit

from asm.core.models import (
    AgentsConfig,
    AsmConfig,
    AsmMeta,
    ExpertiseRef,
    ProjectConfig,
    SkillPolicy,
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
        if ref.intent_tags:
            row.append("intent_tags", ref.intent_tags)
        if ref.task_signals:
            row.append("task_signals", ref.task_signals)
        if ref.confidence_hint:
            row.append("confidence_hint", ref.confidence_hint)
        if ref.selection_rubric:
            row.append("selection_rubric", ref.selection_rubric)
        row.append("prefer_advanced", ref.prefer_advanced)
        policies = ref.resolved_skill_policies()
        if policies:
            row.append("skill_policies", [_policy_to_dict(p) for p in policies])
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
        skill_policies = _parse_skill_policies(meta.get("skill_policies", []))
        raw_skills = list(meta.get("skills", []))
        if raw_skills:
            policy_names = {policy.name for policy in skill_policies}
            for skill_name in raw_skills:
                if skill_name not in policy_names:
                    skill_policies.append(SkillPolicy(name=skill_name))
        elif skill_policies:
            raw_skills = [policy.name for policy in skill_policies]

        expertises[name] = ExpertiseRef(
            name=name,
            description=meta.get("description", ""),
            skills=raw_skills,
            intent_tags=list(meta.get("intent_tags", [])),
            task_signals=list(meta.get("task_signals", [])),
            confidence_hint=meta.get("confidence_hint", ""),
            selection_rubric=list(meta.get("selection_rubric", [])),
            prefer_advanced=meta.get("prefer_advanced", True),
            skill_policies=skill_policies,
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


def _policy_to_dict(policy: SkillPolicy) -> dict:
    payload: dict = {"name": policy.name, "role": policy.role}
    if policy.depends_on:
        payload["depends_on"] = policy.depends_on
    if policy.conflicts_with:
        payload["conflicts_with"] = policy.conflicts_with
    if policy.execution_order is not None:
        payload["execution_order"] = policy.execution_order
    payload["is_advanced"] = policy.is_advanced
    if policy.novelty_reason:
        payload["novelty_reason"] = policy.novelty_reason
    return payload


def _parse_skill_policies(raw_policies: list[dict]) -> list[SkillPolicy]:
    parsed: list[SkillPolicy] = []
    for raw in raw_policies or []:
        name = str(raw.get("name", "")).strip()
        if not name:
            continue
        role_value = str(raw.get("role", "required")).strip() or "required"
        role: Literal["required", "optional", "fallback"] = "required"
        if role_value in {"required", "optional", "fallback"}:
            role = role_value
        execution_order_raw = raw.get("execution_order")
        execution_order = (
            int(execution_order_raw)
            if isinstance(execution_order_raw, int)
            else None
        )
        parsed.append(
            SkillPolicy(
                name=name,
                role=role,
                depends_on=list(raw.get("depends_on", [])),
                conflicts_with=list(raw.get("conflicts_with", [])),
                execution_order=execution_order,
                is_advanced=bool(raw.get("is_advanced", False)),
                novelty_reason=str(raw.get("novelty_reason", "")),
            )
        )
    return parsed
