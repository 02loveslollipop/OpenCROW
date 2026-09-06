#!/usr/bin/env bash
set -euo pipefail
[[ "${OPENCROW_DISPOSABLE_RELEASE_TEST:-}" == 1 && -f /.dockerenv && $(id -u) == 0 ]] || {
  echo 'This script requires an explicitly marked disposable root Docker container.' >&2
  exit 2
}
scenario=${1:?fresh or upgrade required}
[[ "$scenario" == fresh || "$scenario" == upgrade ]]
export DEBIAN_FRONTEND=noninteractive
if command -v apt-get >/dev/null; then
  apt-get update
  apt-get install -y sudo passwd python3 nodejs npm git ca-certificates
elif command -v dnf >/dev/null; then
  dnf install -y sudo shadow-utils python3 nodejs npm git ca-certificates
elif command -v pacman >/dev/null; then
  pacman -Syu --noconfirm --needed sudo shadow python nodejs npm git ca-certificates
else
  echo 'Unsupported release test image' >&2
  exit 2
fi
useradd -m -s /bin/bash release-check
chown release-check:release-check /reports
helper=/workspace/scripts/release_installation.py
python3 "$helper" extract /candidate.zip /tmp/candidate
python3 "$helper" extract /baseline.zip /tmp/baseline
python3 - <<'CHECK'
import json
from pathlib import Path
candidate = json.loads(Path('/tmp/candidate/release-manifest.json').read_text())
baseline = json.loads(Path('/tmp/baseline/release-manifest.json').read_text())
if candidate['release_tag'] == baseline['release_tag']:
    raise SystemExit('Candidate and baseline must be distinct releases')
CHECK
cd /home/release-check
user_run() {
  sudo -H -u release-check env HOME=/home/release-check OPENCROW_TARGET_HOME=/home/release-check \
    PATH=/home/release-check/.local/bin:/home/release-check/.opencode/bin:/usr/local/bin:/usr/bin:/bin \
    PYTHONDONTWRITEBYTECODE=1 "$@"
}
full_install() {
  OPENCROW_TARGET_USER=release-check bash "$1/installer/install.sh" \
    --bundle "$2" --agents codex,opencode,claude,antigravity \
    --toolboxes utility,network,reversing,pwn,web,forensics,stego,crypto,osint \
    --miniconda --install-missing-agent-clis --yes
}
if [[ "$scenario" == fresh ]]; then
  full_install /tmp/candidate /candidate.zip
  user_run python3 "$helper" verify /tmp/candidate /reports/fresh
else
  full_install /tmp/baseline /baseline.zip
  user_run python3 "$helper" verify /tmp/baseline /reports/baseline
  user_run bash -c 'printf "preserve me\n" > "$HOME/release-user-data.txt"; printf "\n# release-user-config: preserve me\n" >> "$HOME/.codex/config.toml"'
  user_run opencrow update --bundle /candidate.zip
  user_run python3 "$helper" verify /tmp/candidate /reports/updated --baseline /tmp/baseline
fi
