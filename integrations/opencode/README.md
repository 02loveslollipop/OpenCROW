# OpenCode integration

OpenCROW installs universal skills into OpenCode's native global skills directory. A local JavaScript plugin maps system-context, compaction, tool, and idle events into the shared lifecycle engine; the MCP entry is merged into `opencode.json`.

Runtime turns use `opencode run --format json --auto`, capture the native JSON session ID, and resume with `--session`. The installer selects the supported v1 or v2 MCP configuration shape from the detected CLI version and rejects versions below the release-manifest minimum.

## Interactive terminal

For a hands-on session, initialize the workspace and open the OpenCode TUI in it. Approvals stay native (interactive terminals never take `--unsafe`):

```bash
mkdir -p orbital-lock
cd orbital-lock
opencrow-init opencode --interactive --challenge-file ../orbital-lock.txt
```

The workspace lifecycle files (`CHALLENGE.md`, `FINDINGS.md`, `CHANGELOG.md`, `HANDOFF.md`) are created first, then `opencode` starts in the workspace with `OPENCROW_PROVIDER` and `OPENCROW_WORKSPACE` set, so the lifecycle plugin and MCP attach to the same session.
