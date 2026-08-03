# Skills and MCP

The `skills/` tree is the only Agent Skills source. Every skill uses valid frontmatter, relative resources, and PATH-resolved commands. Skills probe commands and modules before use, prefer `ctf` or `sage`, then OpenCROW helper Python and system Python, and report exact missing capabilities.

Use lifecycle MCP first for durable knowledge. Full installations also expose selected domain MCP servers for crypto, pwn, reversing, network, web, forensics, stego, OSINT, and utility workflows. Persistent netcat, SSH, and Minecraft sessions use typed session operations and provider-neutral `/tmp/opencrow-*` state.

Interpreter resolution order is:

1. `OPENCROW_PYTHON` or the appropriate explicit override.
2. The suitable `ctf` or `sage` environment.
3. Managed helper Python.
4. Current/system Python.

Never assume domain modules or an MCP launcher exists in a skills-only installation; probe it.
