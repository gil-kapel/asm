"""SKILL.md frontmatter extraction and validation."""

from __future__ import annotations

import re
from pathlib import Path

from asm.core.models import SkillMeta


def extract_meta(skill_dir: Path) -> SkillMeta:
    """Read name + description from SKILL.md YAML frontmatter.

    Returns empty ``name`` when the frontmatter omits it — callers are
    responsible for deriving a name (e.g. from the source path).
    """
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(f"SKILL.md not found in {skill_dir}")

    content = skill_md.read_text()
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        raise ValueError(f"No YAML frontmatter in {skill_md}")

    fm = match.group(1)
    name_m = re.search(r"^name:\s*(.+)$", fm, re.MULTILINE)
    desc_m = re.search(r"^description:\s*(.+)$", fm, re.MULTILINE)

    name = name_m.group(1).strip() if name_m else ""
    description = desc_m.group(1).strip() if desc_m else ""

    if not description:
        block = re.search(
            r"^description:\s*[|>]?-?\s*\n((?:[ \t]+.+\n?)+)", fm, re.MULTILINE
        )
        if block:
            description = " ".join(
                line.strip() for line in block.group(1).splitlines() if line.strip()
            )

    return SkillMeta(name=name, description=description)


def validate(skill_dir: Path) -> tuple[bool, str]:
    """Validate a skill directory meets the canonical SKILL.md format."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return False, "SKILL.md not found"

    try:
        meta = extract_meta(skill_dir)
    except ValueError as exc:
        return False, str(exc)

    if not meta.description:
        return False, "Missing 'description' in frontmatter"
    if meta.name and not re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$", meta.name):
        return False, f"Name '{meta.name}' must be kebab-case"

    return True, "valid"
