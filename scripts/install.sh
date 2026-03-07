#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_NAME="ctf"
DRY_RUN=0

PWNDBG_VERSION="2026.02.18"
PWNINIT_VERSION="3.3.1"
SECCOMP_TOOLS_VERSION="1.6.2"
GHIDRA_VERSION="12.0.4"
GHIDRA_DATE="20260303"
GHIDRA_ZIP="ghidra_${GHIDRA_VERSION}_PUBLIC_${GHIDRA_DATE}.zip"
GHIDRA_URL="https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_${GHIDRA_VERSION}_build/${GHIDRA_ZIP}"

APT_PACKAGES=(
  checksec
  curl
  gdb
  gdbserver
  git
  ltrace
  nasm
  openjdk-21-jre
  patchelf
  qemu-user
  qemu-user-static
  radare2
  ruby
  unzip
)

usage() {
  cat <<EOF
Usage: $(basename "$0") [--env NAME] [--dry-run]

Options:
  --env NAME   Conda environment name to create/update (default: ctf)
  --dry-run    Print commands without executing them
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

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)
      ENV_NAME="$2"
      shift 2
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

if ! command -v conda >/dev/null 2>&1; then
  echo "conda is required on PATH." >&2
  exit 1
fi

run mkdir -p "$HOME/.local/bin" "$HOME/.local/opt"
run mkdir -p "$HOME/.codex/skills"

run sudo apt-get update
run sudo apt-get install -y "${APT_PACKAGES[@]}"

if conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  echo "Conda environment '$ENV_NAME' already exists."
else
  run conda create -n "$ENV_NAME" python=3.12 pip -y
fi

run conda run -n "$ENV_NAME" pip install -r "$ROOT_DIR/requirements-ctf.txt"

run_shell "curl -fsSL https://github.com/io12/pwninit/releases/download/${PWNINIT_VERSION}/pwninit -o '$HOME/.local/bin/pwninit' && chmod +x '$HOME/.local/bin/pwninit'"

run gem install --user-install seccomp-tools -v "$SECCOMP_TOOLS_VERSION"
run_shell "rubyver=\$(ruby -e \"print RbConfig::CONFIG[%q[ruby_version]]\") && ln -sfn '$HOME/.local/share/gem/ruby/'\"\${rubyver}\"'/bin/seccomp-tools' '$HOME/.local/bin/seccomp-tools'"

run_shell "cd '$HOME/.local/opt' && curl -L -o '${GHIDRA_ZIP}' '${GHIDRA_URL}' && unzip -q -o '${GHIDRA_ZIP}' && ln -sfn '$HOME/.local/opt/ghidra_${GHIDRA_VERSION}_PUBLIC' '$HOME/.local/opt/ghidra'"
run ln -sfn "$HOME/.local/opt/ghidra/support/analyzeHeadless" "$HOME/.local/bin/ghidra-headless"
run ln -sfn "$HOME/.local/opt/ghidra/ghidraRun" "$HOME/.local/bin/ghidra"

run_shell "curl -qsL https://install.pwndbg.re | sh -s -- -u -v ${PWNDBG_VERSION} -t pwndbg-gdb"

run bash "$ROOT_DIR/scripts/sync_skills.sh"

echo
echo "Bootstrap complete."
echo "Verify with: bash '$ROOT_DIR/scripts/verify.sh' --env '$ENV_NAME'"
