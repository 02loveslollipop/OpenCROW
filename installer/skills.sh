#!/usr/bin/env bash
set -euo pipefail

INSTALLER_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SOURCE_ROOT=$(CDPATH= cd -- "$INSTALLER_DIR/.." && pwd)
# shellcheck source=lib/selector.sh
source "$INSTALLER_DIR/lib/selector.sh"
ORIGINAL_ARGS=("$@")

select_or_control() {
  local status
  if select_many "$@"; then
    return 0
  else
    status=$?
  fi
  if ((status == 2)); then
    printf 'Back is not available on the first installer screen.\n' >&2
    exit 1
  fi
  exit "$status"
}

DRY_RUN=0
ASSUME_YES=0
AGENTS_ARG=
VERSION=latest
BUNDLE=

usage() {
  cat <<'EOF'
Usage: skills.sh [--agents codex,opencode,claude,antigravity] [--version VERSION]
                 [--bundle PATH] [--yes] [--dry-run]

Installs portable skills, provider hooks, lifecycle MCP, a lightweight helper,
and the opencrow management command. It never installs Conda, toolboxes,
provider CLIs, domain MCP servers, Constellation, or opencrow-init.
EOF
}

while (($#)); do
  case "$1" in
    --agents) AGENTS_ARG=${2:?missing value}; shift 2 ;;
    --version) VERSION=${2:?missing value}; shift 2 ;;
    --bundle) BUNDLE=${2:?missing value}; shift 2 ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) printf 'skills.sh: unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

MACHINE=${OPENCROW_TEST_MACHINE:-$(uname -m)}
if [[ $(uname -s) != Linux ]]; then
  printf 'OpenCROW skills compatibility report: unsupported OS %s (Linux is required).\n' "$(uname -s)" >&2
  exit 3
fi
case "$MACHINE" in
  x86_64|amd64) ARCH=x86_64 ;;
  aarch64|arm64) ARCH=aarch64 ;;
  *) printf 'OpenCROW skills compatibility report: unsupported architecture %s.\n' "$MACHINE" >&2; exit 3 ;;
esac

providers=(codex opencode claude antigravity)
commands=(codex opencode claude agy)
detected=()
for index in "${!providers[@]}"; do
  command -v "${commands[index]}" >/dev/null 2>&1 && detected+=("${providers[index]}")
done
defaults=$(join_by_comma "${detected[@]}")
if [[ -n "$AGENTS_ARG" ]]; then
  IFS=',' read -r -a selected_agents <<< "$AGENTS_ARG"
elif ((ASSUME_YES)); then
  selected_agents=("${detected[@]}")
else
  select_or_control "Portable agent integrations (detected CLIs are preselected)" "$defaults" "${providers[@]}"
  selected_agents=("${SELECTED_VALUES[@]}")
fi

if ((${#selected_agents[@]} == 0)); then
  printf 'skills.sh: no installed provider CLI was selected. Missing CLIs are intentionally not installed.\n' >&2
  exit 2
fi
for provider in "${selected_agents[@]}"; do
  case "$provider" in
    codex) required=codex ;;
    opencode) required=opencode ;;
    claude) required=claude ;;
    antigravity) required=agy ;;
    *) printf 'skills.sh: unknown provider %s\n' "$provider" >&2; exit 2 ;;
  esac
  if ! command -v "$required" >/dev/null 2>&1; then
    printf 'skills.sh: %s was selected but `%s` is missing; skills-only mode does not install agent CLIs.\n' "$provider" "$required" >&2
    exit 2
  fi
done

TARGET_HOME=${OPENCROW_TARGET_HOME:-$HOME}
DATA_HOME=${XDG_DATA_HOME:-$TARGET_HOME/.local/share}
HELPER_DIR=$DATA_HOME/opencrow/helper
PYTHON_CMD=${OPENCROW_PYTHON:-}

portable_python() {
  local asset release_root url checksums expected archive
  if [[ "$ARCH" == x86_64 ]]; then asset=opencrow-python-linux-x86_64.tar.gz; else asset=opencrow-python-linux-arm64.tar.gz; fi
  if [[ "$VERSION" == latest ]]; then
    release_root=https://github.com/02loveslollipop/OpenCROW/releases/latest/download
  else
    release_root=https://github.com/02loveslollipop/OpenCROW/releases/download/$VERSION
  fi
  url=${OPENCROW_PORTABLE_PYTHON_URL:-$release_root/$asset}
  checksums=${OPENCROW_PORTABLE_PYTHON_CHECKSUMS_URL:-$release_root/release-checksums.txt}
  command -v curl >/dev/null 2>&1 || { printf 'skills.sh: Python venv unavailable and curl is missing; portable Python is unresolved.\n' >&2; return 1; }
  archive=$(mktemp "${TMPDIR:-/tmp}/opencrow-python.XXXXXX.tar.gz")
  if ! curl -fsSL "$url" -o "$archive"; then
    rm -f "$archive"
    printf 'skills.sh: portable Python dependency is unresolved at %s.\n' "$url" >&2
    return 1
  fi
  if [[ -n "${OPENCROW_PORTABLE_PYTHON_SHA256:-}" ]]; then
    expected=$OPENCROW_PORTABLE_PYTHON_SHA256
  elif ! expected=$(curl -fsSL "$checksums" | awk -v name="$asset" '$2 == name || $2 == "*" name {print $1; exit}'); then
    rm -f "$archive"
    printf 'skills.sh: release checksums are unresolved at %s.\n' "$checksums" >&2
    return 1
  fi
  [[ "$expected" =~ ^[a-fA-F0-9]{64}$ ]] || { rm -f "$archive"; printf 'skills.sh: no verified checksum is available for %s.\n' "$asset" >&2; return 1; }
  if ! printf '%s  %s\n' "$expected" "$archive" | sha256sum -c - >/dev/null; then
    rm -f "$archive"
    printf 'skills.sh: portable Python checksum verification failed for %s.\n' "$asset" >&2
    return 1
  fi
  mkdir -p "$HELPER_DIR"
  if ! tar -xzf "$archive" -C "$HELPER_DIR" --strip-components=1; then
    rm -f "$archive"
    printf 'skills.sh: verified portable Python archive could not be extracted.\n' >&2
    return 1
  fi
  rm -f "$archive"
  [[ -x "$HELPER_DIR/bin/python3" ]] && PYTHON_CMD=$HELPER_DIR/bin/python3 || PYTHON_CMD=$HELPER_DIR/bin/python
}

if [[ -z "$PYTHON_CMD" ]]; then
  SYSTEM_PYTHON=$(command -v python3 || command -v python || true)
  if [[ -n "$SYSTEM_PYTHON" ]]; then
    if ((DRY_RUN)); then
      PYTHON_CMD=$SYSTEM_PYTHON
    elif "$SYSTEM_PYTHON" -m venv "$HELPER_DIR" >/dev/null 2>&1; then
      PYTHON_CMD=$HELPER_DIR/bin/python
    else
      portable_python
    fi
  elif ((DRY_RUN)); then
    PYTHON_CMD=python3
  else
    portable_python
  fi
fi

agents_csv=$(join_by_comma "${selected_agents[@]}")
printf 'OpenCROW skills-only plan\n  version: %s\n  agents: %s\n  helper: %s\n  source: %s\n' "$VERSION" "$agents_csv" "$PYTHON_CMD" "$SOURCE_ROOT"
if ((DRY_RUN)); then
  printf 'Dry run: no files or provider configs were changed.\n'
  exit 0
fi

source_args=(--source "$SOURCE_ROOT")
if [[ -n "$BUNDLE" ]]; then source_args=(--bundle "$BUNDLE"); fi
"$PYTHON_CMD" "$INSTALLER_DIR/opencrow_manager.py" internal-install "${source_args[@]}" --mode skills --agents "$agents_csv"
printf 'Skills-only installation complete. Add %s/.local/bin to PATH or start a new shell.\n' "$TARGET_HOME"
