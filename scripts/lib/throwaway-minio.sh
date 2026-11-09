# Throwaway MinIO for tests. Sourced, never executed.
#
#   . scripts/lib/throwaway-minio.sh
#   tminio_start platform        # starts aisc-t-minio-platform-<hex> on a free 127.0.0.1 port
#   echo "$TMINIO_URL"           # http://127.0.0.1:<port>, user TMINIO_USER, password TMINIO_PASSWORD
#
# The stack's MinIO holds live files and is never used by a test. This is a container of its own, with
# its own random credentials and no volume, removed by tminio_cleanup (call it from the caller's EXIT trap).
# It runs the stack's own image (aisc-minio, built from source by infra/minio/Dockerfile); when that image
# is not built, tminio_start returns 1 and starts nothing.

TMINIO_IMAGE=${TMINIO_IMAGE:-aisc-minio:latest}
TMINIO_NAME=""
TMINIO_URL=""
TMINIO_USER=""
TMINIO_PASSWORD=""

tminio_cleanup() {
  if [ -n "$TMINIO_NAME" ]; then
    docker rm -fv "$TMINIO_NAME" >/dev/null 2>&1 || true
  fi
}

tminio_start() { # label
  local label=${1:-t} port i
  if ! docker image inspect "$TMINIO_IMAGE" >/dev/null 2>&1; then
    echo "throwaway-minio: image $TMINIO_IMAGE is not built; nothing started" >&2
    return 1
  fi
  TMINIO_NAME="aisc-t-minio-${label}-$(python3 -c 'import secrets; print(secrets.token_hex(4))')"
  TMINIO_USER="t$(python3 -c 'import secrets; print(secrets.token_hex(6))')"
  TMINIO_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_hex(16))')
  port=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')
  if [ -z "$port" ] || [ "$port" = "9000" ]; then
    echo "throwaway-minio: refusing port '$port'" >&2; return 1
  fi
  docker run --rm -d --name "$TMINIO_NAME" -p "127.0.0.1:${port}:9000" \
    -e MINIO_ROOT_USER="$TMINIO_USER" -e MINIO_ROOT_PASSWORD="$TMINIO_PASSWORD" \
    --entrypoint /usr/bin/minio "$TMINIO_IMAGE" server /data >/dev/null || return 1
  TMINIO_URL="http://127.0.0.1:${port}"
  for i in $(seq 1 60); do
    if docker exec "$TMINIO_NAME" mc ready local >/dev/null 2>&1; then
      echo "throwaway-minio: container $TMINIO_NAME on $TMINIO_URL" >&2
      return 0
    fi
    sleep 1
  done
  echo "throwaway-minio: $TMINIO_NAME did not come up" >&2
  return 1
}
