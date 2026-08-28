## 2025-02-27 - Information Disclosure via Tornado WebSocket Error Handling

**Vulnerability:** Unhandled exceptions and explicit error disclosures in Tornado WebSocket handlers returned raw exception tracebacks (`str(exc)`) directly to clients in error payloads. In addition, JSON payloads were parsed with `json.loads()` and immediately passed to `.get()`, causing `AttributeError` when primitive data types (like lists or strings) were sent.

**Learning:** Due to how Python's built-in `json.loads` handles primitive types instead of throwing `JSONDecodeError`, an attacker could intentionally send an invalid payload structure (like a list) to trigger an `AttributeError`. The `except Exception as exc:` block then leaked this runtime exception string back to the client. This highlights the need to validate type as `dict` explicitly before usage.

**Prevention:** Future implementations parsing WebSocket messages with `json.loads()` must enforce `isinstance(payload, dict)`. Broad `except Exception` blocks must be modified to log exceptions internally with `logging.error(..., exc_info=True)` and respond with a generic error message such as "Internal server error" rather than the raw `exc` string to avoid leaking stack traces or other sensitive details.
