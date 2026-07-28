## 2024-07-28 - Security: Prevent timing attacks on system token validation
**Vulnerability:** The system token validation in `constellation/storage.py` used a non-constant time string matching (`in` operation on `self.settings.system_tokens`).
**Learning:** String comparisons like `in` and `==` short-circuit on the first mismatch, allowing an attacker to iteratively guess a valid token character by character based on varying response times.
**Prevention:** Always use `secrets.compare_digest` for validating tokens and secrets to ensure comparisons occur in constant time.
