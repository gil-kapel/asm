"""Markdown template generators for .asm/ artefacts."""

from __future__ import annotations

from pathlib import Path

from asm.core.models import AsmConfig


def render_main_asm(cfg: AsmConfig) -> str:
    """Generate the root main_asm.md that agents read first."""
    lines = [
        "# ASM — Agent Skill Manager",
        "",
        f"> Project: **{cfg.project.name}** v{cfg.project.version}",
        "",
        "## Instructions for Agent",
        "",
        "Before every task, consult this document to identify active SOTA expertise.",
        "Strictly comply with the blueprints and relationship rules defined in each",
        "expertise namespace. Each skill follows the canonical SKILL.md format with",
        "scripts/, references/, and assets/ subdirectories.",
        "",
    ]

    if cfg.skills:
        lines.append("## Installed Skills")
        lines.append("")
        for name, entry in cfg.skills.items():
            lines.append(f"- **{name}**: `.asm/skills/{name}/SKILL.md`")
            lines.append(f"  Source: `{entry.source}`")
        lines.append("")

    if cfg.expertises:
        lines.append("## Active Expertises")
        lines.append("")
        for name, ref in cfg.expertises.items():
            lines.append(f"### {name}")
            lines.append("")
            if ref.description:
                lines.append(ref.description)
                lines.append("")
            lines.append(f"- Navigation: `.asm/expertises/{name}/index.md`")
            lines.append(f"- Relationships: `.asm/expertises/{name}/relationships.md`")
            if ref.skills:
                lines.append(f"- Skills: {', '.join(ref.skills)}")
            lines.append("")

    if not cfg.skills and not cfg.expertises:
        lines.append(
            "_No skills installed yet. Use `asm add skill` or `asm create skill` to get started._"
        )
        lines.append("")

    return "\n".join(lines)


def build_skill_md(
    name: str, title: str, description: str, source_path: str | None = None,
) -> str:
    """Generate a SKILL.md template for a newly created skill."""
    lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
        "---",
        "",
        f"# {title}",
        "",
    ]

    if source_path:
        src = Path(source_path)
        lines.append("## Source Analysis")
        lines.append("")
        if src.is_file():
            lines.append(f"Distilled from `{src.name}`.")
        else:
            files = sorted(p.name for p in src.rglob("*") if p.is_file())[:20]
            lines.append(f"Distilled from `{src.name}/` ({len(files)} files).")
            if files:
                lines.append("")
                lines.append("Key files:")
                for f in files:
                    lines.append(f"- `{f}`")
        lines.append("")

    lines.extend([
        "## Usage",
        "",
        f"[TODO: Describe how agents should use the {title} skill.]",
        "",
        "## Resources",
        "",
        "- `scripts/` — Executable code for deterministic tasks",
        "- `references/` — Documentation loaded into context as needed",
        "",
    ])
    return "\n".join(lines)
