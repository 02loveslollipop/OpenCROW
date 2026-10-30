## 2024-05-15 - Prevent TypeError in secrets.compare_digest

**Vulnerability:** Passing non-string arguments (like `None` or integers) to `secrets.compare_digest` throws a `TypeError`, which can lead to Denial of Service (DoS) or mask authentication bypasses via unhandled exceptions in handlers or background tasks.

**Learning:** Python's `secrets.compare_digest` strictly requires string or bytes-like objects. Using dictionary `.get()` for tokens or parsing external JSON without explicitly type-checking the result before comparison causes a crash if the value is missing (`None`) or of the wrong type (e.g., int, dict).

**Prevention:** Always explicitly validate that both inputs are strings (e.g., `isinstance(a, str) and isinstance(b, str)`) before passing them to `secrets.compare_digest`. When negating this check, wrap the entire compound condition in parentheses: `not (isinstance(a, str) and isinstance(b, str) and secrets.compare_digest(a, b))` to avoid logic errors caused by `not` precedence.

## 2024-10-24 - Fix TypeError DoS vulnerability in compare_digest with non-ASCII chars
**Vulnerability:** `secrets.compare_digest` in Python raises a `TypeError` ("comparing strings with non-ASCII characters is not supported") if one of the strings contains non-ASCII characters. The `X-Constellation-UI-Auth` header and JSON inputs were not encoded before comparison.
**Learning:** Passing non-ASCII strings to `secrets.compare_digest` causes unhandled exceptions, potentially leading to Denial of Service or masking authentication bypasses if caught incorrectly. Using `isinstance(x, str)` is not enough as non-ASCII strings are still strings.
**Prevention:** Always encode strings to bytes (`x.encode("utf-8")`) before passing them to `secrets.compare_digest`.
## 2024-10-24 - Prevent AttributeError DoS in WebSocket payload parsing

**Vulnerability:** Unvalidated JSON parsing in `ConstellationWebSocket._emit_event` assumed `payload.get("sender")` was a dictionary if truthy. If an attacker sends a message with `"sender": "string"`, `(payload.get("sender") or {}).get("member_id")` raises an `AttributeError`, causing an internal server error that drops the event and can potentially kill the websocket loop.

**Learning:** In Python backend services like Tornado WebSockets, parsing JSON payloads using `.get()` on nested objects without explicitly validating they are dictionaries (`isinstance(obj, dict)`) creates a DoS vector via `AttributeError`. The `or {}` fallback only handles `None` or empty values, not incorrect types.

**Prevention:** Ensure parsed JSON objects are explicitly validated as dictionaries (e.g., `sender_id = sender.get("member_id") if isinstance(sender, dict) else None`) before accessing methods like `.get()`.
