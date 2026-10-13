## 2024-05-23 - Handle Database Exceptions in File Download
**Vulnerability:** MongoDB's `open_download_stream` throws `bson.errors.InvalidId` and `gridfs.errors.NoFile` which bypassed normal exception handling and might bubble up as HTTP 500 errors or expose stack traces.
**Learning:** Storage layer operations that raise library-specific exceptions should always catch them and translate them into domain-appropriate exceptions like `KeyError` before they reach the web handler layer.
**Prevention:** Always wrap MongoDB lookup and download endpoints in try-except blocks for both InvalidId and NoFile.
