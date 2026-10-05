# Part 2, stage 4: Code report for D1 to D3 (report run v2)

Status: done. Work order: 12-coding-plan-part2.md, groups 1 to 7 in order. Started 2026-09-25 09:51, finished 10:35.
`env | grep -iE 'DATABASE|DSN|DB_URL'` printed nothing before every run.

## Group 1: the interface (done)

- Before: 139 total, 137 passed, 2 failed (test_p2_prose, measured by stage 3). After: **139 passed**.
- Commit (interface, dev): 7ba6120.

## Group 2: the renderer (done)

- Before: 640 total, 581 passed, 59 failed. After: 640 total, **638 passed, 2 failed** (the two that wait for Group 3:
  `test_p2_english.py::test_r2_d1_5_translate_for_uses_the_package_en_json_then_the_renderer`,
  `test_p2_fixes.py::test_r2_d2_5_the_promptfoo_key_figure_tile_is_labelled_pass`).
- Commits (generator, dev): a13fe49 (English only), 8ed9c65 (singular forms), 74fd5b4 (surrogate id), 90fac3d (Word
  links), 005b2d2 (placeholder left out), 84b7903 (x-aisc-prose annotations), 51a9b29 (by-design test change, see D13-1).
- The placeholder check is in a small `document._section()` wrapper in front of `_render_block`; `render()` keeps
  every section for `block_statuses` and draws only the ones not omitted.
- D13-1 (by-design test change, own commit 51a9b29): `test_block_test_results.py::test_d8_observations_tied_to_their_run_and_the_rest_counted`
  and `test_v2_chart_block.py::test_r_v4_10_more_bars_than_max` pinned "1 observations ..." and "1 more groups ...".
  R2-D3.4.2 makes both singular; stage 2 and 3 did not list them. Only the expected string changed.

## Group 3: the tool packages (done)

- LangBiTe 43 / 26 passed -> **43 passed** (1a58eff en.json only, ab01898 Pass / Fail). StrongREJECT 26 / 24 ->
  **26 passed** (00517cd). promptfoo 29 / 17 -> **29 passed** (20cec8c, 1f4cb73). mlareject **20 passed** (no change).
- Generator after group 3: **640 passed, 0 failed**; `git diff fe30ed2 -- tests/golden` prints nothing.
- Small choice in LangBiTe `_run_result`: a present `All Tolerances Passed` with no numeric score is "not evaluated"
  (the plan names only score 1 and 0); no test covers it.

## Group 4: the composer (done)

- Before: 409 total, 345 passed, 64 failed. After: 409 total, **405 passed, 4 failed** (the four
  `test_api_reports.py` tests that wait for `Throwaway.rows()`, Group 5). guard-frozen.sh = baseline after each commit.
- Commits (aisc-install, only `apps/report-composer/**`): 22653b0 (no language choice), 4741bee (import resets
  references, notices), 7cf5f71 (composer.js back under 500 lines, D13-2), 718100d (B2 test data), 5b87788 (test fix,
  D13-3), 89db07e (schema-driven prose rule, new `report_composer/prose.py`), 6598b29 (B1 by design), 7853afb
  (unwritten hints), 8d42698 (failed outline request, Try again).
- D13-2: the notices code of 4741bee took `composer.js` to 507 lines and broke `test_pages.py::test_r4_1_1_one_small_script`
  (under 500 lines). Fixed in the code (7cf5f71): one `hint()` helper draws the pick-one, empty-chapter and
  not-written hints, shorter notices code; later steps also merged a few small lines and blank lines. Final: 498 lines,
  no `language` substring.
- D13-3 (plainly wrong test, own commit 5b87788): `test_p2_presets.py::test_r2_d3_6_1_import_stores_no_reference_of_the_source`
  searched the whole exported file for "991"; the preset name is `unique()` = a `time.monotonic_ns()` stamp, which
  contains "991" in roughly 2% of runs (it failed once in this stage). The check now looks at the exported blocks,
  where references live. The assertion is otherwise unchanged.
- Outline requests: `composer.js` sends `collect()` (instance id, block type, options) and redraws the not-written hint;
  an option edit schedules one outline request 0.8 s after the last edit (`edited()`), a move asks at once as before.
  Checked once in a scratch Playwright test (not committed): the hint disappears when the text is written and comes
  back when the placeholder is typed again.
- `prose.strip_options` also applies the fixed rule to `commentary` when a described block type's schema lacks it
  (the old rule always blanked commentary; `test_fix4_any_long_text_option_of_a_plugin_block_is_dropped_too` has no
  commentary in its schema).

## Group 5: `Throwaway.rows()` (done)

- Commit (aisc-install, only `scripts/pipeline_chain/throwaway.py`): 343b1fe. Only `rows()` changed: its own
  `docker exec ... psql -X -q -t -A -v ON_ERROR_STOP=1 ... -f -` call, whole stdout parsed as one JSON value, same
  error text.
- scripts stack + grants + throwaway_rows: **94 total, 91 passed, 3 failed** (exactly the 3 stack tests caused by
  other people's work). composer `test_api_reports.py`: **14 passed** (the 4 hidden tests pass).
- `scripts/pipeline_chain/test_dashboard_queries.py` (other people's suite, recorded only): **3 passed**.
- While this ran, another session was running the whole `scripts/tests` folder (containers `aisc-t-guard-*`,
  `aisc-t-grants-*`, `aisc-t-dbcheck-*` created 10:19 to 10:25); they were left alone.

## Group 6: the 08 correction (done)

- Commit (aisc-install, only `08-fix-round-2.md`): d4e4c62. The clause of item 1 is replaced in place by the text of
  12-coding-plan-part2.md Group 6, starting "Corrected in part 2 (2026-09-25):". Facts re-checked in the generator
  venv: lxml on libxml2 2.14.6 gives `'a�b'` for `<p>a\x00b</p>`, markdown-it gives U+FFFD for NUL and for
  `&#1;`, `&#x1b;`, `&#xFFFE;`, and `str.split` treats VT, FF and US as whitespace but not NUL.

## Group 7: final verification (done, 10:20 to 10:33, after the last code commit)

`env | grep -iE 'DATABASE|DSN|DB_URL'` printed nothing. Each database suite ran on its own `aisc-t-*` containers.

| suite | head | result | expected (plan Group 7) |
|---|---|---|---|
| aisc-report-plugin-interface | dev 7ba6120 | 139 passed | 139 passed |
| aisc-report-langbite | dev ab01898 | 43 passed | 43 passed |
| aisc-report-strongreject | dev 00517cd | 26 passed | 26 passed |
| aisc-report-promptfoo | dev 1f4cb73 | 29 passed | 29 passed |
| aisc-report-mlareject | dev 247a0d9 | 20 passed | 20 passed |
| aisc-report-generator (goldens, both e2e files) | dev 51a9b29 | **640 passed, 0 failed** | 640 passed |
| apps/report-composer (browser tests, both e2e files) | aisc-install d4e4c62 | **409 passed, 0 failed** | 409 passed |
| scripts stack + grants + throwaway_rows | same | 94 total: 91 passed, 3 failed | the same 3 |
| scripts/pipeline_chain/test_dashboard_queries.py (recorded only) | same | 3 passed | 3 passed |
| scripts/guard-frozen.sh | same | G1 FAIL (238 lines), G2 PASS, G3 PASS (hashes), G3 PASS (tests/test_vendored.py), the three G4 FAIL lines, G5 PASS | = 00-baseline.md |

Remaining failures, all caused by other people's work (10-specs-part2 section 4), untouched:
`test_report_stack.py::test_d6_guard_init_files_do_not_mention_report_roles` (init/project-databases.sql, 3e20ffb),
`::test_r4_1_2_launcher_card_seven` (homepage/project.html, another session's uncommitted change),
`::test_final_guard_frozen_passes` (guard-frozen.sh fails at baseline).

Checks:
- Both e2e green: generator `test_e2e_v2.py::test_e2e_v2_preview_pdf_and_docx` (snapshot says fr, output English) and
  composer `test_e2e_v2.py::test_e2e_v2_preset_coverage_draft_pdf_and_docx` (no "Write this section." in PDF and DOCX);
  the old `test_e2e.py` files pass too.
- Goldens untouched: `git -C ~/aisc-report-generator diff fe30ed2 -- tests/golden` prints nothing.
- Test changes since the stage-2/3 heads: generator only D13-1 (2 expected strings); interface, LangBiTe (after
  f5c0caf), StrongREJECT, promptfoo none; composer only B2 (conftest.py, v2_fakes.py), D13-3 (test_p2_presets.py) and B1
  (test_v2_pages.py). `scripts/tests/test_service_tokens.py` in the aisc-install range is another session's commit
  (33700ec, API auth WP2), not this stage's.
- `grep -rn language apps/report-composer/report_composer/static/composer.js` prints nothing; no `fr.json` in
  `report_renderer/i18n` or any package (`en.json` in the renderer and in LangBiTe only).
- No container of this stage left (the `aisc-t-chain-*`, `aisc-t-dbcheck-*`, `aisc-t-guard-*`, `aisc-t-grants-*`
  containers seen during the run belong to another session running `scripts/tests` and were left alone); no
  `*:report-v2-test` image was built; no headless Chrome left (the Chrome processes running are the desktop browser).
- Nothing pushed (`git status -sb` shows only "ahead"); no new branch. The live `aisc` stack: container names and
  creation times identical before and after the stage.

## Deviations

- D13-1 (by-design test change, generator 51a9b29): two older tests pinned "1 observations ..." and
  "1 more groups ..."; R2-D3.4.2 makes them singular. Not listed by stages 2 or 3.
- D13-2 (regression fixed in the code, aisc-install 7cf5f71): `composer.js` went over the 500-line limit of
  `test_pages.py::test_r4_1_1_one_small_script` after 4741bee; compacted with a shared `hint()` helper and fewer
  blank lines. 498 lines at the end.
- D13-3 (plainly wrong test, aisc-install 5b87788): the import test searched the whole exported file, including a
  time-stamp name, for "991"; now it searches the blocks. Flaky before (failed once in this stage).
- LangBiTe `_run_result`: a present `All Tolerances Passed` without a numeric score is "not evaluated" (the plan
  names only score 1 and 0).
- `prose.strip_options` applies the fixed commentary rule when a described block type's schema has no `commentary`
  (keeps the old behaviour for such schemas).
- Outline refresh after option edits uses its own 0.8 s debounce (`edited()`), not the preview's timer, so it also
  works with automatic preview off; moves still ask at once.

## Questions for the user

None new. Q2-1 to Q2-8 of 10-specs-part2.md stand with their defaults.

## Commits (local, not pushed)

| repo | commits |
|---|---|
| aisc-report-plugin-interface | 7ba6120 |
| aisc-report-generator | a13fe49, 8ed9c65, 74fd5b4, 90fac3d, 005b2d2, 84b7903, 51a9b29 (test, D13-1) |
| aisc-report-langbite | 1a58eff, ab01898 |
| aisc-report-strongreject | 00517cd |
| aisc-report-promptfoo | 20cec8c, 1f4cb73 |
| aisc-report-mlareject | none |
| aisc-install | 22653b0, 4741bee, 7cf5f71, 718100d (B2), 5b87788 (test, D13-3), 89db07e, 6598b29 (B1), 7853afb, 8d42698, 343b1fe, d4e4c62, and this report's commit |

Other people's working-tree changes in aisc-install (`apps/qualification` and `apps/control-objectives` pointers,
`homepage/project.html`, `docs/superpowers/form-assembly-2026-09-24/`, `docs/superpowers/api-auth-2026-09-25/`,
`__pycache__` folders) were never staged.
