"""Private durable proxy evidence; summaries never include payloads or credentials."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


class ProxyError(ValueError):
    pass


PROVIDER_HOSTS = ("openai.com", "chatgpt.com", "anthropic.com", "claude.ai", "googleapis.com", "opencode.ai", "openrouter.ai", "githubcopilot.com", "mistral.ai", "deepseek.com", "x.ai")
SECRET = re.compile(r"authorization|cookie|token|api[-_]?key|secret|password|credential", re.I)
SESSION_ID = re.compile(r"^[a-f0-9]{32}$")


def private_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.lstat()
    if path.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ProxyError("Proxy state directory must be owned, private and not a symlink")
    return path


def write_private(path: Path, data: bytes):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)


def state_root():
    return private_dir(Path(os.environ.get("OPENCROW_WEB_PROXY_STATE_DIR", str(Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "opencrow/web-proxy"))).expanduser())


def session_dir(session_id):
    if not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
        raise ProxyError("Invalid proxy session ID")
    path = state_root() / session_id
    if not path.is_dir():
        raise ProxyError("Proxy session does not exist for this user")
    return private_dir(path)


def safe_url(url):
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc.rsplit("@", 1)[-1], parsed.path, urlencode([(key, "[redacted]") for key, _ in parse_qsl(parsed.query, keep_blank_values=True)]), ""))


def safe_headers(headers):
    public = {"host", "content-type", "content-length", "content-encoding", "transfer-encoding", "accept", "accept-encoding", "connection", "cache-control", "date", "server", "user-agent", "allow"}
    return [[key, safe_url(value) if key.lower() in {"location", "content-location", "referer"}
             else value if key.lower() in public and not SECRET.search(key) else "[redacted]"] for key, value in headers]


def integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ProxyError(f"{name} must be an integer between {low} and {high}")
    return value


def hostname(value):
    if not isinstance(value, str) or not value or len(value) > 253 or any(c in value for c in " /\\@?#%\r\n\t"):
        raise ProxyError("An exact target hostname or IP address is required")
    try:
        return str(ipaddress.ip_address(value.strip("[]")))
    except ValueError:
        value = value.rstrip(".").encode("idna").decode("ascii").lower()
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", value):
            raise ProxyError("Invalid target hostname")
        return value


def config_for(args):
    workspace = Path(args.get("workspace", "")).expanduser().resolve()
    if not args.get("workspace") or not workspace.is_dir():
        raise ProxyError("An existing workspace is required")
    targets = args.get("targets")
    if not isinstance(targets, list) or not 1 <= len(targets) <= 32:
        raise ProxyError("Supply 1 to 32 explicitly authorized targets")
    parsed = []
    for target in targets:
        if not isinstance(target, dict) or set(target) - {"host", "port", "path_prefix", "allow_private"}:
            raise ProxyError("Invalid target scope")
        prefix = target.get("path_prefix", "/")
        if not isinstance(prefix, str) or not prefix.startswith("/") or any(c in prefix for c in "?#\r\n"):
            raise ProxyError("Target path_prefix must be an absolute URL path")
        if not isinstance(target.get("allow_private", False), bool):
            raise ProxyError("allow_private must be boolean")
        parsed.append({"host": hostname(target.get("host")), "port": integer(target.get("port"), "port", 1, 65535), "path_prefix": prefix, "allow_private": target.get("allow_private", False)})
    protected = args.get("provider_hosts", [])
    if not isinstance(protected, list) or len(protected) > 32:
        raise ProxyError("provider_hosts must be a bounded hostname list")
    config = {"workspace": str(workspace), "targets": parsed, "provider_hosts": [hostname(h) for h in protected],
              "bind_host": "127.0.0.1", "port": integer(args.get("port", 0), "port", 0, 65535),
              "mode": "observe", "pause_timeout_sec": 15, "timeout_policy": "drop", "rules": [],
              "request_timeout_sec": integer(args.get("request_timeout_sec", 60), "request_timeout_sec", 1, 3600),
              "capture_bytes": integer(args.get("capture_bytes", 65536), "capture_bytes", 0, 1048576),
              "history_limit": integer(args.get("history_limit", 500), "history_limit", 1, 10000),
              "history_bytes": integer(args.get("history_bytes", 33554432), "history_bytes", 4096, 268435456),
              "retention_sec": integer(args.get("retention_sec", 86400), "retention_sec", 60, 2592000),
              "max_connections": integer(args.get("max_connections", 32), "max_connections", 1, 128),
              "max_edit_bytes": 1048576, "correlation": {}}
    for flag in ("tls_intercept", "allow_raw_access", "capture_provider_traffic"):
        if not isinstance(args.get(flag, False), bool):
            raise ProxyError(f"{flag} must be boolean")
        config[flag] = args.get(flag, False)
    if args.get("upstream_ca"):
        path = Path(args["upstream_ca"]).expanduser().resolve()
        if not path.is_file():
            raise ProxyError("upstream_ca must be an existing PEM trust bundle")
        config["upstream_ca"] = str(path)
    for key, value in args.get("correlation", {}).items():
        if key not in {"provider", "worker_id", "run_id", "challenge_id"} or not isinstance(value, str) or len(value) > 128:
            raise ProxyError("Invalid correlation metadata")
        config["correlation"][key] = value
    return config


class Capture:
    def __init__(self, limit):
        self.limit, self.size, self.data, self.digest = limit, 0, bytearray(), hashlib.sha256()
        self.trailers = []

    def feed(self, data):
        self.size += len(data)
        self.digest.update(data)
        self.data.extend(data[:max(0, self.limit - len(self.data))])

    def summary(self):
        return {"size": self.size, "captured_size": len(self.data), "truncated": self.size > len(self.data), "sha256": self.digest.hexdigest(), "trailers_present": bool(self.trailers)}


class Store:
    def __init__(self, path, config):
        self.path, self.config = path, config
        private_dir(path / "raw")
        self.db = sqlite3.connect(path / "history.sqlite")
        self.db.execute("CREATE TABLE IF NOT EXISTS flows(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE,created REAL,state TEXT,data TEXT,bytes INTEGER)")
        self.db.commit()
        os.chmod(path / "history.sqlite", 0o600)
        self.prune()

    def recover(self):
        known = {row[0] for row in self.db.execute("SELECT id FROM flows")}
        for directory in (self.path / "raw").iterdir():
            if directory.name not in known: shutil.rmtree(directory, ignore_errors=True)
        for row in self.db.execute("SELECT data FROM flows WHERE state IN ('receiving','paused','forwarding','queued')").fetchall():
            flow = json.loads(row[0]); flow.update(state="interrupted", error="Proxy process restarted; request was not replayed", finished=time.time())
            self.save(flow)

    def save(self, flow, versions=None):
        directory = self.path / "raw" / flow["id"]
        if versions:
            private_dir(directory)
            for name, (metadata, capture) in versions.items():
                write_private(directory / (name + ".json"), json.dumps(metadata).encode())
                write_private(directory / (name + ".body"), bytes(capture.data))
        total = sum(p.stat().st_size for p in directory.iterdir()) if directory.exists() else 0
        self.db.execute("INSERT INTO flows(id,created,state,data,bytes) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,data=excluded.data,bytes=excluded.bytes", (flow["id"], flow["created"], flow["state"], json.dumps(flow), total + len(json.dumps(flow))))
        self.db.commit()
        self.prune()

    def prune(self):
        rows = self.db.execute("SELECT id,created,bytes FROM flows ORDER BY seq DESC").fetchall()
        total = 0
        for index, (identity, created, size) in enumerate(rows):
            total += size
            if index >= self.config["history_limit"] or total > self.config["history_bytes"] or created < time.time() - self.config["retention_sec"]:
                # Active records remain until terminal; their number is bounded
                # independently by the connection/replay limits.
                state = self.db.execute("SELECT state FROM flows WHERE id=?", (identity,)).fetchone()[0]
                if state not in {"receiving", "paused", "forwarding", "queued"}:
                    self.delete(identity)

    def delete(self, identity):
        self.get(identity)
        self.db.execute("DELETE FROM flows WHERE id=?", (identity,)); self.db.commit()
        shutil.rmtree(self.path / "raw" / identity, ignore_errors=True)

    def get(self, identity):
        if not isinstance(identity, str) or not SESSION_ID.fullmatch(identity):
            raise ProxyError("Invalid request ID")
        row = self.db.execute("SELECT data FROM flows WHERE id=?", (identity,)).fetchone()
        if not row:
            raise ProxyError("Request is no longer retained")
        return json.loads(row[0])

    def history(self, args):
        after = integer(args.get("after", 0), "after", 0, 2**63-1)
        limit = integer(args.get("limit", 25), "limit", 1, 100)
        query, values = "SELECT seq,data FROM flows WHERE seq>?", [after]
        for key in ("state", "method", "host", "status"):
            if key in args:
                query += " AND json_extract(data,?)=?"; values.extend(["$." + key, args[key]])
        query += " ORDER BY seq LIMIT ?"; values.append(limit)
        rows = self.db.execute(query, values).fetchall()
        return {"requests": [{"cursor": seq, **json.loads(data)} for seq, data in rows], "next_cursor": rows[-1][0] if rows else after}

    def raw(self, identity, version):
        self.get(identity)
        if version not in {"original", "modified", "response"}:
            raise ProxyError("Invalid evidence version")
        directory = self.path / "raw" / identity
        try:
            return json.loads((directory / (version + ".json")).read_text()), (directory / (version + ".body")).read_bytes()
        except FileNotFoundError as exc:
            raise ProxyError("Evidence version is not available") from exc
