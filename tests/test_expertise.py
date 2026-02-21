from unittest.mock import patch, MagicMock
from asm.cli import cli
from asm.core import paths

def test_create_expertise(runner, initialized_workspace):
    """Test that creating an expertise bundle works."""
    # First create some skills
    runner.invoke(cli, ["create", "skill", "skill1", "Desc 1", "--path", str(initialized_workspace)])
    runner.invoke(cli, ["create", "skill", "skill2", "Desc 2", "--path", str(initialized_workspace)])
    
    result = runner.invoke(cli, [
        "create", "expertise", "test-exp", "skill1", "skill2", 
        "--desc", "Expertise description", 
        "--path", str(initialized_workspace)
    ])
    
    assert result.exit_code == 0
    assert "✔ Created expertise: test-exp" in result.output
    
    exp_dir = initialized_workspace / paths.ASM_DIR / "expertises" / "test-exp"
    assert exp_dir.exists()
    assert (exp_dir / "index.md").exists()

@patch("asm.services.expertise.suggest")
def test_expertise_suggest(mock_suggest, runner, initialized_workspace):
    """Test expertise suggestion command."""
    mock_suggest.return_value = [("test-exp", 0.85)]
    
    result = runner.invoke(cli, ["expertise", "suggest", "task", "--path", str(initialized_workspace)])
    assert result.exit_code == 0
    assert "Matching expertises for: \"task\"" in result.output
    assert "test-exp" in result.output

@patch("asm.services.expertise.auto")
def test_expertise_auto(mock_auto, runner, initialized_workspace):
    """Test expertise auto command."""
    mock_auto.return_value = ("auto-exp", ["skill1"])
    
    result = runner.invoke(cli, ["expertise", "auto", "task", "--path", str(initialized_workspace)])
    assert result.exit_code == 0
    assert "✔ Expertise: auto-exp" in result.output
