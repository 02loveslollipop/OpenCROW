## 2024-10-19 - Null Pointer Dereference in Token Comparison

**Vulnerability:** Calls to `secrets.compare_digest(a, b)` fail with `TypeError` if `a` or `b` are `None`. If this happens in an unhandled authentication check block, it could mask an authentication failure (e.g. throwing a 500 instead of a 401/403) or cause a denial of service.

**Learning:** Python's `secrets.compare_digest` requires both arguments to be non-None (usually strings or bytes). Always explicitly check that variables being compared are not `None` before passing them to `compare_digest`. When negating this check, always wrap the compound condition in parentheses (e.g., `not (a is not None and b is not None and secrets.compare_digest(a, b))`) to avoid critical logical errors caused by Python's `not` vs `and` operator precedence.

**Prevention:** Ensure explicit `None` checks prior to `secrets.compare_digest` usage in all authentication and token verification flows.
