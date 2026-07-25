## 2024-05-15 - Prevent Timing Attacks in Token Validation
**Vulnerability:** System token validation in `constellation/storage.py` used the `in` operator, which performs a short-circuiting string comparison.
**Learning:** This exposes a timing attack vulnerability where an attacker could deduce valid tokens by measuring response times. It's a common pattern to watch out for across this codebase when validating API keys or authentication tokens.
**Prevention:** Always use constant-time comparison methods like `secrets.compare_digest()` for secrets. Validate that the input is non-empty before checking to prevent `TypeError` with `None`.
