**Verdict: 2 blockers, 4 majors, 13 minors. Phase 1 can't be called done.** The phase's own tests pass (231 passed, 0 skipped, `LEDGER_TESTS_REQUIRED=1`, on my own `aisc-t-rev5-*` containers, now removed). Probes against a real immudb found two defects the tests don't exercise, and several Definition of Done items are still open.

## What I ran
- The phase 1 files (`test_ledger_{canonical,naming,registry,store,provision,cleanup,pool_cli}.py`): 231 passed, no skips. `scripts/tests/test_secrets_hardening.py`: 8 passed.
- The rest of the platform suite takes more than 15 minutes and was cut off by my timeout, so I can't say whether it is green.
  - One run with `-x` stopped on `test_dashboard_bridge.py::test_s11_5_...`.
  - That test passes alone, on HEAD and on the base commit 37c9502. It looks order-dependent, not caused by the ledger, but I haven't confirmed that.
- Probe scripts are in the scratchpad (`rev5_probe.py`, `rev5_restart.py`, `rev5_pgstate.py`, `rev5_canon.py`).

## Blockers

**B1. After an immudb restart the store never recovers** (`store.py` `_client`, `_call`, `_classify`).
- Probe: append, `docker restart` the immudb container, append again with the same store. 20 tries over 40 s all fail with `LedgerError: ... not logged in`.
- The cached client is never dropped or logged in again. The error is a plain `LedgerError`, not `LedgerUnavailable`, so a caller can't even treat it as "wait and retry". Only a platform restart fixes it.
- This is the phase's own drill ("an immudb restart mid-append"), so the drill fails.
- Fix: on `UNAUTHENTICATED` or "not logged in", drop the client from `_clients`, log in again once and retry. Add a test that restarts immudb.

**B2. Two writers on one database lose events silently** (`ImmudbLedger.append`).
- The next seq comes from reading `seq:last`, then `setAll` overwrites `e:<seq>` with no check that it is still free.
- Probe: two `ImmudbLedger` instances, 50 appends each to one database. All 100 were acknowledged, only 50 are in the log. Replaying a lost event finds its `id:` key and returns success, so the loss is permanent and never reported. That is I3 broken in both directions.
- The spec relies on the relay's advisory lock (7.2). But the lock doesn't exist yet, `append` is public, and nothing in the store enforces it. Any second path that writes (the `ledger.reanchored` route, a second worker, a manual script) loses data.
- Fix: immudb 1.11 has per-write preconditions. immudb-py 1.5's `setAll` doesn't expose them, but the raw `SetRequest` does. Put `KeyMustNotExist` on `e:<seq>` and `id:<event_id>`; on a precondition failure, read again and retry. Add a two-store test.

## Majors

**M1. Concurrent readers raise false tamper alarms** (`_StateAdapter.set`).
- Two stores sharing one state store (two platform workers on `ledger.state`), one appending and one reading: 8 false `TamperAlarm`s in 60 reads ("the server proved an older state than was verified").
- An older but valid proof isn't tampering; it only means another worker moved the state forward. The compare-and-set `ValueError` also leaks out of `verifiedGet` as a generic `LedgerError`.
- Fix: if the new tx is not past the stored one, keep the stored state without raising. On a lost compare-and-set, read again and retry. A real alarm should come only from immudb's own verification failure.

**M2. `PostgresStateStore` is never tested.**
- The test plan's "the Postgres-kept state catches a rollback across stores" uses `MemoryStateStore`. So does the compare-and-set test.
- I ran its SQL by hand and it works. It differs from the memory version in one way: it ignores `signature` when comparing (memory compares the whole state).
- `ImmudbLedger` over Postgres, the production path, has no test at all.

**M3. `scripts/ledger-pool.sh` can't work on the compose stack as committed.**
- It runs `compose run platform`, but the `platform` service has no `LEDGER_IMMUDB_URL` or `LEDGER_IMMUDB_PASSWORD` in its environment. `--env-file` only feeds compose variable substitution, not the container. So `main()` exits 2 ("set ... first").
- `test_ledger_pool_cli.py` calls `python -m` directly, so it never runs the shell script.

**M4. Project creation needs immudb up** (`provision.assign`).
- `assign` calls `ledger.current().server_id`, which makes a gRPC `Health` call with no deadline. With immudb down it raises a raw `grpc._channel._InactiveRpcError`, not a ledger error; a black-holed host would hang.
- `current()` also raises when `LEDGER_IMMUDB_URL` isn't set. Once phase 3 wires `assign` into project creation, either case blocks creation, which breaks I6.
- Fix: cache the server id in `ledger.pool` or config, treat `LedgerUnavailable` as "pending", and set a deadline.

## Minors (owner in brackets)
1. `_classify` with `login=True` turns every login error that isn't UNAVAILABLE into `UnknownDatabase`, timeouts included. Matching any text containing "verification" as `TamperAlarm` is too broad. [phase 1]
2. MemoryLedger doesn't behave like immudb in three places: no lost-login case, it still appends after a rollback (immudb refuses), and it checks for an unknown database before the size cap (immudb the other way round). [phase 1]
3. First sight trusts the server's current state without saving or checking a signature (no signing key yet). This should be stated in the spec and the runbook. [phase 1 / S3]
4. Canonical JSON: no deviation found. 70k random doubles, plus strings and key order covering controls, U+2028, BOM, astral characters and DEL, all match node byte for byte. Nit: an `IntEnum` becomes the number. [none]
5. Registry, dead or wrong causes:
   - `card.ai_refinement_requested` names `POST .../fill`, but that route is `GET` only (a poll).
   - The step 1 form is also served at `/system/edit` (it renders `QualifyForm`), and that page isn't in `qualification.created` or `card_version.created`.
   - The control install page is `/controls/install`, not `/controls/p/{slug}/install`.
   - Nothing checks that `caused_by` patterns match real routes (C3 checks only `routes`). [phases 5 and 7]
6. Registry, missing actions:
   - control-objectives library: add, edit and retire objectives, delete a set, `DELETE api/sets`;
   - report-composer templates;
   - controls `sources/new`;
   - `dialog.cancelled` (spec 3.5).

   C1 will flag these. [phases 5 to 9]
7. Beacon cause: `page.*` names only `platform /api/ledger/beacon`, but spec 3.5 and 6.3 have a beacon on every site. [phase 4]
8. `registry.check` crashes when `details` isn't a dict or `action` can't be hashed. It should return a problem instead. [phase 3]
9. `inspector_ro` (pgAdmin, SchemaSpy) reads all of `ledger.*` through `pg_read_all_data`; confirmed with `has_table_privilege` and a real SELECT. Harmless for pool and state, but phase 3's `ledger.actor` and `ledger.witness` would be exposed. O1 puts `inspector_ro` among the roles with "no right at all", so it will be red by construction. [phase 3, needs a decision]
10. `--add-ledger-key` exits before `env.runtime` is rebuilt, so "restart the platform to use it" doesn't actually deliver the new key to compose. A malformed list would also get a second `v1`. The temp file isn't cleaned up on failure. No secret is printed, and `--rotate` keeps both ledger secrets (tested). [phase 1]
11. Stale or dangling references:
    - the 0006 header still cites the deleted `init/ledger-schema.sql`;
    - the runbook cites `10-phase1-report.md`, which isn't in the repo, so the restore drill is claimed but its evidence is missing.
    [phase 1]
12. After a restore, appends reuse seq numbers that existed before it, which collides with `event_index (project_pid, seq)`. The runbook should say so. [phases 3/4]
13. Tests that would pass on a wrong implementation:
    - the store tests have no two-store case (would have caught B2 and M1) and no restart case (B1);
    - `crash_after_appends` isn't used in L4;
    - the same-pid retry path in `assign` and the `conn=` savepoint path under conflict are untested;
    - nothing tests the 0006 guard message;
    - `test_the_ledger_user_cannot_create_a_database` passes because the login fails, not because database creation is refused;
    - `REQUIRED` in `test_ledger_registry.py` was edited during the green phase (catalogue events dropped). Spec 3.1 justifies it, but it should be stated.
    [phase 1]

**Checked and fine:**
- `FOR UPDATE SKIP LOCKED` with the partial unique index is safe; two assigns of one pid end in a unique violation and a retry.
- The savepoint path with `conn=` rolls back cleanly.
- Both init files `\connect platform` before creating the schema.
- Module roles have no USAGE on `ledger`.
- The upto="0005" pins are reasonable.
- Skips go through `need()`.

## Definition of Done items not met
- **S3** immudb `--signingKey`: not in compose, no test, `publicKey=b""`. The spec calls it "phase 1's first immudb test".
- **D8** immudb in staging and production compose: absent.
- **Rotating the committed immudb superuser password**: not done. `env.development` and `env.plugin_downloader` are tracked and unchanged, and the engine backend and the dashboard still hold the superuser password.
- **`ledger/secrets.py`** (HKDF `derive`, `digest`, `check`): listed in phase 1's code column, not built.
- **Drills**: the restart drill fails (B1); the restore drill's report is missing.
- **App suites green**: not shown. The full platform run didn't finish (see above).
- **Independent review with no open blocker or major**: not met (B1, B2, M1 to M4).

The fixes for B1, B2, M1 and M4 are all inside `store.py` and `provision.py`. They need the test cases listed in minor 13 written first, as failing tests.
