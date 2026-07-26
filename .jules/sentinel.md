## 2025-02-26 - [CRITICAL] Fix Timing Attack Vulnerability in System Token Validation
**Vulnerability:** System token validation used `in` operator which leaks timing information, allowing attackers to potentially guess system tokens.
**Learning:** Security context reminds to always use constant-time comparison methods (`secrets.compare_digest`) for verifying tokens or secrets, and properly check for None/empty inputs.
**Prevention:** Avoid simple string equality or `in` checks for secret validation. Ensure input is validated before comparison.
