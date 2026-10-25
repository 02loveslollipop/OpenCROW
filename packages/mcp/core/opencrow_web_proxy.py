"""Owned headless proxy sessions and private JSONL control transport."""
from __future__ import annotations
import argparse
import asyncio
import base64
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid

from opencrow_web_proxy_store import (ProxyError, config_for, integer, private_dir, session_dir, state_root, write_private, safe_headers, safe_url)


def socket_path(path):
    candidate = path / "control.sock"
    if len(os.fsencode(candidate)) < 100: return candidate
    root = private_dir(Path("/tmp") / f"opencrow-web-proxy-{os.getuid()}")
    return root / (hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:24] + ".sock")


def rpc(session_id, method, params=None, timeout=10):
    path = session_dir(session_id)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout); client.connect(str(socket_path(path)))
        client.sendall((json.dumps({"method": method, "params": params or {}}) + "\n").encode())
        with client.makefile("rb") as stream:
            line = stream.readline(2 * 1024 * 1024 + 1)
        if not line or len(line) > 2 * 1024 * 1024: raise ProxyError("Proxy control connection failed or exceeded its response limit")
        result = json.loads(line)
        if "error" in result: raise ProxyError(result["error"])
        return result["result"]


def dependencies():
    return [{"dependency": name, "available": importlib.util.find_spec(name) is not None} for name in ("h11", "cryptography")]


def load_config(path):
    return json.loads((path / "config.json").read_text())


def status(session_id):
    try: return rpc(session_id, "status", timeout=2)
    except (ConnectionRefusedError, FileNotFoundError, TimeoutError, socket.timeout):
        path = session_dir(session_id); cfg = load_config(path)
        return {"session_id": session_id, "state": "stopped", "workspace": cfg["workspace"], "history_uri": f"opencrow://opencrow-web-proxy-mcp/sessions/{session_id}/history"}


def start(arguments):
    missing = [item["dependency"] for item in dependencies() if not item["available"]]
    if missing: raise ProxyError("Missing proxy modules: " + ", ".join(missing) + "; install packages/mcp/requirements-web-proxy.txt")
    identity = arguments.get("session_id")
    if identity:
        if set(arguments) != {"session_id"}: raise ProxyError("Restart accepts only session_id; existing scope remains unchanged")
        path = session_dir(identity)
    else:
        cfg = config_for(arguments)
        identity = uuid.uuid4().hex
        path = private_dir(state_root() / identity)
        cfg["bindings"] = {secrets.token_hex(24): cfg["correlation"]}
        write_private(path / "config.json", json.dumps(cfg).encode())
    with (path / "startup.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            live = rpc(identity, "status", timeout=2)
            if live["state"] == "running": return live
        except (ConnectionRefusedError, FileNotFoundError): pass
        except (TimeoutError, socket.timeout) as exc: raise ProxyError("Existing proxy did not answer; refusing to start a second owner") from exc
        control = socket_path(path)
        if control.exists():
            import stat
            info = control.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid(): raise ProxyError("Refusing to replace a foreign control socket")
            control.unlink()
        fd = os.open(path / "daemon.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        try:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "daemon", identity], stdin=subprocess.DEVNULL, stdout=fd, stderr=fd, start_new_session=True)
        finally: os.close(fd)
        threading.Thread(target=process.wait, daemon=True).start()
        for _ in range(150):
            if process.poll() is not None: raise ProxyError("Proxy startup failed; check dependency/port availability")
            try: return rpc(identity, "status", timeout=1)
            except (ConnectionRefusedError, FileNotFoundError): time.sleep(.05)
        process.terminate()
        try: process.wait(timeout=3)
        except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=3)
        raise ProxyError("Proxy startup timed out")


def stop(identity):
    if status(identity)["state"] != "stopped": rpc(identity, "stop")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try: rpc(identity, "status", timeout=.2)
        except (FileNotFoundError, ConnectionError, TimeoutError, socket.timeout, ProxyError):
            with (session_dir(identity) / "owner.lock").open("a") as lock:
                try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError: pass
                else: return status(identity)
        time.sleep(.03)
    raise ProxyError("Proxy shutdown is still in progress; do not start a second process")


def delete(identity):
    if status(identity)["state"] != "stopped": raise ProxyError("Stop the proxy before deleting its private history and CA")
    path = session_dir(identity)
    # Take the daemon's lock too: status cannot authorize deleting an owner
    # still initializing or closing its listener.
    with (path / "owner.lock").open("a") as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc: raise ProxyError("Proxy process still owns the session") from exc
        shutil.rmtree(path)
    return {"session_id": identity, "deleted": True}


def environment(identity, correlation=None):
    """Sensitive data: only hand to a tool process/private file, never MCP output."""
    value = rpc(identity, "bind", correlation or {})
    return value["environment"]


class Controller:
    def __init__(self, engine):
        self.engine = engine
        self.path, self.config, self.store = engine.path, engine.config, engine.store
        self.stopping = asyncio.Event()

    def persist(self):
        write_private(self.path / "config.json", json.dumps(self.config).encode())

    def snapshot(self):
        return {"session_id": self.path.name, "state": "running", "pid": os.getpid(), "workspace": self.config["workspace"],
                "endpoint": f"http://127.0.0.1:{self.engine.port}", "mode": self.config["mode"], "tls_intercept": self.config["tls_intercept"],
                "ca_certificate": str(self.path / "ca/ca.pem") if self.config["tls_intercept"] else None,
                "targets": self.config["targets"], "pending": list(self.engine.pending), "active": len(self.engine.tasks),
                "limits": {key: self.config[key] for key in ("capture_bytes", "history_limit", "history_bytes", "retention_sec", "request_timeout_sec", "pause_timeout_sec", "timeout_policy")},
                "history_uri": f"opencrow://opencrow-web-proxy-mcp/sessions/{self.path.name}/history"}

    async def handle(self, method, p):
        if method == "status": return self.snapshot()
        if method == "stop":
            asyncio.get_running_loop().call_later(.05, self.stopping.set)
            return {"stopping": True}
        if method == "history": return self.store.history(p)
        if method == "get":
            flow = self.store.get(p.get("request_id"))
            if p.get("raw"):
                if not self.config["allow_raw_access"]: raise ProxyError("Raw access was not authorized when the session was created")
                meta, body = self.store.raw(flow["id"], p.get("version", "original"))
                offset = integer(p.get("offset", 0), "offset", 0, 1048576)
                limit = integer(p.get("limit", 8192), "limit", 1, 16384)
                return {"request": flow, "raw_metadata": meta, "body_base64": base64.b64encode(body[offset:offset+limit]).decode(), "offset": offset, "captured_bytes": len(body)}
            return {"request": flow}
        if method == "delete_request":
            identity = p.get("request_id")
            if self.store.get(identity)["state"] in {"receiving", "paused", "forwarding", "queued"}: raise ProxyError("Cannot delete an active request")
            self.store.delete(identity); return {"deleted": identity}
        if method == "intercept":
            mode = p.get("mode", "observe")
            if mode not in {"observe", "pause"} or p.get("timeout_policy", "drop") not in {"drop", "forward"}: raise ProxyError("Invalid interception mode/policy")
            self.config.update(mode=mode, pause_timeout_sec=integer(p.get("pause_timeout_sec", 15), "pause_timeout_sec", 1, 120), timeout_policy=p.get("timeout_policy", "drop"))
            self.persist(); return self.snapshot()
        if method in {"edit", "forward", "drop"}: return await self.engine.decide(p.get("request_id"), method, p.get("edit") if method == "edit" else None)
        if method == "replay": return await self.engine.replay(p.get("request_id"), p.get("edit"), p.get("confirm_side_effects"))
        if method == "rules":
            if "rules" in p:
                from opencrow_web_proxy_engine import edit_request, parse_url
                rules = p["rules"]
                if not isinstance(rules, list) or len(rules) > 32: raise ProxyError("Rules must be a list of at most 32 items")
                for rule in rules:
                    if not isinstance(rule, dict) or set(rule) - {"host", "port", "path_prefix", "edit", "action"}: raise ProxyError("Invalid rewrite rule")
                    prefix = rule.get("path_prefix", "/")
                    if not isinstance(prefix, str) or not prefix.startswith("/"): raise ProxyError("Rule requires a path prefix")
                    if rule.get("action", "rewrite") not in {"rewrite", "drop"}: raise ProxyError("Invalid rule action")
                    rule.update(path_prefix=prefix)
                    from opencrow_web_proxy_engine import authority
                    url = "http://" + authority(rule.get("host", ""), rule.get("port"), "http") + prefix
                    await self.engine.scope(url)
                    meta, _ = edit_request({"url": url, "method": "GET", "headers": []}, b"", rule.get("edit", {}))
                    await self.engine.scope(meta["url"])
                self.config["rules"] = rules; self.persist()
            # Rewrite headers/bodies may carry credentials; don't echo them.
            return {"rules": [{key: rule.get(key) for key in ("host", "port", "path_prefix", "action")} for rule in self.config["rules"]]}
        if method == "bind":
            if not isinstance(p, dict) or set(p) - {"provider", "worker_id", "run_id", "challenge_id"} or any(not isinstance(v, str) or len(v) > 128 for v in p.values()): raise ProxyError("Invalid route correlation")
            matches = [token for token, corr in self.config["bindings"].items() if corr == p]
            if matches: token = matches[0]
            else:
                if len(self.config["bindings"]) >= 256: raise ProxyError("Session route binding limit reached")
                token = secrets.token_hex(24); self.config["bindings"][token] = p; self.persist()
            url = f"http://{token}:route@127.0.0.1:{self.engine.port}"
            from opencrow_web_proxy_store import PROVIDER_HOSTS
            env = {key: url for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")}
            env.update(NO_PROXY=",".join((*PROVIDER_HOSTS, *self.config["provider_hosts"])), no_proxy=",".join((*PROVIDER_HOSTS, *self.config["provider_hosts"])), ALL_PROXY="", all_proxy="")
            # This bundle augments ordinary roots for this tool only.
            if self.config["tls_intercept"]:
                bundle = self.path / "ca/tool-trust.pem"
                if not bundle.exists(): write_private(bundle, Path(ssl_default_ca()).read_bytes() + (self.path / "ca/ca.pem").read_bytes())
                env.update(REQUESTS_CA_BUNDLE=str(bundle), SSL_CERT_FILE=str(bundle), CURL_CA_BUNDLE=str(bundle), NODE_EXTRA_CA_CERTS=str(self.path / "ca/ca.pem"))
            return {"environment": env}
        if method == "compare":
            a, b = self.store.get(p.get("request_id")), self.store.get(p.get("other_request_id"))
            return {"request_id": a["id"], "other_request_id": b["id"], "status": [a.get("status"), b.get("status")],
                    "body_equal": a.get("response_body", {}).get("sha256") == b.get("response_body", {}).get("sha256"),
                    "size": [a.get("response_body", {}).get("size"), b.get("response_body", {}).get("size")]}
        if method == "export": return self.export(p)
        raise ProxyError("Unknown proxy operation")

    def export(self, p):
        rows = self.store.history(p)["requests"]
        fmt = p.get("format", "jsonl")
        if fmt not in {"har", "jsonl"}: raise ProxyError("Export format must be har or jsonl")
        output = Path(self.config["workspace"]) / ".opencrow" / "proxy" / self.path.name
        output.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = output / (uuid.uuid4().hex + "." + fmt)
        if fmt == "har":
            import datetime
            entries = []
            for f in rows:
                entries.append({"startedDateTime": datetime.datetime.fromtimestamp(f["created"], datetime.timezone.utc).isoformat(), "time": 1000 * (f.get("finished", f["created"]) - f["created"]),
                                "request": {"method": f["method"], "url": f["url"], "httpVersion": "HTTP/1.1", "headers": [{"name": k, "value": v} for k, v in f.get("request_headers", [])], "queryString": [], "cookies": [], "headersSize": -1, "bodySize": f.get("request_body", {}).get("size", -1)},
                                "response": {"status": f.get("status", 0), "statusText": "", "httpVersion": "HTTP/1.1", "headers": [{"name": k, "value": v} for k, v in f.get("response_headers", [])], "cookies": [], "content": {"size": f.get("response_body", {}).get("size", 0), "mimeType": "application/octet-stream"}, "redirectURL": "", "headersSize": -1, "bodySize": f.get("response_body", {}).get("size", -1)},
                                "cache": {}, "timings": {"send": 0, "wait": 0, "receive": 0}, "_opencrow": f})
            content = json.dumps({"log": {"version": "1.2", "creator": {"name": "OpenCROW", "version": "1"}, "entries": entries}})
        else: content = "".join(json.dumps(row) + "\n" for row in rows)
        write_private(path, content.encode())
        return {"path": str(path), "count": len(rows), "format": fmt, "sanitized": True}


def ssl_default_ca():
    import ssl
    path = ssl.get_default_verify_paths().cafile
    if not path: raise ProxyError("System CA bundle unavailable; supply tool trust explicitly")
    return path


async def daemon(identity):
    from opencrow_web_proxy_engine import Engine
    path = session_dir(identity)
    with (path / "owner.lock").open("a") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config = load_config(path)
        # Each process lifetime gets a fresh, explicitly trusted interception CA.
        shutil.rmtree(path / "ca", ignore_errors=True)
        if config["tls_intercept"]:
            from opencrow_web_proxy_tls import server_context
            server_context(path / "ca", "localhost")
        engine = Engine(path, config)
        await engine.start()
        controller = Controller(engine)
        clients = set()
        async def control(reader, writer):
            task = asyncio.current_task(); clients.add(task)
            try:
                line = await asyncio.wait_for(reader.readline(), 5)
                request = json.loads(line)
                if not isinstance(request, dict) or not isinstance(request.get("params", {}), dict): raise ProxyError("Invalid control request")
                result = await controller.handle(request.get("method"), request.get("params", {}))
                payload = {"result": result}
            except Exception as exc:
                payload = {"error": str(exc) if isinstance(exc, ProxyError) else "Proxy operation failed; invalid input or runtime error"}
            try:
                writer.write((json.dumps(payload) + "\n").encode()); await asyncio.wait_for(writer.drain(), 5)
            except (OSError, TimeoutError): pass
            finally:
                writer.close(); clients.discard(task)
        control_path = socket_path(path)
        listener = await asyncio.start_unix_server(control, str(control_path), limit=1500000)
        os.chmod(control_path, 0o600)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT): loop.add_signal_handler(sig, controller.stopping.set)
        async def retention():
            while True: await asyncio.sleep(30); engine.store.prune()
        maintenance = asyncio.create_task(retention())
        try: await controller.stopping.wait()
        finally:
            listener.close()
            maintenance.cancel(); await asyncio.gather(maintenance, return_exceptions=True)
            for task in list(clients): task.cancel()
            await asyncio.gather(*list(clients), return_exceptions=True)
            await listener.wait_closed()
            await engine.close()
            control_path.unlink(missing_ok=True)
            shutil.rmtree(path / "ca", ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    for operation in ("daemon", "status", "stop", "delete", "env"):
        command = sub.add_parser(operation); command.add_argument("session_id")
        if operation == "env": command.add_argument("command", nargs=argparse.REMAINDER)
    command = sub.add_parser("start"); command.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.operation == "daemon": os.umask(0o077); asyncio.run(daemon(args.session_id)); return 0
        if args.operation == "env":
            command = args.command[1:] if args.command and args.command[0] == "--" else args.command
            if not command: raise ProxyError("env requires -- COMMAND [ARGS...]; environment secrets are never printed")
            os.execvpe(command[0], command, {**os.environ, **environment(args.session_id)})
        result = start(json.loads(args.config.read_text())) if args.operation == "start" else {"status": status, "stop": stop, "delete": delete}[args.operation](args.session_id)
        print(json.dumps(result)); return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc) if isinstance(exc, ProxyError) else type(exc).__name__}), file=sys.stderr); return 1


if __name__ == "__main__": raise SystemExit(main())
