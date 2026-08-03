#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
command -v docker >/dev/null 2>&1 || { printf 'Docker is required for the disposable distro matrix.\n' >&2; exit 2; }
images=(ubuntu:24.04 fedora:42 archlinux:latest)
for image in "${images[@]}"; do
  printf 'Testing actual installation in %s\n' "$image"
  docker run --rm --volume "$ROOT_DIR:/workspace:ro" "$image" bash /workspace/scripts/test_system_install.sh /workspace
done
