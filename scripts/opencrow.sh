#!/usr/bin/env bash
set -euo pipefail

REPOSITORY=${OPENCROW_REPOSITORY:-02loveslollipop/OpenCROW}
VERSION=latest
PASSTHROUGH=()

usage() {
  cat <<'EOF'
Usage: install.sh [--version VERSION] [full installer options]

Downloads and verifies the OpenCROW full release bundle, then runs its native
installer. Use https://opencrow.02labs.me/skills.sh for the rootless package.
EOF
}

while (($#)); do
  case "$1" in
    --version) VERSION=${2:?missing value}; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) PASSTHROUGH+=("$1"); shift ;;
  esac
done

for command in curl unzip sha256sum; do
  command -v "$command" >/dev/null 2>&1 || { printf 'install.sh: required command is missing: %s\n' "$command" >&2; exit 1; }
done
if [[ "$VERSION" == latest ]]; then
  BASE="https://github.com/$REPOSITORY/releases/latest/download"
else
  BASE="https://github.com/$REPOSITORY/releases/download/$VERSION"
fi
TEMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/opencrow-full.XXXXXX")
trap 'rm -rf "$TEMP_DIR"' EXIT
curl -fsSL "$BASE/release-checksums.txt" -o "$TEMP_DIR/release-checksums.txt"
curl -fsSL "$BASE/opencrow-full.zip" -o "$TEMP_DIR/opencrow-full.zip"
EXPECTED=$(awk '$2 == "opencrow-full.zip" || $2 == "*opencrow-full.zip" {print $1; exit}' "$TEMP_DIR/release-checksums.txt")
[[ "$EXPECTED" =~ ^[a-fA-F0-9]{64}$ ]] || { printf 'install.sh: release checksum is missing.\n' >&2; exit 1; }
printf '%s  %s\n' "$EXPECTED" "$TEMP_DIR/opencrow-full.zip" | sha256sum -c - >/dev/null
unzip -q "$TEMP_DIR/opencrow-full.zip" -d "$TEMP_DIR/source"
[[ -x "$TEMP_DIR/source/installer/install.sh" || -f "$TEMP_DIR/source/installer/install.sh" ]] || { printf 'install.sh: verified bundle lacks installer/install.sh.\n' >&2; exit 1; }
exec bash "$TEMP_DIR/source/installer/install.sh" "${PASSTHROUGH[@]}"
