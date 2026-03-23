#!/usr/bin/env python3
"""Basic stdio MCP handshake probe for OpenCROW servers."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def write_message(stream: Any, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\nContent-Type: application/json\r\n\r\n".encode("utf-8")
    stream.write(header)
    stream.flush()
    stream.write(body)
    stream.flush()


def read_message(stream: Any) -> dict[str, Any]:
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            raise RuntimeError("Unexpected EOF from MCP server.")
        if line in (b"\r\n", b"\n"):
            break
        decoded = line.decode("utf-8").strip()
        name, value = decoded.split(":", 1)
        headers[name.lower()] = value.strip()
    content_length = int(headers["content-length"])
    body = stream.read(content_length)
    return json.loads(body.decode("utf-8"))


def write_json_line(stream: Any, payload: dict[str, Any]) -> None:
    stream.write((json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8"))
    stream.flush()


def read_json_line(stream: Any) -> dict[str, Any]:
    while True:
        line = stream.readline()
        if not line:
            raise RuntimeError("Unexpected EOF from MCP server.")
        stripped = line.strip()
        if not stripped:
            continue
        try:
            return json.loads(stripped.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Unexpected line-delimited payload from MCP server: {stripped!r}") from exc


def parse_json_lines(data: bytes) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for raw_line in data.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Unexpected line-delimited payload from MCP server: {stripped!r}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Unexpected line-delimited payload from MCP server: {parsed!r}")
        messages.append(parsed)
    return messages


def parse_tool_envelope(response: dict[str, Any]) -> dict[str, Any]:
    result = response.get("result")
    if not isinstance(result, dict):
        raise RuntimeError(f"Missing tool result payload: {response}")
    content = result.get("content")
    if not isinstance(content, list) or not content:
        raise RuntimeError(f"Missing tool content payload: {response}")
    first = content[0]
    if not isinstance(first, dict) or first.get("type") != "text":
        raise RuntimeError(f"Unexpected tool content payload: {response}")
    text = first.get("text")
    if not isinstance(text, str):
        raise RuntimeError(f"Missing tool text payload: {response}")
    return json.loads(text)


def parse_resource_contents(response: dict[str, Any]) -> list[dict[str, Any]]:
    result = response.get("result")
    if not isinstance(result, dict):
        raise RuntimeError(f"Missing resource result payload: {response}")
    contents = result.get("contents")
    if not isinstance(contents, list) or not contents:
        raise RuntimeError(f"Missing resource contents payload: {response}")
    first = contents[0]
    if not isinstance(first, dict) or not isinstance(first.get("uri"), str):
        raise RuntimeError(f"Unexpected resource contents payload: {response}")
    return contents


def run_probe(
    server_path: Path,
    *,
    writer: Any,
    reader: Any,
    protocol_version: str,
) -> None:
    proc = subprocess.Popen(
        [str(server_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None

    try:
        write_message(
            proc.stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": protocol_version,
                    "capabilities": {},
                    "clientInfo": {"name": "opencrow-check", "version": "0.1.0"},
                },
            },
        )
        init_result = reader(proc.stdout)
        init_payload = init_result.get("result", {})
        server_name = init_payload.get("serverInfo", {}).get("name")
        if server_name is None:
            raise RuntimeError(f"Missing serverInfo in initialize response: {init_result}")
        if "resources" not in init_payload.get("capabilities", {}):
            raise RuntimeError(f"Missing resources capability in initialize response: {init_result}")

        writer(proc.stdin, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        writer(
            proc.stdin,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            },
        )
        tools_result = reader(proc.stdout)
        tools_payload = tools_result.get("result", {})
        tools = tools_payload.get("tools")
        if not isinstance(tools, list) or not any(tool.get("name") == "toolbox_self_test" for tool in tools if isinstance(tool, dict)):
            raise RuntimeError(f"tools/list did not return toolbox_self_test: {tools_result}")

        writer(
            proc.stdin,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "resources/list",
                "params": {},
            },
        )
        resources_result = reader(proc.stdout)
        resources_payload = resources_result.get("result", {})
        resources = resources_payload.get("resources")
        if not isinstance(resources, list) or not resources:
            raise RuntimeError(f"resources/list returned no resources: {resources_result}")
        server_resource_uri = f"opencrow://{server_name}/server"
        if not any(resource.get("uri") == server_resource_uri for resource in resources if isinstance(resource, dict)):
            raise RuntimeError(f"resources/list did not return the built-in server resource: {resources_result}")

        writer(
            proc.stdin,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "resources/templates/list",
                "params": {},
            },
        )
        templates_result = reader(proc.stdout)
        templates_payload = templates_result.get("result", {})
        resource_templates = templates_payload.get("resourceTemplates")
        if not isinstance(resource_templates, list) or not resource_templates:
            raise RuntimeError(f"resources/templates/list returned no templates: {templates_result}")
        tool_template_uri = f"opencrow://{server_name}/tools/toolbox_self_test"
        if not any(
            template.get("uriTemplate") == f"opencrow://{server_name}/tools/{{name}}"
            for template in resource_templates
            if isinstance(template, dict)
        ):
            raise RuntimeError(f"resources/templates/list did not return the built-in tool template: {templates_result}")

        writer(
            proc.stdin,
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "resources/read",
                "params": {"uri": server_resource_uri},
            },
        )
        server_resource_result = reader(proc.stdout)
        server_resource_contents = parse_resource_contents(server_resource_result)
        if server_resource_contents[0].get("uri") != server_resource_uri:
            raise RuntimeError(f"resources/read returned an unexpected server resource payload: {server_resource_result}")

        writer(
            proc.stdin,
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "resources/read",
                "params": {"uri": tool_template_uri},
            },
        )
        tool_resource_result = reader(proc.stdout)
        tool_resource_contents = parse_resource_contents(tool_resource_result)
        if tool_resource_contents[0].get("uri") != tool_template_uri:
            raise RuntimeError(f"resources/read returned an unexpected templated resource payload: {tool_resource_result}")

        writer(
            proc.stdin,
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "toolbox_self_test", "arguments": {}},
            },
        )
        self_test_result = reader(proc.stdout)
        envelope = parse_tool_envelope(self_test_result)
        if not envelope.get("ok"):
            raise RuntimeError(f"toolbox_self_test failed: {self_test_result}")
        if envelope.get("operation") != "toolbox_self_test":
            raise RuntimeError(f"Unexpected tool response: {self_test_result}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


def run_json_line_probe(server_path: Path) -> None:
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "opencrow-check", "version": "0.1.0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}},
        {"jsonrpc": "2.0", "id": 4, "method": "resources/templates/list", "params": {}},
    ]
    stdin_payload = b"".join(
        (json.dumps(message, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
        for message in requests
    )
    completed = subprocess.run(
        [str(server_path)],
        input=stdin_payload,
        capture_output=True,
        check=False,
        timeout=5,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Line-delimited probe exited with code {completed.returncode}: {completed.stderr.decode('utf-8', errors='replace')}"
        )

    responses = parse_json_lines(completed.stdout)
    if len(responses) < 4:
        raise RuntimeError(f"Line-delimited probe returned too few responses: {responses!r}")

    init_result = responses[0]
    init_payload = init_result.get("result", {})
    server_name = init_payload.get("serverInfo", {}).get("name")
    if server_name is None:
        raise RuntimeError(f"Missing serverInfo in line-delimited initialize response: {init_result}")
    if init_payload.get("protocolVersion") != "2025-11-25":
        raise RuntimeError(f"Unexpected negotiated protocol version in line-delimited response: {init_result}")

    tools_result = responses[1]
    tools_payload = tools_result.get("result", {})
    tools = tools_payload.get("tools")
    if not isinstance(tools, list) or not any(tool.get("name") == "toolbox_self_test" for tool in tools if isinstance(tool, dict)):
        raise RuntimeError(f"Line-delimited tools/list did not return toolbox_self_test: {tools_result}")

    resources_result = responses[2]
    resources_payload = resources_result.get("result", {})
    resources = resources_payload.get("resources")
    server_resource_uri = f"opencrow://{server_name}/server"
    if not isinstance(resources, list) or not any(
        resource.get("uri") == server_resource_uri for resource in resources if isinstance(resource, dict)
    ):
        raise RuntimeError(f"Line-delimited resources/list did not return the built-in server resource: {resources_result}")

    templates_result = responses[3]
    templates_payload = templates_result.get("result", {})
    resource_templates = templates_payload.get("resourceTemplates")
    if not isinstance(resource_templates, list) or not any(
        template.get("uriTemplate") == f"opencrow://{server_name}/tools/{{name}}"
        for template in resource_templates
        if isinstance(template, dict)
    ):
        raise RuntimeError(
            f"Line-delimited resources/templates/list did not return the built-in tool template: {templates_result}"
        )


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_mcp_server.py /absolute/path/to/server", file=sys.stderr)
        return 2

    server_path = Path(sys.argv[1]).expanduser().resolve()
    run_probe(
        server_path,
        writer=write_message,
        reader=read_message,
        protocol_version="2024-11-05",
    )
    run_json_line_probe(server_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
