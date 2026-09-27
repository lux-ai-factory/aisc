# Part 2, fix round 1 (report run v2)

Status: done, 2026-09-25 11:03 to 11:18. Inputs: RULES.md, BRIEF-2.md, 10-specs-part2.md, 13-code-report-part2.md,
14-verify-part2.md and the code. Findings 1 to 3 of 14-verify-part2.md fixed, one commit each, test first.
Finding 4 (the checklist cut of 3 in coverage and the MLA-Reject 1.5 split) was not touched: it is a user decision.
Nothing pushed. The live `aisc` stack was not touched. `env | grep -iE 'DATABASE|DSN|DB_URL'` printed nothing
before each database run.

## Item 1: the outline route waits on the renderer (finding 1)

- Commit: aisc-install 08f0581 (composer only: `api.py`, `renderer_calls.py`, `renderer_client.py`, new test file).
- Fix:
  - `HttpRendererClient` gains `quick_timeout` (default 2 s) and `block_types_quick()`, the block-types call with
    that timeout. Every other call keeps the 120 s timeout.
  - `renderer_calls.BlockTypesCache` keeps the block types for 60 s. A renderer error (timeout, unavailable,
    rejected) gives `[]`, which is the existing DV12-6 fallback (fixed prose list), and is kept for 10 s. So a
    hung renderer costs one 2 s wait per 10 s, not 120 s per edit. A restarted renderer is picked up within
    60 s. The cache lives on `app.state`, one per app.
  - The outline route uses `outline_block_types(request)`. A renderer without `block_types_quick` (the test
    fakes) is asked through `block_types`. Other routes are unchanged.
- Test: `apps/report-composer/tests/test_p2r1_outline_types.py`, 8 tests:
  - cache: one fetch within the TTL, a new fetch after it, a failure gives `[]` and is kept for the failure
    TTL only, every renderer error falls back;
  - client: against a local socket that accepts and never answers, `block_types_quick()` raises
    `RendererTimeout` after the short timeout (under 5 s) while `timeout` stays 120; the default is at most 5 s;
  - route (db): 5 outline requests make 1 block-types call; a renderer whose quick call times out still gives the
    indented outline, never uses the long call, and is asked once for two requests.
- Seen failing first: 8 failed (missing `BlockTypesCache`, no `quick_timeout`, 5 calls instead of 1, the long
  call used). After the fix: 8 passed; composer suite 417 passed.

## Item 2: the notices test only searched composer.js (finding 2)

- Commit: aisc-install 31e37b4 (`tests/test_p2_browser.py`, `tests/test_p2_presets.py`).
- The grep test `test_r2_d3_6_2_the_composer_shows_notices_as_information` in test_p2_presets.py is replaced by
  a Playwright test of the same name in test_p2_browser.py (system Chrome, the existing `live` fixture). It
  imports a preset file with another project's chart and evaluation ids through the layouts page's "Import a
  preset file" form. It checks that the new layout's editor opens and that the message region names both reset
  references with the texts from Python, marked as information (`ok`), and that a reload no longer shows them.
- The behaviour already worked, so the new test passed at once. To prove it tests the behaviour, three
  temporary mutations of composer.js (reverted, file unchanged) each made it fail: `showKeptNotices()` not
  called (timeout waiting for the notice), notices not carried to the next page (timeout), notice shown as an
  error (`ok` missing).
- The composer suite count stays 417 (one test removed, one added).
- Unchanged, from 14's note: `POST /api/presets/import` still has no caller in the UI. The page's import goes
  through `POST /api/p/{ref}/layouts` with `preset_file`, which is what this test drives.

## Item 3: French sample data in the interface's language-file tests (finding 3)

- Commit: aisc-report-plugin-interface 777303f.
- Test first: `test_p2r1_3_the_sample_plugin_package_ships_an_english_catalogue_only` (the sample package's
  `i18n` folder holds only `en.json`, and it loads) failed: 1 failed, 25 passed in test_v2_i18n.py.
- Fix:
  - `tests/fake_i18n_pkg/i18n/fr.json` becomes `en.json` with English texts.
  - `tests/test_v2_i18n.py` uses English catalogues. The code tests use `en` and `en-GB`, the bad codes are
    `english`, `EN`, `en_GB`, `en-gb`. The plural tests keep the rule `[0, 1]` as sample data, so they still
    prove that the rule, not English grammar, decides. The package-first and later-catalogue-variant tests still
    tell the catalogues apart.
  - The i18n.py docstring and the code-format error text now use English examples. There is no behaviour change.
- After: interface 140 passed (139 + 1).
- Left as they are, since they are not language-file tests:
  - `language="fr"` contexts in `tests/test_v2_contracts.py` (compatibility input);
  - a measurement dimension `language: "fr"` in `tests/test_tools.py` (tool data).
- Also left: the stale docstring `aisc-report-generator/tests/v2_core_helpers.py:10` (`{en,fr}.json`,
  `REPORT_I18N_PATH`). It is in another repo and outside this item's scope.

## Final run (after the last commit)

| suite | head | result |
|---|---|---|
| aisc-report-plugin-interface | dev 777303f | 140 passed |
| aisc-report-langbite | dev ab01898 | 43 passed |
| aisc-report-strongreject | dev 00517cd | 26 passed |
| aisc-report-promptfoo | dev 1f4cb73 | 29 passed |
| aisc-report-mlareject | dev 247a0d9 | 20 passed |
| aisc-report-generator (goldens, both e2e files) | dev 51a9b29 | 640 passed, 0 failed, 0 skipped (JUnit) |
| apps/report-composer (5 browser tests, both e2e files) | aisc-install 31e37b4 | 417 passed, 0 failed, 0 skipped (JUnit) |
| scripts stack + grants + throwaway_rows | same | 94: 91 passed, 3 failed (the 3 known others' failures: d6_guard_init_files, r4_1_2_launcher_card_seven, final_guard_frozen_passes) |
| scripts/pipeline_chain/test_dashboard_queries.py (recorded only) | same | 3 passed |
| scripts/guard-frozen.sh | same | G1 FAIL (238 lines), G2 PASS, G3 PASS (hashes), G3 PASS (tests/test_vendored.py), the three G4 FAIL lines, G5 PASS: equals 00-baseline.md |

Leftovers: none of this stage's (`aisc-t-*` containers of this run removed by their fixtures; the guard's /tmp
output folder deleted; no image built; no worktree). The container `aisc-t-schema-86e61729` (created 11:07:35)
belongs to another session and was left alone. Other people's commits and uncommitted changes in aisc-install
(for example 63523a5, `homepage/project.html`, `apps/qualification`) were not staged or touched.

## Deviations

- Item 2 cannot fail before a fix, because the behaviour already worked. Mutation runs stand in for the "failing
  test seen first" step (listed above).

## Questions for the user

- Finding 4 of 14-verify-part2.md (fixed cuts made by the report: checklist mean below 3 in coverage, MLA-Reject
  1.5 split) is still open and untouched.
