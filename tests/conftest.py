import pytest
from pathlib import Path
from click.testing import CliRunner
from asm.cli import cli

@pytest.fixture
def runner():
    """Click CLI runner fixture."""
    return CliRunner()

@pytest.fixture
def tmp_workspace(tmp_path: Path):
    """Fixture for a temporary workspace directory."""
    return tmp_path

@pytest.fixture
def initialized_workspace(runner, tmp_workspace):
    """Fixture for a workspace that is already initialized."""
    result = runner.invoke(cli, ["init", "--path", str(tmp_workspace)])
    assert result.exit_code == 0
    return tmp_workspace
