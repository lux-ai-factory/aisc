#!/usr/bin/env bash
# The aisc_identity suite with a throwaway Postgres for the access tests, removed afterwards.
#
#   scripts/lib/identity-tests.sh [pytest arguments]
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
. "$ROOT/scripts/lib/throwaway-pg.sh"
tpg_start identity >/dev/null
tpg_su postgres -c 'CREATE DATABASE identity_tests' >/dev/null
export AISC_IDENTITY_TEST_DATABASE_URL="postgresql://$TPG_SU:$TPG_PW@127.0.0.1:$PORT/identity_tests"
cd "$ROOT/shared/identity"
uv run --extra dev pytest -q "$@"
