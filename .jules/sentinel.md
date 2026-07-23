## 2025-07-23 - Timing Attack Vulnerability in Token Validation
**Vulnerability:** A timing attack vulnerability was found in the `validate_system_token` method where the `in` operator (which uses early-exit string comparison) was used to check if an input token matches any of the stored `system_tokens`.
**Learning:** Early-exit string comparisons leak timing information that can theoretically be used to guess the token one character at a time, especially over a network.
**Prevention:** Always use constant-time comparison functions like `secrets.compare_digest` for validating authentication tokens, passwords, or cryptographic secrets to prevent timing attacks.
