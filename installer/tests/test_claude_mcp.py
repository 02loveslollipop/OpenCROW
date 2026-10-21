"""Regression tests: the Claude Code lifecycle MCP server must be registered
where Claude Code reads it (user scope, ~/.claude.json), not in
~/.claude/settings.json, and `doctor` must notice when it is missing.

Pre-fix behavior these tests pin down: the installer merged `mcpServers` into
settings.json, `claude mcp list` never showed `opencrow-lifecycle`, and
`opencrow doctor` still reported the claude integration healthy.

The `claude` CLI is the fake from conftest.py; its behaviors are the ones
observed on the real CLI (see the mock-fidelity notes there).
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from opencrow_manager import InstallError, Paths, StateEngine


REPOSITORY = Path(__file__).resolve().parents[2]
SERVER = {"type": "stdio", "command": "opencrow-lifecycle-mcp", "args": []}


def paths_for(tmp_path: Path) -> Paths:
    home = tmp_path / "home"
    return Paths(home=home, data=home / ".local/share/opencrow", state=home / ".local/state/opencrow", bin=home / ".local/bin")


def user_config(paths: Paths) -> dict:
    return json.loads((paths.home / ".claude.json").read_text())


def cli_calls(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text().splitlines()]


def without_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    real_which = __import__("shutil").which
    monkeypatch.setattr("opencrow_manager.shutil.which", lambda name: None if name == "claude" else real_which(name))


def test_server_is_registered_in_user_scope_not_settings(tmp_path: Path, fake_claude_cli: Path) -> None:
    """Core regression. Also checks the CLI runs against the managed home and
    ignores an inherited CLAUDE_CONFIG_DIR, so a test or alternate home can
    never write into the operator's real Claude config."""
    paths = paths_for(tmp_path)
    StateEngine(paths).install(source=REPOSITORY, mode="full", agents=["claude"])

    assert user_config(paths)["mcpServers"]["opencrow-lifecycle"] == SERVER
    settings = json.loads((paths.home / ".claude/settings.json").read_text())
    assert "mcpServers" not in settings
    assert "opencrow-lifecycle-hook session_start --provider claude" in json.dumps(settings["hooks"])
    mcp_calls = [c for c in cli_calls(fake_claude_cli) if c["args"][:1] == ["mcp"]]
    assert mcp_calls[-1]["args"][:4] == ["mcp", "add-json", "--scope", "user"]
    assert all(c["home"] == str(paths.home) and c["claude_config_dir"] is None for c in mcp_calls)


def test_reinstall_replaces_a_stale_definition(tmp_path: Path) -> None:
    """The real CLI refuses `add-json` for an existing name; without the
    remove-first step a second install (update, repair) would fail."""
    paths = paths_for(tmp_path)
    engine = StateEngine(paths)
    engine.install(source=REPOSITORY, mode="full", agents=["claude"])
    config = user_config(paths)
    config["mcpServers"]["opencrow-lifecycle"] = {"type": "stdio", "command": "old-binary", "args": []}
    (paths.home / ".claude.json").write_text(json.dumps(config))

    engine.repair()

    assert user_config(paths)["mcpServers"]["opencrow-lifecycle"] == SERVER


def test_legacy_settings_entry_is_migrated_and_user_servers_survive(tmp_path: Path) -> None:
    """Upgrade path for installs made before the fix: our dead entry leaves
    settings.json, the user's own entries and keys stay untouched."""
    paths = paths_for(tmp_path)
    settings = paths.home / ".claude/settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({
        "theme": "dark",
        "mcpServers": {"opencrow-lifecycle": SERVER, "mine": {"type": "stdio", "command": "x", "args": []}},
    }))
    StateEngine(paths).install(source=REPOSITORY, mode="full", agents=["claude"])

    value = json.loads(settings.read_text())
    assert value["theme"] == "dark"
    assert value["mcpServers"] == {"mine": {"type": "stdio", "command": "x", "args": []}}
    assert "opencrow-lifecycle" in user_config(paths)["mcpServers"]


def test_legacy_only_entry_leaves_no_empty_mcp_servers(tmp_path: Path) -> None:
    paths = paths_for(tmp_path)
    settings = paths.home / ".claude/settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"mcpServers": {"opencrow-lifecycle": SERVER}}))
    StateEngine(paths).install(source=REPOSITORY, mode="full", agents=["claude"])
    assert "mcpServers" not in json.loads(settings.read_text())


def test_without_cli_merges_user_config_atomically_and_privately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fallback when `claude` is not on PATH (skills-only hosts, CI): every
    existing key and server is preserved, the file stays 0600 because it holds
    account metadata, and a backup is recorded before the write."""
    without_cli(monkeypatch)
    paths = paths_for(tmp_path)
    config = paths.home / ".claude.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"numStartups": 7, "mcpServers": {"mine": {"command": "x"}}}))
    config.chmod(0o600)

    state = StateEngine(paths).install(source=REPOSITORY, mode="full", agents=["claude"])

    value = user_config(paths)
    assert value["numStartups"] == 7
    assert value["mcpServers"] == {"mine": {"command": "x"}, "opencrow-lifecycle": SERVER}
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert any(b["path"] == str(config) for b in state["config_backups"])


def test_without_cli_new_user_config_is_created_private(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    without_cli(monkeypatch)
    paths = paths_for(tmp_path)
    StateEngine(paths).install(source=REPOSITORY, mode="full", agents=["claude"])
    config = paths.home / ".claude.json"
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert user_config(paths) == {"mcpServers": {"opencrow-lifecycle": SERVER}}


@pytest.mark.parametrize("content", ["not json", "[]", ""])
def test_unparseable_user_config_fails_closed_and_is_not_touched(
    tmp_path: Path, fake_claude_cli: Path, content: str
) -> None:
    """Fail closed: the real CLI replaces an unparseable .claude.json with a
    fresh file. The installer must refuse before calling it and leave the bytes
    exactly as they were (covers non-JSON, a non-object, and an empty file)."""
    paths = paths_for(tmp_path)
    config = paths.home / ".claude.json"
    config.parent.mkdir(parents=True)
    config.write_text(content)

    with pytest.raises(InstallError, match="Claude Code config"):
        StateEngine(paths).install(source=REPOSITORY, mode="full", agents=["claude"])

    assert config.read_text() == content
    assert not [c for c in cli_calls(fake_claude_cli) if c["args"][:1] == ["mcp"]]


def test_cli_rejection_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_FAIL_ADD", "1")
    paths = paths_for(tmp_path)
    with pytest.raises(InstallError, match="rejected the lifecycle MCP registration: simulated failure"):
        StateEngine(paths).install(source=REPOSITORY, mode="full", agents=["claude"])


def test_doctor_reports_missing_server(tmp_path: Path) -> None:
    """Pre-fix, doctor said healthy while Claude Code could not see the server."""
    paths = paths_for(tmp_path)
    engine = StateEngine(paths)
    engine.install(source=REPOSITORY, mode="full", agents=["claude"])
    assert engine.doctor()["ok"] is True

    config = user_config(paths)
    del config["mcpServers"]["opencrow-lifecycle"]
    (paths.home / ".claude.json").write_text(json.dumps(config))

    report = engine.doctor()
    claude = next(i for i in report["integrations"] if i["provider"] == "claude")
    assert report["ok"] is False
    assert claude["healthy"] is False and claude["lifecycle_mcp_registered"] is False
    assert any("opencrow integrations repair" in issue for issue in report["issues"])

    engine.repair()
    assert engine.doctor()["ok"] is True


def test_unselected_claude_does_not_affect_doctor(tmp_path: Path) -> None:
    paths = paths_for(tmp_path)
    engine = StateEngine(paths)
    engine.install(source=REPOSITORY, mode="full", agents=["codex"])
    assert engine.doctor()["ok"] is True
    assert not (paths.home / ".claude.json").exists()


@pytest.mark.parametrize("with_cli", [True, False])
def test_deselect_and_uninstall_remove_only_our_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_cli: bool
) -> None:
    """Removal through the CLI and through the fallback must both keep the
    user's other servers and keys."""
    if not with_cli:
        without_cli(monkeypatch)
    paths = paths_for(tmp_path)
    engine = StateEngine(paths)
    engine.install(source=REPOSITORY, mode="full", agents=["codex", "claude"])
    config = user_config(paths)
    config["numStartups"] = 3
    config["mcpServers"]["mine"] = {"type": "stdio", "command": "x", "args": []}
    (paths.home / ".claude.json").write_text(json.dumps(config))

    engine.install(source=REPOSITORY, mode="full", agents=["codex"])
    after_deselect = user_config(paths)
    assert after_deselect["numStartups"] == 3
    assert after_deselect["mcpServers"] == {"mine": {"type": "stdio", "command": "x", "args": []}}

    engine.install(source=REPOSITORY, mode="full", agents=["codex", "claude"])
    engine.uninstall(purge_env=False, purge_system=False, purge_agent_clis=False)
    assert "opencrow-lifecycle" not in user_config(paths)["mcpServers"]
    assert "mine" in user_config(paths)["mcpServers"]


def test_uninstall_never_rewrites_an_unparseable_user_config(tmp_path: Path) -> None:
    paths = paths_for(tmp_path)
    engine = StateEngine(paths)
    engine.install(source=REPOSITORY, mode="full", agents=["claude"])
    config = paths.home / ".claude.json"
    config.write_text("corrupted by something else")
    engine.uninstall(purge_env=False, purge_system=False, purge_agent_clis=False)
    assert config.read_text() == "corrupted by something else"


def test_real_home_is_never_used(tmp_path: Path, fake_claude_cli: Path) -> None:
    """Defense for the operator running the suite: nothing may reach the
    developer's own ~/.claude.json."""
    paths = paths_for(tmp_path)
    StateEngine(paths).install(source=REPOSITORY, mode="full", agents=["claude"])
    homes = {c["home"] for c in cli_calls(fake_claude_cli) if c["args"][:1] == ["mcp"]}
    assert homes == {str(paths.home)} and os.path.expanduser("~") not in homes
