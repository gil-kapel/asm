from unittest.mock import patch, MagicMock
from asm.cli import cli
from asm.core.models import LockEntry
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
