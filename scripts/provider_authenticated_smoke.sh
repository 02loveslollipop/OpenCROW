#!/usr/bin/env bash
set -euo pipefail

PROMPT='Reply with exactly OPENCROW_PROVIDER_OK.'
timeout 90 codex exec --json "$PROMPT" >/tmp/opencrow-codex-smoke.jsonl
timeout 90 opencode run --format json "$PROMPT" >/tmp/opencrow-opencode-smoke.jsonl
timeout 90 claude --print --output-format stream-json "$PROMPT" >/tmp/opencrow-claude-smoke.jsonl
timeout 90 agy --print --output-format stream-json "$PROMPT" >/tmp/opencrow-antigravity-smoke.jsonl
for path in /tmp/opencrow-{codex,opencode,claude,antigravity}-smoke.jsonl; do
  [[ -s "$path" ]] || { printf 'Provider smoke produced no events: %s\n' "$path" >&2; exit 1; }
done
