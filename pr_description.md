## Summary
Patched the Tornado WebSocket handlers in Constellation to prevent stack traces and inner exception details from leaking to clients via JSON payloads, and fixed a missing type check that could trigger an unhandled `AttributeError` if a client submitted a non-dictionary JSON array.

## Severity
HIGH

## Affected Component
`services/constellation/constellation/backend.py` (`RuntimeControlWebSocket` and `ConstellationWebSocket`).

## Security Issue
1. **Information Leakage**: The catch-all `except Exception` blocks in the `on_message` and `_watch_events` handlers were stringifying the raw `exc` object and embedding it into the error payload (`{"event_type": "error", "error": str(exc)}`). This could expose database credentials, invalid query details, or absolute stack paths to a malicious client.
2. **Denial of Service/Stability**: After `json.loads`, there was no verification that `payload` was actually a dictionary. If an array `[]` or primitive type was provided, the immediate subsequent call to `payload.get("action", "")` would raise an `AttributeError`, causing the server loop to drop the connection ungracefully or log excessive unhandled errors.

## Impact
Malicious users could deliberately trigger backend exceptions (e.g. invalid message shapes or topic names) and read the leaked `str(exc)` context to map out internal systems or scrape credentials. They could also repeatedly send valid JSON arrays to drop backend connections through unhandled `AttributeError` exceptions.

## Resolution
1. Added `import logging` and switched to using `logging.error(..., exc_info=True)` for catch-all exceptions, ensuring administrators still see the traces while clients receive a generic `"Internal server error"` string.
2. Added an explicit `if not isinstance(payload, dict):` guard immediately after parsing to return an `"Invalid payload format"` payload gracefully.

## Verification
- Code review complete and changes verified manually via `git diff`.
- All `constellation` tests pass via `pytest services/constellation/tests/`.

## Scope
Limited to `constellation/backend.py` WebSocket handler stability and output sanitation.

## Duplicate Check
No pre-existing PRs detected that address this specific Tornado exception handling gap.
