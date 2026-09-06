from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import opencrow_agy_mcp


def test_agy_worker_verify_reports_availability() -> None:
    result = opencrow_agy_mcp.toolbox_verify({})
    assert result["ok"] is True
    assert result["operation"] == "toolbox_verify"
    assert "observations" in result
    assert result["observations"][0]["dependency"] == "agy"


def test_agy_worker_execute_requires_task() -> None:
    result = opencrow_agy_mcp.agy_execute({})
    assert result["ok"] is False
    assert result["exit_code"] == 2
    assert "required" in result["summary"].lower()


def test_agy_worker_execute_validates_workspace(tmp_path: Path) -> None:
    non_existent = tmp_path / "does_not_exist"
    result = opencrow_agy_mcp.agy_execute({"task": "hello", "workspace": str(non_existent)})
    assert result["ok"] is False
    assert result["exit_code"] == 2
    assert "does not exist" in result["summary"].lower()


def test_agy_worker_execute_mock_success(tmp_path: Path) -> None:
    mock_payload = {
        "conversation_id": "test-conv-1234",
        "status": "SUCCESS",
        "response": "Created file sample.py",
        "duration_seconds": 2.5,
        "num_turns": 1,
        "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
    }

    with patch.object(
        opencrow_agy_mcp,
        "_run_agy_turn",
        return_value=(True, mock_payload, json.dumps(mock_payload), "", 0),
    ):
        result = opencrow_agy_mcp.agy_execute({"task": "Create sample.py", "workspace": str(tmp_path)})

    assert result["ok"] is True
    assert result["operation"] == "agy_execute"
    obs = result["observations"][0]
    assert obs["conversation_id"] == "test-conv-1234"
    assert obs["response"] == "Created file sample.py"
    assert obs["num_turns"] == 1


def test_agy_worker_chat_requires_params() -> None:
    # Missing conversation_id
    res1 = opencrow_agy_mcp.agy_chat({"message": "test"})
    assert res1["ok"] is False
    assert res1["exit_code"] == 2

    # Missing message
    res2 = opencrow_agy_mcp.agy_chat({"conversation_id": "conv-1"})
    assert res2["ok"] is False
    assert res2["exit_code"] == 2


def test_agy_worker_chat_mock_continuation(tmp_path: Path) -> None:
    mock_payload = {
        "conversation_id": "test-conv-1234",
        "status": "SUCCESS",
        "response": "Updated sample.py with new logic",
        "duration_seconds": 1.8,
        "num_turns": 2,
        "usage": {"input_tokens": 200, "output_tokens": 80, "total_tokens": 280},
    }

    with patch.object(
        opencrow_agy_mcp,
        "_run_agy_turn",
        return_value=(True, mock_payload, json.dumps(mock_payload), "", 0),
    ):
        result = opencrow_agy_mcp.agy_chat(
            {"conversation_id": "test-conv-1234", "message": "Now add error handling", "workspace": str(tmp_path)}
        )

    assert result["ok"] is True
    assert result["operation"] == "agy_chat"
    obs = result["observations"][0]
    assert obs["conversation_id"] == "test-conv-1234"
    assert obs["num_turns"] == 2


def test_agy_worker_session_status_and_stop() -> None:
    opencrow_agy_mcp._SESSIONS["session-abc"] = {
        "conversation_id": "session-abc",
        "workspace": "/tmp",
        "turns": 3,
        "last_task": "fix code",
        "updated_at": "2026-09-05T00:00:00Z",
    }

    status = opencrow_agy_mcp.agy_session_status({"conversation_id": "session-abc"})
    assert status["ok"] is True
    assert status["observations"][0]["conversation_id"] == "session-abc"

    # Stop session
    stop = opencrow_agy_mcp.agy_session_stop({"conversation_id": "session-abc"})
    assert stop["ok"] is True
    assert stop["observations"][0]["unregistered"] is True
    assert "session-abc" not in opencrow_agy_mcp._SESSIONS
