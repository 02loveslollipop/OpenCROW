## 2024-05-18 - Prevent TypeError in secrets.compare_digest
**Vulnerability:** Unhandled TypeError when one of the arguments to `secrets.compare_digest` is not a string (e.g. `None`), potentially causing DoS or auth bypass.
**Learning:** `secrets.compare_digest` requires both arguments to be of the same type (bytes or strings). If a dict access like `get("token")` returns `None` and is passed directly, it raises a TypeError.
**Prevention:** Always validate that both inputs are strings (e.g., `isinstance(a, str) and isinstance(b, str)`) before passing them to `secrets.compare_digest`. Ensure proper parentheses when negating the check.
