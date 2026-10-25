# OpenCode integration

OpenCROW installs universal skills into OpenCode's native global skills directory. A local JavaScript plugin maps system-context, compaction, tool, and idle events into the shared lifecycle engine; the MCP entry is merged into `opencode.json`.

Runtime turns use `opencode run --format json --auto`, capture the native JSON session ID, and resume with `--session`. The installer selects the supported v1 or v2 MCP configuration shape from the detected CLI version and rejects versions below the release-manifest minimum.

For opt-in toolbox servers in a minimal deployment, use the [standalone config generator](../../packages/mcp/README.md). It generates only the selected server entries and supports both OpenCode configuration shapes without changing the default lifecycle fragment.
