from unittest.mock import patch, MagicMock
from asm.cli import cli
from asm.services.skills import SyncResult

@patch("asm.services.skills.sync_workspace")
def test_sync(mock_sync, runner, initialized_workspace):
    """Test sync command."""
    mock_sync.return_value = SyncResult(
        installed=["skill1"],
        up_to_date=["skill2"],
        integrity_ok=["skill3"],
        integrity_drift=[],
        failed=[],
        removed_from_lock=[]
    )
    
    result = runner.invoke(cli, ["sync", "--path", str(initialized_workspace)])
    assert result.exit_code == 0
    assert "✔ Synced 3 skill(s)" in result.output
