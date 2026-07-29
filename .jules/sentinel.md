## 2024-07-29 - Prevent Timing Attacks in Token and Secret Verification

**Vulnerability:** The codebase previously used the `in` operator to verify system tokens against a tuple of valid tokens, and the `!=` operator to check resume secret digests. These basic comparison operators exit as soon as a mismatch occurs, which leads to execution times that leak information about how much of the guessed secret was correct, enabling timing attacks.

**Learning:** The Python standard library `secrets.compare_digest` must be used when validating sensitive credentials to ensure comparison happens in constant time. However, when adapting standard equality to `compare_digest`, input validation is essential. Because `compare_digest(None, ...)` throws a `TypeError`, we must perform a boolean check (`if not token:`) before doing the digest check to ensure the server doesn't crash on null/empty inputs. When substituting an `in` list-containment check, it must be rewritten as `any(secrets.compare_digest(token, valid_token) for valid_token in valid_tokens)`.

**Prevention:** All token, password, digest, and API key verification must use `secrets.compare_digest` in this repository, taking care to ensure `None` or empty strings are validated before being passed to the function.
