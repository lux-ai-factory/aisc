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
         "control objectives|http://localhost/control-objectives/|objectives"; do
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
# Flask-AppBuilder with AUTH_OAUTH renders a provider page rather than
# redirecting, so check that the page offers Keycloak and that the provider
# link goes to the SAME Keycloak the gateway used.
page=$(curl -s -b "$J" -c "$J" --max-time 20 http://localhost:8188/login/)
printf '%s' "$page" | grep -qi 'sign in with keycloak' \
  && ok "Superset offers Keycloak, not a username/password form" \
  || no "Superset's login page does not offer Keycloak"
printf '%s' "$page" | grep -qi 'name="username"' \
  && no "Superset is still offering a local username/password form" \
  || ok "no local password form on Superset's login page"
loc=$(curl -s -b "$J" -c "$J" --max-time 20 -o /dev/null -D - http://localhost:8188/login/keycloak | grep -i '^location:' | head -1)
case "$loc" in
  *localhost:8081/realms/aisc*client_id=superset*) ok "its provider link goes to the shared Keycloak as client superset" ;;
  *) no "provider link went to: ${loc:-nowhere}" ;;
esac
loc=$(curl -s -b "$J" -c "$J" --max-time 20 -o /dev/null -D - \
  "$KC/realms/aisc/protocol/openid-connect/auth?client_id=superset&redirect_uri=http%3A%2F%2Flocalhost%3A8188%2Foauth-authorized%2Fkeycloak&response_type=code&scope=openid&prompt=none" \
  | grep -i '^location:' | head -1)
case "$loc" in
  *code=*) ok "prompt=none returned a code for superset: the dashboard logs in silently too" ;;
  *login_required*) no "prompt=none said login_required for superset" ;;
  *) no "prompt=none for superset gave: ${loc:-no redirect}" ;;
esac

echo; echo "passed: $pass  failed: $fail"; [ "$fail" -eq 0 ]
