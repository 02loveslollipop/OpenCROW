---
name: opencrow-network-toolbox
description: Use the Anaconda `ctf` environment for packet- and protocol-level CTF tasks that need Python networking helpers. Use when Codex needs `scapy` for packet crafting, protocol decoding, PCAP inspection, or custom network challenge automation.
---

# OpenCROW Network Toolbox

Use this skill for network artifact work that fits Python better than a raw socket loop: packet crafting, PCAP parsing, ad hoc dissectors, and protocol emulation with `scapy`.

## Quick Start

Run inline Python in `ctf`:

```bash
python ~/.codex/skills/opencrow-network-toolbox/scripts/run_network_python.py --code 'from scapy.all import IP, TCP; print((IP(dst=\"127.0.0.1\")/TCP(dport=31337)).summary())'
```

Run a packet helper:

```bash
python ~/.codex/skills/opencrow-network-toolbox/scripts/run_network_python.py --file /absolute/path/to/packets.py
```

Verify the mapped stack:

```bash
python ~/.codex/skills/opencrow-network-toolbox/scripts/verify_toolkit.py
```

## Workflow

1. Use this toolbox when the target is packet or protocol logic, not a long-lived interactive TCP shell.
2. Use `scapy` to decode captures, generate packets, or prototype custom protocol interactions.
3. Use `netcat-async` or `ssh-async` separately when you need persistent line-oriented sessions rather than packet tooling.
4. Read [references/tooling.md](references/tooling.md) for quick guidance.

## Tool Selection

- Use `scapy` for packet crafting, sniffing, protocol parsing, PCAP analysis, and challenge-specific dissectors.
- Use plain Python socket code only when the task is simpler than full packet work.
- Use `netcat-async` when the service is an interactive TCP stream and session persistence matters more than packet structure.

## Resources

- `scripts/run_network_python.py`: execute inline code or a `.py` file inside the `ctf` environment.
- `scripts/verify_toolkit.py`: confirm that `scapy` is available.
- `references/tooling.md`: quick selection notes for network workflows.
