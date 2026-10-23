## 2024-05-23 - Fix TypeError in secrets.compare_digest
**Vulnerability:** secrets.compare_digest throws a TypeError if either argument is not a string, potentially allowing DoS or bypassing authorization checks if unhandled.
**Learning:** When evaluating user-controlled input against a secret token, passing unexpected types (like None or integers) from JSON payloads or HTTP headers can crash the application instead of failing the comparison.
**Prevention:** Always explicitly validate that both arguments are strings using `isinstance(a, str) and isinstance(b, str)` before calling `secrets.compare_digest`.
