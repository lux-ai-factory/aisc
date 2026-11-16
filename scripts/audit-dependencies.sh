#!/usr/bin/env bash
# Does any lock of the checkout, submodules included, hold a version inside a published advisory?
#
#   scripts/audit-dependencies.sh                     # every lock; exit 1 on a high or critical advisory
#   scripts/audit-dependencies.sh --only python       # uv.lock and requirements files only (or --only node)
#   scripts/audit-dependencies.sh --list              # the files it checks, one per line
#   scripts/audit-dependencies.sh --check-accepted    # only the acceptances: an expired or malformed one fails
#   scripts/audit-dependencies.sh --accepted FILE     # acceptances from FILE instead of scripts/audit-accepted.txt
#
# Python: pip-audit (through uvx) on each uv.lock's export and each resolved requirements file (development
# requirement files left out). Node: npm audit --omit=dev in each package-lock.json folder. Findings below high are
# listed and do not fail. An accepted advisory (scripts/audit-accepted.txt: "<id> <package> <reason> until=DATE")
# is skipped until its date passes. CI runs it on every push, and the weekly scan on schedule.
# The logic is in scripts/lib/audit_dependencies.py.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
exec python3 "$ROOT/scripts/lib/audit_dependencies.py" "$@"
