#!/usr/bin/env bash
# immudb's one access model, as assertions against the running stack.
#
#   ./scripts/verify-immudb.sh
#
# Read only. Containers are read by `docker inspect`: the NAMES of their variables, never a value, but
# aisc-backend's IMMUDB_USER and IMMUDB_DATABASE, which are not secrets. The engine's account is checked as
# itself (`python -m platform_service.ledger.engine_account check`, in a short-lived platform container),
# its password handed by name from env.secrets, as scripts/ledger-pool.sh hands its own.
set -uo pipefail
cd "$(dirname "$0")/.."
PROJECT=${COMPOSE_PROJECT:-aisc}
pass=0; fail=0
ok(){ printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
no(){ printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }
env_lines(){ docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$1" 2>/dev/null; }
names_of(){ env_lines "$1" | sed -n 's/=.*//p'; }
plain_value(){ env_lines "$1" | awk -v n="$2" 'index($0, n "=") == 1 { print substr($0, length(n) + 2); exit }'; }

LIST=$(docker ps -a --filter "label=com.docker.compose.project=$PROJECT" \
       --format '{{.Names}}\t{{.Label "com.docker.compose.service"}}' 2>/dev/null)
[ -n "$LIST" ] || { echo "no container of compose project $PROJECT"; exit 1; }
container_of(){ awk -F'\t' -v s="$1" '$2 == s { print $1; exit }' <<<"$LIST"; }

echo "1. only immudb and ledger-pool hold immudb's superuser password (variable names only)"
while IFS=$'\t' read -r c svc; do
  [ -n "$c" ] || continue
  names=$(names_of "$c")
  if grep -qx IMMUDB_ADMIN_PASSWORD <<<"$names"; then
    case "$svc" in
      immudb|ledger-pool) ok "$c ($svc) holds it, as designed" ;;
      *) no "$c ($svc) holds IMMUDB_ADMIN_PASSWORD" ;;
    esac
  fi
  case "$svc" in
    dashboard|dashboard-migrate|aisc-backend-migrate)
      bad=$(grep '^IMMUDB_' <<<"$names" | tr '\n' ' ')
      [ -z "$bad" ] && ok "$c has no immudb setting" || no "$c has immudb settings: $bad" ;;
  esac
done <<<"$LIST"

echo "2. the engine reaches immudb as its own user"
c=$(container_of aisc-backend)
if [ -z "$c" ]; then no "no aisc-backend container"; else
  names=$(names_of "$c")
  for n in IMMUDB_URL IMMUDB_USER IMMUDB_PASSWORD IMMUDB_DATABASE; do
    grep -qx "$n" <<<"$names" && ok "$c has $n" || no "$c lacks $n"
  done
  u=$(plain_value "$c" IMMUDB_USER); d=$(plain_value "$c" IMMUDB_DATABASE)
  [ "$u" = aisc_engine ] && ok "$c logs in to immudb as aisc_engine" || no "$c logs in to immudb as '$u', not aisc_engine"
  [ "$d" = auditdb ] && ok "$c writes its audit log to auditdb" || no "$c writes its audit log to '$d', not auditdb"
fi

echo "3. ledger-pool made the account and exited 0"
c=$(container_of ledger-pool)
if [ -z "$c" ]; then no "no ledger-pool container"; else
  code=$(docker inspect --format '{{.State.ExitCode}}' "$c" 2>/dev/null)
  status=$(docker inspect --format '{{.State.Status}}' "$c" 2>/dev/null)
  [ "$status" = exited ] && [ "$code" = 0 ] && ok "ledger-pool ($c) exited 0" \
    || no "ledger-pool ($c) is $status with exit code $code"
fi

echo "4. the engine's account, as itself"
ENGINE_IMMUDB_PASSWORD=$(awk 'index($0, "ENGINE_IMMUDB_PASSWORD=") == 1 { print substr($0, 24); exit }' env.secrets 2>/dev/null || true)
if [ -z "$ENGINE_IMMUDB_PASSWORD" ]; then no "ENGINE_IMMUDB_PASSWORD is missing from env.secrets (run scripts/secrets.sh)"; else
  LEDGER_IMMUDB_URL=${LEDGER_IMMUDB_URL:-immudb:3322}
  export ENGINE_IMMUDB_PASSWORD LEDGER_IMMUDB_URL
  if out=$(docker compose -p "$PROJECT" --env-file env.runtime -f docker-compose.plugin_downloader.yml \
        -f docker-compose-infra.development.yml -f docker-compose.development.yml \
        run --rm --no-deps -e ENGINE_IMMUDB_PASSWORD -e LEDGER_IMMUDB_URL \
        platform python -m platform_service.ledger.engine_account check 2>&1); then
    ok "engine_account check: $(tail -1 <<<"$out")"
  else
    no "engine_account check failed:"; printf '%s\n' "$out" | tail -8 | sed 's/^/       /'
  fi
  unset ENGINE_IMMUDB_PASSWORD
fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
