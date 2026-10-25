#!/usr/bin/env python3
"""Run or generate opt-in agent configuration for vendored OpenCROW MCP servers."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "core"))
from opencrow_ctf_mcp_common import python_command

SERVERS = ("crypto", "forensics", "network", "osint", "pwn", "reversing", "stego", "utility", "web", "netcat", "ssh", "minecraft", "agy", "worker")


def configuration(provider: str, servers: list[str], skills_root: Path | None = None) -> str:
    entries = {}
    for name in servers:
        entry = {"command": sys.executable, "args": [str(Path(__file__).resolve()), "serve", name]}
        if skills_root:
            entry["env"] = {"OPENCROW_SKILLS_ROOT": str(skills_root.resolve())}
        entries[f"opencrow-{name}"] = entry
    if provider == "codex":
        lines = []
        for name, entry in entries.items():
            lines.extend([f"[mcp_servers.{name}]", f"command = {json.dumps(entry['command'])}", f"args = {json.dumps(entry['args'])}"])
            if entry.get("env"):
                lines.extend([f"[mcp_servers.{name}.env]", f"OPENCROW_SKILLS_ROOT = {json.dumps(entry['env']['OPENCROW_SKILLS_ROOT'])}"])
            lines.append("")
        return "\n".join(lines)
    if provider in {"opencode", "opencode-v2"}:
        entries = {name: {"type": "local", "command": [entry["command"], *entry["args"]], **({"environment": entry["env"]} if "env" in entry else {})} for name, entry in entries.items()}
        return json.dumps({"mcp": {"servers": entries} if provider == "opencode-v2" else entries}, indent=2) + "\n"
    return json.dumps({"mcpServers": entries}, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("server", choices=SERVERS)
    config = sub.add_parser("config", help="Print a fragment; existing agent configuration is never overwritten")
    config.add_argument("--provider", choices=("opencode", "opencode-v2", "codex", "claude", "antigravity"), required=True)
    config.add_argument("--servers", nargs="+", choices=SERVERS, required=True)
    config.add_argument("--skills-root", type=Path)
    args = parser.parse_args()
    if args.action == "config":
        print(configuration(args.provider, args.servers, args.skills_root), end="")
        return 0
    command = python_command()
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "core"), str(ROOT / "servers"), env.get("PYTHONPATH", "")])
    # pip-installed console scripts must be discoverable by toolbox_verify too.
    executable = Path(command[0])
    if executable.is_file():
        env["PATH"] = str(executable.absolute().parent) + os.pathsep + env.get("PATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    os.execvpe(command[0], [*command, str(ROOT / "servers" / f"opencrow_{args.server}_mcp.py")], env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
