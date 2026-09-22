## 2024-03-24 - Fix Unhandled Exception Exposure

**Vulnerability:** Unhandled MongoDB exceptions (`bson.errors.InvalidId`, `gridfs.errors.NoFile`) in GridFS `open_download_stream` allowed HTTP 500 errors and potential stack trace exposure on file download endpoints.

**Learning:** When retrieving resources via GridFS using unsanitized or invalid ObjectIds, exceptions are thrown directly to Tornado handlers. Failing to translate driver-level exceptions to domain exceptions exposes internals.

**Prevention:** Ensure `open_download_stream` invocations are wrapped in `try-except` blocks translating `InvalidId` and `NoFile` into `KeyError`, matching standard key-lookup semantics for proper 404 HTTP errors in handlers.
