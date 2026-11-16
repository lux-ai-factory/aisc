# Runbook: a security incident

## Who decides

The stack's operator (the realm `admin`) decides each step below and records it.

## Contain

Stop what is affected (`docker stop` the container) and keep its logs.

## Rotate

- An infrastructure password: `scripts/rotate-infra-password.sh NAME`.
- The stack's other secrets: `uv run scripts/aisc.py secrets --rotate`, then restart the stack.
- Old plaintext plugin secrets: `scripts/clean-old-secrets.sh` (see `docs/runbooks/clean-old-secrets.md`).

## Restore

From the last backup taken before the incident: `docs/runbooks/restore-a-backup.md`; then the ledger:
`docs/runbooks/ledger-restore.md`.

## Notify

Tell the owners of the affected projects what was exposed, and when.

## Record in the ledger

Declare every change made by hand to a project's data with `POST /api/ledger/corrections` (admin), so it is
`operator.correction.declared` in that project's log.
