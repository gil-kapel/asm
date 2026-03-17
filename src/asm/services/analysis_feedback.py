"""Helpers for turning analysis output into actionable improvement guidance."""

from __future__ import annotations

from asm.core.models import SimilarSkillMatch, SkillManifest


def build_skill_improvement_prompt(
    manifest: SkillManifest,
    recommended_actions: list[str],
    similar_skills: list[SimilarSkillMatch],
) -> str:
    """Build a reusable prompt for improving one analyzed skill."""
    priorities = _format_priorities(recommended_actions)
    overlap = _format_overlap(similar_skills)
    triggers = ", ".join(f'"{phrase}"' for phrase in manifest.trigger_phrases) or "none yet"
    return (
        f'Improve the ASM skill "{manifest.name}".\n\n'
        "Rewrite the skill so it routes more precisely, stays distinct from nearby skills, and is better grounded in concrete evidence.\n\n"
        f"Current description:\n{manifest.description}\n\n"
        f"Current trigger phrases: {triggers}\n"
        f"Nearby skills to stay distinct from: {overlap}\n\n"
        "Priority fixes:\n"
        f"{priorities}\n\n"
        "Return:\n"
        "1. A rewritten SKILL.md description paragraph.\n"
        "2. Three to five explicit quoted trigger phrases.\n"
        "3. A short list of references, scripts, or examples to add or update.\n"
        "4. A boundary note that explains when this skill should not be selected."
    )


def _format_priorities(recommended_actions: list[str]) -> str:
    if not recommended_actions:
        return "- Preserve the current boundary and strengthen supporting references only where needed."
    return "\n".join(f"- {action}" for action in recommended_actions)


def _format_overlap(similar_skills: list[SimilarSkillMatch]) -> str:
    if not similar_skills:
        return "none"
    return ", ".join(f"{item.name} ({item.similarity:.2f})" for item in similar_skills)
