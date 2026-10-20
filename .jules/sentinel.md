## 2024-10-20 - Missing None Checks Before secrets.compare_digest

**Vulnerability:** Several authorization functions (like system token validation and topic resume) passed potentially `None` values directly to `secrets.compare_digest()`. If a system token was unconfigured (resulting in `None` within `self.settings.system_tokens`) or if a secret digestion resulted in `None`, this would raise an unhandled `TypeError` (e.g., `unsupported operand type(s) for compare_digest: 'str' and 'NoneType'`), leading to application crashes and potential denial of service (DoS) on authentication boundaries.

**Learning:** Python's `secrets.compare_digest()` requires both operands to support the buffer protocol (e.g., both strings or both bytes). It does not gracefully handle `None`, and raises a `TypeError` instead of returning `False`. This differs from normal equality (`==`) which safely returns `False` when comparing disparate types like `str` and `NoneType`.

**Prevention:** Always explicitly check that both operands are `is not None` before calling `secrets.compare_digest()`. When using negate conditions, wrap the entire check in parentheses or negate the final result instead of using potentially confusing operator precedence.
