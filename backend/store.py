"""File-backed storage for ASM cloud MVP analysis artifacts."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from asm.core.models import SkillAnalysisRequest, SkillAnalysisResponse


def store_root() -> Path:
    """Return the backend artifact directory."""
    raw = os.environ.get("ASM_CLOUD_STORE", "").strip()
    base = Path(raw).expanduser() if raw else Path.cwd() / ".asm-cloud"
    base.mkdir(parents=True, exist_ok=True)
    return base


def analyses_dir() -> Path:
    path = store_root() / "analyses"
    path.mkdir(parents=True, exist_ok=True)
    return path


def manifests_dir() -> Path:
    path = store_root() / "manifests"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_analysis(request: SkillAnalysisRequest, response: SkillAnalysisResponse) -> Path:
    """Persist request + response for future lookup and similarity corpus reuse."""
    payload = {
        "request": asdict(request),
        "response": asdict(response),
    }
    analysis_path = analyses_dir() / f"{response.analysis_id}.json"
    analysis_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest_path = manifests_dir() / f"{response.analysis_id}.json"
    manifest_path.write_text(
        json.dumps(
            {
                "analysis_id": response.analysis_id,
                "manifest": asdict(request.manifest),
                "embedding_profile": asdict(response.embedding_profile),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return analysis_path


def load_analysis(analysis_id: str) -> dict | None:
    """Load one saved analysis payload."""
    path = analyses_dir() / f"{analysis_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_manifest_corpus() -> list[dict]:
    """Load all previously analyzed manifests for similarity checks."""
    items: list[dict] = []
    for path in sorted(manifests_dir().glob("*.json")):
        items.append(json.loads(path.read_text(encoding="utf-8")))
    return items
