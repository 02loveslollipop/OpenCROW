"""Merge-ready regression tests for the security audit polish.

Covers:
- L1: concurrent record_attempt keeps every entry with unique IDs (outer fcntl lock).
- L4: _next_id counts short handwritten IDs like F-1 so generated IDs never collide.
- L2: StdioServer.dispatch always answers, even on unexpected exceptions.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from opencrow_lifecycle.engine import WorkflowEngine
from opencrow_lifecycle.mcp_server import StdioServer


def _init(tmp_path: Path) -> WorkflowEngine:
    engine = WorkflowEngine(tmp_path)
    engine.initialize("AcmeCTF Orbital Lock: recover the flag from service.bin", provider="codex")
    return engine


def test_next_id_counts_short_handwritten_ids(tmp_path: Path) -> None:
    engine = _init(tmp_path)
    findings = tmp_path / "FINDINGS.md"
    findings.write_text(findings.read_text(encoding="utf-8") + "\nManual note F-1.\n", encoding="utf-8")
    first = engine.record_finding(title="T", finding="b", evidence="e")
    assert first["finding_id"] == "F-0002"


def test_mcp_dispatch_returns_error_on_unexpected_exception(tmp_path: Path, monkeypatch) -> None:
    import opencrow_lifecycle.mcp_server as server_mod

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(server_mod, "call_tool", _boom)
    server = StdioServer(tmp_path)
    response = server.dispatch(
        {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "workflow_status", "arguments": {}}}
    )
    assert response is not None
    assert response["id"] == 7
    assert response["error"]["code"] == -32603


def test_concurrent_attempts_keep_all_entries(tmp_path: Path) -> None:
    _init(tmp_path)
    helper = (
        "import sys; from pathlib import Path; "
        "sys.path.insert(0, 'PACKAGES'); "
        "from opencrow_lifecycle.engine import WorkflowEngine; "
        "ws=Path(RWS); e=WorkflowEngine(ws); "
        "e.record_attempt(hypothesis='h'+IDX, action='a', command='c', "
        "outcome='o', evidence='e', status='succeeded', next_action='n')"
    )
    packages = str(Path(__file__).resolve().parents[1])
    procs = []
    count = 8
    for i in range(count):
        code = helper.replace("PACKAGES", packages).replace("RWS", repr(str(tmp_path))).replace("IDX", repr(str(i)))
        procs.append(subprocess.Popen([sys.executable, "-c", code]))
    for proc in procs:
        assert proc.wait(timeout=60) == 0
    text = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    ids = re.findall(r"## (A-\d+)", text)
    assert len(ids) == count
    assert len(set(ids)) == count
