## 2024-05-18 - Timing Attack Resiliency

**Vulnerability:** Simple string comparisons (`in`, `==`, `!=`) were used for sensitive token validation (e.g., system tokens, resume secrets) in the MongoDB storage layer (`constellation/storage.py`), which are susceptible to timing attacks.

**Learning:** Although standard library functions like `secrets.compare_digest` are well-known, they must be explicitly checked and applied during token verification since native Python operators like `in` and `!=` will short-circuit, potentially leaking token bytes by measuring execution time variations. The fix also required ensuring `None` values were properly guarded before checking via `compare_digest` to avoid `TypeError` exceptions.

**Prevention:** Future secret and token validation logic across the codebase must mandate the use of constant-time comparison methods, ensuring robust typing checks precede these functions to preserve operational stability.
