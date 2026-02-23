from unittest.mock import patch, MagicMock
from pathlib import Path
from asm.cli import cli
from asm.core import paths
from asm.core.models import SkillMeta

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

@patch("asm.services.llm.generate_skill_content")
@patch("asm.services.llm._ensure_litellm")
def test_create_skill_ai(mock_ensure, mock_gen, runner, initialized_workspace):
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
