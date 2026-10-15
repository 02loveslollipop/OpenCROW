## 2024-10-15 - Token Validation bypass
**Vulnerability:** A timing attack and potential TypeErrors can be triggered if `secrets.compare_digest` is called with `None` as either of its arguments.
**Learning:** `secrets.compare_digest` requires both arguments to be string-like. If a token or a secret fetched from environment variables/configurations is `None`, calling `secrets.compare_digest(None, ...)` or `secrets.compare_digest(..., None)` raises a `TypeError`, which could lead to an unhandled exception (Denial of Service) or mask authentication bypasses depending on how the exception is handled.
**Prevention:** Always ensure that arguments passed to `secrets.compare_digest` are validated as not `None` before the comparison, or fallback to an empty string.
