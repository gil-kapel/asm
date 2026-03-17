from unittest.mock import patch
from pathlib import Path

from asm.cli import cli
from asm.core import paths
from asm.core.models import EmbeddingProfile, SkillAnalysisResponse, SkillMeta, SkillScorecard
from asm.services.llm import BODY_DELIMITER, LLMClient, ParsingError

@patch("asm.services.skills.add_skill")
def test_add_skill(mock_add, runner, initialized_workspace):
    """Test that add skill works correctly."""
    mock_add.return_value = SkillMeta(name="test-skill", description="Test description")
    
    result = runner.invoke(cli, ["add", "skill", "gh:user/repo", "--path", str(initialized_workspace)])
    assert result.exit_code == 0
    assert "✔ Installed skill: test-skill" in result.output
    mock_add.assert_called_once()

def test_create_skill_basic(runner, initialized_workspace):
    """Test basic skill creation without AI."""
    result = runner.invoke(cli, ["create", "skill", "new-skill", "Testing skill", "--path", str(initialized_workspace)])
    assert result.exit_code == 0
    assert "✔ Created skill: new-skill" in result.output
    
    skill_dir = initialized_workspace / paths.ASM_DIR / paths.SKILLS_DIR / "new-skill"
    assert skill_dir.exists()
    assert (skill_dir / "SKILL.md").exists()


def test_create_skill_override_replaces_existing_skill_and_clears_analysis(runner, initialized_workspace):
    """Override should rebuild an existing skill in place."""
    initial = runner.invoke(
        cli,
        ["create", "skill", "override-skill", "Initial description", "--path", str(initialized_workspace)],
    )
    assert initial.exit_code == 0

    analysis_dir = initialized_workspace / paths.ASM_DIR / paths.ANALYSIS_DIR / "override-skill"
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "latest.json").write_text('{"stale": true}')

    blocked = runner.invoke(
        cli,
        ["create", "skill", "override-skill", "New description", "--path", str(initialized_workspace)],
    )
    assert blocked.exit_code != 0
    assert "Skill already exists" in blocked.output

    replaced = runner.invoke(
        cli,
        [
            "create",
            "skill",
            "override-skill",
            "New description",
            "--override",
            "--path",
            str(initialized_workspace),
        ],
    )
    assert replaced.exit_code == 0

    skill_md = (
        initialized_workspace / paths.ASM_DIR / paths.SKILLS_DIR / "override-skill" / "SKILL.md"
    ).read_text()
    assert "New description" in skill_md
    assert not (analysis_dir / "latest.json").exists()


@patch.object(LLMClient, "_ensure_litellm", return_value=None)
def test_llm_parse_skill_response_accepts_description_prefix(_mock_litellm):
    """Description cleanup should not crash on prefixed LLM output."""
    client = LLMClient(model="openai/gpt-5-mini")
    description, body = client._parse_skill_response(
        f"Description: Helpful skill summary\n{BODY_DELIMITER}\n## Instructions\nUse it well.",
        "fallback description",
    )

    assert description == "Helpful skill summary"
    assert "## Instructions" in body

@patch("asm.services.llm.generate_skill_content")
def test_create_skill_ai(mock_gen, runner, initialized_workspace):
    """Test skill creation with AI."""
    mock_gen.return_value = ("AI Description", "## Instructions\nTest body")
    
    result = runner.invoke(cli, ["create", "skill", "ai-skill", "AI description", "--ai", "--path", str(initialized_workspace)])
    assert result.exit_code == 0
    assert "✔ Created skill: ai-skill" in result.output
    assert "Content generated with LLM" in result.output
    
    skill_md = (initialized_workspace / paths.ASM_DIR / paths.SKILLS_DIR / "ai-skill" / "SKILL.md").read_text()
    assert "AI Description" in skill_md
    assert "Test body" in skill_md

@patch("asm.services.deepwiki.fetch_repo_docs")
@patch("asm.services.skills.create_skill")
@patch("asm.services.bootstrap.regenerate")
def test_create_skill_from_repo(mock_regen, mock_create, mock_fetch, runner, initialized_workspace):
    """Test skill creation from a repository."""
    mock_fetch.return_value = "Repo docs content"
    mock_create.return_value = initialized_workspace / paths.ASM_DIR / paths.SKILLS_DIR / "repo-skill"
    
    result = runner.invoke(cli, ["create", "skill", "repo-skill", "Desc", "--from-repo", "user/repo", "--path", str(initialized_workspace)])
    assert result.exit_code == 0
    assert "Context from DeepWiki: user/repo" in result.output
    mock_fetch.assert_called_once_with("user", "repo")
    mock_create.assert_called_once()
    assert mock_create.call_args[1]["deepwiki_context"] == "Repo docs content"

@patch("asm.services.skills.create_skill")
def test_create_skill_from_local(mock_create, runner, initialized_workspace):
    """Test skill creation from a local path."""
    source_file = initialized_workspace / "source.py"
    source_file.write_text("print('hello')")
    mock_create.return_value = initialized_workspace / paths.ASM_DIR / paths.SKILLS_DIR / "local-skill"
    
    result = runner.invoke(cli, ["create", "skill", "local-skill", "Desc", "--from", str(source_file), "--path", str(initialized_workspace)])
    assert result.exit_code == 0
    assert "Source distilled from:" in result.output
    assert str(source_file) in result.output
    mock_create.assert_called_once()
    # source_path is the 4th positional argument
    assert str(mock_create.call_args[0][3]) == str(source_file)

@patch("asm.services.skills.create_skill")
def test_create_skill_from_url(mock_create, runner, initialized_workspace):
    """Test skill creation from a URL."""
    mock_create.return_value = initialized_workspace / paths.ASM_DIR / paths.SKILLS_DIR / "url-skill"
    url = "https://example.com/file.md"
    
    result = runner.invoke(cli, ["create", "skill", "url-skill", "Desc", "--from-url", url, "--path", str(initialized_workspace)])
    assert result.exit_code == 0
    assert "Context from URL:" in result.output
    assert url in result.output
    mock_create.assert_called_once()
    assert mock_create.call_args[1]["source_url"] == url


@patch("asm.services.deepwiki.fetch_search_context")
@patch("asm.services.skills.create_skill")
def test_create_skill_from_github_search(mock_create, mock_search, runner, initialized_workspace):
    """Test skill creation enriched by GitHub repository search."""
    mock_create.return_value = initialized_workspace / paths.ASM_DIR / paths.SKILLS_DIR / "search-skill"
    mock_search.return_value = (
        "# GitHub search context\n\n## Search match: tiangolo/sqlmodel",
        [
            type(
                "RepoMatch",
                (),
                {"full_name": "tiangolo/sqlmodel"},
            )(),
        ],
    )

    result = runner.invoke(
        cli,
        [
            "create",
            "skill",
            "search-skill",
            "Desc",
            "--github-search",
            "sqlmodel fastapi",
            "--github-search-limit",
            "2",
            "--path",
            str(initialized_workspace),
        ],
    )

    assert result.exit_code == 0
    assert "GitHub search query: sqlmodel fastapi" in result.output
    assert "Enriched from repos: tiangolo/sqlmodel" in result.output
    mock_search.assert_called_once_with("sqlmodel fastapi", limit=2)
    mock_create.assert_called_once()
    assert mock_create.call_args[1]["deepwiki_context"] == "# GitHub search context\n\n## Search match: tiangolo/sqlmodel"


@patch("asm.services.llm.revise_skill_content")
@patch("asm.services.skill_analysis.analyze_skill_local")
@patch("asm.services.llm.generate_skill_content")
def test_create_skill_loop_until_target(
    mock_generate,
    mock_analyze,
    mock_revise,
    runner,
    initialized_workspace,
):
    """Test iterative build/analyze/rewrite during skill creation."""
    mock_generate.return_value = ("Draft Description", "## Instructions\nDraft body")
    mock_revise.return_value = ("Final Description", "## Instructions\nFinal body")
    artifact_path = initialized_workspace / ".asm" / "analysis" / "loop-skill" / "latest.json"

    def _response(score: float, prompt: str) -> SkillAnalysisResponse:
        duplication_risk = round(max(0.0, 1.0 - score), 2)
        return SkillAnalysisResponse(
            analysis_id=f"analysis-{score}",
            analysis_version="asm-local-llm-v1:openai/gpt-5-mini",
            scorecard=SkillScorecard(
                skill_name="loop-skill",
                analysis_id=f"analysis-{score}",
                analysis_version="asm-local-llm-v1:openai/gpt-5-mini",
                trigger_specificity=score,
                novelty=score,
                evidence_grounding=score,
                duplication_risk=duplication_risk,
                status="needs_work" if score < 0.9 else "approved",
                improvement_prompt=prompt,
            ),
            embedding_profile=EmbeddingProfile(
                provider="litellm",
                model="openai/text-embedding-3-small",
                dimension=1536,
                normalized=False,
                distance_metric="cosine",
                embedding_version="litellm:openai/text-embedding-3-small:1536:cosine:norm=false",
                analysis_mode="local-llm",
            ),
        )

    mock_analyze.side_effect = [
        (_response(0.62, "Tighten the trigger phrases and add clearer evidence."), artifact_path),
        (_response(0.94, "Unused second prompt."), artifact_path),
    ]

    result = runner.invoke(
        cli,
        [
            "create",
            "skill",
            "loop-skill",
            "Looped skill",
            "--loop",
            "--target-score",
            "0.9",
            "--path",
            str(initialized_workspace),
        ],
    )

    assert result.exit_code == 0
    assert "✔ Created skill: loop-skill" in result.output
    assert "Content generated with LLM" in result.output
    assert "Loop score: 0.94 (target 0.90, tries 2/5)" in result.output
    assert "Loop status: reached target" in result.output
    assert mock_generate.call_count == 1
    assert mock_revise.call_count == 1
    assert mock_analyze.call_count == 2

    skill_md = (
        initialized_workspace / paths.ASM_DIR / paths.SKILLS_DIR / "loop-skill" / "SKILL.md"
    ).read_text()
    assert "Final Description" in skill_md
    assert "Final body" in skill_md


@patch("asm.services.llm.revise_skill_content")
@patch("asm.services.skill_analysis.analyze_skill_local")
@patch("asm.services.llm.generate_skill_content")
def test_create_skill_loop_stops_when_rewrite_is_empty(
    mock_generate,
    mock_analyze,
    mock_revise,
    runner,
    initialized_workspace,
):
    """Empty rewrite output should stop the loop without failing skill creation."""
    mock_generate.return_value = ("Draft Description", "## Instructions\nDraft body")
    mock_revise.side_effect = ParsingError("LLM returned empty content while revising a skill.")
    artifact_path = initialized_workspace / ".asm" / "analysis" / "empty-rewrite-skill" / "latest.json"

    response = SkillAnalysisResponse(
        analysis_id="analysis-1",
        analysis_version="asm-local-llm-v1:openai/gpt-5-mini",
        scorecard=SkillScorecard(
            skill_name="empty-rewrite-skill",
            analysis_id="analysis-1",
            analysis_version="asm-local-llm-v1:openai/gpt-5-mini",
            trigger_specificity=0.62,
            novelty=0.62,
            evidence_grounding=0.62,
            duplication_risk=0.38,
            status="needs_work",
            improvement_prompt="Try a better rewrite.",
        ),
        embedding_profile=EmbeddingProfile(
            provider="litellm",
            model="openai/text-embedding-3-small",
            dimension=1536,
            normalized=False,
            distance_metric="cosine",
            embedding_version="litellm:openai/text-embedding-3-small:1536:cosine:norm=false",
            analysis_mode="local-llm",
        ),
    )
    mock_analyze.return_value = (response, artifact_path)

    result = runner.invoke(
        cli,
        [
            "create",
            "skill",
            "empty-rewrite-skill",
            "Looped skill",
            "--loop",
            "--path",
            str(initialized_workspace),
        ],
    )

    assert result.exit_code == 0
    assert "✔ Created skill: empty-rewrite-skill" in result.output
    assert "Loop status: stopped before target" in result.output
    assert mock_generate.call_count == 1
    assert mock_revise.call_count == 1
    skill_md = (
        initialized_workspace / paths.ASM_DIR / paths.SKILLS_DIR / "empty-rewrite-skill" / "SKILL.md"
    ).read_text()
    assert "Draft Description" in skill_md
    assert "Draft body" in skill_md
