"""Repository helpers for local skill analysis artifacts."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from asm.core import paths
from asm.core.models import (
    EmbeddingProfile,
    SimilarSkillMatch,
    SkillAnalysisArtifact,
    SkillEvidence,
    SkillManifest,
    SkillResourceGroup,
    SkillResourceInventory,
    SkillScorecard,
)


def save_skill_analysis_artifact(root: Path, skill_name: str, artifact: SkillAnalysisArtifact) -> Path:
    """Persist the latest analysis artifact under `.asm/analysis/<skill>/latest.json`."""
    target = paths.skill_analysis_latest_path(root, skill_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(asdict(artifact), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def save_skill_manifest(root: Path, skill_name: str, manifest: SkillManifest) -> Path:
    """Persist the latest analysis manifest next to the scorecard artifact."""
    target = paths.skill_analysis_manifest_path(root, skill_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(asdict(manifest), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def load_skill_analysis_artifact(root: Path, skill_name: str) -> SkillAnalysisArtifact | None:
    """Load the latest saved artifact for a skill, if present."""
    target = paths.skill_analysis_latest_path(root, skill_name)
    if not target.exists():
        return None

    payload = json.loads(target.read_text(encoding="utf-8"))
    return SkillAnalysisArtifact(
        manifest=_parse_manifest(payload.get("manifest", {})),
        evidence=SkillEvidence(**payload.get("evidence", {})),
        scorecard=_parse_scorecard(payload.get("scorecard", {})),
        embedding_profile=EmbeddingProfile(**payload.get("embedding_profile", {})),
        snapshot_id=str(payload.get("snapshot_id", "")),
        integrity=str(payload.get("integrity", "")),
    )


def _parse_manifest(raw: dict) -> SkillManifest:
    inventory_raw = raw.get("resource_inventory", {})
    return SkillManifest(
        name=str(raw.get("name", "")),
        description=str(raw.get("description", "")),
        version=str(raw.get("version", "0.0.0")),
        trigger_phrases=list(raw.get("trigger_phrases", [])),
        resource_inventory=SkillResourceInventory(
            references=_parse_resource_group(inventory_raw.get("references", {})),
            scripts=_parse_resource_group(inventory_raw.get("scripts", {})),
            examples=_parse_resource_group(inventory_raw.get("examples", {})),
            assets=_parse_resource_group(inventory_raw.get("assets", {})),
        ),
        source_ref=str(raw.get("source_ref", "")),
        snapshot_id=str(raw.get("snapshot_id", "")),
        integrity=str(raw.get("integrity", "")),
    )


def _parse_resource_group(raw: dict) -> SkillResourceGroup:
    return SkillResourceGroup(
        count=int(raw.get("count", 0)),
        files=list(raw.get("files", [])),
    )


def _parse_scorecard(raw: dict) -> SkillScorecard:
    matches = [
        SimilarSkillMatch(
            name=str(item.get("name", "")),
            similarity=float(item.get("similarity", 0.0)),
        )
        for item in raw.get("similar_skills", [])
    ]
    return SkillScorecard(
        skill_name=str(raw.get("skill_name", "")),
        analysis_id=str(raw.get("analysis_id", "")),
        analysis_version=str(raw.get("analysis_version", "")),
        trigger_specificity=float(raw.get("trigger_specificity", 0.0)),
        novelty=float(raw.get("novelty", 0.0)),
        evidence_grounding=float(raw.get("evidence_grounding", 0.0)),
        duplication_risk=float(raw.get("duplication_risk", 0.0)),
        status=str(raw.get("status", "insufficient_evidence")),  # type: ignore[arg-type]
        findings=list(raw.get("findings", [])),
        recommended_actions=list(raw.get("recommended_actions", [])),
        improvement_prompt=str(raw.get("improvement_prompt", "")),
        similar_skills=matches,
        created_at=str(raw.get("created_at", "")),
    )
