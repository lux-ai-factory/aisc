#!/bin/sh
# Makes the stack's buckets, turns on their server-side encryption (SSE-S3, MinIO's key from MINIO_KMS_SECRET_KEY),
# and the services' own MinIO accounts, then exits. Run by the one-shot make_buckets
# on every start, as MinIO's root account, which no other service holds:
#   - the engine's three buckets (datasets, artifacts, models), kept when they exist;
#   - aisc-engine, the engine backend's account: read, write and delete files in those three buckets only;
#   - aisc-platform, the platform's account: the projects' proof-* buckets, and listing and deleting files
#     in the engine's buckets (a project's files when the project is removed).
# Each policy is written again and each account's password set again from S3_ENGINE_PASSWORD and
# S3_PLATFORM_PASSWORD on every start, so an install made before the accounts existed gets them on its next
# start and a password renewed by `secrets --rotate` reaches MinIO. No stored file is touched.
#
# No password is on a command line: mc reads the root account from MC_HOST_minio and an account's
# password on stdin.
set -eu

: "${MINIO_ROOT_USER:?}" "${MINIO_ROOT_PASSWORD:?}" "${S3_ENGINE_PASSWORD:?}" "${S3_PLATFORM_PASSWORD:?}"
POLICIES=${POLICIES:-/policies}
export MC_HOST_minio="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@${MINIO_ADDRESS:-minio:9000}"

for bucket in datasets artifacts models; do
  mc mb --ignore-existing "minio/$bucket"
done
mc encrypt set sse-s3 minio/datasets >/dev/null
mc encrypt set sse-s3 minio/artifacts >/dev/null
mc encrypt set sse-s3 minio/models >/dev/null
# the projects' proof-file buckets the platform made before it set their encryption itself
for bucket in $(mc ls minio | awk '{print $NF}' | tr -d / | grep '^proof-' || true); do
  mc encrypt set sse-s3 "minio/$bucket" >/dev/null
done
echo "server-side encryption on for every bucket (objects stored before stay as they were)"

account() { # service, password
  mc admin policy create minio "aisc-$1" "$POLICIES/$1.json"
  printf '%s\n' "$2" | mc admin user add minio "aisc-$1" >/dev/null
  # attaching a policy the account already has is refused with "already in effect": that is the wanted state
  if ! said=$(mc admin policy attach minio "aisc-$1" --user "aisc-$1" 2>&1); then
    case "$said" in
      *"already in effect"*|*"already attached"*) ;;
      *) echo "$said" >&2; exit 1 ;;
    esac
  fi
  echo "MinIO account aisc-$1 ready"
}

account engine "$S3_ENGINE_PASSWORD"
account platform "$S3_PLATFORM_PASSWORD"
