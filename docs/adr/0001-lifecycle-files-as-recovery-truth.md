# ADR 0001: Lifecycle files are recovery truth

Status: accepted.

OpenCROW uses five append-only Markdown documents as durable, provider-neutral knowledge. Provider session IDs are resumable accelerators, not the only source of state. When a native session is lost, Constellation records the failure and restarts from lifecycle files.

This avoids coupling recovery to one provider's private transcript format and keeps challenge evidence reviewable by humans.
