# Where this install's engine is: the address steps 1 and 2 open on. Sourced, never executed.
#
#   . scripts/lib/engine-address.sh
#   curl "$VERIFY_APPS_URL/qualification"
#
# It is API_URL_EXTERNAL in env.runtime: http://localhost, or another port when scripts/aisc.py start moved
# a new install off a taken port 80 (env.local). VERIFY_APPS_URL, when set, names another one. Exported, so a
# check's Python part reads the same one.

_engine_address() {
  sed -n 's/^API_URL_EXTERNAL=//p' "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/env.runtime" 2>/dev/null \
    | tail -1 | tr -d '"'
}

VERIFY_APPS_URL=${VERIFY_APPS_URL:-$(_engine_address)}
export VERIFY_APPS_URL=${VERIFY_APPS_URL:-http://localhost}
