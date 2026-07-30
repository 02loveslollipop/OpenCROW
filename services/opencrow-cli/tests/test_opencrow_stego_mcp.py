#!/usr/bin/env python3
"""Tests for OpenCROW stego MCP server."""

import sys
import unittest
from pathlib import Path

# Add the scripts directory to the path so we can import modules from it
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from opencrow_stego_mcp import stego_inspect


class TestStegoMCP(unittest.TestCase):
    def test_stego_inspect_missing_file(self):
        """Test that inspecting a nonexistent file returns the correct error envelope."""
        arguments = {"path": "/path/to/nonexistent/file"}
        result = stego_inspect(arguments)

        self.assertEqual(result.get("operation"), "stego_inspect")
        self.assertTrue("Input file does not exist" in result.get("summary", ""))
        self.assertEqual(result.get("exit_code"), 2)
        self.assertIn("stderr", result)
        self.assertTrue("Missing file:" in result.get("stderr", ""))

if __name__ == "__main__":
    unittest.main()
