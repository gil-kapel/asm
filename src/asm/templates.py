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
        "## Routing Protocol (Mandatory)",
        "",
        "1. Start from `.cursor/skills/asm/SKILL.md`, then read this file.",
        "2. Select one expertise group using the routing rubric below.",
        "3. Open the group index and relationships docs before loading any skill.",
        "4. Prefer advanced, non-trivial skills when available.",
        "5. Load only the selected skills with the right dependency order.",
        "",
    ]

    if cfg.expertises:
        lines.append("## Expertise Group Router")
        lines.append("")
        lines.append("| Group | Purpose | Task signals | Advanced-first | Navigation |")
        lines.append("| --- | --- | --- | --- | --- |")
        for name, ref in cfg.expertises.items():
            signals = ", ".join(ref.task_signals[:3]) if ref.task_signals else "n/a"
            advanced = "yes" if ref.prefer_advanced else "no"
            nav = f"`.asm/expertises/{name}/index.md`"
            lines.append(
                f"| `{name}` | {ref.description or 'n/a'} | {signals} | {advanced} | {nav} |"
            )
        lines.append("")

        lines.append("## Selection Rubric")
        lines.append("")
        lines.append("1. Match task intent to expertise intent tags and task signals.")
        lines.append("2. If multiple groups match, choose the one with stronger advanced skill coverage.")
        lines.append("3. Respect each group's `relationships.md` before skill loading.")
        lines.append("4. Do not route directly to a skill before selecting a group.")
        lines.append("")

        lines.append("## Active Expertises")
        lines.append("")
        for name, ref in cfg.expertises.items():
            lines.append(f"### {name}")
            lines.append("")
            if ref.description:
                lines.append(ref.description)
                lines.append("")
            if ref.intent_tags:
                lines.append(f"- Intent tags: {', '.join(ref.intent_tags)}")
            if ref.task_signals:
                lines.append(f"- Task signals: {', '.join(ref.task_signals)}")
            if ref.confidence_hint:
                lines.append(f"- Confidence hint: {ref.confidence_hint}")
            lines.append(f"- Navigation: `.asm/expertises/{name}/index.md`")
            lines.append(f"- Relationships: `.asm/expertises/{name}/relationships.md`")
            policies = ref.resolved_skill_policies()
            if policies:
                advanced = [p.name for p in policies if p.is_advanced]
                required = [p.name for p in policies if p.role == "required"]
                optional = [p.name for p in policies if p.role == "optional"]
                fallback = [p.name for p in policies if p.role == "fallback"]
                if required:
                    lines.append(f"- Required skills: {', '.join(required)}")
                if optional:
                    lines.append(f"- Optional skills: {', '.join(optional)}")
                if fallback:
                    lines.append(f"- Fallback skills: {', '.join(fallback)}")
                if advanced:
                    lines.append(f"- Advanced skills: {', '.join(advanced)}")
            lines.append("")

    if cfg.skills:
        lines.append("## Installed Skills")
        lines.append("")
        for name, entry in cfg.skills.items():
            lines.append(f"- **{name}**: `.asm/skills/{name}/SKILL.md`")
            lines.append(f"  Source: `{entry.source}`")
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
