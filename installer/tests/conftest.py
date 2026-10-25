from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Mock fidelity: each behavior below was observed on Claude Code 2.1.307 with a
# throwaway HOME, so the installer is tested against what the real CLI does:
#   * user-scope servers are stored under top-level "mcpServers" in $HOME/.claude.json
#     and every other key is preserved;
#   * `add-json` with an existing name exits 1 and does NOT overwrite;
#   * `remove` of a missing name exits 1;
#   * an unparseable .claude.json makes the CLI exit 1 AFTER replacing the file with a
#     fresh config, destroying its content.
# FAKE_CLAUDE_NOOP=1 instead models a `claude` that exits 0 for anything without
# writing (the shims used by scripts/test_installation_e2e.sh, or a wrapper).
FAKE_CLAUDE = r'''#!@PYTHON@
import json, os, sys
from pathlib import Path

args = sys.argv[1:]
with open(os.environ["FAKE_CLAUDE_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"args": args, "home": os.environ.get("HOME"),
                          "claude_config_dir": os.environ.get("CLAUDE_CONFIG_DIR")}) + "\n")
if args == ["--version"]:
    print("2.1.307 (Claude Code)")
    sys.exit(0)
if os.environ.get("FAKE_CLAUDE_NOOP"):
    # Same as the provider shims in scripts/test_*.sh: success, nothing persisted.
    print("claude 99.0.0")
    sys.exit(0)
config = Path(os.environ["HOME"]) / ".claude.json"
try:
    data = json.loads(config.read_text()) if config.exists() else {}
except ValueError:
    config.write_text(json.dumps({"fresh": True}))
    sys.exit(1)
servers = data.setdefault("mcpServers", {})
if args[:3] == ["mcp", "add-json", "--scope"] and args[3] == "user":
    name, spec = args[4], json.loads(args[5])
    if os.environ.get("FAKE_CLAUDE_FAIL_ADD"):
        print("simulated failure", file=sys.stderr)
        sys.exit(1)
    if name in servers:
        print(f"MCP server {name} already exists in user config", file=sys.stderr)
        sys.exit(1)
    servers[name] = spec
elif args[:3] == ["mcp", "remove", "--scope"] and args[3] == "user":
    if args[4] not in servers:
        print(f"No user-scoped MCP server found with name: {args[4]}", file=sys.stderr)
        sys.exit(1)
    del servers[args[4]]
else:
    print(f"unsupported: {args}", file=sys.stderr)
    sys.exit(2)
config.write_text(json.dumps(data))
'''


@pytest.fixture(autouse=True)
def fake_claude_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep every installer test hermetic: the real `claude` on the developer's
    PATH must never run against a test home. Returns the invocation log."""
    bin_dir = tmp_path / "fake-claude-bin"
    bin_dir.mkdir()
    executable = bin_dir / "claude"
    executable.write_text(FAKE_CLAUDE.replace("@PYTHON@", sys.executable))
    executable.chmod(0o755)
    log = tmp_path / "fake-claude.log"
    log.touch()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "must-be-ignored"))
    return log
