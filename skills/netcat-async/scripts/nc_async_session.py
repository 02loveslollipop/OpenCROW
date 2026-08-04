#!/usr/bin/env python3
"""Manage persistent asynchronous TCP connect and listen sessions."""

from __future__ import annotations

import argparse
import base64
import binascii
import ipaddress
import json
import os
import selectors
import signal
import socket
import subprocess
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BASE_DIR = Path(os.environ.get("OPENCROW_NC_ASYNC_DIR", "/tmp/opencrow-nc-async"))
ENCODING = "utf-8"
MAX_SEND_BYTES = 1024 * 1024


class SessionError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_session_name(name: str) -> str:
    normalized = str(name).strip()
    if not normalized:
        raise SessionError("Session name is required.")
    if normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
        raise SessionError(
            "Session name must be a single non-empty path segment without '/' or '\\' and cannot be '.' or '..'."
        )
    return normalized


def session_dir(name: str) -> Path:
    return BASE_DIR / validate_session_name(name)


def paths_for(name: str) -> dict[str, Path]:
    root = session_dir(name)
    return {
        "root": root,
        "pid": root / "pid",
        "meta": root / "meta.json",
        "fifo": root / "tx.fifo",
        "io_log": root / "io.log",
        "rx_raw": root / "rx.raw",
        "daemon_log": root / "daemon.log",
    }


def load_meta(name: str) -> dict:
    path = paths_for(name)["meta"]
    if not path.exists():
        raise SessionError(f"Session '{name}' has no metadata. Did you start it?")
    return json.loads(path.read_text(encoding=ENCODING))


def read_pid(name: str) -> Optional[int]:
    path = paths_for(name)["pid"]
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding=ENCODING).strip())
    except ValueError:
        return None


def is_alive(pid: Optional[int]) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        stat_path = Path(f"/proc/{pid}/stat")
        if stat_path.exists() and stat_path.read_text(encoding=ENCODING).split()[2] == "Z":
            return False
        return True
    except (OSError, IndexError):
        return False


def ensure_stopped(name: str) -> None:
    pid = read_pid(name)
    if is_alive(pid):
        raise SessionError(f"Session '{name}' is already running with PID {pid}.")


def write_meta(name: str, data: dict) -> None:
    path = paths_for(name)["meta"]
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True), encoding=ENCODING)
    os.replace(temporary, path)


def update_meta(name: str, **updates: object) -> dict:
    meta = load_meta(name)
    meta.update(updates)
    write_meta(name, meta)
    return meta


def safe_bytes(payload: bytes) -> str:
    parts: list[str] = []
    escapes = {9: "\\t", 10: "\\n", 13: "\\r"}
    for value in payload:
        if value in escapes:
            parts.append(escapes[value])
        elif 32 <= value <= 126:
            parts.append(chr(value))
        else:
            parts.append(f"\\x{value:02x}")
    return "".join(parts)


def write_io_line(path: Path, direction: str, payload: bytes) -> None:
    with path.open("a", encoding=ENCODING) as handle:
        handle.write(f"[{now_iso()}] {direction} {safe_bytes(payload)}\n")


def open_fifo_reader(path: Path) -> int:
    return os.open(path, os.O_RDONLY | os.O_NONBLOCK)


def parse_expected_peer(value: str | None) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    if not value:
        return None
    try:
        return ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise SessionError(f"Invalid expected peer IP or CIDR '{value}': {exc}") from exc


def is_loopback_bind(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    return bool(addresses) and all(ipaddress.ip_address(item[4][0]).is_loopback for item in addresses)


def validate_port(port: int, *, allow_zero: bool) -> int:
    minimum = 0 if allow_zero else 1
    if not minimum <= port <= 65535:
        qualifier = "0 through 65535" if allow_zero else "1 through 65535"
        raise SessionError(f"Port must be {qualifier}.")
    return port


def connected_loop(name: str, sock: socket.socket) -> int:
    paths = paths_for(name)
    sock.setblocking(False)
    fifo_fd = open_fifo_reader(paths["fifo"])
    selector = selectors.DefaultSelector()
    selector.register(sock, selectors.EVENT_READ, "sock")
    selector.register(fifo_fd, selectors.EVENT_READ, "fifo")

    try:
        with paths["rx_raw"].open("ab") as raw_handle:
            while True:
                for key, _ in selector.select(timeout=0.5):
                    if key.data == "sock":
                        try:
                            data = sock.recv(65536)
                        except BlockingIOError:
                            continue
                        if not data:
                            write_io_line(paths["io_log"], "[STATE]", b"remote closed")
                            update_meta(name, state="remote_closed", remote_closed_at=now_iso())
                            return 0
                        raw_handle.write(data)
                        raw_handle.flush()
                        write_io_line(paths["io_log"], "[RX]", data)
                        continue

                    try:
                        tx = os.read(fifo_fd, 65536)
                    except BlockingIOError:
                        continue
                    if not tx:
                        selector.unregister(fifo_fd)
                        os.close(fifo_fd)
                        fifo_fd = open_fifo_reader(paths["fifo"])
                        selector.register(fifo_fd, selectors.EVENT_READ, "fifo")
                        continue
                    sock.sendall(tx)
                    write_io_line(paths["io_log"], "[TX]", tx)
    finally:
        selector.close()
        try:
            os.close(fifo_fd)
        except OSError:
            pass
        sock.close()


def connect_daemon(name: str, meta: dict) -> int:
    host = str(meta["host"])
    port = int(meta["port"])
    timeout = float(meta.get("connect_timeout", 10))
    sock = socket.create_connection((host, port), timeout=timeout)
    peer_host, peer_port = sock.getpeername()[:2]
    update_meta(
        name,
        state="connected",
        connected_at=now_iso(),
        peer_host=str(peer_host),
        peer_port=int(peer_port),
    )
    write_io_line(paths_for(name)["io_log"], "[STATE]", b"connected")
    return connected_loop(name, sock)


def listen_daemon(name: str, meta: dict) -> int:
    bind_host = str(meta["bind_host"])
    port = int(meta["port"])
    accept_timeout_value = meta.get("accept_timeout")
    accept_timeout = float(accept_timeout_value) if accept_timeout_value is not None else None
    expected_peer = parse_expected_peer(meta.get("expected_peer"))
    paths = paths_for(name)

    family = socket.AF_INET6 if ":" in bind_host else socket.AF_INET
    listener = socket.socket(family, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind((bind_host, port))
        listener.listen(8)
        listener.settimeout(0.25)
        actual_host, actual_port = listener.getsockname()[:2]
        update_meta(
            name,
            state="listening",
            listening_at=now_iso(),
            bind_host=str(actual_host),
            port=int(actual_port),
        )
        write_io_line(paths["io_log"], "[STATE]", f"listening on {actual_host}:{actual_port}".encode(ENCODING))
        deadline = time.monotonic() + accept_timeout if accept_timeout is not None else None

        while True:
            if deadline is not None and time.monotonic() >= deadline:
                write_io_line(paths["io_log"], "[STATE]", b"accept timeout")
                update_meta(name, state="accept_timeout", accept_timeout_at=now_iso())
                return 0
            try:
                client, address = listener.accept()
            except socket.timeout:
                continue

            peer_host, peer_port = address[:2]
            try:
                peer_ip = ipaddress.ip_address(peer_host)
            except ValueError:
                peer_ip = None
            if expected_peer is not None and (peer_ip is None or peer_ip not in expected_peer):
                client.close()
                write_io_line(
                    paths["io_log"],
                    "[REJECT]",
                    f"peer {peer_host}:{peer_port} did not match {expected_peer}".encode(ENCODING),
                )
                continue

            update_meta(
                name,
                state="connected",
                connected_at=now_iso(),
                peer_host=str(peer_host),
                peer_port=int(peer_port),
            )
            write_io_line(paths["io_log"], "[STATE]", f"connected peer {peer_host}:{peer_port}".encode(ENCODING))
            listener.close()
            return connected_loop(name, client)
    finally:
        try:
            listener.close()
        except OSError:
            pass


def daemon_loop(name: str) -> int:
    meta = load_meta(name)
    if meta.get("mode") == "listen":
        return listen_daemon(name, meta)
    return connect_daemon(name, meta)


def handle_signal(signum: int, _frame: object) -> None:
    raise KeyboardInterrupt(f"received signal {signum}")


def initialize_session(name: str, meta: dict) -> tuple[dict[str, Path], subprocess.Popen]:
    paths = paths_for(name)
    ensure_stopped(name)
    paths["root"].mkdir(parents=True, exist_ok=True)
    paths["io_log"].write_text("", encoding=ENCODING)
    paths["daemon_log"].write_text("", encoding=ENCODING)
    paths["rx_raw"].write_bytes(b"")
    paths["pid"].unlink(missing_ok=True)
    if paths["fifo"].exists():
        paths["fifo"].unlink()
    os.mkfifo(paths["fifo"], mode=0o600)
    write_meta(name, meta)

    with paths["daemon_log"].open("a", encoding=ENCODING) as daemon_log:
        process = subprocess.Popen(
            [sys.executable, __file__, "_daemon", "--name", name],
            stdin=subprocess.DEVNULL,
            stdout=daemon_log,
            stderr=daemon_log,
            start_new_session=True,
        )
    paths["pid"].write_text(f"{process.pid}\n", encoding=ENCODING)
    return paths, process


def wait_for_state(name: str, process: subprocess.Popen, wanted: set[str], timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        meta = load_meta(name)
        state = str(meta.get("state", ""))
        if state in wanted:
            return meta
        if state == "error" or process.poll() is not None:
            raise SessionError("daemon exited during startup; check daemon.log")
        time.sleep(0.05)
    raise SessionError("daemon did not become ready; check daemon.log")


def cmd_start(args: argparse.Namespace) -> int:
    name = validate_session_name(args.name)
    validate_port(args.port, allow_zero=False)
    if args.connect_timeout <= 0:
        raise SessionError("Connect timeout must be greater than zero.")
    meta = {
        "name": name,
        "mode": "connect",
        "state": "starting",
        "host": args.host,
        "port": args.port,
        "connect_timeout": args.connect_timeout,
        "started_at": now_iso(),
    }
    _, process = initialize_session(name, meta)
    ready = wait_for_state(name, process, {"connected"}, args.connect_timeout + 2.0)
    print(f"started session '{name}' pid={process.pid} {args.host}:{ready['port']}")
    return 0


def cmd_listen(args: argparse.Namespace) -> int:
    name = validate_session_name(args.name)
    validate_port(args.port, allow_zero=True)
    if not is_loopback_bind(args.bind_host) and not args.allow_remote:
        raise SessionError("Non-loopback bind hosts require explicit --allow-remote.")
    expected_peer = parse_expected_peer(args.expected_peer)
    if args.accept_timeout is not None and args.accept_timeout <= 0:
        raise SessionError("Accept timeout must be greater than zero.")
    meta = {
        "name": name,
        "mode": "listen",
        "state": "starting",
        "bind_host": args.bind_host,
        "port": args.port,
        "allow_remote": bool(args.allow_remote),
        "expected_peer": str(expected_peer) if expected_peer is not None else None,
        "accept_timeout": args.accept_timeout,
        "started_at": now_iso(),
    }
    _, process = initialize_session(name, meta)
    ready = wait_for_state(name, process, {"listening", "connected"}, 5.0)
    print(f"listening session '{name}' pid={process.pid} {ready['bind_host']}:{ready['port']}")
    return 0


def decode_payload(args: argparse.Namespace) -> bytes:
    sources = [args.data is not None, args.hex_data is not None, args.base64_data is not None]
    if sum(sources) != 1:
        raise SessionError("Exactly one of --data, --hex, or --base64 is required.")
    if args.newline and args.data is None:
        raise SessionError("--newline is only valid with --data.")
    if args.data is not None:
        payload = args.data.encode(ENCODING)
        if args.newline:
            payload += b"\n"
    elif args.hex_data is not None:
        compact = args.hex_data.translate(str.maketrans("", "", " \t\r\n\v\f"))
        if len(compact) % 2:
            raise SessionError("Hex input must contain an even number of digits.")
        try:
            payload = bytes.fromhex(compact)
        except ValueError as exc:
            raise SessionError(f"Invalid hex input: {exc}") from exc
    else:
        try:
            payload = base64.b64decode(args.base64_data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise SessionError(f"Invalid base64 input: {exc}") from exc
    if len(payload) > MAX_SEND_BYTES:
        raise SessionError(f"Decoded payload exceeds the {MAX_SEND_BYTES}-byte limit.")
    return payload


def cmd_send(args: argparse.Namespace) -> int:
    name = validate_session_name(args.name)
    paths = paths_for(name)
    pid = read_pid(name)
    if not is_alive(pid):
        raise SessionError(f"Session '{name}' is not running.")
    if load_meta(name).get("state") != "connected":
        raise SessionError(f"Session '{name}' is not connected.")
    if args.timeout <= 0:
        raise SessionError("Send timeout must be greater than zero.")
    payload = decode_payload(args)

    deadline = time.monotonic() + args.timeout
    file_descriptor: int | None = None
    try:
        while file_descriptor is None:
            try:
                file_descriptor = os.open(paths["fifo"], os.O_WRONLY | os.O_NONBLOCK)
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise SessionError(f"Timeout opening '{name}' FIFO: {exc}") from exc
                time.sleep(0.05)

        offset = 0
        while offset < len(payload):
            try:
                written = os.write(file_descriptor, payload[offset:])
                offset += written
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise SessionError(f"Timeout writing to '{name}' FIFO. Session may be unhealthy.")
                time.sleep(0.01)
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)

    print(f"sent {len(payload)} bytes to '{name}'")
    return 0


def tail_file(path: Path, lines: int) -> str:
    recent: deque[str] = deque(maxlen=lines)
    with path.open("r", encoding=ENCODING, errors="replace") as handle:
        for line in handle:
            recent.append(line)
    return "".join(recent)


def cmd_read(args: argparse.Namespace) -> int:
    paths = paths_for(args.name)
    if not paths["io_log"].exists():
        raise SessionError(f"Session '{args.name}' has no logs yet.")
    if args.tail is not None and args.tail <= 0:
        raise SessionError("Tail line count must be greater than zero.")

    if args.tail:
        sys.stdout.write(tail_file(paths["io_log"], args.tail))
    else:
        with paths["io_log"].open("r", encoding=ENCODING, errors="replace") as handle:
            sys.stdout.write(handle.read())

    if args.follow:
        with paths["io_log"].open("r", encoding=ENCODING, errors="replace") as handle:
            handle.seek(0, os.SEEK_END)
            while True:
                line = handle.readline()
                if line:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                elif not is_alive(read_pid(args.name)):
                    return 0
                else:
                    time.sleep(0.2)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    name = validate_session_name(args.name)
    paths = paths_for(name)
    if not paths["meta"].exists():
        raise SessionError(f"Session '{name}' does not exist.")
    meta = load_meta(name)
    result = dict(meta)
    result.update(
        {
            "name": name,
            "running": is_alive(read_pid(name)),
            "pid": read_pid(name),
            "paths": {key: str(value) for key, value in paths.items()},
        }
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    name = validate_session_name(args.name)
    pid = read_pid(name)
    if not is_alive(pid):
        print(f"session '{name}' already stopped")
        return 0
    if args.timeout <= 0:
        raise SessionError("Stop timeout must be greater than zero.")

    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        if not is_alive(pid):
            print(f"stopped session '{name}'")
            return 0
        time.sleep(0.1)
    os.kill(pid, signal.SIGKILL)
    update_meta(name, state="stopped", stopped_at=now_iso())
    print(f"force-stopped session '{name}'")
    return 0


def cmd_daemon(args: argparse.Namespace) -> int:
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    try:
        return daemon_loop(args.name)
    except KeyboardInterrupt as exc:
        paths = paths_for(args.name)
        write_io_line(paths["io_log"], "[STATE]", str(exc).encode(ENCODING))
        update_meta(args.name, state="stopped", stopped_at=now_iso())
        return 0
    except Exception as exc:  # noqa: BLE001
        paths = paths_for(args.name)
        write_io_line(paths["io_log"], "[ERROR]", str(exc).encode(ENCODING))
        update_meta(args.name, state="error", error=str(exc), error_at=now_iso())
        raise
    finally:
        try:
            paths_for(args.name)["pid"].unlink(missing_ok=True)
        except OSError:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Async TCP session manager")
    commands = parser.add_subparsers(dest="cmd", required=True)

    start = commands.add_parser("start", help="Start an outbound background session")
    start.add_argument("--name", required=True)
    start.add_argument("--host", required=True)
    start.add_argument("--port", type=int, required=True)
    start.add_argument("--connect-timeout", type=float, default=10.0)
    start.set_defaults(func=cmd_start)

    listen = commands.add_parser("listen", help="Listen for one inbound TCP connection")
    listen.add_argument("--name", required=True)
    listen.add_argument("--port", type=int, required=True)
    listen.add_argument("--bind-host", default="127.0.0.1")
    listen.add_argument("--allow-remote", action="store_true")
    listen.add_argument("--expected-peer")
    listen.add_argument("--accept-timeout", type=float)
    listen.set_defaults(func=cmd_listen)

    send = commands.add_parser("send", help="Send text or raw bytes to a connected session")
    send.add_argument("--name", required=True)
    payload = send.add_mutually_exclusive_group(required=True)
    payload.add_argument("--data")
    payload.add_argument("--hex", dest="hex_data")
    payload.add_argument("--base64", dest="base64_data")
    send.add_argument("--newline", action="store_true")
    send.add_argument("--timeout", type=float, default=2.0)
    send.set_defaults(func=cmd_send)

    read = commands.add_parser("read", help="Read session logs")
    read.add_argument("--name", required=True)
    read.add_argument("--tail", type=int)
    read.add_argument("--follow", action="store_true")
    read.set_defaults(func=cmd_read)

    status = commands.add_parser("status", help="Show session status")
    status.add_argument("--name", required=True)
    status.set_defaults(func=cmd_status)

    stop = commands.add_parser("stop", help="Stop a session")
    stop.add_argument("--name", required=True)
    stop.add_argument("--timeout", type=float, default=3.0)
    stop.set_defaults(func=cmd_stop)

    daemon = commands.add_parser("_daemon", help=argparse.SUPPRESS)
    daemon.add_argument("--name", required=True)
    daemon.set_defaults(func=cmd_daemon)
    return parser


def main() -> int:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except SessionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
