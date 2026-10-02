## 2024-05-24 - Unhandled TypeError in secrets.compare_digest
**Vulnerability:** secrets.compare_digest throws a TypeError if either argument is None, potentially leading to DoS or bypassing subsequent checks.
**Learning:** Python's secrets.compare_digest requires both arguments to be strings or bytes-like objects and fails ungracefully on None.
**Prevention:** Always validate that both arguments to secrets.compare_digest are not None before calling the function.
