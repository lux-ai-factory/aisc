# Ledger: phase 1 report, the core (2026-10-02)

Phase 1 of `03-coding-plan.md`. Commits on `feat/unified-modules` (aisc, local, not pushed):
- 37c9502: phase 0 closed (the ten-year archive, decision L3);
- 059f111 and d64acfb: the core;
- 5183f74: the fixes from the review (`11-phase1-review.md`);
- the last commit of the day: the re-review's minors (`12-phase1-rereview.md`) and this report.

Nothing touches the running stack. All tests and drills ran on throwaway containers
(`aisc-t-ledger-*`: postgres:14-alpine, and codenotary/immudb:1.11.1 started with a signing key).

## What was built

| Part | File | What it does |
|---|---|---|
| settings | `platform/platform_service/ledger/settings.py` | every number the rules use, named once |
| naming | `naming.py` | random pool names (`ledger` + 32 hex), the platform log, a strict check before any immudb call |
| canonical JSON | `canonical.py` | RFC 8785; cross-checked against node on 19,997 random doubles (and by the reviewer on 70,000), 0 differences |
| registry | `registry.py` | the required actions with unstripped cause paths, `origin`, runs, `check()`; standard library only |
| keys | `secrets.py` | HKDF-SHA256 per project and purpose from versioned master keys; `hmac:v<N>:` digests; old versions keep checking |
| state | `state.py` | the verified immudb state outside immudb (memory, and Postgres `ledger.state`), compare-and-set |
| store | `store.py` | the contract on memory and on immudb (key-value only): one client per database; write preconditions against two writers; re-login after a lost session; signed states; deadlines; error classes |
| pool | `pool.py`, `scripts/ledger-pool.sh` | the operator's step: only the superuser makes databases; the platform never holds its password |
| provision | `provision.py` | a project takes a pool database of the current server, inside its creation's transaction; never blocked when immudb is down |
| schema | `init/platform-db.sql`, `init/project-databases.sql`, migration `0006` | schema `ledger` owned by `platform_rw`; tables `ledger.pool` and `ledger.state` |
| secrets | `scripts/secrets.sh` | `LEDGER_IMMUDB_PASSWORD`, `PLATFORM_LEDGER_KEYS` (both kept by `--rotate`), `--add-ledger-key` |
| runbook | `docs/runbooks/ledger-restore.md` | after an immudb restore; turning on the signing key |

## Tests (all with `LEDGER_TESTS_REQUIRED=1`: a skip is a failure)

| Suite | Result | Skips |
|---|---|---|
| `platform/tests/ledger/test_ledger_{canonical,naming,registry,secrets,store,provision,cleanup,pool_cli}.py` | 266 passed | 0 |
| `scripts/tests/test_{secrets_hardening,ledger_pool_script,compose,dashboard_bridge_token}.py` | 55 passed | 0 |
| platform suite without `tests/ledger` | 579 passed, 1 failed, 2 skipped (pre-existing) | 2 |

**Known failures, none caused by the ledger:**
- `platform/tests/test_targets_sync.py::test_tg2_the_callers_token_goes_to_qualification_both_ways`
  is flaky on token timing. Run alone it failed 2 of 3 runs on HEAD, and 2 of 4 runs on 37c9502,
  before any ledger code.
- `scripts/tests/test_llm_keys.py::test_s3_1_both_copies_exist_and_are_byte_identical`: the two
  `baf_llm.py` copies diverged on 2026-09-30 (qualification 31c5b1e, temperature handling). This is
  not a ledger change; it is left for the owner of step 2.
- The ledger files of later phases are committed red, as written ahead: `test_ledger_{witness,
  outbox,relay,platform_events,internal,beacon,routes,privacy,failure,provision_flow}.py`. They fail
  at collection or at the missing package. A plain `pytest tests` stops on them, so run the
  phase-1 files by name.
- Two `core.system` migration tests were pinned to `upto="0005"`. They replay old layouts without
  postgres-setup, and the ledger's 0006 isn't their subject. In production the platform waits for
  postgres-setup (`service_completed_successfully`).

## Drills

**1. immudb restarted in the middle of 60 appends, on one store throughout** (the first version of
this drill created a fresh store per retry, which hid review blocker B1; this one doesn't):
`docker restart` 1 s in. Results:
- 11 attempts failed, all `LedgerUnavailable`, and the same store recovered on its own;
- 60 entries, numbered 1 to 60 with no gap, each event exactly once.

The reviewer repeated it: 233 accepted, 233 in the log, contiguous.

**2. A real restore from an older backup.** Setup:
- 3 entries written;
- a consistent snapshot taken (container paused, `/var/lib/immudb` copied);
- 7 more written;
- the server replaced by a new container started from the snapshot, at the same address.

Results:
- the first read raised `TamperAlarm` ("illegal state");
- after the runbook's re-anchor by hand (the state row deleted), the head read 3 and entry 3 read
  back.

**Two writers** (review B2), from the reviewer:
- 2 stores in threads × 50: 100 accepted, 100 logged;
- 3 separate processes × 50: 150 logged, contiguous.

## Settled on the way
- **S1** (Caddy `{args[1:]}`), **S3** (signed states, tested with a real key and a wrong one), **S7**
  (the server's UUID from a login-free `Health` call).
- **The catalogue's events left the required list**, as spec 3.1 scopes the hosted catalogue out.

## Not done in phase 1, and why
- **Rotating the immudb superuser password committed in `env.development`.** The engine backend and
  the dashboard use it on the running stack, so changing it is a deploy, and it needs your yes.
- **D8, immudb in staging and production compose.** The staging compose isn't on the unified
  platform at all (it doesn't even mount `init/platform-db.sql`). This waits until staging is moved.
- **Turning on `--signingKey` in the development compose.** The code and the test are done; enabling
  it is a deploy. Follow the order in the runbook.
- **The ledger settings in the platform's compose** (`LEDGER_IMMUDB_URL`, `LEDGER_IMMUDB_PASSWORD`,
  `PLATFORM_LEDGER_KEYS`). This is wired in phase 3, when the platform first writes to the ledger.

## Open for later phases (from the reviews)
- **Phase 3:**
  - S8: whether `inspector_ro`, through `pg_read_all_data`, may read `ledger.actor` and
    `ledger.witness`;
  - `registry.check` callers;
  - deadlines on the relay.
- **Phases 5 to 9:** registry causes to correct against the real routes:
  - the fill route is GET, not POST;
  - `/system/edit` also serves the step-1 form;
  - controls install is `/controls/install`;
  - actions to add: the objective library, report templates, controls sources, `dialog.cancelled`.

  C1 will flag the missing ones.
- **Minors left on purpose:**
  - `--add-ledger-key` saves the key before the rest of the run;
  - `_mac` turns non-bytes into text;
  - two writers appending the same event id at once has no dedicated test.
