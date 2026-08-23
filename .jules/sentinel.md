## YYYY-MM-DD - Information Disclosure in WebSockets
**Vulnerability:** Tornado WebSocket handlers were exposing raw exception messages via `str(exc)` on unexpected errors.
**Learning:** Returning `str(exc)` from a catch-all exception block on a public-facing WebSocket exposes internal stack traces, system structures, and potentially backend logic, acting as an information leak.
**Prevention:** Always log the full exception stack trace internally via `logging.error(..., exc_info=True)` and return a generic error payload (e.g. `{"error": "Internal server error"}`) to clients to avoid leaking sensitive information on unforeseen errors.
