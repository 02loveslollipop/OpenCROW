#!/usr/bin/env bash
# OpenCROW Universal Remote Installer (GitHub Releases)
set -euo pipefail

REPO="02loveslollipop/OpenCROW"
CACHE_DIR="${HOME}/.cache/opencrow"
BUNDLE_DIR="${HOME}/.local/share/opencrow/cli-bundle"
VERSION=""
EXTRA_ARGS=()

usage() {
  cat <<EOF
OpenCROW Remote Installer

Usage:
  curl -fsSL https://raw.githubusercontent.${REPO}/main/scripts/opencrow.sh | bash -s -- [options]

Options:
  --version <tag>   Specify GitHub Release version tag (default: latest release)
  --help            Show this help message
  *                 All other flags are passed directly to the OpenCROW installer
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      VERSION="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

echo "==> OpenCROW Installer"

# Dependencies check
for cmd in curl unzip sha256sum; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Error: Required utility '$cmd' is not installed." >&2
    exit 1
  fi
done

# Resolve release version tag
if [[ -z "$VERSION" ]]; then
  echo "==> Fetching latest release information..."
  RELEASE_API_URL="https://api.github.com/repos/${REPO}/releases/latest"
  VERSION="$(curl -sSL "$RELEASE_API_URL" | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/' || true)"
  if [[ -z "$VERSION" ]]; then
    echo "Warning: Could not determine latest release tag via GitHub API." >&2
    echo "Falling back to main release bundle URL..." >&2
    DOWNLOAD_URL="https://github.com/${REPO}/releases/latest/download/opencrow-cli.zip"
    VERSION="latest"
  else
    DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${VERSION}/opencrow-cli.zip"
  fi
else
  DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${VERSION}/opencrow-cli.zip"
fi

echo "==> Selected OpenCROW version: ${VERSION}"

ZIP_CACHE="${CACHE_DIR}/releases/${VERSION}/opencrow-cli.zip"
mkdir -p "$(dirname "$ZIP_CACHE")"

echo "==> Downloading OpenCROW CLI package from ${DOWNLOAD_URL}..."
if ! curl -fsSL -o "$ZIP_CACHE" "$DOWNLOAD_URL"; then
  echo "Error: Failed to download release bundle from ${DOWNLOAD_URL}" >&2
  exit 1
fi

echo "==> Unpacking OpenCROW CLI bundle..."
mkdir -p "$BUNDLE_DIR"
rm -rf "${BUNDLE_DIR:?}"/*
unzip -q "$ZIP_CACHE" -d "$BUNDLE_DIR"

INSTALL_SCRIPT="${BUNDLE_DIR}/scripts/install.sh"
if [[ ! -f "$INSTALL_SCRIPT" ]]; then
  echo "Error: Release bundle does not contain scripts/install.sh" >&2
  exit 1
fi

chmod +x "$INSTALL_SCRIPT"
echo "==> Starting installation..."
exec "$INSTALL_SCRIPT" "${EXTRA_ARGS[@]}"
