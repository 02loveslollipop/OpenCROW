"""Exercise the shipped entrypoint after vendoring, without the full installer."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/mcp"))
import standalone


@pytest.fixture
def vendored(tmp_path):
    root = tmp_path / "vendor with spaces"
    shutil.copytree(ROOT / "packages/mcp", root / "mcp", ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    env = {k: v for k, v in os.environ.items() if not k.startswith("OPENCROW_") and k != "PYTHONPATH"}
    env.update(PATH="/usr/bin:/bin", XDG_DATA_HOME=str(tmp_path / "empty-data"), HOME=str(tmp_path / "empty-home"))
    return root, env


def rpc(root, env, server, method="tools/list", params=None):
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "id": 2, "method": method, "params": params or {}},
    ]
    result = subprocess.run([sys.executable, str(root / "mcp/standalone.py"), "serve", server],
        input="".join(json.dumps(message) + "\n" for message in messages), text=True,
        capture_output=True, env=env, cwd=root, timeout=30)
    assert result.returncode == 0, result.stderr
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert responses[0]["result"]["protocolVersion"] == "2025-06-18"
    assert "error" not in responses[1], responses[1]
    return responses[1]["result"]


@pytest.mark.parametrize("server", standalone.SERVERS)
def test_vendored_server_initializes_without_constellation_or_conda(vendored, server):
    root, env = vendored
    assert not (root / "services").exists()
    result = rpc(root, env, server)
    assert {"toolbox_info", "toolbox_verify"} <= {tool["name"] for tool in result["tools"]}


def test_condaless_typed_operation_uses_system_python(vendored):
    root, env = vendored
    result = rpc(root, env, "network", "tools/call", {"name": "network_python", "arguments": {"code": "print('standalone-ok')"}})
    envelope = json.loads(result["content"][0]["text"])
    assert envelope["ok"] is True
    assert envelope["stdout"].strip() == "standalone-ok"


def test_explicit_python_override_is_used(vendored):
    root, env = vendored
    marker = root / "used-override"
    wrapper = root / "python override"
    wrapper.write_text(f"#!/bin/sh\ntouch '{marker}'\nexec '{sys.executable}' \"$@\"\n")
    wrapper.chmod(0o755)
    env["OPENCROW_PYTHON"] = '"' + str(wrapper) + '"'
    rpc(root, env, "utility")
    assert marker.exists()


def test_vendored_io_backend_uses_explicit_skills_root(vendored):
    root, env = vendored
    skills = root / "canonical skills"
    shutil.copytree(ROOT / "skills/netcat-async", skills / "netcat-async")
    env["OPENCROW_SKILLS_ROOT"] = str(skills)
    result = rpc(root, env, "netcat", "tools/call", {"name": "session_status", "arguments": {"name": "opencrow-missing-vendoring-test"}})
    envelope = json.loads(result["content"][0]["text"])
    assert "does not exist" in envelope.get("stderr", "")
    assert "can't open file" not in envelope.get("stderr", "")


@pytest.mark.parametrize("provider", ["opencode", "opencode-v2", "codex", "claude", "antigravity"])
def test_generated_configuration_is_parseable_and_opt_in(provider, tmp_path):
    text = standalone.configuration(provider, ["crypto", "netcat"], tmp_path / "skills")
    data = tomllib.loads(text) if provider == "codex" else json.loads(text)
    entries = data.get("mcp_servers", data.get("mcpServers", data.get("mcp")))
    if provider == "opencode-v2":
        entries = entries["servers"]
    assert set(entries) == {"opencrow-crypto", "opencrow-netcat"}
    assert "constellation" not in text and "lifecycle" not in text


def test_missing_conda_environment_falls_back_consistently_for_probe_and_execution(tmp_path, monkeypatch):
    import opencrow_ctf_mcp_common as runtime
    from opencrow_mcp_core import conda_module_available
    monkeypatch.delenv("OPENCROW_PYTHON", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    helper = tmp_path / "helper-python"
    marker = tmp_path / "helper-used"
    helper.write_text(f"#!/bin/sh\ntouch '{marker}'\nexec '{sys.executable}' \"$@\"\n")
    helper.chmod(0o755)
    monkeypatch.setenv("OPENCROW_HELPER_PYTHON", str(helper))
    monkeypatch.setattr(runtime, "_conda_command", lambda: "/unusable-conda")
    monkeypatch.setattr(runtime, "run_command", lambda *a, **kw: {"ok": False})
    assert runtime.python_command() == [str(helper)]
    assert conda_module_available("ctf", "json") is True
    assert marker.exists()
