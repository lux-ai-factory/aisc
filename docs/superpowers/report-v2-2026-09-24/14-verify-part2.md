# Part 2, stage 5: Verification of D1 to D3 (report run v2)

Status: done, 2026-09-25 10:36 to 11:02. Inputs: RULES.md, 00-baseline.md, BRIEF-2.md, 10-specs-part2.md,
11-tests-part2.md, 12-coding-plan-part2.md, 13-code-report-part2.md and the code. Nothing was fixed. Every suite was
re-run by this stage; every pre-fix run used a temporary git worktree in the scratchpad, removed afterwards.
`env | grep -iE 'DATABASE|DSN|DB_URL'` printed nothing before each run.

## Verdict: PASS WITH NOTES

All suites are fully green as 10-specs-part2.md section 4 defines it. The 13 formerly hidden tests run and pass.
Every D3 fix fails on its parent commit for the stated reason and passes at HEAD. Mutating each fix makes its test
fail. D1 and D2 hold in the rendered output. The goldens are unchanged. The guard output equals 00-baseline.md.
Nothing was pushed, and the live `aisc` stack was not touched by this run. There is 1 should-fix (low: the
outline route now waits on the renderer) and 5 notes. None blocks.

## A. Suites (re-run by this stage)

| suite | head | result |
|---|---|---|
| aisc-report-plugin-interface | dev 7ba6120 | 139 passed, 0 skipped |
| aisc-report-langbite | dev ab01898 | 43 passed |
| aisc-report-strongreject | dev 00517cd | 26 passed |
| aisc-report-promptfoo | dev 1f4cb73 | 29 passed |
| aisc-report-mlareject | dev 247a0d9 | 20 passed |
| aisc-report-generator (goldens, test_e2e.py, test_e2e_v2.py) | dev 51a9b29 | **640 passed, 0 failed, 0 skipped** (127 s) |
| apps/report-composer (browser tests, test_e2e.py, test_e2e_v2.py) | aisc-install 196e62f | **409 passed, 0 failed, 0 skipped** (219 s) |
| scripts/tests test_report_stack + test_report_grants + test_throwaway_rows | same | 94: 91 passed, 3 failed (the 3 below) |
| scripts/pipeline_chain/test_dashboard_queries.py (recorded only) | same | 3 passed |

Skip counts come from the JUnit XML of each run, and every count is 0. The composer's 4 Playwright tests ran on
/usr/bin/google-chrome and passed: `test_p2_browser::test_r2_d3_3_1_...`, and in `test_v2_browser` the tests
`test_fix_the_preview_recovers...`, `test_fix_chapter_indentation_follows_a_move` and
`test_fix_r2_5_an_older_outline_answer_arriving_last_is_ignored`. Both e2e tests passed:
generator `test_e2e_v2_preview_pdf_and_docx` and composer `test_e2e_v2_preset_coverage_draft_pdf_and_docx`. The
older test_e2e.py files passed too.

The 3 excluded failures were read, and the attribution holds:
- `test_d6_guard_init_files_do_not_mention_report_roles`: the test finds `report_ro` and `report_composer` in
  `init/project-databases.sql`. That file was last changed by 3e20ffb (2026-09-24 19:34, "A card version belongs to
  its project"), which is not a report-run commit.
- `test_r4_1_2_launcher_card_seven`: the composer card shows number 6, not 7. The cause is the uncommitted
  `homepage/project.html` change in another session's working tree (48+/32-, card restyle).
- `test_final_guard_frozen_passes`: guard-frozen.sh exits 1 with exactly the baseline lines.
No part-2 commit touches `init/`, `homepage/` or `scripts/guard-frozen.sh`.

The 13 hidden tests (R2-D3.5.4), found in the JUnit XML, all ran and passed:
- generator `test_r5_4_1_no_token_no_answer[get-/v1/block-types]`
- composer `test_r4_4_3_a_stranger_gets_404`, GET cases: systems, layouts, choices, /p/alpha/
- composer `test_api_reports` r4_2_5, r3_12, r4_3_5, r7_2_5
- grants d6a, r6_5, d13 x2

## B. D1, English only

- Language files: `report_renderer/i18n` holds only `en.json` (9 `|one` entries). LangBiTe holds only `en.json` (1
  entry). StrongREJECT and promptfoo have no i18n folder, and their package-data glob stays. `REPORT_I18N_PATH` is
  not read by any code, only by docs and two tests that prove it is ignored.
- Composer: `grep -i language` over `report_composer/` hits only 3 docstrings saying a language is ignored.
  `composer.js` (498 lines) and the templates contain no `language`. db.py neither writes nor reads the column.
- French in the output and the UI: none. In tests, French appears only as compatibility input (a snapshot, layout
  row, preset row or file carrying `"fr"`, and user text such as "Rapport Mijke") and in the interface's generic
  i18n tests (DV2-4, see note 3).
- Hands-on check: I rendered a v2 snapshot with `language: "fr"` (project M, M_V2) through `document.render` in a
  throwaway worktree. Results: `<html lang="en">`, "Contents" (no "Sommaire"), the CSS holds `"Page " counter(page) " of "`,
  and preview, PDF and DOCX all succeed. The composer's R2-C.1 tests passed, and I read them: a layout row set to
  `'fr'` gives 200 on GET, preview and generate, and no `language` reaches the renderer; a preset row set to `'fr'`
  makes a layout with no language and an export with no language.
- Goldens: `git diff f211e16..HEAD -- tests/golden` is empty (so is the diff from fe30ed2).
  `test_compat_golden.py` changed only by dropping the "Sommaire" alternative, which 10 section 6.1 allows. The
  golden tests pass.

## C. D2, the tool's own Pass / Fail

Rendered Test results for M_V2 (same scratch render):
- **LangBiTe**: the column is headed "Pass / Fail (LangBiTe tolerance check)". Cells are Pass, Fail, Fail and
  "Not evaluated", matching the descriptions Passed, Failed, Failed and Not evaluated (seed 7201 to 7204). The run
  line reads "All tolerance checks: Fail (1 of 4 passed)", from `All Tolerances Passed` 0.0 with "1/4".
  "Tolerance set in LangBiTe" stays next to the column.
- **promptfoo**: "Pass (higher is better) 85%" and "Fail (lower is better) 15%", followed by the note that these
  are promptfoo's own results. The chart series are Pass, Fail and Refusal rate. A run without rates shows
  "Pass not reported" and "Fail not reported" (labels only).
- **StrongREJECT**: no Pass or Fail word in either the scored run or the failed run.
- **MLA-Reject**: no data in M_V2. Its code is unchanged since the stage-1 head (only a guard test was added), and
  `test_r2_d2_7_no_pass_or_fail_word_and_no_verdict` passes.
- **No verdict of the report**: `verdict()` returns None in all four renderers and the legacy adapter. No renderer
  compares a number with a cut to make Pass or Fail: LangBiTe maps the tool's words and the tool's own 1.0/0.0, and
  promptfoo shows the tool's shares.
- **Threshold-like options**: I grepped the code, and scanned the property names of every real block schema (from
  `build_registry()`) for thresh, toler, cut, pass, fail, verdict, limit, min_, max_, band and score. Only
  `control_objectives.min_severity` (a filter), `control_answers.show_scores` and `chart.max_bars` (display) turned
  up. Tool options are only `show_charts` and `detail`. No user-set threshold exists. For the fixed report-side
  cuts, see note 4.

## D. D3, each fix against its parent commit

Parent runs used a detached worktree (`git worktree add --detach`) with the repo's own venv and
`PYTHONPATH=<worktree>`. I checked that `report_renderer` and `report_composer` were imported from the worktree.

| item | fix commit | test(s) at parent | failure at parent (reason) | HEAD |
|---|---|---|---|---|
| 1 surrogate id | gen 74fd5b4 | test_p2_fixes -k r2_d3_1 | 4 failed: 500 != 422 for preview/pdf/docx; UnicodeEncodeError '\ud800' for the instance_id placement; 12 guards pass | pass |
| 2 Word link | gen 90fac3d | -k r2_d3_2 | 8 failed: `ValueError: All strings must be XML compatible` (the 5 refs x 2 schemes, less the 2 `&#55296;` guards); 3 guards pass | pass |
| 3 failed outline | ai 8d42698 | test_p2_browser | Playwright timeout: "The chapter outline could not be updated." never shown | pass |
| 4 singulars | gen 8ed9c65 (LB 1a58eff) | test_p2_english -k "r2_d3_4 or r2_c_3" | '1 evaluations' != '1 evaluation' and the 8 other messages; "1 observations" in the 3 goldens' Test results | pass |
| 5 Throwaway.rows() | ai 343b1fe | test_throwaway_rows; composer test_api_reports | 10 failed `JSONDecodeError: Expecting value` (2 guards pass); the 4 api_reports tests fail | 12 passed; 14 passed |
| 5 json= (gen) | gen d213334 (test) | test_service -k r5_4_1 | `TypeError: Client.get() got an unexpected keyword argument 'json'` | 5 passed |
| 5 json= (composer) | ai 43bb723 (test) | test_api_access -k stranger | the same TypeError, 4 GET cases | 5 passed |
| 6 import references | ai 4741bee | test_p2_presets -k r2_d3_6 | 4 failed: `'chart_id' not in {'chart_id': 991}`; `notices` None; no "notices" in composer.js | pass |
| 7 prose rule | ai 89db07e (+IF 7ba6120, gen 84b7903) | test_p2_presets + test_v2_presets -k "r2_d3_7 or fix4" | 13 failed: the 11 prose shapes kept, the required placeholder, titles; the fix4 tests pass | pass |
| 8 placeholder | gen 005b2d2; ai 7853afb | test_p2_fixes -k r2_d3_8; test_p2_unwritten | gen 8 failed ("the unwritten section is still printed", "Write this section." in PDF text); composer 4 failed (no `unwritten`) | pass |
| 9 08 correction | ai d4e4c62 | read | one row changed in place with "Corrected in part 2 (2026-09-25):". Facts re-checked in the generator venv: lxml on libxml2 2.14.6 gives 'a�b' for NUL; `str.split` folds VT/FF/US, not NUL; markdown-it gives U+FFFD for NUL, `&#1;`, `&#x1b;`, `&#xFFFE;` | n/a |
| generator test fix | gen 8410eac | test_block_ai_card -k r2_2_2_tags | old test: `'scoring' not in` fails on "Credit scoring" (R2.2.1 text); new test at 8410eac passes on unchanged code | pass |

Break attempts (temporary edits in the throwaway worktree, all reverted with the worktree):
- ai_card shows tags even when hidden: the new tags test fails.
- DOCX `_NOT_XML` pre-check removed, try/except kept: 8 link tests fail with ValueError. This also shows the
  pre-check is what keeps the relationships part valid; the except alone is not enough.
- `_instance_id` without `_printable`: 4 surrogate tests fail.
- `is_placeholder` without `strip()`: the "  Write this section.\n" case fails.
- `block_statuses` built from shown sections only: 2 placeholder tests fail.
- Prose rule on the real renderer schemas (the 14 built-in types): I filled every free string and stripped it.
  Only `commentary`, `free_text.text` and `chapter.intro` change, titles stay, and every result still validates.
  (`dashboard_chart` is invalid before and after, because its required reference has no default. That predates
  part 2.) `unwritten()` then flags only `free_text.text`.

## E. Test integrity since the part-2 stage-1 heads

Heads: generator f211e16, interface 7999876, langbite 4bbf943, strongreject 8611f44, promptfoo 2dcd7c1, mlareject
4942594, aisc-install dc7bf07.
- **Removed test functions**: I diffed the names at the base and at HEAD. Generator 13, LangBiTe 4,
  StrongREJECT 3, promptfoo 3, composer 5, interface/mlareject/scripts 0. Each is a removal or rename listed in 10
  section 6: the `r_v8_2/6/7` tests renamed to R2 ids, `test_e2e_v2_preset_french_*` renamed without "french", and
  the rest removed by D1.
- **Changed tests after stage 2**:
  - langbite f5c0caf (DV12-1: counts both header words, excludes "Pass rate")
  - composer 718100d (B2, test data annotations only) and 6598b29 (B1, outline dicts gain `unwritten`,
    `unwritten_hint`)
  - generator 51a9b29 (D13-1, two expected strings made singular, as R2-D3.4.2 requires)
  - composer 5b87788 (D13-3, the "991" search limited to the exported blocks, where references live)
  All are recorded in 12 or in 13's Deviations. None weakens an assertion.
- **Skip or xfail added**: none (`git diff <base>..HEAD -- tests` has no added skip, xfail, importorskip or
  flaky in any repo). JUnit skip count is 0 in every suite.
- Other sessions' test commits in the range (76fec03, 33700ec, 9d60bb8: test_compose, test_llm_keys,
  test_service_tokens, test_inspector_network) are not report files.

## F. Boundaries

- `scripts/guard-frozen.sh` (run at 10:50): G1 FAIL (238 lines), G2 PASS, G3 PASS (hashes), G3 PASS
  (tests/test_vendored.py), the three G4 FAIL lines, G5 PASS. This equals 00-baseline.md.
- Part-2 commits in aisc-install touch only `apps/report-composer/**`, `scripts/pipeline_chain/throwaway.py`, the
  new `scripts/tests/test_throwaway_rows.py` and the run docs. None is in a frozen area, and none includes another
  person's file (other people's working-tree changes stay unstaged).
- `throwaway.py` (343b1fe): only `rows()` changed, 9+/3-. The same wrapper, psql with `-t -A -f -`, the same error
  text, and the whole stdout parsed as JSON.
- Nothing pushed: the 3 remote repos show only "ahead" (generator 53, interface 11, mlareject 4, aisc-install 171).
  No part-2 commit is on a remote branch. The 3 new packages have no remote. No new branch (the generator's
  `dev-local-history-20260923` was created 2026-09-23).
- Leftovers: both worktrees removed (`git worktree list` shows only the main trees). No `aisc-t-*` container, no
  `*:report-v2-test` image, no headless Chrome.
- Live stack: the report containers (`report-composer`, `report-renderer`, `report-grants`) have the same creation
  and start times before and after. Postgres, pgadmin, schema-docs, qualification-*, controls-* and
  control-objectives were recreated at 10:45 to 10:46 by **another session** (API auth WP3, commits 9d60bb8,
  04290ea, 5cf866b at 10:42 to 10:43). Their compose labels name an override file in that session's scratchpad
  (`.../2b573e56-.../scratchpad/deploy2-override.yml`). This run issued no docker compose command (note 5).
- Disk: at 10:57 the root filesystem was full (0 bytes free for users; Docker reports about 270 GB reclaimable
  across images, volumes and build cache). Around 77 GB were freed shortly after by someone else. This run
  deleted nothing but its own scratch files.

## G. Regressions and security in the part-2 diffs

- **Import reset of references** (presets.py `reset_references`, api.py import and post_layout):
  - Every reference option is top-level in the real schemas (9 found by walking all built-in schemas), so a
    top-level reset is complete.
  - Notice texts are built from the renderer's schema titles and indexes, never from file content.
  - composer.js draws them with `textContent`, and every sessionStorage access is inside try/catch.
  - No injection path found.
- **Prose detection** (prose.py): a pure walk bounded by the schema's depth, not the value's. jsonschema errors
  on odd branches are caught. As DV2-7 intends, unannotated long strings of future plugin blocks are dropped from
  presets.
- **Placeholder omission** (document.py `_section`): numbering, TOC and chapter grouping use only the shown
  sections, and `block_statuses` keeps every block. A text that is literally "Write this section." is left out by
  design (Q2-6).
- **Outline route** (api.py:286-308): the client now sends options. `_blocks` and a dict check guard them, the
  50-block limit stays, and the walk is schema-bounded. Availability regression: see finding 1.

## Findings

1. **Should fix (low)**, `apps/report-composer/report_composer/api.py:299-308` with `renderer_client.py:33`.
   - What changed: the outline route now calls the renderer's `GET /v1/block-types` on every request, with no
     cache. It uses the client's 120 s timeout, and the route is synchronous. composer.js asks for an outline
     0.8 s after every option edit (`edited()`, composer.js:248). The DV12-6 fallback covers only a fast failure
     (connection refused, 5xx).
   - Failure scenario: the renderer hangs, for example stuck in a PDF render. Each outline request then holds a
     worker thread for up to 120 s. An editor typing keeps adding requests, and indentation and hints stop
     updating until the timeout. Enough of them can starve the composer's thread pool. Before part 2 the outline
     route did not depend on the renderer.
   - Possible fix: a short timeout or a cached block-types list for this route.
2. **Note**, `tests/test_p2_presets.py:220-225` (composer). The test for "the composer shows notices" only checks
   that the substring `notices` appears in composer.js. The carry-over through sessionStorage to the editor was not
   exercised in a browser; stage 4's scratch Playwright check covered the unwritten hint only. Also,
   `POST /api/presets/import` has no caller in the UI, so its notices reach API users only.
3. **Note** (D1 wording). French remains in the interface's generic i18n tests and fixture:
   - `aisc-report-plugin-interface/tests/fake_i18n_pkg/i18n/fr.json`
   - `tests/test_v2_i18n.py:20-112`
   - the French examples in the `vera_report_plugin_interface/i18n.py:3-9` docstring
   DV2-4 authorises this: it is a generic mechanism with sample data, and no report output is affected. BRIEF-2's
   "French-specific tests go" could be read to include them, so the user should confirm. There is also a stale
   docstring at `aisc-report-generator/tests/v2_core_helpers.py:10`, which still mentions `{en,fr}.json` and
   `REPORT_I18N_PATH`.
4. **Note** (D2, for the user's awareness). Two fixed cuts made by the report remain. Neither is user-set or a
   tool verdict, and neither was added in part 2:
   - Coverage marks an objective "evidence, attention" when a linked checklist's mean score is below 3
     (`report_renderer/coverage.py:5-6`, 01 R2.8.2).
   - MLA-Reject splits cases into harmful and empty at 1.5 (`vera_report_plugin_mlareject/statistics.py:10`,
     Q2-5).
   Separately, LangBiTe's run line takes Pass or Fail from the tool's score and the counts from its description
   (`vera_report_plugin_langbite/renderer.py:55-60`). Inconsistent data (score 1.0 with "1/4") would read "Pass (1
   of 4 passed)". The real plugin writes the two consistently.
5. **Note** (environment). The live stack was partly recreated at 10:45 to 10:46 by another session's deploy, and
   the disk was briefly full (section F). The report containers were not affected. The live start times therefore
   differ from this stage's first snapshot, and the change is not this run's.

## State of the run

Part-2 commits (local, not pushed):

| repo | commits |
|---|---|
| aisc-report-plugin-interface | cd3cc1e (tests), 7ba6120 |
| aisc-report-generator | d213334, 8410eac, 73c43ea, 8167003, fe30ed2 (tests); a13fe49, 8ed9c65, 74fd5b4, 90fac3d, 005b2d2, 84b7903; 51a9b29 (test, D13-1) |
| aisc-report-langbite | 8389157, 8c5d646, 5f0fe82 (tests), f5c0caf (test fix, DV12-1), 1a58eff, ab01898 |
| aisc-report-strongreject | 440c697, 60a03fe, 8fa948f (tests), 00517cd |
| aisc-report-promptfoo | b5fc3a6, b33df81, 918bc36 (tests), 20cec8c, 1f4cb73 |
| aisc-report-mlareject | 247a0d9 (test) |
| aisc-install | f7fd0f0 (BRIEF-2), dc7bf07 (10), 43bb723, b162d16, 3041352, d446ee2 (tests), 29b65e4 (11), b52751b (12), 22653b0, 4741bee, 7cf5f71, 718100d (B2), 5b87788 (D13-3), 89db07e, 6598b29 (B1), 7853afb, 8d42698, 343b1fe, d4e4c62, 196e62f (13), and this file's commit |

Open questions for the user (defaults in force):
- Q2-1 to Q2-8 of 10-specs-part2.md: `REPORT_I18N_PATH` removed; language columns kept unused; a tool's Fail does
  not mark coverage; promptfoo shares only, no counts; MLA-Reject 1.5 split kept; an unwritten free text is left
  out whole; built-in preset titles as they are; French documents already generated stay stored.
- The earlier defaults of 01-specs section 20 that BRIEF-2 keeps (Q2, Q4 to Q8, Q10, Q2-1, Q3-2).
- New from this stage: finding 1 (outline route timeout or caching); note 3 (whether the interface's generic
  French sample tests should go too); note 4 (whether the fixed checklist cut of 3 in coverage is acceptable under
  "no thresholds").
