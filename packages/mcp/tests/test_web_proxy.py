"""Real owned-daemon HTTP/TLS and MCP tests, all targets isolated on loopback."""
from concurrent.futures import ThreadPoolExecutor
import base64
import gzip
import http.client
import http.server
import json
import os
from pathlib import Path
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time

import pytest
import requests

import opencrow_web_proxy as proxy
import opencrow_web_proxy_mcp as mcp
from opencrow_web_proxy_store import ProxyError, session_dir


class Target(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    hits = []
    def log_message(self, *_): pass
    def do_GET(self): self.respond()
    def do_HEAD(self): self.respond()
    def do_POST(self): self.respond()
    def respond(self):
        if self.headers.get("Transfer-Encoding") == "chunked":
            body = bytearray()
            while True:
                size = int(self.rfile.readline().strip(), 16)
                if not size: self.rfile.readline(); break
                body.extend(self.rfile.read(size)); self.rfile.read(2)
            body = bytes(body)
        else: body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.hits.append((self.command, self.path, body, dict(self.headers)))
        if self.path.startswith("/slow"): time.sleep(2)
        if self.path.startswith("/stream"):
            self.send_response(200); self.send_header("Transfer-Encoding", "chunked"); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
            for part in (b"data: one\n\n", b"data: two\n\n"):
                self.wfile.write(f"{len(part):x}\r\n".encode()+part+b"\r\n"); self.wfile.flush(); time.sleep(.1)
            self.wfile.write(b"0\r\n\r\n"); return
        payload = b"\0\xff\x80" * 100000 if self.path.startswith("/large") else body or self.path.encode()
        if self.path.startswith("/gzip"): payload = gzip.compress(payload)
        self.send_response(302 if self.path.startswith("/redirect") else 200)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Connection", str(id(self.connection)))
        self.send_header("Set-Cookie", "session=response-secret")
        if self.path.startswith("/gzip"): self.send_header("Content-Encoding", "gzip")
        if self.path.startswith("/redirect"): self.send_header("Location", "/final?token=redirect-secret")
        self.end_headers()
        if self.command != "HEAD":
            try: self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError): pass


@pytest.fixture
def target():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Target)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    yield server.server_port
    server.shutdown(); server.server_close()


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCROW_WEB_PROXY_STATE_DIR", str(tmp_path / "state"))
    created = []
    def create(port, **options):
        value = proxy.start({"workspace": str(tmp_path), "targets": [{"host": "127.0.0.1", "port": port, "allow_private": True}], **options})
        created.append(value["session_id"])
        return value
    yield create
    for identity in created:
        try: proxy.stop(identity); proxy.delete(identity)
        except (ProxyError, OSError): pass


def request(session, port, path="/hello", **kwargs):
    env = proxy.environment(session)
    return requests.request(kwargs.pop("method", "GET"), f"http://127.0.0.1:{port}{path}", proxies={"http": env["http_proxy"], "https": env["https_proxy"]}, timeout=8, **kwargs)


def history(identity): return proxy.rpc(identity, "history")["requests"]

def poll(identity, request_id=None, state="completed"):
    for _ in range(200):
        rows = history(identity)
        matches = [row for row in rows if (not request_id or row["id"] == request_id) and row["state"] == state]
        if matches: return matches[-1]
        time.sleep(.02)
    raise AssertionError(rows)


def invoke(name, **arguments):
    server = mcp.build_server()
    result = server._handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
    return json.loads(result["result"]["content"][0]["text"])


def test_observe_binary_streaming_compression_redirect_reuse_and_redaction(sessions, target):
    identity = sessions(target, allow_raw_access=True, capture_bytes=128)["session_id"]
    response = request(identity, target, "/hello?password=query-secret", headers={"Authorization": "Bearer auth-secret", "Cookie": "private=cookie-secret", "X-Api-Key": "key-secret"}, data=b"login-secret", method="POST")
    assert response.content == b"login-secret"
    assert request(identity, target, "/large").content == b"\0\xff\x80" * 100000
    assert request(identity, target, "/gzip").content == b"/gzip"
    assert request(identity, target, "/redirect", allow_redirects=False).status_code == 302
    response = request(identity, target, "/stream", stream=True)
    chunks = list(response.iter_content(chunk_size=11)); assert b"data: one" in b"".join(chunks)
    assert request(identity, target, "/chunked", method="POST", data=iter([b"first", b"second"])).content == b"firstsecond"
    poll(identity)
    rows = history(identity)
    secret_text = json.dumps(rows)
    for secret in ("query-secret", "auth-secret", "cookie-secret", "key-secret", "login-secret", "response-secret", "redirect-secret"):
        assert secret not in secret_text
    raw = proxy.rpc(identity, "get", {"request_id": rows[0]["id"], "raw": True})
    assert base64.b64decode(raw["body_base64"]) == b"login-secret"
    large = next(row for row in rows if row["url"].endswith("/large"))
    assert large["response_body"]["truncated"] and large["response_body"]["size"] == 300000
    export = proxy.rpc(identity, "export", {"format": "har"})
    assert "login-secret" not in Path(export["path"]).read_text()
    # Reuse the downstream HTTP/1.1 connection across independent requests.
    url = proxy.status(identity)["endpoint"]
    port = int(url.rsplit(":", 1)[1]); auth = requests.utils.unquote(proxy.environment(identity)["http_proxy"].split("//", 1)[1].split("@", 1)[0])
    connection = http.client.HTTPConnection("127.0.0.1", port)
    for path in ("/reuse1", "/reuse2"):
        connection.request("GET", f"http://127.0.0.1:{target}{path}", headers={"Proxy-Authorization": "Basic " + base64.b64encode(auth.encode()).decode()})
        result = connection.getresponse(); assert result.status == 200; result.read()
    connection.close()


def test_mcp_pause_edit_forward_replay_compare_and_persistent_history(sessions, target):
    identity = sessions(target, allow_raw_access=True)["session_id"]
    assert invoke("web_proxy_intercept_set", session_id=identity, mode="pause")["ok"]
    with ThreadPoolExecutor() as pool:
        waiting = pool.submit(request, identity, target, "/original", method="POST", data=b"old")
        paused = poll(identity, state="paused")
        edit = {"url": f"http://127.0.0.1:{target}/changed?password=edit-secret", "headers": {"Cookie": "s=edit-secret"}, "body_base64": base64.b64encode(b"new").decode()}
        result = invoke("web_proxy_request_edit", session_id=identity, request_id=paused["id"], edit=edit)
        assert result["ok"] and "edit-secret" not in json.dumps(result)
        assert invoke("web_proxy_forward", session_id=identity, request_id=paused["id"])["ok"]
        assert waiting.result().content == b"new"
    flow = poll(identity, paused["id"])
    assert not invoke("web_proxy_forward", session_id=identity, request_id=flow["id"])["ok"]
    assert not invoke("web_proxy_replay", session_id=identity, request_id=flow["id"])["ok"]
    replay = invoke("web_proxy_replay", session_id=identity, request_id=flow["id"], confirm_side_effects=True)
    assert replay["ok"]
    second = poll(identity, replay["observations"][0]["request_id"])
    assert second["replay_of"] == flow["id"]
    compare = invoke("web_proxy_compare", session_id=identity, request_id=flow["id"], other_request_id=second["id"])
    assert compare["observations"][0]["body_equal"]
    original = proxy.rpc(identity, "get", {"request_id": flow["id"], "raw": True})
    modified = proxy.rpc(identity, "get", {"request_id": flow["id"], "raw": True, "version": "modified"})
    assert base64.b64decode(original["body_base64"]) == b"old"
    assert base64.b64decode(modified["body_base64"]) == b"new"
    proxy.stop(identity)
    assert invoke("web_proxy_history", session_id=identity)["observations"][0]["requests"]
    restarted = proxy.start({"session_id": identity})
    assert restarted["state"] == "running" and history(identity)[0]["id"] == flow["id"]


def test_scope_authentication_timeout_and_raw_permissions(sessions, target):
    identity = sessions(target, request_timeout_sec=1)["session_id"]
    assert request(identity, target).status_code == 200
    flow = poll(identity)
    assert not invoke("web_proxy_request_get", session_id=identity, request_id=flow["id"], raw=True)["ok"]
    assert request(identity, target, "/slow").status_code == 504
    assert request(identity, target + 1).status_code == 403
    endpoint = proxy.status(identity)["endpoint"]
    assert requests.get(f"http://127.0.0.1:{target}/", proxies={"http": endpoint}, timeout=5).status_code == 407
    assert not invoke("web_proxy_start", workspace="/tmp", targets=[{"host": "127.0.0.1", "port": target}], tls_intercept="yes")["ok"]


@pytest.fixture
def tls_target(tmp_path):
    from opencrow_web_proxy_tls import server_context
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Target)
    server.socket = server_context(tmp_path / "target-ca", "127.0.0.1").wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_port, str(tmp_path / "target-ca/ca.pem")
    server.shutdown(); server.server_close()


def test_https_passthrough_and_explicit_mitm_trust_and_ca_cleanup(sessions, tls_target):
    port, target_ca = tls_target
    opaque = sessions(port)["session_id"]
    env = proxy.environment(opaque)
    response = requests.get(f"https://127.0.0.1:{port}/opaque", proxies={"https": env["https_proxy"]}, verify=target_ca, timeout=5)
    assert response.content == b"/opaque"
    assert not (session_dir(opaque) / "ca").exists()
    rows = history(opaque)
    assert all(row["method"] == "CONNECT" and "response_body" not in row for row in rows)
    identity = sessions(port, tls_intercept=True, upstream_ca=target_ca, allow_raw_access=True)["session_id"]
    value = proxy.status(identity); env = proxy.environment(identity)
    assert Path(value["ca_certificate"]).is_file()
    assert (Path(value["ca_certificate"]).parent / "ca-key.pem").stat().st_mode & 0o077 == 0
    with pytest.raises(requests.exceptions.SSLError):
        requests.get(f"https://127.0.0.1:{port}/untrusted", proxies={"https": env["https_proxy"]}, verify=target_ca, timeout=5)
    response = requests.get(f"https://127.0.0.1:{port}/mitm", proxies={"https": env["https_proxy"]}, verify=value["ca_certificate"], timeout=5)
    assert response.content == b"/mitm"
    flow = poll(identity)
    assert any(row["method"] == "GET" and row["url"].endswith("/mitm") for row in history(identity))
    proxy.stop(identity)
    assert not Path(value["ca_certificate"]).exists()


def test_concurrent_pauses_drop_fail_open_and_retention(sessions, target):
    identity = sessions(target, history_limit=3)["session_id"]
    proxy.rpc(identity, "intercept", {"mode": "pause", "pause_timeout_sec": 1, "timeout_policy": "forward"})
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(request, identity, target, f"/concurrent/{index}") for index in range(4)]
        paused = poll(identity, state="paused")
        proxy.rpc(identity, "drop", {"request_id": paused["id"]})
        results = [job.result().status_code for job in jobs]
    assert results.count(403) == 1 and results.count(200) == 3
    assert len(history(identity)) <= 3
    proxy.rpc(identity, "intercept", {"mode": "pause", "pause_timeout_sec": 1, "timeout_policy": "drop"})
    assert request(identity, target).status_code == 403
    proxy.rpc(identity, "intercept", {"mode": "observe"})
    response = request(identity, target, "/upgrade", headers={"Connection": "Upgrade", "Upgrade": "websocket"})
    assert response.status_code == 426


def test_crash_recovery_marks_paused_request_interrupted_without_replay(sessions, target):
    value = sessions(target); identity = value["session_id"]
    proxy.rpc(identity, "intercept", {"mode": "pause"})
    with ThreadPoolExecutor() as pool:
        job = pool.submit(request, identity, target, "/crash")
        flow = poll(identity, state="paused")
        os.kill(value["pid"], signal.SIGKILL)
        with pytest.raises(requests.exceptions.RequestException): job.result()
    time.sleep(.1)
    proxy.start({"session_id": identity})
    assert poll(identity, flow["id"], "interrupted")["error"]
    assert not proxy.status(identity)["pending"]
