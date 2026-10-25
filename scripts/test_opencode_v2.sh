#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
SDK_DIR=$ROOT_DIR/packages/opencode
TEST_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/oc-v2-smoke.XXXXXX")
trap 'rm -rf "$TEST_ROOT"' EXIT
command -v opencode >/dev/null
opencode --version | rg '(^|[[:space:]])v?2\.[0-9]'
[[ -x "$SDK_DIR/node_modules/.bin/bun" ]] || { printf 'Run npm ci --prefix packages/opencode before the SDK gate.\n' >&2; exit 1; }
"$SDK_DIR/node_modules/.bin/tsc" --noEmit -p "$SDK_DIR/tsconfig.json"
env HOME="$TEST_ROOT/home" XDG_DATA_HOME="$TEST_ROOT/data" XDG_CONFIG_HOME="$TEST_ROOT/config" \
  XDG_STATE_HOME="$TEST_ROOT/state" OPENCROW_TEST_PYTHON="${OPENCROW_PYTHON:-$(command -v python3)}" \
  "$SDK_DIR/node_modules/.bin/bun" test "$SDK_DIR/tests" --timeout 60000
