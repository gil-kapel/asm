"""Unified skill analysis service for cloud and local LLM flows."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from asm.core.models import (
    SimilarSkillMatch,
    SkillAnalysisArtifact,
    SkillAnalysisRequest,
    SkillAnalysisResponse,
    SkillManifest,
    SkillScorecard,
)
from asm.repo import analysis, config
from asm.services.analysis_feedback import build_skill_improvement_prompt
from asm.services import cloud_analysis, embeddings, llm

CloudAnalysisError = cloud_analysis.CloudAnalysisError


class LocalAnalysisError(RuntimeError):
    """Raised when local LLM-backed analysis cannot complete."""


def scorecard_overall_score(scorecard: SkillScorecard) -> float:
    """Collapse the scorecard into one 0-1 score for local improvement loops."""
    weighted_total = (
        scorecard.trigger_specificity
        + scorecard.novelty
        + scorecard.evidence_grounding
        + (1.0 - scorecard.duplication_risk)
    )
    return round(weighted_total / 4.0, 4)


def analyze_skill_cloud(
    root: Path,
    name: str,
    *,
    api_url: str | None = None,
    api_key: str | None = None,
) -> tuple[SkillAnalysisResponse, Path]:
    """Delegate to the managed cloud analyzer and persist the artifact."""
    return cloud_analysis.analyze_skill_cloud(root, name, api_url=api_url, api_key=api_key)


def analyze_skill_local(
    root: Path,
    name: str,
    *,
    model: str | None = None,
) -> tuple[SkillAnalysisResponse, Path]:
    """Run local LLM-backed analysis using ASM_LLM_MODEL and provider credentials."""
    request = cloud_analysis.build_skill_analysis_request(root, name, analysis_mode="local-llm")
    similar_skills = _find_local_similar_skills(root, name, request.manifest)
    response = _run_local_llm_analysis(request, similar_skills, model=model)
    artifact = SkillAnalysisArtifact(
        manifest=request.manifest,
        evidence=request.evidence,
        scorecard=response.scorecard,
        embedding_profile=response.embedding_profile,
        snapshot_id=request.manifest.snapshot_id,
        integrity=request.manifest.integrity,
    )
    analysis.save_skill_manifest(root, name, request.manifest)
    artifact_path = analysis.save_skill_analysis_artifact(root, name, artifact)
    return response, artifact_path


def _run_local_llm_analysis(
    request: SkillAnalysisRequest,
    similar_skills: list[SimilarSkillMatch],
    *,
    model: str | None = None,
) -> SkillAnalysisResponse:
    client = llm.LLMClient(model=model)
    analysis_id = f"local-{uuid.uuid4()}"
    analysis_version = f"asm-local-llm-v1:{client.model}"
    embedding_profile = embeddings.current_profile(analysis_mode="local-llm")

    system_prompt = (
        "You are evaluating an ASM skill package.\n"
        "Return JSON only.\n"
        "Score each numeric field from 0.0 to 1.0.\n"
        "Use status one of: approved, needs_work, insufficient_evidence.\n"
        "Be strict about trigger specificity, novelty, and evidence grounding.\n"
        "Use duplication_risk to reflect overlap with similar skills.\n"
        "Keep findings and recommended_actions concise."
    )
    user_prompt = _build_local_analysis_prompt(request, similar_skills, analysis_id, analysis_version, client.model)

    try:
        raw = client.completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1200,
        )
    except llm.LLMError as exc:
        raise LocalAnalysisError(str(exc)) from exc

    payload = _extract_json_payload(raw)
    recommended_actions = _coerce_list(payload.get("recommended_actions"))
    scorecard = SkillScorecard(
        skill_name=request.manifest.name,
        analysis_id=analysis_id,
        analysis_version=analysis_version,
        trigger_specificity=_bounded_score(payload.get("trigger_specificity", 0.0)),
        novelty=_bounded_score(payload.get("novelty", 0.0)),
        evidence_grounding=_bounded_score(payload.get("evidence_grounding", 0.0)),
        duplication_risk=_bounded_score(
            payload.get(
                "duplication_risk",
                similar_skills[0].similarity if similar_skills else 0.0,
            )
        ),
        status=_coerce_status(payload.get("status", "insufficient_evidence")),
        findings=_coerce_list(payload.get("findings")),
        recommended_actions=recommended_actions,
        improvement_prompt=build_skill_improvement_prompt(
            request.manifest,
            recommended_actions,
            similar_skills,
        ),
        similar_skills=similar_skills,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    return SkillAnalysisResponse(
        analysis_id=analysis_id,
        analysis_version=analysis_version,
        scorecard=scorecard,
        embedding_profile=embedding_profile,
    )


def _find_local_similar_skills(root: Path, current_name: str, manifest: SkillManifest) -> list[SimilarSkillMatch]:
    cfg = config.load(root / "asm.toml")
    if not cfg.skills:
        return []

    current_text = _manifest_similarity_text(manifest)
    current_vector = embeddings.embed(current_text)
    matches: list[SimilarSkillMatch] = []
    for name in sorted(cfg.skills):
        if name == current_name:
            continue
        try:
            other_manifest = cloud_analysis.build_skill_manifest(root, name)
        except Exception:
            continue
        similarity = embeddings.cosine_similarity(
            current_vector,
            embeddings.embed(_manifest_similarity_text(other_manifest)),
        )
        matches.append(SimilarSkillMatch(name=name, similarity=round(similarity, 4)))
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


def _build_local_analysis_prompt(
    request: SkillAnalysisRequest,
    similar_skills: list[SimilarSkillMatch],
    analysis_id: str,
    analysis_version: str,
    model_name: str,
) -> str:
    file_sections: list[str] = []
    for record in request.files[:12]:
        snippet = record.content[:2400]
        file_sections.append(f"## {record.path} ({record.kind})\n{snippet}")
    files_block = "\n\n".join(file_sections)

    similar_block = "\n".join(
        f"- {item.name}: {item.similarity:.4f}" for item in similar_skills
    ) or "- none"

    return (
        f"Analysis ID: {analysis_id}\n"
        f"Analysis version: {analysis_version}\n"
        f"LLM model: {model_name}\n\n"
        f"Manifest:\n{json.dumps(asdict(request.manifest), indent=2)}\n\n"
        f"Evidence:\n{json.dumps(asdict(request.evidence), indent=2)}\n\n"
        f"Embedding profile:\n{json.dumps(asdict(request.embedding_profile), indent=2)}\n\n"
        f"Similar skills:\n{similar_block}\n\n"
        "Skill files:\n"
        f"{files_block}\n\n"
        "Return JSON with exactly these keys:\n"
        "{\n"
        '  "trigger_specificity": number,\n'
        '  "novelty": number,\n'
        '  "evidence_grounding": number,\n'
        '  "duplication_risk": number,\n'
        '  "status": "approved" | "needs_work" | "insufficient_evidence",\n'
        '  "findings": [string],\n'
        '  "recommended_actions": [string]\n'
        "}\n"
    )


def _extract_json_payload(raw: str) -> dict:
    text = raw.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LocalAnalysisError(f"Local analysis returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LocalAnalysisError("Local analysis returned a non-object JSON payload.")
    return parsed


def _bounded_score(value: object) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(score, 1.0))


def _coerce_status(value: object) -> str:
    status = str(value).strip()
    if status in {"approved", "needs_work", "insufficient_evidence"}:
        return status
    return "insufficient_evidence"


def _coerce_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
