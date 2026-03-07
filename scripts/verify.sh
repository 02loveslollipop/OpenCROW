#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_NAME="ctf"

usage() {
  cat <<EOF
Usage: $(basename "$0") [--env NAME]
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)
      ENV_NAME="$2"
      shift 2
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

echo "[python modules in ${ENV_NAME}]"
conda run -n "$ENV_NAME" python -c '
import importlib.util as u
mods = [
    "z3",
    "pwn",
    "angr",
    "claripy",
    "capstone",
    "unicorn",
    "keystone",
    "ropper",
    "r2pipe",
    "lief",
    "scapy",
    "fpylll",
]
for mod in mods:
    print(f"{mod}: {bool(u.find_spec(mod))}")
'

echo
echo "[native tools]"
for tool in pwndbg pwninit seccomp-tools ghidra-headless ghidra gdb checksec patchelf r2 qemu-aarch64 objdump strace ltrace binwalk nasm; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "$tool: yes"
  else
    echo "$tool: no"
  fi
done
