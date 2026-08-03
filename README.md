# OpenCROW

Portable agent runtime, skills, and multi-provider challenge orchestration.

OpenCROW v2 is a breaking, provider-neutral release for Codex, OpenCode, Claude Code, and Antigravity (`agy`). It gives each challenge an append-only knowledge lifecycle, portable Agent Skills, typed MCP operations, transactional installation, and an optional trusted multi-agent Constellation runtime.

## Quick start

Install only portable skills, hooks, lifecycle MCP, helper Python, and the management command (no sudo):

```bash
curl -fsSL https://opencrow.02labs.me/skills.sh | bash
```

Install the complete framework on a supported Linux host:

```bash
curl -fsSL https://opencrow.02labs.me/install.sh | sudo bash
```

Initialize one local challenge phase after a full installation:

```bash
mkdir challenge && cd challenge
opencrow-init codex --challenge-file /path/to/description.txt
```

The five lifecycle documents are `CHALLENGE.md`, `FINDINGS.md`, `CHANGELOG.md`, `HANDOFF.md`, and `WRITEUP.md`. The Original Challenge is immutable; clarifications and all other knowledge are append-only.

## Repository layout

- `skills/` — one provider-neutral Agent Skills source tree.
- `packages/lifecycle/` — lifecycle engine, MCP, hooks, prompt, templates, and schemas.
- `packages/mcp/` — common MCP core and domain servers.
- `integrations/` — thin native provider adapters.
- `installer/` — selectors, state transactions, platform maps, and manifests.
- `services/constellation/` — dashboard, backend, provider adapters, and trusted runtime.
- `docs/` — authoritative user, operator, and contributor documentation.

## Development

```bash
make test
make smoke
make build-releases
```

See [Quick start](docs/user/quick-start.md), [installation](docs/user/installation.md), [challenge lifecycle](docs/user/challenge-lifecycle.md), and [Constellation operations](docs/operator/constellation.md).

The public GitHub Wiki is generated from a manifest-selected subset of repository documentation at stable releases. Direct Wiki edits are overwritten and are not supported.
