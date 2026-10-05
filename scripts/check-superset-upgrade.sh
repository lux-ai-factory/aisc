#!/usr/bin/env bash
# Check that the results dashboard's plugin tiles still work on a Superset image, before upgrading to it
# (docs/superpowers/plugin-dashboards-2026-10-04, T8).
#
#   scripts/check-superset-upgrade.sh [superset image]      # default: the stack's (apps/results-dashboard/Dockerfile)
#   scripts/check-superset-upgrade.sh --break [image]       # also proves it fails: a dataset column removed
#
# In throwaway containers only (aisc-t-sup-*, on their own network, removed at the end, whatever happens):
#   - Postgres with one project database, the results of two Data Drift runs and one LangBiTe run
#     (scripts/fixtures/superset_upgrade/project.sql);
#   - Redis, the dashboard's cache;
#   - the given Superset image with the stack's three extra packages (as apps/results-dashboard/Dockerfile),
#     the real superset_config.py and aisc_ext mounted.
# Then scripts/superset_upgrade_check.py registers the project through the bridge, syncs both plugins with
# their real default charts (scripts/fixtures/superset_upgrade/visualizations.json), opens every tile in a
# browser, and checks a person's chart survives a re-sync. Exit 0: all held. Non-zero: the failing chart is named.
# Needs docker and uv; the browser is the stack's own Playwright Chromium or /usr/bin/google-chrome.
set -euo pipefail

BREAK=0
if [[ "${1:-}" == "--break" ]]; then BREAK=1; shift; fi
# the stack's image unless one is given: the FROM of apps/results-dashboard/Dockerfile
IMAGE="${1:-$(sed -n 's/^FROM //p' "$(dirname "$0")/../apps/results-dashboard/Dockerfile" | head -1)}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DASH="$ROOT/apps/results-dashboard"
FIX="$ROOT/scripts/fixtures/superset_upgrade"
TAG="$(openssl rand -hex 4)"
NET="aisc-t-sup-net-$TAG"; PG="aisc-t-sup-pg-$TAG"; REDIS="aisc-t-sup-redis-$TAG"; SUP="aisc-t-sup-$TAG"
BUILT="aisc-t-sup-image:$TAG"
WORK="$(mktemp -d)"
cleanup() {
  docker rm -f "$SUP" "$PG" "$REDIS" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  docker rmi "$BUILT" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

say() { printf '== %s\n' "$*"; }
free_port() { python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])'; }

say "image: $IMAGE"
sed "s#^FROM .*#FROM $IMAGE#" "$DASH/Dockerfile" > "$WORK/Dockerfile"
docker build -q -t "$BUILT" -f "$WORK/Dockerfile" "$WORK" >/dev/null

RO_PW="$(openssl rand -hex 12)"; PG_PW="$(openssl rand -hex 12)"; ADMIN_PW="$(openssl rand -hex 12)"
TOKEN="$(openssl rand -hex 24)"; SECRET="$(openssl rand -hex 32)"
PID="9e0c1d2a-3b4c-4d5e-8f60-718293a4b5c6"; HEX="${PID//-/}"
docker network create "$NET" >/dev/null
docker run -d --rm --name "$PG" --network "$NET" -e POSTGRES_USER=aisc-postgres-user -e POSTGRES_PASSWORD="$PG_PW" \
  -e POSTGRES_DB=platform postgres:15-alpine >/dev/null
docker run -d --rm --name "$REDIS" --network "$NET" redis:7-alpine >/dev/null
until docker exec "$PG" pg_isready -q -U aisc-postgres-user -d platform; do sleep 1; done; sleep 2
docker exec "$PG" psql -q -v ON_ERROR_STOP=1 -U aisc-postgres-user -d platform -c "CREATE DATABASE project_$HEX" >/dev/null
# Superset's own data in Postgres, as on the stack (SUPERSET_DB_URI in docker-compose.development.yml): the
# tile sync's project lock is a Postgres advisory lock, which SQLite would not exercise.
docker exec "$PG" psql -q -v ON_ERROR_STOP=1 -U aisc-postgres-user -d platform -c "CREATE DATABASE superset" >/dev/null
docker exec -i "$PG" psql -q -v ON_ERROR_STOP=1 -U aisc-postgres-user -d "project_$HEX" -v ro_password="$RO_PW" \
  < "$FIX/project.sql" >/dev/null
say "project database ready"

PORT="$(free_port)"
docker run -d --rm --name "$SUP" --network "$NET" -p "127.0.0.1:$PORT:8088" \
  -e SUPERSET_SECRET_KEY="$SECRET" -e SUPERSET_GUEST_TOKEN_SECRET="$(openssl rand -hex 32)" -e SUPERSET_DB_URI="postgresql+psycopg2://aisc-postgres-user:$PG_PW@$PG:5432/superset" \
  -e REDIS_HOST="$REDIS" -e AISC_AUDIT_ENABLED=false -e LEDGER_MODE=off \
  -e DASHBOARD_BRIDGE_TOKEN="$TOKEN" -e DASHBOARD_RO_PASSWORD="$RO_PW" -e AISC_PROJECT_DB_HOSTPORT="$PG:5432" \
  -v "$DASH/superset_config.py:/app/pythonpath/superset_config.py:ro" -v "$DASH/aisc_ext:/app/pythonpath/aisc_ext:ro" \
  "$BUILT" sh -c "superset db upgrade >/tmp/upgrade.log 2>&1 && \
    superset fab create-admin --username admin --firstname a --lastname b --email admin@aisc.invalid \
      --password '$ADMIN_PW' >/tmp/admin.log 2>&1 && superset init >/tmp/init.log 2>&1 && /usr/bin/run-server.sh" >/dev/null
for _ in $(seq 1 120); do
  curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
  if ! docker ps -q --filter "name=$SUP" | grep -q .; then echo "Superset stopped while starting"; exit 1; fi
  sleep 2
done
curl -sf "http://127.0.0.1:$PORT/health" >/dev/null || { echo "Superset did not answer"; docker logs --tail 40 "$SUP"; exit 1; }
say "Superset up on 127.0.0.1:$PORT"

CHROME="${AISC_CHROME:-/usr/bin/google-chrome}"
status=0
uv run -q --with playwright --with requests python "$ROOT/scripts/superset_upgrade_check.py" \
  --url "http://127.0.0.1:$PORT" --container "$SUP" --pid "$PID" --token "$TOKEN" --admin-password "$ADMIN_PW" \
  --fixture "$FIX/visualizations.json" --chrome "$CHROME" $([[ $BREAK == 1 ]] && echo --break) || status=$?
if [[ $status != 0 ]]; then
  say "Superset's last errors"
  # the extension's errors only (the stock image lacks the branding logo: those 404s are expected here)
  docker logs "$SUP" 2>&1 | grep -v -E "SAWarning|cache_ok" | grep -A30 -E "^Traceback|ERROR" \
    | grep -v -E "NotFound|send_static_file|send_from_directory|static/assets" | grep -B4 -A2 -E "aisc_ext|Error|error" | tail -50 || true
fi
exit $status
