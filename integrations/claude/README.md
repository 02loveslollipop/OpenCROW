# Claude Code integration

OpenCROW uses Claude Code Agent Skills, `mcpServers`, and native `SessionStart`, `PreToolUse`, `PostToolUse`, `PreCompact`, and `Stop` command hooks. Hook failures are visible but fail open; lifecycle blockers use exit status 2.

Constellation consumes stream-JSON, saves Claude's native session ID, and resumes with `--resume` on trusted full-auto runtime hosts. OpenCROW records native-install ownership around the [official Claude Code installation](https://code.claude.com/docs/en/setup) and limits explicit CLI purge to receipt-owned `.local/bin` and `.local/share/claude` assets; `.claude` configuration and history are never removed.
