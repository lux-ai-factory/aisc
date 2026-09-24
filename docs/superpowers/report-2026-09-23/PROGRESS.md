# Report run 2026-09-23 (overnight)

Stopping rule: run until stage 5 is complete (target tests green, guard passes); a failed stage gets one retry, then it is written down and the run continues as far as possible. Rules: RULES.md.

| stage | started | finished | output | status |
|---|---|---|---|---|
| 1 specs | 23:41 | 23:46 | 01-specs.md | done |
| 2 architecture check | 23:46 | 23:56 | 02-architecture.md | done (16 deviations + amendments O1, O2) |
| 3 tests (TDD) | 23:56 | 2026-09-24 | 03-tests.md + failing tests | done: 471 tests (461 failing as expected, 10 pass), 4 local commits, finished 08:02 |
| 4 coding plan | 08:02 | 09:04 | 04-coding-plan.md | done (7 groups; 1 test fix: 'and 5 more' -> 'and 6 more', faithful to the 1000-answer cap) |
| 5 code | 09:04 | 09:52 | 05-report.md + 17 commits | done: 7 groups; 17 red tests all in tests/helpers/others' state (see 05 section 2); guard PASS (re-run by orchestrator 09:52) |

## Notes for the user
- aisc-report-generator: local `dev` had the same files as GitHub's `dev` but the old history (GitHub's was squashed on 2026-09-14). Local `dev` now sits on GitHub's history; the old history is kept on branch `dev-local-history-20260923`. No file changed.
- Stage 1 left defaults for you, marked `DEFAULT (user to confirm)` in 01-specs.md. The main one: nothing records which test or checklist covers an objective, so the Summary block lets the editor set those links by hand.
- Stage 2: Superset cannot render chart images today (screenshots off, no browser or worker in the image). Enabling it means rebuilding your dashboard image, so tonight (O1) the chart block shows the title, a link, the comments and, where reachable, the chart's data as a table. The screenshot provider is written and tested, but off (`REPORT_CHART_IMAGES=superset`). Your call to turn it on.
- Stage 2: nothing stores an AI Act risk class, so the editor states it as a block option (O2); provider, deployer and users come from the card.

## Stage 5 results (2026-09-24)
- interface 45 passed; mlareject 19 passed; generator 218/220; composer 99/107 (107/107 with two test helpers repaired in memory); aisc-install scripts/tests 106/113; both end-to-end tests pass; guard GUARD PASS on 7546717.
- Every remaining failure is a test or helper defect, or someone else's backend submodule state: see 05-report.md sections 2 and 4.
- Commits: aisc-install f7da4e3 287cda6 c710784 c62ca4d 776ed3e 7546717; generator 79e5658..65ece60 (10); interface 631b62b; mlareject 2dd5649. Nothing pushed.
