# Where this install's pages are: the addresses the checks open. Sourced, never executed.
#
#   . scripts/lib/install-addresses.sh
#   curl "$VERIFY_APPS_URL/qualification" "$VERIFY_BASE_URL/api/projects" "$VERIFY_DASHBOARD_URL/" "$KEYCLOAK_URL/realms/aisc"
#
# Each is the install's own setting in env.runtime: the engine API_URL_EXTERNAL, the launcher
# LAUNCHER_EXTERNAL_URL, the dashboard DASHBOARD_EXTERNAL_URL, the sign-in KEYCLOAK_URL_EXTERNAL. They are the
# default ports (80, 8100, 8188, 8081) until scripts/aisc.py start moved a new install off a taken one
# (env.local). A variable already set names another address and wins. Exported, so a check's Python part reads
# the same ones. VERIFY_BASE_URL is the launcher without its trailing slash.

_install_setting() {
  sed -n "s/^$1=//p" "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/env.runtime" 2>/dev/null \
    | tail -1 | tr -d "\"'"
}

VERIFY_APPS_URL=${VERIFY_APPS_URL:-$(_install_setting API_URL_EXTERNAL)}
export VERIFY_APPS_URL=${VERIFY_APPS_URL:-http://localhost}

VERIFY_BASE_URL=${VERIFY_BASE_URL:-$(_install_setting LAUNCHER_EXTERNAL_URL)}
VERIFY_BASE_URL=${VERIFY_BASE_URL:-http://localhost:8100}
export VERIFY_BASE_URL=${VERIFY_BASE_URL%/}

VERIFY_DASHBOARD_URL=${VERIFY_DASHBOARD_URL:-$(_install_setting DASHBOARD_EXTERNAL_URL)}
export VERIFY_DASHBOARD_URL=${VERIFY_DASHBOARD_URL:-http://localhost:8188}

KEYCLOAK_URL=${KEYCLOAK_URL:-$(_install_setting KEYCLOAK_URL_EXTERNAL)}
export KEYCLOAK_URL=${KEYCLOAK_URL:-http://localhost:8081}
