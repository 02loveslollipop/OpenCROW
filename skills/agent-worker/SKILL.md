---
name: agent-worker
description: Delegate implementation tasks to local Antigravity, OpenCode, or Codex workers and supervise them through durable status, questions, replies, and checkpoint handoff.
---

# OpenCROW Runner - Agent Worker

Use `opencrow-worker-mcp` to delegate a concrete task to an explicitly selected provider. The standalone runner requires a full OpenCROW installation and the chosen authenticated CLI; it does not require Constellation or an SDK. Inspect `toolbox_verify` when checking provider availability. Model availability and credentials are verified only when a turn runs.

## Delegate and supervise

- Call `worker_start` with `task`, `provider` (`antigravity`, `opencode`, or `codex`), and `workspace`. Include acceptance criteria and an optional provider-native `model` and `effort`. Workers execute with trusted full host access; delegation preserves the scope of the user's task.
- Start returns a logical `worker_id` before the task completes. Its successful MCP envelope means the request was recorded, not that the task passed. Inspect the worker's `state` and results.
- Default `workspace_mode: auto` creates a unique Git worktree and branch from HEAD, excluding uncommitted source edits. Outside Git, it uses the supplied directory. Use `shared` explicitly to operate on the same files and checked-out branch, including local edits. Concurrent shared workers can overwrite each other; assign distinct responsibilities.
- Read `worker_events` with the last returned `next_cursor`. Use optional `wait_sec` up to 30 seconds to wait for updates, or omit `worker_id` to monitor all workers. Use `worker_status` for current state and artifact paths.
- Answer a `question` event using `worker_reply` with its `question_id`. Replies are durable; an early reply waits for the current turn to finish. Workers ask cooperatively and end their turn; this is not native interactive steering.
- Use `worker_followup` after completion to refine work in the same native session. Select an explicit model override when needed. Pending questions use `worker_reply` instead.
- Review the retained worktree, diff, checkpoint, final response, and test evidence. Integrate and clean up through the normal repository workflow; the runner does not auto-commit, merge, push, or remove files.

## Stop or switch providers

`worker_stop` requests cancellation and retains all artifacts. Wait for `active: false` before resuming or handing off. Unexpected supervisor loss becomes `interrupted`; inspect evidence before retrying because edits may already exist.

`worker_handoff` takes the worker ID, target provider/model, and an optional explicit checkpoint. It requires an inactive turn and either a supplied or worker-published checkpoint from the current turn. It retains the workspace and logical worker ID but creates a new native session. Native conversation history is not portable; the checkpoint must capture decisions, changes, verification evidence, and remaining work.

See [examples and provider selection](references/orchestration.md) for request examples and the worker-side reporting contract. Existing `agy-worker` tools retain their synchronous interface.
