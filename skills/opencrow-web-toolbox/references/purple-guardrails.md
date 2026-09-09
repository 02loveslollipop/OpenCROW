# Purple Guardrails — Web Toolbox + Burp MCP

Checklist the agent must satisfy before and after every Burp MCP run.

## Before (gate)

- [ ] Approved scope stated: hosts, ports, paths.
- [ ] `burp_*` enabled only for this agent (`tools: { "burp_*": false }` globally).
- [ ] Burp MCP reachable (`opencode mcp debug burp` OK).

## During

- [ ] History filtered by regex within scope only.
- [ ] Repeater mutations tracked (request, change, observation).
- [ ] Intruder positions justified, payload budget stated.
- [ ] Collaborator: payload ID logged, poll executed before verdict.

## After (purple handoff)

Each finding requires:

1. Organizer entry reference.
2. Severity + impact (1-2 lines).
3. Remediation (concrete fix, not generic advice).
4. Reproduction (Repeater steps or Intruder config).

No remediation = incomplete finding, do not close.
