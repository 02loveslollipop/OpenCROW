# Challenge lifecycle

Every active workspace uses exactly five uppercase lifecycle documents:

| Document | Ownership |
| --- | --- |
| `CHALLENGE.md` | Immutable Original Challenge plus append-only sourced clarifications |
| `FINDINGS.md` | Stable finding IDs with confirmed, refuted, or superseded history |
| `CHANGELOG.md` | Reproducible attempts with UTC time, input, outcome, evidence, status, and next action |
| `HANDOFF.md` | Reproducible reconnaissance and unsolved-solve checkpoints |
| `WRITEUP.md` | Verified solution plus later verification or revision history |

Any non-empty `CHALLENGE.md` activates hooks. `.opencrow/config.json` sets `enforcement` to `strict` (default), `warn`, or `off`. Mechanical hook events live separately in `.opencrow/events.jsonl`.

## Phases

- Without `HANDOFF.md`, the phase is reconnaissance. Completion needs current findings, attempts, and a reproducible handoff.
- With `HANDOFF.md` but no `WRITEUP.md`, the phase is solving. Solved turns require a writeup; unsolved turns need evidence, failures, artifacts, reproduction, and exact next actions.
- With `WRITEUP.md`, the phase is completed/verification. Later turns append verification or revisions without deleting history.

MCP tools are `workflow_status`, `workflow_read`, `workflow_record_attempt`, `workflow_record_finding`, `workflow_add_clarification`, `workflow_update_handoff`, and `workflow_writeup`.

Hooks never block user interruption, authentication failure, provider crashes, or rate limits. Hook faults fail open with a visible warning and `.opencrow/diagnostics.log` entry.
