---
name: opencrow-web-toolbox
description: Use the installed web CTF tooling plus the Burp Suite MCP server when available. Use when an agent needs `sqlmap`, `gobuster`, `ffuf`, `dirb`, `wfuzz`, or Burp proxy-history -> Repeater -> Intruder -> Collaborator flows.
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

## Burp MCP workflow (proxy history -> Repeater -> Intruder -> Collaborator)

Prefer the Burp MCP server (`burp_*` tools) when configured. Requires the PortSwigger MCP extension enabled in Burp (MCP tab, default `http://127.0.0.1:9876` SSE).

1. Proxy history triage: filter HTTP/WebSocket history with regex, respect the target approval allowlist. Never exfiltrate history outside the approved target.
2. Repeater: replay and mutate promising requests (HTTP/1.1 and HTTP/2), use encoding utilities (URL, Base64) and random string generation as needed.
3. Intruder: send the stabilized Repeater request to Intruder for position-based fuzzing.
4. Collaborator (Pro only): generate payload, inject via Repeater/Intruder, then poll for out-of-band interactions before concluding.
5. Organizer: store confirmed findings as Organizer entries.

If `burp_*` tools are absent, fall back to CLI discovery/fuzzing below and note Burp MCP as unavailable.

## Workflow (CLI fallback)

1. Start with endpoint and content discovery using `ffuf`, `gobuster`, or `dirb`.
2. Use `wfuzz` when the problem is parameter fuzzing or more custom request mutation.
3. Use `sqlmap` when the challenge is plausibly SQLi-driven and the target is stable enough for automation.
4. Use `playwright` separately when the task needs a real browser or a JS-heavy flow.
5. If a full profile was installed, use the manual Burp/ZAP links from the installer summary for GUI-heavy workflows.
6. Prefer the MCP server operations first: `toolbox_info`, `toolbox_verify`, `toolbox_capabilities`, `web_discover`, `web_fuzz`, and `web_sqlmap_scan`.

## Tool Selection

- Use `ffuf` for fast fuzzing against paths, parameters, or virtual hosts.
- Use `gobuster` for straightforward wordlist-driven discovery.
- Use `dirb` when a challenge guide or prior workflow already assumes DIRB-style usage.
- Use `wfuzz` when request templating matters more than raw speed.
- Use `sqlmap` when the target and request shape are stable enough to automate.

## Resources

- `opencrow-web-mcp`: stdio MCP server for typed discovery, fuzzing, and sqlmap workflows.
- `scripts/verify_toolkit.py`: confirm that the mapped web discovery tools are installed.
- `references/tooling.md`: quick selection notes for web workflows.
