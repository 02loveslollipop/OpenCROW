# Contributing to OpenCROW

Thank you for contributing to OpenCROW! To maintain the highest standards of security, cross-distro portability, and stability, all contributions must follow our mandatory contribution pipeline.

## Contribution Pipeline

Every change must progress sequentially through the five pipeline phases below:

### 1. Open Issue
Before writing or submitting code, open an issue on GitHub to establish alignment:
- **Problem Statement**: Clearly describe the bug, vulnerability, or feature request with reproducible steps.
- **Root Cause Analysis**: For bugs, identify the specific failure mode and underlying mechanism.
- **Proposed Architecture & Scope**: Outline the planned changes, affected subsystems, and provider impact. Keep changes small: one concern per issue/PR.
- **Risk Evaluation**: Document potential breaking changes, backward compatibility impacts, or security implications.

### 2. Implement
- **Minimal Atomic Diff**: Confine changes strictly to the agreed scope. No drive-by refactoring or unrelated formatting changes.
- **Subsystem Boundaries**:
  - Keep canonical Agent Skills (`skills/`) strictly provider-neutral.
  - Keep lifecycle helpers (`packages/lifecycle/`) standard-library-only.
  - Confine provider CLI adapters and configuration shapes to `integrations/`.
- **Clean Git State**: Rebase your branch onto the latest `origin/main` HEAD before submitting your pull request.

### 3. Full-Coverage Unit and Integration Testing
Every implementation must provide comprehensive test coverage for both internal logic and subsystem interactions:
- **Unit Testing**: Thoroughly cover internal functions, input validation, and expected failure branches.
- **Integration Testing**: Verify cross-module, filesystem, multi-process, and service boundaries (such as concurrency locking, WebSocket messaging, terminal PTY interactions, and installer flows).
- Strive for 100% test coverage of all newly added code paths.

### 4. Mandatory Regression Testing & Test Design Rationale
Every bugfix, security hardening, or robustness modification must include dedicated regression tests ensuring that the issue cannot recur:
- **Pre-Fix Failure**: The regression test must demonstrate failure on pre-fix code and clean passage on post-fix code.
- **Documented Test Design Considerations**: The PR description and test docstrings must explicitly describe what was taken into account in the design of every test, including:
  - **Boundary & Input Validation**: Empty values, null inputs, unexpected JSON types (e.g. non-dict payloads).
  - **Concurrency & Race Conditions**: Thread safety, multi-process re-entrant locks (`fcntl`), atomic database updates (`find_one_and_update`).
  - **Fail-Closed Security**: Unknown permissions, invalid origins, or unauthenticated tokens must default to rejection.
  - **Process & Signal Lifecycle**: Proper handling of interrupts (`SIGINT`, `SIGTERM`), terminal state restoration (`stty`), and cleanup of temporary directories and resources.
  - **Mock Fidelity**: Ensuring mock objects accurately model backend behavior without masking real-world defects.

### 5. Test Environment & Validation Evidence
The PR submission must document the exact verification environment and execution evidence:
- **Environment Specification**:
  - Operating System & Distribution (e.g., Ubuntu 24.04/26.04, RHEL 9, Arch Linux)
  - Hardware Architecture (`x86_64`, `aarch64`)
  - Python runtime version (`python3 --version`)
  - Key installed dependency versions (`tornado`, `pymongo`, `flask`, `websocket-client`)
- **Required Verification Commands**:
  - Full test suite:
    ```bash
    PYTHONPATH=installer:packages/lifecycle:packages/mcp/core:packages/mcp/servers:services/constellation:. pytest -q packages/lifecycle/tests packages/mcp/tests installer/tests services/constellation/tests tests
    ```
  - Smoke tests and script syntax verification:
    ```bash
    bash -n install.sh skills.sh installer/install.sh installer/skills.sh installer/lib/*.sh scripts/*.sh
    python3 -m py_compile installer/opencrow_manager.py installer/lib/*.py scripts/*.py packages/lifecycle/opencrow_lifecycle/*.py packages/mcp/core/*.py packages/mcp/servers/*.py skills/*/scripts/*.py services/constellation/constellation/*.py
    python3 scripts/validate_docs.py
    PYTHONPATH=packages/lifecycle python3 -m opencrow_lifecycle.init_cli codex --challenge-file README.md --dry-run
    bash installer/install.sh --agents codex --toolboxes utility --no-miniconda --yes --dry-run
    ```

## Documentation & Wiki Integrity

Repository Markdown files are authoritative. Public Wiki pages are generated exclusively from `docs/wiki-manifest.json` via `scripts/generate_wiki.py`. Never edit generated Wiki pages directly; submit pull requests for documentation changes instead. Run `python3 scripts/validate_docs.py` prior to opening a PR.

