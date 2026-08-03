#!/usr/bin/env bash
set -euo pipefail
PREFIX=${1:?prefix required}
if [[ -x "$PREFIX/bin/conda" ]]; then
  printf 'Using existing OpenCROW-managed Miniconda at %s.\n' "$PREFIX"
  exit 0
fi
case "$(uname -m)" in
  x86_64|amd64) VENDOR_ARCH=x86_64 ;;
  aarch64|arm64) VENDOR_ARCH=aarch64 ;;
  *) printf 'Unsupported Miniconda architecture: %s\n' "$(uname -m)" >&2; exit 3 ;;
esac
filename=Miniconda3-latest-Linux-${VENDOR_ARCH}.sh
base=https://repo.anaconda.com/miniconda
temporary=$(mktemp "${TMPDIR:-/tmp}/miniconda.XXXXXX.sh")
trap 'rm -f "$temporary" "$temporary.sha256"' EXIT
curl -fsSL "$base/$filename" -o "$temporary"
curl -fsSL "$base/${filename}.sha256" -o "$temporary.sha256"
expected=$(awk 'NR == 1 {print $1}' "$temporary.sha256")
[[ "$expected" =~ ^[a-fA-F0-9]{64}$ ]] || { printf 'Vendor checksum manifest is invalid.\n' >&2; exit 2; }
printf '%s  %s\n' "$expected" "$temporary" | sha256sum -c - >/dev/null
bash "$temporary" -b -p "$PREFIX"
