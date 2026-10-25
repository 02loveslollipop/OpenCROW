# Native HTTP(S) proxy

OpenCROW owns a headless HTTP proxy with durable history, interception, request edits and explicit replay. Burp Suite, ZAP and a GUI are optional. The proxy uses `h11` for HTTP framing and `cryptography` for certificates; its lifecycle, policy, history and MCP controls are OpenCROW code.

## Install and start

Select the **web** toolbox in a full installation. This installs `opencrow-web-mcp`, `opencrow-web-proxy-mcp`, `opencrow-web-proxy` and the pinned Python dependencies. The runtime requires Python 3.12 or newer. Source installations can use:

```bash
python3 -m pip install -r packages/mcp/requirements-web-proxy.txt
PYTHONPATH=packages/mcp/core:packages/mcp/servers python3 packages/mcp/servers/opencrow_web_proxy_mcp.py
```

Both web MCP servers expose the proxy tools. Existing discovery, fuzzing, sqlmap and optional external Burp workflows remain available. `toolbox_self_test` checks the protocol surface without discovery or starting a listener; `toolbox_verify` reports modules explicitly. `opencrow doctor` reports dependency availability for selected web installations. Repair restores launchers without starting a proxy. Update, rollback and uninstall stop owned proxies and destroy their CA material while retaining evidence; explicitly delete sessions to erase history.

Start with `web_proxy_start` and an existing `workspace` plus exact authorized `targets`, for example:

```json
{
  "workspace": "/work/challenge",
  "targets": [{"host": "challenge.example", "port": 443, "path_prefix": "/"}]
}
```

The target list is the operator's authorization boundary. Hostnames, ports and paths are checked again after edits and before replay. DNS results are validated and a validated IP is used for connection, preventing a second DNS lookup from changing the destination. Local/private addresses require `allow_private: true` on that target; unrestricted wildcards and recursive proxy destinations are rejected. Path scopes reject encoded traversal. Known model/provider hosts are excluded; supply additional custom model endpoints through `provider_hosts`. Capturing them requires both explicit target scope and `capture_provider_traffic: true`.

The data listener binds to `127.0.0.1` and requires a private route credential. Control uses a mode-0600 Unix socket inside owned mode-0700 state, with no HTTP control port. Start/status return an endpoint and session ID, never the route secret. Route credentials are supplied directly to tools through the launcher:

```bash
opencrow-web-proxy env SESSION_ID -- curl https://challenge.example/
```

The launcher executes the command without printing credentials. It sets upper/lower-case HTTP(S) proxy variables and scoped bypass settings only for that process. Tools must obey proxy configuration: curl and Python requests/urllib do; applications ignoring environment proxies and raw/direct sockets are not captured. Go-based tools may refuse environment proxying for localhost even with a target scope; configure their proxy flag explicitly. Browsers/Playwright need their own proxy object: load `opencrow_web_proxy.environment(session_id)` inside the launch script, parse its URL into server/username/password, and pass those fields to the browser without printing them.

## Inspect, pause, edit and replay

Use `web_proxy_history` with `session_id`, optional `host`/`method`/`status`/`state`, a creation cursor `after`, and `limit` (at most 100). Stable request IDs address `web_proxy_request_get` and `web_proxy_response_get`. Session resources live at `opencrow://opencrow-web-proxy-mcp/sessions/{session_id}/status` and `/history`. The original and effective request metadata, timestamps, status, correlation, body sizes/hashes, truncation and errors are retained across turns and restarts. History is also readable after stop.

Observation forwards by default. Set `web_proxy_intercept_set` to `mode: "pause"`; requests are buffered up to 1 MiB and wait at most `pause_timeout_sec` (default 15, maximum 120). The default `timeout_policy: "drop"` fails closed. Choose `"forward"` explicitly to forward the current version on expiry. `web_proxy_request_edit` accepts URL/path/query through a full `url`, `method`, a header map (including cookies), `remove_headers`, and binary-safe `body_base64`. Then call `web_proxy_forward` or `web_proxy_drop` once for the request ID. An expired decision cannot be applied to a later request.

Host and message framing are computed from the effective URL/body. Edits cannot inject Host, Content-Length, transfer encoding or connection headers. Compressed request bodies must have Content-Encoding removed before replacement. Original and modified raw versions remain separate. Request trailers are forwarded in observation mode; editing/replay declines them explicitly. Response editing is outside this first version; responses are forwarded intact.

`web_proxy_rules` replaces at most 32 exact host/port/path-scoped automatic rewrite/drop rules. Rules can only operate within the session target scope, including their rewritten destinations. Rule headers and bodies are not echoed in summaries. `web_proxy_replay` queues one resend, returns its new ID immediately, and bypasses pause/rewrite rules to prevent recursive interception. Replay requires a fully captured request; truncated uploads and opaque tunnels cannot be replayed. Methods other than GET/HEAD/OPTIONS require `confirm_side_effects: true`. At most four replays run concurrently. Inspect the resulting state and use `web_proxy_compare` to compare status, body sizes and wire-body hashes. Redirects are returned to clients rather than automatically followed by replay.

## TLS and protocol envelope

| Traffic | Behavior |
| --- | --- |
| HTTP/1.1 forward requests | Streaming relay, chunk decoding/re-encoding, binary bodies, downstream connection reuse; upstream connections are opened per request. |
| HTTPS CONNECT, default | Authenticated opaque byte relay. End-to-end TLS, HTTP/2 and WebSockets can pass through; only tunnel metadata/byte counts are visible. Whole-host path scope is required because encrypted paths cannot be checked. |
| HTTPS with `tls_intercept: true` | Isolated session CA and dynamic leaf certificates. Upstream certificate verification remains enabled; `upstream_ca` explicitly supplies a target trust bundle when needed. |
| Inspected HTTP/2 | ALPN offers HTTP/1.1 only. Prior-knowledge HTTP/2 is declined with 505; no downgrade that silently corrupts frames. |
| Inspected WebSocket upgrade | Declined with 426. Use opaque CONNECT for uninspected WebSockets. |
| SSE / chunked / compressed responses | Streamed with backpressure. Capture is bounded; compressed evidence/hashes describe wire bytes. The configured request lifetime still applies. |

TLS interception is an explicit session option. Start/status report the **public** CA certificate path. The command launcher adds this CA to a tool-only bundle alongside system roots and configures requests/curl/Node trust for that command. For a separately launched client, trust only this CA in that client profile; never disable verification or install the CA globally. A certificate failure without trust is expected. The proxy's CA key and leaf keys stay private and are never workspace artifacts. CA validity is seven days, leaf validity one day. Stop destroys the CA directory; restart creates a fresh CA, so refresh external client trust. Removing the isolated browser/client profile or process-local trust setting removes trust; no host trust-store removal is needed.

## Workers and Constellation

Pass `proxy_session_id` to `worker_start`. The running session must belong to the source workspace; an isolated worktree can attach to that source session. A sanitized `proxy-session.json` artifact and history URI persist in worker status and follow-up/handoff context. History includes provider and worker correlation. Stop the worker independently of the proxy; multiple turns can revisit retained traffic.

OpenCode V2 receives proxy and trust settings through its **per-session tool environment**, while the SDK/model process remains clean. Codex's Constellation adapter uses its shell environment policy for tools. CLI workers and Claude/Antigravity adapters activate settings in noninteractive `bash -c` tool commands through a private BASH_ENV file; shell-script provider launchers do not activate it. Direct executables, other shells and scripts must use `opencrow-web-proxy env` explicitly. This routing is selective configuration, not a network sandbox or a guarantee that arbitrary applications use a proxy.

For Constellation, set `metadata.proxy_session_id` on the agent or challenge. Create the session on the runtime host with its agent workspace or challenge workspace; route references persist for follow-up turns. Public references are uploaded alongside lifecycle artifacts. Environment files and CA keys stay in private state. A connected OpenCode service must run on the same proxy host (or have a separately configured proxy there); loopback proxy endpoints are not remotely reachable. Custom provider endpoints should be included in `provider_hosts`, and provider/model processes must never be launched with the tool proxy bundle.

## Privacy, limits and cleanup

History summaries and HAR/JSONL exports omit all body content, redact query values and credential/cookie headers, and suppress unrecognized header values. URLs' path components and approved public header values remain visible: avoid putting secrets in path names. Login bodies and binary evidence stay in private bounded files. Raw access requires `allow_raw_access: true` when creating the session **and** `raw: true` on an evidence read; each read returns at most 16 KiB. This is an explicit capability on a trusted local user account, not isolation from another process running as that same user. Do not grant raw access merely to inspect ordinary metadata.

Defaults: 32 connections, 60-second request/tunnel lifetime (maximum 3600), 30-second opaque tunnel idle deadline, 64 KiB capture per body, 500 retained terminal requests, 32 MiB retained history and 24-hour retention. Active records have an additional bounded allowance determined by the connection and body caps. Cleanup runs on state opens, writes and every 30 seconds while the daemon runs. Header blocks are bounded to 32 KiB; control frames and output pages are bounded. Partial streams report truncation/errors; prompt admission or replay admission is never reported as network success.

Private state defaults to `$XDG_STATE_HOME/opencrow/web-proxy` (or `~/.local/state/opencrow/web-proxy`); override with `OPENCROW_WEB_PROXY_STATE_DIR`. `web_proxy_export` writes only a bounded sanitized HAR/JSONL page under the session workspace's `.opencrow/proxy/` directory. Raw history and CA keys are never exported there. `web_proxy_delete` removes a terminal request or a stopped session explicitly. Crashed/paused requests become interrupted when history is reopened or the session restarted, with no automatic resend. Restart with `web_proxy_start({"session_id": "..."})`; scope remains unchanged.

Protocol foundations: [h11](https://h11.readthedocs.io/en/stable/basic-usage.html), [Python streams/TLS](https://docs.python.org/3/library/asyncio-stream.html), [certificate primitives](https://cryptography.io/en/latest/x509/tutorial/).
