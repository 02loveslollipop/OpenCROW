#!/usr/bin/env bash
# Expensive release gate: two independent real installation scenarios per distro.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CANDIDATE=$(realpath "${1:?candidate full zip required}")
BASELINE=$(realpath "${2:?previous stable full zip required}")
REPORTS=$(realpath -m "${3:?report directory required}")
[[ -f "$CANDIDATE" && -f "$BASELINE" ]] || { echo 'Both release bundle files are required' >&2; exit 2; }
mkdir -p "$REPORTS"
status=0
container=
cleanup() {
  if [[ -n "$container" ]]; then docker rm -f "$container" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
for image in ubuntu:24.04 fedora:42 archlinux:latest; do
  for scenario in fresh upgrade; do
    report="$REPORTS/${image//[:\/]/-}-$scenario"
    mkdir -p "$report"
    container="opencrow-release-${GITHUB_RUN_ID:-$$}-${image%%:*}-$scenario"
    # No host HOME, credentials, Docker socket, or writable source mount.
    if timeout --signal=TERM --kill-after=30s 45m docker run --rm --init \
      --name "$container" \
      -e OPENCROW_DISPOSABLE_RELEASE_TEST=1 \
      -v "$ROOT:/workspace:ro" -v "$CANDIDATE:/candidate.zip:ro" \
      -v "$BASELINE:/baseline.zip:ro" -v "$report:/reports" \
      "$image" bash /workspace/scripts/test_release_install_container.sh "$scenario" \
      >"$report/container.log" 2>&1; then
      printf '%s %s passed\n' "$image" "$scenario"
    else
      status=1
      printf '%s %s failed; see %s\n' "$image" "$scenario" "$report/container.log" >&2
      cleanup
    fi
    container=
  done
done
exit "$status"
