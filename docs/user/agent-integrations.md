# Agent integrations

OpenCROW uses native provider discovery and permissions. Local sessions retain provider approvals unless `opencrow-init --unsafe` explicitly maps to the provider's bypass or auto-approval switch. Constellation runtime hosts are a separate trusted full-auto surface.

## Codex

Skills use Codex discovery. Lifecycle MCP is registered in `config.toml`; native `hooks.json` maps session start, tool, compaction, and stop events.

## OpenCode

Skills use OpenCode's global Agent Skills directory. A local JavaScript plugin maps system-context, tool, compaction, and idle events; lifecycle MCP is merged into `opencode.json` according to the detected major version.

## Claude Code

Skills, `mcpServers`, and native command hooks in `settings.json` provide the integration. Exit status 2 blocks supported events.

## Antigravity

The provider name `antigravity` dispatches to `agy`. Skills use `.agents/skills`; lifecycle MCP uses Antigravity's `mcp_config.json`, with lifecycle hooks in its settings.

Run `opencrow integrations list` to see discovery results and `opencrow integrations repair` to reapply only OpenCROW-owned entries.
