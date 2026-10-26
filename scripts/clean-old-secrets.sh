#!/usr/bin/env bash
# Old plaintext plugin secrets out of the engine's stores and the platform's ledger copies.
#
#   scripts/clean-old-secrets.sh [--scrub-config-text] [--project PID]...   dry run (the default): counts only
#   scripts/clean-old-secrets.sh --apply --backup-dir DIR [--keep-backup] [--scrub-config-text] [--project PID]... [--reason TEXT]
#   scripts/clean-old-secrets.sh --backup-only --backup-dir DIR [--project PID]...
#   scripts/clean-old-secrets.sh --delete-backup FOLDER
#
# The dry run prints what each side would change and the keys to rotate (by plugin and field, never a value).
# Free text in a stored plugin configuration (a prompt) that may hold a key is not changed: its fields are listed
# under "Review these fields", apart from the keys to rotate. --scrub-config-text has the engine scrub them too
# (they are then counted, changed and listed with the keys to rotate).
# --apply: refuses without a backup folder outside the repository and a passphrase; stops with "nothing to
# clean" when the counts are zero; checks the free disk; writes an encrypted backup of the tables it changes
# (one file per database, AES-256-CBC, PBKDF2 600000 iterations); cleans the engine (manage.py
# clean_old_secrets apply), then the platform (python -m platform_service.ledger.secret_cleanup apply);
# counts again; exports each redacted project's log and checks it with verify-ledger-export.py; deletes the
# backup once that passed, unless --keep-backup.
#
# AISC_CLEANUP_BACKUP_PASSPHRASE (16 characters or more) is read by openssl from the environment, never
# from a command line, and never printed. A dump is decrypted only into a pipe, never onto disk.
#
# Overrides (tests, second installs): CLEAN_SECRETS_PG_CONTAINER, CLEAN_SECRETS_ENGINE_CMD,
# CLEAN_SECRETS_PLATFORM_CMD, CLEAN_SECRETS_CHECKER (split into words, never evaluated),
# CLEAN_SECRETS_PUBLIC_KEY, CLEAN_SECRETS_EXTRA_FREE_BYTES (default 1 GiB).
#
# Exit: 0 done; 1 verification failed (backup kept); 2 usage or a refused precondition; 3 not enough disk;
# 4 backup failed (nothing changed); 5 a clean step failed (backup kept).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$ROOT/scripts/lib/stack-name.sh"

usage() {
  sed -n '4,7p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
}

refuse() { # message
  echo "$1" >&2
  exit 2
}

MODE=dry
BACKUP_DIR=""
KEEP=0
DELETE_FOLDER=""
REASON=""
PROJECT_ARGS=()
ENGINE_FLAGS=()
PIDS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) MODE=apply ;;
    --backup-only) MODE=backup ;;
    --keep-backup) KEEP=1 ;;
    --scrub-config-text) ENGINE_FLAGS+=(--scrub-config-text) ;;
    --backup-dir) [ $# -ge 2 ] || usage; BACKUP_DIR=$2; shift ;;
    --project) [ $# -ge 2 ] || usage; PROJECT_ARGS+=(--project "$2"); PIDS+=("$2"); shift ;;
    --reason) [ $# -ge 2 ] || usage; REASON=$2; shift ;;
    --delete-backup) [ $# -ge 2 ] || usage; MODE=delete; DELETE_FOLDER=$2; shift ;;
    -h|--help) usage ;;
    *) echo "unknown argument: $1" >&2; usage ;;
  esac
  shift
done

# The commands: an override is split into words, never evaluated
if [ -n "${CLEAN_SECRETS_ENGINE_CMD:-}" ]; then
  read -r -a ENGINE_CMD <<< "$CLEAN_SECRETS_ENGINE_CMD"
else
  ENGINE_CMD=(docker exec -i "$(aisc_container aisc-backend-ledger)" uv run manage.py clean_old_secrets)
fi
if [ -n "${CLEAN_SECRETS_PLATFORM_CMD:-}" ]; then
  read -r -a PLATFORM_CMD <<< "$CLEAN_SECRETS_PLATFORM_CMD"
else
  PLATFORM_CMD=(docker exec -i "$(aisc_container platform)" python -m platform_service.ledger.secret_cleanup)
fi
if [ -n "${CLEAN_SECRETS_CHECKER:-}" ]; then
  read -r -a CHECKER_CMD <<< "$CLEAN_SECRETS_CHECKER"
else
  CHECKER_CMD=(python3 "$ROOT/scripts/verify-ledger-export.py")
fi
PG=${CLEAN_SECRETS_PG_CONTAINER:-$(aisc_container postgres)}
PUBLIC_KEY=${CLEAN_SECRETS_PUBLIC_KEY:-$ROOT/immudb-signing.pub}
EXTRA_FREE=${CLEAN_SECRETS_EXTRA_FREE_BYTES:-1073741824}

PROJECT_TABLES="engine.aisc_backend_ledgeroutbox engine.aisc_backend_pluginconfig engine.aisc_backend_evaluationplugin"
PLATFORM_TABLES="core.outbox ledger.content"

engine() { # count|apply
  "${ENGINE_CMD[@]}" "$1" ${ENGINE_FLAGS[@]+"${ENGINE_FLAGS[@]}"} ${PROJECT_ARGS[@]+"${PROJECT_ARGS[@]}"}
}

platform() { # count|apply
  if [ "$1" = apply ] && [ -n "$REASON" ]; then
    "${PLATFORM_CMD[@]}" apply ${PROJECT_ARGS[@]+"${PROJECT_ARGS[@]}"} --reason "$REASON"
  else
    "${PLATFORM_CMD[@]}" "$1" ${PROJECT_ARGS[@]+"${PROJECT_ARGS[@]}"}
  fi
}

ENGINE_OUT=""
PLATFORM_OUT=""
counts() { # sets ENGINE_OUT and PLATFORM_OUT
  if ! ENGINE_OUT=$(engine count); then
    printf '%s\n' "$ENGINE_OUT"
    echo "the engine's count failed; nothing changed" >&2
    exit 5
  fi
  if ! PLATFORM_OUT=$(platform count); then
    printf '%s\n' "$PLATFORM_OUT"
    echo "the platform's count failed; nothing changed" >&2
    exit 5
  fi
}

anything_to_change() { # text: some to-change count is above zero (scan-only counts do not count)
  printf '%s\n' "$1" \
    | grep -Eo '(rows_to_mask|rows_to_change|fields_to_drop|rows_to_scrub|rows_to_redact|events_to_append)=[0-9]+' \
    | awk -F= '$2 > 0 { found = 1 } END { exit !found }'
}

print_rotate() { # text...
  local lines
  lines=$(printf '%s\n' "$@" | grep ': rotate ' || true)
  if [ -n "$lines" ]; then
    echo "Rotate these keys, they were stored in clear:"
    printf '%s\n' "$lines"
  fi
  lines=$(printf '%s\n' "$@" | grep ': review ' || true)
  if [ -n "$lines" ]; then
    echo "Review these fields (text that may contain a key; not changed):"
    printf '%s\n' "$lines"
  fi
}

# Files that held secrets (backups, exports) are overwritten before they are removed. Without shred they are only
# removed, and the output says so once.
NO_SHRED_SAID=0
shred_files() { # files...
  local f
  for f in "$@"; do
    [ -e "$f" ] || continue
    if command -v shred >/dev/null 2>&1; then
      shred -u "$f"
    else
      if [ "$NO_SHRED_SAID" = 0 ]; then
        echo "shred is not available: files are removed with rm, not overwritten first"
        NO_SHRED_SAID=1
      fi
      rm -f "$f"
    fi
  done
}

delete_backup() { # folder
  local folder=$1 name entry
  name=$(basename "$folder")
  case "$name" in
    aisc-secrets-backup-*) ;;
    *) refuse "not a backup folder: $folder" ;;
  esac
  [ -d "$folder" ] || refuse "no such folder: $folder"
  for entry in "$folder"/* "$folder"/.[!.]*; do
    [ -e "$entry" ] || continue
    case "$(basename "$entry")" in
      *.dump.enc) [ -f "$entry" ] || refuse "not a backup folder: $folder" ;;
      verify) if [ ! -d "$entry" ] || [ -n "$(ls -A "$entry")" ]; then refuse "not a backup folder: $folder"; fi ;;
      *) refuse "not a backup folder: $folder" ;;
    esac
  done
  shred_files "$folder"/*.dump.enc
  [ -d "$folder/verify" ] && rmdir "$folder/verify"
  rmdir "$folder"
  echo "backup deleted"
}

if [ "$MODE" = delete ]; then
  delete_backup "$DELETE_FOLDER"
  exit 0
fi

if [ "$MODE" = dry ]; then
  counts
  echo "== engine =="
  printf '%s\n' "$ENGINE_OUT"
  echo "== platform =="
  printf '%s\n' "$PLATFORM_OUT"
  print_rotate "$ENGINE_OUT" "$PLATFORM_OUT"
  echo "dry run: nothing changed. Run with --apply --backup-dir DIR to clean."
  exit 0
fi

# 1. Refusals: nothing is done
if [ -z "$BACKUP_DIR" ]; then
  if [ "$MODE" = apply ]; then refuse "--apply needs --backup-dir"; else refuse "--backup-only needs --backup-dir"; fi
fi
REAL_DIR=$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$BACKUP_DIR")
REAL_ROOT=$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$ROOT")
case "$REAL_DIR/" in
  "$REAL_ROOT/"*) refuse "the backup folder must be outside the repository" ;;
esac
PASSPHRASE=${AISC_CLEANUP_BACKUP_PASSPHRASE:-}
if [ "${#PASSPHRASE}" -lt 16 ]; then
  refuse "set AISC_CLEANUP_BACKUP_PASSPHRASE (16 characters or more) in this shell first"
fi
PASSPHRASE=""
command -v openssl >/dev/null 2>&1 || refuse "openssl is needed for the encrypted backup"

# 2. Counts: nothing to clean, no backup
if [ "$MODE" = apply ]; then
  counts
  if ! anything_to_change "$ENGINE_OUT" && ! anything_to_change "$PLATFORM_OUT"; then
    echo "nothing to clean"
    exit 0
  fi
fi

FOLDER=""
backup_failed() {
  [ -n "$FOLDER" ] && [ -d "$FOLDER" ] && rm -rf "$FOLDER"
  echo "backup failed; nothing changed" >&2
  exit 4
}

pg_query() { # db sql: one answer per line
  docker exec -i "$PG" psql -X -q -v ON_ERROR_STOP=1 -tA -U "$PG_USER" -d "$1" -c "$2"
}

tables_present() { # db tables...: those that exist, space separated
  local db=$1 list="" t
  shift
  for t in "$@"; do
    list="$list${list:+,}'$t'"
  done
  pg_query "$db" "SELECT t FROM unnest(ARRAY[$list]) AS t WHERE to_regclass(t) IS NOT NULL ORDER BY t" | tr '\n' ' '
}

# The databases and their tables
PG_USER=$(docker exec "$PG" printenv POSTGRES_USER 2>/dev/null) || backup_failed
[ -n "$PG_USER" ] || backup_failed
if [ ${#PIDS[@]} -gt 0 ]; then
  DATABASES=""
  for pid in "${PIDS[@]}"; do
    DATABASES="$DATABASES project_$(printf '%s' "$pid" | tr -d '-' | tr 'A-F' 'a-f')"
  done
else
  DATABASES=$(pg_query postgres "SELECT datname FROM pg_database WHERE datname ~ '^project_[0-9a-f]{32}\$' ORDER BY 1" \
    | tr '\n' ' ') || backup_failed
fi
DATABASES="platform $DATABASES"

# 3. Disk: twice the tables' size plus a margin, on / and on the backup folder's disk
df -h /
SIZE=0
for db in $DATABASES; do
  if [ "$db" = platform ]; then tables=$PLATFORM_TABLES; else tables=$PROJECT_TABLES; fi
  present=$(tables_present "$db" $tables) || backup_failed
  for t in $present; do
    bytes=$(pg_query "$db" "SELECT pg_total_relation_size('$t')") || backup_failed
    SIZE=$((SIZE + bytes))
  done
done
NEED=$((2 * SIZE + EXTRA_FREE))
(umask 077 && mkdir -p "$BACKUP_DIR")
FREE_ROOT=$(df -Pk / | awk 'NR == 2 { print $4 }')
FREE_DIR=$(df -Pk "$BACKUP_DIR" | awk 'NR == 2 { print $4 }')
FREE_ROOT=$((FREE_ROOT * 1024))
FREE_DIR=$((FREE_DIR * 1024))
if [ "$FREE_ROOT" -lt "$NEED" ] || [ "$FREE_DIR" -lt "$NEED" ]; then
  echo "not enough free disk: need $NEED bytes, / has $FREE_ROOT, $BACKUP_DIR has $FREE_DIR" >&2
  exit 3
fi

# 4. Backup: one encrypted file per database, checked by listing it through a pipe
umask 077
FOLDER="$BACKUP_DIR/aisc-secrets-backup-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -m 700 "$FOLDER" || backup_failed
COUNT=0
for db in $DATABASES; do
  if [ "$db" = platform ]; then tables=$PLATFORM_TABLES; else tables=$PROJECT_TABLES; fi
  present=$(tables_present "$db" $tables) || backup_failed
  [ -n "${present// /}" ] || continue
  args=()
  n=0
  for t in $present; do
    args+=(-t "$t")
    n=$((n + 1))
  done
  file="$FOLDER/$db.dump.enc"
  docker exec "$PG" pg_dump -Fc -U "$PG_USER" -d "$db" "${args[@]}" \
    | openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -salt -pass env:AISC_CLEANUP_BACKUP_PASSPHRASE -out "$file" \
    || backup_failed
  chmod 600 "$file"
  listed=$(openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -pass env:AISC_CLEANUP_BACKUP_PASSPHRASE -in "$file" \
    | docker exec -i "$PG" pg_restore --list | grep -c ' TABLE DATA ') || backup_failed
  [ "$listed" -eq "$n" ] || backup_failed
  COUNT=$((COUNT + 1))
done
echo "backup: $FOLDER ($COUNT databases, encrypted)"

if [ "$MODE" = backup ]; then
  echo "backup kept at $FOLDER: delete it with --delete-backup once it is no longer needed"
  exit 0
fi

# 5. Clean: the engine, then the platform; a failure keeps the backup
if ! ENGINE_APPLIED=$(engine apply); then
  printf '%s\n' "$ENGINE_APPLIED"
  echo "clean step failed; backup kept at $FOLDER"
  exit 5
fi
echo "== engine =="
printf '%s\n' "$ENGINE_APPLIED"
if ! PLATFORM_APPLIED=$(platform apply); then
  printf '%s\n' "$PLATFORM_APPLIED"
  echo "clean step failed; backup kept at $FOLDER"
  exit 5
fi
echo "== platform =="
printf '%s\n' "$PLATFORM_APPLIED"

# 6. Verify: the counts are zero, and each redacted project's export checks
VERIFIED=1
counts
if anything_to_change "$ENGINE_OUT" || anything_to_change "$PLATFORM_OUT"; then
  echo "verify: counts are not zero"
  VERIFIED=0
else
  echo "verify: counts are zero"
fi
REDACTED_PIDS=$(printf '%s\n' "$PLATFORM_APPLIED" \
  | awk '$1 == "project" && $3 == "ledger.content" { split($4, kv, "="); if (kv[2] > 0) { sub(":$", "", $2); print $2 } }')
for pid in $REDACTED_PIDS; do
  mkdir -p -m 700 "$FOLDER/verify"
  file="$FOLDER/verify/$pid.jsonl"
  if ! "${PLATFORM_CMD[@]}" export "$pid" > "$file"; then
    echo "verify: project $pid could not be exported"
    shred_files "$file"
    VERIFIED=0
    continue
  fi
  chmod 600 "$file"
  if "${CHECKER_CMD[@]}" --public-key "$PUBLIC_KEY" --project "$pid" "$file"; then
    echo "verify: project $pid export ok"
  else
    echo "verify: project $pid export does not check"
    VERIFIED=0
  fi
  shred_files "$file"
done
[ -d "$FOLDER/verify" ] && rmdir "$FOLDER/verify"

# 7. The backup: deleted once verified, unless kept
if [ "$VERIFIED" = 1 ] && [ "$KEEP" = 0 ]; then
  shred_files "$FOLDER"/*.dump.enc
  rmdir "$FOLDER"
  echo "backup deleted"
else
  echo "backup kept at $FOLDER: delete it with --delete-backup once it is no longer needed"
fi

# 8. The keys to rotate
print_rotate "$ENGINE_APPLIED" "$PLATFORM_APPLIED"
[ "$VERIFIED" = 1 ] || exit 1
exit 0
