## 2023-10-22 - Prevent TypeError DoS during secret comparison

**Vulnerability:** Calling `secrets.compare_digest` with `None` as either argument raises a `TypeError`, which if unhandled can crash components or lead to Denial of Service (DoS) where auth flows abruptly fail with HTTP 500s or internal server errors, bypassing constant-time comparison benefits and failing ungracefully.

**Learning:** Python's `secrets.compare_digest` method lacks input type safety and strictly requires string or bytes equivalents. Supplying `None` from unresolved JSON attributes or unexpected request fields creates fragile auth handling. Using `and` conditions or explicit type validation prevents this.

**Prevention:** Ensure both variables are validated as non-`None` (and ideally strings/bytes) before calling `secrets.compare_digest(a, b)`. Always handle absence of expected configurations defensively. Use pattern like `if a is not None and b is not None and secrets.compare_digest(a, b):`.
