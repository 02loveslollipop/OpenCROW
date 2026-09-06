---
name: agy-worker
description: Spawn, instruct, and supervise Google Antigravity (agy) as an execution worker. Use when an orchestrator or planner model needs a fast subagent to write code, edit files, run tests, explore directories, or execute shell tasks while retaining high-level strategic control.
---

# OpenCROW Runner - AGY Worker

For asynchronous supervision, durable questions/replies, worktrees, and additional providers, use [agent-worker](../agent-worker/SKILL.md) with `opencrow-worker-mcp`. The tools below retain their synchronous behavior.

## Runtime preflight

Probe required commands with `command -v` before use. The Antigravity CLI (`agy`) must be installed in PATH. If missing, report that `agy` is not installed on the host.

Use this skill when you are acting as the primary orchestrator, planner, or strategist, and need to delegate concrete execution subtasks to `agy` to preserve your attention and context window.

## MCP First

Prefer the `opencrow-agy-mcp` server tools for delegation:

- Call `toolbox_info`, `toolbox_verify`, and `toolbox_capabilities` first.
- Call `agy_execute` to dispatch a self-contained task or ticket to `agy`:
  - `task`: Clear, unambiguous prompt specifying goals, target files, and acceptance criteria.
  - `workspace`: Directory where `agy` should execute.
  - `conversation_id`: Pass an existing conversation ID to continue an ongoing thread, or leave empty for a fresh thread.
  - `mode`: Default is `accept-edits`.
- Call `agy_chat` when you need to provide corrective feedback, share test errors, or request follow-up refinements in the same conversation thread.
- Call `agy_session_status` to view active session turns and metadata.
- Call `agy_session_stop` to unregister finished sessions.

## Quick Start

Start the MCP server directly or via the OpenCROW launcher:

```bash
opencrow-agy-mcp
```

Or execute an inline task via CLI:

```bash
agy --dangerously-skip-permissions --output-format json --print="Create hello.py and run it"
```

## Workflow

1. **Strategic Planning**: Break the overall problem down into discrete, testable subtasks. Do not give `agy` underspecified, multi-objective epics.
2. **Dispatch Subtask**: Call `agy_execute` with target directory and explicit verification criteria (e.g., "Implement function `foo` in `bar.py` and ensure `pytest tests/test_bar.py` passes").
3. **Inspect Output**: Review the returned response, tool summary, and git status.
4. **Follow-Up or Correct**: If the worker encountered errors or missed an edge case, call `agy_chat` with the error output and corrective guidance.
5. **Finalize**: Unregister the session with `agy_session_stop` and integrate the completed work into your plan.

## Delegation Guidelines

- **Strategist (You)**: High-level architecture, plan maintenance, security decisions, hypothesis formation, evaluating final artifacts.
- **Worker (agy)**: Grepping code, reading multiple source files, editing and formatting code, running commands/builds, applying repetitive changes.

## References

- For delegation patterns and prompt templates, read `references/orchestration.md`.
