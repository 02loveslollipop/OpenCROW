## 2024-07-23 - Prevent Timing Attacks in Token Validation

**Vulnerability:** Token validation in `constellation/storage.py` used `token in self.settings.system_tokens`, which relies on string equality checking. This could allow an attacker to perform timing attacks to deduce valid tokens byte by byte.

**Learning:** When checking against a set or list of sensitive tokens, using the `in` operator relies on non-constant-time comparisons. Constant-time comparisons must be enforced across all secret validations, even when checking against multiple valid tokens.

**Prevention:** Always use `secrets.compare_digest` for validating tokens, secrets, or passwords. When matching against a list, use a generator expression like `any(secrets.compare_digest(token, system_token) for system_token in system_tokens)` to check all valid tokens safely.
