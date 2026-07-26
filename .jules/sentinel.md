## 2025-02-14 - Fix timing attack vulnerability in token validation

**Vulnerability:** The `validate_system_token` method in `constellation/storage.py` used a simple `in` check (`token in self.settings.system_tokens`) to validate system tokens, which is susceptible to timing attacks.

**Learning:** Python's `in` operator (and `==` operator for strings) performs character-by-character comparison and returns early on the first mismatch. This allows an attacker to deduce the token length and content by measuring the time it takes for the server to reject incorrect tokens.

**Prevention:** Always use constant-time comparison functions like `secrets.compare_digest` when verifying security tokens, passwords, or hashes.
