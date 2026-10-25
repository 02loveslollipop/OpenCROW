# OpenCode V2 execution

Worker MCP, Constellation and the initializer import `opencrow_opencode.py`. Its long-lived Bun process uses one shared typed adapter for native sessions, prompts, model/agent switching, variants, events, forms, permissions and interruption. Prompt admission is followed by execution wait **and** the terminal event; only a successful outcome and lifecycle completion check produce a completed result. Native IDs remain distinct from logical worker IDs. Usage and cost are reported as per-turn deltas.

## Installation and verification

```bash
npm ci --prefix packages/opencode
bash scripts/test_opencode_v2.sh
python3 packages/opencode/opencrow_opencode.py health
python3 packages/opencode/opencrow_opencode.py close
```

The installer provisions locked production dependencies outside rotating payloads in `~/.local/share/opencrow/opencode-sdk/<lock-hash>`. Payloads link that directory; rollback retains the previous runtime. Receipts include the lock SHA-256 and SDK/Bun versions. Bundles omit dependencies and require npm access or `OPENCROW_OPENCODE_NODE_MODULES` pointing to an already provisioned matching dependency tree. Linux x86_64 and ARM64 use the corresponding npm native packages; live migration tests ran on Linux x86_64. CLI compatibility minimum is 2.0.0; SDK packages and test CLI are pinned to 2.1.4, Bun to 1.4.4. Initialization verifies package and service versions; errors never downgrade to CLI execution.

The test gate uses real pinned packages, a deterministic local provider and an isolated actual CLI service. It covers start/resume, workspace identity, parallel sessions, usage, failures, forms, permissions, cancellation, timeout, native plugin/skills/MCP discovery, lifecycle events and blocking completion. It also invokes real Python worker MCP, Constellation and initializer contracts. Paid provider credentials are unnecessary. The scheduled compatibility workflow optionally runs authenticated provider turns separately.

## Runtime modes

Default **embedded** mode calls `OpenCode.create()` with an in-memory router and no SDK HTTP listener. Set `OPENCROW_OPENCODE_MODE=embedded` explicitly if desired. Native model/provider configuration and credentials are resolved on the host. OpenCROW does not modify provider credentials.

To connect to an **already-running service**, set `OPENCROW_OPENCODE_URL=https://host:port` (or loopback HTTP) and `OPENCROW_OPENCODE_TOKEN` for Bearer auth, or `OPENCROW_OPENCODE_PASSWORD` with optional `OPENCROW_OPENCODE_USERNAME` (default `opencode`) for native Basic auth. Credentials must be outside the URL. Non-loopback connections require HTTPS and authentication. Alternatively `OPENCROW_OPENCODE_MODE=service` discovers an existing healthy native registered V2 endpoint and uses its authentication. Discovery never starts/replaces a service. Closing the bridge never stops an external service.

Connected services must install the OpenCROW V2 plugin directory and lifecycle helper on the service host. A lifecycle RPC preflight checks the connector before prompt admission; completion checks run there too. Workspace paths refer to that host. Worker artifact/reporting paths require a shared filesystem and matching helper commands. Configure tool environment explicitly with `OPENCROW_OPENCODE_REMOTE_ENV` as a JSON object of strings (for example `{"PATH":"/home/me/.local/bin:/usr/bin:/bin"}`). Local provider credentials are never forwarded to remote tools. Without this variable remote tools receive a minimal PATH. Per-turn worker reporting capabilities are forwarded only for the owning worker and cleared after completion. Embedded tools inherit host environment after bridge secrets and unrelated worker capabilities are removed. V2 session environment replaces its base environment, so the adapter builds the complete environment deliberately.

## Ownership and failure behavior

Python starts at most one owned bridge per SDK checkout, runtime mode, endpoint and credentials, under an exclusive startup lock. A mode-0700 state directory holds a mode-0600 Unix socket, host log and persistent session database. Long socket paths use a private owned directory under `/tmp`; the database stays in persistent state. Health checks precede admission; a hung existing bridge is reported rather than replaced. A dead host can be restarted for the next explicit request, and saved native sessions can be resumed explicitly. The daemon disposes the embedded host after 120 seconds idle or on `close`/SIGTERM/SIGINT. Use `OPENCROW_OPENCODE_IDLE_SEC` to adjust idle cleanup.

The bridge admits at most 16 turns, rejects simultaneous execution of a single native session, limits prompt bytes to 1 MiB, and bounds connection buffers to 4 MiB. Disconnect/backpressure cancels only that connection's owned execution. Worker stop and Constellation stop call native interrupt. Turn timeout is bounded to one day. Stream loss fails current work; reconnection happens before a later request, with **no automatic prompt replay**. Inspect the persisted native ID/checkpoint before resuming an uncertain execution. Logs contain diagnostics; service credentials are redacted from returned errors and removed from tool environments.

Trusted worker/Constellation full-auto replies `once` to native permission requests; explicit deny rules still apply. Safe initializer runs ask through the terminal. Native V2 questions are forms: worker events persist the pending form and `worker_reply` answers it without creating a new turn. A multi-field answer is a JSON object keyed by field name. Constellation prompt replies use the pending native form on the same active turn. Existing helper-reported questions retain their checkpoint/resume behavior.
