**Verdict: 0 open blockers, 0 open majors, 3 minors left over from the phase 1 review, 9 new minors. Phase 1 can be called done, apart from the items that need you, once one document is written: the phase report `10-phase1-report.md`.** That file is still missing. It should hold the skip counts and the restore drill's evidence, and the runbook already points to it.

## What I ran
I used my own throwaway containers `aisc-t-rev6-70ed66-{pg,immudb}`, with immudb started with a signing key. They are removed now. I never touched the running stack or the `aisc-t-ledger-7406c8` containers.
- **Phase 1 ledger tests** (canonical, naming, registry, store, provision, cleanup, pool_cli, secrets): 264 passed, 0 skipped, with `LEDGER_TESTS_REQUIRED=1`.
- **Script tests** (`test_ledger_pool_script.py`, `test_secrets_hardening.py`): 13 passed.
- **Rest of the platform suite** (`tests` without `tests/ledger`): 580 passed, 2 skipped, in 22 minutes. A first run showed 55 failures, but that was my mistake: `python` wasn't on PATH. With the venv on PATH everything passed.
- **The new tests on the old code** (the 3d70163 code with 5183f74's tests on top, in scratch): 13 platform tests and 4 script tests fail, so every new test catches what it was written for. One exception: the Postgres rollback test passes on the old code too. That's fine, because it adds coverage (M2) rather than proving a fix.

## 1. The findings from the phase 1 review

| Item | Status | Where | Fails without the fix? |
|---|---|---|---|
| B1, immudb restart | **fixed** | `store.py:326-342`, `_session_lost` `:441` | Yes. The test logs the client out to simulate a restart. My probes used a real `docker restart`: append, restart, then append again on the same store gives one `LedgerUnavailable` and then seq 2. A second probe appended non-stop through a restart and retried each event until it was accepted: 233 accepted, 233 in the log, numbers contiguous, no duplicates, nothing missing. |
| B2, two writers | **fixed** | `store.py:370-391`, `_set_new` `:423` | Yes. My probes: 2 stores in threads × 50 appends gave 100 accepted and 100 logged. 3 separate processes × 50 gave 150 logged, contiguous. immudb answers `FAILED_PRECONDITION "precondition failed: KeyMustNotExist"`, which matches the check. |
| M1, false alarms with shared state | **fixed** | `store.py:252-265` | Yes. My probe, a reader and a writer on one Postgres state: 211 reads, 0 alarms. |
| M2, Postgres state untested | **fixed** | `state.py:76` now also compares the signature; tests at `test_ledger_store.py:262-293` | The compare-and-set test fails on the old code. The rollback test passes on both, see above. |
| M3, pool script env | **fixed** | `scripts/ledger-pool.sh:16-25` | Yes, both script tests. The platform service already gets `PLATFORM_DATABASE_URL` from `docker-compose.development.yml:821`. |
| M4, assign needs immudb | **fixed, with a residual** (new minor 2) | `provision.py:45-48`; `store.py:287-290` (5 s deadline) | Yes. |
| Minor 1, `_classify` | partly fixed | `store.py:452-461` | No dedicated test. A login answer coded UNKNOWN still becomes `UnknownDatabase` (new minor 7). |
| Minor 2, MemoryLedger differences | mostly fixed | `store.py:150-154` | Yes. A lost login still isn't simulated. |
| Minor 3, first sight | fixed | spec 6.1 and the runbook's "First sight" section | Docs only. |
| Minor 4 | no defect | | |
| Minors 5, 6, 7 | open, owned by later phases | | |
| Minor 8, `registry.check` crash | fixed | `registry.py:319-329` | Yes, 5 cases. |
| Minor 9, `inspector_ro` | recorded as open item S8 | spec | Decide before phase 3. |
| Minor 10, `--add-ledger-key` | partly fixed | `secrets.sh:104-123` | Yes, 2 tests. See new minors 1 and 8. |
| Minor 11, stale references | partly fixed | | The 0006 header is fixed. The runbook still cites the missing `10-phase1-report.md`. |
| Minor 12, seq reuse after a restore | fixed | runbook step 4 | Docs only. |
| Minor 13, weak tests | mostly fixed | | Two-store, restart, Postgres state, guard message and the "cannot create a database" test are added. Still untested: two assigns of the same pid at once. |

The S3 test (`test_ledger_store.py:337`) really exercises the signature check. A store given the wrong public key gets `BadSignatureError`, which becomes `TamperAlarm`.

## 2. New problems the fixes introduced (all minor)

I checked the concerns you listed:
- **The no-alarm path in `_StateAdapter.set` does not hide a real rollback.** In immudb-py's `verifiedGet` (`handler/verifiedGet.py:46-59`), the new state's tx is the larger of the stored tx (at read time) and the entry's tx. So "older than stored" can only mean another worker moved the shared state on. A real rollback is caught earlier. My probes: a stored state ahead of the server gives `illegal state` on both `get` and `append`, with no write. A wrong hash at the same tx gives `ErrCorruptedData`.
- **Re-login does not hide a real auth failure.** Probe: restart immudb and change the password, then append. The result is `LedgerCredentials`.

New minors:
1. **The ledger settings never reach the platform container.** The compose files have no `LEDGER_*` and no `PLATFORM_LEDGER_KEYS` at all. So the message "restart the platform to use it" is still not true end to end, even though `env.runtime` now carries the key. Wiring belongs to phase 3, but the message should say so.
2. **`from_environment` (`store.py:473`) uses `os.environ["LEDGER_IMMUDB_PASSWORD"]`.** If the URL is set but the password isn't, it raises a `KeyError`. `assign` only catches `LedgerError`, so this would block project creation (an M4 residual).
3. **Only `Health` has a deadline.** Login, `Set` and `VerifiableGet` have none, so a black-holed immudb hangs the caller (the relay, in phase 3). Also, a failed `server_id` isn't cached, so each `assign` waits up to 5 s while immudb is down.
4. **`_StateAdapter.set` gives up silently in two cases.** It skips a state with the same tx but a different hash (a forked server; the next read still alarms). It also returns without a word after losing the compare-and-set 5 times. Both are harmless; a log line would help.
5. **Order matters when enabling signing.** If `LEDGER_IMMUDB_PUBLIC_KEY` is set but the server doesn't sign, the result is `TamperAlarm` ("Malformed formatting of signature"). That fails closed, which is right, but the runbook should say: turn on server signing first, then give the platform the key.
6. **No free number after 50 tries raises a plain `LedgerError`**, not something the caller knows to retry. Two writers appending the same event id at once take a path that has no test.
7. **`_classify(login=True)` still turns any UNKNOWN or NOT_FOUND login answer into `UnknownDatabase`.** Probe results: a bad password is UNKNOWN and is caught first; an unknown database is NOT_FOUND; a missing grant is PERMISSION_DENIED. Any other UNKNOWN at login is misnamed.
8. **`--add-ledger-key` saves the key before the plain run that follows.** If that run then fails (realm render, `setfacl`, the cookie length check), `env.secrets` has the new key but `env.runtime` is stale, and the "added" message has already printed. Also, the shell check accepts a duplicate version, which `secrets.py` then refuses.
9. **`secrets._mac` turns non-bytes into text with `str()`**, so `digest(pid, p, 1)` equals `digest(pid, p, "1")`. That's harmless while every caller passes canonical bytes.
10. **Note: later-phase test files are committed in `tests/ledger`** (relay, beacon, privacy, provision_flow) and fail at collection (`verify` doesn't exist yet). They are tests written ahead of their phases. A plain `pytest tests` stops on them, so the report should name them as known failures.

## 3. Definition of Done still open (03-coding-plan.md)
- **The phase report.** `10-phase1-report.md` is missing: the skip counts, the evidence for both drills, and the known failures from point 10. My probes show the restart drill now passes.
- **Coverage tests (C4) for what phase 1 covers.** I didn't check them separately.
- **Your items, outside this verdict:** rotating the committed immudb superuser password; D8 (staging and production compose); turning on `--signingKey` in the dev compose (a deploy). The S3 code and test are done.

Probe scripts are in the scratchpad: `rev6_probe.py` (B1, B2, M1, auth, restart during appends) and `rev6_err.py` (error texts and how they are classified).
