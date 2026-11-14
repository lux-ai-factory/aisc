#!/usr/bin/env bash
# After a restart: the switches, the ledger's mode, the shared Redis and the logs, as assertions against the
# running stack.
#
#   ./scripts/verify-switches.sh [--since TIME]     # TIME as docker logs takes it; default: the last 24 hours
#
# 1. every container given AUTH_ENABLED or LEDGER_MODE is running and holds a switch word (a service that
#    refused a bad value has exited, and is named);
# 2. the latest ledger.mode event the platform wrote at start reads the stack's mode and reached the platform's
#    log without a rejection;
# 3. the shared Redis answers NOAUTH to a client without its password;
# 4. no container's log since TIME holds a token-shaped string. Only the count is printed, never a match.
#
# Read only. Containers are read by `docker inspect`; of their variables only AUTH_ENABLED and LEDGER_MODE are
# read, which are not secrets. The platform database is read as the Postgres container's own user.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
. scripts/lib/stack-name.sh
PROJECT=${COMPOSE_PROJECT:-$(aisc_stack)}
SINCE=24h
if [ "${1:-}" = "--since" ]; then SINCE=${2:?--since needs a time}; fi
pass=0; fail=0
ok(){ printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
no(){ printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }
switch_value(){  # switch_value CONTAINER NAME: the value, or nothing when the container is not given NAME
  docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$1" 2>/dev/null \
    | awk -v n="$2" 'index($0, n "=") == 1 { print substr($0, length(n) + 2); found = 1; exit } END { exit !found }'
}
word(){ printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'; }

LIST=$(docker ps -a --filter "label=com.docker.compose.project=$PROJECT" \
       --format '{{.Names}}\t{{.Label "com.docker.compose.service"}}' 2>/dev/null)
[ -n "$LIST" ] || { echo "no container of compose project $PROJECT"; exit 1; }
container_of(){ awk -F'\t' -v s="$1" '$2 == s { print $1; exit }' <<<"$LIST"; }

echo "1. every service given a switch is running and holds a switch word"
while IFS=$'\t' read -r c _svc; do
  [ -n "$c" ] || continue
  given=0
  for name in AUTH_ENABLED LEDGER_MODE; do
    value=$(switch_value "$c" "$name") || continue
    given=1
    case "$name:$(word "$value")" in
      AUTH_ENABLED:1|AUTH_ENABLED:true|AUTH_ENABLED:yes|AUTH_ENABLED:on) ;;
      AUTH_ENABLED:0|AUTH_ENABLED:false|AUTH_ENABLED:no|AUTH_ENABLED:off) ;;
      LEDGER_MODE:off|LEDGER_MODE:record|LEDGER_MODE:enforce) ;;
      *) no "$c holds $name=$(printf '%q' "$value" | cut -c1-40), which is not a switch word" ;;
    esac
  done
  [ "$given" = 1 ] || continue
  status=$(docker inspect --format '{{.State.Status}}' "$c" 2>/dev/null)
  if [ "$status" = running ]; then ok "$c is running"; else no "$c is $status (a refused switch stops it: docker logs $c)"; fi
done <<<"$LIST"

echo "2. the platform recorded the ledger's mode at start, in its own log"
platform=$(container_of platform)
expected=record
if [ -n "$platform" ] && value=$(switch_value "$platform" LEDGER_MODE); then expected=$(word "$value"); fi
pg=$(container_of postgres)
row=""
if [ -n "$pg" ]; then
  # shellcheck disable=SC2016  # $POSTGRES_USER is the container's own, expanded there
  row=$(docker exec -i "$pg" sh -c 'psql -U "$POSTGRES_USER" -d platform -At' 2>/dev/null <<'SQL'
SELECT details->>'mode', delivered_seq IS NOT NULL, coalesce(delivered_reason, '')
FROM core.outbox WHERE action = 'ledger.mode' ORDER BY occurred_at DESC LIMIT 1
SQL
)
fi
IFS='|' read -r mode delivered reason <<<"$row"
if [ -z "$row" ]; then no "no ledger.mode event in the platform's outbox (has the platform started since the change?)"
elif [ "$mode" != "$expected" ]; then no "the latest ledger.mode reads '$mode', not the stack's '$expected'"
elif [ "$expected" != off ] && [ "$delivered" != t ]; then no "the latest ledger.mode ($mode) is not yet in the platform's log"
elif [ -n "$reason" ]; then no "the latest ledger.mode was rejected by the relay: $reason"
elif [ "$delivered" = t ]; then ok "the latest ledger.mode reads $mode and is in the platform log"
else ok "the latest ledger.mode reads $mode (the ledger is off, so nothing is delivered)"
fi

echo "3. the shared Redis asks for its password"
redis=$(container_of redis)
if [ -z "$redis" ]; then no "no redis container"; else
  answer=$(docker exec "$redis" redis-cli ping 2>&1)
  case "$answer" in
    NOAUTH*) ok "$redis answers NOAUTH without the password" ;;
    *) no "$redis answers '$(printf '%s' "$answer" | head -1 | cut -c1-40)' without a password, not NOAUTH" ;;
  esac
fi

echo "4. no token-shaped string in any log since $SINCE (the count only)"
TOKEN_SHAPE='eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}'
total=0
while IFS=$'\t' read -r c _svc; do
  [ -n "$c" ] || continue
  n=$(docker logs --since "$SINCE" "$c" 2>&1 | grep -cE "$TOKEN_SHAPE")
  n=${n:-0}
  if [ "$n" -gt 0 ]; then no "$c: $n token-shaped string(s) in its log"; fi
  total=$((total + n))
done <<<"$LIST"
if [ "$total" = 0 ]; then ok "0 token-shaped strings in the logs"; else no "$total token-shaped string(s) in the logs in all"; fi

echo
echo "verify-switches: $pass passed, $fail failed"
[ "$fail" = 0 ]
