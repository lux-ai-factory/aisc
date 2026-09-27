# Stage 5: code (report run 2026-09-23)

Stage 5 followed 04-coding-plan.md group by group (A to G). Every commit is local; nothing was
pushed. Every database test ran on throwaway `postgres:14-alpine` containers (`aisc-t-*`), all
removed afterwards. No `docker compose up/down/build/restart/run` was run, and nothing was written
to the live `postgres`.

## 1. Status per group

| group | repo (branch) | status | commits |
|---|---|---|---|
| A roles and grants | aisc-install (feat/unified-modules) | done | f7da4e3 |
| B block and tool contracts | aisc-report-plugin-interface (dev) | done, 45/45 | 631b62b |
| C MLA-Reject tool renderer | aisc-report-mlareject (dev) | done, 19/19 | 2dd5649 |
| D the renderer | aisc-report-generator (dev) | done, 218/220 (2 test defects) | 79e5658, 4b18061, 814cbfd, dec9505, f3ea371, fa237aa (the listed test fix), fc0c115, 2b10397, e914ff5, 65ece60 |
| E the composer | aisc-install (feat/unified-modules) | done, 99/107 (8 test-helper defects; 107/107 with the helpers repaired in memory) | 287cda6, c710784, c62ca4d, 776ed3e |
| F joining the stack | aisc-install (feat/unified-modules) | done | 7546717 |
| G integration check | all | run, see section 2 | none |

The only test edit is the one 04 lists (2.3: "and 5 more" became "and 6 more", its own commit
fa237aa), plus the two additive tests of step D2 (test_o1_chart_data_from_the_api,
test_o1_chart_data_off_without_a_login), seen failing before the code. One plan detail was read
against the spec: 04 says the Summary block's "uncovered only" skips `evidence` rows; R2.8.4 and
its test say only `not covered` and `no evidence` rows are shown, so `evidence, attention` rows are
skipped too.

## 2. Final test counts, with every remaining failure explained

| suite | result |
|---|---|
| aisc-report-plugin-interface | 45 passed |
| aisc-report-mlareject | 19 passed |
| aisc-report-generator | 218 passed, 2 failed (220) |
| apps/report-composer | 99 passed, 8 failed (107) |
| aisc-install scripts/tests | 106 passed, 7 failed (113) |
| generator tests/test_e2e.py | 3 passed |
| composer tests/test_e2e.py | 2 passed |
| scripts/test-pipeline-chain.sh | FAIL at step 4 (see F4 below) |
| scripts/guard-frozen.sh | GUARD PASS on f7da4e3, 287cda6, 776ed3e and 7546717 (the final HEAD) |
| image smoke (optional) | both images built as `*:report-test`; the renderer loads 9 blocks and the MLA-Reject tool renderer and writes a PDF, the composer app builds; both images removed |

None of the 17 remaining failures is a code defect. Each one fails inside the test or its helper,
before the code under test is reached:

- **F1, 8 failures: `Throwaway.rows()` cannot parse psql's output.** In
  `scripts/pipeline_chain/throwaway.py` (DO-NOT-EDIT, a guard input) `rows()` runs psql in aligned
  mode and parses the last line, which is the footer `(1 row)`, as JSON. Every `bed.rows(...)` call
  therefore fails. Affected: test_report_grants.py::test_d6a_report_ro_logs_in_read_only,
  ::test_r6_5_report_ro_never_reads_the_catalogue, ::test_d13_composer_role_owns_its_schema,
  ::test_d13_composer_role_search_path; test_api_reports.py::test_r4_2_5_generate_stores_the_snapshot_and_the_pdf,
  ::test_r3_12_the_snapshot_survives_edits, ::test_r4_3_5_the_renderer_failing_is_502_and_failed,
  ::test_r7_2_5_a_pdf_over_25_mb_is_not_stored. With `rows()` repaired in memory by a scratch pytest
  plugin (no repo file changed), all 8 pass.
- **F2, 4 failures: `client.get(..., json=None)`.**
  test_api_access.py::test_r4_4_3_a_stranger_gets_404 for its 4 GET routes passes `json=` to
  TestClient.get. Neither httpx nor httpx2 accepts that argument, so the test raises TypeError before
  it sends a request. The POST case of the same test passes. With the argument dropped in memory, all 4 pass.
- **F3, 1 failure: the same defect in the renderer.**
  tests/test_service.py::test_r5_4_1_no_token_no_answer[get-/v1/block-types] calls
  `client.get(path, json={})`, which is a TypeError. Checked by hand instead: GET /v1/block-types answers
  401 without the token, 401 with a wrong one, and 200 with the right one. The two POST cases pass.
- **F4, 3 failures plus the chain script: the backend's working tree.**
  test_pipeline_chain.py::test_s12_1_the_full_chain_passes and ::test_s12_2_...[engine_stamp],
  [controls_stamp], and scripts/test-pipeline-chain.sh, all stop at step 4 on an ImportError:
  `apps/backend/aisc_backend/tests/integration/test_integration.py` imports `DataShapeStatus`, which
  `aisc_backend.models` in the checked-out backend (1c71318, with uncommitted changes, not the pointer
  the superproject records) does not define. That is someone else's in-progress submodule state
  (frozen, not touched). Steps 1 to 3, which apply the project template with 0003_report.sql, pass.
- **F5, 1 failure: a test that contradicts the spec.**
  tests/test_block_ai_card.py::test_r2_2_2_tags asserts that `"scoring"` is absent when tags are
  hidden. But R2.2.1 requires the target use case to be shown, and the fixture's target use case is
  "Credit scoring" (the same test file asserts "Credit scoring" is present). The test cannot pass
  as written. 04 does not list it as a fix, so I left it.

## 3. Guard

`scripts/guard-frozen.sh` printed `GUARD PASS` (G1 to G5) after every aisc-install commit and on the
final HEAD 7546717. `init/platform-db.sql` and `init/project-databases.sql` do not mention the new roles.

## 4. Needs the user

1. **Fix `Throwaway.rows()`** (F1). It is a guard input, so it is yours to change. A one-line fix:
   in `rows()`, parse the third non-empty line of the output
   (`json.loads([l for l in r.stdout.splitlines() if l.strip()][2])`), or run psql with `-tA`.
   That turns 8 tests green.
2. **Decide on three test defects** (F2, F3, F5). F2 and F3 need `json=` removed from the GET calls.
   F5 needs its assertion aimed at the tags, for example at the "Tags" heading or at "b2b" only.
   These are 5 tests. I did not edit them because 04 does not list them.
3. **The backend submodule's state** (F4). Its working tree is not at the commit the superproject
   records, and its integration test imports a name the models do not have. Once it is consistent,
   the pipeline chain can pass again.
4. **Other people were working in aisc-install during this run.** Uncommitted changes appeared in
   homepage/index.html and homepage/project.html (09:31), and later an "inspector" (pgAdmin) was added:
   init/inspector-role.sql, inspector/, platform/project-template/0004_inspector.sql, new hunks in
   docker-compose-infra.development.yml and scripts/secrets.sh, and changes to platform_service/app.py
   and its tests. I left all of it unstaged. My commits of docker-compose.development.yml and
   homepage/project.html were staged from HEAD-based patches, so they carry only the report hunks.
   The inspector hunks build on the report lines I committed. Nothing was lost.
5. **Still open from earlier stages:** turning on Superset screenshots (O1, `REPORT_CHART_IMAGES=superset`
   plus a Superset image with a browser and worker); the DEFAULTs of 01 and 02 (D2 stated risk class,
   R2.8.2 attention threshold 3, plain-text free text, templates stripped of references); pushing
   the four repos (nothing is pushed).

## 5. How to try it: deploying the composer to the live stack (runbook, NOT executed)

Run from ~/aisc-install, on the `aisc` project, in this order:

1. Review the commits listed in section 1 (four repos, all local). The renderer is built from
   ../aisc-report-generator, ../aisc-report-plugin-interface and ../aisc-report-mlareject as checked out.
2. Add the three new secrets: `scripts/secrets.sh`. Without `--rotate`, it keeps env.secrets
   and appends REPORT_SERVICE_TOKEN, REPORT_RO_PASSWORD and REPORT_COMPOSER_PASSWORD once. It also
   rewrites env.runtime and the rendered realm file, as it always does.
3. Build the two new images:
   `docker compose -p aisc --env-file env.runtime -f docker-compose-infra.development.yml -f docker-compose.development.yml build report-renderer report-composer`
4. Create the roles and the composer schema on the existing volume (one-shot):
   `... up -d postgres-setup`, then `docker logs postgres-setup` (no error).
5. Grant report_ro its SELECTs (one-shot; it waits for the engine tables):
   `... up -d report-grants`, then `docker logs report-grants` should end with `[report-grants] done`.
6. Start the renderer and the composer: `... up -d report-renderer report-composer`.
   Check `docker logs report-composer` (migrations applied), and check that the renderer answers only
   inside the backend network.
7. Load the new Caddyfile route: `... up -d --force-recreate caddy` (or `docker exec caddy caddy reload --config /etc/caddy/Caddyfile`).
   The launcher's homepage is bind-mounted, so card 7 appears on reload.
8. Open a project on the launcher (http://localhost:8100), then click step 7, "Compose the report".
   This goes to http://localhost/report-composer/p/<pid>, which redirects to /p/<slug>/.

To roll back: `... stop report-composer report-renderer`, and revert the Caddyfile route. The roles and
the `report_composer` schema are harmless when nothing uses them.

## 6. Manual browser checks still to do

- R4.2.3: reorder by drag and drop in the editor, and check the "Unsaved changes" flag after any change.
- R4.2.5: Generate PDF shows "Generating..." and then the per-block statuses, and the reports list reloads.
- In the editor: add a block from the palette, move it up and down, remove it, change the version
  (the confirm dialog after an `invalid_reference`), save, and check that the preview reloads.
- The layouts list: New layout, New from template, Delete (confirm). A viewer (e.g. victor) sees none
  of these controls.
- The downloaded PDF: running header "{project}, Version n", "Page x of y", table of contents after the cover.
- The chart block with screenshots off: title, link, comments, note (and the data table when Superset
  credentials are set).

## Checkpoint log (appended as each group landed)

- A (aisc-install): commit f7da4e3. test_report_grants 54 of 58 green as written; the 4 others (test_d6a_report_ro_logs_in_read_only, test_r6_5_report_ro_never_reads_the_catalogue, test_d13_composer_role_owns_its_schema, test_d13_composer_role_search_path) fail inside the test helper `Throwaway.rows()` (scripts/pipeline_chain/throwaway.py, DO-NOT-EDIT): it parses psql's aligned output and reads the footer `(1 row)` as JSON. With that helper patched in memory by a scratch pytest plugin (no repo file changed) all 58 pass. The 3 test_report_stack items green. Chain regression: FAIL at step 4, an ImportError inside apps/backend's working tree (`DataShapeStatus` missing from aisc_backend.models; someone else's uncommitted submodule state), unrelated to 0003 (steps 1 to 3, which apply the project template, pass). Guard: GUARD PASS on f7da4e3.
- B (aisc-report-plugin-interface): commit 631b62b. 45 passed. Guard: aisc-install HEAD unchanged (f7da4e3), GUARD PASS stands.
- C (aisc-report-mlareject): commit 2dd5649. 19 passed; interface still 45 passed. Guard pass stands (aisc-install f7da4e3).
- D (aisc-report-generator): commits 79e5658 4b18061 814cbfd dec9505 f3ea371 fa237aa fc0c115 2b10397 e914ff5 65ece60 . Full suite 218 passed, 2 failed (220 items incl. the 2 new D2 tests). The 2 failures are test defects outside the allowed fixes: (1) tests/test_block_ai_card.py::test_r2_2_2_tags asserts "scoring" absent with tags hidden, but R2.2.1 requires the target use case "Credit scoring" (fixture) to be shown, so it can never pass; (2) tests/test_service.py::test_r5_4_1_no_token_no_answer[get-/v1/block-types] calls client.get(path, json={}), a TypeError in httpx (and httpx2) Client.get before any request is made; the behaviour it means (401 without or with a wrong token on GET) was checked by hand: 401, 401, 200. Test fix of 04 section 2.3 committed on its own (fa237aa). Interface 45, mlareject 19 still pass. No aisc-t-* left. Guard pass stands (aisc-install f7da4e3).
- E (aisc-install, apps/report-composer): commits 287cda6 (E1), c710784 (E2 to E4), c62ca4d (E5), 776ed3e (E6). Composer suite 99 passed, 8 failed as written; all 8 are test-helper defects: 4 x test_api_access.py::test_r4_4_3_a_stranger_gets_404[get-...] pass json=None to TestClient.get (TypeError in httpx before any request) and 4 tests of test_api_reports.py read rows through the broken Throwaway.rows() (see A). With two scratch pytest plugins that only repair those helpers in memory (no repo file changed), 105 of 105 non-e2e tests pass. Both end-to-end tests (real renderer as a subprocess) pass. Grants suite unchanged (54 of 58, same 4 helper failures). Guard: GUARD PASS on 287cda6 and on 776ed3e.
- Note: homepage/index.html and homepage/project.html were changed in the working tree by someone else at 09:31 during this run (session label, title row, delete button); left unstaged.
- F (aisc-install): commit 7546717. test_report_stack.py all green, test_compose.py green, test_report_grants.py 54 of 58 (same 4 helper failures). docker-compose.development.yml and homepage/project.html were staged from HEAD-based patches (HEAD plus only the report hunks), so the qualification-prefill, PREFILL_URL and the other person's homepage hunks stay unstaged in the working tree. Guard: see the next line.
- F guard: GUARD PASS on 7546717.
- G (integration): the counts of section 2; no aisc-t-* container left; no report-test image left; nothing pushed.
