---
name: opencrow-utility-toolbox
description: Use the OpenCROW utility stack for shell-heavy CTF workflows. Use when an agent needs `jq`, `yq`, `xxd`, `tmux`, `screen`, `rg`, or `fzf` to glue a larger workflow together.
---

# OpenCROW Utility Toolbox

## Runtime preflight

Probe required commands with `command -v` and Python modules with `importlib.util.find_spec` before use. Prefer a PATH-resolved OpenCROW MCP helper or the `ctf`/`sage` environment when available, then the managed helper or system Python. If a capability is missing, stop that path safely and report the exact missing command or module.

Use this skill when the blocker is shell ergonomics or structured-data processing rather than a challenge-specific exploit primitive. It covers the “glue” layer that makes larger CTF workflows faster: `jq`, `yq`, `xxd`, `tmux`, `screen`, `ripgrep`, and `fzf`.

## Quick Start

Start the MCP server from the installed CLI:

```bash
opencrow-utility-mcp
```

Verify the mapped stack:

```bash
python3 scripts/verify_toolkit.py
```

## Workflow

1. Start with the MCP server and call `toolbox_info`, `toolbox_verify`, and `toolbox_capabilities`.
2. Use `utility_search` first when a workspace is large and you need to narrow the problem before opening files manually.
3. Use `utility_json_query` or `utility_yaml_query` when configs, API responses, or challenge metadata need slicing before deeper analysis.
4. Use `utility_hexdump` when you need a fast bounded hex view of a file region.
5. Use `tmux` or `screen` when the task benefits from persistent panes or background sessions.
6. Use the lifecycle MCP tools to record reproducible attempts, findings, and handoffs in the canonical documents.
7. Use `opencrow-init` only to initialize a new full-install workspace; skills-only installations intentionally omit it.

## Resources

- `opencrow-utility-mcp`: stdio MCP server for typed workspace search, jq/yq queries, and xxd hexdumps.
- `scripts/verify_toolkit.py`: confirm that the mapped workflow helpers are installed.
- `references/tooling.md`: quick guidance for common shell utility choices.
