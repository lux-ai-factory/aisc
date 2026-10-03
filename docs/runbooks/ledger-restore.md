# Runbook: the ledger after an immudb restore

Spec: `docs/superpowers/ledger-2026-10-02/02-spec.md` 7.3 (T21). Phase 4 version: the re-anchor
route exists (`POST /ledger/reanchor`); the locked archive (phase 10) doesn't yet.

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
   - As a platform admin, first read what each server holds now: `GET /api/ledger/projects` lists, for
     every project and for the platform log, `server_head` (`{tx, hash}`, not trusted yet) next to
     `trusted_head` (what the platform verified) and `head` (or the alarm). Compare `server_head`
     with the backup you restored, and put it in the decision record.
   - **The platform log first**, if it was restored too: `POST /api/ledger/reanchor
     {"pid": "platform", "expected_head": <its server_head>}`. Each re-anchor is recorded in the
     platform log, so that log must be trusted before it can take the others' records.
   - Then each project: `POST /api/ledger/reanchor {"pid": "<pid>", "expected_head": <its
     server_head>}`. The record (`ledger.reanchored`, both heads, who) is written first; if the
     platform log can't take it, nothing changes and the answer is 409. If the server moved since you
     looked, the answer is 409 too: look again.
   - By hand only if the platform itself can't run, in the platform database as `platform_rw`.
     Nothing records it, so the decision record is the only trace:
     ```sql
     -- keep the old anchor in the decision record first
     SELECT db, tx_id, encode(tx_hash, 'hex') FROM ledger.state WHERE db = '<db>';
     DELETE FROM ledger.state WHERE db = '<db>';
     ```
4. **Know what restarts.** After the re-anchor the log's numbering continues from the restored
   head, so numbers that existed before the restore are given again to new entries. From phase 4
   the read index is keyed by (project, seq): its rows above the restored head must be moved aside
   (kept, marked "lost in restore") before the relay writes again.
5. **Expect the gap.** Entries written after the backup was taken are gone from immudb. Until
   phase 10, the published heads only prove they existed. From phase 10, rebuild them from the locked
   archive (`archive.rebuild`).
6. Run the verifier (phase 3 onwards) and check that the project's later events are delivered.

## First sight

A database with no saved state trusts what the server says the first time it is read. With immudb's
signing key on, that state is signed by the server; from then on the anchor only moves forward.

## Drill (phase 1, done 2026-10-02)

On throwaway containers: write to a database, keep the verified state, replace the server with an
older copy, read. Expected: `TamperAlarm`. Then delete the state row, read again: accepted, a new
anchor. See `docs/superpowers/ledger-2026-10-02/10-phase1-report.md`.

## Turning on immudb's signing key

Order matters. First start immudb with `--signingKey` (`IMMUDB_SIGNINGKEY`), then give the platform its
public half (`LEDGER_IMMUDB_PUBLIC_KEY`). A platform holding a public key while the server doesn't
sign raises `TamperAlarm` on every read ("malformed signature"): it fails closed, as it should.
