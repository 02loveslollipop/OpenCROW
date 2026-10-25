#!/usr/bin/env bash
set -euo pipefail

PROMPT='Reply with exactly OPENCROW_PROVIDER_OK.'
ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
timeout 90 codex exec --json "$PROMPT" >/tmp/opencrow-codex-smoke.jsonl
sdk_args=(turn --workspace "$ROOT_DIR" --timeout-sec 80)
if [[ -n "${OPENCROW_OPENCODE_SMOKE_MODEL:-}" ]]; then sdk_args+=(--model "$OPENCROW_OPENCODE_SMOKE_MODEL"); fi
printf '%s' "$PROMPT" | timeout 90 python3 "$ROOT_DIR/packages/opencode/opencrow_opencode.py" "${sdk_args[@]}" >/tmp/opencrow-opencode-smoke.jsonl
timeout 90 claude --print --output-format stream-json "$PROMPT" >/tmp/opencrow-claude-smoke.jsonl
timeout 90 agy --print --output-format stream-json "$PROMPT" >/tmp/opencrow-antigravity-smoke.jsonl
for path in /tmp/opencrow-{codex,opencode,claude,antigravity}-smoke.jsonl; do
  [[ -s "$path" ]] || { printf 'Provider smoke produced no events: %s\n' "$path" >&2; exit 1; }
done
