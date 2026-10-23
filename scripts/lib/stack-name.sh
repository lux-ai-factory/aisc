# The names this install's stack and containers carry, the same answers as scripts/aisc.py.
# Source it; it defines two functions and runs nothing.
#
#   aisc_stack              the Compose project: $AISC_PROJECT, else aisc-<id>, else aisc
#   aisc_container NAME     the container of service NAME: aisc-<id>-NAME, or NAME for an install without an id
#
# The id is AISC_INSTALL in the repository root's env.secrets, whatever the current directory.
_aisc_stack_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

_aisc_install_id() {
  [ -f "$_aisc_stack_root/env.secrets" ] || return 0
  awk 'index($0, "AISC_INSTALL=") == 1 { sub(/\r$/, ""); print substr($0, 14); exit }' "$_aisc_stack_root/env.secrets"
}

aisc_stack() {
  local id
  if [ -n "${AISC_PROJECT:-}" ]; then printf '%s\n' "$AISC_PROJECT"; return 0; fi
  id=$(_aisc_install_id)
  if [ -n "$id" ]; then printf 'aisc-%s\n' "$id"; else printf 'aisc\n'; fi
}

aisc_container() {
  local id
  id=$(_aisc_install_id)
  if [ -n "$id" ]; then printf 'aisc-%s-%s\n' "$id" "$1"; else printf '%s\n' "$1"; fi
}
