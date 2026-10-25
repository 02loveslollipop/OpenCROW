from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/minecraft-async/scripts"))

import minecraft_async as mc


def _namespace(**overrides) -> argparse.Namespace:
    base = {"session": "default", "game_dir": None, "username": None, "timeout": 5.0}
    base.update(overrides)
    return argparse.Namespace(**base)


def test_username_from_log_matches():
    text = "[12:00:01] [Render thread/INFO]: Setting user: codextest\n"
    assert mc.username_from_log(text) == "codextest"


def test_username_from_log_last_wins_and_none():
    text = "Setting user: old\nnoise\nSetting user: new\n"
    assert mc.username_from_log(text) == "new"
    assert mc.username_from_log("booting...\nno profile yet\n") is None


def test_verify_identity_ok(tmp_path: Path):
    game_dir = tmp_path / "game"
    (game_dir / "logs").mkdir(parents=True)
    (game_dir / "logs" / "latest.log").write_text(
        "[12:00:01] [Render thread/INFO]: Setting user: codextest\n", encoding="utf-8"
    )
    assert mc.cmd_verify_identity(_namespace(game_dir=str(game_dir), username="codextest")) == 0


def test_verify_identity_mismatch_raises(tmp_path: Path):
    game_dir = tmp_path / "game"
    (game_dir / "logs").mkdir(parents=True)
    (game_dir / "logs" / "latest.log").write_text("Setting user: 02loveslollipop\n", encoding="utf-8")
    with pytest.raises(mc.McError, match="expected 'codextest'"):
        mc.cmd_verify_identity(_namespace(game_dir=str(game_dir), username="codextest"))


def test_verify_identity_times_out_without_line(tmp_path: Path):
    game_dir = tmp_path / "game"
    (game_dir / "logs").mkdir(parents=True)
    with pytest.raises(mc.McError, match="No 'Setting user:'"):
        mc.cmd_verify_identity(_namespace(game_dir=str(game_dir), username="codextest", timeout=0.1))


def test_wait_finds_line_split_across_polls(tmp_path: Path):
    latest = tmp_path / "latest.log"
    latest.write_text("[12:00:01] [Render thread/INFO]: Setting us", encoding="utf-8")

    def append_rest():
        time.sleep(0.2)
        with latest.open("a", encoding="utf-8") as handle:
            handle.write("er: codextest\n")

    thread = threading.Thread(target=append_rest)
    thread.start()
    try:
        assert mc.wait_for_identity(latest, 5.0) == "codextest"
    finally:
        thread.join(timeout=10)


def test_wait_resets_on_log_rotation(tmp_path: Path):
    latest = tmp_path / "latest.log"
    latest.write_text("booting\n", encoding="utf-8")
    assert mc.wait_for_identity(latest, 0.2) is None
    latest.write_text("Setting user: codextest\n", encoding="utf-8")
    assert mc.wait_for_identity(latest, 2.0) == "codextest"


def test_wait_never_sleeps_past_deadline(tmp_path: Path):
    latest = tmp_path / "missing.log"
    start = time.monotonic()
    assert mc.wait_for_identity(latest, 0.2) is None
    assert time.monotonic() - start < 0.4


def test_verify_identity_defaults_to_session_meta(tmp_path: Path, monkeypatch):
    game_dir = tmp_path / "game"
    (game_dir / "logs").mkdir(parents=True)
    (game_dir / "logs" / "latest.log").write_text("Setting user: codextest\n", encoding="utf-8")
    monkeypatch.setattr(mc, "load_meta", lambda name: {"username": "codextest"})
    assert mc.cmd_verify_identity(_namespace(game_dir=str(game_dir))) == 0


def test_build_direct_command_propagates_username(tmp_path: Path):
    game_dir = tmp_path / "game"
    version_dir = game_dir / "versions" / "1.21.8"
    version_dir.mkdir(parents=True)
    (version_dir / "1.21.8.json").write_text(
        json.dumps(
            {
                "id": "1.21.8",
                "type": "release",
                "mainClass": "net.minecraft.client.main.Main",
                "javaVersion": {},
                "arguments": {
                    "game": ["--username", "${auth_player_name}", "--uuid", "${auth_uuid}"],
                    "jvm": [],
                },
            }
        ),
        encoding="utf-8",
    )
    (version_dir / "1.21.8.jar").write_bytes(b"fake")
    cmd, meta = mc.build_direct_command(
        game_dir=game_dir,
        version_id="1.21.8",
        username="codextest",
        session="s",
        width=None,
        height=None,
        java_override="/usr/bin/true",
        min_memory=512,
        max_memory=1024,
        server=None,
        world=None,
    )
    assert "--username" in cmd
    assert cmd[cmd.index("--username") + 1] == "codextest"
    assert cmd[cmd.index("--uuid") + 1] == mc.offline_uuid("codextest")
    assert meta["username"] == "codextest"


@pytest.mark.parametrize("legacy", [False, True])
def test_direct_command_overrides_literal_and_duplicate_identity(tmp_path, monkeypatch, legacy):
    monkeypatch.setattr(mc, "BASE_DIR", tmp_path / "sessions")
    version = tmp_path / "versions/test"
    version.mkdir(parents=True)
    game = ["--username", "stored-user", "--username=other-user", "--uuid", "stored-uuid", "--accessToken=stored-token", "--userType", "msa"]
    data = {"mainClass": "Main"}
    if legacy:
        data["minecraftArguments"] = " ".join(game)
    else:
        data["arguments"] = {"game": game, "jvm": []}
    (version / "test.json").write_text(json.dumps(data))
    (version / "test.jar").write_bytes(b"fake")
    cmd, _ = mc.build_direct_command(tmp_path, "test", "codextest", "test", None, None, "/usr/bin/true", 512, 1024, None, None)
    for option, value in [("--username", "codextest"), ("--uuid", mc.offline_uuid("codextest")), ("--accessToken", "0"), ("--userType", "legacy")]:
        assert cmd.count(option) == 1
        assert cmd[cmd.index(option) + 1] == value
    assert not any("stored" in arg or "other-user" in arg for arg in cmd)


@pytest.mark.parametrize("username", ["", "bad name", "x" * 17, "雪"])
def test_direct_command_rejects_invalid_offline_username(tmp_path, username):
    with pytest.raises(mc.McError, match="Offline username"):
        mc.build_direct_command(tmp_path, "unused", username, "test", None, None, None, 512, 1024, None, None)


def test_launch_verifies_child_log_without_reusing_latest_log(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "BASE_DIR", tmp_path / "sessions")
    latest = tmp_path / "logs/latest.log"
    latest.parent.mkdir()
    latest.write_text("Setting user: stored-user\n")
    meta = {"backend": "direct", "username": "codextest", "game_dir": str(tmp_path)}
    command = [sys.executable, "-c", "import time; print('Setting user: codextest', flush=True); time.sleep(30)"]
    try:
        assert mc.start_session("test", command, meta, False) == 0
        assert mc.load_meta("test")["identity_verified"] is True
        assert latest.read_text() == "Setting user: stored-user\n"
        assert mc.cmd_verify_identity(_namespace(session="test")) == 0
    finally:
        pid = mc.read_pid("test")
        if pid:
            os.killpg(pid, signal.SIGTERM)
            os.waitpid(pid, 0)


def test_launch_fails_and_stops_child_with_wrong_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "BASE_DIR", tmp_path / "sessions")
    meta = {"backend": "direct", "username": "codextest"}
    command = [sys.executable, "-c", "import time; print('Setting user: wrong', flush=True); time.sleep(30)"]
    with pytest.raises(mc.McError, match="Offline identity verification failed"):
        mc.start_session("test", command, meta, False)
    assert mc.read_pid("test") is None
    assert mc.load_meta("test")["identity_verified"] is False
