#!/usr/bin/env bash
# Install and start AISC in one command (workshop 2026-10-06):
#
#   ./scripts/start.sh
#
# 1. Refuses a checkout that cannot work, before anything runs: Docker not running, Compose older than
#    2.17, a branch other than feat/unified-modules (master's files are older), submodules not checked out.
#    Warns when the disk is nearly full.
# 2. Makes the secrets (scripts/secrets.sh: once, then it keeps them; rerun after a pull).
# 3. Builds every image. A failed build is tried twice more, with fewer builds at once: a timeout on a
#    slow network or a laptop short of memory usually passes the second time, and the cache keeps what
#    was built.
# 4. Starts the stack and waits until the sign-in page answers: `up -d` returns before the gateway's
#    sign-in is ready, and a page opened then shows 502.
# 5. Lists the local controls (local_controls/) every project catalogue gets; one it cannot read is a
#    warning, not a failure.
#
# Settings for the impatient or the tests: START_WAIT_S (default 300), START_POLL_S (5), START_URL,
# START_MIN_DISK_GB (20).
set -euo pipefail
cd "$(dirname "$0")/.."

BRANCH=feat/unified-modules
WAIT_S=${START_WAIT_S:-300}
POLL_S=${START_POLL_S:-5}
URL=${START_URL:-http://localhost:8100/}
MIN_DISK_GB=${START_MIN_DISK_GB:-20}
COMPOSE=(docker compose -p aisc --env-file env.runtime -f docker-compose.plugin_downloader.yml
         -f docker-compose-infra.development.yml -f docker-compose.development.yml)

say() { printf '%s\n' "$*"; }
fail() { printf 'start.sh: %s\n' "$*" >&2; exit 1; }

# 1. The checkout and the machine

docker info >/dev/null 2>&1 || fail "Docker is not running (or this user may not use it). Start Docker Desktop or the docker service, then run this again."

version=$(docker compose version --short 2>/dev/null || true)
version=${version#v}
major=${version%%.*}; rest=${version#*.}; minor=${rest%%.*}
if [[ ! $major =~ ^[0-9]+$ || ! $minor =~ ^[0-9]+$ ]] || (( major < 2 || (major == 2 && minor < 17) )); then
    fail "Docker Compose ${version:-is missing}: AISC needs the Compose plugin 2.17 or later (docker compose version)."
fi

branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)
[[ $branch == "$BRANCH" ]] || fail "this checkout is on '${branch:-no branch}', not $BRANCH. Run: git checkout $BRANCH && git submodule update --init --recursive (or clone again: git clone --recursive --branch $BRANCH https://github.com/lux-ai-factory/aisc.git)"

missing=$(git submodule status 2>/dev/null | grep -c '^-' || true)
(( missing == 0 )) || fail "$missing submodule(s) are not checked out. Run: git submodule update --init --recursive"

free_gb=$(df -Pk . | awk 'NR == 2 { print int($4 / 1048576) }')
if (( free_gb < MIN_DISK_GB )); then
    say "Warning: ${free_gb} GB free here; the first build needs about ${MIN_DISK_GB} GB. It may fail with 'no space left on device'."
fi

# 2. The secrets

./scripts/secrets.sh

# 3. The images

built=0
for attempt in 1 2 3; do
    if (( attempt == 1 )); then
        say "Building the images (the first time takes several minutes) ..."
        "${COMPOSE[@]}" build && { built=1; break; }
    else
        say "The build failed; trying again ($attempt of 3), fewer images at once ..."
        COMPOSE_BAKE=false COMPOSE_PARALLEL_LIMIT=2 "${COMPOSE[@]}" build && { built=1; break; }
    fi
done
(( built )) || fail "the build failed three times. The first error above says why: often the network (pip, uv or npm timed out) or the disk. Fix it and run this again; what was built is kept."

# 4. Start, and wait for the sign-in page

say "Starting the stack ..."
"${COMPOSE[@]}" up -d

say "Waiting for the sign-in page at $URL (Keycloak needs about 30 seconds on a first start) ..."
deadline=$(( SECONDS + WAIT_S ))
while :; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$URL" || true)
    case "$code" in
        200|302|303) break ;;
    esac
    if (( SECONDS >= deadline )); then
        say "The sign-in page did not answer within ${WAIT_S}s (last answer: ${code:-none}). Services not running:" >&2
        "${COMPOSE[@]}" ps -a --format '{{.Service}}	{{.Status}}' | grep -v -E '	(Up|running|Exited \(0\))' >&2 || true
        fail "see why with: docker compose -p aisc logs <service>  (for example keycloak or oauth2-proxy)"
    fi
    sleep "$POLL_S"
done

# 5. The local controls every project catalogue gets (local_controls/), read by the platform's own code

if found=$("${COMPOSE[@]}" exec -T platform python -m platform_service.catalogue); then
    count=$(printf '%s\n' "$found" | grep -c . || true)
    say "$count local controls go into every project catalogue (local_controls/):"
    printf '%s\n' "$found" | grep . | sed 's/^/  /' || true
else
    say "Warning: the local controls could not be read; catalogues get the public entries only."
    say "See why with: docker compose -p aisc logs platform"
fi

say ""
say "AISC is up: open ${URL%/} and sign in as admin / admin."
say "If you installed AISC before on this machine, use a private window (an old session cookie is refused)."
