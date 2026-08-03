# Troubleshooting

Start with:

```bash
opencrow doctor
opencrow integrations list
```

- Missing skills: confirm the provider is selected, then run `opencrow integrations repair` and restart the provider.
- Lifecycle tool missing: confirm `opencrow-lifecycle-mcp` is on PATH and inspect the provider's same-named MCP entry.
- Stop is blocked: read the reported lifecycle blocker and record the missing evidence or checkpoint; do not delete prior history.
- No sudo: use `skills.sh`. The full installer intentionally cannot fall back to partial root mutation.
- Unsupported distro: use the compatibility report and a verified local bundle; do not substitute another package manager.
- Provider mismatch in Constellation: select a runtime that advertises that provider. Scheduling never falls back silently.
- Lost provider session: the runtime records the resume failure in `CHANGELOG.md`, restarts from lifecycle files, and stores the replacement native session ID.
