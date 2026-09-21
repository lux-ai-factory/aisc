#!/usr/bin/env bash
# What "one sign-in covers every module" means, as assertions.
#
#   ./scripts/verify-sso.sh            # signs in as user/user
#   KC_USER=admin KC_PASS=admin ./scripts/verify-sso.sh
#
# A bare 200 proves nothing here: following the redirect chain lands on
# Keycloak's own login page, which is also a 200. So each module is checked by
# what it served and where the chain ended, not by its status code.
#
# The last assertion is the one that matters for the execution engine: its SPA
# initialises Keycloak with onLoad "check-sso", which is a prompt=none
# authorization request. If that returns a code, the engine authenticates from
# the gateway's session and never shows its own sign-in page.
set -uo pipefail
J=$(mktemp); trap 'rm -f "$J"' EXIT
U=${KC_USER:-user}; P=${KC_PASS:-user}
KC=${KEYCLOAK_URL:-http://localhost:8081}
pass=0; fail=0
ok(){ printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
no(){ printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }

echo "1. one Keycloak login, at the launcher"
page=$(curl -s -c "$J" -b "$J" -L --max-time 25 http://localhost:8100/)
form=$(printf '%s' "$page" | grep -oE 'action="[^"]+"' | head -1 | sed 's/action="//;s/"$//' | sed 's/&amp;/\&/g')
[ -n "$form" ] && ok "Keycloak served the sign-in form" || no "no sign-in form"
code=$(curl -s -c "$J" -b "$J" -L --max-time 25 -o /dev/null -w '%{http_code}' \
   --data-urlencode "username=$U" --data-urlencode "password=$P" "$form")
[ "$code" = "200" ] && ok "signed in, landed on the launcher (200)" || no "login landed $code"

echo "2. every module on that same session, with no further login"
for e in "launcher|http://localhost:8100/|AI Assessment Sandbox Configurator" \
         "execution engine|http://localhost/|AI Assessment Sandbox" \
         "qualification|http://localhost/qualification|qualification" \
         "controls|http://localhost/controls|controls" \
         "control objectives|http://localhost/control-objectives/|objectives" \
         "catalogue|http://localhost:8102/|AI Factory Sandbox Configurator"; do
  n=$(echo "$e" | cut -d'|' -f1); u=$(echo "$e" | cut -d'|' -f2); m=$(echo "$e" | cut -d'|' -f3)
  body=$(curl -s -b "$J" -c "$J" -L --max-time 30 "$u")
  eff=$(curl -s -b "$J" -c "$J" -L --max-time 30 -o /dev/null -w '%{url_effective}' "$u")
  case "$eff" in
    *:8081*) no "$n -> bounced to Keycloak ($eff)" ;;
    *) printf '%s' "$body" | grep -qi "$m" && ok "$n -> served the app (matched \"$m\")" || no "$n -> 200 but no \"$m\" in the body" ;;
  esac
done

echo "3. the engine's own check-sso finds that session (prompt=none)"
loc=$(curl -s -b "$J" -c "$J" --max-time 20 -o /dev/null -D - \
  "$KC/realms/aisc/protocol/openid-connect/auth?client_id=aisc-webapp&redirect_uri=http%3A%2F%2Flocalhost%2F&response_type=code&scope=openid&prompt=none" \
  | grep -i '^location:' | head -1)
case "$loc" in
  *code=*) ok "prompt=none returned an auth code: the engine authenticates silently" ;;
  *login_required*) no "prompt=none said login_required: the engine would still prompt" ;;
  *) no "prompt=none gave: ${loc:-no redirect}" ;;
esac

echo "4. the dashboard uses the same Keycloak, with its own client"
# Superset authenticates itself, and with one provider its /login/ page would be
# a single button. It is configured to skip that, so the dashboard shows no
# sign-in screen of its own at all.
loc=$(curl -s --max-time 20 -o /dev/null -D - http://localhost:8188/login/ | grep -i '^location:' | head -1)
case "$loc" in
  */login/keycloak*) ok "Superset's login page redirects to the provider, no picker" ;;
  *) no "Superset's /login/ went to: ${loc:-its own page}" ;;
esac
loc=$(curl -s --max-time 20 -o /dev/null -D - http://localhost:8188/login/keycloak | grep -i '^location:' | head -1)
case "$loc" in
  *localhost:8081/realms/aisc*client_id=superset*) ok "and that provider is the shared Keycloak, as client superset" ;;
  *) no "provider route went to: ${loc:-nowhere}" ;;
esac
out=$(curl -s -b "$J" -c "$J" -L --max-time 30 -w '\n__URL__%{url_effective}' http://localhost:8188/)
eff=$(printf '%s' "$out" | tail -1)
printf '%s' "$out" | grep -qi 'sign in with keycloak\|name="username"' \
  && no "the dashboard still asked for a sign-in" \
  || ok "the dashboard opened on that one session, no sign-in screen"
case "$eff" in
  *superset/welcome*) ok "and landed on Superset's own page ($eff)" ;;
  *) no "landed at: $eff" ;;
esac
loc=$(curl -s -b "$J" -c "$J" --max-time 20 -o /dev/null -D - \
  "$KC/realms/aisc/protocol/openid-connect/auth?client_id=superset&redirect_uri=http%3A%2F%2Flocalhost%3A8188%2Foauth-authorized%2Fkeycloak&response_type=code&scope=openid&prompt=none" \
  | grep -i '^location:' | head -1)
case "$loc" in
  *code=*) ok "prompt=none returned a code for superset: the dashboard logs in silently too" ;;
  *login_required*) no "prompt=none said login_required for superset" ;;
  *) no "prompt=none for superset gave: ${loc:-no redirect}" ;;
esac

echo "5. nothing is reachable without going through the gateway"
for e in "control objectives|8090" "immudb console|8086"; do
  n=${e%%|*}; port=${e#*|}
  c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 4 "http://localhost:$port/" 2>/dev/null)
  [ "$c" = "000" ] && ok "$n publishes no port of its own" || no "$n answers on :$port anonymously ($c)"
done
for e in "postgres|5432" "redis|6379" "minio|9000" "immudb|3322" "rabbitmq|5672"; do
  n=${e%%|*}; port=${e#*|}
  docker ps --filter "label=com.docker.compose.project=aisc" --format '{{.Ports}}' | grep -q "127.0.0.1:$port" \
    && ok "$n is bound to the loopback only" || no "$n is not loopback-bound on :$port"
done

echo "6. the catalogue's one-click install door on the engine"
DOOR=${CATALOGUE_EXTERNAL_URL:-http://localhost:8102}/api/v1/catalogue/install
TOKEN=${CATALOGUE_INSTALL_TOKEN:-__CATALOGUE_INSTALL_TOKEN__}
INDEX=${CATALOGUE_INDEX_URL:-http://devpi:3141/root/public/+simple/}
payload() { printf '{"package_name":"langbite","version":"1.1.1","index_url":"%s","project_uuid":"00000000-0000-0000-0000-000000000000"}' "$1"; }

c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -X POST -H 'Content-Type: application/json' -d "$(payload "$INDEX")" "$DOOR")
[ "$c" = "302" ] && ok "without a session the gateway refuses the door (302)" || no "no-session POST -> $c (want 302)"

# the door is served on the catalogue's own origin; the catalogue's own API must
# still answer there, which it only does if the route order is explicit
c=$(curl -s -b "$J" -o /dev/null -w '%{http_code}' --max-time 20 "${CATALOGUE_EXTERNAL_URL:-http://localhost:8102}/api/tool/langbite/install-info")
[ "$c" = "200" ] && ok "the catalogue's own API still answers on that origin (200)" || no "catalogue API on the shared origin -> $c"

c=$(curl -s -b "$J" -o /dev/null -w '%{http_code}' --max-time 20 -X POST -H 'Content-Type: application/json' -d "$(payload "$INDEX")" "$DOOR")
[ "$c" = "401" ] && ok "with a session but no bearer token the door refuses (401)" || no "no-bearer POST -> $c (want 401)"

c=$(curl -s -b "$J" -o /dev/null -w '%{http_code}' --max-time 20 -X POST -H 'Content-Type: application/json' \
      -H "Authorization: Bearer $TOKEN" -d "$(payload http://evil.example/simple/)" "$DOOR")
[ "$c" = "403" ] && ok "an index outside the allowlist is refused (403)" || no "untrusted index -> $c (want 403)"

# With every gate passed it reaches the business logic, which needs a real
# project. On a virgin install there is none, so 404 is the proof of passage.
c=$(curl -s -b "$J" -o /dev/null -w '%{http_code}' --max-time 90 -X POST -H 'Content-Type: application/json' \
      -H "Authorization: Bearer $TOKEN" -d "$(payload "$INDEX")" "$DOOR")
case "$c" in
  404|200|201) ok "token and index accepted: the door reached the engine ($c)" ;;
  *) no "authorised install -> $c (want 404 on a virgin install, or 2xx)" ;;
esac

info=$(curl -s -b "$J" -L --max-time 20 http://localhost:8102/api/tool/langbite/install-info)
printf '%s' "$info" | grep -q '"installable":true' \
  && ok "the catalogue serves an installable descriptor for a test" \
  || no "install-info: ${info:0:90}"

echo; echo "passed: $pass  failed: $fail"; [ "$fail" -eq 0 ]
