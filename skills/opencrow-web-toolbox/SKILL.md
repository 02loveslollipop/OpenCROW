---
name: opencrow-web-toolbox
description: Use the native headless HTTP(S) proxy and installed web CTF tooling for scoped traffic inspection, interception, editing, replay, discovery, fuzzing and SQL injection workflows.
---

# OpenCROW Web Toolbox

## Runtime preflight

Probe required commands with `command -v` and Python modules with `importlib.util.find_spec` before use. Prefer a PATH-resolved OpenCROW MCP helper or the `ctf`/`sage` environment when available, then the managed helper or system Python. If a capability is missing, stop that path safely and report the exact missing command or module.

Use this skill for web CTF work that starts from discovery and fuzzing rather than browser automation: `sqlmap`, `gobuster`, `ffuf`, `dirb`, and `wfuzz`. The `full` installer profile also tracks manual acquisition steps for Burp Suite Community and OWASP ZAP.

## Quick Start

Start the MCP server from the installed CLI:

```bash
opencrow-web-mcp
```

Verify the mapped stack:

```bash
python3 scripts/verify_toolkit.py
```

## Workflow

1. Start with endpoint and content discovery using `ffuf`, `gobuster`, or `dirb`.
2. Use `wfuzz` when the problem is parameter fuzzing or more custom request mutation.
3. Use `sqlmap` when the challenge is plausibly SQLi-driven and the target is stable enough for automation.
4. Use `playwright` separately when the task needs a real browser or a JS-heavy flow.
5. For agent traffic, use `web_proxy_start` with the existing workspace and exact authorized host/port/path targets. Observation and opaque HTTPS are defaults. Private targets need `allow_private`; TLS interception and raw evidence each require explicit session options. Provider/model APIs stay excluded.
6. Route tool commands with `opencrow-web-proxy env SESSION_ID -- COMMAND`, or attach `proxy_session_id` to a worker. Never apply the tool environment to the provider/model process. Direct sockets and applications ignoring proxies are not captured; configure browser/Playwright proxy authentication explicitly inside its launch script.
7. Read `web_proxy_history` and request/response metadata first. Opt into `web_proxy_intercept_set` pause mode before `web_proxy_request_edit`, then forward/drop that request ID. Replay is queued and must be polled; side-effectful methods require explicit confirmation. Export sanitized HAR/JSONL when evidence is needed across turns.
8. Prefer typed MCP operations. Burp/ZAP remain optional GUI workflows; the native proxy requires neither. See [proxy protocol, trust and cleanup](references/proxy.md).

## Tool Selection

- Use `ffuf` for fast fuzzing against paths, parameters, or virtual hosts.
- Use `gobuster` for straightforward wordlist-driven discovery.
- Use `dirb` when a challenge guide or prior workflow already assumes DIRB-style usage.
- Use `wfuzz` when request templating matters more than raw speed.
- Use `sqlmap` when the target and request shape are stable enough to automate.

## Resources

- `opencrow-web-mcp`: stdio MCP server for typed discovery, fuzzing, and sqlmap workflows.
- `opencrow-web-proxy-mcp`: standalone native proxy controls with stable session/history resources; these tools are also exposed by `opencrow-web-mcp`.
- `scripts/verify_toolkit.py`: confirm that the mapped web discovery tools are installed.
- `references/tooling.md`: quick selection notes for web workflows.
