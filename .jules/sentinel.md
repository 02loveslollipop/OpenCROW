## 2025-02-12 - Prevent TypeError in secrets.compare_digest
**Vulnerability:** `secrets.compare_digest` throws `TypeError` when one of the arguments is `None` (for example when accessing tokens or secrets using `.get()`).
**Learning:** Comparing tokens securely with `compare_digest` requires explicit validation of both inputs to prevent unhandled TypeErrors which could lead to Denial of Service or internal server errors that mask auth bypasses.
**Prevention:** Always validate that both inputs are not `None` before calling `secrets.compare_digest`.
