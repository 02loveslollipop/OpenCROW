# Agent integrations

OpenCROW uses native provider discovery and permissions. Local sessions retain provider approvals unless `opencrow-init --unsafe` explicitly maps to the provider's bypass or auto-approval switch. Constellation runtime hosts are a separate trusted full-auto surface.

## Codex

Skills use Codex discovery. Lifecycle MCP is registered in `config.toml`; native `hooks.json` maps session start, tool, compaction, and stop events.

## OpenCode

OpenCode 2.0.0+ uses global Agent Skills discovery, a native V2 plugin directory in plural `plugins`, and lifecycle MCP under `mcp.servers`. Worker MCP, Constellation and the initializer share a pinned SDK adapter for sessions, streaming, resume and interrupt. The default embedded host opens no HTTP listener; an existing authenticated service can also be connected. See the [OpenCode integration](../../integrations/opencode/README.md) for upgrade and runtime setup.

## Claude Code

Skills, `mcpServers`, and native command hooks in `settings.json` provide the integration. Exit status 2 blocks supported events.

## Antigravity

The provider name `antigravity` dispatches to `agy`. Skills use `.agents/skills`; lifecycle MCP uses Antigravity's `mcp_config.json`, with lifecycle hooks in its settings.

Run `opencrow integrations list` to see discovery results and `opencrow integrations repair` to reapply only OpenCROW-owned entries.
