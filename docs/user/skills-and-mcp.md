# Skills and MCP

The `skills/` tree is the only Agent Skills source. Every skill uses valid frontmatter, relative resources, and PATH-resolved commands. Skills probe commands and modules before use, prefer `ctf` or `sage`, then OpenCROW helper Python and system Python, and report exact missing capabilities.

Use lifecycle MCP first for durable knowledge. Full installations also expose selected domain MCP servers for crypto, pwn, reversing, network, web, forensics, stego, OSINT, and utility workflows. Persistent netcat, reverse-shell listener, SSH, and Minecraft sessions use typed session operations and provider-neutral `/tmp/opencrow-*` state.

The `reverse-shell-async` skill manages one authorized inbound TCP session without generating callback payloads. Full installations should use `opencrow-netcat-mcp` and its `session_listen` operation; skills-only installations expose the listener-only `rsx` command. Loopback is the default, non-loopback binds require `--allow-remote`, and `--expected-peer` can restrict the accepted source IP or CIDR.

Interpreter resolution order is:

1. `OPENCROW_PYTHON` or the appropriate explicit override.
2. The suitable `ctf` or `sage` environment.
3. Managed helper Python.
4. Current/system Python.

Never assume domain modules or an MCP launcher exists in a skills-only installation; probe it.

## Standalone execution workers

Full installations include `opencrow-worker-mcp` and the [agent-worker skill](../../skills/agent-worker/SKILL.md). Add this launcher to the MCP configuration of the orchestrating client, just as for other domain servers. It supports Antigravity (`agy`), OpenCode (`opencode`), and Codex (`codex`) without requiring Constellation or the Codex SDK. The older `opencrow-agy-mcp` interface remains available.

Choose a provider and optional native model explicitly. The runner checks installed CLI flags, starts a detached turn, and returns a logical worker ID. `worker_status` and cursor-based `worker_events` expose execution outcomes, progress, questions, and artifacts. `worker_reply` answers questions durably, `worker_followup` resumes a native session, and `worker_handoff` starts a new provider session from a checkpoint in the same workspace.

Workers run with trusted full host access. In Git repositories the default is a new worktree and branch from the committed HEAD (or supplied `base_ref`); source uncommitted edits are excluded and reported. `workspace_mode: shared` explicitly permits using the same files and checked-out branch, including concurrent workers. Outside Git, the default uses the supplied directory. The runner does not automatically commit, merge, push, or delete results.

State lives under `${XDG_STATE_HOME:-~/.local/state}/opencrow/workers`, optionally overridden by `OPENCROW_WORKER_STATE_DIR`. This directory contains a SQLite inbox, event history, worktrees, and per-turn stdout, stderr, prompt, and review artifacts. Keep it on a local filesystem. Set the same state directory when reconnecting an MCP client. Turn timeout defaults to 300 seconds and is configurable from 1 to 86400 seconds.

MCP disconnection does not stop workers. `worker_stop` requests cancellation; wait until `active` is false before further execution or cleanup. A lost supervisor becomes `interrupted` rather than silently replaying the task. Native sessions and workspaces are retained. Questions require the worker to publish a checkpoint and end its turn; a reply received early starts continuation only after that turn exits. Inspect errors and artifacts when a CLI fails to yield or cannot resume.

Review and integrate results before removing retained worktrees with your normal Git workflow. Stop workers before uninstalling or replacing the runner's runtime files. Model access, authentication, and provider behavior depend on the installed CLI; preflight does not execute an authenticated model turn.
