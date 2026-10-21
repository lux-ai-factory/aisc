#!/usr/bin/env bash
# Does AISC start, and can a person sign in, when its default browser ports are taken? Proven on a whole copy.
#
#   ./scripts/verify-port-fallback.sh                       # refuses while an AISC stack is on this machine
#   ./scripts/verify-port-fallback.sh --take-down-running   # takes that stack down (data kept), back at the end
#   ./scripts/verify-port-fallback.sh --keep                # leaves the copy up to walk through its pages
#   ./scripts/verify-port-fallback.sh --dry-run             # prints what it would do, changes nothing
#   ./scripts/verify-port-fallback.sh --clean-up <folder>   # removes a copy kept with --keep
#
# A copy of the current commit is cloned into a temporary folder and started with `scripts/aisc.py start`, as a
# person installing it would, while stand-in web servers hold the ports it prefers. It runs as its own Compose
# project (aisc-ports) on its own image tag (ports), so no install's data or images are touched; everything it
# made is removed on any exit. The compose files fix the containers' names, though, so the copy cannot run
# beside an installed stack: that one has to be taken down for the length of the check.
#
# Scenarios, each a real start of the copy:
#   new install, every default taken        80, 8100, 8188 and 127.0.0.1:8081 held: the four ports move, and
#                                           the moved launcher signs in and serves steps 1, 2 and 4, the
#                                           dashboard and everything verify-sso.sh checks
#   ports nobody uses                       127.0.0.1:5432 held as well: start neither stops nor moves for it
#   install with data, its port taken later the engine's new port taken too: it moves again, and the sign-in,
#                                           told the new address, still lands on it
#   leftover of a failed attempt            a container only created, never started: start clears it
#
# Prints "  PASS <check>" or "  FAIL <check>" per check; exits 1 on any FAIL, 2 when it refuses to run.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
COMPOSE_FILES="docker-compose.plugin_downloader.yml docker-compose-infra.development.yml docker-compose.development.yml"
STAND_IN_IMAGE=nginx:1.27-alpine

usage() {
  sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
}

TAKE_DOWN=0; KEEP=0; DRY_RUN=0; CLEAN_UP=""
while [ $# -gt 0 ]; do
  case "$1" in
    --take-down-running) TAKE_DOWN=1 ;;
    --keep) KEEP=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --clean-up) CLEAN_UP=${2:-}; [ -n "$CLEAN_UP" ] || { usage >&2; exit 2; }; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

pass=0; fail=0
ok() { printf '  PASS %s\n' "$1"; pass=$((pass+1)); }
no() { printf '  FAIL %s\n' "$1"; fail=$((fail+1)); }
section() { printf '\n%s\n' "$1"; }

# The copy's compose command, run in its clone: always the aisc-ports project, never another one.
copy_compose() { # clone folder, compose arguments...
  local clone=$1; shift
  # shellcheck disable=SC2086
  (cd "$clone" && docker compose -p aisc-ports --env-file env.runtime $(printf -- '-f %s ' $COMPOSE_FILES) "$@")
}

# An install's own compose command, as its containers' labels recorded it: its folder, its env file, its compose
# files. Taking it down and bringing it back this way leaves it exactly as it ran: nothing rebuilt from the
# folder's current files, no port moved, no branch checked (aisc.py start would do all three).
stack_compose() { # project, folder, env file, compose files (comma-separated), compose arguments...
  local project=$1 folder=$2 env_file=$3 files=$4 file
  shift 4
  local args=()
  local IFS=,
  for file in $files; do args+=(-f "$file"); done
  unset IFS
  (cd "$folder" && docker compose -p "$project" --env-file "$env_file" "${args[@]}" "$@")
}

# Everything the check made, and the stack it took down back up. Also run by --clean-up on a kept copy.
clean_up() { # work folder
  local work=$1 project folder
  echo "Removing the copy, its stand-ins and its images ..."
  if [ -f "$work/aisc/env.runtime" ]; then
    copy_compose "$work/aisc" down -v --remove-orphans >/dev/null 2>&1
  fi
  # what is left when the clone never got as far as its env.runtime, or was removed by hand
  docker compose -p aisc-ports down -v --remove-orphans >/dev/null 2>&1
  docker volume ls -q --filter label=com.docker.compose.project=aisc-ports | xargs docker volume rm >/dev/null 2>&1
  local standins images
  standins=$(docker ps -aq --filter name=aisc-ports-standin-)
  [ -z "$standins" ] || docker rm -f $standins >/dev/null
  # By reference, never by id and never forced: the copy's aisc-backend:ports can share its id with the
  # install's aisc-backend:latest (same commit, warm cache), and removing the reference only drops that tag.
  # An image still in use is left, and said so.
  local image
  for image in $( (docker image ls --format '{{.Repository}}:{{.Tag}}' --filter 'reference=aisc-*:ports'
                   docker image ls --format '{{.Repository}}:{{.Tag}}' --filter 'reference=aisc-ports-*') | sort -u); do
    docker rmi "$image" >/dev/null 2>&1 || echo "The image $image was not removed (in use?); remove it with: docker rmi $image"
  done
  if [ -f "$work/taken-down" ]; then
    local env_file files
    while IFS='|' read -r project folder env_file files; do
      [ -n "$project" ] || continue
      echo "Bringing back the stack $project in $folder, as it ran ..."
      if ! stack_compose "$project" "$folder" "$env_file" "$files" up -d --no-build </dev/null; then
        echo "The stack $project did not come back. Start it with: cd $folder && docker compose -p $project" \
             "--env-file $env_file -f ${files//,/ -f } up -d --no-build" >&2
      fi
    done < "$work/taken-down"
  fi
  case "$work" in
    */aisc-ports.*) rm -rf "$work" ;;
  esac
}

if [ -n "$CLEAN_UP" ]; then
  case "$CLEAN_UP" in
    */aisc-ports.*) ;;
    *) echo "$CLEAN_UP is not a folder this check made (aisc-ports.<random>)" >&2; exit 2 ;;
  esac
  clean_up "$CLEAN_UP"
  exit 0
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running (or this user may not use it): the check starts a whole copy of AISC." >&2
  exit 2
fi

# 1. AISC's container names already in use: the copy would collide with them
aisc_names() {
  (cd "$ROOT" && sed -n 's/^[[:space:]]*container_name:[[:space:]]*//p' $COMPOSE_FILES | tr -d "\"' " | sort -u)
}
held=$(docker ps -a --format '{{.Names}}' | grep -Fx -f <(aisc_names))
TAKE_DOWN_LIST=""   # project|folder|env file|compose files, one per line: how to bring it back as it ran
LEFTOVER=0          # containers of an earlier check's copy, removed before this one starts
UNLABELLED=""       # containers no compose project made, or made without the labels to bring them back
others=""
for name in $held; do
  labels=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}	{{index .Config.Labels "com.docker.compose.project.working_dir"}}	{{index .Config.Labels "com.docker.compose.project.environment_file"}}	{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$name" 2>/dev/null)
  project=$(printf '%s' "$labels" | cut -f1)
  folder=$(printf '%s' "$labels" | cut -f2)
  env_file=$(printf '%s' "$labels" | cut -f3)
  files=$(printf '%s' "$labels" | cut -f4)
  if [ "$project" = "aisc-ports" ]; then
    LEFTOVER=1
    continue
  fi
  others="$others$name "
  if [ -z "$project" ] || [ -z "$folder" ] || [ -z "$files" ]; then
    UNLABELLED="$UNLABELLED $name"
  elif ! printf '%s\n' "$TAKE_DOWN_LIST" | grep -q "^$project|"; then
    # an older compose did not record the env file: the one aisc.py start makes
    TAKE_DOWN_LIST="$TAKE_DOWN_LIST$project|$folder|${env_file:-env.runtime}|$files
"
  fi
done
if [ -n "$UNLABELLED" ]; then
  echo "Containers with AISC's names that the check cannot bring back as they ran (no compose project, folder or" \
       "files on them):$UNLABELLED. Remove them first (docker rm -f); the copy uses the same names." >&2
  exit 2
fi
if [ -n "$others" ] && [ "$TAKE_DOWN" = 0 ]; then
  echo "An AISC stack is on this machine (containers: ${others% }). The compose files fix the containers' names," \
       "so the copy this check starts cannot run beside it. Run again with --take-down-running to take that" \
       "stack down for the check (its data is kept) and bring it back at the end." >&2
  exit 2
fi

if [ "$DRY_RUN" = 1 ]; then
  echo "What the check would do (nothing is done in a dry run):"
  printf '%s' "$TAKE_DOWN_LIST" | while IFS='|' read -r project folder env_file files; do
    [ -n "$project" ] && echo "  take down the stack $project in $folder (containers: ${others% }), its data kept;" \
                              "bring it back at the end with its own files, up -d --no-build"
  done
  [ "$LEFTOVER" = 1 ] && echo "  remove the containers an earlier check left (project aisc-ports)"
  cat <<EOF
  clone commit $(git -C "$ROOT" rev-parse --short HEAD) with its submodules into a temporary folder aisc-ports.<random>
  set AISC_IMAGE_TAG=ports in the clone's env.plugin_downloader; run start as AISC_PROJECT=aisc-ports
  new install, every default taken: stand-ins ($STAND_IN_IMAGE) on 80, 8100, 8188, 127.0.0.1:8081; start;
    four moves, AISC is up, env.local 8080 8110 8198 8091; sign in at the moved launcher, the launcher lists
    projects, steps 1, 2 and 4 and the dashboard answer signed in, verify-sso.sh passes
  ports nobody uses: a stand-in on 127.0.0.1:5432 during that start; start does not stop or move for it
  install with data, its port taken later: the copy down (volumes kept), a stand-in on 8080, start; the engine
    moves to 8090 and the signed-in checks pass again
  leftover of a failed attempt: the copy down, one service only created, start; it is cleared and AISC is up
  clean up: the copy down -v (project aisc-ports), the stand-ins, the :ports images, the temporary folder$( \
    [ -n "$TAKE_DOWN_LIST" ] && printf ', then the stack taken down started again')
EOF
  exit 0
fi

WORK=$(mktemp -d "${TMPDIR:-/tmp}/aisc-ports.XXXXXX")
CLONE=$WORK/aisc
on_exit() {
  local code=$?
  if [ "$KEEP" = 1 ] && [ -f "$CLONE/env.local" ]; then
    local launcher
    launcher=$(sed -n 's/^LAUNCHER_EXTERNAL_URL=//p' "$CLONE/env.runtime" 2>/dev/null | tail -1)
    echo
    echo "The copy is still up: open ${launcher:-its launcher} and sign in as admin (the password is"
    echo "AISC_ADMIN_PASSWORD in $CLONE/env.secrets). Remove it, and bring back a stack this check took down, with:"
    echo "  bash $ROOT/scripts/verify-port-fallback.sh --clean-up $WORK"
  else
    clean_up "$WORK"
  fi
  exit "$code"
}
trap on_exit EXIT
trap 'exit 130' INT TERM

if [ "$LEFTOVER" = 1 ]; then
  echo "Removing what an earlier check left (project aisc-ports) ..."
  docker compose -p aisc-ports down -v --remove-orphans >/dev/null 2>&1
fi
# recorded before the take-down, so a take-down that fails half-way is still brought back
printf '%s' "$TAKE_DOWN_LIST" > "$WORK/taken-down"
while IFS='|' read -r project folder env_file files; do
  [ -n "$project" ] || continue
  echo "Taking down the stack $project (its data is kept; it comes back at the end) ..."
  stack_compose "$project" "$folder" "$env_file" "$files" down </dev/null >/dev/null 2>&1 \
    || { no "take down the stack $project"; exit 1; }
done < "$WORK/taken-down"
if [ -s "$WORK/taken-down" ]; then
  still=$(docker ps -a --format '{{.Names}}' | grep -Fx -f <(aisc_names) | tr '\n' ' ')
  [ -z "$still" ] || { no "containers with AISC's names are still here after the take-down: $still"; exit 1; }
fi

stand_in() { # [address:]port -> a web server holding it
  local name
  name=aisc-ports-standin-$(printf '%s' "$1" | tr '.:' '--')
  if docker run -d --name "$name" -p "$1:80" "$STAND_IN_IMAGE" >/dev/null 2>"$WORK/stand-in.err"; then
    ok "a stand-in holds $1"
  else
    no "a stand-in holds $1: $(tail -1 "$WORK/stand-in.err")"
    exit 1
  fi
}

start_copy() { # log file -> start's own exit code; its output is shown as it comes and kept in the log
  (cd "$CLONE" && AISC_PROJECT=aisc-ports AISC_IMAGE_TAG=ports uv run scripts/aisc.py start) 2>&1 | tee "$1"
  return "${PIPESTATUS[0]}"
}

local_setting() { # NAME -> its value in the copy's env.local
  sed -n "s/^$1=//p" "$CLONE/env.local" 2>/dev/null | tail -1
}

started() { # exit code, log file, what: start went through and said so
  if [ "$1" = 0 ] && grep -q "AISC is up" "$2"; then ok "$3: start ended with AISC is up"; return 0; fi
  no "$3: start ended with code $1 and without AISC is up (log: $2)"
  return 1
}

# The checks made as a person: signed in at the moved launcher, through the gateway. In a subshell, inside the
# clone, so the helpers read the copy's env.runtime and env.secrets, and addresses read earlier do not stick.
signed_in_checks() { # engine port
  ( cd "$CLONE" || exit 1
    unset VERIFY_APPS_URL VERIFY_BASE_URL VERIFY_DASHBOARD_URL KEYCLOAK_URL GATEWAY_LAUNCHER_URL \
          VERIFY_ADMIN_USER VERIFY_ADMIN_PASSWORD VERIFY_USER VERIFY_PASSWORD
    . scripts/lib/dev-accounts.sh
    . scripts/lib/gateway-session.sh
    . scripts/lib/probe-project.sh
    pass=0; fail=0
    case "$VERIFY_APPS_URL" in *":$1") ok "steps 1 and 2 are at $VERIFY_APPS_URL" ;; *) no "steps 1 and 2 are at $VERIFY_APPS_URL, not port $1" ;; esac
    case "$VERIFY_BASE_URL" in *":8110") ok "the launcher is at $VERIFY_BASE_URL" ;; *) no "the launcher is at $VERIFY_BASE_URL, not 8110" ;; esac
    case "$VERIFY_DASHBOARD_URL" in *":8198") ok "the dashboard is at $VERIFY_DASHBOARD_URL" ;; *) no "the dashboard is at $VERIFY_DASHBOARD_URL, not 8198" ;; esac
    case "$KEYCLOAK_URL" in *":8091") ok "the sign-in is at $KEYCLOAK_URL" ;; *) no "the sign-in is at $KEYCLOAK_URL, not 8091" ;; esac

    jar=$WORK/jar; rm -f "$jar"
    if gateway_session "$ADMIN_NAME" "$ADMIN_PASSWORD" "$jar"; then
      ok "signed in as $ADMIN_NAME through the gateway, back on $VERIFY_BASE_URL/"
    else
      no "signing in as $ADMIN_NAME at $VERIFY_BASE_URL/ did not land back on the launcher"
      exit 1
    fi

    token=$(curl -s --max-time 15 -d client_id=aisc-webapp -d grant_type=password -d scope=openid \
              --data-urlencode "username=$ADMIN_NAME" --data-urlencode "password=$ADMIN_PASSWORD" \
              "$KEYCLOAK_URL/realms/aisc/protocol/openid-connect/token" \
            | python3 -c 'import json,sys; print(json.load(sys.stdin).get("access_token",""))' 2>/dev/null)
    probe_project_for "$token"
    listed=$(curl -s -b "$jar" --max-time 15 "$VERIFY_BASE_URL/api/projects" \
             | python3 -c 'import json,sys; print(" ".join(p.get("pid","") for p in json.load(sys.stdin)))' 2>/dev/null)
    case " $listed " in
      *" $PROBE_PID "*) [ -n "$PROBE_PID" ] && ok "the launcher lists the projects (with $PROBE_PID)" \
                                             || no "no project to work in" ;;
      *) no "the launcher's project list (${listed:-nothing}) does not hold ${PROBE_PID:-the probe project}" ;;
    esac

    for step in "step 1|$VERIFY_APPS_URL/qualification/p/$PROBE_PID" \
                "step 2|$VERIFY_APPS_URL/control-objectives/p/$PROBE_PID/projects" \
                "step 4|$VERIFY_APPS_URL/?project=$PROBE_PID" \
                "the dashboard|$VERIFY_DASHBOARD_URL/"; do
      what=${step%%|*}; url=${step#*|}
      got=$(curl -s -b "$jar" -c "$jar" -L --max-time 30 -o /dev/null -w '%{http_code} %{url_effective}' "$url")
      code=${got%% *}; landed=${got#* }
      case "$code $landed" in
        "200 $KEYCLOAK_URL"*) no "$what ($url) sent the signed-in session back to the sign-in" ;;
        "200 "*) ok "$what answers signed in at $url" ;;
        *) no "$what ($url) answered $code" ;;
      esac
    done

    if bash scripts/verify-sso.sh > "$WORK/verify-sso.log" 2>&1; then
      ok "verify-sso.sh in the copy: $(grep -c 'PASS' "$WORK/verify-sso.log") checks, all passed"
    else
      no "verify-sso.sh in the copy failed:"
      grep 'FAIL' "$WORK/verify-sso.log" | sed 's/^/       /'
    fi
  )
}

counted_checks() { # engine port: the signed-in checks, counted here
  local out
  out=$(signed_in_checks "$1")
  printf '%s\n' "$out"
  pass=$((pass + $(printf '%s\n' "$out" | grep -c '^  PASS')))
  fail=$((fail + $(printf '%s\n' "$out" | grep -c '^  FAIL')))
  printf '%s\n' "$out" | grep -q '^  PASS' || fail=$((fail+1))
}

finish() {
  printf '\n%d passed, %d failed\n' "$pass" "$fail"
  [ "$fail" -eq 0 ] || exit 1
  exit 0
}

section "The copy"
if [ -n "$(git -C "$ROOT" status --porcelain --ignore-submodules=none)" ]; then
  echo "Note: this checkout has uncommitted changes; the copy is the commit $(git -C "$ROOT" rev-parse --short HEAD) without them."
fi
branch=$(sed -n 's/^BRANCH = "\(.*\)"/\1/p' "$ROOT/scripts/aisc.py")
# the copy is on the branch start insists on, at this checkout's commit, whatever this checkout is on
if git clone -q --no-checkout "$ROOT" "$CLONE" && git -C "$CLONE" checkout -q -B "$branch" "$(git -C "$ROOT" rev-parse HEAD)" \
   && git -C "$CLONE" submodule init -q; then
  # the submodules come from this checkout's own, at the commits the root records: no network, no access needed
  git -C "$CLONE" config -f "$CLONE/.gitmodules" --get-regexp '^submodule\..*\.path$' | while read -r key path; do
    name=${key#submodule.}; name=${name%.path}
    git -C "$CLONE" config "submodule.$name.url" "$ROOT/$path"
  done
  if git -C "$CLONE" -c protocol.file.allow=always submodule update -q --recursive; then
    ok "cloned $(git -C "$CLONE" rev-parse --short HEAD) and its submodules into $CLONE"
  else
    no "the submodules of the copy could not be checked out"; finish
  fi
else
  no "the copy could not be cloned"; finish
fi
# the copy's images get a tag of their own, so the install's :latest images are neither rebuilt nor removed
printf '\nAISC_IMAGE_TAG=ports\n' >> "$CLONE/env.plugin_downloader"

section "new install, every default taken (and ports nobody uses)"
for port in 80 8100 8188 127.0.0.1:8081 127.0.0.1:5432; do stand_in "$port"; done
start_copy "$WORK/start-new.log"; code=$?
started "$code" "$WORK/start-new.log" "new install" || finish
moves=$(grep -c 'is taken on this computer, so AISC uses' "$WORK/start-new.log")
[ "$moves" = 4 ] && ok "start moved four ports" || no "start moved $moves ports, not four"
for setting in ENGINE_PORT=8080 HOMEPAGE_PORT_EXTERNAL=8110 DASHBOARD_PORT_EXTERNAL=8198 KEYCLOAK_PORT_EXTERNAL=8091; do
  name=${setting%%=*}; want=${setting#*=}; got=$(local_setting "$name")
  [ "$got" = "$want" ] && ok "env.local holds $setting" || no "env.local holds $name=${got:-nothing}, not $want"
done
if grep -q 5432 "$WORK/start-new.log"; then
  no "start spoke of 5432, a port AISC does not publish: $(grep 5432 "$WORK/start-new.log" | head -1)"
else
  ok "start neither stopped nor moved for 127.0.0.1:5432, which AISC does not publish"
fi
[ -n "$(docker ps -q --filter name=aisc-ports-standin-127-0-0-1-5432 --filter status=running)" ] \
  && ok "the program on 127.0.0.1:5432 still runs" || no "the stand-in on 127.0.0.1:5432 is gone"

section "signed in on the moved ports"
counted_checks 8080

section "install with data, its port taken later"
copy_compose "$CLONE" down >/dev/null 2>&1
stand_in 8080
start_copy "$WORK/start-taken-later.log"; code=$?
if started "$code" "$WORK/start-taken-later.log" "install with data"; then
  got=$(local_setting ENGINE_PORT)
  [ "$got" = 8090 ] && ok "the engine moved to 8090" || no "the engine is on ${got:-nothing}, not 8090"
  counted_checks 8090
fi

section "leftover of a failed attempt"
copy_compose "$CLONE" down >/dev/null 2>&1
copy_compose "$CLONE" create redis >/dev/null 2>&1 \
  && ok "a container created and never started is left (redis)" || no "compose could not create redis"
start_copy "$WORK/start-leftover.log"; code=$?
grep -q "Removing what an earlier attempt left unstarted" "$WORK/start-leftover.log" \
  && ok "start cleared the unstarted container" || no "start did not say it cleared the unstarted container"
started "$code" "$WORK/start-leftover.log" "after a failed attempt"
[ -z "$(copy_compose "$CLONE" ps -a -q --status created 2>/dev/null)" ] \
  && ok "no container is left only created" || no "containers are still only created"

finish
