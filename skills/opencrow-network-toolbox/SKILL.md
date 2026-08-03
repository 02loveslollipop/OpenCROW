---
name: opencrow-network-toolbox
description: Use the best available portable Python runtime and installed network tooling for packet- and protocol-level CTF tasks. Prefer a detected `ctf` environment. Use when an agent needs `scapy`, `tshark`, `tcpdump`, `nmap`, `nc`, or `socat` for packet work, capture analysis, or service triage.
---

# OpenCROW Network Toolbox

## Runtime preflight

Probe required commands with `command -v` and Python modules with `importlib.util.find_spec` before use. Prefer a PATH-resolved OpenCROW MCP helper or the `ctf`/`sage` environment when available, then the managed helper or system Python. If a capability is missing, stop that path safely and report the exact missing command or module.

Use this skill for network artifact work that spans both Python packet tooling and native capture or triage tools: `scapy`, `tshark`, `tcpdump`, `nmap`, `nc`, and `socat`.

## Quick Start

Start the MCP server from the installed CLI:

```bash
opencrow-network-mcp
```

Run inline Python in `ctf`:

```bash
python3 scripts/run_network_python.py --code 'from scapy.all import IP, TCP; print((IP(dst=\"127.0.0.1\")/TCP(dport=31337)).summary())'
```

Run a packet helper:

```bash
python3 scripts/run_network_python.py --file /absolute/path/to/packets.py
```

Verify the mapped stack:

```bash
python3 scripts/verify_toolkit.py
```

## Workflow

1. Start with the MCP server and call `toolbox_info`, `toolbox_verify`, and `toolbox_capabilities`.
2. Use `network_pcap_inspect` first when you already have a capture or need a quick filtered look at traffic.
3. Use `network_scan` to map reachable services before deeper protocol work.
4. Use `network_socket_probe` for one-shot TCP or UDP validation without opening a persistent async session.
5. Use `network_python` for Scapy-driven packet generation, decoding, or challenge-specific protocol logic.
6. Use `netcat-async` or `ssh-async` separately when you need a long-lived interactive session rather than packet tooling.
7. Read [references/tooling.md](references/tooling.md) for quick guidance.

## Tool Selection

- Use `scapy` for packet crafting, sniffing, protocol parsing, PCAP analysis, and challenge-specific dissectors.
- Use `opencrow-network-mcp` first for typed MCP access to capture inspection, scanning, probing, and Scapy execution.
- Use `tshark` for quick PCAP summaries, display filters, and protocol-aware decoding.
- Use `tcpdump` for capture creation and fast packet inspection from the shell.
- Use `nmap` for host, port, and service discovery before deeper protocol analysis.
- Use `nc` or `socat` for quick socket experiments, port relays, or test servers.
- Use plain Python socket code only when the task is simpler than full packet work.
- Use `netcat-async` when the service is an interactive TCP stream and session persistence matters more than packet structure.

## Resources

- `opencrow-network-mcp`: stdio MCP server for typed PCAP inspection, scanning, socket probing, and Scapy execution.
- `scripts/run_network_python.py`: execute inline code or a `.py` file inside the `ctf` environment.
- `scripts/verify_toolkit.py`: confirm that `scapy` is available.
- `references/tooling.md`: quick selection notes for network workflows.
