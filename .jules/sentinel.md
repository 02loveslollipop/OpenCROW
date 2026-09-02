## 2025-02-14 - Fix exception disclosure and unhandled type errors on WebSocket handlers

**Vulnerability:** The Tornado WebSocket handlers (`RuntimeControlWebSocket` and `ConstellationWebSocket`) exposed internal exception details (`str(exc)`) directly to clients in a catch-all exception block. Additionally, when parsing incoming JSON messages, they failed to validate that the parsed payload was actually a dictionary before accessing `.get()`, allowing malformed types (like strings or lists) to trigger unhandled `AttributeError` exceptions and leak information via the catch-all.

**Learning:** Python's `json.loads()` can return non-dictionary types (strings, lists, booleans). Blindly assuming it is a dictionary and calling `.get()` can trigger internal server errors. Catch-all `except Exception` blocks in public-facing handlers shouldn't expose internal stack traces or details to users.

**Prevention:** Always validate the type of decoded JSON input before accessing its properties (e.g., `if not isinstance(payload, dict): ...`). When handling generic exceptions in WebSockets or APIs, log the exception locally (e.g., `logging.error(..., exc_info=True)`) and return a sanitized generic error message (like `"Internal server error"`) to the client.
