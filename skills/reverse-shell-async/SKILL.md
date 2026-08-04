---
name: reverse-shell-async
description: Manage one authorized inbound reverse-shell TCP session asynchronously without generating a callback payload. Use for CTF challenges, isolated labs, or systems you own when an agent must listen safely, exchange text or exact bytes, inspect captured output, and stop the named listener without blocking its main workflow.
---

# OpenCROW I/O - Reverse Shell Async

Use this skill only for authorized CTF challenges, isolated labs, or systems you own. It manages the listener side of one inbound TCP session. It does not generate, suggest, or deploy reverse-shell payloads.

## Runtime preflight

Prefer the `opencrow-netcat-mcp` server in a full installation. Start with `toolbox_info`, `toolbox_verify`, and `toolbox_capabilities`, then use `session_listen`. In a skills-only installation, probe `rsx` with `command -v rsx`; if it is unavailable, use the relative `scripts/rsx` resource. Report the exact missing command if neither path exists.

## Safety defaults

- The listener binds to `127.0.0.1` unless `--bind-host` is supplied.
- A non-loopback bind is rejected unless `--allow-remote` is explicit.
- Use `--expected-peer IP_OR_CIDR` whenever the peer address is known. Mismatches are logged, closed, and do not consume the listener.
- A named listener accepts exactly one matching connection. It does not reconnect and does not serve multiple clients.
- Use a distinct session name for each authorized target flow, and stop live sessions when work is complete.

## MCP-first workflow

1. Call `session_listen` with a name and port. Port `0` requests an available local port; read the actual port from the returned status.
2. Poll `session_status` until its state is `connected`.
3. Use `session_send` with exactly one of `data`, `hex`, or `base64`.
4. Use `session_read` for the escaped event log. Treat the `rx.raw` artifact as the exact received bytes.
5. Call `session_stop` if the listener or connection is still running.

## CLI fallback

```bash
# Loopback listener on an automatically selected port
rsx listen --name lab --port 0

# Explicit authorized remote listener restricted to one source CIDR
rsx listen --name lab --bind-host 0.0.0.0 --port 4444 \
  --allow-remote --expected-peer 192.0.2.25/32

# Text and exact-byte input
rsx send --name lab --data 'id' --newline
rsx send --name lab --hex '03'
rsx send --name lab --base64 'AAEC/w=='

# Observe and stop
rsx status --name lab
rsx read --name lab --tail 40
rsx stop --name lab
```

`--newline` is valid only with text. Hex input may contain ASCII whitespace but must have valid, paired digits. Base64 input is strict. Decoded sends are limited to 1 MiB. The skill deliberately performs no automated PTY upgrade.

## State and artifacts

State is stored at `/tmp/opencrow-nc-async/<name>/` unless `OPENCROW_NC_ASYNC_DIR` is set. Important states are `starting`, `listening`, `connected`, `remote_closed`, `accept_timeout`, `stopped`, and `error`.

- `meta.json`: mode, state, bind, peer, and timestamps
- `io.log`: safely escaped state, TX, and RX events
- `rx.raw`: exact bytes received from the peer
- `daemon.log`: listener diagnostics
- `tx.fifo`: internal asynchronous send channel

## References

- Read `references/operations.md` for state transitions, error recovery, and raw-data rules.
