import json

from asm.cli import cli
from asm.repo import analysis
from asm.services import cloud_analysis, embeddings, skill_analysis
from asm.core.models import EmbeddingProfile, SkillAnalysisResponse, SkillScorecard


def test_build_skill_analysis_request_collects_manifest_and_files(runner, initialized_workspace):
    result = runner.invoke(
        cli,
        ["create", "skill", "analysis-skill", "This skill should be used when the user asks to \"analyze migrations\".", "--path", str(initialized_workspace)],
    )
    assert result.exit_code == 0

    skill_dir = initialized_workspace / ".asm" / "skills" / "analysis-skill"
    references_dir = skill_dir / "references"
    references_dir.mkdir(exist_ok=True)
    (references_dir / "guide.md").write_text("See https://example.com/alembic for details.")

    request = cloud_analysis.build_skill_analysis_request(initialized_workspace, "analysis-skill")

    assert request.manifest.name == "analysis-skill"
    assert request.manifest.snapshot_id
    assert request.manifest.integrity.startswith("sha256:")
    assert "analyze migrations" in request.manifest.trigger_phrases
    assert any(item.path == "SKILL.md" for item in request.files)
    assert "references/guide.md" in request.evidence.source_files
    assert "https://example.com/alembic" in request.evidence.source_urls


def test_analyze_skill_cloud_saves_local_artifact(runner, initialized_workspace, monkeypatch):
    result = runner.invoke(
        cli,
        ["create", "skill", "artifact-skill", "This skill should be used when the user asks to \"ship a skill\".", "--path", str(initialized_workspace)],
    )
    assert result.exit_code == 0

    canned = SkillAnalysisResponse(
        analysis_id="analysis-123",
        analysis_version="asm-cloud-mvp-v1",
        scorecard=SkillScorecard(
            skill_name="artifact-skill",
            analysis_id="analysis-123",
            analysis_version="asm-cloud-mvp-v1",
            trigger_specificity=0.88,
            novelty=0.79,
            evidence_grounding=0.66,
            duplication_risk=0.21,
            status="approved",
            improvement_prompt="Improve the artifact skill.",
        ),
        embedding_profile=EmbeddingProfile(
            provider="litellm",
            model="text-embedding-3-small",
            dimension=1536,
            normalized=False,
            distance_metric="cosine",
            embedding_version="litellm:text-embedding-3-small:1536:cosine:norm=false",
            analysis_mode="cloud",
        ),
    )
    monkeypatch.setattr(cloud_analysis, "submit_skill_analysis", lambda request, **kwargs: canned)

    response, artifact_path = cloud_analysis.analyze_skill_cloud(initialized_workspace, "artifact-skill")
    saved = analysis.load_skill_analysis_artifact(initialized_workspace, "artifact-skill")

    assert response.analysis_id == "analysis-123"
    assert artifact_path.exists()
    assert saved is not None
    assert saved.scorecard.status == "approved"
    assert saved.scorecard.improvement_prompt == "Improve the artifact skill."
    assert saved.embedding_profile.analysis_mode == "cloud"
    assert saved.snapshot_id == saved.manifest.snapshot_id


def test_embedding_profile_contains_version_metadata():
    profile = embeddings.current_profile(analysis_mode="cloud")
    assert profile.embedding_version
    assert profile.provider in profile.embedding_version
    assert profile.distance_metric == "cosine"


def test_analyze_skill_local_saves_local_artifact(runner, initialized_workspace, monkeypatch):
    result = runner.invoke(
        cli,
        ["create", "skill", "local-analysis-skill", "This skill should be used when the user asks to \"review prompts\".", "--path", str(initialized_workspace)],
    )
    assert result.exit_code == 0
    result = runner.invoke(
        cli,
        ["create", "skill", "neighbor-skill", "This skill should be used when the user asks to \"review prompts faster\".", "--path", str(initialized_workspace)],
    )
    assert result.exit_code == 0

    payload = {
        "trigger_specificity": 0.84,
        "novelty": 0.72,
        "evidence_grounding": 0.67,
        "duplication_risk": 0.28,
        "status": "approved",
        "findings": ["Trigger phrases are concrete."],
        "recommended_actions": ["Add one more reference example."],
    }
    monkeypatch.setattr(
        skill_analysis.llm.LLMClient,
        "completion",
        lambda self, messages, max_tokens=1200, **kwargs: json.dumps(payload),
    )

    response, artifact_path = skill_analysis.analyze_skill_local(
        initialized_workspace,
        "local-analysis-skill",
        model="openai/gpt-5-mini",
    )
    saved = analysis.load_skill_analysis_artifact(initialized_workspace, "local-analysis-skill")

    assert response.analysis_id.startswith("local-")
    assert response.embedding_profile.analysis_mode == "local-llm"
    assert response.scorecard.status == "approved"
    assert artifact_path.exists()
    assert saved is not None
    assert saved.scorecard.findings == ["Trigger phrases are concrete."]
    assert 'Improve the ASM skill "local-analysis-skill".' in saved.scorecard.improvement_prompt
    assert "Add one more reference example." in saved.scorecard.improvement_prompt
