#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
BUNDLE=${1:-$ROOT_DIR/dist/opencrow-skills.zip}
PROVIDER_LIST=${2:-codex,opencode,claude,antigravity}
PYTHON_CMD=${OPENCROW_PYTHON:-$(command -v python3 || command -v python)}
[[ -f "$BUNDLE" ]] || { printf 'Provider runtime smoke bundle is missing: %s\n' "$BUNDLE" >&2; exit 2; }
[[ -n "$PYTHON_CMD" ]] || { printf 'Provider runtime smoke requires Python.\n' >&2; exit 2; }

TEST_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/opencrow-provider-runtimes.XXXXXX")
trap 'rm -rf "$TEST_ROOT"' EXIT
IFS=',' read -r -a providers <<< "$PROVIDER_LIST"

for provider in "${providers[@]}"; do
  case "$provider" in
    codex) provider_command=codex ;;
    opencode) provider_command=opencode ;;
    claude) provider_command=claude ;;
    antigravity) provider_command=agy ;;
    *) printf 'Unknown provider runtime: %s\n' "$provider" >&2; exit 2 ;;
  esac
  command -v "$provider_command" >/dev/null 2>&1 || {
    printf 'Provider runtime command is missing: %s (%s)\n' "$provider" "$provider_command" >&2
    exit 1
  }
  "$provider_command" --version

  runtime_root="$TEST_ROOT/$provider"
  runtime_home="$runtime_root/home"
  runtime_bin="$runtime_home/.local/bin"
  mkdir -p "$runtime_home"
  printf 'preserve provider-owned data\n' > "$runtime_home/provider-owned.txt"
  runtime_environment=(
    "OPENCROW_TARGET_HOME=$runtime_home"
    "OPENCROW_BIN_DIR=$runtime_bin"
    "OPENCROW_PYTHON=$PYTHON_CMD"
    "XDG_DATA_HOME=$runtime_root/data"
    "XDG_STATE_HOME=$runtime_root/state"
    "XDG_CONFIG_HOME=$runtime_root/config"
    "PATH=$runtime_bin:$PATH"
  )
  install_log="$runtime_root/install.log"
  if ! env "${runtime_environment[@]}" bash "$ROOT_DIR/installer/skills.sh" \
    --bundle "$BUNDLE" --agents "$provider" --yes >"$install_log" 2>&1; then
    cat "$install_log" >&2
    exit 1
  fi
  env "${runtime_environment[@]}" "$PYTHON_CMD" \
    "$ROOT_DIR/scripts/verify_provider_runtime_skills.py" \
    --provider "$provider" --runtime-root "$runtime_root" --repository "$ROOT_DIR"
  env "${runtime_environment[@]}" "$runtime_bin/opencrow" uninstall >"$runtime_root/uninstall.json"
  [[ ! -e "$runtime_root/state/opencrow/state.json" ]]
  [[ ! -e "$runtime_bin/opencrow" ]]
  [[ -f "$runtime_home/provider-owned.txt" ]]
  command -v "$provider_command" >/dev/null 2>&1
done

printf 'Packaged skills passed on %s trusted provider runtimes.\n' "${#providers[@]}"
