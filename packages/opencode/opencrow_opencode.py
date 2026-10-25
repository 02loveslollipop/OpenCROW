"""Shared OpenCode V2 SDK transport for workers, initializer and Constellation.

The owned Bun daemon multiplexes native sessions over a mode-0600 Unix socket.
Python turn proxies never start ``opencode run`` or own an external service.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import tempfile
import time

ROOT = Path(__file__).resolve().parent
VERSION = "2.1.4"
MAX_FRAME = 4 * 1024 * 1024


class SDKError(RuntimeError):
    pass


def form_answer(form: dict, message: str) -> dict:
    fields = form.get("fields", [])
    try:
        answer = json.loads(message)
    except ValueError:
        answer = None
    if isinstance(answer, dict):
        return answer
    if len(fields) != 1:
        raise SDKError("Reply to a multi-field native form with a JSON object keyed by field name")
    value = message if fields[0]["type"] == "string" else answer
    return {fields[0]["key"]: value}


def state_directory() -> Path:
    override = os.environ.get("OPENCROW_OPENCODE_STATE_DIR")
    base = Path(override).expanduser() if override else Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "opencrow/opencode"
    # Keep separate endpoints for separate SDK checkouts/services/credentials.
    identity = "\0".join([str(ROOT), VERSION, *(os.environ.get("OPENCROW_OPENCODE_" + name, "") for name in
        ("MODE", "URL", "TOKEN", "USERNAME", "PASSWORD", "REMOTE_ENV"))])
    return base / hashlib.sha256(identity.encode()).hexdigest()[:12]


def socket_path() -> Path:
    directory = state_directory()
    candidate = directory / "sdk.sock"
    if len(os.fsencode(candidate)) < 104:
        return candidate
    short = Path(tempfile.gettempdir()) / f"opencrow-sdk-{os.getuid()}"
    short.mkdir(mode=0o700, exist_ok=True)
    info = short.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise SDKError("Short OpenCode socket directory must be owned and mode 0700")
    return short / (hashlib.sha256(str(directory).encode()).hexdigest()[:24] + ".sock")


def _connect(timeout: float = 15) -> socket.socket:
    path = socket_path()
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(timeout)
    try:
        connection.connect(str(path))
    except BaseException:
        connection.close()
        raise
    return connection


def rpc(method: str, params: dict | None = None, *, timeout: float = 15):
    with _connect(timeout) as connection:
        connection.sendall((json.dumps({"id": 1, "method": method, "params": params or {}}) + "\n").encode())
        with connection.makefile("rb") as stream:
            line = stream.readline(MAX_FRAME + 1)
            if not line or len(line) > MAX_FRAME:
                raise SDKError("OpenCode host disconnected or exceeded its response limit; the request was not replayed")
            response = json.loads(line)
            if "error" in response:
                raise SDKError(response["error"]["message"])
            return response["result"]


def ensure_host() -> dict:
    directory = state_directory()
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = directory.lstat()
    if info.st_uid != os.getuid() or not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
        raise SDKError("OpenCode bridge state must be an owned, private mode-0700 directory")
    with (directory / "startup.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            return rpc("health", timeout=3)
        except (FileNotFoundError, ConnectionRefusedError):
            pass
        except (socket.timeout, TimeoutError) as error:
            raise SDKError("Existing OpenCode host did not answer; refusing to start a second host") from error
        override = os.environ.get("OPENCROW_BUN")
        bun = override or str(ROOT / "node_modules/.bin/bun")
        if not (Path(bun).is_file() and os.access(bun, os.X_OK)):
            bun = shutil.which(bun) or (shutil.which("bun") if not override else None)
        if not bun or not (ROOT / "node_modules/@opencode/sdk/package.json").is_file():
            raise SDKError(f"OpenCode V2 SDK runtime is missing; run npm ci --prefix {ROOT}")
        path = socket_path()
        if path.exists():
            metadata = path.lstat()
            if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.getuid():
                raise SDKError("Refusing to replace an unowned/non-socket bridge path")
            path.unlink()
        log = os.open(directory / "host.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            process = subprocess.Popen([bun, str(ROOT / "daemon.ts"), str(path), str(directory / "sessions.sqlite")], cwd=ROOT,
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
                env={key: value for key, value in os.environ.items() if not key.startswith("OPENCROW_WORKER_")})
        finally:
            os.close(log)
        threading.Thread(target=process.wait, daemon=True).start()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise SDKError(f"OpenCode SDK host initialization failed (exit {process.returncode}); inspect {directory / 'host.log'}; no CLI fallback was attempted")
            try:
                return rpc("health", timeout=3)
            except (FileNotFoundError, ConnectionRefusedError, socket.timeout):
                time.sleep(0.1)
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=5)
        raise SDKError("OpenCode SDK host startup timed out")


class Turn:
    def __init__(self, *, prompt: str, workspace: str | Path, session_id: str | None = None,
                 model: str | None = None, effort: str | None = None, full_auto: bool = True,
                 timeout_sec: int = 300) -> None:
        ensure_host()
        self.input = {"prompt": prompt, "workspace": str(Path(workspace).resolve()), "session_id": session_id,
                      "model": model, "effort": effort, "full_auto": full_auto, "timeout_sec": timeout_sec}
        self.input = {key: value for key, value in self.input.items() if value is not None}
        self.input["environment"] = {key: os.environ[key] for key in (
            "OPENCROW_WORKER_STATE_DIR", "OPENCROW_WORKER_ID", "OPENCROW_WORKER_TURN_TOKEN") if key in os.environ}
        self.provider_session_id = session_id
        self.pending_form: dict | None = None
        self._connection: socket.socket | None = None
        self._cancelled = threading.Event()

    def stream(self):
        if self._cancelled.is_set():
            raise SDKError("OpenCode turn was cancelled before admission")
        try:
            with _connect(self.input["timeout_sec"] + 20) as connection:
                self._connection = connection
                connection.sendall((json.dumps({"id": 1, "method": "turn", "params": self.input}) + "\n").encode())
                with connection.makefile("rb") as stream:
                    completed = False
                    while True:
                        line = stream.readline(MAX_FRAME + 1)
                        if not line or len(line) > MAX_FRAME:
                            raise SDKError("OpenCode SDK connection lost; inspect the native session before resuming; this turn was not replayed")
                        frame = json.loads(line)
                        if "error" in frame:
                            raise SDKError(frame["error"]["message"])
                        event = frame.get("event")
                        if event:
                            self.provider_session_id = event.get("session_id") or self.provider_session_id
                            if event.get("type") == "opencrow.v2.question":
                                self.pending_form = event["form"]
                            completed = completed or event.get("type") == "opencrow.v2.completed"
                            yield event
                        else:
                            if not completed:
                                raise SDKError("OpenCode ended without a verified terminal outcome")
                            return
        finally:
            self._connection = None

    def interrupt(self):
        self._cancelled.set()
        if self.provider_session_id:
            try:
                rpc("interrupt", {"session_id": self.provider_session_id}, timeout=7)
            except (OSError, SDKError):
                pass
        if self._connection:
            try:
                self._connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def reply(self, message: str):
        form = self.pending_form
        if not form or not self.provider_session_id:
            raise SDKError("No native OpenCode form is pending")
        result = rpc("form.reply", {"session_id": self.provider_session_id, "form_id": form["id"], "answer": form_answer(form, message)})
        self.pending_form = None
        return result


def turn_command(*, workspace: str | Path, session_id=None, model=None, effort=None, full_auto=True, timeout_sec=300):
    result = [sys.executable, str(Path(__file__).resolve()), "turn", "--workspace", str(workspace), "--timeout-sec", str(timeout_sec)]
    for option, value in (("--session-id", session_id), ("--model", model), ("--effort", effort)):
        if value:
            result.extend([option, value])
    if full_auto:
        result.append("--full-auto")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("health")
    sub.add_parser("close")
    turn = sub.add_parser("turn")
    turn.add_argument("--workspace", required=True)
    turn.add_argument("--session-id")
    turn.add_argument("--model")
    turn.add_argument("--effort")
    turn.add_argument("--timeout-sec", type=int, default=300)
    turn.add_argument("--full-auto", action="store_true")
    args = parser.parse_args()
    active = None
    try:
        if args.operation == "health":
            print(json.dumps(ensure_host()))
        elif args.operation == "close":
            print(json.dumps(rpc("close")))
        else:
            active = Turn(prompt=sys.stdin.read(), workspace=args.workspace, session_id=args.session_id,
                          model=args.model, effort=args.effort, full_auto=args.full_auto, timeout_sec=args.timeout_sec)
            def cancel(_signal, _frame):
                active.interrupt()
                raise SDKError("OpenCode turn cancelled")
            signal.signal(signal.SIGTERM, cancel)
            signal.signal(signal.SIGINT, cancel)
            for event in active.stream():
                print(json.dumps(event), flush=True)
                if not args.full_auto and event["type"] == "opencrow.v2.permission":
                    with open("/dev/tty", "r+") as tty:
                        tty.write(f"OpenCode permission {event['request']['action']}: approve once? [y/N] "); tty.flush()
                        decision = "once" if tty.readline().strip().lower() == "y" else "reject"
                    rpc("permission.reply", {"session_id": active.provider_session_id, "request_id": event["request"]["id"], "decision": decision})
                if event["type"] == "opencrow.v2.question" and not os.environ.get("OPENCROW_WORKER_ID"):
                    with open("/dev/tty", "r+") as tty:
                        tty.write(f"OpenCode asks: {event['form']['title']}\nReply (JSON object for multiple fields): "); tty.flush()
                        answer = tty.readline().rstrip("\n")
                    active.reply(answer)
    except (SDKError, OSError, ValueError) as error:
        if active:
            active.interrupt()
        print(json.dumps({"type": "opencrow.v2.failed", "session_id": active.provider_session_id if active else None, "error": str(error)}), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
