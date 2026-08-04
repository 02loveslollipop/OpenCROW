# Test records

Deep test evidence must be reproducible without publishing private filesystem paths, credentials, challenge flags, or operational identifiers. The stable v2 baseline consists of:

- Lifecycle phase transitions, schema validation, append-only history, stale-document blockers, fail-open hook diagnostics, and search-policy tests in `packages/lifecycle/tests/`.
- Skills-only install, local verified bundles, config ownership/backups, upgrade, update, rollback, integration repair, and managed uninstall tests in `installer/tests/` and `scripts/test_installation_e2e.sh`.
- Provider scheduling, runtime protocol, session recovery, lifecycle artifacts, recon-to-solve continuation, and workspace isolation tests in `services/constellation/tests/`.
- Wiki generation, redirects, immutable metadata, link validation, sidebar order, CLI examples, compatibility manifests, and secret scanning in `tests/` and `scripts/validate_docs.py`.

Scheduled compatibility and stable release runs install real provider CLIs through their vendor-owned channels. The packaged skills archive is installed separately for Codex, OpenCode, Claude Code, and Antigravity; each isolated runtime verifies skill discovery, provider configuration, lifecycle hook context, the complete lifecycle MCP tool surface, Constellation runtime availability, doctor health, and managed uninstall. A separate disposable-container matrix performs actual full and skills-only installs on Ubuntu, Fedora, and Arch; release validation runs the same matrix before publication. Authenticated turns run only when protected CI secrets explicitly enable them; test output must never contain challenge secrets.

Wiki synchronization is tested against a local bare Git remote for deterministic reruns and injected pre-push failure. Provider recovery tests require a failed native resume to be written to lifecycle history and the replacement native session ID to be saved.

Release evidence is the test summary for the annotated tag plus the checksummed release manifest. Raw logs containing provider output are retained only through the repository's access-controlled CI retention policy.
