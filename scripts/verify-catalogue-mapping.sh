#!/usr/bin/env bash
# Every plugin the engine has was installed from a catalogue entry, and says so.
#
#   ./scripts/verify-catalogue-mapping.sh
#
# Discovery lives in the catalogue: the engine lists no packages of its own, so
# an installed distribution only means something if it can be traced back to the
# entry it came from. That link is the `catalogue_slug` recorded on the install.
# This checks the whole chain against the RUNNING stack, not the source tree:
#   the catalogue resolves an entry to a distribution on the index,
#   the page the browser is served puts the entry's slug in the enable URI,
#   the engine's page parses it and posts it,
#   the engine stores it, answers with it, and never forgets it,
#   and the stored slug still resolves back to the same distribution.
#
# It works inside a project of its own, which it deletes afterwards, so it never
# enables or disables anything in a project you are using.
set -uo pipefail
J=$(mktemp); T=$(mktemp); trap 'rm -f "$J" "$T"' EXIT
U=${KC_USER:-user}; P=${KC_PASS:-user}
KC=${KEYCLOAK_URL:-http://localhost:8081}
ENGINE=${ENGINE_URL:-http://localhost}
CATALOGUE=${CATALOGUE_URL:-http://localhost:8102}
SLUG=${ENTRY_SLUG:-langbite}
PGDB=${DB_NAME:-aisc}; PGUSER=${DB_USER:-aisc-postgres-user}
pass=0; fail=0
ok(){ printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
no(){ printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }
py(){ python3 -c "import json,sys
try: d=json.load(sys.stdin)
except Exception: sys.exit(0)
$1"; }
psql_(){ docker exec postgres psql -U "$PGUSER" -d "$PGDB" -At -c "$1"; }
# The JS the browser actually runs, fetched over HTTP the way a browser would.
served_js(){ # $1 = site root
  local page assets out=""
  page=$(curl -s -b "$J" -L --max-time 25 "$1/")
  assets=$(printf '%s' "$page" | grep -oE '(src|href)="[^"]+\.js"' | sed 's/.*="//;s/"$//')
  for a in $assets; do
    case "$a" in http*) out="$out$(curl -s -b "$J" -L --max-time 30 "$a")";;
                     *) out="$out$(curl -s -b "$J" -L --max-time 30 "$1/${a#/}")";; esac
  done
  printf '%s' "$out"
}

echo "0. one sign-in, the same session every call below rides on"
page=$(curl -s -c "$J" -b "$J" -L --max-time 25 "$ENGINE/")
form=$(printf '%s' "$page" | grep -oE 'action="[^"]+"' | head -1 | sed 's/action="//;s/"$//;s/&amp;/\&/g')
[ -n "$form" ] && curl -s -c "$J" -b "$J" -L --max-time 25 -o /dev/null \
  --data-urlencode "username=$U" --data-urlencode "password=$P" "$form"
curl -s --max-time 15 -d 'client_id=aisc-webapp' -d 'grant_type=password' \
  -d "username=$U" -d "password=$P" -d 'scope=openid' \
  "$KC/realms/aisc/protocol/openid-connect/token" | py 'print(d.get("access_token",""))' > "$T"
TOK=$(cat "$T")
[ -n "$TOK" ] && ok "the realm issued an access token" || no "no access token"
api(){ curl -s -b "$J" -H "Authorization: Bearer $TOK" "$@"; }

echo "1. the catalogue resolves an entry to something installable"
INFO=$(docker exec catalogue-backend python -c "
import urllib.request
print(urllib.request.urlopen('http://localhost:8000/tool/$SLUG/install-info', timeout=20).read().decode())")
PKG=$(printf '%s' "$INFO" | py 'print(d.get("package_name",""))')
VER=$(printf '%s' "$INFO" | py 'print(d.get("version") or "")')
[ -n "$PKG" ] && [ -n "$VER" ] && ok "entry \"$SLUG\" is $PKG $VER on the index" \
  || no "no install coordinates for \"$SLUG\": $INFO"

echo "2. the pages the browser is served carry the mapping"
# Matched with `case`, not `grep -q`: on a bundle this size grep exits at the
# first hit, printf takes SIGPIPE, and `pipefail` would report the pipeline as
# failed even though the string is there.
case "$(served_js "$CATALOGUE")" in
  *slug=*) ok "the catalogue's page puts slug= in the enable URI" ;;
  *) no "the catalogue's served page has no slug= in its install URI" ;;
esac
case "$(served_js "$ENGINE")" in
  *catalogue_slug*) ok "the engine's page posts catalogue_slug" ;;
  *) no "the engine's served page never mentions catalogue_slug" ;;
esac

echo "3. an install through the engine's own endpoint records the entry"
NAME="verify-catalogue-mapping-$$"
PROJECT=$(api --max-time 20 -X POST -H 'Content-Type: application/json' \
            -d "{\"name\":\"$NAME\"}" "$ENGINE/api/v1/projects" | py 'print(d.get("pid",""))')
[ -n "$PROJECT" ] && ok "working in a project of its own ($NAME)" || { no "could not create a project"; }
cleanup(){ [ -n "${PROJECT:-}" ] || return 0
  psql_ "delete from aisc_backend_plugin where project_id in
           (select id from aisc_backend_project where pid = '$PROJECT')" >/dev/null
  psql_ "delete from aisc_backend_project where pid = '$PROJECT'" >/dev/null; }
trap 'cleanup; rm -f "$J" "$T"' EXIT
body(){ printf '{"package_name":"%s","version":"%s","project_uuid":"%s"%s}' "$PKG" "$VER" "$PROJECT" "$1"; }
mine(){ psql_ "select distinct catalogue_slug from aisc_backend_plugin p
                 join aisc_backend_project pr on pr.id = p.project_id
                where pr.pid = '$PROJECT'"; }

OUT=$(api --max-time 180 -X POST -H 'Content-Type: application/json' \
        -d "$(body ",\"catalogue_slug\":\"$SLUG\"")" "$ENGINE/api/v1/plugins")
case "$OUT" in
  *"\"catalogue_slug\": \"$SLUG\""*|*"\"catalogue_slug\":\"$SLUG\""*)
    ok "the engine answered with the entry it installed from" ;;
  *) no "install response carries no catalogue_slug: ${OUT:0:200}" ;;
esac
ROW=$(mine)
[ "$ROW" = "$SLUG" ] && ok "and stored it on the row ($ROW)" || no "stored catalogue_slug is \"$ROW\", wanted \"$SLUG\""

echo "4. an install with no origin neither invents one nor erases one"
api --max-time 180 -X POST -H 'Content-Type: application/json' -d "$(body "")" "$ENGINE/api/v1/plugins" >/dev/null
ROW=$(mine)
[ "$ROW" = "$SLUG" ] && ok "the known origin survived an install that carried none" \
  || no "the origin became \"$ROW\" after an install without one"

echo "5. the stored slug is a real catalogue entry, not free text"
BACK=$(docker exec catalogue-backend python -c "
import urllib.request
print(urllib.request.urlopen('http://localhost:8000/tool/$ROW/install-info', timeout=20).read().decode())" 2>/dev/null)
case "$BACK" in
  *"\"package_name\":\"$PKG\""*) ok "\"$ROW\" resolves in the catalogue to the same distribution" ;;
  *) no "\"$ROW\" does not resolve back to $PKG: ${BACK:0:120}" ;;
esac

echo "6. and it leaves nothing behind"
cleanup
LEFT=$(psql_ "select count(*) from aisc_backend_project where pid = '$PROJECT'")
PROJECT=""
[ "$LEFT" = "0" ] && ok "its own project and rows are gone" || no "$LEFT project row(s) left behind"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
