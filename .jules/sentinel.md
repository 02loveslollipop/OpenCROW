## 2024-10-16 - Prevent GridFS Internal Exceptions
**Vulnerability:** MongoDB GridFS layer's `open_download_stream` raises unhandled `bson.errors.InvalidId` and `gridfs.errors.NoFile` exceptions, exposing internal errors (HTTP 500) and potentially stack traces to clients via Tornado handlers.
**Learning:** These exceptions must be caught and translated to domain-appropriate exceptions like `KeyError` in the storage layer to prevent unhandled internal server errors and stack trace exposure in the web framework.
**Prevention:** When calling GridFS `open_download_stream`, always wrap the call in a try/except block, catch GridFS and BSON-specific errors, and raise domain-specific exceptions.
