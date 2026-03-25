from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import click

from asm.cli import cli
from asm.cli import commands as command_module
from asm.core.models import EmbeddingProfile, LockEntry, SkillAnalysisResponse, SkillScorecard
from asm.repo import lockfile, snapshots
from asm.services.skills import SkillWorkingStatus

@patch("asm.services.skills.skill_commit")
def test_skill_commit(mock_commit, runner, initialized_workspace):
    mock_commit.return_value = LockEntry(local_revision=1, snapshot_id="snap1")
    result = runner.invoke(cli, ["skill", "commit", "test-skill", "-m", "msg", "--path", str(initialized_workspace)])
    assert result.exit_code == 0
    assert "✔ Committed test-skill r1" in result.output

@patch("asm.services.skills.skill_stash_push")
def test_skill_stash_push(mock_push, runner, initialized_workspace):
    mock_push.return_value = "stash1"
    result = runner.invoke(cli, ["skill", "stash", "push", "test-skill", "-m", "msg", "--path", str(initialized_workspace)])
    assert result.exit_code == 0
    assert "✔ Stashed test-skill: stash1" in result.output

@patch("asm.services.skills.skill_stash_apply")
def test_skill_stash_apply(mock_apply, runner, initialized_workspace):
    mock_apply.return_value = LockEntry(local_revision=1, snapshot_id="snap1")
    result = runner.invoke(cli, ["skill", "stash", "apply", "test-skill", "--path", str(initialized_workspace)])
    assert result.exit_code == 0
    assert "✔ Applied stash to test-skill" in result.output

@patch("asm.services.skills.skill_status")
def test_skill_status(mock_status, runner, initialized_workspace):
    mock_status.return_value = SkillWorkingStatus(
        name="test-skill", 
        snapshot_id="snap1", 
        added=["file1.txt"], 
        modified=[], 
        removed=[]
    )
    result = runner.invoke(cli, ["skill", "status", "test-skill", "--path", str(initialized_workspace)])
    assert result.exit_code == 0
    assert "A  file1.txt" in result.output

@patch("asm.services.skills.skill_tag")
def test_skill_tag(mock_tag, runner, initialized_workspace):
    mock_tag.return_value = "snap1"
    result = runner.invoke(cli, ["skill", "tag", "test-skill", "v1", "--path", str(initialized_workspace)])
    assert result.exit_code == 0
    assert "✔ Tagged test-skill:v1 -> snap1" in result.output

@patch("asm.services.skills.skill_checkout")
def test_skill_checkout(mock_checkout, runner, initialized_workspace):
    mock_checkout.return_value = LockEntry(local_revision=1, snapshot_id="snap1")
    result = runner.invoke(cli, ["skill", "checkout", "test-skill", "v1", "--path", str(initialized_workspace)])
    assert result.exit_code == 0
    assert "✔ Checked out test-skill -> snap1" in result.output

@patch("asm.services.skills.skill_history")
def test_skill_history(mock_history, runner, initialized_workspace):
    mock_history.return_value = [{"created_at": "2024-01-01", "kind": "commit", "local_revision": 1, "snapshot_id": "snap1", "message": "msg"}]
    result = runner.invoke(cli, ["skill", "history", "test-skill", "--path", str(initialized_workspace)])
    assert result.exit_code == 0
    assert "r1 snap1 - msg" in result.output

@patch("asm.services.skills.skill_diff")
def test_skill_diff(mock_diff, runner, initialized_workspace):
    mock_diff.return_value = "diff text"
    result = runner.invoke(cli, ["skill", "diff", "test-skill", "--path", str(initialized_workspace)])
    assert result.exit_code == 0
    assert "diff text" in result.output


@patch("asm.services.skill_analysis.analyze_skill_cloud")
def test_skill_analyze_cloud(mock_analyze, runner, initialized_workspace):
    mock_analyze.return_value = (
        SkillAnalysisResponse(
            analysis_id="analysis-1",
            analysis_version="asm-cloud-mvp-v1",
            scorecard=SkillScorecard(
                skill_name="test-skill",
                analysis_id="analysis-1",
                analysis_version="asm-cloud-mvp-v1",
                trigger_specificity=0.91,
                novelty=0.82,
                evidence_grounding=0.77,
                duplication_risk=0.24,
                status="approved",
                improvement_prompt="Rewrite the cloud skill description.",
            ),
            embedding_profile=EmbeddingProfile(
                provider="openai",
                model="text-embedding-3-small",
                dimension=1536,
                normalized=False,
                distance_metric="cosine",
                embedding_version="openai:text-embedding-3-small:1536:cosine:norm=false",
                analysis_mode="cloud",
            ),
        ),
        Path("/tmp/latest.json"),
    )
    result = runner.invoke(
        cli,
        [
            "skill",
            "analyze",
            "test-skill",
            "--cloud",
            "--api-url",
            "http://127.0.0.1:8000",
            "--path",
            str(initialized_workspace),
        ],
    )
    assert result.exit_code == 0
    assert "✔ Analyzed test-skill" in result.output
    assert "mode: cloud" in result.output
    assert "status: approved" in result.output
    assert "improvement_prompt:" in result.output
    assert "Rewrite the cloud skill description." in result.output
    assert "analysis_id: analysis-1" in result.output
    assert mock_analyze.call_args.kwargs["api_url"] == "http://127.0.0.1:8000"


@patch("asm.services.skill_analysis.analyze_skill_local")
def test_skill_analyze_local(mock_analyze, runner, initialized_workspace):
    mock_analyze.return_value = (
        SkillAnalysisResponse(
            analysis_id="local-analysis-1",
            analysis_version="asm-local-llm-v1:openai/gpt-5-mini",
            scorecard=SkillScorecard(
                skill_name="test-skill",
                analysis_id="local-analysis-1",
                analysis_version="asm-local-llm-v1:openai/gpt-5-mini",
                trigger_specificity=0.73,
                novelty=0.69,
                evidence_grounding=0.80,
                duplication_risk=0.31,
                status="needs_work",
                improvement_prompt="Tighten the local skill boundary.",
            ),
            embedding_profile=EmbeddingProfile(
                provider="openai",
                model="text-embedding-3-small",
                dimension=1536,
                normalized=False,
                distance_metric="cosine",
                embedding_version="openai:text-embedding-3-small:1536:cosine:norm=false",
                analysis_mode="local-llm",
            ),
        ),
        Path("/tmp/local-latest.json"),
    )
    result = runner.invoke(
        cli,
        [
            "skill",
            "analyze",
            "test-skill",
            "--local",
            "--model",
            "openai/gpt-5-mini",
            "--path",
            str(initialized_workspace),
        ],
    )
    assert result.exit_code == 0
    assert "✔ Analyzed test-skill" in result.output
    assert "mode: local-llm" in result.output
    assert "status: needs_work" in result.output
    assert "model: openai/gpt-5-mini" in result.output
    assert "improvement_prompt:" in result.output
    assert "Tighten the local skill boundary." in result.output
    assert mock_analyze.call_args.kwargs["model"] == "openai/gpt-5-mini"


def test_skill_name_completion_reads_workspace(runner, initialized_workspace):
    runner.invoke(cli, ["create", "skill", "alpha-skill", "Desc", "--path", str(initialized_workspace)])
    runner.invoke(cli, ["create", "skill", "beta-skill", "Desc", "--path", str(initialized_workspace)])

    ctx = SimpleNamespace(params={"root": str(initialized_workspace)})
    items = command_module._complete_installed_skills(ctx, click.Argument(["name"]), "a")

    assert [item.value for item in items] == ["alpha-skill"]


def test_expertise_completion_reads_workspace(runner, initialized_workspace):
    runner.invoke(cli, ["create", "skill", "skill1", "Desc 1", "--path", str(initialized_workspace)])
    runner.invoke(cli, ["create", "skill", "skill2", "Desc 2", "--path", str(initialized_workspace)])
    runner.invoke(
        cli,
        ["create", "expertise", "test-exp", "skill1", "skill2", "--desc", "Expertise description", "--path", str(initialized_workspace)],
    )

    ctx = SimpleNamespace(params={"root": str(initialized_workspace)})
    items = command_module._complete_expertises(ctx, click.Argument(["expertise_name"]), "test")

    assert [item.value for item in items] == ["test-exp"]


def test_skill_ref_and_stash_completion(runner, initialized_workspace):
    runner.invoke(cli, ["create", "skill", "ref-skill", "Desc", "--path", str(initialized_workspace)])
    current = lockfile.load(initialized_workspace / "asm.lock")["ref-skill"]
    snapshots.tag_snapshot(initialized_workspace, "ref-skill", "stable", current.snapshot_id)
    snapshots.stash_push(
        initialized_workspace,
        "ref-skill",
        snapshot_id=current.snapshot_id,
        message="wip",
        author="tester",
    )

    ctx = SimpleNamespace(params={"root": str(initialized_workspace), "name": "ref-skill"})
    ref_items = command_module._complete_skill_refs(ctx, click.Argument(["ref"]), "st")
    stash_items = command_module._complete_stash_ids(ctx, click.Argument(["stash_id"]), "")

    assert [item.value for item in ref_items] == ["stable"]
    assert len(stash_items) == 1
