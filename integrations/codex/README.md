# Codex integration

OpenCROW uses Codex Agent Skills discovery, a PATH-resolved lifecycle MCP server in `config.toml`, and native `hooks.json` lifecycle events. Normal local invocations preserve Codex's configured approvals; only `opencrow-init --unsafe` selects the explicit bypass flag.

Constellation requires both the Codex CLI version declared in `integrations/manifest.json` and the `openai-codex` SDK. It starts SDK threads with deny-all approvals and danger-full-access sandboxing because runtime hosts are explicitly trusted, resumes by native thread ID, and restarts from lifecycle files if that ID is lost.
