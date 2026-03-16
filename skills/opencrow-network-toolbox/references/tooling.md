# OpenCROW Network Toolbox

Use this reference when the problem is packet- or protocol-oriented and `scapy` is likely the lightest useful tool.

## Python in `ctf`

- `scapy`: packet crafting, packet decoding, PCAP parsing, protocol modeling, and lightweight sniff/send workflows.

## Practical selection

- Use `scapy` when you need visibility into headers, payload formats, or custom packet sequences.
- Use this toolbox for PCAP analysis or synthetic packet generation.
- Use `netcat-async` instead when the service is just a persistent line-based TCP interaction.
