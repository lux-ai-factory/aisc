# Ledger: coding plan, version 2.2 (2026-10-02)

Order of work for `01-plan.md`, against `02-spec.md` (v2), checked by `04-test-plan.md`. The tests for
phases 0b to 4 and the coverage, Caddy and credential tests are written and red.

## Rules for every phase
- TDD: the phase's tests exist and fail for the right reason before any code.
- Throwaway Postgres and immudb 1.11.1 containers only, never the live stack.
  `PLATFORM_TEST_DATABASE_URL`, `PLATFORM_TEST_SUPERUSER_URL`, `LEDGER_TEST_IMMUDB_URL` and
  `LEDGER_TEST_IMMUDB_ADMIN_PASSWORD` are always set, with **`LEDGER_TESTS_REQUIRED=1`**: a skip is a
  failure (spec section 9).
- `LEDGER_MODE=off` and `LEDGER_GATEWAY=off` by default in compose. `record` and `on` together after
  phase 4 is deployed. `enforce` only on the user's yes after a clean reconciliation period
  (`RECONCILE_DAYS`).
- Local commits on `feat/unified-modules` by explicit path. Nothing pushed without a yes, no deploy
  without a yes.
- **Definition of done**:
  - the phase's tests green with no skip, and the skip count stated in the report;
  - every suite of every app it touched green, with known pre-existing failures named;
  - the coverage tests green for what the phase covers, including C4 for its app;
  - the phase's drills pass;
  - an independent review (fresh context) with **no open blocker or major**, and minors listed with
    an owner (R6.3);
  - after a deploy yes, a live check.
- **Stopping rule**: stop and report at the end of each phase. Stop at once on a red isolation,
  frozen-guard or service-token suite, a red invariant test, or a real-Caddy test that fails on the
  deployed Caddyfile.

## Phases

| # | Content | Code | Tests (04-test-plan) | Drill |
|---|---|---|---|---|
| 0 | spec v1, review, spike, spec v2, tests v2, second review | docs, tests | all of 0b-4 and C1-C4, G, K written, red | - |
| 0b | Header strip | `Caddyfile`: `strip-and-sign-in` and `protect` inside `route`, every handle `import protect <app>`, launcher `/api/authz/*` 404; `witness-*` snippets empty (`LEDGER_GATEWAY=off`) | C2, G (off half), and the live check that forged headers don't reach an app | curl with forged headers at each site after the deploy yes |
| 1 | Ledger core | `ledger/` `settings`, `naming`, `canonical`, `secrets`, `registry` (stdlib only), `state`, `store` (key-value, a client per database), `pool` + `scripts/ledger-pool.sh`, `provision`; immudb `--signingKey` (S3); `aisc_ledger` secret in `scripts/secrets.sh`; immudb in staging and production compose (D8); rotate the committed superuser password; restore runbook | L1-L4, PV1-PV8, CL1 | an immudb restart mid-append; a backup restored, then the alarm and the re-anchor |
| 2 | Witness | `ledger/witness.py`, `actors.py`, `GET /authz/witness`, `ledger.witness` in the platform DB, the shared `gateway_identity` (Python + TS), oauth2-proxy `--cookie-refresh=4m`; `witness-on` and `witness-reads-on` snippets | W1-W6, C2, G (on half), K | platform stopped: writes refused, reads served; a token at the edge of expiry |
| 3 | Emit and relay | template `0020_ledger_outbox.sql` with `ledger.emit`; `core.outbox`; `relay.py` with every check of spec 4.2-4.5; forwarded requests; runs; the platform's own events; project delete drain; `verify.py` reconciliation | O1-O3, R1-R8, P1-P4, F1-F3, PF1-PF5, PR1-PR8 | relay killed mid-batch; immudb down for 10 minutes; two platform workers |
| 3b | **Red team** | a fresh agent tries to get an unwitnessed change or a forged actor into the log, against phases 0b-3 | every finding becomes a test first | - |
| 4 | Panel, export, internal route, beacon | routes of spec 6.3, export with proofs, `scripts/verify-ledger-export.py`, `homepage/logs.html`, Manage > Audit > Activity log, beacon on each site | A1-A4, I1-I3, B1-B2 | an export checked offline; the record-to-enforce flip in a browser on every app |
| 5 | Step 1 | TS emitter (`$executeRaw`) and canonical twin (shared vectors), history tables, agent runs persisted with run ids, `ai.llm_call`; qualification forwards `X-AISC-Request-Id` to the platform | Q1-Q4, C4[qualification], C4[qualification_agents] | agent killed mid-run |
| 6 | Step 2 | Python emitter (`text()`), mapping runs kept, assessor rows kept, authors by subject | S1-S3, C4[control_objectives] | - |
| 7 | Step 4 controls app | emitter, checklist versions, soft deletes | K1-K3, C4[controls] | question review with closed submissions |
| 8 | Engine and workers | the one registered forwarding module (D3), engine backend holds the token, never the worker | E1-E2, credentials suite | a plugin trying to read a ledger token |
| 9 | Steps 5 and 6 | dashboard events and soft deletes, admin views; composer layout revisions, no cascade, report anchoring | D1-D2, M1-M3, C4[dashboard], C4[report_composer] | a report verified offline |
| 10 | Keycloak logins, evidence bucket with lock (`LEDGER_ARCHIVE_LOCK`), published heads, hourly entry archive and `archive.rebuild`, verifier | | V1-V5 (V5: delete a project's immudb database, rebuild it from the archive, verify against the heads) | a row changed directly in Postgres raises the alarm |

Phases 5 to 9 depend on phase 3's `caused_by` and runs, not on each other. A DPIA is done before
`record` is switched on in staging (spec 7.5).
