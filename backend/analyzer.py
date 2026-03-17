"""Heuristic analyzer for the ASM cloud MVP."""

from __future__ import annotations

import math
import os
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from asm.core.models import (
    SimilarSkillMatch,
    SkillAnalysisRequest,
    SkillAnalysisResponse,
    SkillManifest,
    SkillScorecard,
)
from asm.services import embeddings
from asm.services.analysis_feedback import build_skill_improvement_prompt

from backend import store


def analyze_request(request: SkillAnalysisRequest) -> SkillAnalysisResponse:
    """Analyze one submitted skill and return a structured scorecard."""
    embedding_profile = embeddings.current_profile(analysis_mode="cloud")
    similar_skills = _find_similar_skills(request.manifest)
    duplication_risk = similar_skills[0].similarity if similar_skills else 0.0
    trigger_specificity = _score_trigger_specificity(request.manifest)
    evidence_grounding = _score_evidence_grounding(request)
    novelty = _score_novelty(trigger_specificity, evidence_grounding, duplication_risk)
    analysis_id = str(uuid.uuid4())
    analysis_version = os.environ.get("ASM_CLOUD_ANALYZER_VERSION", "asm-cloud-mvp-v1").strip()
    recommended_actions = _build_recommendations(
        request,
        similar_skills,
        trigger_specificity,
        evidence_grounding,
        duplication_risk,
    )

    scorecard = SkillScorecard(
        skill_name=request.manifest.name,
        analysis_id=analysis_id,
        analysis_version=analysis_version,
        trigger_specificity=trigger_specificity,
        novelty=novelty,
        evidence_grounding=evidence_grounding,
        duplication_risk=duplication_risk,
        status=_derive_status(trigger_specificity, evidence_grounding, duplication_risk),
        findings=_build_findings(request, similar_skills, trigger_specificity, evidence_grounding, duplication_risk),
        recommended_actions=recommended_actions,
        improvement_prompt=build_skill_improvement_prompt(
            request.manifest,
            recommended_actions,
            similar_skills,
        ),
        similar_skills=similar_skills,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    response = SkillAnalysisResponse(
        analysis_id=analysis_id,
        analysis_version=analysis_version,
        scorecard=scorecard,
        embedding_profile=embedding_profile,
    )
    store.save_analysis(request, response)
    return response


def _find_similar_skills(manifest: SkillManifest) -> list[SimilarSkillMatch]:
    corpus = store.load_manifest_corpus()
    current_text = _manifest_similarity_text(manifest)
    current_vector = embeddings.embed(current_text)
    matches: list[SimilarSkillMatch] = []
    for item in corpus:
        raw_manifest = item.get("manifest", {})
        other_name = str(raw_manifest.get("name", "")).strip()
        if not other_name or other_name == manifest.name:
            continue
        other_text = _manifest_similarity_text_from_dict(raw_manifest)
        similarity = embeddings.cosine_similarity(current_vector, embeddings.embed(other_text))
        matches.append(SimilarSkillMatch(name=other_name, similarity=round(similarity, 4)))
    matches.sort(key=lambda item: item.similarity, reverse=True)
    return matches[:3]


def _manifest_similarity_text(manifest: SkillManifest) -> str:
    inventory = manifest.resource_inventory
    return " ".join(
        [
            manifest.name,
            manifest.description,
            " ".join(manifest.trigger_phrases),
            " ".join(inventory.references.files),
            " ".join(inventory.scripts.files),
            " ".join(inventory.examples.files),
            " ".join(inventory.assets.files),
        ]
    )


def _manifest_similarity_text_from_dict(raw: dict) -> str:
    inventory = raw.get("resource_inventory", {})
    return " ".join(
        [
            str(raw.get("name", "")),
            str(raw.get("description", "")),
            " ".join(raw.get("trigger_phrases", [])),
            " ".join(inventory.get("references", {}).get("files", [])),
            " ".join(inventory.get("scripts", {}).get("files", [])),
            " ".join(inventory.get("examples", {}).get("files", [])),
            " ".join(inventory.get("assets", {}).get("files", [])),
        ]
    )


def _score_trigger_specificity(manifest: SkillManifest) -> float:
    triggers = [phrase for phrase in manifest.trigger_phrases if phrase.strip()]
    if not triggers:
        return 0.15
    avg_words = sum(len(phrase.split()) for phrase in triggers) / len(triggers)
    count_score = min(len(triggers) / 4.0, 1.0)
    phrase_score = min(avg_words / 6.0, 1.0)
    desc_bonus = 0.15 if "This skill should be used when" in manifest.description else 0.0
    return round(min((0.45 * count_score) + (0.4 * phrase_score) + desc_bonus, 1.0), 4)


def _score_evidence_grounding(request: SkillAnalysisRequest) -> float:
    manifest = request.manifest
    inventory = manifest.resource_inventory
    evidence = request.evidence
    file_count = len(request.files)
    reference_signal = min(inventory.references.count / 3.0, 1.0)
    script_signal = min(inventory.scripts.count / 2.0, 1.0)
    evidence_signal = min((len(evidence.source_urls) + len(evidence.source_files)) / 8.0, 1.0)
    coverage_signal = min(file_count / 6.0, 1.0)
    return round(min((0.35 * reference_signal) + (0.2 * script_signal) + (0.25 * evidence_signal) + (0.2 * coverage_signal), 1.0), 4)


def _score_novelty(trigger_specificity: float, evidence_grounding: float, duplication_risk: float) -> float:
    raw = (0.35 * trigger_specificity) + (0.25 * evidence_grounding) + (0.4 * (1.0 - duplication_risk))
    return round(max(0.0, min(raw, 1.0)), 4)


def _derive_status(trigger_specificity: float, evidence_grounding: float, duplication_risk: float) -> str:
    if trigger_specificity < 0.3 or evidence_grounding < 0.3:
        return "insufficient_evidence"
    if duplication_risk > 0.75 or trigger_specificity < 0.65 or evidence_grounding < 0.55:
        return "needs_work"
    return "approved"


def _build_findings(
    request: SkillAnalysisRequest,
    similar_skills: list[SimilarSkillMatch],
    trigger_specificity: float,
    evidence_grounding: float,
    duplication_risk: float,
) -> list[str]:
    findings: list[str] = []
    if request.manifest.trigger_phrases:
        findings.append(f"Detected {len(request.manifest.trigger_phrases)} explicit trigger phrase(s).")
    else:
        findings.append("No explicit quoted trigger phrases detected in the skill description.")
    findings.append(f"Evidence inventory covers {len(request.evidence.source_files)} file(s).")
    if similar_skills:
        findings.append(
            f"Nearest overlap is `{similar_skills[0].name}` with similarity {similar_skills[0].similarity:.2f}."
        )
    if trigger_specificity >= 0.7:
        findings.append("Trigger wording is specific enough to route with high confidence.")
    if evidence_grounding >= 0.6:
        findings.append("Supporting references/scripts provide good grounding coverage for MVP analysis.")
    if duplication_risk >= 0.7:
        findings.append("Skill meaning overlaps strongly with an already analyzed skill.")
    return findings


def _build_recommendations(
    request: SkillAnalysisRequest,
    similar_skills: list[SimilarSkillMatch],
    trigger_specificity: float,
    evidence_grounding: float,
    duplication_risk: float,
) -> list[str]:
    actions: list[str] = []
    if trigger_specificity < 0.65:
        actions.append("Add more explicit quoted trigger phrases to the SKILL.md description.")
    if evidence_grounding < 0.55:
        actions.append("Add more references, scripts, or examples that ground the skill's strongest claims.")
    if duplication_risk > 0.75 and similar_skills:
        actions.append(f"Sharpen the boundary from `{similar_skills[0].name}` or merge overlapping guidance.")
    if not request.manifest.resource_inventory.references.count:
        actions.append("Move detailed non-obvious guidance into `references/` to improve grounding and reuse.")
    return actions or ["Maintain this skill boundary and keep future evidence tied to concrete references."]
