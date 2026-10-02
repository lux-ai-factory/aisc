# Ledger: test plan (2026-10-02)

Every invariant (I) and threat (T) of `02-spec.md` is covered by at least one test below. Tests marked
**written** exist now and are red until their phase is built.

## How to run (written tests)
- Platform: from `platform/`, with a throwaway Postgres (recipe:
  `docs/superpowers/pipeline-2026-09-24-llm-keys/02-tests.md` section 3) and a throwaway immudb:
  `docker run --rm -d --name aisc-t-immudb-$RANDOM -p 127.0.0.1:$PORT:3322 codenotary/immudb:1.9.5`,
  then `LEDGER_TEST_IMMUDB_URL=127.0.0.1:$PORT PLATFORM_TEST_DATABASE_URL=... uv run --extra dev pytest tests/ledger`.
- Repo level: `uvx --with pyyaml pytest scripts/tests/test_ledger_coverage.py scripts/tests/test_ledger_caddy.py`.

## Phase 1: core
| Id | Test | Covers | File |
|---|---|---|---|
| L1 | canonical JSON: the RFC 8785 vectors (key order by UTF-16, numbers, escapes, nested), same value gives same bytes | I4, I5 | `platform/tests/ledger/test_canonical.py` **written** |
| L2 | naming: a pid gives `ledger<hex>`; anything else refused; the platform's own log name | I9 | `test_naming.py` **written** |
| L3 | registry: every action has a step, apps, item type, routes, actor kinds; unknown action, missing field, a details key not allowed, a secret-looking value are problems | I2, I7, I8, T13 | `test_registry.py` **written** |
| L4 | store (memory and immudb): append returns increasing seq; the same event_id twice gives the first seq; get is verified; head moves forward; a rolled-back persisted state raises TamperAlarm; another project's db never sees the entry | I3, I4, I9, T8, T11 | `test_store.py` **written** |

## Phase 2: witness
| Id | Test | Covers | File |
|---|---|---|---|
| W1 | a write with a valid token: 200, `X-AISC-Request-Id`, one `request.witnessed` with subject and name from the token, app from the upstream, project from the path | I1, I2 | `test_witness.py` **written** |
| W2 | enforce: missing, malformed, wrongly signed, other issuer, expired token: 401 and nothing reaches the app; record: 200, `request.unverified` | I1, T5 | same **written** |
| W3 | a GET document load is witnessed (`page.opened`); a GET fetch is not; a path with no project goes to the platform log | spec 4.3 | same **written** |
| C2 | Caddy: the `protect` snippet calls the witness and copies `X-AISC-Request-Id`; every reverse_proxy handle except the listed exceptions imports `protect` | I1 | `scripts/tests/test_ledger_caddy.py` **written** |

## Phase 3: outbox and relay
| Id | Test | Covers | File |
|---|---|---|---|
| O1 | the template: module roles can INSERT only; `db_role` is the inserting role whatever was sent; no SELECT, UPDATE, DELETE | T7 | `test_outbox.py` **written** |
| R1 | relay: a row citing a valid request becomes one entry with the witness's actor and the app from `db_role`; a row carrying an actor field gives `ledger.rejected (actor_supplied)` and no trusted entry | I2, T1 | `test_relay.py` **written** |
| R2 | relay refuses: missing request id, another app's request, a request older than the window, a route the action doesn't allow, more events than `per_request`, a content hash that doesn't match, an unknown action, a project mismatch | T2-T4, T6, I9 | same **written** |
| R3 | relay crash after the immudb write and before the mark: a rerun adds nothing; a replayed row is a no-op | I3, T9 | same **written** |
| P1 | the platform's own events: project created/deleted, member changes, LLM keys (fingerprint only), connections, allowlist, card version, step 4 links saved | I7, I8 | `test_platform_events.py` **written** |

## Phase 4: panel, export, internal route, beacon
| Id | Test | Covers | File |
|---|---|---|---|
| A1 | members list and filter; a stranger gets 404; another project's entries never appear | I9 | `test_routes.py` **written** |
| A2 | an entry is shown only after a verified read, and an index row that disagrees with immudb is an alarm | I4, T12 | same **written** |
| A3 | export: JSONL + head, accepted by `scripts/verify-ledger-export.py`; refused to a viewer | I4 | same **written** |
| I1 | internal route: needs the app's own token; an AI event without `program`, `model` or a citing request is refused; `on_behalf_of` comes from the cited request | I2, T3 | `test_internal.py` **written** |
| B1 | beacon: witnessed, `reported_by=browser`, only allowed actions, ≤ 2 KB | spec 4.3 | `test_beacon.py` **written** |

## Coverage (all phases)
| Id | Test | Covers | File |
|---|---|---|---|
| C1 | every state-changing route of every app (FastAPI and Django Ninja decorators, Next.js route handlers and server actions) maps to a registry action's routes, or is on the reviewed exception list | I7, T16 | `scripts/tests/test_ledger_coverage.py` **written** |
| C3 | every registry action's routes exist in the code (no stale entry) | I7 | same **written** |

## Phases 5 to 10 (written at their start)
| Id | Test |
|---|---|
| Q1-Q4 | step 1: each action writes one outbox row in its transaction, none on rollback; TS canonical JSON matches the shared fixture; corrections, drafts and links keep history; an agent event names the agent, the model and the person |
| S1-S3 | step 2: a new AI run keeps the previous run and the assessor's rows; authors stored by subject; every action writes its event |
| K1-K3 | catalogue and controls: a question review keeps closed answers; soft deletes; the AI ingest call is logged with model and hashes |
| E1-E2 | engine: forwarding only in configurator mode, with the request id through Celery; frozen guard green with one registered file |
| D1-D2 | dashboard: comment and review events with the subject, soft deletes, no viewer edit view |
| M1-M3 | composer: layout revisions kept, a layout delete keeps its reports, a report prints a head the offline checker accepts |
| V1-V4 | verifier: a changed evidence row, a changed bucket object, a missing witness, a skipped event are each reported; Keycloak login events land with `reported_by=keycloak` |
