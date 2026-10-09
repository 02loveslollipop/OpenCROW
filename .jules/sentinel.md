## 2024-05-15 - [Security: Ensure secrets.compare_digest inputs are not None]
**Vulnerability:** Unhandled `TypeError` exceptions caused by passing `None` to `secrets.compare_digest` during token/secret validation.
**Learning:** `secrets.compare_digest` expects string/bytes inputs. If a client omits a token and the code passes `None` (e.g. from `dict.get()`), it crashes the handler/worker supervisor, potentially leading to DoS or masked auth failures.
**Prevention:** Always explicitly validate that *both* inputs are not `None` before comparison (e.g., `arg1 is not None and arg2 is not None and secrets.compare_digest(arg1, arg2)`).
