"""Helpers for analysis feedback prompts and structured OpenAI analysis."""

from __future__ import annotations

import asyncio
import os
from dataclasses import asdict
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from asm.core.models import SimilarSkillMatch, SkillAnalysisRequest, SkillManifest

DEFAULT_OPENAI_ANALYSIS_MODEL = "gpt-5-mini"


class AnalysisFeedbackError(RuntimeError):
    """Raised when the OpenAI feedback service cannot complete."""


class LocalAnalysisFeedbackPayload(BaseModel):
    """Strict structured output shape for local OpenAI skill analysis."""

    model_config = ConfigDict(extra="forbid")

    trigger_specificity: float = Field(ge=0.0, le=1.0)
    novelty: float = Field(ge=0.0, le=1.0)
    evidence_grounding: float = Field(ge=0.0, le=1.0)
    duplication_risk: float = Field(ge=0.0, le=1.0)
    status: Literal["approved", "needs_work", "insufficient_evidence"]
    findings: list[str]
    recommended_actions: list[str]


class OpenAIAnalysisFeedbackService:
    """Facade for AsyncOpenAI structured analysis feedback."""

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.model = _normalize_openai_model(model)
        self._client = AsyncOpenAI(
            api_key=api_key or os.environ.get("OPENAI_API_KEY"),
            base_url=base_url or os.environ.get("OPENAI_BASE_URL") or None,
        )

    async def analyze_skill(
        self,
        request: SkillAnalysisRequest,
        similar_skills: list[SimilarSkillMatch],
        *,
        analysis_id: str,
        analysis_version: str,
    ) -> LocalAnalysisFeedbackPayload:
        """Run one structured OpenAI analysis pass."""
        response = await self._client.responses.parse(
            model=self.model,
            input=[
                {"role": "system", "content": _build_local_analysis_system_prompt()},
                {
                    "role": "user",
                    "content": build_local_analysis_prompt(
                        request,
                        similar_skills,
                        analysis_id,
                        analysis_version,
                        self.model,
                    ),
                },
            ],
            text_format=LocalAnalysisFeedbackPayload,
        )
        refusal = getattr(response, "refusal", None)
        if refusal:
            raise AnalysisFeedbackError(f"OpenAI refused local analysis: {refusal}")
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise AnalysisFeedbackError("OpenAI returned no parsed structured analysis payload.")
        return parsed


def analyze_local_analysis_feedback_sync(
    request: SkillAnalysisRequest,
    similar_skills: list[SimilarSkillMatch],
    *,
    analysis_id: str,
    analysis_version: str,
    model: str | None = None,
) -> LocalAnalysisFeedbackPayload:
    """Sync wrapper around the async OpenAI structured analysis client."""
    service = OpenAIAnalysisFeedbackService(model=model)
    return asyncio.run(
        service.analyze_skill(
            request,
            similar_skills,
            analysis_id=analysis_id,
            analysis_version=analysis_version,
        )
    )


def build_local_analysis_prompt(
    request: SkillAnalysisRequest,
    similar_skills: list[SimilarSkillMatch],
    analysis_id: str,
    analysis_version: str,
    model_name: str,
) -> str:
    """Build the structured local analysis prompt payload."""
    payload = {
        "analysis_id": analysis_id,
        "analysis_version": analysis_version,
        "model": model_name,
        "manifest": asdict(request.manifest),
        "evidence": asdict(request.evidence),
        "files": [asdict(item) for item in request.files[:12]],
        "similar_skills": [asdict(item) for item in similar_skills],
    }
    return (
        "Analyze this ASM skill package and return the structured scorecard.\n"
        "Use only the supplied evidence.\n\n"
        f"{payload}"
    )


def _build_local_analysis_system_prompt() -> str:
    return (
        "You are evaluating an ASM skill package.\n"
        "Score each numeric field from 0.0 to 1.0.\n"
        "Use status one of: approved, needs_work, insufficient_evidence.\n"
        "Be strict about trigger specificity, novelty, and evidence grounding.\n"
        "\n"
        "Scoring rubric:\n"
        "- trigger_specificity: High only if manifest.trigger_phrases has 3-5 meaningful, routing-ready phrases (not generic).\n"
        "  If manifest.trigger_phrases is empty or extracted from vague or unspecific text, score low.\n"
        "- evidence_grounding: High only if evidence includes concrete, actionable sources (URLs, specific file content) that support the workflow or rules.\n"
        "  If references or research evidence is missing, generic, or not present in evidence.source_files, score low.\n"
        "  Also score low if evidence.source_files appear to contain placeholder material such as 'Materialized by ASM', 'TODO: implement', or similar stub text.\n"
        "- novelty: Reward distinctness in purpose and boundaries compared to similar skills.\n"
        '- duplication_risk: High only if the skill\'s "Select This Skill" / "Do Not Select" boundaries do not clearly exclude the nearby similar skills by name.\n'
        "  If boundaries explicitly name and exclude those similar skills, score duplication_risk lower.\n"
        "Keep findings and recommended_actions concise."
    )


def build_skill_improvement_prompt(
    manifest: SkillManifest,
    recommended_actions: list[str],
    similar_skills: list[SimilarSkillMatch],
) -> str:
    """Build a reusable prompt for improving one analyzed skill."""
    from asm.services import llm

    priorities = _format_priorities(recommended_actions)
    overlap = _format_overlap(similar_skills)
    nearby_names = ", ".join(item.name for item in similar_skills[:5]) if similar_skills else "none"
    triggers = ", ".join(f'"{phrase}"' for phrase in manifest.trigger_phrases) or "none yet"
    supporting_files = (
        manifest.resource_inventory.references.files
        + manifest.resource_inventory.scripts.files
        + manifest.resource_inventory.examples.files
        + manifest.resource_inventory.assets.files
    )
    runtime_guidance = llm.render_runtime_guidance(
        llm.infer_runtime_preference(
            text_blobs=[manifest.description],
            supporting_files=supporting_files,
        )
    ).strip()
    runtime_block = f"Implementation/runtime constraint:\n{runtime_guidance}\n\n" if runtime_guidance else ""
    return (
        f'Improve the ASM skill "{manifest.name}".\n\n'
        "Rewrite the skill so it routes more precisely, stays distinct from nearby skills, and is better grounded in concrete evidence.\n"
        "Keep SKILL.md compact. Put detailed contracts, examples, and research notes in files under references/, examples/, or scripts/, then point to those files from SKILL.md.\n\n"
        f"{runtime_block}"
        f"Current description:\n{manifest.description}\n\n"
        f"Current trigger phrases: {triggers}\n"
        f"Nearby skills to stay distinct from: {overlap}\n\n"
        "Priority fixes:\n"
        f"{priorities}\n\n"
        "Return:\n"
        "1. A concise SKILL.md structure with short routing guidance.\n"
        "2. Three to five explicit quoted trigger phrases (double-quoted) that must appear in the one-line frontmatter `description:` output (NOT only in the markdown body), so ASM can extract `trigger_phrases` for routing.\n"
        "3. A `## Niche Examples` section with 2-3 short, concrete mini-examples (each 3-6 lines) that demonstrate how to use the skill correctly.\n"
        "4. A short list of concrete file paths under `references/`, `examples/`, `scripts/`, or `assets/` to add or update (use explicit paths like `references/foo.md` so ASM can materialize missing files).\n"
        f"5. Update the `## Do Not Select This Skill When` / boundary section so it explicitly mentions the nearby skills by name ({nearby_names}) and states a one-sentence distinction for each."
    )


def _normalize_openai_model(model: str | None) -> str:
    raw = (model or os.environ.get("ASM_LLM_MODEL") or DEFAULT_OPENAI_ANALYSIS_MODEL).strip()
    if not raw:
        return DEFAULT_OPENAI_ANALYSIS_MODEL
    if "/" in raw:
        provider, _, candidate = raw.partition("/")
        if provider != "openai":
            raise AnalysisFeedbackError(
                f"Local analysis only supports OpenAI models via AsyncOpenAI. Got: {raw}"
            )
        return candidate.strip() or DEFAULT_OPENAI_ANALYSIS_MODEL
    return raw


def _format_priorities(recommended_actions: list[str]) -> str:
    if not recommended_actions:
        return "- Preserve the current boundary and strengthen supporting references only where needed."
    return "\n".join(f"- {action}" for action in recommended_actions)


def _format_overlap(similar_skills: list[SimilarSkillMatch]) -> str:
    if not similar_skills:
        return "none"
    return ", ".join(f"{item.name} ({item.similarity:.2f})" for item in similar_skills)
