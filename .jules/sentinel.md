## 2024-05-18 - Hardcoded Secrets in Config
**Vulnerability:** Found hardcoded secrets (`opencrow-constellation-ui-dev-secret`) used as default values for `ui_secret_key` and `ui_shared_secret` in `constellation/config.py`.
**Learning:** Hardcoded default secrets create a severe risk where deployments may use well-known secrets for session encryption and backend authentication if operators forget to set environment variables.
**Prevention:** Default fallback secrets should be randomly generated at runtime using `secrets.token_hex(32)` (for session keys) or left blank (for optional shared secrets) to force explicit configuration or secure defaults.
