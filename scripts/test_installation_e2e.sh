#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
TEST_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/opencrow-e2e.XXXXXX")
trap 'rm -rf "$TEST_ROOT"' EXIT

python3 "$ROOT_DIR/scripts/build_releases.py" --allow-development-placeholders
FULL_BUNDLE=$ROOT_DIR/dist/opencrow-full.zip
SKILLS_BUNDLE=$ROOT_DIR/dist/opencrow-skills.zip
[[ -f "$FULL_BUNDLE" && -f "$SKILLS_BUNDLE" ]]

mkdir -p "$TEST_ROOT/bin"
for provider in codex opencode claude agy; do
  printf '#!/bin/sh\necho "%s 99.0.0"\n' "$provider" >"$TEST_ROOT/bin/$provider"
  chmod +x "$TEST_ROOT/bin/$provider"
done
export PATH="$TEST_ROOT/bin:$PATH"
export OPENCROW_TARGET_HOME="$TEST_ROOT/home"
export OPENCROW_BIN_DIR="$TEST_ROOT/home/.local/bin"
export XDG_DATA_HOME="$TEST_ROOT/home/.local/share"
export XDG_STATE_HOME="$TEST_ROOT/home/.local/state"
export OPENCROW_PYTHON=$(command -v python3)
mkdir -p "$OPENCROW_TARGET_HOME"

bash "$ROOT_DIR/installer/skills.sh" --bundle "$SKILLS_BUNDLE" --yes >/dev/null
MANAGER=$OPENCROW_BIN_DIR/opencrow
"$MANAGER" doctor >"$TEST_ROOT/doctor.json"
grep -q '"ok": true' "$TEST_ROOT/doctor.json"
"$MANAGER" integrations list >/dev/null

python3 "$ROOT_DIR/installer/opencrow_manager.py" internal-install \
  --bundle "$FULL_BUNDLE" --mode full --agents codex,opencode,claude,antigravity \
  --toolboxes utility,network >/dev/null
grep -q '"install_mode": "full"' "$XDG_STATE_HOME/opencrow/state.json"
[[ -x "$OPENCROW_BIN_DIR/opencrow-init" ]]
"$MANAGER" update --bundle "$FULL_BUNDLE" >/dev/null
"$MANAGER" rollback >/dev/null
"$MANAGER" integrations repair >/dev/null
"$MANAGER" uninstall --purge-env >/dev/null
[[ ! -e "$XDG_STATE_HOME/opencrow/state.json" ]]
printf 'OpenCROW v2 isolated installation transaction passed.\n'
