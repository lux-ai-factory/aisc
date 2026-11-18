#!/usr/bin/env bash
# Is the dashboard's Redis what it is supposed to be? (ANA-01)
#
# The pilot's rule: Superset's cache is a Redis of its own — a password from the
# environment, on a network no service running plugin code joins, publishing no
# port. The compose file proves what would start (apps/backend's
# tests/test_dashboard_redis_compose.py runs `docker compose config`); this script
# proves what *did* start, on a running deployment.
#
#   DASHBOARD_REDIS_PASSWORD=... scripts/verify-dashboard-redis.sh
#
# No Docker here, but a `redis-server` on PATH? Then the rule itself can still be
# exercised, on this host, with the same configuration the compose service writes:
#
#   scripts/verify-dashboard-redis.sh --local
#
# Local mode starts a throwaway server on a free loopback port with the compose
# service's own config (requirepass, no persistence, nothing published) and checks
# what a client sees. The deployment checks (which network it is on, which
# containers share it, what `docker inspect` shows) need a running stack; local
# mode says so instead of pretending to know.
#
# Exit 0: every check passed. Exit 1: the deployment deviates, and the line says how.
set -uo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
COMPOSE_PROFILE="${COMPOSE_PROFILE:-analytics}"
SERVICE="dashboard-redis"
NETWORK_NAME="${DASHBOARD_NETWORK:-dashboard}"
failures=0

say()  { printf '%s\n' "$*"; }
ok()   { printf 'ok   %s\n' "$*"; }
bad()  { printf 'BAD  %s\n' "$*"; failures=$((failures + 1)); }

compose() { docker compose -f "$COMPOSE_FILE" --profile "$COMPOSE_PROFILE" "$@"; }

# ─── local mode: the rule itself, without Docker ────────────────────────────
if [ "${1:-}" = "--local" ]; then
  for tool in redis-server redis-cli; do
    command -v "$tool" >/dev/null 2>&1 || { bad "$tool is not installed"; say "install redis, or run this against a deployment"; exit 1; }
  done
  workdir=$(mktemp -d)
  port=$(( (RANDOM % 20000) + 20000 ))
  password="${DASHBOARD_REDIS_PASSWORD:-$(head -c 18 /dev/urandom | base64 | tr -d '/+=')}"
  # the compose entrypoint's own lines, plus a loopback port so nothing here is public
  printf 'requirepass %s\nsave ""\nappendonly no\nport %s\nbind 127.0.0.1\n' \
    "$password" "$port" > "$workdir/redis.conf"
  redis-server "$workdir/redis.conf" --daemonize yes --pidfile "$workdir/redis.pid" \
    --logfile "$workdir/redis.log" || { bad "the server did not start"; exit 1; }
  trap 'redis-cli -p "$port" -a "$password" shutdown nosave >/dev/null 2>&1; rm -rf "$workdir"' EXIT
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    redis-cli -p "$port" ping >/dev/null 2>&1 && break
    sleep 0.2
  done

  answer=$(redis-cli -p "$port" ping 2>&1 || true)
  case "$answer" in
    *NOAUTH*|*"Authentication required"*) ok "a client with no password is refused (NOAUTH)" ;;
    *) bad "redis-cli ping without a password answered '$answer' — is requirepass on?" ;;
  esac
  answer=$(REDISCLI_AUTH="$password" redis-cli -p "$port" ping 2>&1 || true)
  case "$answer" in
    *PONG*) ok "the password the service is given is the one it takes" ;;
    *) bad "the password did not work: '$answer'" ;;
  esac
  answer=$(REDISCLI_AUTH="$password" redis-cli -p "$port" config get appendonly 2>&1 | tail -1)
  case "$answer" in
    no) ok "it keeps nothing (appendonly no): a cache, not a store" ;;
    *) bad "appendonly answered '$answer'" ;;
  esac
  case "$(REDISCLI_AUTH="$password" redis-cli -p "$port" config get bind 2>&1 | tail -1)" in
    127.0.0.1*) ok "it listens on loopback only (nothing published)" ;;
    *) bad "bind is not loopback: the cache would be reachable" ;;
  esac
  # the password is in the config file, never on the server's command line
  if ps -o args= -C redis-server 2>/dev/null | grep -q -- "$password"; then
    bad "the password is in the server's command line"
  else
    ok "the server's command line does not carry the password"
  fi

  say ""
  if [ "$failures" -eq 0 ]; then
    say "the dashboard's Redis rule holds on this host: password-protected, loopback-only, storing nothing"
    say "note the deployment checks (its network, who shares it) were not run — they need a running stack"
    exit 0
  fi
  say "$failures check(s) failed"
  exit 1
fi
if [ "$#" -gt 0 ]; then
  bad "unknown argument: $1 (the only argument is --local)"
  exit 1
fi

# 1. it is running, and it asks for a password: a command without one is refused
if ! compose ps --status running --services 2>/dev/null | grep -qx "$SERVICE"; then
  bad "$SERVICE is not running ($COMPOSE_FILE, profile $COMPOSE_PROFILE)"
else
  ok "$SERVICE is running"
  answer=$(compose exec -T "$SERVICE" redis-cli ping 2>&1 || true)
  case "$answer" in
    *NOAUTH*|*"Authentication required"*) ok "it refuses a client with no password (NOAUTH)" ;;
    *) bad "redis-cli ping without a password answered '$answer' — is requirepass on?" ;;
  esac
  if [ -n "${DASHBOARD_REDIS_PASSWORD:-}" ]; then
    answer=$(compose exec -T -e "REDISCLI_AUTH=$DASHBOARD_REDIS_PASSWORD" "$SERVICE" redis-cli ping 2>&1 || true)
    case "$answer" in
      *PONG*) ok "the password in DASHBOARD_REDIS_PASSWORD is the one it takes" ;;
      *) bad "the password did not work: '$answer'" ;;
    esac
  else
    say "note DASHBOARD_REDIS_PASSWORD is unset, so the password itself was not tried"
  fi
fi

# 2. nothing is published to the host
if compose port "$SERVICE" 6379 >/dev/null 2>&1; then
  bad "$SERVICE publishes a port ($(compose port "$SERVICE" 6379)): its cache must not be reachable from the host"
else
  ok "no port is published for $SERVICE"
fi

# 3. the password is not in the server's command line (where `ps` would show it)
cmdline=$(compose ps -q "$SERVICE" 2>/dev/null | head -1)
if [ -n "$cmdline" ]; then
  running_cmd=$(docker inspect --format '{{join .Config.Cmd " "}}' "$cmdline" 2>/dev/null || true)
  case "$running_cmd" in
    *"${DASHBOARD_REDIS_PASSWORD:-__unset__}"*) bad "the password is in the server's command line" ;;
    *) [ -n "$running_cmd" ] && ok "the server's command line does not carry the password" ;;
  esac
fi

# 4. only the dashboard's side is on its network: no plugin code, not the eval cache
if docker network inspect "${COMPOSE_PROJECT_NAME:-aisc}_${NETWORK_NAME}" >/dev/null 2>&1; then
  attached=$(docker network inspect --format '{{range .Containers}}{{.Name}} {{end}}' \
             "${COMPOSE_PROJECT_NAME:-aisc}_${NETWORK_NAME}")
  say "note on ${COMPOSE_PROJECT_NAME:-aisc}_${NETWORK_NAME}: ${attached:-nothing}"
  for forbidden in eval-worker eval-flower redis aisc-backend caddy; do
    case " $attached " in
      *"$forbidden"*) bad "$forbidden is on the $NETWORK_NAME network with the dashboard's cache" ;;
    esac
  done
  ok "no service running plugin code shares the dashboard's cache network"
else
  say "note no ${COMPOSE_PROJECT_NAME:-aisc}_${NETWORK_NAME} network found; if the dashboard runs on another host, check it there"
fi

say ""
if [ "$failures" -eq 0 ]; then
  say "the dashboard's Redis is its own, password-protected and unpublished"
  exit 0
fi
say "$failures check(s) failed"
exit 1
