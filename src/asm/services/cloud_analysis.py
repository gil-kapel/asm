"""Cloud skill analysis service."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import asdict
from pathlib import Path

import httpx

from asm.core import paths
from asm.core.frontmatter import extract_meta
from asm.core.models import (
    SimilarSkillMatch,
    SkillAnalysisArtifact,
    SkillAnalysisRequest,
    SkillAnalysisResponse,
    SkillEvidence,
    SkillFileRecord,
    SkillManifest,
    SkillResourceGroup,
    SkillResourceInventory,
    SkillScorecard,
)
from asm.repo import analysis, config, lockfile, snapshots
from asm.services import embeddings, skills

_DEFAULT_TIMEOUT_SECONDS = 30.0


class CloudAnalysisError(RuntimeError):
    """Raised when the managed analyzer request cannot complete."""


def analyze_skill_cloud(
    root: Path,
    name: str,
    *,
    api_url: str | None = None,
    api_key: str | None = None,
) -> tuple[SkillAnalysisResponse, Path]:
    """Build a request payload, call the cloud analyzer, and persist the artifact."""
    request = build_skill_analysis_request(root, name)
    response = submit_skill_analysis(request, api_url=api_url, api_key=api_key)
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


def build_skill_analysis_request(
    root: Path,
    name: str,
    *,
    analysis_mode: str = "cloud",
) -> SkillAnalysisRequest:
    """Build the cloud analysis payload for one installed skill."""
    skill_dir = skills._require_skill_dir(root, name)
    manifest = build_skill_manifest(root, name, skill_dir)
    evidence = build_skill_evidence(skill_dir)
    files = collect_skill_files(skill_dir)
    embedding_profile = embeddings.current_profile(analysis_mode=analysis_mode)
    return SkillAnalysisRequest(
        manifest=manifest,
        evidence=evidence,
        embedding_profile=embedding_profile,
        files=files,
    )


def build_skill_manifest(root: Path, name: str, skill_dir: Path | None = None) -> SkillManifest:
    """Build a structured manifest from local ASM state."""
    skill_dir = skill_dir or skills._require_skill_dir(root, name)
    meta = extract_meta(skill_dir)
    cfg = config.load(root / paths.ASM_TOML)
    lock = lockfile.load(paths.lock_path(root))
    source_ref = cfg.skills.get(name).source if name in cfg.skills else ""
    current_lock = lock.get(name)
    integrity = lockfile.compute_integrity(skill_dir)
    snapshot_id = snapshots.ensure_snapshot(root, name, skill_dir)
    return SkillManifest(
        name=meta.name or name,
        description=meta.description,
        version=meta.version,
        trigger_phrases=list(getattr(meta, "trigger_phrases", [])) or _extract_trigger_phrases(meta.description),
        resource_inventory=_build_resource_inventory(skill_dir),
        source_ref=source_ref or (current_lock.resolved if current_lock else ""),
        snapshot_id=snapshot_id,
        integrity=integrity,
    )


def build_skill_evidence(skill_dir: Path) -> SkillEvidence:
    """Build a simple evidence inventory from skill files."""
    source_urls: set[str] = set()
    source_files: list[str] = []

    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(skill_dir).as_posix()
        source_files.append(rel_path)
        if path.suffix.lower() in {".md", ".txt", ".py", ".toml", ".json", ".yaml", ".yml", ".sh"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            source_urls.update(_extract_urls(text))

    digest_input = "\n".join([*sorted(source_urls), *source_files])
    evidence_digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
    return SkillEvidence(
        source_urls=sorted(source_urls),
        source_files=source_files,
        evidence_digest=f"sha256:{evidence_digest}",
    )


def collect_skill_files(skill_dir: Path) -> list[SkillFileRecord]:
    """Collect the skill files sent to the cloud analyzer."""
    records: list[SkillFileRecord] = []
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(skill_dir).as_posix()
        records.append(
            SkillFileRecord(
                path=rel_path,
                kind=_classify_file(rel_path),
                content=path.read_text(encoding="utf-8", errors="ignore"),
            )
        )
    return records


def submit_skill_analysis(
    request: SkillAnalysisRequest,
    *,
    api_url: str | None = None,
    api_key: str | None = None,
) -> SkillAnalysisResponse:
    """Submit a skill analysis request to the managed ASM backend."""
    base_url = (api_url or os.environ.get("ASM_CLOUD_API_URL", "")).strip().rstrip("/")
    if not base_url:
        raise CloudAnalysisError(
            "ASM cloud analyzer URL is not configured. Set `ASM_CLOUD_API_URL` or pass `--api-url` later when supported."
        )

    token = (api_key or os.environ.get("ASM_CLOUD_API_KEY", "")).strip()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload = asdict(request)
    try:
        with httpx.Client(timeout=_DEFAULT_TIMEOUT_SECONDS) as client:
            response = client.post(f"{base_url}/v1/skills/analyze", json=payload, headers=headers)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise CloudAnalysisError(f"Cloud analysis request failed: {exc}") from exc

    return _parse_analysis_response(response.json())


def _parse_analysis_response(payload: dict) -> SkillAnalysisResponse:
    scorecard_raw = payload.get("scorecard", {})
    similar = [
        SimilarSkillMatch(
            name=str(item.get("name", "")),
            similarity=float(item.get("similarity", 0.0)),
        )
        for item in scorecard_raw.get("similar_skills", [])
    ]
    scorecard = SkillScorecard(
        skill_name=str(scorecard_raw.get("skill_name", "")),
        analysis_id=str(scorecard_raw.get("analysis_id", payload.get("analysis_id", ""))),
        analysis_version=str(scorecard_raw.get("analysis_version", payload.get("analysis_version", ""))),
        trigger_specificity=float(scorecard_raw.get("trigger_specificity", 0.0)),
        novelty=float(scorecard_raw.get("novelty", 0.0)),
        evidence_grounding=float(scorecard_raw.get("evidence_grounding", 0.0)),
        duplication_risk=float(scorecard_raw.get("duplication_risk", 0.0)),
        status=str(scorecard_raw.get("status", "insufficient_evidence")),  # type: ignore[arg-type]
        findings=list(scorecard_raw.get("findings", [])),
        recommended_actions=list(scorecard_raw.get("recommended_actions", [])),
        improvement_prompt=str(scorecard_raw.get("improvement_prompt", "")),
        similar_skills=similar,
        created_at=str(scorecard_raw.get("created_at", "")),
    )
    profile_raw = payload.get("embedding_profile", {})
    embedding_profile = embeddings.profile_from_dict(profile_raw, analysis_mode="cloud")
    return SkillAnalysisResponse(
        analysis_id=str(payload.get("analysis_id", scorecard.analysis_id)),
        analysis_version=str(payload.get("analysis_version", scorecard.analysis_version)),
        scorecard=scorecard,
        embedding_profile=embedding_profile,
    )


def _build_resource_inventory(skill_dir: Path) -> SkillResourceInventory:
    return SkillResourceInventory(
        references=_resource_group(skill_dir, "references"),
        scripts=_resource_group(skill_dir, "scripts"),
        examples=_resource_group(skill_dir, "examples"),
        assets=_resource_group(skill_dir, "assets"),
    )


def _resource_group(skill_dir: Path, directory: str) -> SkillResourceGroup:
    root = skill_dir / directory
    if not root.exists():
        return SkillResourceGroup()
    files = [
        path.relative_to(skill_dir).as_posix()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]
    return SkillResourceGroup(count=len(files), files=files)


def _extract_trigger_phrases(description: str) -> list[str]:
    return [match.strip() for match in re.findall(r'"([^"]+)"', description)]


def _extract_urls(text: str) -> list[str]:
    return re.findall(r"https?://[^\s)>\]]+", text)


def _classify_file(rel_path: str) -> str:
    if rel_path == "SKILL.md":
        return "skill_md"
    if rel_path.startswith("references/"):
        return "reference"
    if rel_path.startswith("scripts/"):
        return "script"
    if rel_path.startswith("examples/"):
        return "example"
    if rel_path.startswith("assets/"):
        return "asset"
    return "other"
