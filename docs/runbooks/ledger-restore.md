# Runbook: the ledger after an immudb restore

Spec: `docs/superpowers/ledger-2026-10-02/02-spec.md` 7.3 (T21). Phase 1 version: the re-anchor
route (`POST /ledger/reanchor`, phase 4) and the locked archive (phase 10) don't exist yet.

## What you will see

The platform keeps the last verified state of every ledger database in `ledger.state` (platform
database). After immudb is restored from an older copy, the first read of each restored database
fails verification:
- a restored copy **shorter** than what was verified answers gRPC `INVALID_ARGUMENT "illegal
  state"` (spike M13);
- a copy with a **different** history fails as `ErrCorruptedData` (M14).

Both surface as `TamperAlarm`. The ledger keeps refusing to read or append to that database until
the state is re-anchored. Nothing is lost on the apps' side: events wait in the outboxes (I6).

## What to do

1. **Make sure it is a restore, not tampering.** Who restored what, from which backup, and why. If
   nobody did, stop: treat it as an incident.
2. **Record the decision**: who decided, the backup's time, and the databases affected.
3. **Re-anchor** each affected database, so the platform trusts the restored server from now on:
   - From phase 4: an admin calls `POST /ledger/reanchor {"pid": ...}`, which records
     `ledger.reanchored` with the old and the new head in the platform log.
   - Until then, by hand, in the platform database as `platform_rw`. Delete the state, and the next
     read takes the server's current state as the new anchor:
     ```sql
     -- keep the old anchor in the decision record first
     SELECT db, tx_id, encode(tx_hash, 'hex') FROM ledger.state WHERE db = '<db>';
     DELETE FROM ledger.state WHERE db = '<db>';
     ```
4. **Expect the gap.** Entries written after the backup was taken are gone from immudb. Until
   phase 10, the published heads only prove they existed. From phase 10, rebuild them from the locked
   archive (`archive.rebuild`).
5. Run the verifier (phase 3 onwards) and check that the project's later events are delivered.

## Drill (phase 1, done 2026-10-02)

On throwaway containers: write to a database, keep the verified state, replace the server with an
older copy, read. Expected: `TamperAlarm`. Then delete the state row, read again: accepted, a new
anchor. See `docs/superpowers/ledger-2026-10-02/10-phase1-report.md`.
