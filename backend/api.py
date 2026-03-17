"""Thin FastAPI app for the ASM cloud MVP."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, HTTPException

from asm.core.models import (
    EmbeddingProfile,
    SimilarSkillMatch,
    SkillAnalysisRequest,
    SkillAnalysisResponse,
    SkillEvidence,
    SkillFileRecord,
    SkillManifest,
    SkillResourceGroup,
    SkillResourceInventory,
    SkillScorecard,
)

from backend import analyzer, store

app = FastAPI(title="ASM Cloud MVP", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    """Simple health check for the managed backend."""
    return {"status": "ok"}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Alias health endpoint for deployment probes."""
    return {"status": "ok"}


@app.post("/v1/skills/analyze")
def analyze_skill(payload: dict) -> dict:
    """Analyze one skill payload and return a structured scorecard."""
    request = _parse_request(payload)
    response = analyzer.analyze_request(request)
    return asdict(response)


@app.get("/v1/skills/analyses/{analysis_id}")
def get_analysis(analysis_id: str) -> dict:
    """Fetch one persisted scorecard by analysis id."""
    payload = store.load_analysis(analysis_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    return payload.get("response", {})


def _parse_request(payload: dict) -> SkillAnalysisRequest:
    try:
        manifest_raw = payload["manifest"]
        evidence_raw = payload["evidence"]
        profile_raw = payload["embedding_profile"]
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"missing field: {exc.args[0]}") from exc

    inventory_raw = manifest_raw.get("resource_inventory", {})
    manifest = SkillManifest(
        name=str(manifest_raw.get("name", "")),
        description=str(manifest_raw.get("description", "")),
        version=str(manifest_raw.get("version", "0.0.0")),
        trigger_phrases=list(manifest_raw.get("trigger_phrases", [])),
        resource_inventory=SkillResourceInventory(
            references=_parse_resource_group(inventory_raw.get("references", {})),
            scripts=_parse_resource_group(inventory_raw.get("scripts", {})),
            examples=_parse_resource_group(inventory_raw.get("examples", {})),
            assets=_parse_resource_group(inventory_raw.get("assets", {})),
        ),
        source_ref=str(manifest_raw.get("source_ref", "")),
        snapshot_id=str(manifest_raw.get("snapshot_id", "")),
        integrity=str(manifest_raw.get("integrity", "")),
    )
    evidence = SkillEvidence(
        source_urls=list(evidence_raw.get("source_urls", [])),
        source_files=list(evidence_raw.get("source_files", [])),
        deepwiki_ref=str(evidence_raw.get("deepwiki_ref", "")),
        evidence_digest=str(evidence_raw.get("evidence_digest", "")),
    )
    profile = EmbeddingProfile(
        provider=str(profile_raw.get("provider", "")),
        model=str(profile_raw.get("model", "")),
        dimension=int(profile_raw.get("dimension", 0)),
        normalized=bool(profile_raw.get("normalized", False)),
        distance_metric=str(profile_raw.get("distance_metric", "cosine")),
        embedding_version=str(profile_raw.get("embedding_version", "")),
        analysis_mode=str(profile_raw.get("analysis_mode", "cloud")),
    )
    files = [
        SkillFileRecord(
            path=str(item.get("path", "")),
            kind=str(item.get("kind", "other")),  # type: ignore[arg-type]
            content=str(item.get("content", "")),
        )
        for item in payload.get("files", [])
    ]
    return SkillAnalysisRequest(
        manifest=manifest,
        evidence=evidence,
        embedding_profile=profile,
        files=files,
    )


def _parse_resource_group(raw: dict) -> SkillResourceGroup:
    return SkillResourceGroup(
        count=int(raw.get("count", 0)),
        files=list(raw.get("files", [])),
    )
