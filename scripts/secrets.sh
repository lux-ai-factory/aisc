#!/usr/bin/env bash
# The secrets this install runs on, generated here and never committed: `scripts/aisc.py secrets`, whose top
# says what each option does and why.
#
#   ./scripts/secrets.sh            # make them if they are missing
#   ./scripts/secrets.sh --rotate   # make new ones, replacing what is there
#   ./scripts/secrets.sh --add-ledger-key   # add the next version of the ledger's master key
#   ./scripts/secrets.sh --rotate-one NAME   # a new IMMUDB_ADMIN_PASSWORD, LEDGER_IMMUDB_PASSWORD or ENGINE_IMMUDB_PASSWORD
set -euo pipefail
cd "$(dirname "$0")/.."
. scripts/lib/aisc-py.sh
aisc_py secrets "$@"
