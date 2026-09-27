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
# No module keeps a sign-in of its own: the gateway holds the one session and
# passes its token on, and sections 2d, 3 and 4 assert that the engine and the
# dashboard take who is signed in from it.
set -uo pipefail
J=$(mktemp); trap 'rm -f "$J"' EXIT
U=${KC_USER:-user}; P=${KC_PASS:-user}
KC=${KEYCLOAK_URL:-http://localhost:8081}
pass=0; fail=0
ok(){ printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
no(){ printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }
token_for(){ # user password -> an access token for the engine's client, or nothing
  curl -s --max-time 15 -d 'client_id=aisc-webapp' -d 'grant_type=password' \
       -d "username=$1" -d "password=$2" -d 'scope=openid' \
       "$KC/realms/aisc/protocol/openid-connect/token" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("access_token",""))' 2>/dev/null
}

echo "1. one Keycloak login, at the launcher"
page=$(curl -s -c "$J" -b "$J" -L --max-time 25 http://localhost:8100/)
form=$(printf '%s' "$page" | grep -oE 'action="[^"]+"' | head -1 | sed 's/action="//;s/"$//' | sed 's/&amp;/\&/g')
[ -n "$form" ] && ok "Keycloak served the sign-in form" || no "no sign-in form"
code=$(curl -s -c "$J" -b "$J" -L --max-time 25 -o /dev/null -w '%{http_code}' \
   --data-urlencode "username=$U" --data-urlencode "password=$P" "$form")
[ "$code" = "200" ] && ok "signed in, landed on the launcher (200)" || no "login landed $code"

# The project is chosen once, on the launcher, and every module is then entered
# for that project. So the modules are checked where they are actually used:
# inside a project, whose pid comes from the platform on this same session.
PROJECT=$(curl -s -b "$J" --max-time 15 http://localhost:8100/api/projects \
          | python3 -c 'import json,sys; print((json.load(sys.stdin) or [{}])[0].get("pid",""))' 2>/dev/null)
[ -n "$PROJECT" ] && ok "the platform has a project to work in" || no "no project on the platform"

echo "2. every module on that same session, with no further login"
for e in "launcher|http://localhost:8100/|AI Assessment Sandbox Configurator" \
         "execution engine|http://localhost/?project=$PROJECT|AI Assessment Sandbox" \
         "qualification|http://localhost/qualification/p/$PROJECT|qualification" \
         "controls|http://localhost/controls/p/$PROJECT/checklists|checklist" \
         "control objectives|http://localhost/control-objectives/p/$PROJECT/projects|objectives" \
         "catalogue|http://localhost:8102/|AI Factory Sandbox Configurator"; do
  n=$(echo "$e" | cut -d'|' -f1); u=$(echo "$e" | cut -d'|' -f2); m=$(echo "$e" | cut -d'|' -f3)
  body=$(curl -s -b "$J" -c "$J" -L --max-time 30 "$u")
  eff=$(curl -s -b "$J" -c "$J" -L --max-time 30 -o /dev/null -w '%{url_effective}' "$u")
  code=$(curl -s -b "$J" -c "$J" -L --max-time 30 -o /dev/null -w '%{http_code}' "$u")
  # The status too, not only the words on the page: a Next.js error page says
  # 500 while still carrying the app's own name, which let two apps sit broken
  # behind a check that read the body alone.
  if [ "$code" != "200" ]; then
    no "$n -> $code"
    continue
  fi
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

echo "2b. and a module reached without a project sends you where one is chosen"
for e in "qualification|http://localhost/qualification" \
         "controls|http://localhost/controls" \
         "control objectives|http://localhost/control-objectives/"; do
  n=${e%%|*}; u=${e#*|}
  loc=$(curl -s -b "$J" --max-time 20 -o /dev/null -D - "$u" | grep -i '^location:' | head -1 | tr -d '\r')
  case "$loc" in
    *8100*) ok "$n -> the launcher, not a second project list" ;;
    *) no "$n -> ${loc:-no redirect}: it is deciding the project itself" ;;
  esac
done

echo "2c. and every tool has a Back to the project it was entered from"
# The project page on the launcher is where the six steps are, so each tool
# carries a link to it rather than leaving the reader to the browser's back
# button. Matched on what it points at and on its label, not on wording alone.
# The engine is a single-page app whose page is an empty div until React runs,
# so it is checked in its bundle below rather than in its HTML.
for e in "qualification|http://localhost/qualification/p/$PROJECT" \
         "controls|http://localhost/controls/p/$PROJECT/checklists" \
         "control objectives|http://localhost/control-objectives/p/$PROJECT/projects"; do
  n=${e%%|*}; u=${e#*|}
  body=$(curl -s -b "$J" -L --max-time 30 "$u")
  case "$body" in
    *"Back to the project"*) ;;
    *) no "$n has no Back to the project"; continue ;;
  esac
  case "$body" in
    *"/p/$PROJECT"*) ok "$n has a Back to this project's page" ;;
    *) no "$n has a Back that does not point at this project" ;;
  esac
done
bundle=$(docker exec aisc-webapp sh -c 'cat /usr/share/nginx/html/assets/*.js' | tr -d '\n')
case "$bundle" in
  *"Back to the project"*) ok "the engine's bundle carries the Back" ;;
  *) no "the engine's bundle has no Back to the project" ;;
esac
case "$bundle" in
  *APP_LAUNCHER_URL*) no "the engine's launcher URL is still the placeholder" ;;
  *) ok "and its launcher URL is substituted, not a placeholder" ;;
esac

echo "2d. the gateway is the only session (wave 1)"
# Every request already passes through oauth2-proxy, which holds a session it
# refreshes. Nothing behind it should keep a second session of its own: the
# engine's page does, which is why it dies after the realm's 30 idle minutes
# while every other module keeps working, and why an install fails with 401s.
#
# What that costs to fix is config: oauth2-proxy passes the token it already
# has, Caddy copies that header onto the proxied request, and the engine's page
# stops holding one. These assertions describe that end state.
cmd=$(docker inspect oauth2-proxy --format '{{json .Config.Cmd}}' 2>/dev/null)
case "$cmd" in
  *pass-access-token*) ok "the gateway passes the token it holds to what it protects" ;;
  *) no "the gateway keeps its token to itself: what it protects has to find its own" ;;
esac
case "$(grep -A 12 '(protect)' Caddyfile 2>/dev/null)" in
  *X-Auth-Request-Access-Token*) ok "and the gateway's proxy copies it onto the request" ;;
  *) no "forward_auth does not copy the token header, so it never arrives" ;;
esac
case "$cmd" in
  *cookie-refresh*) ok "and it refreshes that session while someone is working" ;;
  *) no "the gateway never refreshes its session, so the realm drops it mid-work" ;;
esac
# The engine verifies what it is handed rather than taking the gateway's word.
who=$(curl -s -b "$J" --max-time 20 http://localhost/api/v1/me)
case "$who" in
  *'"auth_disabled": true'*) no "the engine is not verifying tokens at all (auth disabled)" ;;
  *'"username": "'*) ok "the engine verifies the token and knows who it is (${who:0:40}...)" ;;
  *) no "the engine could not say who this is: ${who:0:60}" ;;
esac
case "$who" in
  *primary-user*|*admin*) ok "and the roles survive the handover" ;;
  *) no "the roles are lost on the way: role-gated endpoints would refuse an admin" ;;
esac
# The observable end of it: a signed-in browser, holding only the gateway's
# cookie and no token of its own, can use the engine's API.
c=$(curl -s -b "$J" -o /dev/null -w '%{http_code}' --max-time 20 http://localhost/api/v1/projects)
[ "$c" = "200" ] && ok "a session with no token of its own can read the engine's API ($c)" \
  || no "the engine's API refuses a gateway session that holds no token ($c)"
# And nothing may reach it without going through the gateway at all.
c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 http://localhost/api/v1/projects)
case "$c" in
  200) no "the engine's API answered an anonymous request ($c)" ;;
  *) ok "while an anonymous request is still refused ($c)" ;;
esac

echo "2e. nothing is running on a secret anyone can read"
# Values that were once committed to the repo are known to anyone with a clone.
# The worst is the gateway's cookie secret: whoever holds it can mint a session
# cookie for any user, offline, and that cookie is the session every module trusts.
# By fingerprint, not by the values themselves: a check that refuses a secret
# should not be the last place that secret is written down.
#   sha256 of the cookie secret that shipped, and of the client secret
SHIPPED_COOKIE_SHA=68468559c25d06fff2b3653eaf81c2dff9dc1069f6e58be81c326fca91392d5e
SHIPPED_CLIENT_SHA=73ce74bda63a34da96e9cf3e53562c1a36c487e57498d402a961313e4340717a
flag(){ printf '%s' "$1" | sha256sum | cut -d' ' -f1; }
gateway_flag(){ # name -> the value oauth2-proxy runs with for --<name>
  docker inspect oauth2-proxy --format '{{range .Config.Cmd}}{{println .}}{{end}}' 2>/dev/null \
    | sed -n "s/^--$1=//p" | head -1
}
running_cookie=$(gateway_flag cookie-secret)
running_client=$(gateway_flag client-secret)
[ "$(flag "$running_cookie")" != "$SHIPPED_COOKIE_SHA" ] \
  && ok "the gateway's cookie secret is not the one that was in the repo" \
  || no "the gateway is running on the cookie secret that was in the repo"
[ "$(flag "$running_client")" != "$SHIPPED_CLIENT_SHA" ] \
  && ok "nor its client secret" \
  || no "the gateway is running on the client secret that was in the repo"
# And the repo carries none of them, defaults included.
if grep -rqE "(GATEWAY_COOKIE_SECRET|GATEWAY_CLIENT_SECRET|DASHBOARD_OIDC_CLIENT_SECRET|CATALOGUE_INSTALL_TOKEN|DJANGO_SECRET_KEY|INTERNAL_API_KEY)=[^$#[:space:]]" \
     env.development env.plugin_downloader env.staging 2>/dev/null; then
  no "a secret is still written in a tracked env file"
else
  ok "and no tracked env file carries one"
fi
# A variable whose NAME says it holds a secret, with a non-empty default.
# `${MISTRAL_API_KEY:-}` is the right shape: no key, and no pretending there is
# one. _PASSWORD belongs here too: leaving it out is how a Superset signing key
# and two database passwords sat in a submodule's own compose unnoticed, and
# every compose file in the install is read, not only the two at the top.
if grep -rqE '\$\{[A-Za-z_]*(PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY|_KEY|CREDENTIALS?)[A-Za-z_]*:-[^}[:space:]]' \
     docker-compose.development.yml docker-compose-infra.development.yml \
     apps/*/docker-compose*.yml apps/*/*/docker-compose*.yml 2>/dev/null; then
  no "compose still falls back to a shipped secret"
else
  ok "and compose refuses to start rather than falling back to one"
fi

echo "3. the engine has no login of its own"
# The webapp runs no Keycloak client of its own (no keycloak-js, no check-sso):
# it asks the API who the gateway says this is, and signs in and out there.
js=$(curl -s -b "$J" --max-time 20 http://localhost/ | grep -oE '/assets/[^"]+\.js' | head -1)
bundle=$(curl -s -b "$J" --max-time 20 "http://localhost$js")
case "$bundle" in
  *silent-check-sso*|*onTokenExpired*|*aisc-webapp*) no "the engine's page still carries a Keycloak client of its own" ;;
  *) ok "the engine's page has no Keycloak client of its own" ;;
esac
for path in /admin/ /_allauth/browser/v1/config; do
  c=$(docker exec caddy wget -qSO /dev/null "http://aisc-backend:8000$path" 2>&1 | grep -oE 'HTTP/[0-9.]+ [0-9]+' | tail -1)
  case "$c" in
    *404) ok "the engine backend has no $path ($c)" ;;
    *) no "the engine backend still answers $path (${c:-no answer})" ;;
  esac
done

echo "4. the dashboard is behind the gateway, with no login of its own"
# Superset takes who is signed in from the gateway (dashboard-gateway/): no
# Keycloak client of its own, no password login, and not reachable around Caddy.
loc=$(curl -s --max-time 20 -o /dev/null -D - http://localhost:8188/ | grep -i '^location:' | head -1)
case "$loc" in
  */oauth2/start*) ok "signed out, the dashboard sends you to the gateway" ;;
  *) no "signed out, the dashboard went to: ${loc:-its own page}" ;;
esac
out=$(curl -s -b "$J" -c "$J" -L --max-time 30 -w '\n__URL__%{url_effective}' http://localhost:8188/)
eff=$(printf '%s' "$out" | tail -1)
shopt -s nocasematch
case "$out" in
  *'sign in with keycloak'*|*'name="username"'*|*'name="password"'*) no "the dashboard still asked for a sign-in" ;;
  *) ok "the dashboard opened on that one session, no sign-in screen" ;;
esac
shopt -u nocasematch
case "$eff" in
  *localhost:8188/superset/welcome*) ok "and landed on Superset's own page ($eff)" ;;
  *) no "landed at: $eff" ;;
esac
c=$(curl -s -b "$J" --max-time 20 -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"x","provider":"db"}' http://localhost:8188/api/v1/security/login)
[ "$c" = "404" ] && ok "Superset's password login is gone (404)" || no "Superset's password login answered $c"
listen=$(ss -tln 2>/dev/null | awk '{print $4}' | grep -E ":${DASHBOARD_INTERNAL_PORT:-8189}$" | sort -u | tr '\n' ' ')
case "$listen" in
  *0.0.0.0:*|*'[::]:'*|*'*:'*) no "Superset itself listens on every interface: $listen" ;;
  '') no "Superset is not listening on ${DASHBOARD_INTERNAL_PORT:-8189}" ;;
  *) ok "Superset itself listens only on the Docker host address ($listen)" ;;
esac

echo "5. nothing is reachable without going through the gateway"
# Asked of THIS install's containers, not of the host: other stacks on the same
# machine may well be publishing these ports, and that says nothing about
# whether ours does.
for e in "control objectives|control-objectives|8090" "immudb console|immudb|8086"; do
  n=$(echo "$e" | cut -d'|' -f1)
  container=$(echo "$e" | cut -d'|' -f2)
  port=$(echo "$e" | cut -d'|' -f3)
  published=$(docker inspect "$container" \
                --format "{{range \$p, \$conf := .NetworkSettings.Ports}}{{if \$conf}}{{\$p}} {{end}}{{end}}" 2>/dev/null)
  case "$published" in
    *"$port"*) no "$n publishes :$port itself" ;;
    *) ok "$n publishes no port of its own" ;;
  esac
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
  page=$(curl -s -b "$J" --max-time 15 "http://localhost:8100/p/$slug")
  n=$(printf '%s' "$page" | grep -c 'class="card')
  [ "$n" = "6" ] && ok "a project page carries the six steps ($slug)" || no "project page has $n cards"
  case "$page" in
    *'aria-label="Back to the projects"'*) ok "and a Projects button back to the list" ;;
    *) no "the project page has no way back to the projects" ;;
  esac
else
  no "no project to open"
fi
c=$(curl -s -b "$J" -o /dev/null -w '%{http_code}' --max-time 15 -H 'Content-Type: application/json' -d '{"name":"!!! ???"}' http://localhost:8100/api/projects)
[ "$c" = "422" ] && ok "a name with no usable handle is refused, not guessed (422)" || no "unusable name -> $c"

echo "7. installing a plugin goes through the engine, not a second door"
# The catalogue emits web+aiscplugin:// links; the engine catches them, shows a
# project dropdown and posts to its own endpoint. So what has to exist is: the
# engine's install endpoint, its project list, and no bespoke door.
# The role checks below send an access token of their own, so that the answer
# is about the account named, not about whoever the session belongs to.
TOK=$(token_for "$U" "$P")
[ -n "$TOK" ] && ok "the realm issues an access token for the engine's client" || no "no access token from the realm"

c=$(curl -s -b "$J" -H "Authorization: Bearer $TOK" -o /dev/null -w '%{http_code}' --max-time 20 http://localhost/api/v1/projects)
[ "$c" = "200" ] && ok "the engine lists projects for the dialog's dropdown (200)" || no "GET /api/v1/projects -> $c"

# Installing puts code on the server, so it takes the admin role. The dialog is
# the same dialog for everybody; what changes is who it works for, which is
# asserted in both directions here and in full in verify-rbac.sh.
ADMIN_TOK=$(token_for admin admin)
install_as() {
  curl -s -b "$J" -H "Authorization: Bearer $1" -o /dev/null -w '%{http_code}' --max-time 30 \
    -X POST -H 'Content-Type: application/json' \
    -d '{"package_name":"x","version":"1.0.0","project_uuid":"00000000-0000-0000-0000-000000000000"}' \
    http://localhost/api/v1/plugins
}
c=$(install_as "$ADMIN_TOK")
# 404: no such project on a virgin install, which means it got past auth and
# schema into the engine's own logic, exactly as the dialog would.
case "$c" in
  404|400|422|200|201) ok "the engine's own POST /api/v1/plugins accepts the dialog's payload ($c)" ;;
  401|403) no "POST /api/v1/plugins refused an admin ($c)" ;;
  *) no "POST /api/v1/plugins -> $c" ;;
esac
if [ "$U" = "admin" ]; then
  ok "signed in as admin, so the install above was the ordinary path"
else
  c=$(install_as "$TOK")
  [ "$c" = "403" ] && ok "and refuses an account that may not install code (403)" \
    || no "an ordinary account's install was not refused: $c"
fi

# A session that carries no token of its own is still a signed-in user: the
# gateway holds the session and passes the token, so the call is served. What
# must be refused is a call carrying neither, which is asserted in section 2d.
c=$(curl -s -b "$J" -o /dev/null -w '%{http_code}' --max-time 20 http://localhost/api/v1/projects)
[ "$c" = "200" ] && ok "and serves the same call on the gateway's session alone (200)" \
  || no "a signed-in session was refused: /api/v1/projects -> $c"
# The engine's "Public Catalogue" button reads a placeholder that env.sh
# replaces at container start; unset, it opens the literal string.
docker exec aisc-webapp sh -c 'grep -qoh "APP_CATALOG_URL" /usr/share/nginx/html/assets/*.js' 2>/dev/null \
  && no "the engine's catalogue link is still the unsubstituted placeholder" \
  || ok "the engine's catalogue link is substituted, not a placeholder"
docker exec aisc-webapp sh -c "grep -qoh '${CATALOGUE_EXTERNAL_URL:-http://localhost:8102}' /usr/share/nginx/html/assets/*.js" 2>/dev/null \
  && ok "and it points at this install's catalogue" \
  || no "the catalogue URL is not in the engine's bundle"

# With an admin token, so the catalogue's own guard on writes is not what
# answers: a 404 then means there is no such route, which is the point.
c=$(curl -s -b "$J" -H "Authorization: Bearer $ADMIN_TOK" -o /dev/null -w '%{http_code}' --max-time 20 \
      -X POST -H 'Content-Type: application/json' -d '{}' \
      "${CATALOGUE_EXTERNAL_URL:-http://localhost:8102}/api/v1/catalogue/install")
[ "$c" = "404" ] && ok "the bespoke install door is gone (404)" || no "the old door still answers ($c)"
info=$(curl -s -b "$J" -L --max-time 20 "${CATALOGUE_EXTERNAL_URL:-http://localhost:8102}/api/tool/langbite/install-info")
printf '%s' "$info" | grep -c '"installable":true' >/dev/null \
  && ok "the catalogue still resolves a test to an installable package" \
  || no "install-info: ${info:0:90}"

echo; echo "passed: $pass  failed: $fail"; [ "$fail" -eq 0 ]
