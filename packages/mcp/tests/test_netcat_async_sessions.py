from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest


REPOSITORY = Path(__file__).resolve().parents[3]
BACKEND = REPOSITORY / "skills/netcat-async/scripts/nc_async_session.py"
RSX = REPOSITORY / "skills/reverse-shell-async/scripts/rsx"


def backend_environment(base_dir: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["OPENCROW_NC_ASYNC_DIR"] = str(base_dir)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def run_backend(
    base_dir: Path,
    *arguments: str,
    check: bool = True,
    timeout: float = 10,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(BACKEND), *arguments],
        env=backend_environment(base_dir),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"backend failed: {result.args}\n{result.stdout}\n{result.stderr}")
    return result


def session_status(base_dir: Path, name: str) -> dict[str, object]:
    return json.loads(run_backend(base_dir, "status", "--name", name).stdout)


def wait_for_state(base_dir: Path, name: str, expected: str, timeout: float = 5) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    latest: dict[str, object] = {}
    while time.monotonic() < deadline:
        latest = session_status(base_dir, name)
        if latest.get("state") == expected:
            return latest
        time.sleep(0.05)
    raise AssertionError(f"session {name!r} did not reach {expected!r}: {latest}")


def stop_if_running(base_dir: Path, name: str) -> None:
    meta = base_dir / name / "meta.json"
    if meta.exists():
        run_backend(base_dir, "stop", "--name", name, check=False)


def receive_exact(client: socket.socket, size: int) -> bytes:
    result = bytearray()
    while len(result) < size:
        chunk = client.recv(size - len(result))
        if not chunk:
            break
        result.extend(chunk)
    return bytes(result)


def load_backend_module():
    specification = importlib.util.spec_from_file_location("opencrow_test_nc_async", BACKEND)
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_listener_port_zero_text_raw_capture_restart_and_timeout(tmp_path: Path) -> None:
    base_dir = tmp_path / "sessions"
    name = "listener"
    client: socket.socket | None = None
    try:
        run_backend(
            base_dir,
            "listen",
            "--name",
            name,
            "--port",
            "0",
            "--expected-peer",
            "127.0.0.0/8",
        )
        listening = session_status(base_dir, name)
        assert listening["mode"] == "listen"
        assert listening["state"] == "listening"
        assert listening["bind_host"] == "127.0.0.1"
        assert isinstance(listening["port"], int) and listening["port"] > 0

        client = socket.create_connection(("127.0.0.1", int(listening["port"])), timeout=2)
        client.settimeout(2)
        connected = wait_for_state(base_dir, name, "connected")
        assert connected["peer_host"] == "127.0.0.1"

        run_backend(base_dir, "send", "--name", name, "--data", "whoami", "--newline")
        assert receive_exact(client, 7) == b"whoami\n"
        run_backend(base_dir, "send", "--name", name, "--hex", "03")
        assert receive_exact(client, 1) == b"\x03"
        run_backend(base_dir, "send", "--name", name, "--base64", "AP8=")
        assert receive_exact(client, 2) == b"\x00\xff"

        received = b"answer\x00\x1b\xff\n"
        client.sendall(received)
        raw_path = base_dir / name / "rx.raw"
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and raw_path.read_bytes() != received:
            time.sleep(0.05)
        assert raw_path.read_bytes() == received
        log_path = base_dir / name / "io.log"
        deadline = time.monotonic() + 3
        log = log_path.read_text(encoding="utf-8")
        while time.monotonic() < deadline and "answer\\x00\\x1b\\xff\\n" not in log:
            time.sleep(0.05)
            log = log_path.read_text(encoding="utf-8")
        assert "answer\\x00\\x1b\\xff\\n" in log
        assert "\x1b" not in log

        client.close()
        client = None
        closed = wait_for_state(base_dir, name, "remote_closed")
        assert closed["running"] is False

        run_backend(
            base_dir,
            "listen",
            "--name",
            name,
            "--port",
            "0",
            "--accept-timeout",
            "0.25",
        )
        timed_out = wait_for_state(base_dir, name, "accept_timeout")
        assert timed_out["running"] is False
        assert raw_path.read_bytes() == b""
    finally:
        if client is not None:
            client.close()
        stop_if_running(base_dir, name)


def test_remote_bind_requires_opt_in_and_peer_filter_keeps_listening(tmp_path: Path) -> None:
    base_dir = tmp_path / "sessions"
    denied = run_backend(
        base_dir,
        "listen",
        "--name",
        "denied",
        "--bind-host",
        "0.0.0.0",
        "--port",
        "0",
        check=False,
    )
    assert denied.returncode == 2
    assert "--allow-remote" in denied.stderr

    name = "filtered"
    try:
        run_backend(
            base_dir,
            "listen",
            "--name",
            name,
            "--bind-host",
            "0.0.0.0",
            "--allow-remote",
            "--expected-peer",
            "192.0.2.0/24",
            "--port",
            "0",
        )
        port = int(session_status(base_dir, name)["port"])
        rejected = socket.create_connection(("127.0.0.1", port), timeout=2)
        rejected.settimeout(2)
        assert rejected.recv(1) == b""
        rejected.close()

        deadline = time.monotonic() + 3
        log_path = base_dir / name / "io.log"
        while time.monotonic() < deadline and "[REJECT]" not in log_path.read_text(encoding="utf-8"):
            time.sleep(0.05)
        assert "did not match 192.0.2.0/24" in log_path.read_text(encoding="utf-8")
        status = session_status(base_dir, name)
        assert status["state"] == "listening"
        assert status["running"] is True
        run_backend(base_dir, "stop", "--name", name)
        stopped = session_status(base_dir, name)
        assert stopped["state"] == "stopped"
        assert stopped["running"] is False
    finally:
        stop_if_running(base_dir, name)

    accepted_name = "remote-opt-in"
    client: socket.socket | None = None
    try:
        run_backend(
            base_dir,
            "listen",
            "--name",
            accepted_name,
            "--bind-host",
            "0.0.0.0",
            "--allow-remote",
            "--expected-peer",
            "127.0.0.1/32",
            "--port",
            "0",
        )
        port = int(session_status(base_dir, accepted_name)["port"])
        client = socket.create_connection(("127.0.0.1", port), timeout=2)
        assert wait_for_state(base_dir, accepted_name, "connected")["peer_host"] == "127.0.0.1"
    finally:
        if client is not None:
            client.close()
        stop_if_running(base_dir, accepted_name)


def test_payload_validation_and_listener_only_wrapper(tmp_path: Path) -> None:
    module = load_backend_module()

    def arguments(**updates: object) -> argparse.Namespace:
        values = {"data": None, "hex_data": None, "base64_data": None, "newline": False}
        values.update(updates)
        return argparse.Namespace(**values)

    assert module.decode_payload(arguments(hex_data="00 03\nff")) == b"\x00\x03\xff"
    assert module.decode_payload(arguments(base64_data="AAEC/w==")) == b"\x00\x01\x02\xff"
    with pytest.raises(module.SessionError, match="even number"):
        module.decode_payload(arguments(hex_data="0"))
    with pytest.raises(module.SessionError, match="Invalid hex"):
        module.decode_payload(arguments(hex_data="zz"))
    with pytest.raises(module.SessionError, match="Invalid base64"):
        module.decode_payload(arguments(base64_data="AA E="))
    with pytest.raises(module.SessionError, match="only valid with --data"):
        module.decode_payload(arguments(hex_data="03", newline=True))
    with pytest.raises(module.SessionError, match="1 payload representation|Exactly one"):
        module.decode_payload(arguments())
    oversized = base64.b64encode(b"x" * (module.MAX_SEND_BYTES + 1)).decode("ascii")
    with pytest.raises(module.SessionError, match="exceeds"):
        module.decode_payload(arguments(base64_data=oversized))

    multiple = run_backend(
        tmp_path / "sessions",
        "send",
        "--name",
        "invalid",
        "--data",
        "x",
        "--hex",
        "00",
        check=False,
    )
    assert multiple.returncode == 2
    invalid_name = run_backend(tmp_path / "sessions", "status", "--name", "../escape", check=False)
    assert invalid_name.returncode == 2

    for forbidden in ("start", "generate", "payload"):
        result = subprocess.run(
            [str(RSX), forbidden],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 2
        assert "listener-only" in result.stderr


def test_outbound_session_start_remains_compatible(tmp_path: Path) -> None:
    base_dir = tmp_path / "sessions"
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = int(server.getsockname()[1])
    received: list[bytes] = []

    def serve() -> None:
        connection, _ = server.accept()
        with connection:
            connection.sendall(b"ready\n")
            received.append(receive_exact(connection, 5))

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        run_backend(
            base_dir,
            "start",
            "--name",
            "outbound",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        )
        assert session_status(base_dir, "outbound")["mode"] == "connect"
        run_backend(base_dir, "send", "--name", "outbound", "--data", "ping", "--newline")
        thread.join(timeout=3)
        assert received == [b"ping\n"]
        wait_for_state(base_dir, "outbound", "remote_closed")
        assert (base_dir / "outbound/rx.raw").read_bytes() == b"ready\n"
    finally:
        server.close()
        stop_if_running(base_dir, "outbound")


def test_netcat_mcp_listener_schema_handlers_and_raw_send(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import opencrow_netcat_mcp as module

    base_dir = tmp_path / "mcp-sessions"
    monkeypatch.setenv("OPENCROW_NC_ASYNC_DIR", str(base_dir))
    monkeypatch.setattr(module, "SESSION_BASE_DIR", str(base_dir))
    server = module.build_server()
    listed = server._handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    tools = {tool["name"]: tool for tool in listed["result"]["tools"]}
    assert "session_listen" in tools
    assert len(tools["session_send"]["inputSchema"]["oneOf"]) == 3

    invalid = module.session_send({"name": "mcp", "data": "x", "hex": "78"})
    assert invalid["ok"] is False
    assert invalid["exit_code"] == 2

    client: socket.socket | None = None
    try:
        result = module.session_listen({"name": "mcp", "port": 0, "expected_peer": "127.0.0.0/8"})
        assert result["ok"] is True, result
        observation = result["observations"][0]
        assert observation["state"] == "listening"
        client = socket.create_connection(("127.0.0.1", int(observation["port"])), timeout=2)
        wait_for_state(base_dir, "mcp", "connected")

        sent = module.session_send({"name": "mcp", "hex": "03 ff"})
        assert sent["ok"] is True, sent
        assert receive_exact(client, 2) == b"\x03\xff"
        client.sendall(b"mcp\x00response")
        raw_path = base_dir / "mcp/rx.raw"
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and raw_path.read_bytes() != b"mcp\x00response":
            time.sleep(0.05)
        assert raw_path.read_bytes() == b"mcp\x00response"
        status = module.session_status({"name": "mcp"})
        assert status["ok"] is True
        assert status["observations"][0]["mode"] == "listen"
    finally:
        if client is not None:
            client.close()
        module.session_stop({"name": "mcp"})


def test_reverse_shell_skill_is_provider_neutral_and_complete() -> None:
    skill = REPOSITORY / "skills/reverse-shell-async/SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert text.startswith("---\nname: reverse-shell-async\n")
    assert "OpenCROW I/O - Reverse Shell Async" in text
    assert "does not generate" in text
    assert "~/.codex" not in text
    assert "scripts/rsx" in text
    assert (REPOSITORY / "skills/reverse-shell-async/references/operations.md").is_file()
    assert os.access(RSX, os.X_OK)
    skills = list((REPOSITORY / "skills").glob("*/SKILL.md"))
    assert len(skills) == 14
