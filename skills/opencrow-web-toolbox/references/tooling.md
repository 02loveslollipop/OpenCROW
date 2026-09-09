# OpenCROW Web Toolbox

Use this reference when the task is web discovery, fuzzing, or light exploitation and you need to choose the right installed CLI.

## Native tools

- `ffuf`: fast content, parameter, and vhost fuzzing.
- `gobuster`: directory, DNS, and virtual host brute forcing.
- `dirb`: classic web content brute forcer.
- `wfuzz`: more configurable request and parameter fuzzing.
- `sqlmap`: automated SQLi testing and exploitation.

## Burp MCP server (PortSwigger BApp)

- Requires Burp MCP extension enabled (`http://127.0.0.1:9876` SSE or packaged stdio proxy).
- OpenCode config: `mcp.burp = { type: "remote", url: "http://127.0.0.1:9876", oauth: false }`.
- Flow: proxy history (regex filter) -> Repeater -> Intruder -> Collaborator poll -> Organizer.
- Respect target approval system; Collaborator is Professional-only.

## Full-profile manual tools

- `OWASP ZAP`: web proxy and scanner, tracked by the installer as a manual full-profile step.
- `Burp Suite Community`: interception proxy for manual testing, tracked by the installer as a manual full-profile step.

## Practical selection

- Start with `ffuf` or `gobuster` for hidden content discovery.
- Use `wfuzz` when you need richer parameter mutation than simple wordlist substitution.
- Use `sqlmap` only after the vulnerable request shape is reasonably understood.
- Use `playwright` rather than this toolbox when the blocker is browser behavior, auth flows, or front-end rendering.
