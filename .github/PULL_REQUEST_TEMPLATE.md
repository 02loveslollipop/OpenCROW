## 1. Issue Reference & Problem Description

Fixes #<!-- Issue number -->

<!-- Brief description of the problem, root cause, and what this PR accomplishes. -->

## 2. Implementation Summary

<!-- Detail the changes made across components. Keep changes minimal, provider-neutral, and isolated. -->

## 3. Test Design Rationale

<!--
Describe what was taken into account in the design of every newly added or modified test:
- Boundary conditions and invalid/unexpected inputs (nulls, empty collections, wrong types).
- Concurrency, race conditions, and locking (flock/fcntl, thread safety, atomic operations).
- Fail-closed security behavior (unauthorized access, malformed payloads, disallowed origins).
- Signal and process lifecycle handling (SIGINT/SIGTERM, terminal restoration, cleanup).
- Mock fidelity and test isolation.
-->

## 4. Test Environment Specification

- **OS / Distribution**: <!-- e.g., Ubuntu 24.04 / RHEL 9 -->
- **Architecture**: <!-- x86_64 / aarch64 -->
- **Python Version**: <!-- e.g., Python 3.12.3 -->
- **Key Dependencies**: <!-- e.g., Tornado 6.5.7, PyMongo 4.18.0, Flask 3.1.3 -->

## 5. Verification Checklist

- [ ] **Unit Tests**: Full unit test coverage added and passing.
- [ ] **Integration Tests**: Subsystem/cross-process integration verified.
- [ ] **Regression Guard**: Dedicated regression test added that reproduces prior failure.
- [ ] **Rebased on Main**: Branch is up to date with latest origin/main HEAD.
- [ ] **Full Suite**: `PYTHONPATH=installer:packages/lifecycle:packages/mcp/core:packages/mcp/servers:services/constellation:. pytest -q packages/lifecycle/tests packages/mcp/tests installer/tests services/constellation/tests tests`
- [ ] **Smoke Tests**: `bash -n ...`, `python3 -m py_compile ...`, and installer dry-run verified.
- [ ] **Doc Validation**: `python3 scripts/validate_docs.py` passed with 0 errors.
- [ ] **No Secrets**: No private keys, local tokens, or hardcoded personal credentials.
