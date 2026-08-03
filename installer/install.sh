#!/usr/bin/env bash
set -euo pipefail

INSTALLER_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SOURCE_ROOT=$(CDPATH= cd -- "$INSTALLER_DIR/.." && pwd)
# shellcheck source=lib/selector.sh
source "$INSTALLER_DIR/lib/selector.sh"
ORIGINAL_ARGS=("$@")

DRY_RUN=0
ASSUME_YES=0
AGENTS_ARG=
TOOLBOXES_ARG=
TOOLS_ARG=
INSTALL_MISSING=0
INSTALL_CONDA=auto
ADVANCED=0
BUNDLE=

usage() {
  cat <<'EOF'
Usage: install.sh [--agents LIST] [--toolboxes LIST] [--tools LIST]
                  [--install-missing-agent-clis] [--miniconda|--no-miniconda]
                  [--bundle PATH] [--advanced] [--yes] [--dry-run]

Full OpenCROW installation. Linux x86_64/aarch64 only. Mutation requires sudo;
all user assets are installed as SUDO_USER and only OS packages run as root.
EOF
}

while (($#)); do
  case "$1" in
    --agents) AGENTS_ARG=${2:?missing value}; shift 2 ;;
    --toolboxes) TOOLBOXES_ARG=${2:?missing value}; shift 2 ;;
    --tools) TOOLS_ARG=${2:?missing value}; shift 2 ;;
    --install-missing-agent-clis) INSTALL_MISSING=1; shift ;;
    --miniconda) INSTALL_CONDA=yes; shift ;;
    --no-miniconda) INSTALL_CONDA=no; shift ;;
    --advanced) ADVANCED=1; shift ;;
    --bundle) BUNDLE=${2:?missing value}; shift 2 ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) printf 'install.sh: unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

compatibility_report() {
  printf 'OpenCROW compatibility report\n  OS: %s\n  architecture: %s\n  distro: %s\n  package manager: %s\n' \
    "$(uname -s)" "$MACHINE" "${DISTRO_ID:-unknown}" "${PACKAGE_MANAGER:-unsupported}" >&2
}

MACHINE=${OPENCROW_TEST_MACHINE:-$(uname -m)}
if [[ $(uname -s) != Linux ]]; then
  DISTRO_ID=unknown PACKAGE_MANAGER=unsupported compatibility_report
  exit 3
fi
case "$MACHINE" in
  x86_64|amd64) ARCH=x86_64 ;;
  aarch64|arm64) ARCH=aarch64 ;;
  *) DISTRO_ID=unknown PACKAGE_MANAGER=unsupported compatibility_report; exit 3 ;;
esac
DISTRO_ID=
if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
  DISTRO_ID=${ID:-}
  DISTRO_LIKE=${ID_LIKE:-}
fi
case " $DISTRO_ID ${DISTRO_LIKE:-} " in
  *" debian "*|*" ubuntu "*)
    if command -v apt-get >/dev/null 2>&1; then PACKAGE_MANAGER=apt; else PACKAGE_MANAGER=unsupported; fi
    ;;
  *" fedora "*|*" rhel "*|*" rocky "*)
    if command -v dnf >/dev/null 2>&1; then
      PACKAGE_MANAGER=dnf
    elif command -v yum >/dev/null 2>&1; then
      PACKAGE_MANAGER=yum
    else
      PACKAGE_MANAGER=unsupported
    fi
    ;;
  *" arch "*)
    if command -v pacman >/dev/null 2>&1; then PACKAGE_MANAGER=pacman; else PACKAGE_MANAGER=unsupported; fi
    ;;
  *) PACKAGE_MANAGER=unsupported; compatibility_report; exit 3 ;;
esac
if [[ "$PACKAGE_MANAGER" == unsupported ]]; then
  compatibility_report
  exit 3
fi

providers=(codex opencode claude antigravity)
commands=(codex opencode claude agy)
detected=()
for index in "${!providers[@]}"; do
  command -v "${commands[index]}" >/dev/null 2>&1 && detected+=("${providers[index]}")
done
defaults=$(join_by_comma "${detected[@]}")
if [[ -n "$AGENTS_ARG" ]]; then
  IFS=',' read -r -a selected_agents <<< "$AGENTS_ARG"
else
  selected_agents=("${detected[@]}")
fi
install_missing=()

conda_detected=0
command -v conda >/dev/null 2>&1 && conda_detected=1
if ((EUID == 0)) && [[ -n "${SUDO_USER:-}" ]]; then
  sudo_home=$(getent passwd "$SUDO_USER" | awk -F: '{print $6}')
  for candidate in "$sudo_home/.local/share/opencrow/miniconda/bin/conda" "$sudo_home/miniconda3/bin/conda" "$sudo_home/anaconda3/bin/conda"; do
    [[ -x "$candidate" ]] && conda_detected=1
  done
fi
conda_selected=0
if [[ "$INSTALL_CONDA" == yes ]]; then
  conda_selected=1
elif [[ "$INSTALL_CONDA" == auto ]] && ((conda_detected == 0)); then
  conda_selected=1
fi

headless=(utility network reversing pwn web forensics stego crypto osint)
toolbox_options=("${headless[@]}" sagemath)
headless_defaults=$(join_by_comma "${headless[@]}")
if [[ -n "$TOOLBOXES_ARG" ]]; then
  IFS=',' read -r -a selected_toolboxes <<< "$TOOLBOXES_ARG"
else
  selected_toolboxes=("${headless[@]}")
fi

selected_tools=()
if [[ -n "$TOOLS_ARG" ]]; then
  IFS=',' read -r -a selected_tools <<< "$TOOLS_ARG"
fi
manual=(burpsuite zaproxy autopsy openstego steghsolve ghidra-gui)

refresh_missing() {
  local selected required
  missing=()
  for selected in "${selected_agents[@]}"; do
    case "$selected" in
      codex) required=codex ;;
      opencode) required=opencode ;;
      claude) required=claude ;;
      antigravity) required=agy ;;
      *) printf 'Unknown provider: %s\n' "$selected" >&2; exit 2 ;;
    esac
    command -v "$required" >/dev/null 2>&1 || missing+=("$selected")
  done
}

screen_enabled() {
  case "$1" in
    1) [[ -z "$AGENTS_ARG" ]] ;;
    2) ((${#missing[@]} > 0 && INSTALL_MISSING == 0)) ;;
    3) [[ "$INSTALL_CONDA" == auto ]] && ((conda_detected == 0)) ;;
    4) [[ -z "$TOOLBOXES_ARG" ]] ;;
    5) [[ -z "$TOOLS_ARG" ]] ;;
    *) return 1 ;;
  esac
}

next_enabled_screen() {
  local candidate=$(( $1 + 1 ))
  while ((candidate <= 5)); do
    if screen_enabled "$candidate"; then printf '%s' "$candidate"; return; fi
    candidate=$((candidate + 1))
  done
  printf '6'
}

previous_enabled_screen() {
  local candidate=$(( $1 - 1 ))
  while ((candidate >= 1)); do
    if screen_enabled "$candidate"; then printf '%s' "$candidate"; return; fi
    candidate=$((candidate - 1))
  done
  printf '0'
}

run_selection_flow() {
  local screen=$1 status defaults_for_screen prior
  while ((screen <= 5)); do
    refresh_missing
    if ! screen_enabled "$screen"; then
      screen=$(next_enabled_screen "$screen")
      continue
    fi
    case "$screen" in
      1)
        defaults_for_screen=$(join_by_comma "${selected_agents[@]}")
        if select_many "1/6 Agent integrations (missing CLIs are visible but unchecked)" "$defaults_for_screen" "${providers[@]}"; then
          selected_agents=("${SELECTED_VALUES[@]}")
          if ((${#selected_agents[@]} == 0)); then
            printf 'Select at least one agent integration.\n' >&2
            continue
          fi
          install_missing=()
        else
          status=$?
          ((status == 1)) && exit 1
          printf 'Already at the first applicable installer screen.\n' >&2
          continue
        fi
        ;;
      2)
        defaults_for_screen=$(join_by_comma "${install_missing[@]}")
        if select_many "2/6 Optionally install selected missing agent CLIs" "$defaults_for_screen" "${missing[@]}"; then
          install_missing=("${SELECTED_VALUES[@]}")
        else
          status=$?
          ((status == 1)) && exit 1
          screen=$(previous_enabled_screen "$screen")
          continue
        fi
        ;;
      3)
        defaults_for_screen=
        ((conda_selected)) && defaults_for_screen="Install Miniconda"
        if select_many "3/6 Miniconda (recommended because Conda was not detected)" "$defaults_for_screen" "Install Miniconda"; then
          conda_selected=0
          _selector_contains "Install Miniconda" "${SELECTED_VALUES[@]}" && conda_selected=1
        else
          status=$?
          ((status == 1)) && exit 1
          screen=$(previous_enabled_screen "$screen")
          continue
        fi
        ;;
      4)
        defaults_for_screen=$(join_by_comma "${selected_toolboxes[@]}")
        if select_many "4/6 Toolbox bundles (headless bundles are preselected; SageMath is optional)" "$defaults_for_screen" "${toolbox_options[@]}"; then
          selected_toolboxes=("${SELECTED_VALUES[@]}")
        else
          status=$?
          ((status == 1)) && exit 1
          screen=$(previous_enabled_screen "$screen")
          continue
        fi
        ;;
      5)
        defaults_for_screen=$(join_by_comma "${selected_tools[@]}")
        if select_many "5/6 Advanced individual-tool overrides" "$defaults_for_screen" "${manual[@]}"; then
          selected_tools=("${SELECTED_VALUES[@]}")
        else
          status=$?
          ((status == 1)) && exit 1
          screen=$(previous_enabled_screen "$screen")
          continue
        fi
        ;;
    esac
    refresh_missing
    screen=$(next_enabled_screen "$screen")
  done
}

refresh_missing
if ((INSTALL_MISSING || ASSUME_YES)); then install_missing=("${missing[@]}"); fi
if ((!ASSUME_YES)); then
  first_screen=$(next_enabled_screen 0)
  ((first_screen <= 5)) && run_selection_flow "$first_screen"
fi
if ((${#selected_agents[@]} == 0)); then
  printf 'install.sh: select at least one agent integration.\n' >&2
  exit 2
fi

while true; do
  agents_csv=$(join_by_comma "${selected_agents[@]}")
  toolboxes_csv=$(join_by_comma "${selected_toolboxes[@]}")
  tools_csv=$(join_by_comma "${selected_tools[@]}")
  sagemath_extra=0
  _selector_contains sagemath "${selected_toolboxes[@]}" && sagemath_extra=6
  estimated_gb=$((2 + ${#selected_toolboxes[@]} * 1 + conda_selected * 2 + sagemath_extra))
  printf '\n6/6 Licenses, estimate, and command plan\n'
  printf '  Providers: %s\n  Missing CLI installs: %s\n  Miniconda: %s\n  Toolboxes: %s\n  Advanced tools: %s\n' \
    "$agents_csv" "$(join_by_comma "${install_missing[@]}")" "$conda_selected" "$toolboxes_csv" "${tools_csv:-none}"
  printf '  Estimated disk ceiling: approximately %s GiB\n' "$estimated_gb"
  printf '  Package manager: %s (OS packages only)\n' "$PACKAGE_MANAGER"
  printf '  Licenses: OpenCROW Apache-2.0; third-party tools retain their own licenses.\n'
  printf '  Runtime trust: Constellation hosts execute provider agents in full-auto mode.\n'
  ((ASSUME_YES)) && break
  if select_many "Final confirmation" "Install" "Install"; then
    _selector_contains Install "${SELECTED_VALUES[@]}" || { printf 'Installation cancelled.\n'; exit 1; }
    break
  fi
  status=$?
  ((status == 1)) && exit 1
  prior=$(previous_enabled_screen 6)
  if ((prior == 0)); then
    printf 'No earlier interactive screen is available.\n' >&2
  else
    run_selection_flow "$prior"
  fi
done

if ((DRY_RUN)); then
  compatibility_report
  printf 'Dry run: no packages, files, environments, or provider configs were changed.\n'
  exit 0
fi

if ((EUID != 0)); then
  printf 'Full installation requires sudo and has not changed the machine. Rerun exactly:\n  sudo bash %q' "$0" >&2
  printf ' %q' "${ORIGINAL_ARGS[@]}" >&2
  printf '\nFor a rootless installation instead:\n  curl -fsSL https://opencrow.02labs.me/skills.sh | bash\n' >&2
  exit 4
fi

TARGET_USER=${OPENCROW_TARGET_USER:-${SUDO_USER:-}}
if [[ -z "$TARGET_USER" ]]; then
  printf 'install.sh: run through sudo so SUDO_USER identifies the owner of user files, or set OPENCROW_TARGET_USER. No changes made.\n' >&2
  exit 4
fi
TARGET_HOME=$(getent passwd "$TARGET_USER" | awk -F: '{print $6}')
[[ -n "$TARGET_HOME" ]] || { printf 'install.sh: cannot resolve home for %s.\n' "$TARGET_USER" >&2; exit 4; }

run_user() {
  sudo -H -u "$TARGET_USER" env \
    HOME="$TARGET_HOME" \
    OPENCROW_TARGET_HOME="$TARGET_HOME" \
    PATH="$TARGET_HOME/.local/bin:$TARGET_HOME/.opencode/bin:$PATH" \
    "$@"
}

case "$PACKAGE_MANAGER" in
  apt) base_packages=(python3 python3-venv curl ca-certificates unzip) ;;
  dnf|yum) base_packages=(python3 python3-pip curl ca-certificates unzip) ;;
  pacman) base_packages=(python curl ca-certificates unzip) ;;
esac
preexisting_base=()
for package in "${base_packages[@]}"; do
  case "$PACKAGE_MANAGER" in
    apt) dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed' && preexisting_base+=("$package") ;;
    dnf|yum) rpm -q "$package" >/dev/null 2>&1 && preexisting_base+=("$package") ;;
    pacman) pacman -Q "$package" >/dev/null 2>&1 && preexisting_base+=("$package") ;;
  esac
done
case "$PACKAGE_MANAGER" in
  apt)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y "${base_packages[@]}"
    ;;
  dnf) dnf install -y "${base_packages[@]}" ;;
  yum) yum install -y "${base_packages[@]}" ;;
  pacman) pacman -Sy --needed --noconfirm "${base_packages[@]}" ;;
esac

package_plan=$(python3 - "$INSTALLER_DIR/platforms/packages.json" "$PACKAGE_MANAGER" "$toolboxes_csv" "$tools_csv" <<'PY'
import json, sys
path, manager, selected, tools = sys.argv[1:]
if manager == "yum": manager = "dnf"
data = json.load(open(path, encoding="utf-8"))["platforms"][manager]
packages = []
for name in [x for x in selected.split(",") if x]: packages.extend(data.get(name, []))
tool_map = data.get("tools", {})
for name in [x for x in tools.split(",") if x]: packages.append(tool_map.get(name, f"unresolved:{name}"))
print(" ".join(dict.fromkeys(packages)))
PY
)
resolved_packages=("${base_packages[@]}")
unresolved_packages=()
preexisting_packages=("${preexisting_base[@]}")
if [[ -n "$package_plan" ]]; then
  read -r -a package_candidates <<< "$package_plan"
  for package in "${package_candidates[@]}"; do
    if [[ "$package" == unresolved:* ]]; then
      unresolved_packages+=("${package#unresolved:}")
      continue
    fi
    available=0
    case "$PACKAGE_MANAGER" in
      apt) apt-cache show "$package" >/dev/null 2>&1 && available=1 ;;
      dnf|yum)
        "$PACKAGE_MANAGER" -q list --available "$package" >/dev/null 2>&1 && available=1
        "$PACKAGE_MANAGER" -q list --installed "$package" >/dev/null 2>&1 && available=1
        ;;
      pacman) pacman -Si "$package" >/dev/null 2>&1 && available=1 ;;
    esac
    if ((available)); then
      resolved_packages+=("$package")
      case "$PACKAGE_MANAGER" in
        apt) dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed' && preexisting_packages+=("$package") ;;
        dnf|yum) rpm -q "$package" >/dev/null 2>&1 && preexisting_packages+=("$package") ;;
        pacman) pacman -Q "$package" >/dev/null 2>&1 && preexisting_packages+=("$package") ;;
      esac
    else
      unresolved_packages+=("$package")
    fi
  done
fi
if ((${#resolved_packages[@]})); then
  case "$PACKAGE_MANAGER" in
    apt) apt-get install -y "${resolved_packages[@]}" ;;
    dnf) dnf install -y "${resolved_packages[@]}" ;;
    yum) yum install -y "${resolved_packages[@]}" ;;
    pacman) pacman -S --needed --noconfirm "${resolved_packages[@]}" ;;
  esac
fi
if ((${#unresolved_packages[@]})); then
  printf 'OpenCROW unresolved external packages (installation continues): %s\n' "$(join_by_comma "${unresolved_packages[@]}")" >&2
fi

install_missing_csv=$(join_by_comma "${install_missing[@]}")
cli_receipt_before=$(run_user python3 "$INSTALLER_DIR/lib/agent_cli_receipts.py" snapshot \
  --home "$TARGET_HOME" --providers "$install_missing_csv")
for provider in "${install_missing[@]}"; do
  run_user bash "$INSTALLER_DIR/lib/install_agent_cli.sh" "$provider"
done
cli_receipts=$(run_user python3 "$INSTALLER_DIR/lib/agent_cli_receipts.py" receipts \
  --home "$TARGET_HOME" --providers "$install_missing_csv" --before "$cli_receipt_before")
if ((conda_selected)); then
  run_user bash "$INSTALLER_DIR/lib/install_miniconda.sh" "$TARGET_HOME/.local/share/opencrow/miniconda"
fi

managed_conda="$TARGET_HOME/.local/share/opencrow/miniconda/bin/conda"
conda_command=
if [[ -x "$managed_conda" ]]; then
  conda_command=$managed_conda
else
  for candidate in "$TARGET_HOME/miniconda3/bin/conda" "$TARGET_HOME/anaconda3/bin/conda" /opt/conda/bin/conda; do
    if [[ -x "$candidate" ]]; then conda_command=$candidate; break; fi
  done
  if [[ -z "$conda_command" ]]; then
    conda_command=$(run_user sh -c 'command -v conda 2>/dev/null || true')
  fi
fi
environment_args=()
if [[ -n "$conda_command" ]]; then
  environment_args=(--conda "$conda_command")
fi
environment_methods_json=$(run_user python3 "$INSTALLER_DIR/lib/install_python_envs.py" \
  "${environment_args[@]}" \
  --manifest "$INSTALLER_DIR/manifests/python-environments.json" \
  --data-root "$TARGET_HOME/.local/share/opencrow" \
  --toolboxes "$toolboxes_csv")
environment_unresolved=$(python3 - "$environment_methods_json" <<'PY'
import json, sys
print("; ".join(json.loads(sys.argv[1]).get("unresolved", [])))
PY
)
if [[ -n "$environment_unresolved" ]]; then
  printf 'OpenCROW unresolved environment dependencies (installation continues): %s\n' "$environment_unresolved" >&2
fi

package_methods_json=$(python3 - "$PACKAGE_MANAGER" "$(join_by_comma "${resolved_packages[@]}")" "$(join_by_comma "${preexisting_packages[@]}")" "$(join_by_comma "${unresolved_packages[@]}")" "$install_missing_csv" "$conda_selected" "$environment_methods_json" "$cli_receipts" <<'PY'
import json, sys
manager, installed, preexisting, unresolved, agent_clis, miniconda, environments, receipts = sys.argv[1:]
split = lambda value: [item for item in value.split(",") if item]
installed_values, preexisting_values = split(installed), set(split(preexisting))
print(json.dumps({
    "os_packages": {"method": manager, "resolved": installed_values, "installed_by_opencrow": [item for item in installed_values if item not in preexisting_values], "preexisting": sorted(preexisting_values), "unresolved": split(unresolved)},
    "agent_clis": {"method": "vendor-owned", "installed": split(agent_clis), "receipts": json.loads(receipts)},
    "miniconda": {"method": "vendor-checksummed", "installed": miniconda == "1"},
    "python_environments": json.loads(environments),
}, separators=(",", ":")))
PY
)
source_args=(--source "$SOURCE_ROOT")
if [[ -n "$BUNDLE" ]]; then source_args=(--bundle "$BUNDLE"); fi
run_user python3 "$INSTALLER_DIR/opencrow_manager.py" internal-install \
  "${source_args[@]}" --mode full --agents "$agents_csv" --toolboxes "$toolboxes_csv" --tools "$tools_csv" \
  --package-methods-json "$package_methods_json"
printf 'OpenCROW full installation complete for %s. Start a new shell, then run `opencrow doctor`.\n' "$TARGET_USER"
