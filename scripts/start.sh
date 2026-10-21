#!/usr/bin/env bash
# Install and start AISC in one command: `scripts/aisc.py start`, whose docstring says what it checks and does.
#
#   ./scripts/start.sh
#
# Settings for the impatient or the tests: START_WAIT_S (default 300), START_POLL_S (5), START_URL,
# START_MIN_DISK_GB (20).
set -euo pipefail
cd "$(dirname "$0")/.."
. scripts/lib/aisc-py.sh
aisc_py start "$@"
