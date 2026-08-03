#!/usr/bin/env bash
set -euo pipefail
provider=${1:?provider required}
case "$provider" in
  codex)
    command -v npm >/dev/null 2>&1 || { printf 'Codex CLI unresolved: npm is unavailable.\n' >&2; exit 4; }
    npm install --global --prefix "$HOME/.local" @openai/codex
    ;;
  opencode)
    curl -fsSL https://opencode.ai/install | bash
    ;;
  claude)
    curl -fsSL https://claude.ai/install.sh | bash
    ;;
  antigravity)
    curl -fsSL https://antigravity.google/cli/install.sh | bash
    ;;
  *) printf 'Unknown provider: %s\n' "$provider" >&2; exit 2 ;;
esac
