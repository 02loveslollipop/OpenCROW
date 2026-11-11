## 2024-05-15 - Prevent TypeError in secrets.compare_digest

**Vulnerability:** Passing non-string arguments (like `None` or integers) to `secrets.compare_digest` throws a `TypeError`, which can lead to Denial of Service (DoS) or mask authentication bypasses via unhandled exceptions in handlers or background tasks.

**Learning:** Python's `secrets.compare_digest` strictly requires string or bytes-like objects. Using dictionary `.get()` for tokens or parsing external JSON without explicitly type-checking the result before comparison causes a crash if the value is missing (`None`) or of the wrong type (e.g., int, dict).

**Prevention:** Always explicitly validate that both inputs are strings (e.g., `isinstance(a, str) and isinstance(b, str)`) before passing them to `secrets.compare_digest`. When negating this check, wrap the entire compound condition in parentheses: `not (isinstance(a, str) and isinstance(b, str) and secrets.compare_digest(a, b))` to avoid logic errors caused by `not` precedence.

## 2024-10-24 - Fix TypeError DoS vulnerability in compare_digest with non-ASCII chars
**Vulnerability:** `secrets.compare_digest` in Python raises a `TypeError` ("comparing strings with non-ASCII characters is not supported") if one of the strings contains non-ASCII characters. The `X-Constellation-UI-Auth` header and JSON inputs were not encoded before comparison.
**Learning:** Passing non-ASCII strings to `secrets.compare_digest` causes unhandled exceptions, potentially leading to Denial of Service or masking authentication bypasses if caught incorrectly. Using `isinstance(x, str)` is not enough as non-ASCII strings are still strings.
**Prevention:** Always encode strings to bytes (`x.encode("utf-8")`) before passing them to `secrets.compare_digest`.
## 2024-11-20 - Prevent UnicodeDecodeError DoS in Tornado WebSockets
**Vulnerability:** In Tornado `WebSocketHandler`, the `on_message` method receives binary frames as `bytes` and text frames as `str`. Decoding binary frames via `json.loads(message)` without catching `UnicodeDecodeError` leads to unhandled exceptions when invalid bytes are sent.
**Learning:** Always explicitly catch `UnicodeDecodeError` alongside format errors like `json.JSONDecodeError` when manually decoding user-controlled byte inputs or binary frames in Tornado handlers to prevent 500 errors or dropped connections.
**Prevention:** Update the method signature to `def on_message(self, message: str | bytes) -> None:` and catch `(json.JSONDecodeError, UnicodeDecodeError)`.
