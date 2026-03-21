import json
from unittest.mock import patch
from pathlib import Path

from asm.cli import cli
from asm.core import paths
from asm.core.models import EmbeddingProfile, SkillAnalysisResponse, SkillMeta, SkillScorecard
from asm.services.llm import BODY_DELIMITER, LLMClient, ParsingError
from asm.services import skills as skills_service

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


@patch("asm.services.llm.revise_skill_content")
def test_create_skill_improve_rewrites_existing_skill_in_place(
    mock_revise,
    runner,
    initialized_workspace,
):
    """Improve should rewrite the existing skill without deleting support files."""
    initial = runner.invoke(
        cli,
        ["create", "skill", "improve-skill", "Initial description", "--path", str(initialized_workspace)],
    )
    assert initial.exit_code == 0

    skill_dir = initialized_workspace / paths.ASM_DIR / paths.SKILLS_DIR / "improve-skill"
    references_dir = skill_dir / "references"
    references_dir.mkdir(parents=True)
    preserved_file = references_dir / "existing-notes.md"
    preserved_file.write_text("Keep this evidence file.")

    analysis_dir = initialized_workspace / paths.ASM_DIR / paths.ANALYSIS_DIR / "improve-skill"
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "latest.json").write_text('{"keep": true}')

    mock_revise.return_value = ("Improved Description", "## Instructions\nImproved body")

    improved = runner.invoke(
        cli,
        [
            "create",
            "skill",
            "improve-skill",
            "Tighten routing precision and evidence grounding.",
            "--improve",
            "--path",
            str(initialized_workspace),
        ],
    )
    assert improved.exit_code == 0
    assert "✔ Improved skill: improve-skill" in improved.output
    assert "Content generated with LLM" in improved.output

    skill_md = (skill_dir / "SKILL.md").read_text()
    assert "Improved Description" in skill_md
    assert "Improved body" in skill_md
    assert preserved_file.exists()
    assert (analysis_dir / "latest.json").exists()
    assert mock_revise.call_count == 1
    assert "Tighten routing precision and evidence grounding." in mock_revise.call_args[0][2]
    assert "references/existing-notes.md" in mock_revise.call_args[1]["supporting_files"]


@patch("asm.services.llm.generate_support_file_content")
@patch("asm.services.llm.revise_skill_content")
def test_create_skill_improve_prefers_python_runnable_files(
    mock_revise,
    mock_generate_support_file,
    initialized_workspace,
):
    """Python-oriented skills should normalize runnable script paths to Python."""
    created = skills_service.create_skill(
        initialized_workspace,
        "python-runtime-skill",
        "This skill should be used when the user asks to run browser automation in Python.",
    )
    assert created.path.exists()

    mock_revise.return_value = (
        'Python automation skill with triggers "run in python" "python browser automation"',
        "\n".join(
            [
                "## Niche Examples",
                "- Example: run the browser flow from Python and write artifacts.",
                "",
                "## Supporting Files",
                "- `scripts/run-agent.js`",
            ]
        ),
    )
    mock_generate_support_file.return_value = "\n".join(
        [
            "#!/usr/bin/env python3",
            "from __future__ import annotations",
            "",
            "import argparse",
            "",
            "def main():",
            "    parser = argparse.ArgumentParser()",
            "    parser.add_argument('--scenario', required=True)",
            "    parser.parse_args()",
            "",
            "if __name__ == '__main__':",
            "    main()",
            "",
        ]
    )

    result = skills_service.create_skill(
        initialized_workspace,
        "python-runtime-skill",
        "Improve this skill in Python.",
        use_llm=True,
        improve=True,
    )

    skill_md = (result.path / "SKILL.md").read_text()
    assert "scripts/run-agent.py" in skill_md
    assert "scripts/run-agent.js" not in skill_md
    assert (result.path / "scripts" / "run-agent.py").exists()
    assert not (result.path / "scripts" / "run-agent.js").exists()
    assert mock_generate_support_file.call_args.args[2] == "scripts/run-agent.py"


def test_create_skill_improve_rejects_override(runner, initialized_workspace):
    """Improve and override are mutually exclusive modes."""
    result = runner.invoke(
        cli,
        [
            "create",
            "skill",
            "confused-skill",
            "Do not allow both modes.",
            "--improve",
            "--override",
            "--path",
            str(initialized_workspace),
        ],
    )
    assert result.exit_code != 0
    assert "--improve and --override cannot be used together" in result.output


def test_skill_share_packages_shareable_artifacts(runner, initialized_workspace):
    """A local skill can be exported as a shareable folder and zip."""
    created = runner.invoke(
        cli,
        ["create", "skill", "share-skill", "Shareable skill", "--path", str(initialized_workspace)],
    )
    assert created.exit_code == 0

    result = runner.invoke(
        cli,
        ["skill", "share", "share-skill", "--path", str(initialized_workspace)],
    )
    assert result.exit_code == 0
    assert "✔ Shared skill: share-skill" in result.output

    share_dir = initialized_workspace / "dist" / "skills" / "share-skill"
    archive_path = initialized_workspace / "dist" / "skills" / "share-skill.zip"
    assert share_dir.exists()
    assert archive_path.exists()
    assert (share_dir / "SKILL.md").exists()

    share_manifest = json.loads((share_dir / "share.json").read_text())
    assert share_manifest["name"] == "share-skill"
    assert share_manifest["source"] == "local:.asm/skills/share-skill"
    assert "SKILL.md" in share_manifest["files"]


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


@patch("asm.services.url_content.fetch_url_content")
@patch("asm.services.llm.generate_skill_content")
def test_create_skill_ai_writes_research_context_files(mock_gen, mock_fetch_url, initialized_workspace):
    """AI skill creation should materialize research into support files."""
    mock_gen.return_value = (
        "Short description",
        "# Short Skill\n\n## Supporting Files\n- `references/research-context.md`\n- `references/url-context.md`",
    )
    mock_fetch_url.return_value = "Fetched guide content."

    result = skills_service.create_skill(
        initialized_workspace,
        "research-skill",
        "Research-backed skill",
        use_llm=True,
        source_url="https://example.com/guide",
        deepwiki_context="# Repo Notes\n\nImportant API behavior.",
    )

    assert result.path.exists()
    research_file = result.path / "references" / "research-context.md"
    url_file = result.path / "references" / "url-context.md"
    assert research_file.exists()
    assert url_file.exists()
    assert "Repo Notes" in research_file.read_text()
    assert "Source: https://example.com/guide" in url_file.read_text()
    assert mock_gen.call_count == 1
    assert sorted(mock_gen.call_args[1]["supporting_files"]) == [
        "references/research-context.md",
        "references/url-context.md",
    ]


@patch("asm.services.llm.generate_support_file_content")
@patch("asm.services.llm.generate_skill_content")
def test_create_skill_ai_materializes_referenced_support_files_from_skill_md(
    mock_generate,
    mock_generate_support_file,
    initialized_workspace,
):
    """Generated SKILL.md should materialize referenced files even if loop stops early."""
    mock_generate.return_value = (
        "Short description with no triggers needed for this test.",
        "\n".join(
            [
                "# Skill",
                "## Niche Examples",
                "- Example: run the flow and capture an artifact.",
                "## Supporting Files",
                "- `references/overview.md`",
                "- `examples/cdp-attach.js`",
            ]
        ),
    )
    mock_generate_support_file.side_effect = [
        "# Overview\n\nConcrete support content.\n",
        "#!/usr/bin/env javascript\nconsole.log('cdp attach');\n",
    ]

    result = skills_service.create_skill(
        initialized_workspace,
        "materialize-skill",
        "Materialize skill description",
        use_llm=True,
        improvement_loop=False,
    )

    assert result.path.exists()
    assert (result.path / "references" / "overview.md").exists()
    assert (result.path / "examples" / "cdp-attach.js").exists()
    assert "Concrete support content." in (result.path / "references" / "overview.md").read_text()

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


@patch("asm.services.skills.create_skill")
def test_create_skill_verbose_streams_progress(mock_create, runner, initialized_workspace):
    """--verbose should print progress messages instead of only spinner updates."""
    def _fake_create(*args, **kwargs):
        on_progress = kwargs["on_progress"]
        on_progress("Scaffolding skill directory…")
        on_progress("Generating content with LLM…")
        return initialized_workspace / paths.ASM_DIR / paths.SKILLS_DIR / "verbose-skill"

    mock_create.side_effect = _fake_create

    result = runner.invoke(
        cli,
        [
            "create",
            "skill",
            "verbose-skill",
            "Desc",
            "--verbose",
            "--path",
            str(initialized_workspace),
        ],
    )

    assert result.exit_code == 0
    assert "Scaffolding skill directory…" in result.output
    assert "Generating content with LLM…" in result.output


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
@patch("asm.services.deepwiki.fetch_search_context")
def test_create_skill_loop_until_target(
    mock_fetch,
    mock_generate,
    mock_analyze,
    mock_revise,
    runner,
    initialized_workspace,
):
    """Test iterative build/analyze/rewrite during skill creation."""
    mock_fetch.return_value = ("Evidence context from DeepWiki.", [])
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
    assert mock_fetch.call_count == 1

    skill_md = (
        initialized_workspace / paths.ASM_DIR / paths.SKILLS_DIR / "loop-skill" / "SKILL.md"
    ).read_text()
    assert "Final Description" in skill_md
    assert "Final body" in skill_md


@patch("asm.services.llm.revise_skill_content")
@patch("asm.services.skill_analysis.analyze_skill_local")
@patch("asm.services.llm.generate_skill_content")
@patch("asm.services.deepwiki.fetch_search_context")
def test_create_skill_loop_stops_when_rewrite_is_empty(
    mock_fetch,
    mock_generate,
    mock_analyze,
    mock_revise,
    runner,
    initialized_workspace,
):
    """Empty rewrite output should stop the loop without failing skill creation."""
    mock_fetch.return_value = ("Evidence context from DeepWiki.", [])
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
    assert mock_fetch.call_count == 1
    skill_md = (
        initialized_workspace / paths.ASM_DIR / paths.SKILLS_DIR / "empty-rewrite-skill" / "SKILL.md"
    ).read_text()
    assert "Draft Description" in skill_md
    assert "Draft body" in skill_md


@patch("asm.services.llm.revise_skill_content")
@patch("asm.services.skill_analysis.analyze_skill_local")
@patch("asm.services.llm.generate_skill_content")
@patch("asm.services.deepwiki.fetch_search_context")
def test_create_skill_loop_materializes_research_when_evidence_low(
    mock_fetch,
    mock_generate,
    mock_analyze,
    mock_revise,
    runner,
    initialized_workspace,
):
    """If evidence grounding is low, the loop should fetch DeepWiki evidence and materialize it."""
    mock_fetch.return_value = ("# Evidence context from DeepWiki.\n\nSome useful docs.", [])
    mock_generate.return_value = ("Draft Description", "## Instructions\nDraft body")
    mock_revise.return_value = ("Final Description", "## Instructions\nFinal body")

    skill_name = "research-loop-skill"
    artifact_path = (
        initialized_workspace / ".asm" / "analysis" / skill_name / "latest.json"
    )

    research_actions = ["Add edge cases", "Clarify contracts"]
    expected_query = f"{skill_name} {' '.join(research_actions[:3])}".strip()

    def _response(score: float, prompt: str, *, status: str) -> SkillAnalysisResponse:
        duplication_risk = round(max(0.0, 1.0 - score), 2)
        return SkillAnalysisResponse(
            analysis_id=f"analysis-{score}",
            analysis_version="asm-local-llm-v1:openai/gpt-5-mini",
            scorecard=SkillScorecard(
                skill_name=skill_name,
                analysis_id=f"analysis-{score}",
                analysis_version="asm-local-llm-v1:openai/gpt-5-mini",
                trigger_specificity=score,
                novelty=score,
                evidence_grounding=score,
                duplication_risk=duplication_risk,
                status=status,
                recommended_actions=research_actions,
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
        (_response(0.4, "Evidence too weak; pull references.", status="needs_work"), artifact_path),
        (_response(0.95, "Good enough; stop now.", status="approved"), artifact_path),
    ]

    result = runner.invoke(
        cli,
        [
            "create",
            "skill",
            skill_name,
            "Research loop skill description",
            "--loop",
            "--target-score",
            "0.9",
            "--path",
            str(initialized_workspace),
        ],
    )

    assert result.exit_code == 0
    assert mock_fetch.call_count == 1
    assert mock_fetch.call_args.args[0] == expected_query
    assert mock_fetch.call_args.kwargs["limit"] == 3

    research_file = (
        initialized_workspace
        / paths.ASM_DIR
        / paths.SKILLS_DIR
        / skill_name
        / "references"
        / "research-iteration-1.md"
    )
    assert research_file.exists()
    assert "Evidence context (DeepWiki/GitHub)" in research_file.read_text(encoding="utf-8")

    supporting_files = mock_revise.call_args.kwargs.get("supporting_files", [])
    assert "references/research-iteration-1.md" in supporting_files


@patch("asm.services.llm.generate_support_file_content")
@patch("asm.services.llm.revise_skill_content")
@patch("asm.services.skill_analysis.analyze_skill_local")
@patch("asm.services.llm.generate_skill_content")
@patch("asm.services.deepwiki.fetch_search_context")
def test_create_skill_loop_materializes_missing_support_files_from_skill_md(
    mock_fetch,
    mock_generate,
    mock_analyze,
    mock_revise,
    mock_generate_support_file,
    runner,
    initialized_workspace,
):
    """If SKILL.md references support files that don't exist, the loop should create them."""
    mock_fetch.return_value = ("Evidence context from DeepWiki.", [])
    mock_generate.return_value = ("Draft Description", "## Instructions\nDraft body")

    revised_body = "\n".join(
        [
            "## Niche Examples",
            "- Example: attach via CDP, then take a DOM snapshot after navigating.",
            "",
            "## Supporting Files (add/update)",
            "- `references/cdp-checklist.md`",
            "- `examples/cdp-attach.js`",
        ]
    )

    mock_revise.return_value = ("Final Description", revised_body)
    mock_generate_support_file.side_effect = [
        "# CDP Checklist\n\nConcrete checklist.\n",
        "\n".join(
            [
                "#!/usr/bin/env node",
                "// Example: attach to a CDP target and enable core domains.",
                "const target = process.argv[2] || 'ws://127.0.0.1:9222/devtools/page/example';",
                "const events = [];",
                "const notes = [];",
                "events.push({ method: 'Page.enable' });",
                "events.push({ method: 'DOM.enable' });",
                "events.push({ method: 'Input.enable' });",
                "events.push({ method: 'Runtime.enable' });",
                "notes.push('connect to target');",
                "notes.push('enable domains');",
                "notes.push('navigate and capture');",
                "notes.push('write artifacts');",
                "console.log('cdp example start');",
                "console.log(JSON.stringify({ target, events }, null, 2));",
                "console.log(JSON.stringify({ notes }, null, 2));",
                "",
            ]
        ),
    ]

    artifact_path = initialized_workspace / ".asm" / "analysis" / "support-files-loop" / "latest.json"

    def _response(score: float, prompt: str, *, status: str) -> SkillAnalysisResponse:
        duplication_risk = round(max(0.0, 1.0 - score), 2)
        return SkillAnalysisResponse(
            analysis_id=f"analysis-{score}",
            analysis_version="asm-local-llm-v1:openai/gpt-5-mini",
            scorecard=SkillScorecard(
                skill_name="support-files-loop",
                analysis_id=f"analysis-{score}",
                analysis_version="asm-local-llm-v1:openai/gpt-5-mini",
                trigger_specificity=score,
                novelty=score,
                evidence_grounding=score,
                duplication_risk=duplication_risk,
                status=status,
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
        (_response(0.8, "Improve support files materialization.", status="needs_work"), artifact_path),
        (_response(1.0, "Done.", status="approved"), artifact_path),
    ]

    result = runner.invoke(
        cli,
        [
            "create",
            "skill",
            "support-files-loop",
            "Support files loop skill description",
            "--loop",
            "--target-score",
            "0.9",
            "--path",
            str(initialized_workspace),
        ],
    )

    assert result.exit_code == 0

    skill_dir = initialized_workspace / paths.ASM_DIR / paths.SKILLS_DIR / "support-files-loop"
    assert (skill_dir / "references" / "cdp-checklist.md").exists()
    assert (skill_dir / "examples" / "cdp-attach.js").exists()
    assert "Concrete checklist." in (skill_dir / "references" / "cdp-checklist.md").read_text()


@patch("asm.services.llm.generate_support_file_content")
@patch("asm.services.skill_analysis.analyze_skill_local")
@patch("asm.services.llm.generate_skill_content")
def test_create_skill_loop_quality_gate_blocks_placeholder_support_files(
    mock_generate,
    mock_analyze,
    mock_generate_support_file,
    runner,
    initialized_workspace,
):
    """High analyzer scores should still fail the loop when support files are placeholder garbage."""
    mock_generate.return_value = (
        "Draft Description",
        "\n".join(
            [
                "## Niche Examples",
                "- Example: launch browser and capture one screenshot.",
                "",
                "## Supporting Files",
                "- `references/overview.md`",
            ]
        ),
    )
    mock_generate_support_file.return_value = (
        "# Overview\n\n"
        "Generated by ASM as a minimal, evidence-backed usage file.\n"
        "Edit/extend this file as you refine the skill.\n"
        "placeholder\n"
    )

    artifact_path = initialized_workspace / ".asm" / "analysis" / "quality-gate-skill" / "latest.json"
    response = SkillAnalysisResponse(
        analysis_id="analysis-quality-gate",
        analysis_version="asm-local-llm-v1:openai/gpt-5-mini",
        scorecard=SkillScorecard(
            skill_name="quality-gate-skill",
            analysis_id="analysis-quality-gate",
            analysis_version="asm-local-llm-v1:openai/gpt-5-mini",
            trigger_specificity=1.0,
            novelty=1.0,
            evidence_grounding=1.0,
            duplication_risk=0.0,
            status="approved",
            improvement_prompt="Looks good at a glance.",
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
            "quality-gate-skill",
            "Quality gate skill",
            "--loop",
            "--target-score",
            "0.9",
            "--max-tries",
            "1",
            "--path",
            str(initialized_workspace),
        ],
    )

    assert result.exit_code == 0
    assert "Loop status: stopped before target" in result.output
    assert "Loop stop reason: quality_gate_failed" in result.output
