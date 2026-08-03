# Provider compatibility matrix

| Provider | Command | Local permissions | Runtime event format | Native resume | Skill discovery |
| --- | --- | --- | --- | --- | --- |
| Codex | `codex` | Provider approvals; explicit bypass | SDK notifications | SDK session ID | Codex Agent Skills |
| OpenCode | `opencode` | Native defaults; explicit `--auto` | JSON events | `--session` | OpenCode Agent Skills |
| Claude Code | `claude` | Native permissions; explicit bypass | stream JSON | `--resume` | Claude Agent Skills |
| Antigravity | `agy` | Native permissions; explicit bypass | stream JSON | `--conversation` | `.agents/skills` |

The release compatibility source is `integrations/manifest.json`. Install and repair preflight reject a parseable version below its declared minimum before managed files change. Unknown or non-SemVer vendor output is permitted with a prominent warning. `opencrow doctor` reports the detected and required versions.

Runtimes publish command availability, detected version, required minimum, and `compatible`, `incompatible`, or `unknown` status during registration. Constellation rejects incompatible providers during scheduling and execution, permits an available provider whose version is unknown with a warning, and never changes providers silently.

## Platform release matrix

| Operating system | Architecture | Package managers | Status |
| --- | --- | --- | --- |
| Linux | `x86_64` | apt, dnf, yum, pacman | Supported |
| Linux | `aarch64` (ARM64) | apt, dnf, yum, pacman | Supported |

Native macOS, native Windows, Alpine/musl, 32-bit platforms, and other package managers are outside the v2 compatibility contract. Unsupported systems receive a compatibility report; the installer does not guess commands.
