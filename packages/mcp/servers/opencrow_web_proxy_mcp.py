#!/usr/bin/env python3
"""Provider-neutral control of OpenCROW's owned HTTP(S) proxy."""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import opencrow_web_proxy as proxy
from opencrow_web_proxy_store import ProxyError, Store, session_dir, SESSION_ID
from opencrow_mcp_core import (MCPTool, MCPResourceTemplate, StdioMCPServer, json_resource_contents,
    success_envelope, error_envelope, make_toolbox_info_handler, make_toolbox_self_test_handler, make_toolbox_capabilities_handler)

SERVER_NAME = "opencrow-web-proxy-mcp"
TOOLBOX_ID = "opencrow-web-proxy"
STRING = {"type": "string", "minLength": 1, "maxLength": 4096}
ID = {"type": "string", "minLength": 32, "maxLength": 32}
BOOL = {"type": "boolean"}

def number(low, high): return {"type": "integer", "minimum": low, "maximum": high}
def obj(properties, required=()): return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}
def array(items, count=32): return {"type": "array", "items": items, "maxItems": count}
HEADERS = {"type": "object", "additionalProperties": {"type": "string", "maxLength": 8192}, "maxProperties": 64}
EDIT = obj({"url": STRING, "method": STRING, "headers": HEADERS, "remove_headers": array(STRING, 64), "body_base64": {"type": "string", "maxLength": 1398104}})
TARGET = obj({"host": STRING, "port": number(1, 65535), "path_prefix": STRING, "allow_private": BOOL}, ["host", "port"])
CORRELATION = obj({key: {"type": "string", "maxLength": 128} for key in ("provider", "worker_id", "run_id", "challenge_id")})
HISTORY = {"after": number(0, 2**63-1), "limit": number(1, 100), "state": STRING, "method": STRING, "host": STRING, "status": number(100, 599)}
SESSION = {"session_id": ID}
REQUEST = {**SESSION, "request_id": ID}
TOOLS = {
    "web_proxy_start": ("Start an owned loopback proxy for explicitly authorized targets, or restart a saved session_id. HTTPS is opaque unless tls_intercept is enabled.", obj({**SESSION, "workspace": STRING, "targets": array(TARGET), "provider_hosts": array(STRING), "port": number(0, 65535), "tls_intercept": BOOL, "allow_raw_access": BOOL, "capture_provider_traffic": BOOL, "upstream_ca": STRING, "correlation": CORRELATION, "request_timeout_sec": number(1, 3600), "capture_bytes": number(0, 1048576), "history_limit": number(1, 10000), "history_bytes": number(4096, 268435456), "retention_sec": number(60, 2592000), "max_connections": number(1, 128)}), "start"),
    "web_proxy_status": ("Inspect health, scope, deadlines and pending request IDs without exposing route credentials.", obj(SESSION, SESSION), "status"),
    "web_proxy_stop": ("Stop the owned listener, interrupt active requests, destroy the session CA and retain private history.", obj(SESSION, SESSION), "stop"),
    "web_proxy_history": ("Read a bounded sanitized history page. Bodies are omitted and query values/secrets redacted.", obj({**SESSION, **HISTORY}, SESSION), "history"),
    "web_proxy_request_get": ("Get sanitized metadata or explicitly authorized bounded raw evidence (original, modified or response).", obj({**REQUEST, "raw": BOOL, "version": {"type": "string", "enum": ["original", "modified", "response"]}, "offset": number(0, 1048576), "limit": number(1, 16384)}, REQUEST), "get"),
    "web_proxy_response_get": ("Get response metadata or an explicitly authorized bounded raw response slice.", obj({**REQUEST, "raw": BOOL, "offset": number(0, 1048576), "limit": number(1, 16384)}, REQUEST), "response"),
    "web_proxy_intercept_set": ("Opt into bounded pause/edit mode, or restore observe/forward. Deadlines drop by default; forward policy is explicit.", obj({**SESSION, "mode": {"type": "string", "enum": ["observe", "pause"]}, "pause_timeout_sec": number(1, 120), "timeout_policy": {"type": "string", "enum": ["drop", "forward"]}}, ["session_id", "mode"]), "intercept"),
    "web_proxy_request_edit": ("Edit a paused request. URL determines Host; framing is recomputed. Original evidence remains separate.", obj({**REQUEST, "edit": EDIT}, ["session_id", "request_id", "edit"]), "edit"),
    "web_proxy_forward": ("Forward one paused request exactly once using its current edited version.", obj(REQUEST, REQUEST), "forward"),
    "web_proxy_drop": ("Drop one paused request exactly once.", obj(REQUEST, REQUEST), "drop"),
    "web_proxy_replay": ("Queue one explicit replay without recursive interception. POST/PUT/etc require confirm_side_effects; inspect history for outcome.", obj({**REQUEST, "edit": EDIT, "confirm_side_effects": BOOL}, REQUEST), "replay"),
    "web_proxy_rules": ("List redacted rule metadata or replace bounded host/port/path-scoped automatic rewrite/drop rules.", obj({**SESSION, "rules": array(obj({"host": STRING, "port": number(1, 65535), "path_prefix": STRING, "action": {"type": "string", "enum": ["rewrite", "drop"]}, "edit": EDIT}, ["host", "port"]))}, SESSION), "rules"),
    "web_proxy_export": ("Export a bounded sanitized HAR/JSONL page to the session workspace; raw bodies and CA keys are excluded.", obj({**SESSION, **HISTORY, "format": {"type": "string", "enum": ["har", "jsonl"]}}, SESSION), "export"),
    "web_proxy_compare": ("Compare status, wire-body hashes and sizes of two retained responses.", obj({**REQUEST, "other_request_id": ID}, ["session_id", "request_id", "other_request_id"]), "compare"),
    "web_proxy_delete": ("Explicitly delete a terminal request, or all stopped-session history and private material.", obj(REQUEST, SESSION), "delete"),
}
OPERATIONS = [{"name": name, "description": spec[0]} for name, spec in TOOLS.items()]


def validate(value, schema):
    kind = schema.get("type")
    valid = {"object": lambda: isinstance(value, dict), "array": lambda: isinstance(value, list), "string": lambda: isinstance(value, str), "boolean": lambda: isinstance(value, bool), "integer": lambda: isinstance(value, int) and not isinstance(value, bool)}[kind]()
    if not valid: raise ProxyError("Proxy argument has an invalid type")
    if "enum" in schema and value not in schema["enum"]: raise ProxyError("Proxy argument is outside the supported enum")
    if kind == "object":
        if len(value) > schema.get("maxProperties", 64) or set(schema.get("required", [])) - set(value): raise ProxyError("Missing/oversized proxy argument object")
        for key, item in value.items():
            child = schema.get("properties", {}).get(key, schema.get("additionalProperties"))
            if not child: raise ProxyError("Unknown proxy argument")
            validate(item, child)
    elif kind == "array":
        if len(value) > schema.get("maxItems", 32): raise ProxyError("Proxy argument list too large")
        for item in value: validate(item, schema["items"])
    elif kind == "string" and not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 4096): raise ProxyError("Proxy argument string length outside bounds")
    elif kind == "integer" and not schema.get("minimum", value) <= value <= schema.get("maximum", value): raise ProxyError("Proxy integer outside bounds")


def operation(identity, method, arguments):
    try: return proxy.rpc(identity, method, arguments)
    except (ConnectionRefusedError, FileNotFoundError):
        if method not in {"history", "get", "export", "compare", "delete_request"}: raise ProxyError("Proxy is stopped; restart its saved session_id")
        import fcntl
        path = session_dir(identity)
        with (path / "owner.lock").open("a") as lock:
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc: raise ProxyError("Proxy is starting or stopping; retry after health settles") from exc
            config = proxy.load_config(path)
            store = Store(path, config)
            try:
                store.recover()
                controller = proxy.Controller(SimpleNamespace(path=path, config=config, store=store))
                return asyncio.run(controller.handle(method, arguments))
            finally: store.db.close()


def invoke(name, arguments, toolbox=TOOLBOX_ID):
    # Never echo edit bodies, target query strings or raw headers into envelopes.
    inputs = {key: arguments[key] for key in ("session_id", "request_id") if isinstance(arguments, dict) and key in arguments and isinstance(arguments[key], str) and SESSION_ID.fullmatch(arguments[key])}
    try:
        validate(arguments, TOOLS[name][1])
        args = dict(arguments); identity = args.pop("session_id", None); method = TOOLS[name][2]
        if method == "start": result = proxy.start(arguments)
        elif method in {"status", "stop"}: result = {"status": proxy.status, "stop": proxy.stop}[method](identity)
        elif method == "delete" and not args: result = proxy.delete(identity)
        else:
            if method == "response": method = "get"; args["version"] = "response"
            if method == "delete": method = "delete_request"
            result = operation(identity, method, args)
        return success_envelope(toolbox=toolbox, operation=name, summary="Proxy operation recorded; inspect request state for network outcome.", inputs=inputs, observations=[result],
                                artifacts=[result["path"]] if name == "web_proxy_export" else [], command="OpenCROW owned proxy control: " + method)
    except (ProxyError, OSError, ValueError, KeyError, TypeError) as exc:
        message = str(exc) if isinstance(exc, ProxyError) else "Proxy operation failed; check session health and input schema"
        return error_envelope(toolbox=toolbox, operation=name, summary=message, inputs=inputs, stderr=message, exit_code=2)


def proxy_tools(toolbox=TOOLBOX_ID):
    return [MCPTool(name, description, schema, lambda args, name=name: invoke(name, args, toolbox)) for name, (description, schema, _) in TOOLS.items()]


def register_resources(server):
    for suffix, method in (("status", "status"), ("history", "history")):
        server.register_resource_template(MCPResourceTemplate(f"opencrow://{server.server_name}/sessions/{{session_id}}/{suffix}", "Proxy session " + suffix, "Owned sanitized proxy state", "application/json",
            lambda uri, params, method=method: json_resource_contents(uri, proxy.status(params["session_id"]) if method == "status" else operation(params["session_id"], method, {}))))


def build_server():
    server = StdioMCPServer(server_name=SERVER_NAME, server_version="0.1.0", instructions="Own HTTP(S) proxy sessions; authorize target scope explicitly. Default observe, opaque TLS, private control. Raw evidence requires prior explicit opt-in.")
    metadata = dict(toolbox=TOOLBOX_ID, display_name="OpenCROW Native Web Proxy", server_name=SERVER_NAME, server_version="0.1.0", operations=OPERATIONS)
    empty = obj({})
    server.register_tools([
        MCPTool("toolbox_info", "Proxy protocol and operations.", empty, make_toolbox_info_handler(**metadata, summary="Native proxy metadata.")),
        MCPTool("toolbox_self_test", "Protocol-only readiness; no scans or network connections.", empty, make_toolbox_self_test_handler(**metadata)),
        MCPTool("toolbox_capabilities", "Typed proxy operations.", empty, make_toolbox_capabilities_handler(TOOLBOX_ID, OPERATIONS)),
        MCPTool("toolbox_verify", "Explicit dependency diagnostics without starting listeners.", empty, lambda args: success_envelope(toolbox=TOOLBOX_ID, operation="toolbox_verify", inputs=args, summary="Proxy dependency availability; no target requests sent.", observations=proxy.dependencies())),
        *proxy_tools(),
    ])
    register_resources(server)
    return server


if __name__ == "__main__": raise SystemExit(build_server().serve())
