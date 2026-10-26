# Runbook: old plaintext plugin secrets, cleaned on a live stack

Before plugin configuration secrets were masked at save, they were stored in clear in five places:

| Where | Database | What the cleanup does |
|---|---|---|
| `engine.aisc_backend_ledgeroutbox` (configuration events) | each project database | masks the config as a ledger copy |
| `engine.aisc_backend_pluginconfig` (stored configurations) | each project database | drops the secret fields (the form shows them empty), a URL with credentials included; free text that may hold a key, such as a prompt, is left as it is and listed for review (changed only with `--scrub-config-text`) |
| `engine.aisc_backend_evaluationplugin.error_message` (failure text) | each project database | redacts key shapes and key-like `password=...` values |
| `core.outbox` (the platform's copy of the events) | `platform` | masks the config as a ledger copy |
| `ledger.content` (frozen contents) | `platform` | removes the content, marks the row redacted, and appends a `ledger.content.redacted` entry naming it to the project's log |

A secret is found by its field name (header fields such as `Authorization`, `X-Api-Key` and `Cookie` included)
and by its shape: provider key prefixes, `Bearer`, `Basic` and `Token` credentials (16 characters or more), the
`user:password` of a URL, PEM private keys, and `password=...` style assignments, with a prefixed or camelCase
name too (`DB_PASSWORD=`, `judgeApiKey=`) and URL-encoded, whose value looks like a key (it holds a digit, or is
16 characters or more in mixed case). A dict or list under a secret name (`api_keys: {openai: ...}`) counts as one
secret. A secret field of a stored configuration is dropped, never replaced by a placeholder the plugin would run
with. Not caught: base64-encoded keys, keys split across lines, and a password that reads like a word or a
quoted passphrase of several words.

Stored free text is different: a prompt or a rubric is what the plugin runs with, and prose can look like a key
(`password: see the policy`). So a text field of a stored configuration is never rewritten by default. When the
text rule finds something in one, the dry run lists it under its own heading,
`Review these fields (text that may contain a key; not changed):` (`review plugin=... field=... configs=N`),
never under the keys to rotate. Copies and records (the outboxes, the frozen contents, the failure text) keep using
the text rule.

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
   Read the fields the engine lists for stored configurations (`rotate ... configs=` lines): each is dropped.
   A field that is not a secret (a long column name under a name ending in `key`, say) would be dropped too. If
   one is listed, stop and decide before going on.
   Then read the `Review these fields (text that may contain a key; not changed):` list. Each is a text field
   (a prompt, a rubric) the cleanup leaves as it is. Look at each one in the plugin's configuration form. If the
   text holds a key, either remove the key in the form, or, when every listed field holds a real key and nothing
   in them is prose the plugin needs as it is, run the dry run again with `--scrub-config-text` and use that
   option in step 4 too: the listed fields then have their keys replaced by `[redacted]`, are counted as
   changed, and move to the keys to rotate. If any listed field is only prose that looks like a key, do not use
   the option.
3. **First live run only: check what the tests could not.** The tests ran the script with stand-in commands
   and the platform's in-memory ledger. On the live stack, check before any `--apply`:
   - the default commands work: the dry run of step 2 used them as they are
     (`docker exec <stack>-aisc-backend-ledger uv run manage.py clean_old_secrets`,
     `docker exec <stack>-platform python -m platform_service.ledger.secret_cleanup`, names from
     `scripts/lib/stack-name.sh`). Both sections printed their lines and the script exited 0; a
     `failed project_...` line or a missing section means a command does not work: stop and report.
   - the immudb export checks: pick one project the dry run lists with `rows_to_redact` above 0, export its
     log into a private file outside the repository, check it, and shred the file (it holds the project's
     content keys):

     ```
     umask 077; mkdir -p ~/aisc-secret-backups; f=~/aisc-secret-backups/check-$PID.jsonl
     docker exec <stack>-platform python -m platform_service.ledger.secret_cleanup export $PID > "$f"
     python3 scripts/verify-ledger-export.py --public-key immudb-signing.pub --project $PID "$f"
     shred -u "$f"
     ```

     The ok line must say `format immudb, signed; frozen contents checked`. Anything else: stop and report;
     the script's own verification (step 4) relies on this check.
4. **Backup, apply, verify.** In a shell where the passphrase is set (16 characters or more, kept outside
   the repository and never pasted into a chat or a ticket):

   ```
   export AISC_CLEANUP_BACKUP_PASSPHRASE=...   # typed, or read from a password manager
   scripts/clean-old-secrets.sh --apply --keep-backup --backup-dir ~/aisc-secret-backups
   # only when step 2 decided it: ... --apply --keep-backup --scrub-config-text --backup-dir ~/aisc-secret-backups
   ```

   The folder must be outside every repository. The script checks the disk (twice the tables' size plus
   1 GiB on `/` and on the backup's disk), writes one encrypted dump per database into
   `~/aisc-secret-backups/aisc-secrets-backup-<time>/` (mode 0700, files 0600), checks each dump lists its
   tables, cleans the engine, then the platform, counts again (every to-change count must be 0), exports
   each redacted project's log and checks it with `scripts/verify-ledger-export.py` (the ok line ends with
   `N frozen content(s) redacted, each named by a ledger.content.redacted entry`).

   Exit codes: 0 done; 1 verification failed (backup kept); 2 refused (no folder, folder inside the
   repository, passphrase missing or short); 3 not enough disk; 4 backup failed (nothing changed); 5 a
   clean step failed (backup kept). Anything but 0: stop and report with the printed lines. If the platform
   step printed `the ledger raised an integrity alarm`, the log does not verify: do not run the cleanup again
   before the log is checked. A line `shred is not available` means the export and backup files were removed
   with `rm` only; say so in the report.
5. **Run it again.** `scripts/clean-old-secrets.sh --apply --backup-dir ~/aisc-secret-backups` must print
   `nothing to clean` and make no backup.
6. **Delete the backup** once the runs and the report are checked (the backup holds the very secrets that
   were removed): `scripts/clean-old-secrets.sh --delete-backup ~/aisc-secret-backups/aisc-secrets-backup-<time>`.
   Without `--keep-backup` in step 4, the script deletes its backup itself once verification passed.
7. **Rotate** every key of the step 2 list at its provider, plus the LangBiTe judge keys and any key found in a
   reviewed text field, and record which were rotated.
8. **Report**: the counts per store, the verifier lines (step 3 and step 4), the keys rotated by plugin and
   field, and the reviewed text fields with what was decided for each.

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
