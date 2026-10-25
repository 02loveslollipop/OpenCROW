# Standalone toolbox MCP servers

This directory can be vendored independently of the full OpenCROW installer. Its stdio servers and launcher use the Python standard library. Tool operations still need the corresponding native tools, Python packages, credentials or provider CLIs; missing dependencies are reported by `toolbox_verify`.

Use the `opencrow-mcp.zip` release asset, or vendor the `mcp-subtree/release` branch. Vendor `skills-subtree/release` alongside it when using the netcat, SSH or Minecraft servers. Pin the **commit IDs** from the same release manifest's `components.skills` and `components.mcp` entries; the branch names advance at stable release time.

For example, with `/opt/vendor/mcp` and `/opt/vendor/skills`:

```sh
python3 /opt/vendor/mcp/standalone.py config \
  --provider opencode --servers crypto osint netcat \
  --skills-root /opt/vendor/skills > /tmp/opencrow-mcp.fragment.json
```

Merge only the generated entries into your existing agent configuration. This command prints a fragment and does not modify agent files. `--provider codex` emits TOML; `claude` and `antigravity` emit `mcpServers` JSON. `opencode` emits the v1 `mcp` shape; use `opencode-v2` for clients expecting `mcp.servers`. Select only the servers you need to limit the tool surface.

The generated commands use absolute paths and configure `PYTHONPATH` automatically. At startup, runtime selection is `OPENCROW_PYTHON` → managed `ctf` Python → usable named Conda environment → managed/helper Python → current Python. An explicit invalid override is an error. No Conda installation or environment activation is required. Interpreter console scripts are exposed to server operations as well.

Run one server directly for protocol/debugging:

```sh
OPENCROW_SKILLS_ROOT=/opt/vendor/skills \
  python3 /opt/vendor/mcp/standalone.py serve netcat
```

The command serves MCP on stdin/stdout and waits for a client; it is not a shell prompt. Always initialize the protocol before calling tools.

| Servers | Additional runtime requirements |
| --- | --- |
| crypto, forensics, network, osint, pwn, reversing, stego, utility, web | Selected toolbox dependencies; no Constellation or lifecycle package |
| netcat, ssh, minecraft | Corresponding canonical skill scripts via `OPENCROW_SKILLS_ROOT`; SSH/Minecraft also need their external runtime dependencies |
| agy, worker | Installed and configured provider CLIs for execution; no Constellation, lifecycle package or Codex SDK |

Constellation backend, UI and runtime services and lifecycle hooks are separate full-stack components. They are not registered by this launcher. The standard skills-only installer keeps its existing lightweight defaults; toolbox registration is opt-in.
