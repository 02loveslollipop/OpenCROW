#!/usr/bin/env python3
"""Smoke test the public OpenCROW stego MCP surface against missing file errors."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import opencrow_stego_mcp as stego_mcp

def main() -> int:
    server = stego_mcp.build_server()
    stego_inspect_handler = server.tools["stego_inspect"].handler

    arguments = {"path": "/path/to/nonexistent/file.txt"}
    result = stego_inspect_handler(arguments)

    if result.get("ok"):
        print("Test failed: Expected error for missing file, got success.")
        return 1

    if "Input file does not exist" not in result.get("summary", ""):
        print(f"Test failed: Expected 'Input file does not exist' in summary, got: {result.get('summary')}")
        return 1

    if result.get("exit_code") != 2:
        print(f"Test failed: Expected exit_code 2, got: {result.get('exit_code')}")
        return 1

    print("Test passed: stego_inspect handles missing files correctly.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
