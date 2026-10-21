#!/usr/bin/env bash
# Read-only checks of the per-project LLM keys on a deployed stack: the internal resolve route
# is not served by the launcher, and a non-admin cannot read a project's LLM settings.
# Run by hand after a deployment; it changes nothing.
#
#   ./scripts/verify-llm-keys.sh [project-slug]
#
# Env:
#   LAUNCHER_URL   default http://localhost:8100
#   AISC_COOKIE    optional: the Cookie header of a NON-admin session; never printed.
#                  With it, the second check runs (a non-admin gets 403).
set -euo pipefail

LAUNCHER_URL=${LAUNCHER_URL:-http://localhost:8100}
SLUG=${1:-}
failed=0

check() {  # check <name> <expected status> <actual status>
  if [ "$2" = "$3" ]; then
    echo "PASS $1 (HTTP $3)"
  else
    echo "FAIL $1 (expected HTTP $2, got HTTP $3)"
    failed=1
  fi
}

got=$(curl -s -o /dev/null -w '%{http_code}' \
  "$LAUNCHER_URL/api/internal/projects/00000000-0000-0000-0000-000000000000/llm/card_agent")
check "the launcher does not serve the internal resolve route" 404 "$got"

if [ -n "${AISC_COOKIE:-}" ] && [ -n "$SLUG" ]; then
  got=$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: $AISC_COOKIE" \
    "$LAUNCHER_URL/api/projects/$SLUG/llm")
  check "a non-admin cannot read the project's LLM settings" 403 "$got"
else
  echo "SKIP the non-admin check: set AISC_COOKIE and give a project slug"
fi

exit $failed
