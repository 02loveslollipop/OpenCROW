# Delegation examples

## Start and follow up

```json
{"task":"Implement the specified parser change and run its tests. Report files changed and test results.","provider":"codex","workspace":"/path/to/repo","workspace_mode":"auto"}
```

Pass provider-native model IDs explicitly when a specific model is needed. OpenCode model names use `provider/model`; effort maps to OpenCode `--variant`, Codex `model_reasoning_effort`, or Antigravity `--effort`. Omitting model uses the CLI's configured default. An explicit null on a follow-up clears the override. Reported model information is separate from requested settings.

```json
{"worker_id":"returned-worker-id","after":0,"wait_sec":15}
```

Send this to `worker_events`. Keep its returned cursor and answer a question using:

```json
{"worker_id":"returned-worker-id","question_id":"question-event-id","message":"Use the existing parser's error type and preserve its public signature."}
```

Send this to `worker_reply`. Do not issue a separate follow-up for the same answer. Repeating an identical reply is idempotent; a conflicting reply is rejected.

## Workspaces

`auto` in a Git repository creates `opencrow/worker/<id>` from `base_ref` or HEAD. It preserves the source subdirectory if that directory exists in the commit. Source edits and untracked files are not copied; `excluded_local_edits` reports their presence. Use `shared` to include them. Repositories without a commit require shared mode. Outside Git, auto is shared; explicit worktree mode fails clearly.

Distinct worktrees have distinct branches. To use the same checked-out branch and files, select shared mode and the same directory. The runner neither switches that branch nor serializes different workers in shared mode.

## Worker reports

Every turn receives a fully qualified local helper command in its prompt and worker identity in its environment. The helper accepts `progress`, `alert`, `checkpoint`, and `question`, followed by one quoted message. Use the provided command; no separate MCP registration or inbox polling is needed inside the worker.

Publish a checkpoint before asking a question, then finish the native turn. Include test commands/results and any outstanding instructions in checkpoints. Ordinary response text is never interpreted as a control message. A worker that ignores the question-and-yield instruction remains active until it exits, is stopped, or times out.

## Choosing a provider and moving work

Choose a CLI that is installed and authenticated, and a model supported by that account. Use task fit and measured outcomes to compare workers; model names alone do not establish speed, quality, or price. Usage fields contain provider-reported values and may be absent. The runner does not automatically retry or switch providers after a failure.

For a provider switch, finish or stop the current turn and call `worker_handoff` with the target provider and a checkpoint if one was not published in the current turn. Carry test evidence, decisions, file references, and remaining tasks in the checkpoint. The worktree is preserved; the new provider starts a fresh native conversation. The prior session ID remains in history for inspection.
