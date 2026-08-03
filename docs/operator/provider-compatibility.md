# Provider compatibility matrix

| Provider | Command | Local permissions | Runtime event format | Native resume | Skill discovery |
| --- | --- | --- | --- | --- | --- |
| Codex | `codex` | Provider approvals; explicit bypass | SDK notifications | SDK session ID | Codex Agent Skills |
| OpenCode | `opencode` | Native defaults; explicit `--auto` | JSON events | `--session` | OpenCode Agent Skills |
| Claude Code | `claude` | Native permissions; explicit bypass | stream JSON | `--resume` | Claude Agent Skills |
| Antigravity | `agy` | Native permissions; explicit bypass | stream JSON | `--conversation` | `.agents/skills` |

The release compatibility source is `integrations/manifest.json`. Runtimes publish detected versions during registration. Version mismatch and missing commands are reported; Constellation never changes providers silently.

## Platform release matrix

| Operating system | Architecture | Package managers | Status |
| --- | --- | --- | --- |
| Linux | `x86_64` | apt, dnf, yum, pacman | Supported |
| Linux | `aarch64` (ARM64) | apt, dnf, yum, pacman | Supported |

Native macOS, native Windows, Alpine/musl, 32-bit platforms, and other package managers are outside the v2 compatibility contract. Unsupported systems receive a compatibility report; the installer does not guess commands.
