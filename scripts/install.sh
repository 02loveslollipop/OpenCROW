#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_NAME="ctf"
DRY_RUN=0
CONDA_BIN=""
TARGET_USER=""
TARGET_HOME=""
TARGET_PATH=""
FORCE_INTERACTIVE=0
PROFILE=""
EXPLICIT_ENV=0
ALL_TOOLBOXES=0

PWNDBG_VERSION="2026.02.18"
PWNINIT_VERSION="3.3.1"
GHIDRA_VERSION="12.0.4"
GHIDRA_DATE="20260303"
GHIDRA_ZIP="ghidra_${GHIDRA_VERSION}_PUBLIC_${GHIDRA_DATE}.zip"
GHIDRA_URL="https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_${GHIDRA_VERSION}_build/${GHIDRA_ZIP}"

TOOLBOX_IDS=()
TOOL_IDS=()
SELECTION_FILE=""
INTERACTIVE_SESSION=0

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Options:
  --env NAME        Conda environment name to create/update (default: ctf)
  --toolbox ID      Select a toolbox. Repeatable.
  --tool ID         Select an individual tool. Repeatable.
  --profile MODE    Install profile for toolbox-based selection: headless or full
  --all-toolboxes   Select all OpenCROW toolboxes explicitly
  --interactive     Force the interactive installer flow
  --dry-run         Print commands without executing them
EOF
}

run() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf '[dry-run] %q' "$1"
    shift
    for arg in "$@"; do
      printf ' %q' "$arg"
    done
    printf '\n'
  else
    "$@"
  fi
}

run_shell() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf '[dry-run] %s\n' "$*"
  else
    bash -lc "$*"
  fi
}

run_as_target() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf '[dry-run] %q' "$1"
    shift
    for arg in "$@"; do
      printf ' %q' "$arg"
    done
    printf '\n'
    return 0
  fi

  if [[ "$(id -un)" != "$TARGET_USER" ]]; then
    sudo -u "$TARGET_USER" env HOME="$TARGET_HOME" PATH="$TARGET_PATH" "$@"
  else
    env HOME="$TARGET_HOME" PATH="$TARGET_PATH" "$@"
  fi
}

capture_as_target() {
  if [[ "$(id -un)" != "$TARGET_USER" ]]; then
    sudo -u "$TARGET_USER" env HOME="$TARGET_HOME" PATH="$TARGET_PATH" "$@"
  else
    env HOME="$TARGET_HOME" PATH="$TARGET_PATH" "$@"
  fi
}

run_shell_as_target() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf '[dry-run] %s\n' "$*"
    return 0
  fi

  if [[ "$(id -un)" != "$TARGET_USER" ]]; then
    sudo -u "$TARGET_USER" env HOME="$TARGET_HOME" PATH="$TARGET_PATH" bash -lc "$*"
  else
    env HOME="$TARGET_HOME" PATH="$TARGET_PATH" bash -lc "$*"
  fi
}

run_as_root() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf '[dry-run] %q' "$1"
    shift
    for arg in "$@"; do
      printf ' %q' "$arg"
    done
    printf '\n'
    return 0
  fi

  if [[ "$EUID" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

resolve_target_identity() {
  local passwd_home

  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    TARGET_USER="$SUDO_USER"
  else
    TARGET_USER="$(id -un)"
  fi

  passwd_home="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
  if [[ -n "$passwd_home" ]]; then
    TARGET_HOME="$passwd_home"
  else
    TARGET_HOME="$HOME"
  fi

  TARGET_PATH="$TARGET_HOME/.local/bin:$PATH"
}

cleanup() {
  [[ -n "$SELECTION_FILE" && -f "$SELECTION_FILE" ]] && rm -f "$SELECTION_FILE"
}

find_conda() {
  local candidate

  if [[ "$(id -un)" == "$TARGET_USER" ]] && command -v conda >/dev/null 2>&1; then
    CONDA_BIN="$(command -v conda)"
    return 0
  fi

  for candidate in \
    "$TARGET_HOME/miniconda3/bin/conda" \
    "$TARGET_HOME/anaconda3/bin/conda" \
    "/opt/miniconda3/bin/conda" \
    "/opt/anaconda3/bin/conda"
  do
    if [[ -x "$candidate" ]]; then
      CONDA_BIN="$candidate"
      return 0
    fi
  done

  return 1
}

print_conda_install_help() {
  cat >&2 <<'EOF'
Anaconda or Miniconda is required, but no conda installation was found.

Download links:
  Miniconda: https://docs.conda.io/en/latest/miniconda.html
  Anaconda:  https://www.anaconda.com/download

After installation, reopen your shell or add conda to PATH and rerun this script.
EOF
}

resolve_selection() {
  local cmd
  SELECTION_FILE="$(capture_as_target mktemp)"
  trap cleanup EXIT

  if [[ "$FORCE_INTERACTIVE" -eq 1 || ( ${#TOOLBOX_IDS[@]} -eq 0 && ${#TOOL_IDS[@]} -eq 0 && -z "$PROFILE" && -t 0 && -t 1 ) ]]; then
    if [[ ! -t 0 || ! -t 1 ]]; then
      echo "--interactive requires a TTY." >&2
      exit 2
    fi
    INTERACTIVE_SESSION=1
    capture_as_target env OPENCROW_HOME="$TARGET_HOME" python3 "$ROOT_DIR/scripts/tool_catalog.py" interactive-select --output "$SELECTION_FILE"
    return 0
  fi

  cmd=(python3 "$ROOT_DIR/scripts/tool_catalog.py" resolve-selection --output "$SELECTION_FILE" --mode noninteractive)

  if [[ ${#TOOL_IDS[@]} -gt 0 ]]; then
    for tool_id in "${TOOL_IDS[@]}"; do
      cmd+=(--tool "$tool_id")
    done
  else
    cmd+=(--profile "${PROFILE:-headless}")
    if [[ "$ALL_TOOLBOXES" -eq 0 ]]; then
      for toolbox_id in "${TOOLBOX_IDS[@]}"; do
        cmd+=(--toolbox "$toolbox_id")
      done
    fi
  fi

  capture_as_target env OPENCROW_HOME="$TARGET_HOME" "${cmd[@]}"
}

link_gem_executable() {
  local executable="$1"
  local ruby_version
  ruby_version="$(capture_as_target ruby -e 'print RbConfig::CONFIG[%q[ruby_version]]')"
  run_as_target ln -sfn "$TARGET_HOME/.local/share/gem/ruby/${ruby_version}/bin/${executable}" "$TARGET_HOME/.local/bin/${executable}"
}

install_gem_spec() {
  local spec="$1"
  local name="${spec%%:*}"
  local version="${spec#*:}"

  if [[ -n "$version" && "$version" != "$name" ]]; then
    run_as_target gem install --user-install "$name" -v "$version"
  else
    run_as_target gem install --user-install "$name"
  fi
  link_gem_executable "$name"
}

install_direct_handler() {
  local handler="$1"

  case "$handler" in
    pwninit)
      run_shell_as_target "curl -fsSL https://github.com/io12/pwninit/releases/download/${PWNINIT_VERSION}/pwninit -o '$TARGET_HOME/.local/bin/pwninit' && chmod +x '$TARGET_HOME/.local/bin/pwninit'"
      ;;
    ghidra)
      run_shell_as_target "cd '$TARGET_HOME/.local/opt' && curl -L -o '${GHIDRA_ZIP}' '${GHIDRA_URL}' && unzip -q -o '${GHIDRA_ZIP}' && ln -sfn '$TARGET_HOME/.local/opt/ghidra_${GHIDRA_VERSION}_PUBLIC' '$TARGET_HOME/.local/opt/ghidra'"
      run_as_target ln -sfn "$TARGET_HOME/.local/opt/ghidra/support/analyzeHeadless" "$TARGET_HOME/.local/bin/ghidra-headless"
      run_as_target ln -sfn "$TARGET_HOME/.local/opt/ghidra/ghidraRun" "$TARGET_HOME/.local/bin/ghidra"
      ;;
    pwndbg)
      run_shell_as_target "curl -qsL https://install.pwndbg.re | sh -s -- -u -v ${PWNDBG_VERSION} -t pwndbg-gdb"
      ;;
    *)
      echo "Unknown direct install handler: $handler" >&2
      exit 2
      ;;
  esac
}

maybe_confirm() {
  local reply
  if [[ "$INTERACTIVE_SESSION" -eq 1 && "$DRY_RUN" -eq 0 ]]; then
    read -r -p "Continue with this install plan? [y/N] " reply
    case "$reply" in
      y|Y|yes|YES)
        ;;
      *)
        echo "Install cancelled."
        exit 0
        ;;
    esac
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)
      ENV_NAME="$2"
      EXPLICIT_ENV=1
      shift 2
      ;;
    --toolbox)
      TOOLBOX_IDS+=("$2")
      shift 2
      ;;
    --tool)
      TOOL_IDS+=("$2")
      shift 2
      ;;
    --profile)
      PROFILE="$2"
      shift 2
      ;;
    --all-toolboxes)
      ALL_TOOLBOXES=1
      shift
      ;;
    --interactive)
      FORCE_INTERACTIVE=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -n "$PROFILE" && "$PROFILE" != "headless" && "$PROFILE" != "full" ]]; then
  echo "Unsupported profile: $PROFILE" >&2
  exit 2
fi

resolve_target_identity

if ! find_conda; then
  print_conda_install_help
  exit 1
fi

echo "Installing for user: $TARGET_USER"
echo "Using conda at: $CONDA_BIN"

resolve_selection
python3 "$ROOT_DIR/scripts/tool_catalog.py" print-summary --selection "$SELECTION_FILE"
maybe_confirm

eval "$(OPENCROW_HOME="$TARGET_HOME" python3 "$ROOT_DIR/scripts/tool_catalog.py" export-plan --selection "$SELECTION_FILE")"

run_as_target mkdir -p "$TARGET_HOME/.local/bin" "$TARGET_HOME/.local/opt"
run_as_target mkdir -p "$TARGET_HOME/.codex/skills"

if [[ " ${SELECTED_TOOL_IDS[*]} " == *" tshark "* ]]; then
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf "[dry-run] echo 'wireshark-common wireshark-common/install-setuid boolean false' | %s debconf-set-selections\n" "$( [[ "$EUID" -eq 0 ]] && printf '%s' '' || printf '%s' 'sudo' )"
  elif [[ "$EUID" -eq 0 ]]; then
    echo 'wireshark-common wireshark-common/install-setuid boolean false' | debconf-set-selections
  else
    echo 'wireshark-common wireshark-common/install-setuid boolean false' | sudo debconf-set-selections
  fi
fi

run_as_root apt-get update
run_as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y "${APT_PACKAGES[@]}"

if capture_as_target "$CONDA_BIN" env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  echo "Conda environment '$ENV_NAME' already exists."
else
  run_as_target "$CONDA_BIN" create -n "$ENV_NAME" python=3.12 pip -y
fi

if [[ ${#PIP_PACKAGES[@]} -gt 0 ]]; then
  run_as_target "$CONDA_BIN" run -n "$ENV_NAME" pip install "${PIP_PACKAGES[@]}"
fi

for spec in "${GEM_SPECS[@]}"; do
  install_gem_spec "$spec"
done

for handler in "${DIRECT_HANDLERS[@]}"; do
  install_direct_handler "$handler"
done

run_as_target env OPENCROW_HOME="$TARGET_HOME" bash "$ROOT_DIR/scripts/sync_skills.sh"

if [[ ${#MANUAL_TOOL_IDS[@]} -gt 0 ]]; then
  echo
  echo "Manual steps are still required for some full-profile tools."
  echo "See the summary above for their homepage and license links."
  printf 'Pending manual tools: %s\n' "${MANUAL_TOOL_IDS[*]}"
fi

if [[ "$DRY_RUN" -eq 0 ]]; then
  run_as_target env OPENCROW_HOME="$TARGET_HOME" python3 "$ROOT_DIR/scripts/tool_catalog.py" save-state --selection "$SELECTION_FILE" --env "$ENV_NAME" >/dev/null
else
  echo "Dry-run mode: install state was not written."
fi

echo
echo "Bootstrap complete."
echo "Verify with: bash '$ROOT_DIR/scripts/verify.sh' --env '$ENV_NAME'"
