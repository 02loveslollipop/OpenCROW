#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=${1:-/workspace}
[[ $(id -u) == 0 ]] || { printf 'System install smoke must run as root inside a disposable Linux host.\n' >&2; exit 2; }

# Bootstrap only what the full installer itself expects to exist before it owns
# package selection. All subsequent packages are installed by install.sh.
source /etc/os-release
case " ${ID:-} ${ID_LIKE:-} " in
  *" debian "*|*" ubuntu "*)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y sudo passwd
    ;;
  *" fedora "*|*" rhel "*|*" rocky "*)
    manager=dnf
    command -v dnf >/dev/null 2>&1 || manager=yum
    "$manager" install -y sudo shadow-utils
    ;;
  *" arch "*)
    pacman -Sy --needed --noconfirm sudo shadow
    ;;
  *) printf 'Unsupported disposable distro: %s\n' "${ID:-unknown}" >&2; exit 3 ;;
esac

useradd --create-home --shell /bin/bash opencrow-ci
printf '#!/bin/sh\necho "codex 99.0.0"\n' >/usr/local/bin/codex
chmod 0755 /usr/local/bin/codex

full_install_log=/tmp/opencrow-full-install.log
if ! OPENCROW_TARGET_USER=opencrow-ci bash "$ROOT_DIR/installer/install.sh" \
  --agents codex --toolboxes utility --no-miniconda --yes >"$full_install_log" 2>&1; then
  cat "$full_install_log" >&2
  exit 1
fi
if find /home/opencrow-ci/.local/share/opencrow/current \
  \( -type d -name __pycache__ -o -type f \( -name '*.pyc' -o -name '*.pyo' \) \) \
  -print -quit | grep -q .; then
  printf 'Managed installation contains generated Python cache files.\n' >&2
  exit 1
fi
for command in jq xxd tmux screen rg fzf; do
  command -v "$command" >/dev/null 2>&1 || {
    printf 'Utility toolbox command is missing after installation: %s\n' "$command" >&2
    exit 1
  }
done
sudo -H -u opencrow-ci env \
  HOME=/home/opencrow-ci \
  OPENCROW_TARGET_HOME=/home/opencrow-ci \
  PATH=/home/opencrow-ci/.local/bin:/usr/local/bin:/usr/bin:/bin \
  /home/opencrow-ci/.local/bin/opencrow doctor >/tmp/opencrow-doctor.json
grep -q '"ok": true' /tmp/opencrow-doctor.json
sudo -H -u opencrow-ci env \
  HOME=/home/opencrow-ci \
  OPENCROW_TARGET_HOME=/home/opencrow-ci \
  PATH=/home/opencrow-ci/.local/bin:/usr/local/bin:/usr/bin:/bin \
  /home/opencrow-ci/.local/bin/opencrow uninstall --purge-env >/tmp/opencrow-uninstall.json
[[ ! -e /home/opencrow-ci/.local/state/opencrow/state.json ]]

useradd --create-home --shell /bin/bash opencrow-skills
skills_install_log=/tmp/opencrow-skills-install.log
if ! sudo -H -u opencrow-skills env \
  HOME=/home/opencrow-skills \
  OPENCROW_TARGET_HOME=/home/opencrow-skills \
  PATH=/usr/local/bin:/usr/bin:/bin \
  bash "$ROOT_DIR/installer/skills.sh" --agents codex --yes >"$skills_install_log" 2>&1; then
  cat "$skills_install_log" >&2
  exit 1
fi
[[ ! -e /home/opencrow-skills/.local/share/opencrow/miniconda ]]
[[ ! -e /home/opencrow-skills/.local/bin/opencrow-init ]]
sudo -H -u opencrow-skills env \
  HOME=/home/opencrow-skills \
  OPENCROW_TARGET_HOME=/home/opencrow-skills \
  PATH=/home/opencrow-skills/.local/bin:/usr/local/bin:/usr/bin:/bin \
  /home/opencrow-skills/.local/bin/opencrow doctor >/tmp/opencrow-skills-doctor.json
grep -q '"ok": true' /tmp/opencrow-skills-doctor.json

printf 'Actual full and skills-only install passed on %s.\n' "${PRETTY_NAME:-$ID}"
