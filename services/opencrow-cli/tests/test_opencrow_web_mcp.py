import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from opencrow_web_mcp import web_fuzz

def test_web_fuzz_missing_url_empty_dict():
    """Test web_fuzz returns an error when target_url is not provided."""
    arguments = {}
    result = web_fuzz(arguments)
    assert result.get("operation") == "web_fuzz"
    assert result.get("summary") == "Target URL is required."

def test_web_fuzz_missing_url_whitespace():
    """Test web_fuzz returns an error when target_url is only whitespace."""
    arguments = {"target_url": "   \n\t"}
    result = web_fuzz(arguments)
    assert result.get("operation") == "web_fuzz"
    assert result.get("summary") == "Target URL is required."
