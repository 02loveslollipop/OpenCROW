"""Regression guards for the MCP core hardening (L3).

Malformed input must never crash the serve loop or hang the client:
null params collapse to {}, header lines without a colon are skipped.
"""
import io
import json

from opencrow_mcp_core import StdioMCPServer


def _server() -> StdioMCPServer:
    return StdioMCPServer(server_name="test", server_version="0.0")


def test_null_params_never_crash():
    server = _server()
    initialized = server._handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": None}
    )
    assert initialized["result"]["protocolVersion"]
    listed = server._handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": None})
    assert listed["result"] == {"tools": []}
    unknown = server._handle_message({"jsonrpc": "2.0", "id": 3, "method": "nope", "params": None})
    assert unknown["error"]["code"] == -32601
    call = server._handle_message({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": None})
    assert call["error"]["code"] == -32602


def test_header_without_colon_is_skipped():
    server = _server()
    body = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "ping"}).encode("utf-8")
    stream = io.BytesIO(b"Garbage-Header-Line\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
    assert server._read_message(stream) == {"jsonrpc": "2.0", "id": 7, "method": "ping"}
