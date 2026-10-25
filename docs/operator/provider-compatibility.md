# Provider compatibility matrix

| Provider | Command | Local permissions | Runtime event format | Native resume | Skill discovery |
| --- | --- | --- | --- | --- | --- |
| Codex | `codex` | Provider approvals; explicit bypass | SDK notifications | SDK session ID | Codex Agent Skills |
| OpenCode 2.0.0+ | Shared V2 SDK bridge | Native defaults; trusted workers approve once | Typed V2 events | Native SDK session ID | OpenCode Agent Skills |
| Claude Code | `claude` | Native permissions; explicit bypass | stream JSON | `--resume` | Claude Agent Skills |
| Antigravity | `agy` | Native permissions; explicit bypass | stream JSON | `--conversation` | `.agents/skills` |

The release compatibility source is `integrations/manifest.json`. Install and repair preflight reject a parseable version below its declared minimum before managed files change. Unknown or non-SemVer vendor output is permitted with a prominent warning. `opencrow doctor` reports the detected and required versions.

Runtimes publish command availability, detected version, required minimum, and `compatible`, `incompatible`, or `unknown` status during registration. Constellation rejects incompatible providers during scheduling and execution, permits an available provider whose version is unknown with a warning, and never changes providers silently.

## Platform release matrix

OpenCode SDK/client/plugin packages are locked to 2.1.4 with Bun 1.4.4; the real SDK and native CLI gate tests that exact build. The SDK host verifies these pins and requires a V2 service version even when CLI discovery was unknown. It never silently falls back to CLI execution. See [runtime setup and test evidence](../../packages/opencode/README.md).

| Operating system | Architecture | Package managers | Status |
| --- | --- | --- | --- |
| Linux | `x86_64` | apt, dnf, yum, pacman | Supported |
| Linux | `aarch64` (ARM64) | apt, dnf, yum, pacman | Supported |

Native macOS, native Windows, Alpine/musl, 32-bit platforms, and other package managers are outside the v2 compatibility contract. Unsupported systems receive a compatibility report; the installer does not guess commands.
