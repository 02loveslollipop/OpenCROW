#!/usr/bin/env python3
"""Verify one installed skills bundle and its trusted provider runtime adapter."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


EXPECTED_MCP_TOOLS = {
    "workflow_status",
    "workflow_read",
    "workflow_record_attempt",
    "workflow_record_finding",
    "workflow_add_clarification",
    "workflow_update_handoff",
    "workflow_writeup",
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"Expected a JSON object: {path}")
    return value


def run_json(command: list[str], *, environment: dict[str, str], input_text: str | None = None) -> dict[str, Any]:
    process = subprocess.run(
        command,
        input=input_text,
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )
    if process.returncode != 0:
        raise AssertionError(
            f"Command failed ({process.returncode}): {' '.join(command)}\n{process.stdout}\n{process.stderr}"
        )
    value = json.loads(process.stdout)
    if not isinstance(value, dict):
        raise AssertionError(f"Expected JSON object from {' '.join(command)}")
    return value


def verify_mcp(bin_dir: Path, workspace: Path, environment: dict[str, str], expected_version: str) -> None:
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        },
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "workflow_status", "arguments": {"workspace": str(workspace)}},
        },
    ]
    process = subprocess.run(
        [str(bin_dir / "opencrow-lifecycle-mcp"), "--workspace", str(workspace)],
        input="\n".join(json.dumps(request) for request in requests) + "\n",
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )
    if process.returncode != 0:
        raise AssertionError(f"Installed lifecycle MCP failed: {process.stderr}")
    responses = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
    if len(responses) != 3:
        raise AssertionError(f"Expected three MCP responses, received {len(responses)}")
    server_version = responses[0]["result"]["serverInfo"]["version"]
    if server_version != expected_version:
        raise AssertionError(f"MCP version {server_version} does not match {expected_version}")
    tools = {item["name"] for item in responses[1]["result"]["tools"]}
    if tools != EXPECTED_MCP_TOOLS:
        raise AssertionError(f"Unexpected lifecycle MCP tools: {sorted(tools)}")
    status_result = responses[2]["result"]
    if status_result.get("isError"):
        raise AssertionError(f"workflow_status failed: {status_result}")
    status = json.loads(status_result["content"][0]["text"])
    if status.get("phase") != "reconnaissance":
        raise AssertionError(f"Unexpected installed workflow phase: {status.get('phase')}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True, choices=("codex", "opencode", "claude", "antigravity"))
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--repository", required=True, type=Path)
    args = parser.parse_args()

    runtime_root = args.runtime_root.resolve()
    repository = args.repository.resolve()
    home = runtime_root / "home"
    data = runtime_root / "data" / "opencrow"
    state_path = runtime_root / "state" / "opencrow" / "state.json"
    bin_dir = home / ".local" / "bin"
    current = data / "current"
    environment = os.environ.copy()
    environment.update(
        {
            "OPENCROW_TARGET_HOME": str(home),
            "OPENCROW_BIN_DIR": str(bin_dir),
            "XDG_DATA_HOME": str(runtime_root / "data"),
            "XDG_STATE_HOME": str(runtime_root / "state"),
            "XDG_CONFIG_HOME": str(runtime_root / "config"),
            "PATH": f"{bin_dir}:{environment['PATH']}",
        }
    )

    state = load_json(state_path)
    release = load_json(current / "release-manifest.json")
    version_match = re.match(r"^(\d+\.\d+\.\d+)", str(release.get("version", "")))
    if not version_match:
        raise AssertionError("Installed release manifest does not contain a SemVer version")
    expected_version = version_match.group(1)
    if state.get("version") != expected_version or state.get("install_mode") != "skills":
        raise AssertionError("Installed desired state does not match the skills release")
    if state.get("selected_agents") != [args.provider]:
        raise AssertionError(f"Runtime selected unexpected providers: {state.get('selected_agents')}")

    doctor = run_json([str(bin_dir / "opencrow"), "doctor"], environment=environment)
    integrations = run_json(
        [str(bin_dir / "opencrow"), "integrations", "list"], environment=environment
    )["integrations"]
    selected = next(item for item in integrations if item["provider"] == args.provider)
    if not doctor.get("ok") or doctor.get("mode") != "skills" or doctor.get("version") != expected_version:
        raise AssertionError(f"Installed doctor check failed: {doctor}")
    if not selected.get("selected") or not selected.get("available") or not selected.get("healthy"):
        raise AssertionError(f"Installed provider integration is unhealthy: {selected}")
    if selected.get("compatibility") == "incompatible":
        raise AssertionError(f"Installed provider is incompatible: {selected}")

    integration_manifest = load_json(current / "integrations" / "manifest.json")
    specification = integration_manifest["providers"][args.provider]
    source_skills = {
        path.parent.name for path in (current / "skills").glob("*/SKILL.md") if path.is_file()
    }
    skills_dir = home / specification["skills_dir"]
    installed_skills = {path.parent.name for path in skills_dir.glob("*/SKILL.md") if path.is_file()}
    if not source_skills or installed_skills != source_skills:
        raise AssertionError(
            f"Installed skills differ for {args.provider}: expected={sorted(source_skills)} "
            f"actual={sorted(installed_skills)}"
        )
    if selected.get("skill_count") != len(source_skills):
        raise AssertionError(f"Doctor reported the wrong skill count: {selected}")

    for key in ("config", "hooks", "plugin", "mcp_config"):
        relative = specification.get(key)
        if not relative:
            continue
        configured = home / relative
        if not configured.is_file() or "opencrow-lifecycle" not in configured.read_text(encoding="utf-8"):
            raise AssertionError(f"Missing lifecycle registration for {args.provider}: {configured}")

    for launcher in ("opencrow", "opencrow-lifecycle-hook", "opencrow-lifecycle-mcp"):
        if not (bin_dir / launcher).is_file():
            raise AssertionError(f"Skills install is missing launcher: {launcher}")
    if (bin_dir / "opencrow-init").exists():
        raise AssertionError("Skills-only install unexpectedly contains opencrow-init")
    for forbidden in (current / "packages" / "mcp", current / "services" / "constellation", data / "miniconda"):
        if forbidden.exists():
            raise AssertionError(f"Skills-only runtime contains a forbidden heavy component: {forbidden}")

    workspace = runtime_root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "CHALLENGE.md").write_text(
        "# Challenge\n\n## Original Challenge\n\nVerify the installed provider workflow.\n\n"
        "## Clarifications\n\nNone.\n",
        encoding="utf-8",
    )
    hook = run_json(
        [
            str(bin_dir / "opencrow-lifecycle-hook"),
            "session_start",
            "--provider",
            args.provider,
            "--workspace",
            str(workspace),
        ],
        environment=environment,
        input_text="{}\n",
    )
    context = str(hook.get("additionalContext") or hook.get("hookSpecificOutput", {}).get("additionalContext") or "")
    if "Current phase: reconnaissance" not in context:
        raise AssertionError(f"Installed lifecycle hook did not inject reconnaissance context: {hook}")
    verify_mcp(bin_dir, workspace, environment, expected_version)

    sys.path.insert(0, str(repository / "services" / "constellation"))
    from constellation.providers import adapter_for

    availability = adapter_for(args.provider).availability()
    if not availability.available or availability.compatibility == "incompatible":
        raise AssertionError(f"Trusted runtime cannot advertise {args.provider}: {availability}")

    print(
        json.dumps(
            {
                "provider": args.provider,
                "provider_version": availability.version,
                "compatibility": availability.compatibility,
                "skills": len(source_skills),
                "lifecycle_phase": "reconnaissance",
                "version": expected_version,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
