# Reverse Shell Async Operations

## Listener lifecycle

`listen` returns after the background daemon reaches `listening` (or immediately reaches `connected`). The normal state sequence is:

```text
starting -> listening -> connected -> remote_closed
```

An explicit accept timeout produces `accept_timeout`. An explicit stop produces `stopped`. Bind, validation, or socket failures produce `error`; inspect `daemon.log` and `io.log` before restarting the same name.

Port `0` is useful for local automation. After `listen` returns, obtain the assigned port from `status.port`. The default accept wait is unlimited.

## Peer filtering

`--expected-peer` accepts one IP address or CIDR. A connection outside that network is closed and recorded as `[REJECT]`; the listener remains in `listening` until a matching peer arrives or the accept timeout expires.

Binding `0.0.0.0`, `::`, or any non-loopback address exposes the TCP port beyond the local host and therefore requires `--allow-remote`. This flag confirms exposure only; it does not replace host firewall policy or peer filtering.

## Byte transport

- `--data TEXT` encodes UTF-8. Add `--newline` only for line-oriented text.
- `--hex HEX` removes ASCII whitespace and decodes paired hexadecimal digits.
- `--base64 BASE64` uses strict base64 decoding.
- Each decoded send is limited to 1 MiB.

The event log escapes control and non-ASCII bytes, including `\x00`, `\x03`, and `\xff`, so reading it cannot emit terminal-control data. Use `rx.raw` when byte-for-byte evidence matters.

## Recovery

1. Run `rsx status --name NAME`.
2. If the state is `error`, inspect `daemon.log` and `io.log`.
3. If `running` is false, restart with the same name only after preserving any evidence you need; restart resets that session's logs and raw capture.
4. If `running` is true but the listener is no longer needed, run `rsx stop --name NAME`.

No reconnect, multi-client loop, callback payload generator, or automated PTY upgrade is provided.
