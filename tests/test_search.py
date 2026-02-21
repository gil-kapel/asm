from unittest.mock import patch, MagicMock
from asm.cli import cli
from asm.core.models import DiscoveryItem

@patch("asm.services.discovery.search")
def test_search_display(mock_search, runner, initialized_workspace):
    """Test that search displays results correctly."""
    mock_search.return_value = [
        DiscoveryItem(
            provider="asm-index",
            identifier="test-skill",
            name="Test Skill",
            description="A test skill",
            url="https://example.com",
            install_source="test:skill",
            score=0.9
        )
    ]
    
    result = runner.invoke(cli, ["search", "test", "--path", str(initialized_workspace)])
    assert result.exit_code == 0
    assert "Found 1 result(s)" in result.output
    assert "[asm-index] Test Skill" in result.output
    assert "id: test-skill" in result.output

def test_search_limit_invalid(runner):
    """Test that search fails with invalid limit."""
    result = runner.invoke(cli, ["search", "test", "--limit", "0"])
    assert result.exit_code != 0
    assert "--limit must be >= 1" in result.output
