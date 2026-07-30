"""Unit tests for opencrow_mcp_core.py."""

from __future__ import annotations

from pathlib import Path
import pytest

from opencrow_mcp_core import (
    normalize_path,
    summarize_command,
    decode_output,
    run_command,
    success_envelope,
    error_envelope,
    missing_dependency_envelope,
    serialize_tool_result,
    StdioMCPServer,
)


def test_normalize_path(tmp_path):
    assert normalize_path(None) is None
    p = normalize_path(tmp_path)
    assert p == str(tmp_path.resolve())


def test_summarize_command():
    assert summarize_command(["echo", "hello world"]) == "echo \"hello world\""


def test_decode_output():
    assert decode_output(None) == ""
    assert decode_output("text") == "text"
    assert decode_output(b"bytes\xff") == "bytes\ufffd"


def test_run_command_success():
    res = run_command(["echo", "test"])
    assert res["ok"] is True
    assert "test" in res["stdout"]
    assert res["exit_code"] == 0


def test_run_command_not_found():
    res = run_command(["nonexistent_executable_binary_12345"])
    assert res["ok"] is False
    assert res["exit_code"] == 127


def test_envelopes():
    s = success_envelope(
        toolbox="test-toolbox",
        operation="op1",
        summary="Success summary",
        inputs={"param": 1},
    )
    assert s["ok"] is True
    assert s["toolbox"] == "test-toolbox"

    e = error_envelope(
        toolbox="test-toolbox",
        operation="op1",
        summary="Error summary",
        inputs={"param": 1},
    )
    assert e["ok"] is False

    m = missing_dependency_envelope("test-toolbox", "op1", "gdb", {"param": 1})
    assert m["ok"] is False
    assert "gdb" in m["summary"]


def test_serialize_tool_result():
    env = success_envelope(
        toolbox="tb",
        operation="op",
        summary="Done",
        inputs={},
    )
    res = serialize_tool_result(env)
    assert "content" in res
    assert res["isError"] is False
