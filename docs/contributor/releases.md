# Release procedure

Development flows sequentially through `feature/* → dev → main → release`. Provider implementation branches are based on the updated `dev` after their predecessor merges.

For the v2 rollout, the required merge order is `feature/lifecycle-installer-v2`, `feature/agent-codex`, `feature/agent-opencode`, `feature/agent-claude-code`, then `feature/agent-antigravity`. Each branch starts from `dev` after the preceding branch has merged. Promotion from `main` to `release` is always explicit.

Only an annotated stable SemVer tag on the `release` branch may publish. Tags use `MAJOR.MINOR.PATCH[-PRERELEASE][+BUILD]`. Stable publication rejects prerelease identifiers; when build metadata is present, it must contain the source SHA (for example, `2.0.0+sha.0123456789ab`).

The release transaction validates tests/docs, builds checksummed assets and the Wiki tree, and gates publication on the full installation suite described below. It then creates a draft GitHub Release, replaces the generated Wiki from the tag using a dedicated credential, publishes the release, advances stable Cloudflare pointers, and verifies the public files byte-for-byte. Wiki failure leaves the release draft and stable pointers unchanged.

## Release installation gate

`scripts/test_release_installation.sh` runs only in the annotated stable-tag transaction. Each Ubuntu 24.04, Fedora 42, and Arch container starts with a clean user home and real vendor-installed Codex, OpenCode, Claude Code, and Antigravity CLIs. Each distribution gets two separate scenarios:

- Fresh installation of the exact candidate full ZIP, with all nine default headless toolboxes and managed Miniconda/CTF Python environment.
- Full installation of the most recently published stable release, verification of that baseline, then `opencrow update --bundle` to the candidate and the same verification again. Drafts, prereleases, and the candidate tag are excluded from baseline selection. Missing baselines and invalid published checksums fail the gate.

Verification checks bundle integrity, installed payload hashes and version, selected providers/toolboxes, installed skills, `opencrow doctor`, core utility availability, Python installation receipts and `pip check`. It boots all four CLIs with version/help and native configuration-list commands, then initializes each installed MCP server and lists its tools. Upgrade checks also verify the previous snapshot and preservation of user data and a user configuration comment. No model prompts, authenticated turns, worker tasks, or toolbox operations run in this suite.

Full means the default headless installation: optional GUI tools and SageMath are excluded. Unavailable distro packages remain best-effort installer omissions recorded in the report; missing core utilities or unresolved Python dependencies fail. Vendor downloads require network access, but containers receive no host home, agent credentials, GitHub token, or Docker socket. Every scenario has a 45-minute deadline; CLI and MCP probes have 120-second deadlines. Failed scenarios block publication, and the remaining scenarios still run. Container output and per-phase startup logs/reports are retained for 14 days, including on failure. The matrix exercises the runner's native x86_64 architecture; it does not establish ARM64 runtime coverage.

The expensive suite is deliberately absent from PR and scheduled workflows. Normal CI tests its verification logic with deterministic fixtures; the existing scheduled skills/provider and lightweight distro checks remain separate. To reproduce the release gate on a disposable Docker-capable machine:

```sh
python scripts/release_installation.py fetch-previous "$CANDIDATE_TAG" /tmp/opencrow-previous
bash scripts/test_release_installation.sh dist/opencrow-full.zip /tmp/opencrow-previous/opencrow-full.zip /tmp/opencrow-release-reports
```
