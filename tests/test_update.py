from unittest.mock import patch, MagicMock
from asm.cli import cli

@patch("subprocess.run")
def test_update(mock_run, runner):
    """Test that asm update attempts to uninstall and reinstall via uv."""
    result = runner.invoke(cli, ["update"])
    assert result.exit_code == 0
    assert "✔ Updated asm" in result.output
    assert mock_run.call_count == 2
