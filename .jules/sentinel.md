## 2024-05-15 - Prevent TypeError in secrets.compare_digest

**Vulnerability:** Passing non-string arguments (like `None` or integers) to `secrets.compare_digest` throws a `TypeError`, which can lead to Denial of Service (DoS) or mask authentication bypasses via unhandled exceptions in handlers or background tasks.

**Learning:** Python's `secrets.compare_digest` strictly requires string or bytes-like objects. Using dictionary `.get()` for tokens or parsing external JSON without explicitly type-checking the result before comparison causes a crash if the value is missing (`None`) or of the wrong type (e.g., int, dict).

**Prevention:** Always explicitly validate that both inputs are strings (e.g., `isinstance(a, str) and isinstance(b, str)`) before passing them to `secrets.compare_digest`. When negating this check, wrap the entire compound condition in parentheses: `not (isinstance(a, str) and isinstance(b, str) and secrets.compare_digest(a, b))` to avoid logic errors caused by `not` precedence.

## 2024-10-24 - Fix TypeError DoS vulnerability in compare_digest with non-ASCII chars
**Vulnerability:** `secrets.compare_digest` in Python raises a `TypeError` ("comparing strings with non-ASCII characters is not supported") if one of the strings contains non-ASCII characters. The `X-Constellation-UI-Auth` header and JSON inputs were not encoded before comparison.
**Learning:** Passing non-ASCII strings to `secrets.compare_digest` causes unhandled exceptions, potentially leading to Denial of Service or masking authentication bypasses if caught incorrectly. Using `isinstance(x, str)` is not enough as non-ASCII strings are still strings.
**Prevention:** Always encode strings to bytes (`x.encode("utf-8")`) before passing them to `secrets.compare_digest`.

## 2024-11-01 - Fix AttributeError DoS in dictionary access
**Vulnerability:** In Python backend services processing external JSON (like Tornado WebSocket handlers), using `(payload.get("key") or {}).get("nested")` allows incorrect types (like strings) to pass through the `or {}` check if they are truthy, which raises an `AttributeError` on the subsequent `.get()` call, creating a Denial of Service vector by killing the event loop.
**Learning:** `or {}` only protects against falsy values (like `None` or `{}`), but fails to validate the type. A maliciously crafted JSON with a truthy non-dictionary string will cause an unhandled exception.
**Prevention:** Always explicitly validate that nested parsed JSON objects are dictionaries using `isinstance(value, dict)` before attempting to access them via `.get()`.
