from __future__ import annotations

import importlib

import pytest


SERVER_MODULES = (
    "opencrow_crypto_mcp",
    "opencrow_forensics_mcp",
    "opencrow_minecraft_mcp",
    "opencrow_netcat_mcp",
    "opencrow_network_mcp",
    "opencrow_osint_mcp",
    "opencrow_pwn_mcp",
    "opencrow_reversing_mcp",
    "opencrow_ssh_mcp",
    "opencrow_stego_mcp",
    "opencrow_utility_mcp",
    "opencrow_web_mcp",
)


@pytest.mark.parametrize("module_name", SERVER_MODULES)
def test_domain_server_protocol_surface(module_name: str) -> None:
    module = importlib.import_module(module_name)
    server = module.build_server()
    initialized = server._handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}
    )
    assert initialized["result"]["protocolVersion"] == "2025-06-18"
    listed = server._handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert {"toolbox_info", "toolbox_self_test", "toolbox_verify", "toolbox_capabilities"} <= names


def test_domain_server_reports_missing_inputs_without_traceback() -> None:
    module = importlib.import_module("opencrow_web_mcp")
    result = module.web_discover({"backend": "ffuf", "target_url": "", "wordlist": "/missing"})
    assert result["ok"] is False
    assert result["exit_code"] == 2
    assert "required" in result["summary"].lower()
