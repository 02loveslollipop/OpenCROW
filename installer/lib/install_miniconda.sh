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
temporary_checksum=$(mktemp "${TMPDIR:-/tmp}/miniconda.XXXXXX.sha256")
index=$(mktemp "${TMPDIR:-/tmp}/miniconda-index.XXXXXX.html")
trap 'rm -f "$temporary" "$temporary_checksum" "$index"' EXIT
curl -fsSL "$base/$filename" -o "$temporary"
expected=
# Preferred source: the .sha256 sidecar. Anaconda removed these sidecars from
# repo.anaconda.com, so fall back to the official hash published in the
# repository index page that Anaconda's own docs point to for verification.
if curl -fsSL "$base/${filename}.sha256" -o "$temporary_checksum"; then
  expected=$(awk 'NR == 1 {print $1}' "$temporary_checksum")
fi
if [[ ! "$expected" =~ ^[a-fA-F0-9]{64}$ ]]; then
  if curl -fsSL "$base/index.html" -o "$index"; then
    expected=$(awk -v fn="$filename" '
      $0 ~ ("<a href=\"" fn "\">") { found = 1 }
      found && match($0, /[a-fA-F0-9]{64}/) { print substr($0, RSTART, RLENGTH); exit }
    ' "$index")
  fi
fi
[[ "$expected" =~ ^[a-fA-F0-9]{64}$ ]] || {
  printf 'Vendor checksum unavailable: neither %s.sha256 nor the repository index provided a SHA-256.\n' "$filename" >&2
  exit 2
}
printf '%s  %s\n' "$expected" "$temporary" | sha256sum -c - >/dev/null
bash "$temporary" -b -p "$PREFIX"
