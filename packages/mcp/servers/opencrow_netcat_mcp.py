#!/usr/bin/env python3
"""OpenCROW netcat async MCP server."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from opencrow_io_mcp_common import normalize_session_name, parse_json_stdout, run_backend_script, session_artifact_paths
from opencrow_mcp_core import (
    MCPTool,
    MCPResourceTemplate,
    StdioMCPServer,
    default_execution,
    error_envelope,
    json_resource_contents,
    make_toolbox_capabilities_handler,
    make_toolbox_info_handler,
    make_toolbox_self_test_handler,
    success_envelope,
)


SERVER_NAME = "opencrow-netcat-mcp"
SERVER_VERSION = "0.2.0"
TOOLBOX_ID = "netcat-async"
DISPLAY_NAME = "OpenCROW I/O - Netcat Async"
BACKEND_SCRIPT = "nc_async_session.py"
SESSION_BASE_DIR = os.environ.get("OPENCROW_NC_ASYNC_DIR", "/tmp/opencrow-nc-async")
OPERATIONS = [
    {"name": "session_start", "description": "Start a named outbound asynchronous TCP session."},
    {"name": "session_listen", "description": "Listen for one inbound TCP connection."},
    {"name": "session_send", "description": "Send text or encoded raw bytes to a connected TCP session."},
    {"name": "session_read", "description": "Read or follow the captured log for a TCP session."},
    {"name": "session_status", "description": "Return the structured status for a TCP session."},
    {"name": "session_stop", "description": "Stop a running asynchronous TCP session."},
]


def _run_status(name: str, cwd: str | Path | None, timeout_sec: int) -> tuple[dict[str, object], dict[str, object] | None]:
    result = run_backend_script(BACKEND_SCRIPT, ["status", "--name", name], cwd=cwd, timeout_sec=timeout_sec)
    return result, parse_json_stdout(result)


def _invalid_session_name(operation: str, inputs: dict[str, object], exc: ValueError) -> dict[str, object]:
    return error_envelope(
        toolbox=TOOLBOX_ID,
        operation=operation,
        summary="Invalid session name.",
        inputs=inputs,
        stderr=str(exc),
        exit_code=2,
    )


def _session_artifact_snapshot(name: str) -> list[dict[str, object]]:
    return [
        {"path": path, "exists": Path(path).exists()}
        for path in session_artifact_paths(SESSION_BASE_DIR, name)
    ]


def _read_session_status_resource(uri: str, params: dict[str, str]) -> list[dict[str, object]]:
    name = normalize_session_name(params.get("name", ""))
    result, payload = _run_status(name, None, 30)
    return json_resource_contents(
        uri,
        {
            "name": name,
            "backend_script": BACKEND_SCRIPT,
            "base_dir": SESSION_BASE_DIR,
            "ok": result["ok"],
            "status": payload,
            "stderr": result["stderr"],
            "exit_code": result["exit_code"],
        },
    )


def _read_session_artifacts_resource(uri: str, params: dict[str, str]) -> list[dict[str, object]]:
    name = normalize_session_name(params.get("name", ""))
    return json_resource_contents(
        uri,
        {
            "name": name,
            "base_dir": SESSION_BASE_DIR,
            "artifacts": _session_artifact_snapshot(name),
        },
    )


def toolbox_verify(arguments: dict[str, object]) -> dict[str, object]:
    observations = [
        {"dependency": "python_socket", "available": True},
        {"dependency": "session_base_dir", "path": SESSION_BASE_DIR},
        {"dependency": "backend_script", "path": BACKEND_SCRIPT},
    ]
    return success_envelope(
        toolbox=TOOLBOX_ID,
        operation="toolbox_verify",
        summary="Netcat async MCP server is available.",
        inputs=arguments,
        observations=observations,
        next_steps=["Use `session_start` for outbound TCP or `session_listen` for one inbound connection."],
    )


def session_start(arguments: dict[str, object]) -> dict[str, object]:
    raw_name = arguments.get("name", "")
    host = str(arguments.get("host", "")).strip()
    port = arguments.get("port")
    connect_timeout_value = arguments.get("connect_timeout", 10.0)
    inputs = {
        "name": str(raw_name).strip(),
        "host": host,
        "port": port,
        "connect_timeout": connect_timeout_value,
    }
    if not host or port is None:
        return error_envelope(
            toolbox=TOOLBOX_ID,
            operation="session_start",
            summary="Session name, host, and port are required.",
            inputs=inputs,
            stderr="Pass `name`, `host`, and `port`.",
            exit_code=2,
        )
    try:
        name = normalize_session_name(raw_name)
        port_number = int(port)
        connect_timeout = float(connect_timeout_value)
    except (TypeError, ValueError) as exc:
        return error_envelope(
            toolbox=TOOLBOX_ID,
            operation="session_start",
            summary="Invalid outbound session input.",
            inputs=inputs,
            stderr=str(exc),
            exit_code=2,
        )
    inputs.update({"name": name, "port": port_number, "connect_timeout": connect_timeout})

    cwd, timeout_sec = default_execution(arguments)
    result = run_backend_script(
        BACKEND_SCRIPT,
        [
            "start",
            "--name",
            name,
            "--host",
            host,
            "--port",
            str(port_number),
            "--connect-timeout",
            str(connect_timeout),
        ],
        cwd=cwd,
        timeout_sec=timeout_sec,
    )
    status_result, status_payload = _run_status(name, cwd, timeout_sec)
    artifacts = session_artifact_paths(SESSION_BASE_DIR, name)
    observations = [status_payload] if isinstance(status_payload, dict) else []
    if result["ok"]:
        return success_envelope(
            toolbox=TOOLBOX_ID,
            operation="session_start",
            summary=f"Netcat session '{name}' started.",
            inputs=inputs,
            artifacts=artifacts,
            observations=observations,
            command=result["command"],
            stdout=result["stdout"],
            stderr=result["stderr"] if result["stderr"] else status_result.get("stderr", ""),
            exit_code=result["exit_code"],
            next_steps=["Use `session_send` and `session_read` against the same `name`."],
        )
    return error_envelope(
        toolbox=TOOLBOX_ID,
        operation="session_start",
        summary=f"Failed to start netcat session '{name}'.",
        inputs=inputs,
        command=result["command"],
        stdout=result["stdout"],
        stderr=result["stderr"],
        exit_code=result["exit_code"],
    )


def session_listen(arguments: dict[str, object]) -> dict[str, object]:
    raw_name = arguments.get("name", "")
    port = arguments.get("port")
    bind_host = str(arguments.get("bind_host", "127.0.0.1")).strip()
    allow_remote = bool(arguments.get("allow_remote", False))
    expected_peer_value = arguments.get("expected_peer")
    expected_peer = str(expected_peer_value).strip() if expected_peer_value is not None else None
    accept_timeout_value = arguments.get("accept_timeout")
    inputs = {
        "name": str(raw_name).strip(),
        "port": port,
        "bind_host": bind_host,
        "allow_remote": allow_remote,
        "expected_peer": expected_peer,
        "accept_timeout": accept_timeout_value,
    }
    if port is None or not bind_host:
        return error_envelope(
            toolbox=TOOLBOX_ID,
            operation="session_listen",
            summary="Session name, bind host, and port are required.",
            inputs=inputs,
            stderr="Pass `name` and `port`; `bind_host` defaults to 127.0.0.1.",
            exit_code=2,
        )
    try:
        name = normalize_session_name(raw_name)
        port_number = int(port)
        accept_timeout = float(accept_timeout_value) if accept_timeout_value is not None else None
    except (TypeError, ValueError) as exc:
        return error_envelope(
            toolbox=TOOLBOX_ID,
            operation="session_listen",
            summary="Invalid listener input.",
            inputs=inputs,
            stderr=str(exc),
            exit_code=2,
        )
    inputs.update({"name": name, "port": port_number, "accept_timeout": accept_timeout})

    command = ["listen", "--name", name, "--port", str(port_number), "--bind-host", bind_host]
    if allow_remote:
        command.append("--allow-remote")
    if expected_peer:
        command.extend(["--expected-peer", expected_peer])
    if accept_timeout is not None:
        command.extend(["--accept-timeout", str(accept_timeout)])

    cwd, timeout_sec = default_execution(arguments)
    result = run_backend_script(BACKEND_SCRIPT, command, cwd=cwd, timeout_sec=timeout_sec)
    artifacts = session_artifact_paths(SESSION_BASE_DIR, name)
    if result["ok"]:
        status_result, status_payload = _run_status(name, cwd, timeout_sec)
        observations = [status_payload] if isinstance(status_payload, dict) else []
        return success_envelope(
            toolbox=TOOLBOX_ID,
            operation="session_listen",
            summary=f"Netcat session '{name}' is listening for one inbound connection.",
            inputs=inputs,
            artifacts=artifacts,
            observations=observations,
            command=result["command"],
            stdout=result["stdout"],
            stderr=result["stderr"] if result["stderr"] else status_result.get("stderr", ""),
            exit_code=result["exit_code"],
            next_steps=["Give the reported port to the authorized peer, then use `session_status`, `session_send`, and `session_read`."],
        )
    return error_envelope(
        toolbox=TOOLBOX_ID,
        operation="session_listen",
        summary=f"Failed to start listener session '{name}'.",
        inputs=inputs,
        artifacts=artifacts,
        command=result["command"],
        stdout=result["stdout"],
        stderr=result["stderr"],
        exit_code=result["exit_code"],
    )


def session_send(arguments: dict[str, object]) -> dict[str, object]:
    raw_name = arguments.get("name", "")
    provided = [key for key in ("data", "hex", "base64") if key in arguments and arguments[key] is not None]
    newline = bool(arguments.get("newline", False))
    timeout_value = arguments.get("timeout", 2.0)
    inputs = {
        "name": str(raw_name).strip(),
        "newline": newline,
        "timeout": timeout_value,
        **{key: arguments[key] for key in provided},
    }
    if len(provided) != 1:
        return error_envelope(
            toolbox=TOOLBOX_ID,
            operation="session_send",
            summary="Exactly one payload representation is required.",
            inputs=inputs,
            stderr="Pass exactly one of `data`, `hex`, or `base64`.",
            exit_code=2,
        )
    if newline and provided[0] != "data":
        return error_envelope(
            toolbox=TOOLBOX_ID,
            operation="session_send",
            summary="Newline is only valid for text input.",
            inputs=inputs,
            stderr="Use `newline` only with `data`.",
            exit_code=2,
        )
    try:
        name = normalize_session_name(raw_name)
        timeout = float(timeout_value)
    except (TypeError, ValueError) as exc:
        return error_envelope(
            toolbox=TOOLBOX_ID,
            operation="session_send",
            summary="Invalid session send input.",
            inputs=inputs,
            stderr=str(exc),
            exit_code=2,
        )
    inputs.update({"name": name, "timeout": timeout})

    cwd, timeout_sec = default_execution(arguments)
    payload_type = provided[0]
    payload_value = str(arguments[payload_type])
    command = ["send", "--name", name, f"--{payload_type}", payload_value, "--timeout", str(timeout)]
    if newline:
        command.append("--newline")
    result = run_backend_script(BACKEND_SCRIPT, command, cwd=cwd, timeout_sec=timeout_sec)
    artifacts = session_artifact_paths(SESSION_BASE_DIR, name)
    if result["ok"]:
        return success_envelope(
            toolbox=TOOLBOX_ID,
            operation="session_send",
            summary=f"Sent data to netcat session '{name}'.",
            inputs=inputs,
            artifacts=artifacts,
            observations=[{"name": name, "newline": newline, "payload_type": payload_type}],
            command=result["command"],
            stdout=result["stdout"],
            stderr=result["stderr"],
            exit_code=result["exit_code"],
            next_steps=["Use `session_read` to inspect the remote response."],
        )
    return error_envelope(
        toolbox=TOOLBOX_ID,
        operation="session_send",
        summary=f"Failed to send data to netcat session '{name}'.",
        inputs=inputs,
        command=result["command"],
        stdout=result["stdout"],
        stderr=result["stderr"],
        exit_code=result["exit_code"],
    )


def session_read(arguments: dict[str, object]) -> dict[str, object]:
    raw_name = arguments.get("name", "")
    tail = arguments.get("tail")
    follow = bool(arguments.get("follow", False))
    inputs = {"name": str(raw_name).strip(), "tail": tail, "follow": follow}
    try:
        name = normalize_session_name(raw_name)
    except ValueError as exc:
        return _invalid_session_name("session_read", inputs, exc)
    inputs["name"] = name

    cwd, timeout_sec = default_execution(arguments)
    command = ["read", "--name", name]
    if tail is not None:
        command.extend(["--tail", str(int(tail))])
    if follow:
        command.append("--follow")
    result = run_backend_script(BACKEND_SCRIPT, command, cwd=cwd, timeout_sec=timeout_sec)
    artifacts = session_artifact_paths(SESSION_BASE_DIR, name)
    if result["ok"]:
        return success_envelope(
            toolbox=TOOLBOX_ID,
            operation="session_read",
            summary=f"Read output for netcat session '{name}'.",
            inputs=inputs,
            artifacts=artifacts,
            observations=[{"name": name, "follow": follow, "tail": tail}],
            command=result["command"],
            stdout=result["stdout"],
            stderr=result["stderr"],
            exit_code=result["exit_code"],
        )
    return error_envelope(
        toolbox=TOOLBOX_ID,
        operation="session_read",
        summary=f"Failed to read output for netcat session '{name}'.",
        inputs=inputs,
        command=result["command"],
        stdout=result["stdout"],
        stderr=result["stderr"],
        exit_code=result["exit_code"],
    )


def session_status(arguments: dict[str, object]) -> dict[str, object]:
    raw_name = arguments.get("name", "")
    inputs = {"name": str(raw_name).strip()}
    try:
        name = normalize_session_name(raw_name)
    except ValueError as exc:
        return _invalid_session_name("session_status", inputs, exc)
    inputs["name"] = name

    cwd, timeout_sec = default_execution(arguments)
    result, payload = _run_status(name, cwd, timeout_sec)
    if result["ok"] and isinstance(payload, dict):
        artifacts = list(payload.get("paths", {}).values()) if isinstance(payload.get("paths"), dict) else session_artifact_paths(SESSION_BASE_DIR, name)
        return success_envelope(
            toolbox=TOOLBOX_ID,
            operation="session_status",
            summary=f"Status returned for netcat session '{name}'.",
            inputs=inputs,
            artifacts=artifacts,
            observations=[payload],
            command=result["command"],
            stdout=result["stdout"],
            stderr=result["stderr"],
            exit_code=result["exit_code"],
        )
    return error_envelope(
        toolbox=TOOLBOX_ID,
        operation="session_status",
        summary=f"Failed to load status for netcat session '{name}'.",
        inputs=inputs,
        command=result["command"],
        stdout=result["stdout"],
        stderr=result["stderr"],
        exit_code=result["exit_code"],
    )


def session_stop(arguments: dict[str, object]) -> dict[str, object]:
    raw_name = arguments.get("name", "")
    timeout = float(arguments.get("timeout", 3.0))
    inputs = {"name": str(raw_name).strip(), "timeout": timeout}
    try:
        name = normalize_session_name(raw_name)
    except ValueError as exc:
        return _invalid_session_name("session_stop", inputs, exc)
    inputs["name"] = name

    cwd, timeout_sec = default_execution(arguments)
    result = run_backend_script(
        BACKEND_SCRIPT,
        ["stop", "--name", name, "--timeout", str(timeout)],
        cwd=cwd,
        timeout_sec=timeout_sec,
    )
    artifacts = session_artifact_paths(SESSION_BASE_DIR, name)
    if result["ok"]:
        return success_envelope(
            toolbox=TOOLBOX_ID,
            operation="session_stop",
            summary=f"Stopped netcat session '{name}'.",
            inputs=inputs,
            artifacts=artifacts,
            observations=[{"name": name}],
            command=result["command"],
            stdout=result["stdout"],
            stderr=result["stderr"],
            exit_code=result["exit_code"],
        )
    return error_envelope(
        toolbox=TOOLBOX_ID,
        operation="session_stop",
        summary=f"Failed to stop netcat session '{name}'.",
        inputs=inputs,
        command=result["command"],
        stdout=result["stdout"],
        stderr=result["stderr"],
        exit_code=result["exit_code"],
    )


def build_server() -> StdioMCPServer:
    server = StdioMCPServer(
        server_name=SERVER_NAME,
        server_version=SERVER_VERSION,
        instructions="OpenCROW async netcat I/O server.",
    )
    server.register_tools(
        [
            MCPTool(
                name="toolbox_info",
                description="Return metadata about the OpenCROW async netcat I/O server.",
                input_schema={"type": "object", "properties": {}},
                handler=make_toolbox_info_handler(
                    toolbox=TOOLBOX_ID,
                    display_name=DISPLAY_NAME,
                    server_name=SERVER_NAME,
                    server_version=SERVER_VERSION,
                    summary="OpenCROW async netcat I/O server information returned.",
                    operations=OPERATIONS,
                ),
            ),
            MCPTool(
                name="toolbox_self_test",
                description="Run a lightweight self-test for this OpenCROW MCP server.",
                input_schema={"type": "object", "properties": {}},
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
                description="Return dependency status for the OpenCROW async netcat I/O server.",
                input_schema={"type": "object", "properties": {}},
                handler=toolbox_verify,
            ),
            MCPTool(
                name="toolbox_capabilities",
                description="Return the structured operations exposed by the OpenCROW async netcat I/O server.",
                input_schema={"type": "object", "properties": {}},
                handler=make_toolbox_capabilities_handler(TOOLBOX_ID, OPERATIONS),
            ),
            MCPTool(
                name="session_start",
                description="Start a named outbound asynchronous TCP session.",
                input_schema={
                    "type": "object",
                    "required": ["name", "host", "port"],
                    "properties": {
                        "name": {"type": "string"},
                        "host": {"type": "string"},
                        "port": {"type": "integer"},
                        "connect_timeout": {"type": "number"},
                        "execution": {"type": "object"},
                    },
                },
                handler=session_start,
            ),
            MCPTool(
                name="session_listen",
                description="Listen for one inbound TCP connection; non-loopback binds require explicit opt-in.",
                input_schema={
                    "type": "object",
                    "required": ["name", "port"],
                    "properties": {
                        "name": {"type": "string"},
                        "port": {"type": "integer", "minimum": 0, "maximum": 65535},
                        "bind_host": {"type": "string", "default": "127.0.0.1"},
                        "allow_remote": {"type": "boolean", "default": False},
                        "expected_peer": {"type": "string"},
                        "accept_timeout": {"type": "number", "exclusiveMinimum": 0},
                        "execution": {"type": "object"},
                    },
                },
                handler=session_listen,
            ),
            MCPTool(
                name="session_send",
                description="Send text, hexadecimal bytes, or base64 bytes to a connected TCP session.",
                input_schema={
                    "type": "object",
                    "required": ["name"],
                    "oneOf": [
                        {"required": ["data"]},
                        {"required": ["hex"]},
                        {"required": ["base64"]},
                    ],
                    "properties": {
                        "name": {"type": "string"},
                        "data": {"type": "string"},
                        "hex": {"type": "string"},
                        "base64": {"type": "string"},
                        "newline": {"type": "boolean"},
                        "timeout": {"type": "number"},
                        "execution": {"type": "object"},
                    },
                },
                handler=session_send,
            ),
            MCPTool(
                name="session_read",
                description="Read or follow a session log.",
                input_schema={
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "tail": {"type": "integer"},
                        "follow": {"type": "boolean"},
                        "execution": {"type": "object"},
                    },
                },
                handler=session_read,
            ),
            MCPTool(
                name="session_status",
                description="Return structured status for a named session.",
                input_schema={
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "execution": {"type": "object"},
                    },
                },
                handler=session_status,
            ),
            MCPTool(
                name="session_stop",
                description="Stop a named asynchronous TCP session.",
                input_schema={
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "timeout": {"type": "number"},
                        "execution": {"type": "object"},
                    },
                },
                handler=session_stop,
            ),
        ]
    )
    server.register_resource_templates(
        [
            MCPResourceTemplate(
                uri_template=f"opencrow://{SERVER_NAME}/sessions/{{name}}/status",
                name="Netcat session status",
                description="Read status metadata for a named asynchronous TCP session.",
                mime_type="application/json",
                handler=_read_session_status_resource,
            ),
            MCPResourceTemplate(
                uri_template=f"opencrow://{SERVER_NAME}/sessions/{{name}}/artifacts",
                name="Netcat session artifacts",
                description="Read the expected artifact paths and existence state for a named asynchronous TCP session.",
                mime_type="application/json",
                handler=_read_session_artifacts_resource,
            ),
        ]
    )
    return server


def main() -> int:
    return build_server().serve()


if __name__ == "__main__":
    sys.exit(main())
