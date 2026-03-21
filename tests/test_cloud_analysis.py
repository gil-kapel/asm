import re
import pytest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import BaseModel

from asm.cli import cli
from asm.repo import analysis
from asm.services import analysis_feedback, cloud_analysis, embeddings, skill_analysis
from asm.core import paths
from asm.core.models import EmbeddingProfile, SkillAnalysisResponse, SkillScorecard
from asm.services.llm import LLMClient


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


def test_build_skill_manifest_parses_trigger_phrases_from_frontmatter(runner, initialized_workspace):
    result = runner.invoke(
        cli,
        ["create", "skill", "trigger-frontmatter-skill", "A skill description for trigger parsing.", "--path", str(initialized_workspace)],
    )
    assert result.exit_code == 0

    skill_dir = initialized_workspace / paths.ASM_DIR / paths.SKILLS_DIR / "trigger-frontmatter-skill"
    skill_md_path = skill_dir / "SKILL.md"
    original = skill_md_path.read_text(encoding="utf-8")

    m = re.match(r"^---\n(?P<fm>.*?)\n---\n(?P<body>.*)$", original, flags=re.DOTALL)
    assert m, "Expected YAML frontmatter in generated SKILL.md"

    frontmatter = m.group("fm").rstrip()
    body = m.group("body")
    frontmatter = (
        frontmatter
        + "\ntrigger_phrases:\n  - \"alpha trigger phrase\"\n  - \"beta trigger phrase\"\n"
    )
    skill_md_path.write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")

    manifest = cloud_analysis.build_skill_manifest(initialized_workspace, "trigger-frontmatter-skill", skill_dir=skill_dir)
    assert "alpha trigger phrase" in manifest.trigger_phrases
    assert "beta trigger phrase" in manifest.trigger_phrases


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
    seen: dict[str, object] = {}

    def _fake_feedback(request, similar_skills, **kwargs):
        seen["analysis_id"] = kwargs.get("analysis_id")
        seen["analysis_version"] = kwargs.get("analysis_version")
        seen["model"] = kwargs.get("model")
        return analysis_feedback.LocalAnalysisFeedbackPayload.model_validate(payload)

    monkeypatch.setattr(
        skill_analysis,
        "analyze_local_analysis_feedback_sync",
        _fake_feedback,
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
    assert seen["analysis_id"].startswith("local-")
    assert seen["analysis_version"] == "asm-local-openai-v1"
    assert seen["model"] == "openai/gpt-5-mini"


def test_analyze_skill_local_raises_when_openai_feedback_fails(runner, initialized_workspace, monkeypatch):
    result = runner.invoke(
        cli,
        ["create", "skill", "failed-analysis-skill", "This skill should be used when the user asks to \"repair analyzer output\".", "--path", str(initialized_workspace)],
    )
    assert result.exit_code == 0

    monkeypatch.setattr(
        skill_analysis,
        "analyze_local_analysis_feedback_sync",
        lambda request, similar_skills, **kwargs: (_ for _ in ()).throw(
            analysis_feedback.AnalysisFeedbackError("structured parse failed")
        ),
    )

    with pytest.raises(skill_analysis.LocalAnalysisError, match="structured parse failed"):
        skill_analysis.analyze_skill_local(
            initialized_workspace,
            "failed-analysis-skill",
            model="openai/gpt-5-mini",
        )


@patch.object(LLMClient, "_ensure_litellm", return_value=None)
def test_llm_client_completion_pydantic_requests_model_schema(_mock_litellm, monkeypatch):
    calls: list[dict] = []

    class _TestSchema(BaseModel):
        status: str

    def _fake_completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"status":"ok"}')
                )
            ]
        )

    import litellm

    monkeypatch.setattr(litellm, "completion", _fake_completion)
    client = LLMClient(model="openai/gpt-5-mini")

    payload = client.completion_pydantic(
        messages=[{"role": "user", "content": "Return JSON."}],
        response_model=_TestSchema,
        schema_name="test_schema",
    )

    assert payload.status == "ok"
    assert calls[0]["response_format"]["type"] == "json_schema"
    assert calls[0]["response_format"]["json_schema"]["name"] == "test_schema"
    assert calls[0]["response_format"]["json_schema"]["schema"]["required"] == ["status"]


@patch.object(LLMClient, "_ensure_litellm", return_value=None)
def test_llm_client_completion_pydantic_strictifies_defaulted_fields(_mock_litellm, monkeypatch):
    calls: list[dict] = []

    class _TestSchema(BaseModel):
        required_text: str
        default_list: list[str] = []

    def _fake_completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"required_text":"ok","default_list":[]}')
                )
            ]
        )

    import litellm

    monkeypatch.setattr(litellm, "completion", _fake_completion)
    client = LLMClient(model="openai/gpt-5-mini")

    payload = client.completion_pydantic(
        messages=[{"role": "user", "content": "Return JSON."}],
        response_model=_TestSchema,
        schema_name="strict_defaults",
    )

    assert payload.required_text == "ok"
    assert calls[0]["response_format"]["json_schema"]["schema"]["required"] == [
        "required_text",
        "default_list",
    ]


def test_openai_analysis_feedback_service_uses_async_parse(runner, initialized_workspace, monkeypatch):
    result = runner.invoke(
        cli,
        ["create", "skill", "service-analysis-skill", "This skill should be used when the user asks to \"review prompts async\".", "--path", str(initialized_workspace)],
    )
    assert result.exit_code == 0

    request = cloud_analysis.build_skill_analysis_request(initialized_workspace, "service-analysis-skill")
    calls: list[dict] = []
    client_kwargs: list[dict] = []
    parsed_payload = analysis_feedback.LocalAnalysisFeedbackPayload(
        trigger_specificity=0.9,
        novelty=0.8,
        evidence_grounding=0.7,
        duplication_risk=0.2,
        status="approved",
        findings=["Structured output succeeded."],
        recommended_actions=["Keep the async OpenAI path."],
    )

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            client_kwargs.append(kwargs)
            self.responses = SimpleNamespace(parse=self._parse)

        async def _parse(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_parsed=parsed_payload, refusal=None)

    monkeypatch.setattr(analysis_feedback, "AsyncOpenAI", _FakeAsyncOpenAI)

    payload = analysis_feedback.analyze_local_analysis_feedback_sync(
        request,
        [],
        analysis_id="local-123",
        analysis_version="asm-local-openai-v1",
        model="openai/gpt-5-mini",
    )

    assert payload == parsed_payload
    assert "api_key" in client_kwargs[0]
    assert calls[0]["model"] == "gpt-5-mini"
    assert calls[0]["text_format"] is analysis_feedback.LocalAnalysisFeedbackPayload
