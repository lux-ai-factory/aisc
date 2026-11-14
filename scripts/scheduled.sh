#!/usr/bin/env bash
# One scheduled job of this install, with a dated log: what scripts/schedule.sh puts in the crontab.
#
#   bash scripts/scheduled.sh backup [--log-dir DIR]   scripts/backup-databases.sh (every part restored and counted)
#   bash scripts/scheduled.sh verify [--log-dir DIR]   scripts/verify.sh --stack, the checks of the running stack
#
# The job's output goes to DIR/<job>-YYYY-MM-DD.log (appended; default $HOME/aisc-logs/<stack>), logs older than
# 30 days are removed, and the job's exit code is this script's, so cron mails a failure when it is set to.
# AISC_VERIFY_SCRIPT runs another verify (the tests use a fake one).
set -uo pipefail
umask 077

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
# shellcheck source=SCRIPTDIR/lib/stack-name.sh
. "$ROOT/scripts/lib/stack-name.sh"

usage() { echo "usage: bash scripts/scheduled.sh backup|verify [--log-dir DIR]" >&2; exit 2; }

[ $# -ge 1 ] || usage
JOB=$1
shift
LOGS="$HOME/aisc-logs/$(aisc_stack)"
while [ $# -gt 0 ]; do
  case $1 in
    --log-dir) [ $# -ge 2 ] || usage; LOGS=$2; shift 2 ;;
    *) usage ;;
  esac
done
case $JOB in
  backup) CMD=(bash "$ROOT/scripts/backup-databases.sh") ;;
  verify) CMD=(bash "${AISC_VERIFY_SCRIPT:-$ROOT/scripts/verify.sh}" --stack) ;;
  *) usage ;;
esac

mkdir -p "$LOGS" || exit 2
LOG="$LOGS/$JOB-$(date +%Y-%m-%d).log"
find "$LOGS" -maxdepth 1 -type f \( -name 'backup-*.log' -o -name 'verify-*.log' \) -mtime +30 -exec rm -f {} + \
  2>/dev/null
cd "$ROOT" || exit 2
{
  echo "== $JOB started $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  "${CMD[@]}"
  code=$?
  echo "== $JOB ended $(date -u +%Y-%m-%dT%H:%M:%SZ) with exit code $code"
  exit "$code"
} >> "$LOG" 2>&1
