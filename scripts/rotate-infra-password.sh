#!/usr/bin/env bash
# A new value for one of the passwords the infrastructure keeps in its own volume:
# `scripts/aisc.py rotate-infra-password`, which says how it is applied.
#
#   ./scripts/rotate-infra-password.sh NAME           # a new random value
#   ./scripts/rotate-infra-password.sh NAME --ask     # one you choose, typed twice and never shown
#
# NAME is one of POSTGRES_PASSWORD, RABBITMQ_PASSWORD, S3_PASSWORD, KEYCLOAK_ADMIN_PASSWORD,
# AISC_ADMIN_PASSWORD (the realm's admin account) or AISC_USER_PASSWORD (its user account).
set -euo pipefail
cd "$(dirname "$0")/.."
. scripts/lib/aisc-py.sh
aisc_py rotate-infra-password "$@"
