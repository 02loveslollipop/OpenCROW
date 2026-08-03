#!/usr/bin/env bash
set -euo pipefail

REPOSITORY=${OPENCROW_REPOSITORY:-02loveslollipop/OpenCROW}
VERSION=latest
PASSTHROUGH=()

usage() {
  cat <<'EOF'
Usage: skills.sh [--version VERSION] [skills installer options]

Downloads and verifies the rootless OpenCROW skills/integrations bundle.
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
  command -v "$command" >/dev/null 2>&1 || { printf 'skills.sh: required command is missing: %s\n' "$command" >&2; exit 1; }
done
if [[ "$VERSION" == latest ]]; then
  BASE="https://github.com/$REPOSITORY/releases/latest/download"
else
  BASE="https://github.com/$REPOSITORY/releases/download/$VERSION"
fi
TEMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/opencrow-skills.XXXXXX")
trap 'rm -rf "$TEMP_DIR"' EXIT
curl -fsSL "$BASE/release-checksums.txt" -o "$TEMP_DIR/release-checksums.txt"
curl -fsSL "$BASE/opencrow-skills.zip" -o "$TEMP_DIR/opencrow-skills.zip"
EXPECTED=$(awk '$2 == "opencrow-skills.zip" || $2 == "*opencrow-skills.zip" {print $1; exit}' "$TEMP_DIR/release-checksums.txt")
[[ "$EXPECTED" =~ ^[a-fA-F0-9]{64}$ ]] || { printf 'skills.sh: release checksum is missing.\n' >&2; exit 1; }
printf '%s  %s\n' "$EXPECTED" "$TEMP_DIR/opencrow-skills.zip" | sha256sum -c - >/dev/null
unzip -q "$TEMP_DIR/opencrow-skills.zip" -d "$TEMP_DIR/source"
[[ -f "$TEMP_DIR/source/installer/skills.sh" ]] || { printf 'skills.sh: verified bundle lacks installer/skills.sh.\n' >&2; exit 1; }
exec bash "$TEMP_DIR/source/installer/skills.sh" --version "$VERSION" "${PASSTHROUGH[@]}"
