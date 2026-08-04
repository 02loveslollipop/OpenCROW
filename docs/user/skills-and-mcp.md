# Skills and MCP

The `skills/` tree is the only Agent Skills source. Every skill uses valid frontmatter, relative resources, and PATH-resolved commands. Skills probe commands and modules before use, prefer `ctf` or `sage`, then OpenCROW helper Python and system Python, and report exact missing capabilities.

Use lifecycle MCP first for durable knowledge. Full installations also expose selected domain MCP servers for crypto, pwn, reversing, network, web, forensics, stego, OSINT, and utility workflows. Persistent netcat, reverse-shell listener, SSH, and Minecraft sessions use typed session operations and provider-neutral `/tmp/opencrow-*` state.

The `reverse-shell-async` skill manages one authorized inbound TCP session without generating callback payloads. Full installations should use `opencrow-netcat-mcp` and its `session_listen` operation; skills-only installations expose the listener-only `rsx` command. Loopback is the default, non-loopback binds require `--allow-remote`, and `--expected-peer` can restrict the accepted source IP or CIDR.

Interpreter resolution order is:

1. `OPENCROW_PYTHON` or the appropriate explicit override.
2. The suitable `ctf` or `sage` environment.
3. Managed helper Python.
4. Current/system Python.

Never assume domain modules or an MCP launcher exists in a skills-only installation; probe it.
