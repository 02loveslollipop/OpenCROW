# Release procedure

Development flows sequentially through `feature/* → dev → main → release`. Provider implementation branches are based on the updated `dev` after their predecessor merges.

For the v2 rollout, the required merge order is `feature/lifecycle-installer-v2`, `feature/agent-codex`, `feature/agent-opencode`, `feature/agent-claude-code`, then `feature/agent-antigravity`. Each branch starts from `dev` after the preceding branch has merged. Promotion from `main` to `release` is always explicit.

Only an annotated stable SemVer tag on the `release` branch may publish. Tags use `MAJOR.MINOR.PATCH[-PRERELEASE][+BUILD]`. Stable publication rejects prerelease identifiers; when build metadata is present, it must contain the source SHA (for example, `2.0.0+sha.0123456789ab`).

The release transaction validates tests/docs, builds checksummed assets and Wiki tree, installs the current Codex, OpenCode, Claude Code, and Antigravity CLIs through their vendor-owned channels, and installs the packaged skills bundle into an isolated trusted runtime for each provider. Every runtime must advertise a compatible provider, discover every skill, register lifecycle hooks and MCP, complete a reconnaissance workflow probe, pass `opencrow doctor`, and uninstall without touching provider-owned data before a draft GitHub Release is created. The transaction then replaces the generated Wiki from the tag using a dedicated credential, publishes the release, advances stable Cloudflare pointers, and verifies the public files byte-for-byte. Wiki failure leaves the release draft and stable pointers unchanged.
