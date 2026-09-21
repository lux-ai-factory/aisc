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
    *) # `case`, not `grep -q`: grep exits at the first hit, printf takes
       # SIGPIPE, and `pipefail` would then call a found string a failure.
       shopt -s nocasematch
       case "$body" in
         *"$m"*) ok "$n -> served the app (matched \"$m\")" ;;
         *) no "$n -> 200 but no \"$m\" in the body" ;;
       esac
       shopt -u nocasematch ;;
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
shopt -s nocasematch
case "$out" in
  *'sign in with keycloak'*|*'name="username"'*) no "the dashboard still asked for a sign-in" ;;
  *) ok "the dashboard opened on that one session, no sign-in screen" ;;
esac
shopt -u nocasematch
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

echo "6. the platform's projects"
c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 http://localhost:8100/api/projects)
[ "$c" = "302" ] && ok "the projects API is behind the gateway (302 anonymous)" || no "anonymous /api/projects -> $c"
body=$(curl -s -b "$J" --max-time 15 http://localhost:8100/api/projects)
case "$body" in
  *'"slug"'*) ok "it lists projects on a session" ;;
  *) no "projects list: ${body:0:80}" ;;
esac
case "$(curl -s -b "$J" --max-time 15 http://localhost:8100/)" in
  *'<h2>Projects</h2>'*) ok "the launcher is the project list" ;;
  *) no "the launcher is not the project list" ;;
esac
slug=$(printf '%s' "$body" | python3 -c 'import json,sys; print((json.load(sys.stdin) or [{}])[0].get("slug",""))' 2>/dev/null)
if [ -n "$slug" ]; then
  n=$(curl -s -b "$J" --max-time 15 "http://localhost:8100/p/$slug" | grep -c 'class="card')
  [ "$n" = "6" ] && ok "a project page carries the six steps ($slug)" || no "project page has $n cards"
else
  no "no project to open"
fi
c=$(curl -s -b "$J" -o /dev/null -w '%{http_code}' --max-time 15 -H 'Content-Type: application/json' -d '{"name":"!!! ???"}' http://localhost:8100/api/projects)
[ "$c" = "422" ] && ok "a name with no usable handle is refused, not guessed (422)" || no "unusable name -> $c"

echo "7. installing a plugin goes through the engine, not a second door"
# The catalogue emits web+aiscplugin:// links; the engine catches them, shows a
# project dropdown and posts to its own endpoint. So what has to exist is: the
# engine's install endpoint, its project list, and no bespoke door.
# The engine's API wants a Keycloak access token, which the dialog has because
# keycloak-js gave it one. A session cookie alone is not enough, so the check
# takes a token the way the app does.
TOK=$(curl -s --max-time 15 -d 'client_id=aisc-webapp' -d 'grant_type=password' \
        -d "username=$U" -d "password=$P" -d 'scope=openid' \
        "$KC/realms/aisc/protocol/openid-connect/token" \
      | python3 -c 'import json,sys; print(json.load(sys.stdin).get("access_token",""))' 2>/dev/null)
[ -n "$TOK" ] && ok "the realm issues an access token for the engine's client" || no "no access token from the realm"

c=$(curl -s -b "$J" -H "Authorization: Bearer $TOK" -o /dev/null -w '%{http_code}' --max-time 20 http://localhost/api/v1/projects)
[ "$c" = "200" ] && ok "the engine lists projects for the dialog's dropdown (200)" || no "GET /api/v1/projects -> $c"

c=$(curl -s -b "$J" -H "Authorization: Bearer $TOK" -o /dev/null -w '%{http_code}' --max-time 30 \
      -X POST -H 'Content-Type: application/json' \
      -d '{"package_name":"x","version":"1.0.0","project_uuid":"00000000-0000-0000-0000-000000000000"}' \
      http://localhost/api/v1/plugins)
# 404: no such project on a virgin install, which means it got past auth and
# schema into the engine's own logic, exactly as the dialog would.
case "$c" in
  404|400|422|200|201) ok "the engine's own POST /api/v1/plugins accepts the dialog's payload ($c)" ;;
  401|403) no "POST /api/v1/plugins refused the token ($c)" ;;
  *) no "POST /api/v1/plugins -> $c" ;;
esac

c=$(curl -s -b "$J" -o /dev/null -w '%{http_code}' --max-time 20 http://localhost/api/v1/projects)
[ "$c" = "401" ] && ok "and refuses the same call without a token (401)" || no "unauthenticated /api/v1/projects -> $c (want 401)"
# The engine's "Public Catalogue" button reads a placeholder that env.sh
# replaces at container start; unset, it opens the literal string.
docker exec aisc-webapp sh -c 'grep -qoh "APP_CATALOG_URL" /usr/share/nginx/html/assets/*.js' 2>/dev/null \
  && no "the engine's catalogue link is still the unsubstituted placeholder" \
  || ok "the engine's catalogue link is substituted, not a placeholder"
docker exec aisc-webapp sh -c "grep -qoh '${CATALOGUE_EXTERNAL_URL:-http://localhost:8102}' /usr/share/nginx/html/assets/*.js" 2>/dev/null \
  && ok "and it points at this install's catalogue" \
  || no "the catalogue URL is not in the engine's bundle"

c=$(curl -s -b "$J" -o /dev/null -w '%{http_code}' --max-time 20 -X POST -H 'Content-Type: application/json' -d '{}' \
      "${CATALOGUE_EXTERNAL_URL:-http://localhost:8102}/api/v1/catalogue/install")
[ "$c" = "404" ] && ok "the bespoke install door is gone (404)" || no "the old door still answers ($c)"
info=$(curl -s -b "$J" -L --max-time 20 "${CATALOGUE_EXTERNAL_URL:-http://localhost:8102}/api/tool/langbite/install-info")
printf '%s' "$info" | grep -c '"installable":true' >/dev/null \
  && ok "the catalogue still resolves a test to an installable package" \
  || no "install-info: ${info:0:90}"

echo; echo "passed: $pass  failed: $fail"; [ "$fail" -eq 0 ]
