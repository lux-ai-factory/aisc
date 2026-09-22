#!/usr/bin/env bash
# Is this install sound? One command, one verdict.
#
#   ./scripts/verify.sh              # the running stack, then every module's tests
#   ./scripts/verify.sh --stack      # only the checks against the running stack
#   ./scripts/verify.sh --modules    # only the module test suites
#
# There were five answers to this question: three scripts against the running
# stack and a test runner per module, each with its own invocation and its own
# idea of how to say "fine". This runs all of them and prints one line at the
# end, so "does this install work" has a single answer that a person or a CI job
# can read.
#
# A module whose dependencies are not installed is reported as skipped, not as
# passed: a check that did not run is not a check that succeeded.
set -uo pipefail
cd "$(dirname "$0")/.."
ONLY=${1:-all}
pass=0; fail=0; skip=0
line(){ printf '\n\033[1m%s\033[0m\n' "$1"; }
ok(){   printf '  \033[32m  ok\033[0m %s\n' "$1"; pass=$((pass+1)); }
no(){   printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }
skipped(){ printf '  \033[33mskip\033[0m %s (%s)\n' "$1" "$2"; skip=$((skip+1)); }

run(){ # name | command
  local name="$1"; shift
  local out
  if out=$("$@" 2>&1); then ok "$name"; else
    no "$name"
    printf '%s\n' "$out" | tail -12 | sed 's/^/       /'
  fi
}

if [ "$ONLY" != "--modules" ]; then
  line "the running stack"
  for s in verify-db-access.sh verify-one-database.sh verify-sso.sh verify-catalogue-mapping.sh; do
    if [ -x "scripts/$s" ]; then run "$s" "scripts/$s"; else skipped "$s" "not executable"; fi
  done
fi

if [ "$ONLY" != "--stack" ]; then
  line "the modules"
  # module | directory | what tells you its dependencies are there | command
  while IFS='|' read -r name dir marker cmd; do
    [ -n "$name" ] || continue
    if [ ! -d "$dir" ]; then skipped "$name" "no $dir"; continue; fi
    if [ -n "$marker" ] && [ ! -e "$dir/$marker" ]; then
      skipped "$name" "dependencies not installed"
      continue
    fi
    run "$name" bash -c "cd '$dir' && $cmd"
  done <<'MODULES'
platform|platform|.venv|uv run --extra dev pytest -q
control objectives|apps/control-objectives|.venv|uv run pytest -q
catalogue backend|apps/catalogue/backend|.venv|uv run pytest -q -p no:cacheprovider
catalogue frontend|apps/catalogue/frontend|node_modules|npx vitest run
qualification|apps/qualification|node_modules|npx vitest run
qualification ontology|apps/qualification|node_modules|docker run --rm -v "$PWD:/w" -w /w/services/ontology python:3.12-slim sh -lc 'pip install -q -r requirements.txt pytest && python -m pytest -q'
controls|apps/controls|node_modules|npx vitest run
engine webapp|apps/webapp|node_modules|npx vitest run
engine backend|.|.|docker exec -e DB_ENGINE=django.db.backends.sqlite3 -e DB_NAME=/tmp/aisc-verify.db aisc-backend .venv/bin/python manage.py test aisc_backend.tests.routers aisc_backend.tests.repositories aisc_backend.tests.immudb aisc_backend.tests.keycloak aisc_backend.tests.test_sample aisc_backend.tests.test_platform_links
MODULES
fi

printf '\n\033[1m%d ok, %d failed, %d skipped\033[0m\n' "$pass" "$fail" "$skip"
[ "$fail" -eq 0 ]
