# Throwaway immudb for tests. Sourced, never executed.
#
#   . scripts/lib/throwaway-immudb.sh
#   timmu_start platform         # starts aisc-t-immudb-platform-<hex> on a free 127.0.0.1 port
#   echo "$TIMMU_URL"            # 127.0.0.1:<port>, superuser password in TIMMU_ADMIN_PASSWORD
#   echo "$TIMMU_PUBLIC_KEY"     # the public half of the key the server signs its state with
#
# The stack's immudb holds the live ledger and is never used by a test. This is a container of its own on
# the stack's pinned image, with a generated superuser password and signing key, no volume, removed by
# timmu_cleanup (call it from the caller's EXIT trap). The password reaches docker through the environment,
# never the command line, and is never printed. The stack's port 3322 is refused.

TIMMU_IMAGE=${TIMMU_IMAGE:-codenotary/immudb:1.11.1}
TIMMU_NAME=""
TIMMU_URL=""
TIMMU_ADMIN_PASSWORD=""
TIMMU_PUBLIC_KEY=""
TIMMU_DIR=""

timmu_cleanup() {
  if [ -n "$TIMMU_NAME" ]; then
    docker rm -f "$TIMMU_NAME" >/dev/null 2>&1 || true
  fi
  if [ -n "$TIMMU_DIR" ]; then
    rm -rf "$TIMMU_DIR"
  fi
}

timmu_start() { # label
  local label=${1:-t} port
  TIMMU_NAME="aisc-t-immudb-${label}-$(python3 -c 'import secrets; print(secrets.token_hex(4))')"
  # immudb wants upper, lower, digit and symbol, at most 32 characters (secrets.sh's shape)
  TIMMU_ADMIN_PASSWORD="Az9-$(python3 -c 'import secrets; print(secrets.token_hex(12))')"
  port=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')
  if [ -z "$port" ] || [ "$port" = "3322" ]; then
    echo "throwaway-immudb: refusing port '$port'" >&2; return 1
  fi
  # A signing key of its own, so the tests that check immudb's signed state run too.
  TIMMU_DIR=$(mktemp -d)
  mkdir "$TIMMU_DIR/keys"
  openssl ecparam -name prime256v1 -genkey -noout -out "$TIMMU_DIR/keys/signing.key" 2>/dev/null || return 1
  openssl ec -in "$TIMMU_DIR/keys/signing.key" -pubout -out "$TIMMU_DIR/signing.pub" 2>/dev/null || return 1
  chmod 755 "$TIMMU_DIR/keys" && chmod 444 "$TIMMU_DIR/keys/signing.key"
  TIMMU_PUBLIC_KEY="$TIMMU_DIR/signing.pub"
  IMMUDB_ADMIN_PASSWORD="$TIMMU_ADMIN_PASSWORD" docker create --name "$TIMMU_NAME" \
    -p "127.0.0.1:${port}:3322" -e IMMUDB_ADMIN_PASSWORD -e IMMUDB_SIGNINGKEY=/keys/signing.key \
    "$TIMMU_IMAGE" >/dev/null || return 1
  # copied in, not mounted: the container keeps nothing on the host once removed
  docker cp "$TIMMU_DIR/keys" "$TIMMU_NAME:/keys" >/dev/null || return 1
  docker start "$TIMMU_NAME" >/dev/null || return 1
  TIMMU_URL="127.0.0.1:${port}"
  echo "throwaway-immudb: container $TIMMU_NAME on $TIMMU_URL" >&2
}
