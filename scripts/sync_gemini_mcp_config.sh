#!/usr/bin/env bash
set -euo pipefail

TARGET_HOME="${TARGET_HOME:-${1:-$HOME}}"

python3 - "$TARGET_HOME" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path


OPEN_CROW_MCP_SERVERS = [
    "opencrow-crypto-mcp",
    "opencrow-forensics-mcp",
    "opencrow-minecraft-mcp",
    "opencrow-netcat-mcp",
    "opencrow-network-mcp",
    "opencrow-osint-mcp",
    "opencrow-pwn-mcp",
    "opencrow-reversing-mcp",
    "opencrow-ssh-mcp",
    "opencrow-stego-mcp",
    "opencrow-utility-mcp",
    "opencrow-web-mcp",
]
TIMEOUT_MS = 20_000


def load_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected a JSON object in {path}, got {type(payload).__name__}.")
    return payload


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict[str, object]) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def installed_opencrow_mcp_servers(target_home: Path) -> list[str]:
    bin_dir = target_home / ".local" / "bin"
    return [server_name for server_name in OPEN_CROW_MCP_SERVERS if (bin_dir / server_name).exists()]


def build_server_entry(target_home: Path, server_name: str) -> dict[str, object]:
    command_path = target_home / ".local" / "bin" / server_name
    if not command_path.exists():
        raise SystemExit(f"Required OpenCROW MCP command is missing: {command_path}")
    return {
        "command": str(command_path),
        "description": f"OpenCROW managed MCP server for {server_name}.",
        "timeout": TIMEOUT_MS,
    }


def sync_settings_payload(payload: dict[str, object], target_home: Path) -> dict[str, object]:
    output = dict(payload)
    mcp_servers = output.get("mcpServers")
    if not isinstance(mcp_servers, dict):
        mcp_servers = {}
    else:
        mcp_servers = {
            key: value
            for key, value in dict(mcp_servers).items()
            if key not in OPEN_CROW_MCP_SERVERS
        }

    for server_name in installed_opencrow_mcp_servers(target_home):
        mcp_servers[server_name] = build_server_entry(target_home, server_name)

    output["mcpServers"] = mcp_servers
    return output


target_home = Path(sys.argv[1]).expanduser().resolve()
gemini_settings_path = target_home / ".gemini" / "settings.json"
antigravity_config_path = target_home / ".gemini" / "antigravity" / "mcp_config.json"
installed_servers = installed_opencrow_mcp_servers(target_home)

settings_payload = sync_settings_payload(load_json(gemini_settings_path), target_home)
write_json(gemini_settings_path, settings_payload)
print(f"Synced {len(installed_servers)} OpenCROW MCP entries into {gemini_settings_path}")

# Keep the existing Antigravity-side MCP file aligned when that Gemini extension data exists.
if antigravity_config_path.parent.exists() or antigravity_config_path.exists():
    antigravity_payload = sync_settings_payload(load_json(antigravity_config_path), target_home)
    write_json(antigravity_config_path, antigravity_payload)
    print(f"Synced {len(installed_servers)} OpenCROW MCP entries into {antigravity_config_path}")
PY
