# Pipeline run 2026-09-23 (user away 20:00-21:00)

Stopping rule: run until stage 6 is complete; stop early only on a blocker that needs the user (written below). Rules: RULES.md.

| stage | started | finished | output | status |
|---|---|---|---|---|
| 1 interrupted-doc | 20:05 | 20:10 | 01-interrupted.md | done |
| 2 work plan | 20:10 | 20:18 | 02-work-plan.md | done (verified: engine evaluation.system_id -> core.system exists at e34fca3) |
| 3 specs | 20:18 | 20:31 | 03-specs.md | done (+ amendments A1, A2) |
| 4 tests (TDD) | 20:31 | 20:52 | 04-tests.md + failing tests | done (8 repos, local commits only; see 04 "Findings for stage 5", incl. the controls live-DB hazard) |
| 5 coding plan | 20:52 | 21:13 | 05-coding-plan.md | done (12 groups A-K + amendments B1-B3) |
| 6 code | 21:13 | 22:40 | 06-report.md + commits | done (A to K; 8 items under "Needs the user" in 06) |

## Notes for the user (decisions made in your absence, reversible)
- Stage 1 found a conflict: the other session's plan 4 and the spec move the engine into each project's own database, but you said the engine is fixed, and RULES.md keeps engine tables where they are. The run keeps the engine where it is (shared `platform` DB) and harmonises the other modules around it. Flagged for you.
- Stage 3 wanted to put the test stamp in one line of Sean's `routers/evaluation.py`. Overruled (amendment A1): Sean's files stay byte-identical, and the stamp is set by a new signal module instead.
- Stage 3 found `core.system` is owned by the superuser, so the platform cannot alter it. Accepted fix: an ownership line in `init/project-databases.sql`, which only takes effect on the next start of the live stack (A2). Your call before restarting.
- Stage 4 found that controls' existing integration tests create and drop databases in the live `postgres` container whenever `PROJECT_DATABASE_URL` is set. They were not run against live; stage 6 was told to point them at a throwaway server only.
- Stage 5 planned to edit an already-applied qualification migration so fresh installs work. Amendment B1: first try keeping the unused `core.ai_system_version` table in place, and edit the migration only as a fallback, recorded under "Needs the user".
- Committing the other sessions' prefill and review-page work (uncommitted in qualification and results-dashboard) was left for you (B2).
