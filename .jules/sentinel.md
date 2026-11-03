## 2024-05-15 - Prevent TypeError in secrets.compare_digest

**Vulnerability:** Passing non-string arguments (like `None` or integers) to `secrets.compare_digest` throws a `TypeError`, which can lead to Denial of Service (DoS) or mask authentication bypasses via unhandled exceptions in handlers or background tasks.

**Learning:** Python's `secrets.compare_digest` strictly requires string or bytes-like objects. Using dictionary `.get()` for tokens or parsing external JSON without explicitly type-checking the result before comparison causes a crash if the value is missing (`None`) or of the wrong type (e.g., int, dict).

**Prevention:** Always explicitly validate that both inputs are strings (e.g., `isinstance(a, str) and isinstance(b, str)`) before passing them to `secrets.compare_digest`. When negating this check, wrap the entire compound condition in parentheses: `not (isinstance(a, str) and isinstance(b, str) and secrets.compare_digest(a, b))` to avoid logic errors caused by `not` precedence.

## 2024-10-24 - Fix TypeError DoS vulnerability in compare_digest with non-ASCII chars
**Vulnerability:** `secrets.compare_digest` in Python raises a `TypeError` ("comparing strings with non-ASCII characters is not supported") if one of the strings contains non-ASCII characters. The `X-Constellation-UI-Auth` header and JSON inputs were not encoded before comparison.
**Learning:** Passing non-ASCII strings to `secrets.compare_digest` causes unhandled exceptions, potentially leading to Denial of Service or masking authentication bypasses if caught incorrectly. Using `isinstance(x, str)` is not enough as non-ASCII strings are still strings.
**Prevention:** Always encode strings to bytes (`x.encode("utf-8")`) before passing them to `secrets.compare_digest`.

## 2024-11-03 - Prevent AttributeError DoS when parsing nested JSON in WebSockets
**Vulnerability:** In `ConstellationWebSocket._emit_event`, using `(payload.get("sender") or {}).get("member_id")` assumes `sender` is either missing or a dictionary. If an attacker sends a string (or other non-dict type) for `sender`, `or {}` does not handle it, and `.get()` raises an `AttributeError`, crashing the WebSocket loop and causing a Denial of Service.
**Learning:** Using `or {}` only provides a fallback for `None` or empty values. It fails against type confusion attacks where JSON fields are populated with unexpected types.
**Prevention:** Always explicitly validate that nested objects are dictionaries (e.g., using `isinstance(sender, dict)`) before calling `.get()` on them.
