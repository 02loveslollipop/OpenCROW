#!/usr/bin/env bash
# Dependency-free multi-select used by both OpenCROW installation products.

SELECTED_VALUES=()
SELECTOR_ACTION=confirm

# Global terminal-restore state for the interactive menu. This must stay
# global (never `local`): trap handlers run outside function scope, and a
# previous attempt with function-local state hung on consecutive menus.
_SELECTOR_TTY_ACTIVE=0
_SELECTOR_SAVED_STTY=""

_selector_restore() {
  if (( ${_SELECTOR_TTY_ACTIVE:-0} )); then
    stty "$_SELECTOR_SAVED_STTY" <&3 2>/dev/null
    _SELECTOR_TTY_ACTIVE=0
  fi
  printf '\033[?25h' >&2
  { exec 3<&-; } 2>/dev/null || true
}

_selector_sig() {
  _selector_restore
  trap - INT TERM
  kill -s "$1" "$$"
}

_selector_arm_traps() {
  trap '_selector_sig INT' INT
  trap '_selector_sig TERM' TERM
}

_selector_contains() {
  local needle=$1 item
  shift
  for item in "$@"; do
    [[ "$item" == "$needle" ]] && return 0
  done
  return 1
}

_selector_plain() {
  local title=$1 defaults=$2
  shift 2
  local options=("$@") answer item index
  printf '\n%s\n' "$title" >&2
  for index in "${!options[@]}"; do
    item=${options[$index]}
    if [[ ",$defaults," == *",$item,"* ]]; then
      printf '  %d. [x] %s\n' "$((index + 1))" "$item" >&2
    else
      printf '  %d. [ ] %s\n' "$((index + 1))" "$item" >&2
    fi
  done
  if [[ ! -r /dev/tty ]]; then
    IFS=',' read -r -a SELECTED_VALUES <<< "$defaults"
    printf 'No interactive terminal; using defaults: %s\n' "${defaults:-none}" >&2
    return 0
  fi
  printf 'Enter comma-separated numbers, Enter for defaults, b for Back, or q for Quit: ' >&2
  IFS= read -r answer </dev/tty
  case "$answer" in
    q|Q) SELECTOR_ACTION=quit; return 1 ;;
    b|B) SELECTOR_ACTION=back; return 2 ;;
    "") IFS=',' read -r -a SELECTED_VALUES <<< "$defaults"; return 0 ;;
  esac
  SELECTED_VALUES=()
  IFS=',' read -r -a indexes <<< "$answer"
  for index in "${indexes[@]}"; do
    index=${index//[[:space:]]/}
    [[ "$index" =~ ^[0-9]+$ ]] || continue
    (( index >= 1 && index <= ${#options[@]} )) && SELECTED_VALUES+=("${options[$((index - 1))]}")
  done
  return 0
}

select_many() {
  local title=$1 defaults=$2
  shift 2
  local options=("$@")
  SELECTED_VALUES=()
  SELECTOR_ACTION=confirm
  if [[ ! -r /dev/tty || ${TERM:-dumb} == dumb || ! -t 2 ]]; then
    _selector_plain "$title" "$defaults" "${options[@]}"
    return $?
  fi

  local selected=() item index=0 key rest cursor
  for item in "${options[@]}"; do
    if [[ ",$defaults," == *",$item,"* ]]; then selected+=(1); else selected+=(0); fi
  done
  exec 3</dev/tty
  _SELECTOR_SAVED_STTY=$(stty -g <&3)
  _SELECTOR_TTY_ACTIVE=1
  _selector_arm_traps
  stty -echo -icanon min 1 time 0 <&3
  printf '\033[?25l' >&2
  while true; do
    printf '\033[2J\033[H%s\n\n' "$title" >&2
    for cursor in "${!options[@]}"; do
      if (( cursor == index )); then printf '  > ' >&2; else printf '    ' >&2; fi
      if (( selected[cursor] )); then
        printf '[x] %s\n' "${options[cursor]}" >&2
      else
        printf '[ ] %s\n' "${options[cursor]}" >&2
      fi
    done
    printf '\nUp/Down navigate · Space toggle · Enter confirm · b Back · q Quit\n' >&2
    IFS= read -rsn1 key <&3
    if [[ "$key" == $'\033' ]]; then
      IFS= read -rsn2 rest <&3
      case "$rest" in
        '[A') (( index = (index - 1 + ${#options[@]}) % ${#options[@]} )) ;;
        '[B') (( index = (index + 1) % ${#options[@]} )) ;;
      esac
    elif [[ "$key" == " " ]]; then
      (( selected[index] = 1 - selected[index] ))
    elif [[ -z "$key" || "$key" == $'\n' || "$key" == $'\r' ]]; then
      break
    elif [[ "$key" == q || "$key" == Q ]]; then
      SELECTOR_ACTION=quit
      _selector_restore
      printf '\n' >&2
      return 1
    elif [[ "$key" == b || "$key" == B ]]; then
      SELECTOR_ACTION=back
      _selector_restore
      printf '\n' >&2
      return 2
    fi
  done
  _selector_restore
  printf '\033[2J\033[H' >&2
  for cursor in "${!options[@]}"; do
    (( selected[cursor] )) && SELECTED_VALUES+=("${options[cursor]}")
  done
  return 0
}

join_by_comma() {
  local IFS=,
  printf '%s' "$*"
}
