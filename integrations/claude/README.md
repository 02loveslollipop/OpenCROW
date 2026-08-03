# Claude Code integration

OpenCROW uses Claude Code Agent Skills, `mcpServers`, and native `SessionStart`, `PreToolUse`, `PostToolUse`, `PreCompact`, and `Stop` command hooks. Hook failures are visible but fail open; lifecycle blockers use exit status 2.
