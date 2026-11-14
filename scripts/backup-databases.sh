#!/usr/bin/env bash
# A backup of everything the stack would lose with its volumes, each part restored into a throwaway and compared.
#
#   bash scripts/backup-databases.sh [--dir DIR] [--keep N] [--no-restore-check | --restore-check-only]
#
# What it writes into DIR, every file private (0600), named <part>_<UTC stamp>:
#   <database>.dump and .counts   every database of the stack's Postgres (platform, keycloak, superset,
#                                 ledger_identity, every project_*), dumped and counted from one snapshot
#                                 (scripts/lib/backup-one.sql)
#   <volume>.tar.gz and .manifest the volumes immudb_data (the ledger), immudb_key (its signing key) and
#                                 minio_data (run artifacts, datasets, proof files); the containers that use a
#                                 volume are paused while it is archived, so the archive is one moment
#   secrets.enc                   env.secrets, whose keys open stored secrets and verify the ledger, encrypted
#                                 with a passphrase (below); the backup never holds its values in the clear
#
# Then, unless --no-restore-check, it restores the newest of each part: every dump into a throwaway Postgres
# (scripts/lib/throwaway-pg.sh), counted table by table; every archive into a throwaway volume, compared file by
# file; the secrets copy decrypted and compared with the file. It prints `restore-check <part> PASS`, or FAIL
# with what differs, and exits 0 only when every part passes. --restore-check-only checks what DIR holds
# without taking a new backup. The newest N of each part are kept (--keep, default 14).
#
# Settings (environment):
#   AISC_BACKUP_DIR              DIR when --dir is not given; default $HOME/aisc-backups/<stack>. Never inside
#                                the checkout, which is refused.
#   AISC_BACKUP_PASSPHRASE_FILE  a file holding the passphrase of the secrets copy; default
#                                $HOME/.config/aisc/backup-passphrase. Made by the operator, private, and kept
#                                somewhere else as well: without it the copy cannot be opened.
#   AISC_BACKUP_PASSPHRASE       the passphrase itself, instead of the file.
#   BACKUP_PG_CONTAINER          the Postgres container; default this install's (aisc-<id>-postgres)
#   POSTGRES_USER                its superuser; default the one in env.runtime
#   BACKUP_STACK                 the Compose project whose volumes are archived; default this install's
#   AISC_SECRETS_FILE            the secrets file; default env.secrets in the checkout
#   BACKUP_HELPER_IMAGE          the image that reads and writes the volumes; default postgres:15-alpine, which
#                                every install already has
#
# Nothing it prints is a secret: no value of the secrets file and no passphrase is ever printed.
set -uo pipefail
umask 077

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
# shellcheck source=SCRIPTDIR/lib/stack-name.sh
. "$ROOT/scripts/lib/stack-name.sh"

VOLUMES="immudb_data immudb_key minio_data"
HELPER=${BACKUP_HELPER_IMAGE:-postgres:15-alpine}

usage() {
  echo "usage: bash scripts/backup-databases.sh [--dir DIR] [--keep N] [--no-restore-check | --restore-check-only]" >&2
  exit 2
}

DIR=${AISC_BACKUP_DIR:-}
KEEP=14
BACKUP=1
CHECK=1
while [ $# -gt 0 ]; do
  case $1 in
    --dir) [ $# -ge 2 ] || usage; DIR=$2; shift 2 ;;
    --keep) [ $# -ge 2 ] || usage; KEEP=$2; shift 2 ;;
    --no-restore-check) CHECK=0; shift ;;
    --restore-check-only) BACKUP=0; shift ;;
    *) usage ;;
  esac
done
case $KEEP in ''|*[!0-9]*|0) echo "--keep takes a number of 1 or more" >&2; exit 2 ;; esac
STACK=${BACKUP_STACK:-$(aisc_stack)}
[ -n "$DIR" ] || DIR="$HOME/aisc-backups/$STACK"

# A backup folder inside the checkout would put dumps beside the code, where a git add or a copy of the folder
# takes them along: refused, before anything is made.
case $DIR in /*) ABS=$DIR ;; *) ABS="$PWD/$DIR" ;; esac
case "$ABS/" in
  "$ROOT"/*) echo "the backup folder must be outside the checkout ($ROOT): $DIR" >&2; exit 2 ;;
esac
mkdir -p "$DIR" || exit 2
chmod 700 "$DIR"

PG=${BACKUP_PG_CONTAINER:-$(aisc_container postgres)}
SU=${POSTGRES_USER:-}
if [ -z "$SU" ] && [ -f "$ROOT/env.runtime" ]; then
  SU=$(awk 'index($0, "POSTGRES_USER=") == 1 { sub(/\r$/, ""); print substr($0, 15); exit }' "$ROOT/env.runtime")
fi
SECRETS=${AISC_SECRETS_FILE:-$ROOT/env.secrets}
PASSFILE=${AISC_BACKUP_PASSPHRASE_FILE:-$HOME/.config/aisc/backup-passphrase}
COUNTS_QUERY=$(cat "$ROOT/scripts/lib/table-counts.sql")

FAILED=0
fail() { echo "FAIL: $*"; FAILED=1; }

# One stamp per run, later than every file already there, so two runs within a second never share names
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
while ls "$DIR"/*_"$STAMP".* >/dev/null 2>&1; do sleep 1; STAMP=$(date -u +%Y%m%dT%H%M%SZ); done

newest() { # part, extension: the newest file of that part in DIR, or nothing
  # shellcheck disable=SC2012
  ls -1 "$DIR/$1"_2*."$2" 2>/dev/null | sort | tail -n 1
}

prune() { # part, extension, extensions beside it
  local part=$1 ext=$2 old other
  shift 2
  # shellcheck disable=SC2012
  ls -1 "$DIR/$part"_2*."$ext" 2>/dev/null | sort -r | tail -n +"$((KEEP + 1))" | while read -r old; do
    rm -f "$old"
    for other in "$@"; do rm -f "${old%."$ext"}.$other"; done
  done
}

# --------------------------------------------------------------------------------------------- the databases

databases() {
  docker exec "$PG" psql -X -At -U "$SU" -d postgres -c \
    "SELECT datname FROM pg_database WHERE NOT datistemplate AND datname <> 'postgres' ORDER BY 1"
}

backup_database() { # db
  local db=$1 inside="/tmp/aisc-backup-counts-$1" dump="$DIR/${1}_$STAMP.dump"
  if ! docker exec -i -e BACKUP_USER="$SU" -e BACKUP_DB="$db" "$PG" \
      psql -X -q -At -U "$SU" -d "$db" -v counts_file="$inside" -v counts_query="$COUNTS_QUERY" -f - \
      < "$ROOT/scripts/lib/backup-one.sql" > "$dump.part"; then
    rm -f "$dump.part"
    docker exec "$PG" rm -f "$inside" >/dev/null 2>&1
    fail "$db was not dumped"
    return
  fi
  docker exec "$PG" cat "$inside" > "${dump%.dump}.counts"
  docker exec "$PG" rm -f "$inside" >/dev/null 2>&1
  mv "$dump.part" "$dump"
  echo "dumped $db"
}

compare_counts() { # name, backed-up counts, restored counts: one FAIL line per table that differs
  awk -F'\t' -v name="$1" '
    NR == FNR { kept[$1] = $2; next }
    { got[$1] = $2 }
    END {
      bad = 0
      for (t in kept) if (!(t in got) || kept[t] != got[t]) { print "FAIL: " t " " kept[t] " " ((t in got) ? got[t] : "missing"); bad = 1 }
      for (t in got) if (!(t in kept)) { print "FAIL: " t " missing " got[t]; bad = 1 }
      exit bad
    }' "$2" "$3"
}

CHECK_PG=""
check_database() { # db
  local db=$1 dump counts restored
  dump=$(newest "$db" dump)
  counts=${dump%.dump}.counts
  if [ -z "$dump" ] || [ ! -f "$counts" ]; then fail "$db has no dump with its counts in $DIR"; return; fi
  if [ -z "$CHECK_PG" ]; then
    # shellcheck source=SCRIPTDIR/lib/throwaway-pg.sh
    . "$ROOT/scripts/lib/throwaway-pg.sh"
    TPG_OWN_TRAP=1 tpg_start backup-check >/dev/null 2>&1 || { fail "no throwaway Postgres for the restore check"; return; }
    CHECK_PG=$TPG_NAME
  fi
  docker exec "$CHECK_PG" psql -X -q -U "$TPG_SU" -d platform -c "DROP DATABASE IF EXISTS \"check\"" -c "CREATE DATABASE \"check\"" >/dev/null 2>&1
  if ! docker exec -i "$CHECK_PG" pg_restore -U "$TPG_SU" -d check --no-owner --no-privileges < "$dump" >/dev/null 2>&1; then
    echo "restore-check $db FAIL"
    fail "$db: pg_restore reported errors"
    return
  fi
  restored=$(mktemp "$DIR/.restored.XXXXXX")
  docker exec -i "$CHECK_PG" psql -X -q -At -v ON_ERROR_STOP=1 -U "$TPG_SU" -d check \
    -v counts_query="$COUNTS_QUERY" -f - <<< ':counts_query \gexec' > "$restored"
  if compare_counts "$db" "$counts" "$restored"; then
    echo "restore-check $db PASS"
  else
    echo "restore-check $db FAIL"
    FAILED=1
  fi
  rm -f "$restored"
}

# ------------------------------------------------------------------------------------------------ the volumes

# what a volume holds, one line per entry: name, mode, owner, kind (a link with its target), then each file's hash
MANIFEST='cd /v && find . -print0 | sort -z | xargs -0 -r stat -c "%N %a %u %g %F" && find . -type f -print0 | sort -z | xargs -0 -r sha256sum'

PAUSED=""
unpause() {
  if [ -n "$PAUSED" ]; then
    # shellcheck disable=SC2086
    docker unpause $PAUSED >/dev/null 2>&1
    PAUSED=""
  fi
}

backup_volume() { # short name
  local short=$1 full="${STACK}_$1" archive="$DIR/${1}_$STAMP.tar.gz"
  if ! docker volume inspect "$full" >/dev/null 2>&1; then
    echo "no volume $full: nothing of $short to back up"
    return
  fi
  PAUSED=$(docker ps -q --filter "volume=$full" | tr '\n' ' ')
  # shellcheck disable=SC2086
  [ -z "$PAUSED" ] || docker pause $PAUSED >/dev/null
  if docker run --rm -v "$full:/v:ro" "$HELPER" sh -c "$MANIFEST" > "${archive%.tar.gz}.manifest" \
      && docker run --rm -v "$full:/v:ro" "$HELPER" tar --numeric-owner -C /v -cf - . | gzip > "$archive.part"; then
    unpause
    mv "$archive.part" "$archive"
    echo "archived $short"
  else
    unpause
    rm -f "$archive.part" "${archive%.tar.gz}.manifest"
    fail "$short was not archived"
  fi
}

check_volume() { # short name
  local short=$1 archive scratch got
  archive=$(newest "$short" tar.gz)
  if [ -z "$archive" ]; then
    # a volume the stack does not have has no archive: nothing to check
    docker volume inspect "${STACK}_$short" >/dev/null 2>&1 && fail "$short has no archive in $DIR"
    return
  fi
  scratch="aisc-t-backup-check-$(date +%s)-$$-$short"
  docker volume create "$scratch" >/dev/null
  got=$(mktemp "$DIR/.restored.XXXXXX")
  if gzip -dc "$archive" | docker run -i --rm -v "$scratch:/v" "$HELPER" tar --numeric-owner -C /v -xpf - \
      && docker run --rm -v "$scratch:/v:ro" "$HELPER" sh -c "$MANIFEST" > "$got" \
      && cmp -s "$got" "${archive%.tar.gz}.manifest"; then
    echo "restore-check $short PASS"
  else
    echo "restore-check $short FAIL"
    fail "$short: the restored volume differs from what was archived"
  fi
  rm -f "$got"
  docker volume rm -f "$scratch" >/dev/null 2>&1
}

# ----------------------------------------------------------------------------------------- the secrets file

passphrase_source() { # the openssl -pass argument, or nothing when there is no passphrase
  if [ -n "${AISC_BACKUP_PASSPHRASE:-}" ]; then
    echo "env:AISC_BACKUP_PASSPHRASE"
  elif [ -s "$PASSFILE" ]; then
    echo "file:$PASSFILE"
  fi
}

ENC="-aes-256-cbc -pbkdf2 -iter 600000 -md sha256"

backup_secrets() {
  local pass copy="$DIR/secrets_$STAMP.enc"
  if [ ! -f "$SECRETS" ]; then fail "no secrets file at $SECRETS"; return; fi
  pass=$(passphrase_source)
  if [ -z "$pass" ]; then
    fail "the secrets file was not backed up: put a passphrase in $PASSFILE (or set AISC_BACKUP_PASSPHRASE)"
    return
  fi
  # shellcheck disable=SC2086
  if openssl enc $ENC -salt -pass "$pass" -in "$SECRETS" -out "$copy.part"; then
    mv "$copy.part" "$copy"
    echo "encrypted the secrets file"
  else
    rm -f "$copy.part"
    fail "the secrets file was not encrypted"
  fi
}

check_secrets() {
  local copy pass
  copy=$(newest secrets enc)
  if [ -z "$copy" ]; then fail "no secrets copy in $DIR"; return; fi
  pass=$(passphrase_source)
  if [ -z "$pass" ]; then fail "no passphrase to open the secrets copy ($PASSFILE)"; return; fi
  # shellcheck disable=SC2086
  if [ "$(openssl enc -d $ENC -pass "$pass" -in "$copy" 2>/dev/null | openssl dgst -sha256 -r)" \
      = "$(openssl dgst -sha256 -r < "$SECRETS")" ]; then
    echo "restore-check secrets PASS"
  else
    echo "restore-check secrets FAIL"
    fail "the secrets copy does not open to the secrets file"
  fi
}

# ------------------------------------------------------------------------------------------------------ run

# shellcheck disable=SC2329  # run by the EXIT trap
cleanup() {
  unpause
  rm -f "$DIR"/*.part "$DIR"/.restored.* 2>/dev/null
  [ -z "$CHECK_PG" ] || docker rm -fv "$CHECK_PG" >/dev/null 2>&1
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

DBS=""
if [ "$BACKUP" = 1 ]; then
  if ! DBS=$(databases); then
    fail "cannot list the databases of $PG"
    DBS=""
  fi
  for db in $DBS; do backup_database "$db"; prune "$db" dump counts; done
  for v in $VOLUMES; do backup_volume "$v"; prune "$v" tar.gz manifest; done
  backup_secrets
  prune secrets enc
else
  # shellcheck disable=SC2012
  DBS=$(ls -1 "$DIR" 2>/dev/null | sed -n 's/^\(.*\)_2[0-9]\{7\}T[0-9]\{6\}Z\.dump$/\1/p' | sort -u)
fi

if [ "$CHECK" = 1 ]; then
  for db in $DBS; do check_database "$db"; done
  for v in $VOLUMES; do check_volume "$v"; done
  check_secrets
fi

[ "$FAILED" = 0 ] && echo "backup in $DIR: every part passed" || echo "backup in $DIR: some parts FAILED"
exit "$FAILED"
