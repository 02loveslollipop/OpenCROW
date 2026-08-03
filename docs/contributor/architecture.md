# Architecture

OpenCROW v2 is separated by capability. `packages/lifecycle` is standard-library-only and authoritative for workspace state. `skills` is provider-neutral content. `integrations` maps native discovery and events into the shared contract. `installer` owns desired state and transactions. `packages/mcp` contains the shared protocol core and optional domain servers. `services/constellation` schedules provider adapters on trusted runtime hosts.

The lifecycle Markdown is human knowledge and remains append-only. `.opencrow/events.jsonl` is mechanical telemetry. Constellation persists provider/session/phase state but uses lifecycle files as recovery truth.

See schemas in `packages/lifecycle/schemas` and decisions in `docs/adr`.
