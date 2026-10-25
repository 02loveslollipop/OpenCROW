## 2024-05-15 - Prevent TypeError in secrets.compare_digest

**Vulnerability:** Passing non-string arguments (like `None` or integers) to `secrets.compare_digest` throws a `TypeError`, which can lead to Denial of Service (DoS) or mask authentication bypasses via unhandled exceptions in handlers or background tasks.

**Learning:** Python's `secrets.compare_digest` strictly requires string or bytes-like objects. Using dictionary `.get()` for tokens or parsing external JSON without explicitly type-checking the result before comparison causes a crash if the value is missing (`None`) or of the wrong type (e.g., int, dict).

**Prevention:** Always explicitly validate that both inputs are strings (e.g., `isinstance(a, str) and isinstance(b, str)`) before passing them to `secrets.compare_digest`. When negating this check, wrap the entire compound condition in parentheses: `not (isinstance(a, str) and isinstance(b, str) and secrets.compare_digest(a, b))` to avoid logic errors caused by `not` precedence.
