"""OpenCROW's asyncio HTTP/1.1 interception engine, using h11 for framing."""
from __future__ import annotations

import asyncio
import base64
import copy
import ipaddress
import json
import secrets
import socket
import ssl
import time
import uuid
from urllib.parse import urlsplit, urlunsplit

import h11
from opencrow_web_proxy_store import (Capture, ProxyError, Store, PROVIDER_HOSTS, hostname, safe_url, safe_headers, integer, write_private)

HOP = {"connection", "proxy-connection", "keep-alive", "te", "trailer", "upgrade", "proxy-authorization", "proxy-authenticate"}


def authority(host, port, scheme):
    host = f"[{host}]" if ":" in host else host
    return host if port == (443 if scheme == "https" else 80) else f"{host}:{port}"


def parse_url(url):
    try:
        p = urlsplit(url)
        if p.scheme not in {"http", "https"} or p.username is not None or p.password is not None or p.fragment or not p.hostname or any(ord(c) < 33 or ord(c) > 126 for c in url):
            raise ValueError()
        host = hostname(p.hostname)
        port = p.port or (443 if p.scheme == "https" else 80)
        return p, host, port
    except (ValueError, UnicodeError) as exc:
        raise ProxyError("An absolute ASCII HTTP(S) URL without credentials or fragment is required") from exc


def cleaned(headers):
    tokens = {token.strip().lower() for key, value in headers if key.lower() == "connection" for token in value.split(",")}
    return [(key, value) for key, value in headers if key.lower() not in HOP | tokens]


def request_headers(meta, body_length=None):
    p, host, port = parse_url(meta["url"])
    original = {k.lower(): v for k, v in meta["headers"]}
    result = [(k, v) for k, v in cleaned(meta["headers"]) if k.lower() not in {"host", "content-length", "transfer-encoding", "expect"}]
    result.append(("Host", authority(host, port, p.scheme)))
    if body_length is not None:
        result.append(("Content-Length", str(body_length)))
    elif "content-length" in original:
        result.append(("Content-Length", original["content-length"]))
    elif "transfer-encoding" in original:
        result.append(("Transfer-Encoding", "chunked"))
    return result


def edit_request(meta, body, edit):
    if not isinstance(edit, dict) or set(edit) - {"url", "method", "headers", "remove_headers", "body_base64"}:
        raise ProxyError("Invalid request edit fields")
    result = copy.deepcopy(meta)
    for key in ("url", "method"):
        if key in edit:
            if not isinstance(edit[key], str): raise ProxyError("URL/method edits must be strings")
            result[key] = edit[key]
    parse_url(result["url"])
    removals = edit.get("remove_headers", [])
    headers = edit.get("headers", {})
    if not isinstance(removals, list) or any(not isinstance(x, str) for x in removals) or not isinstance(headers, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in headers.items()):
        raise ProxyError("Header edits must map names to strings")
    forbidden = {"host", "content-length", "transfer-encoding", "connection", "proxy-authorization", "upgrade"}
    if forbidden.intersection(k.lower() for k in headers):
        raise ProxyError("Host and framing headers are computed from the URL/body; edit those fields instead")
    remove = {x.lower() for x in removals} | {x.lower() for x in headers}
    result["headers"] = [(k, v) for k, v in result["headers"] if k.lower() not in remove] + list(headers.items())
    if "body_base64" in edit:
        if any(k.lower() == "content-encoding" and v.lower() != "identity" for k, v in result["headers"]):
            raise ProxyError("Remove Content-Encoding when replacing a compressed body")
        try: body = base64.b64decode(edit["body_base64"], validate=True)
        except (ValueError, TypeError) as exc: raise ProxyError("Invalid base64 body") from exc
    if len(body) > 1048576:
        raise ProxyError("Edited/replay bodies are limited to 1 MiB")
    # h11 validates method/header syntax and rejects CR/LF injection.
    try: h11.Request(method=result["method"], target="/", headers=request_headers(result, len(body)))
    except (h11.ProtocolError, UnicodeError) as exc: raise ProxyError("Invalid method or header syntax") from exc
    return result, body


class Engine:
    def __init__(self, path, config):
        self.path, self.config = path, config
        self.store = Store(path, config)
        self.store.recover()
        self.pending = {}
        self.tasks = set()
        self.writers = set()
        self.listener = None
        self.replays = 0
        self.port = 0

    async def scope(self, url, *, connect=False):
        p, host, port = parse_url(url)
        if not self.config["capture_provider_traffic"] and any(host == h or host.endswith("." + h) for h in (*PROVIDER_HOSTS, *self.config["provider_hosts"])):
            raise ProxyError("Provider/model API destinations are excluded")
        matches = [t for t in self.config["targets"] if t["host"] == host and t["port"] == port and (connect or (p.path or "/").startswith(t["path_prefix"]))]
        if not matches:
            raise ProxyError("Destination is outside the authorized target scope")
        if connect and not self.config["tls_intercept"] and not any(t["path_prefix"] == "/" for t in matches):
            raise ProxyError("Opaque CONNECT requires whole-host path scope; enable TLS inspection for path restrictions")
        addresses = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        if not addresses:
            raise ProxyError("Target DNS did not return an address")
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if not ip.is_global and not any(t["allow_private"] for t in matches):
                raise ProxyError("Private/loopback target requires explicit allow_private scope")
            if ip.is_unspecified or ip.is_multicast:
                raise ProxyError("Unspecified/multicast destinations are not supported")
            if port == self.port and ip.is_loopback:
                raise ProxyError("Recursive proxy destinations are forbidden")
        # Connect to the already validated IP, never re-resolve at connect time.
        return p, host, port, addresses[0][4][0]

    async def open_upstream(self, meta):
        p, host, port, ip = await self.scope(meta["url"])
        context = None
        if p.scheme == "https":
            context = ssl.create_default_context(cafile=self.config.get("upstream_ca"))
            context.set_alpn_protocols(["http/1.1"])
        reader, writer = await asyncio.open_connection(ip, port, ssl=context, server_hostname=host if context else None,
                                                      **({"ssl_handshake_timeout": 10, "ssl_shutdown_timeout": 2} if context else {}))
        if context and writer.get_extra_info("ssl_object").selected_alpn_protocol() not in {None, "http/1.1"}:
            writer.close(); raise ProxyError("Upstream negotiated an unsupported HTTP protocol")
        return reader, writer

    def new_flow(self, meta, correlation, identity=None, replay_of=None):
        p, host, port = parse_url(meta["url"])
        flow = {"id": identity or uuid.uuid4().hex, "session_id": self.path.name, "created": time.time(), "state": "receiving",
                "method": meta["method"], "url": safe_url(meta["url"]), "host": host, "port": port,
                "request_headers": safe_headers(meta["headers"]), "workspace": self.config["workspace"],
                "correlation": {**self.config["correlation"], **correlation}, "replay_of": replay_of}
        self.store.save(flow)
        return flow

    def authenticate(self, headers):
        value = next((v for k, v in headers if k.lower() == "proxy-authorization"), "")
        try:
            kind, encoded = value.split(" ", 1)
            user, password = base64.b64decode(encoded, validate=True).decode().split(":", 1)
            if kind.lower() != "basic" or password != "route": raise ValueError()
            for token, correlation in self.config["bindings"].items():
                if secrets.compare_digest(user, token): return correlation
        except (ValueError, UnicodeError): pass
        raise ProxyError("Proxy authentication required; use the session env launcher")

    async def next_event(self, conn, reader):
        while True:
            event = conn.next_event()
            if event is h11.NEED_DATA:
                data = await reader.read(32768)
                conn.receive_data(data)
            else: return event

    async def send(self, writer, conn, event):
        data = conn.send(event)
        if data: writer.write(data); await writer.drain()

    async def error(self, writer, status):
        if writer.is_closing(): return
        body = {403: b"Destination denied", 407: b"Proxy authentication required", 413: b"Interception body limit exceeded", 426: b"WebSocket upgrade unsupported", 502: b"Upstream/protocol failure", 504: b"Proxy deadline exceeded", 505: b"HTTP/1.1 required", 503: b"Proxy capacity exceeded"}.get(status, b"Request dropped")
        writer.write(f"HTTP/1.1 {status} Proxy Error\r\nConnection: close\r\nContent-Length: {len(body)}\r\n".encode()
                     + (b'Proxy-Authenticate: Basic realm="OpenCROW"\r\n' if status == 407 else b"") + b"\r\n" + body)
        await writer.drain()

    async def start(self):
        self.listener = await asyncio.start_server(self.handle, "127.0.0.1", self.config["port"], limit=65536)
        self.port = self.listener.sockets[0].getsockname()[1]

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        if len(self.tasks) >= self.config["max_connections"]:
            await self.error(writer, 503); writer.close(); return
        self.tasks.add(task); self.writers.add(writer)
        try:
            await self.connection(reader, writer)
        except (asyncio.CancelledError, ConnectionError, ssl.SSLError, OSError): pass
        finally:
            self.tasks.discard(task); self.writers.discard(writer)
            writer.close()
            try: await asyncio.wait_for(writer.wait_closed(), 2)
            except (OSError, asyncio.TimeoutError): pass

    async def connection(self, reader, writer, tunnel=None, correlation=None):
        conn = h11.Connection(h11.SERVER, max_incomplete_event_size=32768)
        while True:
            flow = None
            started_response = [False]
            try:
                async with asyncio.timeout(self.config["request_timeout_sec"]):
                    event = await self.next_event(conn, reader)
                    if isinstance(event, h11.ConnectionClosed): return
                    if not isinstance(event, h11.Request): raise ProxyError("HTTP request expected")
                    if event.http_version != b"1.1": await self.error(writer, 505); return
                    headers = [(k.decode("ascii"), v.decode("latin1")) for k, v in event.headers.raw_items()]
                    if sum(len(k) + len(v) for k, v in headers) > 32768: raise ProxyError("Header limit exceeded")
                    if correlation is None:
                        try: corr = self.authenticate(headers)
                        except ProxyError: await self.error(writer, 407); return
                    else: corr = correlation
                    if event.method == b"CONNECT":
                        if tunnel: raise ProxyError("Nested CONNECT is forbidden")
                        await self.connect(event, conn, reader, writer, corr)
                        return
                    if any(k.lower() == "upgrade" for k, _ in headers): await self.error(writer, 426); return
                    target = event.target.decode("ascii")
                    if tunnel:
                        if not target.startswith("/"): raise ProxyError("TLS tunnel requires origin-form requests")
                        target = tunnel + target
                    meta = {"url": target, "method": event.method.decode("ascii"), "headers": [(k, v) for k, v in headers if k.lower() != "proxy-authorization"]}
                    await self.scope(target)
                    flow = self.new_flow(meta, corr)
                    if any(k.lower() == "expect" and v.lower() == "100-continue" for k, v in headers):
                        await self.send(writer, conn, h11.InformationalResponse(status_code=100, headers=[]))
                    await self.exchange(meta, flow, conn, reader, writer, started_response)
                    if conn.our_state is h11.MUST_CLOSE or conn.their_state is h11.MUST_CLOSE: return
                    conn.start_next_cycle()
            except asyncio.CancelledError:
                if flow:
                    flow.update(state="interrupted", error="Proxy shutdown; request was not replayed", finished=time.time()); self.store.save(flow)
                raise
            except Exception as exc:
                if flow:
                    flow.update(state="failed", error="deadline_exceeded" if isinstance(exc, TimeoutError) else "scope_denied" if isinstance(exc, ProxyError) else "upstream_or_protocol_error", finished=time.time()); self.store.save(flow)
                if not started_response[0]:
                    await self.error(writer, 504 if isinstance(exc, TimeoutError) else 413 if isinstance(exc, BodyLimit) else 403 if isinstance(exc, ProxyError) else 502)
                return

    async def connect(self, event, conn, reader, writer, correlation):
        target = event.target.decode("ascii")
        p, host, port, ip = await self.scope("https://" + target, connect=True)
        if p.path or p.query or ":" not in target: raise ProxyError("CONNECT requires host:port")
        # Consume end-of-message before switching protocols.
        end = await self.next_event(conn, reader)
        if not isinstance(end, h11.EndOfMessage): raise ProxyError("CONNECT body is not supported")
        flow = self.new_flow({"url": "https://" + target, "method": "CONNECT", "headers": []}, correlation)
        flow["tunnel"] = "intercepted" if self.config["tls_intercept"] else "opaque"
        try:
            if self.config["tls_intercept"]:
                from opencrow_web_proxy_tls import server_context
                if conn.trailing_data[0]: raise ProxyError("Early TLS data before CONNECT acknowledgement is unsupported")
                context = server_context(self.path / "ca", host)
                await self.send(writer, conn, h11.Response(status_code=200, headers=[]))
                await writer.start_tls(context, ssl_handshake_timeout=10, ssl_shutdown_timeout=2)
                if writer.get_extra_info("ssl_object").selected_alpn_protocol() not in {None, "http/1.1"}: raise ProxyError("HTTP/2 interception is unsupported")
                await self.connection(reader, writer, "https://" + authority(host, port, "https"), correlation)
            else:
                upstream_reader, upstream_writer = await asyncio.open_connection(ip, port)
                try:
                    await self.send(writer, conn, h11.Response(status_code=200, headers=[]))
                    if conn.trailing_data[0]: upstream_writer.write(conn.trailing_data[0]); await upstream_writer.drain()
                    counts = [0, 0]
                    async def pump(source, sink, index):
                        while data := await asyncio.wait_for(source.read(32768), 30):
                            counts[index] += len(data); sink.write(data); await sink.drain()
                        if sink.can_write_eof(): sink.write_eof()
                    await asyncio.gather(pump(reader, upstream_writer, 0), pump(upstream_reader, writer, 1))
                    flow.update(request_bytes=counts[0], response_bytes=counts[1])
                finally: upstream_writer.close(); await upstream_writer.wait_closed()
            flow.update(state="completed", status=200)
        except BaseException:
            flow.update(state="interrupted", error="Tunnel ended or was interrupted")
            raise
        finally:
            flow["finished"] = time.time(); self.store.save(flow)

    async def request_body(self, conn, reader, capture, forward=None):
        body = bytearray()
        while True:
            event = await self.next_event(conn, reader)
            if isinstance(event, h11.EndOfMessage):
                if forward: await forward(h11.EndOfMessage(headers=cleaned([(k.decode(), v.decode("latin1")) for k, v in event.headers])))
                return bytes(body)
            if not isinstance(event, h11.Data): raise ProxyError("Incomplete request body")
            capture.feed(event.data)
            if forward: await forward(h11.Data(data=event.data))
            else:
                body.extend(event.data)
                if len(body) > self.config["max_edit_bytes"]: raise BodyLimit()

    async def exchange(self, original, flow, conn=None, reader=None, writer=None, started_response=None, replay_body=None):
        request_capture = Capture(self.config["capture_bytes"])
        response_capture = Capture(self.config["capture_bytes"])
        modified_capture = Capture(self.config["capture_bytes"])
        versions = {}
        upstream_writer = None
        response_meta = None
        meta = copy.deepcopy(original)
        body = replay_body
        try:
            rules = [rule for rule in self.config["rules"] if self.rule_matches(rule, meta)] if replay_body is None else []
            pause = self.config["mode"] == "pause" and replay_body is None
            buffered = replay_body is not None or pause or bool(rules)
            if replay_body is None and buffered:
                body = await self.request_body(conn, reader, request_capture)
            elif replay_body is not None: request_capture.feed(body)
            if buffered:
                versions["original"] = (original, request_capture)
                flow.update(request_body=request_capture.summary())
                self.store.save(flow, versions)
                for rule in rules:
                    if rule.get("action") == "drop": raise ProxyError("Request dropped by scoped rule")
                    meta, body = edit_request(meta, body, rule.get("edit", {}))
                if pause:
                    event = asyncio.Event()
                    self.pending[flow["id"]] = {"event": event, "meta": meta, "body": body, "decision": None, "flow": flow}
                    flow["state"] = "paused"; self.store.save(flow)
                    try:
                        await asyncio.wait_for(event.wait(), self.config["pause_timeout_sec"])
                    except TimeoutError:
                        if self.config["timeout_policy"] == "drop": raise ProxyError("Interception deadline: dropped")
                    finally:
                        pending = self.pending.pop(flow["id"])
                    if pending["decision"] == "drop": raise ProxyError("Request dropped")
                    meta, body = pending["meta"], pending["body"]
                meta, body = edit_request(meta, body, {})
                modified_capture.feed(body)
            flow.update(state="forwarding", url=safe_url(meta["url"]), method=meta["method"], modified=meta != original or (buffered and body != bytes(request_capture.data)))
            self.store.save(flow)
            upstream_reader, upstream_writer = await self.open_upstream(meta)
            upstream = h11.Connection(h11.CLIENT, max_incomplete_event_size=32768)
            p, _, _ = parse_url(meta["url"])
            path = urlunsplit(("", "", p.path or "/", p.query, ""))
            await self.send(upstream_writer, upstream, h11.Request(method=meta["method"], target=path, headers=request_headers(meta, len(body) if buffered else None)))
            if buffered:
                await self.send(upstream_writer, upstream, h11.Data(data=body))
                await self.send(upstream_writer, upstream, h11.EndOfMessage())
            else:
                await self.request_body(conn, reader, request_capture, lambda event: self.send(upstream_writer, upstream, event))
                modified_capture = request_capture
            versions.update(original=(original, request_capture), modified=(meta, modified_capture))
            flow["request_body"] = request_capture.summary()
            flow["modified_request_body"] = modified_capture.summary()
            flow["request_sent"] = time.time()
            self.store.save(flow, versions)
            while True:
                event = await self.next_event(upstream, upstream_reader)
                if isinstance(event, h11.InformationalResponse):
                    if event.status_code == 101: raise ProxyError("Protocol upgrade is unsupported")
                    if writer: await self.send(writer, conn, event)
                elif isinstance(event, h11.Response):
                    response_meta = {"status": event.status_code, "headers": [(k.decode(), v.decode("latin1")) for k, v in event.headers.raw_items()]}
                    flow.update(status=event.status_code, response_headers=safe_headers(response_meta["headers"]), response_started=time.time())
                    if writer:
                        if started_response is not None: started_response[0] = True
                        await self.send(writer, conn, h11.Response(status_code=event.status_code, headers=cleaned(response_meta["headers"])))
                elif isinstance(event, h11.Data):
                    response_capture.feed(event.data)
                    if writer: await self.send(writer, conn, h11.Data(data=event.data))
                elif isinstance(event, h11.EndOfMessage):
                    if writer: await self.send(writer, conn, h11.EndOfMessage(headers=cleaned([(k.decode(), v.decode("latin1")) for k, v in event.headers])))
                    flow.update(state="completed", response_body=response_capture.summary(), finished=time.time())
                    break
                else: raise ProxyError("Incomplete upstream response")
        finally:
            versions.setdefault("original", (original, request_capture))
            if response_meta:
                versions["response"] = (response_meta, response_capture)
                flow["response_body"] = response_capture.summary()
            self.store.save(flow, versions)
            if upstream_writer:
                upstream_writer.close()
                try: await asyncio.wait_for(upstream_writer.wait_closed(), 2)
                except (OSError, TimeoutError): pass

    @staticmethod
    def rule_matches(rule, meta):
        _, host, port = parse_url(meta["url"])
        return host == rule["host"] and port == rule["port"] and urlsplit(meta["url"]).path.startswith(rule["path_prefix"])

    async def decide(self, identity, action, edit=None):
        item = self.pending.get(identity)
        if not item or item["event"].is_set(): raise ProxyError("Request is no longer paused")
        if edit is not None:
            meta, body = edit_request(item["meta"], item["body"], edit)
            await self.scope(meta["url"])
            item.update(meta=meta, body=body)
            cap = Capture(self.config["capture_bytes"]); cap.feed(body)
            self.store.save(item["flow"], {"modified": (meta, cap)})
        if action in {"forward", "drop"}:
            item["decision"] = action; item["event"].set()
        return {"request_id": identity, "decision": action}

    async def replay(self, identity, edit, confirm):
        if self.replays >= 4: raise ProxyError("Replay concurrency limit reached")
        flow = self.store.get(identity)
        meta, body = self.store.raw(identity, "modified" if flow.get("modified") else "original")
        summary = flow.get("modified_request_body" if flow.get("modified") else "request_body", {})
        if summary.get("truncated", True) or flow["method"] == "CONNECT": raise ProxyError("Truncated bodies and opaque tunnels cannot be replayed")
        meta, body = edit_request(meta, body, edit or {})
        if meta["method"].upper() not in {"GET", "HEAD", "OPTIONS"} and confirm is not True:
            raise ProxyError("Replay of side-effectful methods requires confirm_side_effects=true")
        await self.scope(meta["url"])
        fresh = self.new_flow(meta, flow["correlation"], replay_of=identity)
        fresh["state"] = "queued"; self.store.save(fresh)
        self.replays += 1
        async def run():
            try:
                async with asyncio.timeout(self.config["request_timeout_sec"]): await self.exchange(meta, fresh, replay_body=body)
            except BaseException:
                fresh.update(state="failed", error="Replay failed or was interrupted", finished=time.time()); self.store.save(fresh)
            finally: self.replays -= 1
        task = asyncio.create_task(run()); self.tasks.add(task); task.add_done_callback(self.tasks.discard)
        return {"request_id": fresh["id"], "state": "queued", "replay_of": identity}

    async def close(self):
        if self.listener: self.listener.close()
        for writer in list(self.writers):
            writer.close()
            writer.transport.abort()
        for task in list(self.tasks): task.cancel()
        await asyncio.gather(*list(self.tasks), return_exceptions=True)
        if self.listener: await self.listener.wait_closed()
        self.store.db.close()


class BodyLimit(ProxyError):
    pass
