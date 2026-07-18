## 2025-02-28 - [Timing Attack Vulnerability in Secret Comparison]
**Vulnerability:** A standard string equality operator `!=` was used in `constellation/storage.py` to compare cryptographic hash digests (`resume_secret_digest`).
**Learning:** Comparing sensitive secrets or their digests with standard equality operators is susceptible to timing attacks, as the comparison halts upon finding the first mismatching character. This allows attackers to potentially infer secrets by measuring response times.
**Prevention:** Always use constant-time comparison functions, like `secrets.compare_digest()` in Python, when validating cryptographic secrets or digests to mitigate timing attacks.
