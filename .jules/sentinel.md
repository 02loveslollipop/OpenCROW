## 2024-05-24 - Cross-Site WebSocket Hijacking Prevention False Positive
**Vulnerability:** Tornado WebSocket handlers bypassing `check_origin` when an `Authorization: Bearer` header is present.
**Learning:** This is NOT a vulnerability in this specific architecture because standard browser APIs cannot set custom headers for WebSockets. The token is also validated immediately after in the `open()` method. This bypass is necessary for non-browser programmatic clients like local workers to connect.
**Prevention:** Add comments explaining that the origin bypass is safe when coupled with custom header requirements and token validation, preventing other developers from "fixing" it and breaking non-browser clients.
