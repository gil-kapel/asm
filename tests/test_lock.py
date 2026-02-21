from unittest.mock import patch
from asm.cli import cli

@patch("asm.repo.lockfile.migrate")
def test_lock_migrate(mock_migrate, runner, initialized_workspace):
    mock_migrate.return_value = True
    result = runner.invoke(cli, ["lock", "migrate", "--path", str(initialized_workspace)])
    assert result.exit_code == 0
    assert "✔ Migrated asm.lock" in result.output
    mock_migrate.assert_called_once()
