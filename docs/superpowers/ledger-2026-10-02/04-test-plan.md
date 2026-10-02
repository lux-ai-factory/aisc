# Ledger: test plan, version 2 (2026-10-02)

Every invariant (I1-I11) and threat (T1-T24) of `02-spec.md` v2 is covered by at least one test below.
Tests marked **written** exist now, and are red until their phase is built. Each is red for the right
reason, checked on 2026-10-02:
- the platform files fail at collection on `No module named 'platform_service.ledger'`;
- the gateway, Caddy and credential suites fail on today's Caddyfile and compose files;
- the gateway and Caddy suites pass on `spike/Caddyfile.reference`, so they can be satisfied.

## How to run

Every run below sets **`LEDGER_TESTS_REQUIRED=1`**: a missing service fails instead of skipping (spec
section 9).

- **Platform**, from `platform/`:
  1. A throwaway Postgres (recipe: `docs/superpowers/pipeline-2026-09-24-llm-keys/02-tests.md`
     section 3).
  2. A throwaway immudb:
     `docker run --rm -d --name aisc-t-immudb-$RANDOM -p 127.0.0.1:$PORT:3322 -e IMMUDB_ADMIN_PASSWORD=$PW codenotary/immudb:1.11.1`
     (the stack's pin).
  3. `LEDGER_TESTS_REQUIRED=1 LEDGER_TEST_IMMUDB_URL=127.0.0.1:$PORT LEDGER_TEST_IMMUDB_ADMIN_PASSWORD=$PW PLATFORM_TEST_DATABASE_URL=... PLATFORM_TEST_SUPERUSER_URL=... uv run --extra dev pytest tests/ledger`
- **Repo level**:
  `LEDGER_TESTS_REQUIRED=1 uvx --with pyyaml pytest scripts/tests/test_ledger_{coverage,caddy,gateway,credentials}.py`.
  The gateway suite starts its own `aisc-t-gw-*` containers (caddy:2.10.2 and stubs) and removes
  them. `LEDGER_TEST_CADDYFILE=<path>` runs the Caddy suites on another file.

## Phase 0b and 2: the gateway

| Id | Test | Covers | File |
|---|---|---|---|
| C2 | `protect` is `route { import strip-and-sign-in; import witness-{$LEDGER_GATEWAY} {args[0]} }`; the strip comes before sign-in; `witness-on`, `witness-reads-on` and the empty `-off` snippets; every serving handle imports `protect <app>` or `protect-reads <app> <path>...` with the expected app; refusing handles never serve; the launcher blocks `/api/authz/*` before its API | I1, T18, T19 | `scripts/tests/test_ledger_caddy.py` **written** |
| G | on a real caddy:2.10.2, with `LEDGER_GATEWAY` on and off: <ul><li>each site's write reaches the witness with its app, the unstripped URI, the secret and the person's token;</li><li>reads are not witnessed;</li><li>forged `X-AISC-*` and identity headers never reach an app;</li><li>`X-AISC-Project` is kept;</li><li>the launcher answers 404 to `/api/authz/witness`;</li><li>with the platform down, reads work, and writes fail only with the witness on;</li><li>a refused page load becomes a 302;</li><li>a listed read is witnessed</li></ul> | I1, I6, T18, T19, R5.1 | `scripts/tests/test_ledger_gateway.py` **written** |
| W1 | a write is witnessed in Postgres, with a fresh id and the person behind the `actor_ref`; immudb isn't touched | I1, I2 | `platform/tests/ledger/test_ledger_witness.py` **written** |
| W2 | no secret, an empty secret or a wrong secret: 401 with no record, even in `record`; no configured secret: 503; an unknown app: 400 | T18 | same **written** |
| W3 | `enforce`: a missing, malformed, foreign-key, foreign-issuer, expired, not-yet-valid or other-client (`azp`) token gives 401. `record`: 200 with an unverified record and a reason. Leeway; a Bearer token for the same person passes; for another person, 401 in `enforce` and `token_mismatch` in `record`; a forged Bearer gives 401 | T5, T20 | same **written** |
| W4 | the project from the unstripped path by each app's rule; the stripped URI alone is refused; the engine's `X-AISC-Project`; an unknown pid goes to the platform log and creates no database; a stranger's request never enters the project's log | T6, T23, I9 | same **written** |
| W5 | the query string is kept only as an HMAC; `Next-Action` is recorded; `off` gives no id | I8 | same **written** |
| W6 | the witness works while immudb is down | I6 | same **written** |
| K | each credential is held exactly by its holders; nothing that runs plugin code holds a ledger credential; Caddy has `LEDGER_GATEWAY` | T17, T18 | `scripts/tests/test_ledger_credentials.py` **written** |

## Phase 1: core

| Id | Test | Covers | File |
|---|---|---|---|
| L1 | canonical JSON: <ul><li>the RFC 8785 example and the shared vectors file (`fixtures/canonical_vectors.json`, read by the TS twin in phase 5);</li><li>UTF-16 key order;</li><li>the 1e-6, 1e20 and 1e21 boundaries;</li><li>`true` is not `1`;</li><li>integers beyond 2^53, lone surrogates, Decimal, datetime, bytes and sets refused</li></ul> | I4, I5 | `test_ledger_canonical.py` **written** |
| L2 | naming: a dashed pid in either case; an undashed pid and the nil UUID refused | I9 | `test_ledger_naming.py` **written** |
| L3 | registry: <ul><li>every required event, including `ai.llm_call`, `flower.request`, `pgadmin.request`, `ledger.reanchored`;</li><li>it imports only the standard library;</li><li>`VERSION`;</li><li>every gateway app known, with a project rule;</li><li>user actions have `caused_by` matching from `^/`;</li><li>item groups only;</li><li>witness-born actions have no cause and no route;</li><li>every AI or worker action is in a user start action's `runs`;</li><li>routes are (app, file, function);</li><li>`check(event, emitter)`: `emitter` for a wrong app and for platform-only actions; `actor_supplied` in details and in top-level platform fields, never for `content`; secrets in details and content</li></ul> | I2, I7, I8, T13 | `test_ledger_registry.py` **written** |
| L4 | store, on memory and on immudb as `aisc_ledger`, a unique database per test: <ul><li>increasing seq;</li><li>replay is a no-op, the same id with other content is `DuplicateEvent`;</li><li>verified reads;</li><li>paging;</li><li>isolation;</li><li>the head moves forward;</li><li>an unknown database is refused;</li><li>the 64 KiB cap;</li><li>two threads on two databases never cross;</li><li>a rolled-back state is a `TamperAlarm`.</li></ul> Immudb only: <ul><li>`aisc_ledger` can't create databases;</li><li>a database granted after login is usable;</li><li>the Postgres-kept state catches a rollback across stores;</li><li>compare-and-set</li></ul> | I3, I4, I9, T8, T11, T21, T24 | `test_ledger_store.py` **written** |

## Phase 3: emit, relay, platform events, privacy, failure

| Id | Test | Covers | File |
|---|---|---|---|
| O1-O3 | `ledger.emit`: <ul><li>every emitting role can call it;</li><li>`db_role` and `occurred_at` are stamped whatever was sent;</li><li>it returns nothing;</li><li>a rollback leaves no event;</li><li>platform-only actions refused;</li><li>no right at all on the table (SELECT, INSERT, UPDATE, DELETE, TRUNCATE);</li><li>non-emitting roles can't call it;</li><li>delivery state unreachable;</li><li>a malformed event refused</li></ul> | T7, R2.1, R3.3, R4.6 | `test_ledger_outbox.py` **written** |
| R1-R8 | relay, with test-declared actions: <ul><li>the actor from the witness;</li><li>`actor_supplied`;</li><li>a rejection is the relay's;</li><li>reasons `missing_request`, `unknown_request`, `project_mismatch`, `emitter`, `cause`, `item`, `unknown_action`, `content_hash`, `per_request`;</li><li>the window on the databases' clocks: stale, early, a backlog never stale;</li><li>forwarded requests accepted only from their `caused_by` app;</li><li>server-action id binding, and an action id required;</li><li>exactly once across a crash, `duplicate_event_id`, a late commit not skipped;</li><li>immudb down: pending, nothing rejected;</li><li>two relays honour `per_request`;</li><li>record mode gives `verified=false`;</li><li>a newer registry version is held;</li><li>item chain breaks and witnessed writes with no event reported</li></ul> | I2, I3, I6, I9, I11, T1-T4, T6, T8, T9, T14, T24 | `test_ledger_relay.py` **written** |
| P1-P4 | <ul><li>member changes with who made them, a failed change leaves no event, member events in `core.outbox`;</li><li>an LLM key by its HMAC only;</li><li>no request id gives 401 in `enforce`;</li><li>an id presented by someone else gives 401;</li><li>a card version saved by step 1 is the person's, caused by qualification's witnessed request;</li><li>a project with undelivered events isn't dropped (409) until they are delivered, and the log outlives it</li></ul> | I3, I7, I8, R1.5, R1.6, R2.4 | `test_ledger_platform_events.py` **written** |
| PR1-PR4 | immudb holds no subject or name; `actor_ref` keyed per project; a swapped mapping row is a `MappingAlarm`; erasure keeps entries pseudonymous; content digests are keyed | I10 | `test_ledger_privacy.py` **written** |
| F1-F3 | an immudb outage blocks nothing and loses nothing; an internal event is queued; `enforce` refuses a write with no request id at the app | I6 | `test_ledger_failure.py` **written** |

## Phase 4: routes, internal route, beacon

| Id | Test | Covers | File |
|---|---|---|---|
| A1-A4 | <ul><li>list newest first from the index;</li><li>a stranger gets 404;</li><li>filters;</li><li>isolation;</li><li>verified entries;</li><li>a tampered entry or index row is a 409 alarm;</li><li>export roles from `EXPORT_ROLES`;</li><li>the export carries proofs and a signed head and checks offline against the signing key;</li><li>an edited and re-hashed export fails;</li><li>admin-only heads;</li><li>admin-only re-anchor, recorded</li></ul> | I4, I9, T12, T21 | `test_ledger_routes.py` **written** |
| I1-I3 | internal route: <ul><li>AI events name the program, the model and the run's person;</li><li>tokens: 401 or 503;</li><li>malformed: 422;</li><li>no start event, past the run window, an action not in the run's `runs`, another app's action, another project: each `ledger.rejected`;</li><li>a supplied person is rejected</li></ul> | I2, T3, T17 | `test_ledger_internal.py` **written** |
| B1-B2 | beacon: <ul><li>`text/plain`;</li><li>page views kept outside immudb, with retention;</li><li>only beacon actions;</li><li>at most 2 KB;</li><li>a witnessed request needed, and the presenter's own;</li><li>rate limit</li></ul> | I10, R3.6 | `test_ledger_beacon.py` **written** |

## Coverage (all phases)

| Id | Test | Covers | File |
|---|---|---|---|
| C1 | every state-changing route (FastAPI, Ninja, Flask/FAB `@expose` and `ModelView`s, `api_route`, `add_api_route`, Next.js route handlers incl. re-exports, server actions incl. `export const x = async`), keyed by (app, file, function), is in a registry action's `routes` or in `fixtures/ledger_route_exceptions.tsv` with a reason | I7, T16 | `scripts/tests/test_ledger_coverage.py` **written** |
| C3 | every registry route exists in the code, GET reads included | I7 | same **written** |
| C4 | each registered handler calls the emitter with its action, per app (the engine is checked by E1-E2) | I7, T16, R4.14 | same **written** |
| discovery | finds the routes the review listed as missed; same-path Ninja routes stay apart; every app known; the scoped-out code has a reason | R4.12, R4.13 | same **written** |

## Phases 5 to 10 (written at their start)

| Id | Test |
|---|---|
| Q1-Q4 | step 1: each action calls `ledger.emit` in its transaction, none on rollback; the TS canonical twin passes the shared vectors; corrections, drafts and links keep history; an agent run has a start event and a run id; qualification forwards the request id to the platform |
| S1-S3 | step 2: a new AI run keeps the previous run and the assessor's rows; authors stored by subject; every action emits |
| K1-K3 | controls: a question review keeps closed answers; soft deletes; the AI ingest call is logged with model and keyed hashes |
| E1-E2 | engine: forwarding only in configurator mode, from the backend, with the request id and the run id through Celery; frozen guard green with one registered file |
| D1-D2 | dashboard: comment and review events, soft deletes, no viewer edit view; dashboard events find their project through the bridge table |
| M1-M3 | composer: layout revisions kept, a layout delete keeps its reports, a report prints a head that the offline checker accepts |
| V1-V4 | verifier: a changed evidence row, a changed bucket object, a missing database and a published head that disagrees are each reported; Keycloak login events land with `reported_by=keycloak` |
