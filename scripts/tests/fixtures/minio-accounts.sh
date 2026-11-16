#!/usr/bin/env bash
# Runs infra/minio/make-buckets.sh twice in a throwaway MinIO (scripts/lib/throwaway-minio.sh, the stack's own
# image, fake passwords), then tries what each account may and may not do, and prints the answers as JSON.
# Exit 3 when the aisc-minio image is not built. The stack's MinIO is never used.
set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
. "$ROOT/scripts/lib/throwaway-minio.sh"
trap tminio_cleanup EXIT
tminio_start accounts 2>/dev/null || exit 3
name=$TMINIO_NAME
docker exec -u 0 "$name" mkdir -p /policies-under-test >/dev/null
docker cp "$ROOT/infra/minio/policies/." "$name:/policies-under-test/" >/dev/null
docker cp "$ROOT/infra/minio/make-buckets.sh" "$name:/tmp/make-buckets.sh" >/dev/null
engine=fake-engine-$RANDOM$RANDOM
platform=fake-platform-$RANDOM$RANDOM
for _ in 1 2; do
  docker exec -e MINIO_ROOT_USER="$TMINIO_USER" -e MINIO_ROOT_PASSWORD="$TMINIO_PASSWORD" \
    -e S3_ENGINE_PASSWORD="$engine" -e S3_PLATFORM_PASSWORD="$platform" -e MINIO_ADDRESS=127.0.0.1:9000 \
    -e POLICIES=/policies-under-test "$name" sh /tmp/make-buckets.sh >/dev/null 2>&1 || { echo "make-buckets.sh failed" >&2; exit 1; }
done
docker exec "$name" sh -c 'echo file > /tmp/file' >/dev/null

can() { # user password command
  if docker exec -e MC_HOST_x="http://$1:$2@127.0.0.1:9000" "$name" sh -c "$3" >/dev/null 2>&1; then
    printf true
  else
    printf false
  fi
}
e=aisc-engine p=aisc-platform
put_artifacts=$(can $e "$engine" "mc cp /tmp/file x/artifacts/a")
read_datasets=$(can $e "$engine" "mc ls x/datasets")
engine_bucket=$(can $e "$engine" "mc mb x/other")
engine_admin=$(can $e "$engine" "mc admin user list x")
make_proof=$(can $p "$platform" "mc mb x/proof-0123 && mc cp /tmp/file x/proof-0123/f && mc cat x/proof-0123/f")
engine_proof=$(can $e "$engine" "mc cat x/proof-0123/f")
platform_read=$(can $p "$platform" "mc cat x/artifacts/a")
platform_put=$(can $p "$platform" "mc cp /tmp/file x/artifacts/b")
platform_list=$(can $p "$platform" "mc ls x/artifacts")
platform_admin=$(can $p "$platform" "mc admin user list x")
printf '{"engine": {"put_artifacts": %s, "read_datasets": %s, "make_bucket": %s, "read_proof": %s, "admin": %s},' \
  "$put_artifacts" "$read_datasets" "$engine_bucket" "$engine_proof" "$engine_admin"
printf ' "platform": {"make_proof_bucket": %s, "list_artifacts": %s, "read_artifact": %s, "put_artifacts": %s, "admin": %s}}\n' \
  "$make_proof" "$platform_list" "$platform_read" "$platform_put" "$platform_admin"
