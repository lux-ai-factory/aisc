# Runbook: back up, and restore from a backup

## What a backup holds

`bash scripts/backup-databases.sh` writes into `$HOME/aisc-backups/<stack>` (or `--dir DIR`, or
`AISC_BACKUP_DIR`; never inside the checkout), every file private, named `<part>_<UTC stamp>`:

| part | files | what it is |
|---|---|---|
| each database (platform, keycloak, superset, ledger_identity, every `project_*`) | `.dump`, `.counts` | `pg_dump -Fc`, and the row count of every table, from one snapshot |
| `immudb_data` | `.tar.gz`, `.manifest` | the ledger |
| `immudb_key` | `.tar.gz`, `.manifest` | the key immudb signs its states with |
| `minio_data` | `.tar.gz`, `.manifest` | run artifacts, datasets, proof files |
| `secrets` | `.enc` | `env.secrets`, encrypted: its keys open the stored LLM keys and engine credentials and verify the ledger |

Each run restores the newest of every part into a throwaway (a Postgres, a volume) and compares it: row counts
table by table, files by name, owner, mode and hash, the secrets file byte for byte. It prints
`restore-check <part> PASS` for each, and exits 0 only when all pass. The newest 14 of each part are kept
(`--keep N`). The containers that use a volume (immudb, MinIO) are paused for the seconds its archive takes.

## Before the first backup: the passphrase

The secrets copy is encrypted with a passphrase the backup reads from `$HOME/.config/aisc/backup-passphrase`
(another file: `AISC_BACKUP_PASSPHRASE_FILE`; the value itself: `AISC_BACKUP_PASSPHRASE`). Nothing makes it for
you. Make it once, private, and keep a copy somewhere other than this machine and the backup folder: without it
the secrets copy cannot be opened, and without the secrets nothing encrypted or signed can be read or verified.

```bash
mkdir -p ~/.config/aisc && (umask 077 && openssl rand -base64 32 > ~/.config/aisc/backup-passphrase)
```

Without it the backup still takes the databases and volumes, and fails naming the secrets file.

## Every day

`bash scripts/schedule.sh --print` shows two crontab lines: the backup at 02:30 and `scripts/verify.sh --stack` at
03:30, each through `scripts/scheduled.sh`, which writes `$HOME/aisc-logs/<stack>/<job>-YYYY-MM-DD.log` and keeps
30 days. `bash scripts/schedule.sh --install` puts them in your crontab; `--remove` takes them out again.

`uv run scripts/aisc.py remove` offers a backup before it deletes the volumes.

## Restore

A restore replaces what the stack holds: decide it, write down who decided and which backup, and stop the stack
first (`uv run scripts/aisc.py stop`). `S` is the stack (`aisc-<id>`), `B` the backup folder, `T` the stamp chosen.

1. **Check the backup first**, without touching the stack: `bash scripts/backup-databases.sh --dir "$B"
   --restore-check-only`. Every part must say PASS.
2. **The secrets file**, if it was lost:

   ```bash
   openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -md sha256 -pass file:$HOME/.config/aisc/backup-passphrase \
     -in "$B/secrets_$T.enc" -out env.secrets
   ```

3. **A volume** (`immudb_data`, `immudb_key`, `minio_data`): remove the damaged one and fill a new one.

   ```bash
   docker volume rm "${S}_minio_data" && docker volume create "${S}_minio_data"
   gzip -dc "$B/minio_data_$T.tar.gz" | docker run -i --rm -v "${S}_minio_data:/v" postgres:15-alpine \
     tar --numeric-owner -C /v -xpf -
   ```

   After `immudb_data` comes back from an older copy, the platform alarms on the ledger until it is re-anchored:
   follow [the ledger after an immudb restore](ledger-restore.md).
4. **A database**: start Postgres alone (`docker compose ... up -d postgres`), drop the damaged database, make it
   again and restore into it (owners and grants come with the dump; the roles exist in the stack):

   ```bash
   docker exec "${S}-postgres" sh -c 'psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE IF EXISTS platform" -c "CREATE DATABASE platform"'
   docker exec -i "${S}-postgres" sh -c 'pg_restore --exit-on-error -U "$POSTGRES_USER" -d platform' < "$B/platform_$T.dump"
   ```

5. **Count**: start the stack (`uv run scripts/aisc.py start`), then `bash scripts/verify.sh --stack`.

`scripts/tests/test_backup_restore_real_services.py` runs these steps on a throwaway immudb, MinIO and Postgres
and counts the ledger entries, objects and rows after the restore.
