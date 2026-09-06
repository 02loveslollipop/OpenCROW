#!/usr/bin/env python3
"""OpenCROW AGY worker MCP server."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opencrow_mcp_core import (
    MCPTool,
    StdioMCPServer,
    command_exists,
    default_execution,
    error_envelope,
    make_toolbox_capabilities_handler,
    make_toolbox_info_handler,
    make_toolbox_self_test_handler,
    missing_dependency_envelope,
    normalize_path,
    success_envelope,
)

SERVER_NAME = "opencrow-agy-mcp"
SERVER_VERSION = "0.1.0"
TOOLBOX_ID = "agy-worker"
DISPLAY_NAME = "OpenCROW Runner - AGY Worker"
OPERATIONS = [
    {
        "name": "agy_execute",
        "description": "Execute a task with Antigravity (agy) in a specified workspace.",
    },
    {
        "name": "agy_chat",
        "description": "Send follow-up instructions or corrective feedback to an existing agy conversation.",
    },
    {
        "name": "agy_session_status",
        "description": "Return structured status and turn history for an agy conversation session.",
    },
    {
        "name": "agy_session_stop",
        "description": "Stop or unregister an active agy worker session.",
    },
]
SYSTEM_DEPENDENCIES = ["agy"]

# In-memory session tracking for active runner processes
_SESSIONS: dict[str, dict[str, Any]] = {}


def _get_agy_version() -> str | None:
    executable = shutil.which("agy")
    if not executable:
        return None
    try:
        proc = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        line = (proc.stdout or proc.stderr).strip().splitlines()[0]
        if line:
            return line
    except (OSError, subprocess.SubprocessError, IndexError):
        pass
    return "installed (version unavailable)"


def _run_agy_turn(
    *,
    task: str,
    workspace: Path,
    conversation_id: str | None = None,
    mode: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    timeout_sec: int = 300,
) -> tuple[bool, dict[str, Any] | None, str, str, int]:
    """Runs agy in print mode with JSON output and returns (ok, parsed_json, stdout, stderr, exit_code)."""
    executable = shutil.which("agy")
    if not executable:
        return False, None, "", "Executable 'agy' not found in PATH", 127

    command = [
        executable,
        "--dangerously-skip-permissions",
        "--output-format",
        "json",
    ]
    if conversation_id:
        command.extend(["--conversation", conversation_id])
    if mode in ("accept-edits", "plan"):
        command.extend(["--mode", mode])
    if model:
        command.extend(["--model", model])
    if effort in ("low", "medium", "high"):
        command.extend(["--effort", effort])
    command.append(f"--print={task}")

    try:
        proc = subprocess.run(
            command,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stderr_msg = f"agy task timed out after {timeout_sec} seconds"
        return False, None, exc.stdout or "", stderr_msg, 124
    except OSError as exc:
        return False, None, "", f"Execution failed: {exc}", 1

    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()

    parsed: dict[str, Any] | None = None
    if stdout:
        try:
            loaded = json.loads(stdout)
            if isinstance(loaded, dict):
                parsed = loaded
        except json.JSONDecodeError:
            pass

    ok = proc.returncode == 0 and parsed is not None and parsed.get("status") == "SUCCESS"
    return ok, parsed, stdout, stderr, proc.returncode


def toolbox_verify(arguments: dict[str, object]) -> dict[str, object]:
    agy_available = command_exists("agy")
    version = _get_agy_version() if agy_available else None
    observations = [
        {
            "dependency": "agy",
            "available": agy_available,
            "version": version,
            "type": "system-command",
        }
    ]
    return success_envelope(
        toolbox=TOOLBOX_ID,
        operation="toolbox_verify",
        summary="AGY worker dependency status returned.",
        inputs=arguments,
        observations=observations,
        next_steps=[
            "Use `agy_execute` to dispatch code editing, testing, or exploration tasks to agy.",
            "Use `agy_chat` to provide conversational feedback or corrections using the returned conversation_id.",
        ],
    )


def agy_execute(arguments: dict[str, object]) -> dict[str, object]:
    task = str(arguments.get("task", "")).strip()
    if not task:
        return error_envelope(
            toolbox=TOOLBOX_ID,
            operation="agy_execute",
            summary="Task description is required.",
            inputs=arguments,
            stderr="Missing or empty 'task' parameter.",
            exit_code=2,
        )

    raw_workspace = arguments.get("workspace")
    if raw_workspace:
        workspace = Path(str(raw_workspace)).expanduser().resolve()
    else:
        workspace = Path.cwd().resolve()

    if not workspace.is_dir():
        return error_envelope(
            toolbox=TOOLBOX_ID,
            operation="agy_execute",
            summary=f"Workspace directory does not exist: {workspace}",
            inputs=arguments,
            stderr=f"Directory not found: {workspace}",
            exit_code=2,
        )

    conversation_id = str(arguments.get("conversation_id", "")).strip() or None
    mode = str(arguments.get("mode", "")).strip() or None
    model = str(arguments.get("model", "")).strip() or None
    effort = str(arguments.get("effort", "")).strip() or None

    try:
        timeout_sec = int(arguments.get("timeout_sec", 300))
    except (ValueError, TypeError):
        timeout_sec = 300

    if not command_exists("agy"):
        return missing_dependency_envelope(
            toolbox=TOOLBOX_ID,
            operation="agy_execute",
            dependency="agy",
            inputs=arguments,
        )

    ok, parsed, stdout, stderr, exit_code = _run_agy_turn(
        task=task,
        workspace=workspace,
        conversation_id=conversation_id,
        mode=mode,
        model=model,
        effort=effort,
        timeout_sec=timeout_sec,
    )

    if not ok:
        error_msg = stderr or (parsed.get("response") if parsed else "") or stdout or "agy task failed"
        return error_envelope(
            toolbox=TOOLBOX_ID,
            operation="agy_execute",
            summary=f"AGY task execution failed (exit code {exit_code}).",
            inputs=arguments,
            stderr=error_msg,
            exit_code=exit_code if exit_code != 0 else 1,
        )

    conv_id = parsed.get("conversation_id", conversation_id or "unknown")
    num_turns = parsed.get("num_turns", 1)
    duration = parsed.get("duration_seconds", 0.0)
    response_text = parsed.get("response", "")
    usage = parsed.get("usage", {})

    now_iso = datetime.now(timezone.utc).isoformat()
    _SESSIONS[conv_id] = {
        "conversation_id": conv_id,
        "workspace": str(workspace),
        "turns": num_turns,
        "last_task": task[:120],
        "updated_at": now_iso,
    }

    return success_envelope(
        toolbox=TOOLBOX_ID,
        operation="agy_execute",
        summary=f"AGY task completed successfully in {duration:.2f}s ({num_turns} turn(s)).",
        inputs=arguments,
        observations=[
            {
                "conversation_id": conv_id,
                "response": response_text,
                "duration_seconds": duration,
                "num_turns": num_turns,
                "usage": usage,
                "workspace": str(workspace),
            }
        ],
        next_steps=[
            f"To follow up or ask agy to make fixes, call `agy_chat` with conversation_id '{conv_id}'.",
            "Review modified files and verify against acceptance criteria.",
        ],
    )


def agy_chat(arguments: dict[str, object]) -> dict[str, object]:
    conv_id = str(arguments.get("conversation_id", "")).strip()
    if not conv_id:
        return error_envelope(
            toolbox=TOOLBOX_ID,
            operation="agy_chat",
            summary="conversation_id is required.",
            inputs=arguments,
            stderr="Missing or empty 'conversation_id' parameter.",
            exit_code=2,
        )

    message = str(arguments.get("message", "")).strip()
    if not message:
        return error_envelope(
            toolbox=TOOLBOX_ID,
            operation="agy_chat",
            summary="message is required.",
            inputs=arguments,
            stderr="Missing or empty 'message' parameter.",
            exit_code=2,
        )

    raw_workspace = arguments.get("workspace")
    if raw_workspace:
        workspace = Path(str(raw_workspace)).expanduser().resolve()
    elif conv_id in _SESSIONS:
        workspace = Path(_SESSIONS[conv_id]["workspace"]).resolve()
    else:
        workspace = Path.cwd().resolve()

    try:
        timeout_sec = int(arguments.get("timeout_sec", 300))
    except (ValueError, TypeError):
        timeout_sec = 300

    if not command_exists("agy"):
        return missing_dependency_envelope(
            toolbox=TOOLBOX_ID,
            operation="agy_chat",
            dependency="agy",
            inputs=arguments,
        )

    ok, parsed, stdout, stderr, exit_code = _run_agy_turn(
        task=message,
        workspace=workspace,
        conversation_id=conv_id,
        timeout_sec=timeout_sec,
    )

    if not ok:
        error_msg = stderr or (parsed.get("response") if parsed else "") or stdout or "agy chat turn failed"
        return error_envelope(
            toolbox=TOOLBOX_ID,
            operation="agy_chat",
            summary=f"AGY chat turn failed (exit code {exit_code}).",
            inputs=arguments,
            stderr=error_msg,
            exit_code=exit_code if exit_code != 0 else 1,
        )

    num_turns = parsed.get("num_turns", 1)
    duration = parsed.get("duration_seconds", 0.0)
    response_text = parsed.get("response", "")
    usage = parsed.get("usage", {})

    now_iso = datetime.now(timezone.utc).isoformat()
    _SESSIONS[conv_id] = {
        "conversation_id": conv_id,
        "workspace": str(workspace),
        "turns": num_turns,
        "last_task": message[:120],
        "updated_at": now_iso,
    }

    return success_envelope(
        toolbox=TOOLBOX_ID,
        operation="agy_chat",
        summary=f"AGY follow-up turn completed in {duration:.2f}s ({num_turns} turn(s)).",
        inputs=arguments,
        observations=[
            {
                "conversation_id": conv_id,
                "response": response_text,
                "duration_seconds": duration,
                "num_turns": num_turns,
                "usage": usage,
                "workspace": str(workspace),
            }
        ],
        next_steps=[
            f"Continue refining by calling `agy_chat` with conversation_id '{conv_id}', or complete this phase.",
        ],
    )


def agy_session_status(arguments: dict[str, object]) -> dict[str, object]:
    conv_id = str(arguments.get("conversation_id", "")).strip()
    if not conv_id:
        # Return all known sessions
        return success_envelope(
            toolbox=TOOLBOX_ID,
            operation="agy_session_status",
            summary=f"Known AGY sessions returned ({len(_SESSIONS)} session(s)).",
            inputs=arguments,
            observations=[{"sessions": list(_SESSIONS.values())}],
        )

    session = _SESSIONS.get(conv_id)
    if not session:
        return success_envelope(
            toolbox=TOOLBOX_ID,
            operation="agy_session_status",
            summary=f"Session '{conv_id}' is not currently cached in memory.",
            inputs=arguments,
            observations=[{"conversation_id": conv_id, "cached": False}],
        )

    return success_envelope(
        toolbox=TOOLBOX_ID,
        operation="agy_session_status",
        summary=f"Status for session '{conv_id}' returned.",
        inputs=arguments,
        observations=[session],
    )


def agy_session_stop(arguments: dict[str, object]) -> dict[str, object]:
    conv_id = str(arguments.get("conversation_id", "")).strip()
    if not conv_id:
        return error_envelope(
            toolbox=TOOLBOX_ID,
            operation="agy_session_stop",
            summary="conversation_id is required.",
            inputs=arguments,
            stderr="Missing or empty 'conversation_id' parameter.",
            exit_code=2,
        )

    existed = conv_id in _SESSIONS
    _SESSIONS.pop(conv_id, None)

    return success_envelope(
        toolbox=TOOLBOX_ID,
        operation="agy_session_stop",
        summary=f"Session '{conv_id}' unregistered from active worker sessions.",
        inputs=arguments,
        observations=[{"conversation_id": conv_id, "unregistered": existed}],
    )


def build_server() -> StdioMCPServer:
    server = StdioMCPServer(
        server_name=SERVER_NAME,
        server_version=SERVER_VERSION,
        instructions="OpenCROW AGY worker MCP server. Delegate code editing, testing, and tactical implementation to agy.",
    )
    server.register_tools(
        [
            MCPTool(
                name="toolbox_info",
                description="Return metadata and operations for the OpenCROW AGY worker MCP server.",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                handler=make_toolbox_info_handler(
                    toolbox=TOOLBOX_ID,
                    display_name=DISPLAY_NAME,
                    server_name=SERVER_NAME,
                    server_version=SERVER_VERSION,
                    summary="OpenCROW AGY worker information returned.",
                    operations=OPERATIONS,
                ),
            ),
            MCPTool(
                name="toolbox_self_test",
                description="Run a lightweight self-test of the AGY worker MCP server.",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                handler=make_toolbox_self_test_handler(
                    toolbox=TOOLBOX_ID,
                    display_name=DISPLAY_NAME,
                    server_name=SERVER_NAME,
                    server_version=SERVER_VERSION,
                    operations=OPERATIONS,
                ),
            ),
            MCPTool(
                name="toolbox_verify",
                description="Verify availability of agy command in PATH.",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                handler=toolbox_verify,
            ),
            MCPTool(
                name="toolbox_capabilities",
                description="Return the structured operations exposed by the AGY worker MCP server.",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                handler=make_toolbox_capabilities_handler(TOOLBOX_ID, OPERATIONS),
            ),
            MCPTool(
                name="agy_execute",
                description="Execute an implementation, exploration, or testing task using the agy worker agent.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "Clear instructions for agy detailing what files to create/edit or commands to run.",
                        },
                        "workspace": {
                            "type": "string",
                            "description": "Absolute or relative path to the workspace directory. Defaults to current working directory.",
                        },
                        "conversation_id": {
                            "type": "string",
                            "description": "Optional conversation ID to resume or continue an existing thread.",
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["accept-edits", "plan"],
                            "description": "Agent execution mode ('accept-edits' by default).",
                        },
                        "model": {
                            "type": "string",
                            "description": "Optional model override for agy (e.g. gemini-2.5-flash, gemini-2.5-pro).",
                        },
                        "effort": {
                            "type": "string",
                            "enum": ["low", "medium", "high"],
                            "description": "Optional reasoning effort for agy.",
                        },
                        "timeout_sec": {
                            "type": "integer",
                            "description": "Timeout in seconds for this turn (default 300).",
                        },
                    },
                    "required": ["task"],
                    "additionalProperties": False,
                },
                handler=agy_execute,
            ),
            MCPTool(
                name="agy_chat",
                description="Send follow-up instructions, corrections, or feedback to an existing agy conversation thread.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "conversation_id": {
                            "type": "string",
                            "description": "The active conversation ID returned from a previous agy_execute or agy_chat call.",
                        },
                        "message": {
                            "type": "string",
                            "description": "The follow-up instruction, corrective prompt, or failure output to fix.",
                        },
                        "workspace": {
                            "type": "string",
                            "description": "Optional workspace directory path.",
                        },
                        "timeout_sec": {
                            "type": "integer",
                            "description": "Timeout in seconds for this turn (default 300).",
                        },
                    },
                    "required": ["conversation_id", "message"],
                    "additionalProperties": False,
                },
                handler=agy_chat,
            ),
            MCPTool(
                name="agy_session_status",
                description="Inspect turn history and workspace metadata for one or all cached agy sessions.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "conversation_id": {
                            "type": "string",
                            "description": "Optional conversation ID to inspect. If omitted, returns all cached sessions.",
                        },
                    },
                    "additionalProperties": False,
                },
                handler=agy_session_status,
            ),
            MCPTool(
                name="agy_session_stop",
                description="Unregister a finished agy worker session from memory.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "conversation_id": {
                            "type": "string",
                            "description": "The conversation ID to unregister.",
                        },
                    },
                    "required": ["conversation_id"],
                    "additionalProperties": False,
                },
                handler=agy_session_stop,
            ),
        ],
    )
    return server


def main() -> int:
    return build_server().serve()


if __name__ == "__main__":
    sys.exit(main())
