#!/usr/bin/env bash
# OpenCROW Lightweight E2E Installation & Functionality Test
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_HOME="/tmp/opencrow-e2e-test-$$"

cleanup() {
  echo "==> Cleaning up temporary test directory ${TEST_HOME}..."
  rm -rf "$TEST_HOME"
}
trap cleanup EXIT

echo "==> 1. Building release packages..."
python3 "$ROOT_DIR/scripts/build_releases.py"

CLI_ZIP="$ROOT_DIR/dist/opencrow-cli.zip"
if [[ ! -f "$CLI_ZIP" ]]; then
  echo "Error: $CLI_ZIP was not created." >&2
  exit 1
fi

echo "==> 2. Setting up isolated test environment in ${TEST_HOME}..."
mkdir -p "$TEST_HOME/.local/share/opencrow/cli-bundle"

echo "==> 3. Unpacking release bundle..."
unzip -q "$CLI_ZIP" -d "$TEST_HOME/.local/share/opencrow/cli-bundle"

INSTALL_SCRIPT="$TEST_HOME/.local/share/opencrow/cli-bundle/scripts/install_headless.sh"
if [[ ! -f "$INSTALL_SCRIPT" ]]; then
  echo "Error: install_headless.sh not found in release bundle." >&2
  exit 1
fi

chmod +x "$INSTALL_SCRIPT"

echo "==> 4. Executing dry-run headless installation..."
OPENCROW_HOME="$TEST_HOME" bash "$INSTALL_SCRIPT" --env ctf --profile headless --dry-run

echo "==> 5. Verifying bundled entrypoint scripts and skill directories..."
BUNDLE_SCRIPTS="$TEST_HOME/.local/share/opencrow/cli-bundle/scripts"
BUNDLE_BIN="$TEST_HOME/.local/share/opencrow/cli-bundle/bin"
BUNDLE_SKILLS="$TEST_HOME/.local/share/opencrow/cli-bundle/skills"

test -f "$BUNDLE_SCRIPTS/install_cli.py"
test -f "$BUNDLE_SCRIPTS/tool_catalog.json"
test -d "$BUNDLE_SKILLS/opencrow-crypto-toolbox"

echo "==> 6. Testing utility executable flags..."
PYTHONPATH="$BUNDLE_SCRIPTS" python3 "$BUNDLE_SCRIPTS/opencrow_autosetup.py" --help >/dev/null
PYTHONPATH="$BUNDLE_SCRIPTS" python3 "$BUNDLE_SCRIPTS/opencrow_exploit.py" --help >/dev/null
PYTHONPATH="$BUNDLE_SCRIPTS" python3 "$BUNDLE_SCRIPTS/opencrow_crypto_mcp.py" --help >/dev/null

echo "==> Lightweight E2E Installation & Functionality Test PASSED cleanly!"
