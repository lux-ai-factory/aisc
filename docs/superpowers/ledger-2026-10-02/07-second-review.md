**Verdict: phase 0b can start; phase 1 can't yet. Open: 0 blocker, 6 major, 19 minor.**

The 6 open majors are 5 new ones (N1 to N5) plus review finding 6.2, which is only partly closed. Ten more majors from the first review are partly closed, with what's left scheduled in later phases (section 2). The 19 minors are 12 new ones and 7 left over from the first review, with some overlap.

# Ledger: second independent review (2026-10-02)

Reviewer: fresh context, read-only, `feat/unified-modules` at aab31e5. I read 01 to 06, `spike/Caddyfile.reference`, every file under `platform/tests/ledger/`, `scripts/tests/test_ledger_{coverage,caddy,gateway,credentials}.py`, `ledger_routes.py` and the gateway stub. I checked them against the compose files and the platform test conftest.

## What I ran

| Command | Result | Right reason? |
|---|---|---|
| `pytest --collect-only tests/ledger` (dummy DB URL) | 96 collected, 11 errors | The 11 errors are `No module named 'platform_service.ledger'`: right. The 96 come from `test_ledger_witness.py` and `test_ledger_outbox.py`, which collect fine. |
| The same two files with `LEDGER_TESTS_REQUIRED=1` | **96 skipped, 0 failed** | **Wrong.** See 6.2 below. |
| `test_ledger_{coverage,caddy,credentials}` with `LEDGER_TESTS_REQUIRED=1`, on today's Caddyfile | 24 failed, 6 passed | Right. Coverage fails on the missing registry module, Caddy on today's snippet, credentials on today's compose. The 6 that pass are guards (discovery, oauth endpoints, plugin runners). |
| Real-Caddy suite + Caddy text tests on `Caddyfile.reference` | 38 passed, 1 failed | Right. The one failure is `test_every_serving_handle_imports_protect_with_its_app`, which needs the registry. My `aisc-t-gw-*` containers were removed. Other `aisc-t-*` containers already on the host are not mine and I left them alone. |

## 1. The three blockers

| Finding | Status | Evidence |
|---|---|---|
| 1.1 app and project taken from paths | **Closed** | Spec `02-spec.md:85-92` and `117-131` (app from `X-AISC-App`, project from `X-AISC-Original-Uri`), project rules at `164-175`. The fixture `conftest.py:143-162` sends exactly what Caddy sends (stripped `X-Forwarded-Uri` plus the original URI). The witness tests cover each app's rule (`test_ledger_witness.py:163-187`) and refuse the stripped URI alone (`176-181`). On a real Caddy, `test_ledger_gateway.py:124-134` asserts app, unstripped URI, secret and token on all 7 write sites, and passes on the reference. |
| 1.2 witness callable by anyone | **Closed** | Threats T18 and T23 (`02-spec.md:70,75`), the strip (`87`), the launcher's `/api/authz/*` 404 (`106`). Tests: no, empty or wrong secret gives 401 with no id (`test_ledger_witness.py:55-61`); no configured secret gives 503 (`64-69`); an unknown pid creates no database (`190-198`); a stranger's request goes to the platform log (`201-204`); real Caddy answers 404 (`test_ledger_gateway.py:159-162`); only Caddy and the platform hold the secret (`test_ledger_credentials.py:12-18`). Small gap in minor n1. |
| 1.6 app-to-app writes | **Partly** | The mechanism is in: `caused_by` (`02-spec.md:193-196`), forwarded ids (`233-242`), and tests `test_ledger_relay.py:187-203` and `test_ledger_platform_events.py:85-98`. But rule 4.5 (`02-spec.md:261-263`) rejects the second event of the very submit that motivated it (see N3). Calls from the platform to the engine and the dashboard bridge have no test. As a functional blocker it is gone: the business write succeeds and only the ledger entry is rejected. |

## 2. The 30 majors of the first review

"Closed" means the spec says what to do and a test would fail if it weren't done.

| # | Status | Where |
|---|---|---|
| 1.3 forged request id | Closed | T19, the strip; C2 (`test_ledger_caddy.py:90-96`), G (`test_ledger_gateway.py:142-151`) |
| 1.4 two tokens | Closed | T20, spec 3.3; `test_ledger_witness.py:131-158` |
| 1.7 binding by shape only | Partly | Claim narrowed (spec section 0), item group, action id; tests `relay:115-148, 208-227`. The action-id rule is unsound (N3). |
| 1.8 AI runs | Closed | Spec 4.4; `test_ledger_internal.py:89-128`. The per-run limits asked for in review 1 aren't specified (minor). |
| 1.9 plugin environment | Partly | T17 says a test checks the plugin's child environment. The actual test only reads `environment:` keys in the dev compose files (`test_ledger_credentials.py:22-29`): no `env_file`, no `AISC_*_TOKEN`, no check of the `child_env` copy. |
| 1.10 apps with no project in the path | Partly | Engine header tested (`witness:184-187`). The dashboard bridge-table rule is untested, and the controls install entry outside `/p/` isn't addressed. |
| 1.11 witness on every request | Closed | Writes-only matcher plus `LEDGER_GATEWAY`; G tests `gateway:137-139, 165-174` |
| 1.12 token expiry | Partly | Leeway tested (`witness:124-128`). Nothing tests `--cookie-refresh=4m`. The 302 is tested only against the stub (minor n4). |
| 2.1 `occurred_at` set by apps | Closed | `ledger.emit` stamps it; `test_ledger_outbox.py:77-81` |
| 2.2 stale window | Closed | Spec 4.2 rule 7; `relay:161-182`, backlog case included |
| 2.4 platform outbox, delete | Closed | `core.outbox`, delete answers 409; `platform_events:100-119` |
| 2.5 privacy | Partly | I10 and PR1-PR4 exist, but the key design undoes them (N5) |
| 2.6 item chain, ordering | Closed | I11; `relay:327-343` |
| 2.7 concurrency | Closed | `store:100-117`, `relay:288-306` (the Postgres state store is untested, minor n12) |
| 2.9 backup and rotation | Partly | Re-anchor route tested (`routes` test, file lines 138-147). JWKS refetch on an unknown `kid`, the rotation overlap and the rebuild of `delivered` have no test. |
| 2.10 superuser deletes a log | Partly | `missing_database` is a field of the verify report, but no test before phase 10 |
| 3.1 database creation | Closed | Pool script, tests run as `aisc_ledger` (`store:152-166`). But see N1. |
| 3.3 ORM `RETURNING` | Closed | Void `ledger.emit`; `outbox:84-86` (real ORMs in phases 5 to 9) |
| 4.4 store tests | Closed | A unique database per test (`conftest.py:75-106`), duplicates, threads |
| 4.5 witness tests | Partly | All the listed gaps are filled except the dashboard and the platform's own 302 |
| 4.7 relay tests | Closed in content | But the suite can't run as written (N2) |
| 4.9 export without a trust root | Partly | Proofs and signed head tested only against `MemoryLedger.public_key_pem()` (`routes` test 106-128). immudb's real `--signingKey` is open item S3. |
| 4.12 discovery misses routes | Partly | Keyed by file and function, FAB views, `api_route`, re-exports all fixed. `PY_DIRS` (`ledger_routes.py:10-25`) is an allowlist, so a new app directory is never discovered. Superset's own APIs are still not considered. |
| 4.13 exception parser | Closed | TSV with an asserted 4-field shape (`coverage:41-49`) |
| 4.14 coverage only declarative | Closed | C4 (`coverage:117-129`); its heuristic is weak (minor n9) |
| 5.1 no real-Caddy test | Closed | G suite, passes on the reference |
| 5.2 I6 untested | Closed | F1-F3, relay with immudb down, witness with immudb down |
| 6.1 riskiest part last | Closed | `06-spike.md` |
| 6.2 skips can pass the DoD | **Partly (open major)** | `need()` (`conftest.py:40-45`) only covers immudb and the superuser URL. Nine Postgres suites use `pytestmark = needs_database`, a `skipif` set at import time (`tests/conftest.py:31`) that ignores `LEDGER_TESTS_REQUIRED`. I observed 96 skips and no failure with it set. Spec section 9 (`02-spec.md:490-493`) is not met. |
| 6.4 availability with the ledger off | Closed | `gateway:165-174` (off: the POST is still 200) |

Tally: 19 closed, 11 partly, 0 open.

## 3. New problems in v2

**N1 (major, must fix before phase 1). Database names contradict the pool.**
- Spec L1 and 7.1 (`02-spec.md:353-358, 435-440`): an operator pre-creates pool databases, and `provision.assign(pid)` hands one out.
- But `naming.database_name(pid)` is `"ledger" + pid hex` (`309-311`, `test_ledger_naming.py`). Every relay, privacy, platform-event and failure test reads entries from `database_name(project["pid"])`.
- A pool made before the project exists can't carry the project's pid, and immudb can't rename a database.
- The tests also can't pass as wired:
  - `memory_ledger` (`conftest.py:63-72`) is a fresh store with no databases.
  - It is swapped in after the `project` fixture has run (for example `test_ledger_relay.py:86`: `project, memory_ledger`).
  - `MemoryLedger` must refuse a database it never made (`store:82-85`).
  - So every append to the project's log raises `UnknownDatabase`, or the events wait forever.
- Fix, either way:
  - (a) tests look the database up with `provision.database_for(pid)`, and `memory_ledger` is created before `project` and provisions on `assign`; or
  - (b) the pool hands out pids (pre-allocated pid plus database), and the spec says so.

**N2 (major). Relay and internal suites set `enforce` before the project exists.**
- The autouse fixtures `_actions` (`test_ledger_relay.py:42-47`) and `_tokens` (`test_ledger_internal.py:23-27`) set `LEDGER_MODE=enforce`.
- pytest runs autouse fixtures first, so `project` (`conftest.py:115-124`) then does `POST /projects` with no request id.
- Spec 5.3 (`02-spec.md:296-297`) and P3 (`test_ledger_platform_events.py:69-73`) require a 401 there.
- So about 45 tests are unsatisfiable. The only other way to pass them is to exempt `POST /projects` from enforce, which is a hole. The `other_project` cases (`relay:132-134`, `internal:118-122`) do the same thing mid-test.
- Fix: set the mode after the project is created, or create projects through a witnessed call.

**N3 (major). Binding the action id on first use rejects legitimate events.**
- Spec 4.5 (`02-spec.md:261-263`): the first event action accepted for an action id wins, and any other action citing that id is rejected (`action_id`).
- That breaks three things:
  - (a) A step-1 submit causes both `qualification.created` and the platform's `card_version.created` (`01-event-registry.md:27,48`), both citing the same `Next-Action`.
  - (b) AI run events (`card.augmented_by_ai`, `agent.run_*`) cite the start request, whose action id is already bound to `card.ai_refinement_requested`. The test `internal:44-69` expects them accepted.
  - (c) A server action that saves and links in one call.
- R4, R5 and I1 all pass separately; a test combining two of them would fail.
- The binding is also per project and resets with each build, so a compromised app picks the binding on first use after every deploy. It detects a change of mind, nothing more.
- Fix: bind (app, action id) to the set of actions seen in the first request that used it; exempt run events and other apps' events from the rule; add the combined tests.

**N4 (major). Who computes keyed content digests contradicts itself.**
- I10 and `secrets.content_digest` (`02-spec.md:46, 316-318`) key digests with `PLATFORM_LEDGER_KEY`, which only the platform holds (`test_ledger_credentials.py:16`).
- Yet apps supply `content_sha256` in the outbox, and the relay checks it (`content_hash`).
- The relay test emits a plain `sha256_hex(content)` and expects acceptance (`relay:87-90`), and expects `"0"*64` rejected (`143-144`). The privacy test emits a keyed digest and expects acceptance (privacy test file lines 21-31).
- Only a check that accepts either digest passes both, and that would be a wrong implementation. `before_sha256` and `after_sha256` (I11) have the same problem: plain hashes of low-entropy states.
- Fix: apps send plain content; the platform computes every keyed digest; drop `content_sha256` from the outbox or keep it as a plain integrity check.

**N5 (major, phase 1 code). One global ledger key for three purposes.**
- **Erasure is reversible.** `actor_ref = HMAC(key, pid, sub)` is deterministic. Anyone with the key and a list of subjects (Keycloak, the member tables) can recompute it, so deleting the mapping row (`02-spec.md:474-476`) isn't crypto-shredding.
- **Rotation breaks old records.** T22 rotates the ledger key with a 24 h overlap (`74`). After that, ten years of refs and digests can't be checked (`MappingAlarm`, failed evidence checks), and there is no key id in `hmac:...`.
- **Auditors can't check content.** An offline auditor can't verify content digests without the key, and handing it over exposes every project.
- Fix:
  - `actor_ref` becomes a random id per (project, person). The mapping row carries an HMAC so a swapped row is still detected; deleting the row is then real erasure.
  - Per-project, per-purpose keys derived with HKDF.
  - Versioned prefixes (`hmac:v1:`), old keys kept for checking.
  - An export key per project for auditors.

**Minor:**
- **n1.** The W2 test is titled "leaves no record" but only checks that no id header comes back (`witness:55-61`). It would pass if the platform recorded the call and then answered 401.
- **n2.** Drift between documents:
  - Reasons `missing_request`, `run`, `run_window` and "no action id gives `action_id`" are in the tests, not in spec 4.2.
  - `ledger.witness` is in the platform DB (`02-spec.md:150`) but listed among the project-template tables (`410`).
  - `01-plan.md:72` still says "subject + name from the token".
  - The test plan says every platform file fails at collection; two collect and skip.
- **n3.** The delete rule "refuse while any row is undelivered" (`02-spec.md:415`): the DELETE's own witness record and the `project.deleted` row are always undelivered at that moment. Say "rows in the project database's outbox".
- **n4.** The 302 for a refused page load is implemented only in the test stub (`fixtures/ledger_gateway/stub.py:22-25`). No platform test checks that the witness answers 302.
- **n5.** The beacon:
  - The reference Caddyfile has no `/ledger/beacon` route on the main or dashboard site (R3.6); the main site's catch-all goes to the engine web app.
  - The project comes from the request body, with no membership test.
  - Each beacon's own witness record goes to immudb as `request.witnessed`, which leaks page-view timing against I10.
- **n6.** Any signed-in user's POST to any handle (the `/p/*` file server, the engine web app's catch-all) creates a permanent `request.witnessed` in the platform log and a "witnessed write with no event" alarm. There is no limit per person. Rate-limit the witness and decide D11 for app-less writes.
- **n7.** The credentials test ignores `env_file` (controls, control objectives) and the staging and production compose files. The staging Caddyfile lives outside the repo (`/home/deployer/config/caddy`), so neither 0b nor the G suite covers staging.
- **n8.** Two checks with no test:
  - The route half of R1.5: a controls request id presented to the platform's members route.
  - `X-AISC-Project` being ignored for apps other than the engine.
- **n9.** C4 and discovery heuristics:
  - TypeScript is matched on the whole file.
  - A Python match can come from a comment or docstring.
  - A handler that delegates to a service fails.
  - Inline `"use server"` functions, `/* */` file headers and Ninja's `api_operation` are missed.
- **n10.** No check ties registry read actions to the `protect-reads` paths in Caddy. A read action that Caddy doesn't list can never cite a witness. Paths for `handle_path` apps must be written stripped, and nothing says so.
- **n11.** `ledger.emit` repeats the platform-only list in SQL. `flower.request`, `pgadmin.request` and `request.unverified` aren't tested there.
- **n12.** `PostgresStateStore` (the production compare-and-set) has no test, and immudb's signing (S3) is untested.

Minors left over from the first review: 1.5, 1.14, 3.5, 3.6, 4.11 and 6.6 are partly closed; 2.13 (I5 baseline) is open and deferred. The other 22 are closed.

**Security points checked and found sound:**
- **Gateway secret.** It is set by `header_up` on the witness call only, after the strip, and the spike saw it reach no app. Caddy substitutes it at parse time into its admin config, which can only be read inside the container. Acceptable.
- **Forwarded ids.** They need the person's token with a matching `sub`. What remains (a compromised app replaying a person's token within the window) is residual risk 4 in spec section 10.
- **Reference Caddyfile.** Order is enforced by `route`, the strip runs first, and `/api/authz/*` returns 404 before `handle_path /api/*`.

## 4. Must fix, ranked

1. **N1** naming against the pool, and the memory ledger never provisioned: blocks phase 1, whose code is naming, pool and provision.
2. **N5** key design (erasure, rotation, auditor access): blocks phase 1, whose code is `secrets.py`.
3. **6.2** `needs_database` bypasses `LEDGER_TESTS_REQUIRED`: fix now, it's cheap. It blocks phase 2's Definition of Done.
4. **N2** enforce set before the project fixture: blocks phase 3 and 4 tests.
5. **N3** action-id binding on first use: blocks phase 3 (relay rule) and phase 5 (step-1 submit).
6. **N4** keyed content digests: blocks phase 3, and touches phase 1 `secrets`.

Phase 0b (header strip, empty witness snippets) depends only on C2, the G suite and K, which are consistent and pass on the reference, so it can start now. Minor n7 should be noted for the staging deploy, since the staging Caddyfile is outside the repo.
