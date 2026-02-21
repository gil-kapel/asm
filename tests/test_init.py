from pathlib import Path
from asm.cli import cli
from asm.core import paths

def test_init_creates_files(runner, tmp_workspace):
    """Test that asm init creates the expected files."""
    result = runner.invoke(cli, ["init", "--path", str(tmp_workspace)])
    assert result.exit_code == 0
    assert "✔ Initialised ASM workspace" in result.output
    
    assert (tmp_workspace / paths.ASM_TOML).exists()
    assert (tmp_workspace / paths.ASM_DIR).exists()
    assert (tmp_workspace / paths.ASM_DIR / paths.MAIN_ASM_MD).exists()

def test_init_fail_if_already_initialized(runner, initialized_workspace):
    """Test that asm init fails if already initialized."""
    result = runner.invoke(cli, ["init", "--path", str(initialized_workspace)])
    assert result.exit_code != 0
    assert "already initialised" in result.output
