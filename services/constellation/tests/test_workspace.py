"""Unit tests for Constellation workspace.py."""

from __future__ import annotations

from pathlib import Path
from constellation.config import load_client_settings
from constellation.workspace import (
    state_dir,
    state_path,
    watcher_log_path,
    watcher_pid_path,
    ensure_state_dir,
    read_workspace_state,
    write_workspace_state,
)


def test_workspace_paths(tmp_path):
    settings = load_client_settings(overrides={"state_dir_name": ".opencrow-test"})
    sd = state_dir(tmp_path, settings)
    assert sd == tmp_path / ".opencrow-test"

    sp = state_path(tmp_path, settings)
    assert sp == tmp_path / ".opencrow-test" / "state.json"

    lp = watcher_log_path(tmp_path, settings)
    assert lp == tmp_path / ".opencrow-test" / "watcher.log"

    pp = watcher_pid_path(tmp_path, settings)
    assert pp == tmp_path / ".opencrow-test" / "watcher.pid"


def test_workspace_state_rw(tmp_path):
    settings = load_client_settings()
    ensure_state_dir(tmp_path, settings)

    assert read_workspace_state(tmp_path, settings) == {}

    data = {"topic": "test-topic", "agent_id": "agent-123"}
    write_workspace_state(tmp_path, settings, data)

    read_back = read_workspace_state(tmp_path, settings)
    assert read_back == data
