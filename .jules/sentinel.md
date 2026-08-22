## 2024-08-22 - Information Disclosure in WebSocket Handlers

**Vulnerability:** Tornado WebSocket handlers are catching broad exceptions (`except Exception`) and exposing the internal string representation of the exception (`str(exc)`) directly to the client in the WebSocket payload.

**Learning:** This can inadvertently leak sensitive internal details, such as stack traces, database schema information, or database credentials, if an unexpected error occurs during processing.

**Prevention:** Catch-all `except Exception` blocks in WebSocket handlers must log the exception internally using `logging.error(..., exc_info=True)` and return a generic error message (e.g., 'Internal server error') in the payload, rather than exposing `str(exc)`.
