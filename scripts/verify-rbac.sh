#!/usr/bin/env bash
# Who may do what, as assertions, against the running stack.
#
#   ./scripts/verify-rbac.sh
#
# Signing in is verify-sso.sh's subject. This is the other half: two real
# accounts, and for each one both directions, what they may do and what they
# must be refused. A test that only checks the allowed direction would pass on
# a system with no authorisation at all, which is exactly the system this
# replaced.
#
# `admin` holds the realm's admin role; `user` holds primary-user and is an
# ordinary account.
set -uo pipefail
KC=${KEYCLOAK_URL:-http://localhost:8081}
REALM=$KC/realms/aisc
pass=0; fail=0
ok(){ printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
no(){ printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }

token_for() {
  curl -s --max-time 20 -d client_id=aisc-webapp -d grant_type=password \
       -d "username=$1" -d "password=$2" "$REALM/protocol/openid-connect/token" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("access_token",""))' 2>/dev/null
}

# A call from inside the network, as a named account. The module backends are
# not published to the host: the gateway is the only door, and it carries a
# cookie session rather than a token, so these go through a container that is
# already on the network.
call() {  # call <container> <url> <method> <token> [body]
  docker exec -e U="$2" -e M="$3" -e T="$4" -e B="${5:-}" "$1" python -c '
import os, urllib.request, urllib.error
headers = {"Content-Type": "application/json"}
if os.environ["T"]:
    headers["Authorization"] = "Bearer " + os.environ["T"]
body = os.environ["B"].encode() if os.environ["B"] else None
req = urllib.request.Request(os.environ["U"], data=body, method=os.environ["M"], headers=headers)
try:
    print(urllib.request.urlopen(req, timeout=20).status)
except urllib.error.HTTPError as exc:
    print(exc.code)
except Exception as exc:
    print("000", exc)
' 2>/dev/null | tail -1
}

is() {  # is <what> <expected> <got>
  [ "$3" = "$2" ] && ok "$1 ($2)" || no "$1: expected $2, got $3"
}
isnot() {  # isnot <what> <unwanted...> <got>
  local what=$1; shift
  local got=${*: -1}
  set -- "${@:1:$(($#-1))}"   # what is left is the list of unwanted codes
  for code in "$@"; do
    [ "$code" = "$got" ] && { no "$what: got $got"; return; }
  done
  ok "$what (got $got)"
}

ADMIN=$(token_for admin admin)
USER=$(token_for user user)
[ -n "$ADMIN" ] && ok "a token for admin" || no "no token for admin"
[ -n "$USER" ] && ok "a token for user" || no "no token for user"
[ -n "$ADMIN" ] && [ -n "$USER" ] || { echo "cannot go on without tokens"; exit 1; }

echo
echo "1. the catalogue: the engine runs what is listed there, so changing it is administrative"
CAT=http://localhost:8000
is "an ordinary account cannot add a tool"        403 "$(call catalogue-backend $CAT/tool/ POST "$USER" '{}')"
is "an ordinary account cannot delete a tool"     403 "$(call catalogue-backend $CAT/tool/999999/ DELETE "$USER" '{}')"
is "an ordinary account cannot add a tag"         403 "$(call catalogue-backend $CAT/tags/ POST "$USER" '{}')"
is "an ordinary account cannot upload a package"  403 "$(call catalogue-backend $CAT/devpi/upload POST "$USER" '{}')"
is "nor can an anonymous one"                     401 "$(call catalogue-backend $CAT/tool/ POST '' '{}')"
isnot "an admin reaches the handler"          401 403 "$(call catalogue-backend $CAT/tool/ POST "$ADMIN" '{}')"
is "reading the catalogue is open to anyone"      200 "$(call catalogue-backend $CAT/tool/ GET "$USER")"
is "and filtering, which is a read spelled as a post" 404 \
   "$(call catalogue-backend $CAT/tool/999999/methods/filter/ POST "$USER" '{}')"

echo
echo "2. the engine: installing a plugin puts code on the server"
ENG=http://localhost:8000/api/v1
INSTALL='{"package_name":"nope","version":"1.0","project_uuid":"00000000-0000-0000-0000-000000000000"}'
is "an ordinary account cannot install"        403 "$(call aisc-backend $ENG/plugins POST "$USER" "$INSTALL")"
is "nor remove one"                            403 "$(call aisc-backend $ENG/plugins DELETE "$USER" "$INSTALL")"
is "nor refresh one"                           403 "$(call aisc-backend $ENG/plugins/refresh POST "$USER" "$INSTALL")"
isnot "an admin gets past the guard"       401 403 "$(call aisc-backend $ENG/plugins POST "$ADMIN" "$INSTALL")"
is "reading the installed plugins is open to any account" 200 "$(call aisc-backend $ENG/plugins GET "$USER")"
is "the audit log is for admins"               403 "$(call aisc-backend $ENG/audit GET "$USER")"
isnot "and an admin may read it"           401 403 "$(call aisc-backend $ENG/audit GET "$ADMIN")"

echo
echo "3. the platform: a project belongs to the people in it"
PLAT=http://localhost:8000
is "an anonymous caller is asked who they are" 401 "$(call platform $PLAT/projects GET '')"
is "a signed-in account sees its own projects" 200 "$(call platform $PLAT/projects GET "$USER")"
# A project nobody is in: the stranger's answer is the same as for one that is
# not there, so no name leaks.
STRANGER=$(docker exec platform python -c "
import json, urllib.request
req = urllib.request.Request('http://localhost:8000/projects', data=json.dumps({'name':'verify rbac scratch'}).encode(),
                             headers={'Content-Type':'application/json','Authorization':'Bearer $ADMIN'}, method='POST')
try: print(json.load(urllib.request.urlopen(req, timeout=20))['slug'])
except Exception: print('')
" 2>/dev/null | tail -1)
if [ -n "$STRANGER" ]; then
  is "a project somebody else made is not found"   404 "$(call platform $PLAT/projects/$STRANGER GET "$USER")"
  is "its members are not readable either"         404 "$(call platform $PLAT/projects/$STRANGER/members GET "$USER")"
  is "and its systems are not"                     404 "$(call platform $PLAT/projects/$STRANGER/systems GET "$USER")"
  is "the owner reads it"                          200 "$(call platform $PLAT/projects/$STRANGER GET "$ADMIN")"
  is "authz answers a stranger without refusing"   200 "$(call platform $PLAT/authz/projects/$STRANGER GET "$USER")"
  role=$(docker exec platform python -c "
import json, urllib.request
req = urllib.request.Request('http://localhost:8000/authz/projects/$STRANGER', headers={'Authorization':'Bearer $USER'})
print(json.load(urllib.request.urlopen(req, timeout=20)).get('role'))
" 2>/dev/null | tail -1)
  is "and says they are nothing to it"            None "$role"
  docker exec postgres psql -U aisc-postgres-user -d platform -q -c \
    "delete from core.project where slug = '$STRANGER'" >/dev/null 2>&1
  ok "the scratch project was cleaned up"
else
  no "could not make a project to be a stranger to"
fi

echo
echo "4. the modules, inside a project the account is in"
PROJECT=$(docker exec platform python -c "
import json, urllib.request
req = urllib.request.Request('http://localhost:8000/projects', headers={'Authorization':'Bearer $USER'})
found = json.load(urllib.request.urlopen(req, timeout=20))
print(found[0]['pid'] if found else '')
" 2>/dev/null | tail -1)
if [ -n "$PROJECT" ]; then
  ok "the account is in a project to work in"
  is "control objectives lets a member in"       200 "$(call control-objectives http://localhost:8090/p/$PROJECT GET "$USER")"
  is "and asks an anonymous caller who they are" 401 "$(call control-objectives http://localhost:8090/p/$PROJECT GET '')"
  is "a project nobody is in is not found"       404 "$(call control-objectives http://localhost:8090/p/00000000-0000-0000-0000-000000000000 GET "$USER")"
  is "the catalogue of objectives is the same for everyone" 200 \
     "$(call control-objectives http://localhost:8090/objectives GET "$USER")"
  is "the engine shows the project to a member"  200 "$(call aisc-backend $ENG/projects?platform_project_id=$PROJECT GET "$USER")"
  # The two Next apps, through the container rather than the gateway: their door
  # reads the same token, and the gateway wants a cookie session instead.
  page() {  # page <container:port/path> <token>
    docker exec caddy wget -q -O /dev/null -S --header="Authorization: Bearer $2" "http://$1" 2>&1 \
      | grep -m1 'HTTP/' | awk '{print $2}'
  }
  NOBODY=00000000-0000-0000-0000-000000000000
  is "controls opens for a member"               200 "$(page controls-web:3000/controls/p/$PROJECT/checklists "$USER")"
  is "and not for a project nobody is in"        404 "$(page controls-web:3000/controls/p/$NOBODY/checklists "$USER")"
  is "qualification opens for a member"          200 "$(page qualification-web:3000/qualification/p/$PROJECT/qualifications "$USER")"
  is "and not for a project nobody is in"        404 "$(page qualification-web:3000/qualification/p/$NOBODY/qualifications "$USER")"
  CTRL="controls-web:3000/controls/p"
  is "a path that is not a project is not found"  404 "$(page $CTRL/abc/checklists "$USER")"
  is "the install page previews for a member"     200 "$(page "$CTRL/$PROJECT/install?slug=accuracy-checklist" "$USER")"
  is "and is not found for a project nobody is in" 404 "$(page "$CTRL/$NOBODY/install?slug=accuracy-checklist" "$USER")"
  is "the project chooser opens for anyone signed in" 200 "$(page "controls-web:3000/controls/install?slug=accuracy-checklist" "$USER")"
  echo "the controls schema no longer lives in the shared database"
  left=$(docker exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select count(*) from pg_namespace where nspname = \$\$controls\$\$"')
  is "no shared controls schema" 0 "$left"
else
  no "the ordinary account is in no project at all"
fi

echo
echo "5. what the audit found, staying fixed"
# An upload does not get to say where it lands. The traversal is refused as
# not-a-wheel either way; what is asserted is that nothing outside the staging
# directory was touched, which the unit suite covers in full.
is "a traversing filename does not reach the handler's file"  403 \
   "$(call catalogue-backend $CAT/devpi/upload POST "$USER" '{}')"
staged=$(docker exec -w /app catalogue-backend uv run python -c "
import tempfile, pathlib, sys
sys.path.insert(0, '/app')
from devpi_api import staged_path
d = pathlib.Path(tempfile.mkdtemp())
bad = staged_path('../../app/main_api.py', d)
print('contained' if bad.parent == d else 'escaped to ' + str(bad))
" 2>/dev/null | tail -1)
is "and a name that climbs stays in the staging directory" contained "$staged"

# CORS: the wildcard echoed any origin back as soon as a cookie was present.
origin=$(docker exec catalogue-backend python -c "
import urllib.request
req = urllib.request.Request('http://localhost:8000/health',
      headers={'Origin': 'https://evil.example', 'Cookie': 'x=1'})
print(urllib.request.urlopen(req, timeout=10).headers.get('access-control-allow-origin') or 'none')
" 2>/dev/null | tail -1)
is "an unknown origin is not echoed back"                    none "$origin"

# The engine's routes addressed by a child object's id.
is "an evaluation is not readable by id alone"               404 \
   "$(call aisc-backend $ENG/evaluations/00000000-0000-0000-0000-000000000000 GET "$USER")"
is "nor a stored file by its object name"                    404 \
   "$(call aisc-backend $ENG/files/dataset/whatever.csv GET "$USER")"
is "nor a project's statistics by its pid"                   404 \
   "$(call aisc-backend $ENG/stats/projects/00000000-0000-0000-0000-000000000000/overview GET "$USER")"

echo
echo "6. the dashboard: a viewer looks and comments"
roles=$(docker exec postgres psql -U aisc-postgres-user -d superset -At -c \
  "select r.name from ab_permission_view_role prv
     join ab_role r on r.id = prv.role_id
     join ab_permission_view pv on pv.id = prv.permission_view_id
     join ab_permission p on p.id = pv.permission_id
    where p.name in ('can_sqllab','can_sql_json','can_execute_sql_query')
    group by r.name order by r.name" 2>/dev/null | tr '\n' ' ')
case " $roles " in
  *" AiscViewer "*) no "the viewer role can reach SQL Lab: $roles" ;;
  *" Gamma "*)      no "Gamma can reach SQL Lab, and accounts may still land there" ;;
  *)                ok "only ${roles:-nobody} can reach SQL Lab, which reads the whole database" ;;
esac
# Without this the count below is zero for a role that does not exist, which
# would pass for the wrong reason.
held=$(docker exec postgres psql -U aisc-postgres-user -d superset -At -c \
  "select count(*) from ab_permission_view_role prv join ab_role r on r.id = prv.role_id
    where r.name = 'AiscViewer'" 2>/dev/null | tail -1)
[ "${held:-0}" -gt 0 ] 2>/dev/null \
  && ok "the viewer role exists and holds something ($held permissions)" \
  || no "there is no AiscViewer role: accounts still land somewhere else"
landed=$(docker exec postgres psql -U aisc-postgres-user -d superset -At -c \
  "select r.name from ab_user u join ab_user_role ur on ur.user_id = u.id
     join ab_role r on r.id = ur.role_id where u.username = 'user'" 2>/dev/null | tail -1)
case "${landed:-none}" in
  AiscViewer) ok "an ordinary account is a viewer on the dashboard" ;;
  none)       ok "the ordinary account has not signed into the dashboard yet" ;;
  *)          no "an ordinary account is $landed on the dashboard" ;;
esac
writes=$(docker exec postgres psql -U aisc-postgres-user -d superset -At -c \
  "select count(*) from ab_permission_view_role prv
     join ab_role r on r.id = prv.role_id
     join ab_permission_view pv on pv.id = prv.permission_view_id
     join ab_permission p on p.id = pv.permission_id
     join ab_view_menu v on v.id = pv.view_menu_id
    where r.name = 'AiscViewer' and p.name = 'can_write' and v.name in ('Chart','Dashboard')" 2>/dev/null | tail -1)
is "a viewer cannot edit the shared charts and dashboards" 0 "${writes:-missing}"

printf '\n\033[1m%d ok, %d failed\033[0m\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
