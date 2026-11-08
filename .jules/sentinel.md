## 2024-05-15 - Prevent TypeError in secrets.compare_digest

**Vulnerability:** Passing non-string arguments (like `None` or integers) to `secrets.compare_digest` throws a `TypeError`, which can lead to Denial of Service (DoS) or mask authentication bypasses via unhandled exceptions in handlers or background tasks.

**Learning:** Python's `secrets.compare_digest` strictly requires string or bytes-like objects. Using dictionary `.get()` for tokens or parsing external JSON without explicitly type-checking the result before comparison causes a crash if the value is missing (`None`) or of the wrong type (e.g., int, dict).

**Prevention:** Always explicitly validate that both inputs are strings (e.g., `isinstance(a, str) and isinstance(b, str)`) before passing them to `secrets.compare_digest`. When negating this check, wrap the entire compound condition in parentheses: `not (isinstance(a, str) and isinstance(b, str) and secrets.compare_digest(a, b))` to avoid logic errors caused by `not` precedence.

## 2024-10-24 - Fix TypeError DoS vulnerability in compare_digest with non-ASCII chars
**Vulnerability:** `secrets.compare_digest` in Python raises a `TypeError` ("comparing strings with non-ASCII characters is not supported") if one of the strings contains non-ASCII characters. The `X-Constellation-UI-Auth` header and JSON inputs were not encoded before comparison.
**Learning:** Passing non-ASCII strings to `secrets.compare_digest` causes unhandled exceptions, potentially leading to Denial of Service or masking authentication bypasses if caught incorrectly. Using `isinstance(x, str)` is not enough as non-ASCII strings are still strings.
**Prevention:** Always encode strings to bytes (`x.encode("utf-8")`) before passing them to `secrets.compare_digest`.
## 2025-01-28 - Prevent Unhandled UnicodeDecodeError DoS in WebSocket handlers and MCP Core

**Vulnerability:** When processing external stream inputs or decoding raw bytes in MCP servers or Tornado WebSocket handlers, an unhandled `UnicodeDecodeError` can crash the server thread or the websocket loop, leading to Denial of Service (DoS).

**Learning:** Python's `.decode("utf-8")` throws a `UnicodeDecodeError` when processing invalid byte sequences. In `tornado.websocket.WebSocketHandler`, when receiving binary messages over `on_message(self, message: str | bytes)`, failing to manually decode bytes into strings within a `try...except UnicodeDecodeError` block results in unhandled exceptions that cause 500 Internal Server Errors and kill the websocket connection. In MCP servers reading streams, unhandled `UnicodeDecodeError` kills the background worker runner thread.

**Prevention:** Always wrap `.decode("utf-8")` in a `try...except UnicodeDecodeError` block. In Tornado WebSocket handlers, always accept `message: str | bytes`, explicitly decode bytes to strings, and return a structured JSON error instead of crashing if decoding fails.
