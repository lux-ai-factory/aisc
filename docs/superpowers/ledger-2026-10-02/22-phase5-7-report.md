# Ledger: phases 5 to 7 report, the three apps with a project database (2026-10-03)

Phases 5 (qualification and its agents), 6 (control objectives) and 7 (controls) of
`03-coding-plan.md`, their independent reviews (`19-phase5-review.md`, `20-phase6-review.md`,
`21-phase7-review.md`) and the fixes. Every commit is on `feat/unified-modules`, local, **not pushed**:

| Repo | Commits |
|---|---|
| apps/qualification | 3a2b537 (phase 5), 44bd97d (review fixes) |
| apps/control-objectives | 6cc41aa (phase 6), a63bdda (review fixes) |
| apps/controls | 8c4c2b5 (phase 7), 2bb7a74 (review fixes) |
| aisc | a776645, 53a90b0 (phase 5); cbd1f2f (phase 6); 9fd6984, 4e357ab (phase 7); the commit with this report (phase 6 fixes, the reviews, submodule pointers) |

**Nothing is deployed.** `LEDGER_MODE` defaults to `off` in compose for every app, and with it off no
app writes an outbox row (each app has a test that catches an "always on" mutation).

## What was built

All three apps follow one rule: an event is written with the project database's `ledger.emit(jsonb)`
(template 0020) **in the same transaction as the change**, it cites the request the gateway witnessed
(`X-AISC-Request-Id`), and it never names a person.

| App | What records what |
|---|---|
| qualification (phase 5) | <ul><li>a TypeScript emitter and the canonical twin (`src/server/ledger/`), checked against the platform's own vectors</li><li>card links, ontology corrections, extracted-data replacements, form sets and questionnaires, the qualification's creation, page opens, PDF downloads</li><li>`card_history` (append-only, TRUNCATE refused)</li><li>the AI fill as one run: the app opens it (`card.ai_refinement_requested`) before asking the agent; the agent posts `agent.run_started`, each `ai.llm_call` and `agent.run_finished`/`failed` with its own token; the app records `card.augmented_by_ai` in the save</li></ul> |
| control objectives (phase 6) | <ul><li>`ledger.py` (emitter, request-id middleware, model-call timing) and `api/ledger_events.py`</li><li>every assessment write (start, ratings, comments, keys, mapping by hand, profile switch, delete) and every library write (sets, objectives, publishing, profiles)</li><li>`mapping_archive` (append-only, TRUNCATE refused): what an AI run, a profile switch, a person's edit or a delete replaces</li><li>authors kept by Keycloak subject beside the name the pages show</li><li>an AI mapping as one run: its request in a transaction of its own **before** the first model call, then each call and the outcome in the save's</li></ul> |
| controls (phase 7) | <ul><li>the same emitter and twin (`src/lib/ledger/`), one state builder per item (`state.ts`)</li><li>installs (with the package digest, the source and the questions with their ids), a submission's life (created, saved, closed, reopened, archived, restored), sources, checklist edits, question reviews</li><li>`questions_version` on each checklist</li></ul> |
| platform | registry entries with `routes` (C4) and causes, `same_action` for one server action's two events, `open_runs` for AI runs that never ended, and C5, a test that each server action's cause is the page its form is really mounted on |

## Tests (on throwaway databases only; `LEDGER_TESTS_REQUIRED=1`: a skip is a failure)

| Suite | Result |
|---|---|
| qualification, whole, with its throwaway database | 1795 passed, 1 skipped |
| control objectives, whole (scratch database `co_tests`) | 518 passed, 1 skipped |
| controls, whole, with its throwaway database | 272 passed, 2 skipped (the opt-in chain test) |
| platform `tests/ledger` step 1, 2, 4 and registry | 196 passed |
| `test_ledger_action_pages.py` (C5) and C4 | green for the three apps |
| `test_ledger_coverage.py` C1 | red only for routes of apps whose phase hasn't come (engine, connectors, platform, report composer, renderer) |

**Five controls suites no longer touch the live database.** `install`, `action-access`,
`project-database`, `submission-lifecycle` and `project-scope` ran their SQL with
`docker exec postgres`, the live container, so they had never run here. They now use the throwaway
helper and all pass. `project-database` had a stale mock: it lacked `notFound`, which the I2.5 rule
calls (a dropped database is "not found").

**How the tests were checked.** Each reviewer broke the code on purpose (mutations). The ones that
survived (a draft's or an archive's event in a second transaction, installs with no event, the run
events of a mapping in a second transaction, no model-call recording, no archive on a profile switch,
no append-only trigger, routes storing no author subject) now each have a test that fails on them.

## Drills

| Drill | Result |
|---|---|
| phase 5: the agent killed mid-run (opt-in) | the open run is counted by `verify.open_runs` once its window has passed |
| phase 6: a mapping whose calls take 6 minutes | its request is accepted (written before the calls), and so are its calls and its outcome |
| phase 7: a question review with closed submissions | see open decision 1: the answers are still deleted, and the event keeps them |

## Reviews and what was done

- **Phase 5 (`19`, 1B/7M/9m):** B1, M1 to M7, m1, m2, m4, m6, m7 and m8 fixed. m3 is covered by
  `open_runs`; m5 (program naming) recorded; m9 goes to phase 10.
- **Phase 6 (`20`, 0B/4M/11m):**
  - M1: the mapping's request goes first, in its own transaction; `open_runs` counts a mapping with no end.
  - M2: a new card version's assessment takes the previous profile in its own start transaction, and `assessment.started` names it.
  - M3: a risk's rating, comment and mapping are three items, each `<assessment>/risks/<risk>`. Keys send the whole map. A test runs a realistic sequence and finds no chain break.
  - M4: tests for every surviving mutation, including a fake mapper that calls its model.
  - m1, m2, m4 to m9 and m11 fixed. m3 and m10 are below.
- **Phase 7 (`21`, 0B/4M/10m):**
  - M1 guard 1: a review that keeps the questions as they are touches no question and no answer, and records `controls.checklist.edited`. The rest of M1 is decision 1.
  - M4: the five suites, above.
  - m1, m3 to m6, m8 and m9 fixed.
  - M2 and M3 are decisions 2 and 3.
  - m2 goes with decision 1; m7 and K3 get owners (below); m10 goes to phase 10.

## Open decisions (each changes what a person sees, or keeps data loss)

1. **A question review still deletes the answers given to the questions it replaces, closed
   submissions' included (controls, review 21 M1).** Since this phase, only when a question is really
   added, removed or reworded. The review's event keeps every deleted answer, but the database loses
   them, and the closed submission's PDF and the evidence page then show it unanswered. The options:
   - (a) **soft-retired questions** (my recommendation): nothing is deleted; a closed submission keeps
     its questions and answers. This needs the controls app, the platform's `evidence.py` and the report
     generator to filter retired questions. `evidence.py` is being changed by another session right now.
   - (b) refuse a review while closed submissions answer its questions (the person amends them first),
     or ask for a confirmation the event records.
   - (c) keep it as is, with the ledger's copy as the only record.
2. **Installs from the catalogue's dialog and from `/controls/install` are always rejected
   (`project_mismatch`)** (review 21 M2; review 20 m10). Those two paths carry the project in the form,
   not the URL, so the witness can't name it. Only the in-app catalogue page is recorded. The fix moves
   both under `/controls/p/<project>/...`. That changes a URL the catalogue (another repo) posts to.
3. **An answer that looks like a token** ("Bearer ...", "sk-...", "eyJ...") gets every save of that
   submission rejected by the relay, and a review's frozen copy with it (review 21 M3). Proposal:
   with the ledger on, the app refuses such an answer with a message saying why. This changes what a
   person can type.
4. **From phase 4, still open:**
   - the C4 rule for the platform's own data-layer emits;
   - `evidence.links.saved`, waiting for the other session's `evidence.py` work;
   - a project's delete, refused while the apps hold pooled connections (proposal: `pg_signal_backend` for `platform_rw`).

## Recorded, with owners

- **m3 (review 20), before the `enforce` flip:** in `enforce`, an app should refuse a write that
  carries no request id (spec 5.3). Qualification and control objectives both lack this today. It goes
  on the enforce checklist.
- **No phase owns these yet** (proposal: add them to phase 10):
  - m7 (review 21): `controls.report.downloaded` and `controls.page.opened`, with the other page moments
    moved there from review 17;
  - K3: the catalogue's AI ingest (`catalogue.control.ingested`). The controls app has no AI step; the
    catalogue, a service of its own, has one.
- **Phase 10:**
  - no-op writes that leave a witnessed request with no event (reopening twice, archiving an archived submission);
  - phase 5's m9.
- **Known flakes:** `test_tg2` (platform token timing), and one vitest worker crash once in
  qualification.

## To deploy, when you say so

After phases 2 to 4's steps (`14-phase2-report.md`, `18-phase3-4-report.md`):
1. Rebuild and recreate qualification, its agents, control objectives and controls-web. Their
   migrations add `card_history`, `mapping_archive`, the `*_sub` columns and `questions_version`, and
   only add.
2. Give the agents their token (`PLATFORM_LEDGER_AGENTS_TOKEN`, already in `env.secrets`).
3. Decide 1 to 3 above before `LEDGER_MODE=record`.
