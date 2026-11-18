#!/usr/bin/env bash
#
# Create the S3 buckets the platform expects (datasets, artifacts, models).
#
# This is a one-off step, not a container: the stack ships no bucket-init
# service (I11 — a container runs a long-lived process, setup is a step).
# Start the stack first, then run this once:
#
#   docker compose up -d
#   scripts/make-buckets.sh
#
# It honours the standard Compose variables, so the development and staging
# overlays work too, e.g.:
#
#   COMPOSE_FILE=docker-compose-infra.development.yml \
#   COMPOSE_ENV_FILES=env.development scripts/make-buckets.sh
#
set -euo pipefail

docker compose run --rm --entrypoint /bin/sh minio -c '
  mc alias set aisc http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" &&
  mc mb --ignore-existing aisc/datasets &&
  mc mb --ignore-existing aisc/artifacts &&
  mc mb --ignore-existing aisc/models'
