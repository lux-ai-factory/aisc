# Runbook: old plaintext plugin secrets, cleaned on a live stack

Before plugin configuration secrets were masked at save, they were stored in clear in five places:

| Where | Database | What the cleanup does |
|---|---|---|
| `engine.aisc_backend_ledgeroutbox` (configuration events) | each project database | masks the config as a ledger copy |
| `engine.aisc_backend_pluginconfig` (stored configurations) | each project database | drops the secret fields (the form shows them empty) |
| `engine.aisc_backend_evaluationplugin.error_message` (failure text) | each project database | redacts key shapes and `password=...` values |
| `core.outbox` (the platform's copy of the events) | `platform` | masks the config as a ledger copy |
| `ledger.content` (frozen contents) | `platform` | removes the content, marks the row redacted, and appends a `ledger.content.redacted` entry naming it to the project's log |

No migration rewrites these rows: the cleanup changes stored data, so it runs only on an operator's word,
through `scripts/clean-old-secrets.sh`. New events are masked when they are saved, and an older undelivered
engine event is masked when it is sent, so nothing new needs this.

Removing the copies does not make an exposed key safe. Every key the dry run lists is rotated at its provider.

## Before you start

- You have the user's yes for this cleanup on this stack, and the stack runs a version with
  `manage.py clean_old_secrets`, `platform_service.ledger.secret_cleanup` and platform migration `0014`.
- Stop at the first failure, keep every backup, and report.

## Steps

1. **Disk.** `df -h /`. Below 5 GB free: stop and report. Never prune.
2. **Dry run.** `scripts/clean-old-secrets.sh` (add `--project PID` to narrow it). It prints, per project
   database and per project, what would change, and the keys to rotate by plugin and field
   (`rotate plugin=... field=...`, `rotate item=... field=...`), never a value. Note the rotation list.
   Read the fields the engine would drop from stored configurations: a field that is not a secret (a long
   column name under a name ending in `key`, say) would be dropped too. If one is listed, stop and decide
   before going on.
3. **Backup, apply, verify.** In a shell where the passphrase is set (16 characters or more, kept outside
   the repository and never pasted into a chat or a ticket):

   ```
   export AISC_CLEANUP_BACKUP_PASSPHRASE=...   # typed, or read from a password manager
   scripts/clean-old-secrets.sh --apply --keep-backup --backup-dir ~/aisc-secret-backups
   ```

   The folder must be outside every repository. The script checks the disk (twice the tables' size plus
   1 GiB on `/` and on the backup's disk), writes one encrypted dump per database into
   `~/aisc-secret-backups/aisc-secrets-backup-<time>/` (mode 0700, files 0600), checks each dump lists its
   tables, cleans the engine, then the platform, counts again (every to-change count must be 0), exports
   each redacted project's log and checks it with `scripts/verify-ledger-export.py` (the ok line ends with
   `N frozen content(s) redacted, each named by a ledger.content.redacted entry`).

   Exit codes: 0 done; 1 verification failed (backup kept); 2 refused (no folder, folder inside the
   repository, passphrase missing or short); 3 not enough disk; 4 backup failed (nothing changed); 5 a
   clean step failed (backup kept). Anything but 0: stop and report with the printed lines.
4. **Run it again.** `scripts/clean-old-secrets.sh --apply --backup-dir ~/aisc-secret-backups` must print
   `nothing to clean` and make no backup.
5. **Delete the backup** once the runs and the report are checked (the backup holds the very secrets that
   were removed): `scripts/clean-old-secrets.sh --delete-backup ~/aisc-secret-backups/aisc-secrets-backup-<time>`.
   Without `--keep-backup` in step 3, the script deletes its backup itself once verification passed.
6. **Rotate** every key of the step 2 list at its provider, plus the LangBiTe judge keys, and record which
   were rotated.
7. **Report**: the counts per store, the verifier lines, and the keys rotated by plugin and field.

## Restoring from the backup

Only if a clean step went wrong, and only after deciding it with the user. Decrypt into a pipe, never onto
disk; this lists what a dump holds:

```
openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -pass env:AISC_CLEANUP_BACKUP_PASSPHRASE \
  -in <folder>/<db>.dump.enc | docker exec -i <postgres container> pg_restore --list
```

and the same pipe into `pg_restore -U <user> -d <db>` with the options the decision calls for restores it. A
restored `ledger.content` row comes back with its content and without its mark, while the
`ledger.content.redacted` entry naming it stays in the append-only log; run the script again afterwards.
