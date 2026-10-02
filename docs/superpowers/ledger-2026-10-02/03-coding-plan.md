# Ledger: coding plan (2026-10-02)

Order of work for `01-plan.md`, against `02-spec.md`, checked by `04-test-plan.md`. Tests for phases
1 to 4 and the coverage tests are written first (phase 0); later phases write theirs at their start.

## Rules for every phase
- TDD: the phase's tests exist and fail for the right reason before any code.
- Throwaway Postgres and immudb containers only; never the live stack. `LEDGER_TEST_IMMUDB_URL` and
  `PLATFORM_TEST_DATABASE_URL` always set.
- `LEDGER_MODE=off` by default in compose until phase 4 is deployed, then `record`; `enforce` only on
  the user's yes after a clean reconciliation period.
- Local commits on `feat/unified-modules` by explicit path; nothing pushed without a yes; no deploy
  without a yes.
- **Definition of done**: the phase's tests green; every suite of every app it touched green (known
  pre-existing failures named); the coverage tests green for what the phase covers; the phase's drills
  pass; an independent review (fresh context) with no open finding; after a deploy yes, a live check.
- **Stopping rule**: stop and report at the end of each phase, and immediately on a red isolation,
  frozen-guard or service-token suite, or a red invariant test.

## Phases

| # | Content | Code | Tests (04-test-plan) | Drill |
|---|---|---|---|---|
| 0 | Spec, plan, tests; plan review by a fresh reviewer; the user's decisions | docs, tests | all of phases 1-4 + C1-C3 written, red | - |
| 1 | Ledger core | `ledger/naming, canonical, secrets, registry, store`; immudb user `aisc_ledger` + secret in `scripts/secrets.sh`; immudb in staging/production compose (D8); rotate the committed superuser password | L1-L4 | immudb restart mid-append; backup and restore, then verify |
| 2 | Witness | `ledger/witness.py`, `GET /authz/witness`, `core.witness_index`; Caddy `protect` snippet gets the witness `forward_auth` and copies `X-AISC-Request-Id` upstream | W1-W3, C2 | platform stopped: writes refused in enforce, let through and marked in record |
| 3 | Outbox and relay | template `0020_ledger_outbox.sql`; `ledger/relay.py`; actor from the witness; `ledger.rejected`; the platform's own events (projects, members, Manage, card versions, step 4) | O1, R1-R3, P1 | relay killed mid-batch; immudb down for a minute |
| 4 | Panel, export, internal route, beacon | routes of spec 4.3; `homepage/logs.html`; Manage > Audit > Activity log; shared `ledger-beacon.js` | A1-A3, I1, B1 | export checked by `scripts/verify-ledger-export.py` |
| 4b | Red-team pass | a fresh agent tries to get an unwitnessed change or a forged actor into the log | every finding becomes a test first | - |
| 5 | Step 1 | TS emitter + canonical JSON twin (shared fixture with phase 1); history tables (corrections, drafts, links); agent runs persisted; `ai.llm_call` | Q1-Q4 | agent killed mid-run |
| 6 | Step 2 | Python emitter; mapping runs kept; assessor rows kept; authors by subject | S1-S3 | - |
| 7 | Steps 3 and 4 apps | catalogue + controls emitters; checklist versions; soft deletes; AI ingest calls | K1-K3 | question review with closed submissions |
| 8 | Engine and workers | one registered exception (D3); request id through Celery | E1-E2 | worker killed mid-plugin |
| 9 | Steps 5 and 6 | dashboard events, soft deletes, admin views; composer layout revisions, no cascade, report anchoring | D1-D2, M1-M3 | report verified offline |
| 10 | Keycloak logins, evidence bucket with lock, verifier, daily reconciliation | | V1-V4 | a row changed directly in Postgres raises the alarm |
