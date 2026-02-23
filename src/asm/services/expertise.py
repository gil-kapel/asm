"""Expertise service — bundle skills into task-oriented domains.

Phase A: create expertise from explicit skill list or LLM-suggested selection.
Phase B: suggest/auto commands for autonomous agent matching.
"""

from __future__ import annotations

import os
from pathlib import Path

from asm.core import paths
from asm.core.models import AsmConfig, ExpertiseRef
from asm.repo import config
from asm.services import embeddings


def create_expertise(
    name: str,
    description: str,
    skill_names: list[str],
    root: Path,
) -> Path:
    """Create an expertise bundle from an explicit list of skills.

    Writes .asm/expertises/<name>/index.md and updates asm.toml.
    Returns the path to the created index.md.
    """
    cfg_path = root / paths.ASM_TOML
    cfg = config.load(cfg_path)

    missing = [s for s in skill_names if s not in cfg.skills]
    if missing:
        raise ValueError(f"Skills not installed: {', '.join(missing)}")

    expertise_dir = paths.asm_dir(root) / "expertises" / name
    expertise_dir.mkdir(parents=True, exist_ok=True)

    index_md = _render_index(name, description, skill_names, cfg)
    index_path = expertise_dir / "index.md"
    index_path.write_text(index_md, encoding="utf-8")

    relationships_md = _render_relationships(name, skill_names)
    (expertise_dir / "relationships.md").write_text(relationships_md, encoding="utf-8")

    cfg.expertises[name] = ExpertiseRef(
        name=name, description=description, skills=list(skill_names),
    )
    config.save(cfg, cfg_path)

    return index_path


def create_expertise_auto(
    name: str,
    task_description: str,
    root: Path,
    *,
    model: str | None = None,
) -> tuple[Path, list[str]]:
    """LLM-assisted expertise creation: describe a task, get a skill bundle.

    Returns (index_path, selected_skill_names).
    """
    cfg_path = root / paths.ASM_TOML
    cfg = config.load(cfg_path)

    if not cfg.skills:
        raise ValueError("No skills installed. Add skills first with `asm add skill`.")

    selected = _llm_select_skills(task_description, cfg, model=model)
    if not selected:
        raise ValueError("LLM could not identify relevant skills for this task.")

    index_path = create_expertise(name, task_description, selected, root)
    return index_path, selected


def suggest(
    task_description: str,
    root: Path,
) -> list[tuple[str, float]]:
    """Match a task description against existing expertises using embeddings.

    Returns list of (expertise_name, similarity_score) sorted by relevance.
    """
    cfg_path = root / paths.ASM_TOML
    cfg = config.load(cfg_path)

    if not cfg.expertises:
        return []

    task_vec = embeddings.embed(task_description)

    results: list[tuple[str, float]] = []
    for name, ref in cfg.expertises.items():
        trigger_text = f"{name} {ref.description} {' '.join(ref.skills)}"
        trigger_vec = embeddings.embed(trigger_text)
        sim = embeddings.cosine_similarity(task_vec, trigger_vec)
        results.append((name, sim))

    results.sort(key=lambda t: t[1], reverse=True)
    return results


def auto(
    task_description: str,
    root: Path,
    *,
    model: str | None = None,
) -> tuple[str, list[str]]:
    """Full autonomous flow: suggest or create expertise, install if needed, return best match.

    Returns (expertise_name, skill_names).
    """
    existing = suggest(task_description, root)
    if existing and existing[0][1] > 0.5:
        best_name = existing[0][0]
        cfg = config.load(root / paths.ASM_TOML)
        return best_name, cfg.expertises[best_name].skills

    name = _slugify(task_description)
    _, selected = create_expertise_auto(name, task_description, root, model=model)
    return name, selected


def _llm_select_skills(
    task_description: str,
    cfg: AsmConfig,
    *,
    model: str | None = None,
) -> list[str]:
    """Use LLM to pick the most relevant installed skills for a task."""
    try:
        from asm.services.llm import _ensure_litellm
        _ensure_litellm()
        import litellm
    except RuntimeError:
        return _embedding_select_skills(task_description, cfg)

    model = (model or os.environ.get("ASM_LLM_MODEL") or "openai/gpt-4o-mini").strip()

    skill_list = "\n".join(
        f"- {name}: {entry.source}" for name, entry in cfg.skills.items()
    )

    system = (
        "You select the most relevant skills for a given task. "
        "Reply with ONLY a comma-separated list of skill names. No explanation."
    )
    user = (
        f"Task: {task_description}\n\n"
        f"Available skills:\n{skill_list}\n\n"
        "Which skills are relevant for this task? List only their names, comma-separated."
    )

    try:
        response = litellm.completion(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=256,
        )
        raw = (response.choices[0].message.content or "").strip()
        candidates = [s.strip().strip("`\"'") for s in raw.split(",")]
        installed = set(cfg.skills.keys())
        return [c for c in candidates if c in installed]
    except Exception:
        return _embedding_select_skills(task_description, cfg)


def _embedding_select_skills(
    task_description: str,
    cfg: AsmConfig,
    top_k: int = 5,
) -> list[str]:
    """Fallback: select skills using embedding similarity when LLM is unavailable."""
    task_vec = embeddings.embed(task_description)
    scored: list[tuple[str, float]] = []

    for name in cfg.skills:
        skill_vec = embeddings.embed(f"{name} {cfg.skills[name].source}")
        sim = embeddings.cosine_similarity(task_vec, skill_vec)
        scored.append((name, sim))

    scored.sort(key=lambda t: t[1], reverse=True)
    return [name for name, _ in scored[:top_k]]


def _slugify(text: str) -> str:
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower().strip())
    return slug.strip("-")[:50]


def _render_index(
    name: str, description: str, skill_names: list[str], cfg: AsmConfig,
) -> str:
    title = name.replace("-", " ").title()
    lines = [
        f"# Expertise: {title}",
        "",
        description,
        "",
        "## Skills",
        "",
    ]
    for sname in skill_names:
        entry = cfg.skills.get(sname)
        source = entry.source if entry else "unknown"
        lines.append(f"- **{sname}**: `.asm/skills/{sname}/SKILL.md` (source: `{source}`)")
    lines.append("")
    lines.append("## Usage")
    lines.append("")
    lines.append(
        "When working on a task matching this expertise, load all listed skills "
        "and follow their instructions together."
    )
    lines.append("")
    return "\n".join(lines)


def _render_relationships(name: str, skill_names: list[str]) -> str:
    title = name.replace("-", " ").title()
    lines = [
        f"# Relationships: {title}",
        "",
        "## Skill Dependencies",
        "",
    ]
    for sname in skill_names:
        lines.append(f"- `{sname}` — required")
    lines.append("")
    lines.append("## Execution Order")
    lines.append("")
    lines.append("Load all skills before starting. No strict ordering required.")
    lines.append("")
    return "\n".join(lines)
