# Constellation deployment and runtime trust

Constellation contains the backend/dashboard and a runtime service. Runtimes advertise provider names and versions; scheduling filters on the chosen challenge/agent provider and fails clearly when no runtime supports it.

```bash
cd services/constellation
docker compose up -d
opencrow-constellation-runtime
```

Runtime hosts execute every provider in full-auto mode. Treat them as dedicated trusted execution machines: isolate credentials and networks, restrict control tokens, monitor artifacts, and never attach a runtime to workloads beyond its authorization boundary.

The full installer provisions runtime dependencies, including the Codex SDK adapter, in its managed `ctf` environment. A standalone runtime deployment should install `services/constellation/requirements-runtime.txt` before launching the runtime command.

Challenge archives are extracted with traversal and link checks. Backend challenge data then generates authoritative `CHALLENGE.md`. Each agent has an independent workspace. Before a master turn, slave lifecycle artifacts are materialized read-only under `.opencrow/slaves/<agent-id>/`; the master alone produces canonical deliverables.

All existing lifecycle documents upload after each turn. A valid reconnaissance handoff queues exactly one solve continuation. A valid incomplete solving checkpoint waits for user/master direction. Lost provider sessions restart from lifecycle documents and persist the replacement native identifier.
