## 2024-07-30 - Fix Timing Attack Vulnerabilities in Token Validation

**Vulnerability:** Security tokens and secrets were being compared using simple equality operators (e.g., `in` and `!=`), leaving the application vulnerable to timing attacks.

**Learning:** Python's standard equality checks short-circuit on the first mismatched character. An attacker could measure the time taken to reject a token to sequentially guess the characters of a valid token. The vulnerability extended to both system token validation and member resume secret validation. Replacing standard comparison operators with constant-time alternatives requires verifying input types, as  expects string types and will throw an exception if given .

**Prevention:** Always use constant-time comparison functions like `secrets.compare_digest` for security-sensitive comparisons (passwords, tokens, HMACs, etc.). Ensure inputs are validated to avoid passing  values into constant-time functions.
## 2024-07-30 - Fix Timing Attack Vulnerabilities in Token Validation

**Vulnerability:** Security tokens and secrets were being compared using simple equality operators (e.g., `in` and `!=`), leaving the application vulnerable to timing attacks.

**Learning:** Python's standard equality checks short-circuit on the first mismatched character. An attacker could measure the time taken to reject a token to sequentially guess the characters of a valid token. The vulnerability extended to both system token validation and member resume secret validation. Replacing standard comparison operators with constant-time alternatives requires verifying input types, as `secrets.compare_digest` expects string types and will throw an exception if given `None`.

**Prevention:** Always use constant-time comparison functions like `secrets.compare_digest` for security-sensitive comparisons (passwords, tokens, HMACs, etc.). Ensure inputs are validated to avoid passing `None` values into constant-time functions.
