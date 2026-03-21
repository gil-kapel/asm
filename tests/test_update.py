from unittest.mock import MagicMock, patch

from asm.cli import cli


@patch("subprocess.run")
def test_update(mock_run, runner):
    """Test that asm update prefers the wheel path when install succeeds."""
    mock_run.side_effect = [
        MagicMock(returncode=0),
        MagicMock(returncode=0),
    ]

    result = runner.invoke(cli, ["update"])

    assert result.exit_code == 0
    assert "✔ Updated asm from official release wheel" in result.output
    assert mock_run.call_count == 2


@patch("subprocess.run")
def test_update_falls_back_to_git(mock_run, runner):
    """Test that asm update falls back to git when the wheel install fails."""
    mock_run.side_effect = [
        MagicMock(returncode=0),
        MagicMock(returncode=1),
        MagicMock(returncode=0),
    ]

    result = runner.invoke(cli, ["update"])

    assert result.exit_code == 0
    assert "Updating from source (git)" in result.output
    assert "✔ Updated asm from source (git)" in result.output
    assert mock_run.call_count == 3
