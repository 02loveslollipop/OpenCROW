#!/usr/bin/env python3
"""Verify OpenCROW utility tools."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))
from python_runtime import system_tools_available


SYSTEM_TOOLS = [
    "opencrow-utility-mcp",
    "jq",
    "yq",
    "xxd",
    "tmux",
    "screen",
    "rg",
    "fzf",
    "opencrow",
    "opencrow-lifecycle-mcp",
    "opencrow-netcat-mcp",
    "opencrow-ssh-mcp",
    "opencrow-minecraft-mcp",
]


def main() -> int:
    payload = {
        "system_tools": system_tools_available(SYSTEM_TOOLS)
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
