#!/usr/bin/env bash
# A copy of the ledger's signed heads, kept outside the stack: one file a day.
#
#   scripts/ledger-anchor.sh [--webhook URL]
#
# Runs the platform's anchor command (python -m platform_service.ledger.anchor) in the platform container. It
# reads every log whole, checks it, and prints each log's head with the store's signature. The output is written
# to ~/aisc-ledger-anchors/<UTC date>.json (file 0600, folder 0700, never inside the repository); a day already
# written is never overwritten. With --webhook URL, or LEDGER_ANCHOR_WEBHOOK_URL, the same bytes are also posted
# there (10 s timeout; only the status is logged). A log rewritten later no longer matches a head kept here.
#
# Not installed automatically. To run it every day at 02:15 UTC, add a line like this to the host's crontab:
#
#   15 2 * * * cd /path/to/aisc && bash scripts/ledger-anchor.sh >> "$HOME/aisc-ledger-anchors/anchor.log" 2>&1
#
# Exit: 0 written (and posted, when asked); 1 any failure (the day's file, once written, is kept).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$ROOT/scripts/lib/stack-name.sh"

webhook=${LEDGER_ANCHOR_WEBHOOK_URL:-}
while [ $# -gt 0 ]; do
  case "$1" in
    --webhook) [ $# -ge 2 ] || { echo "ledger-anchor: --webhook needs a URL" >&2; exit 1; }; webhook=$2; shift 2 ;;
    *) echo "ledger-anchor: unknown argument $1" >&2; exit 1 ;;
  esac
done

dir="$HOME/aisc-ledger-anchors"
day=$(date -u +%Y-%m-%d)
file="$dir/$day.json"
case "$(cd "$(dirname "$dir")" 2>/dev/null && pwd)/" in
  "$ROOT"/*) echo "ledger-anchor: $dir is inside the repository; anchors are kept outside it" >&2; exit 1 ;;
esac
umask 077
mkdir -p "$dir"
chmod 700 "$dir"
if [ -e "$file" ]; then
  echo "ledger-anchor: $file already exists; a day's anchor is never overwritten" >&2
  exit 1
fi

tmp=$(mktemp "$dir/.anchor.XXXXXX")
trap 'rm -f "$tmp"' EXIT
if ! docker exec "$(aisc_container platform)" python -m platform_service.ledger.anchor > "$tmp"; then
  echo "ledger-anchor: the platform's anchor command failed; nothing written" >&2
  exit 1
fi
if ! python3 -c 'import json, sys; d = json.load(open(sys.argv[1])); assert set(d) == {"anchored_at", "heads"} and d["heads"]' "$tmp"; then
  echo "ledger-anchor: the anchor command did not print one document with heads; nothing written" >&2
  exit 1
fi
chmod 600 "$tmp"
# a hard link refuses an existing name, so two runs at once never overwrite each other
if ! ln "$tmp" "$file" 2>/dev/null; then
  echo "ledger-anchor: $file already exists; a day's anchor is never overwritten" >&2
  exit 1
fi
echo "ledger-anchor: wrote $file"

if [ -n "$webhook" ]; then
  status=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 -X POST -H 'Content-Type: application/json' \
    --data-binary "@$file" "$webhook" 2>/dev/null) || status=000
  echo "ledger-anchor: webhook answered $status"
  case "$status" in
    2??) ;;
    *) echo "ledger-anchor: the webhook did not take the anchor; the file is kept" >&2; exit 1 ;;
  esac
fi
