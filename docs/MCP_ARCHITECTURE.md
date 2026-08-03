# OpenCROW MCP Architecture

This document defines the contract for OpenCROW toolbox and I/O MCP servers.

## Principles

- One MCP server per toolbox or session-oriented I/O domain helper.
- Python stdio transport is the v2 baseline.
- Servers must be provider-neutral and consumable by Codex, Claude Code, Gemini, Copilot, and other MCP-capable clients.
- Toolbox servers must expose typed domain tools, not a generic shell-exec surface.
- Tool names, input shapes, and response envelopes must be stable across toolboxes.
- Each operation must surface the underlying command or execution summary when applicable.
- Missing dependencies, missing credentials, invalid inputs, and timeouts must return structured error envelopes instead of raw tracebacks.

## Common Surfaces

Every toolbox server must expose the same common tools:

- `toolbox_info`
- `toolbox_self_test`
- `toolbox_verify`
- `toolbox_capabilities`

These tools must keep the same semantics across all toolbox and I/O servers.

- `toolbox_self_test` is the lightweight readiness probe for boot-time MCP checks. It must not perform dependency discovery or environment scans.
- `toolbox_verify` is the heavier dependency report and should be reserved for explicit diagnostics after the server is already up.

Every server must also expose MCP resources:

- static metadata resources for server info, capabilities, and verification guidance
- at least one resource template for tool- or domain-specific lookups

The shared v2 defaults are:

- `opencrow://<server>/server`
- `opencrow://<server>/capabilities`
- `opencrow://<server>/verify-guide`
- `opencrow://<server>/tools/{name}`

Session-oriented I/O servers should add templates for live session state or artifacts when the domain has stable named sessions.

## Response Envelope

Every MCP tool call returns a single JSON object encoded as text content with the following keys:

- `ok`
- `summary`
- `toolbox`
- `operation`
- `inputs`
- `artifacts`
- `observations`
- `command`
- `stdout`
- `stderr`
- `exit_code`
- `next_steps`

The envelope is the canonical contract. The human-readable text in `summary` is only a compact view of the structured result.

Resource reads should return structured text or JSON content with stable URIs and MIME types. Resource payloads do not use the tool-call envelope.

## Input Shape

- Inputs must be explicit and typed.
- Paths, URLs, hostnames, queries, wordlists, plugins, and modes must be first-class arguments.
- Tool-specific escape hatches are allowed only as constrained typed fields, not raw shell strings.
- Long-running tools may accept an optional `execution` object with:
  - `cwd`
  - `timeout_sec`
  - `transcript_path`

## I/O Server Rules

- Session-oriented I/O servers should keep generic lifecycle verbs when the backend is protocol-agnostic:
  - `session_start`
  - `session_send`
  - `session_read`
  - `session_status`
  - `session_stop`
- Domain-specific interactive servers may expose typed verbs when the workflow is not a generic session shell. Minecraft is the current example, with explicit operations such as `minecraft_launch`, `minecraft_chat`, and `minecraft_screenshot`.
- Session state, managed logs, and generated captures must be surfaced through `artifacts`.
- Session servers must preserve reproducibility by reporting the managed backend command or execution summary in `command`.
- Long-lived reads should expose bounded snapshots by default and require an explicit follow/streaming mode when supported.
- Session-oriented servers should expose resource templates for stable session lookups, such as named status or artifact views.

## Execution Rules

- Servers probe required native commands and modules before use. Python selection is explicit override, appropriate `ctf` or `sage` environment, managed helper, then current/system Python.
- Tool wrappers must preserve reproducibility by reporting the executed command.
- Server behavior must be deterministic for the same inputs and environment.
- Stdout and stderr should be captured and returned in bounded form.

## Source ownership

Common protocol and execution code lives in `packages/mcp/core/`; typed domain servers live in `packages/mcp/servers/`. Provider integrations register PATH-resolved launchers and do not maintain provider-specific copies of MCP code.
