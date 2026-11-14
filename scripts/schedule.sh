#!/usr/bin/env bash
# This install's schedule: the daily backup at 02:30 and the daily verify of the running stack at 03:30, as two
# lines of the user's crontab, each tagged with this install's stack.
#
#   bash scripts/schedule.sh --print     print the two lines, change nothing
#   bash scripts/schedule.sh --install   put them in the crontab (any earlier ones of this install replaced)
#   bash scripts/schedule.sh --remove    take this install's lines out; every other line is left as it was
#
# Each line runs scripts/scheduled.sh, which writes a dated log. The backup needs its passphrase file (see
# scripts/backup-databases.sh) before the first night, or it reports the secrets file as not backed up.
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
# shellcheck source=SCRIPTDIR/lib/stack-name.sh
. "$ROOT/scripts/lib/stack-name.sh"

TAG="# aisc-schedule:$(aisc_stack)"
# cron starts jobs with a bare PATH: docker, python3 and uv are looked for where they are installed
PATHS="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"

lines() {
  printf '30 2 * * * cd "%s" && PATH="%s" bash scripts/scheduled.sh backup %s\n' "$ROOT" "$PATHS" "$TAG"
  printf '30 3 * * * cd "%s" && PATH="%s" bash scripts/scheduled.sh verify %s\n' "$ROOT" "$PATHS" "$TAG"
}

others() { # the crontab's lines that are not this install's (none when there is no crontab yet)
  crontab -l 2>/dev/null | grep -vF "$TAG" || true
}

# read before writing: `crontab -l | ... | crontab -` would race the new table against the reading of the old
case ${1:-} in
  --print) lines ;;
  --install)
    kept=$(others)
    { [ -z "$kept" ] || printf '%s\n' "$kept"; lines; } | crontab - || exit 1
    echo "installed the backup (02:30) and verify (03:30) lines tagged '$TAG' in the crontab"
    ;;
  --remove)
    kept=$(others)
    { [ -z "$kept" ] || printf '%s\n' "$kept"; } | crontab - || exit 1
    echo "removed the lines tagged '$TAG' from the crontab"
    ;;
  *) echo "usage: bash scripts/schedule.sh --print|--install|--remove" >&2; exit 2 ;;
esac
