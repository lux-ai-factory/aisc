# Stage 4: Code report for report run v2

Status: stage 4 of 5, done. Work order: 03-coding-plan.md, groups 1 to 7 in order. Group 4 (tool packages) and group 5
(composer) were run by parallel helper agents (forks of the stage-4 agent) while the stage-4 agent did groups 2, 3
and 6 in the generator.

## Group 1: the interface (done)

- Before: interface 121 total, 72 failed, 49 passed. After: **121 passed**. mlareject 19 passed (lock refreshed).
- `sqlalchemy` is no longer loaded by `import vera_report_plugin_interface` (D3-1, lazy `BaseReporterPlugin`).
- nh3 0.3.7 has no `generic_attributes` keyword; `attributes={"a": {"href"}, "*": set()}` drops the default
  `title`/`lang` generic attributes instead.
- By-design test change (not in the plan's section 4): `tests/test_blocks.py::test_r1_6_every_block_accepts_title_and_page_break_before`
  expected `full_default_options()` without the two new common options; R-V3.6 adds them. Own commit f44fbd7.
- Commits (interface, dev): f44fbd7 (test), c77fc0b (richtext, charts, i18n, deps), 69549e8 (blocks, tools, init).
  mlareject (dev): lock refresh commit.

## Group 4 steps 4.1 to 4.3: the three tool packages (done, by a helper agent)

- LangBiTe 27 failed / 1 passed -> **28 passed** (4db2bf4); StrongREJECT 22/1 -> **23 passed** (4af9b42);
  promptfoo 20/1 -> **21 passed** (41c4ab8). No test edited.
- Notes for wiring: chart colours are read from `getattr(ctx, "chart_colours", None)` (a name the helper chose;
  the renderer's BlockContext gains `chart_colours`); `detail="summary"` also hides the tables of StrongREJECT
  and "Other measurements" of promptfoo (the spec defines summary only for LangBiTe).

## Group 2: the renderer core (done)

- Commits (generator, dev): d71ead9 (registry tests, section 4), 539fef5 (by-design: two more old tests),
  03688d0 (snapshot v2, languages, context, service routes), 8473143 (chapters, appendix, numbering, TOC page
  numbers, header/footer/marking/document id, commentary, free text formats), ac65a02 (tool contract check),
  ead5924 (translations, fr.json). Plan commits 3, 4 and 5 are one commit: they all change document.py.
- Interface (dev): 1193ab2 adds neutral aliases `LanguageFile`, `read_language_file`, `package_language_file`.
- Deviation D4-1: the old guard `test_data_access.py::test_r6_5_the_renderer_never_names_the_catalogue` forbids
  the word in any renderer .py/.j2, so the plan's `languages.catalogues()` is `languages.language_files()`,
  and the renderer imports the interface's loader under the neutral aliases above.
- By-design test changes (539fef5, not in the plan's section 4): `test_snapshot.py::test_r5_4_2_problems_carry_the_json_pointer`
  used `mode="docx"` as its invalid example (R-V8.9 makes it valid; now `"word"`);
  `test_document.py::test_r1_3_a_block_gets_exactly_its_context` expected options without the commentary
  defaults (R-V3.6). Also `test_registry.py::test_r3_6_other_options_are_not_references` gains the five new
  reference options of R-V1.4 (in d71ead9).
- `BlockContext.number()` keeps `str(value)` (not `:g`) so English stays byte identical (control answer scores
  print "4.0" as today).
- After group 2: generator 513 total, 166 failed (all group 3/4/6 tests plus the 2 known), goldens 11/11 green.

## Group 3: the renderer's blocks and data (done)

- Commits (generator, dev): 6c8da28 (by-design test), 617acf3 (readable evaluations, metric filter, tool
  options), 52702df (filters), 50b38ae (coverage-choices route), 5bb6f13 (key figures and chart; plan commits
  4 and 5 in one, they share context.py and blocks/__init__.py), 800276d (new unit tests, DV2-5), 4c6e453
  (changes_since), 5f1fd3c (labels, help, More options), 38d818e (new test: key figures source-error tile).
- By-design test change (6c8da28, not in the plan): `test_block_test_results.py::test_r2_5_evaluations_and_tools_filters`
  asserted "Mystery Tool" is absent from the whole section with `tools=["LangBiTe"]`; R-V2.1 names every tool of
  the evaluation in its heading whatever the filter ("Evaluation 2: LangBiTe, Mystery Tool", pinned by
  `test_r_v2_1_the_number_does_not_depend_on_the_filters`). The test now checks the runs shown (the h4 headings).
- New tests (DV2-5): `tests/test_v2_changes_since_unit.py` (6, seen failing before the block existed) and
  `tests/test_v2_key_figures_source_error.py` (1, written after the block, passes).
- Deviation D4-2: `metric_choices` and the evaluation choice labels are computed in `views.py` / the block from
  the scoped readers, not as new SQL in `data/engine.py` (same data, no new query).
- Deviation D4-3: BlockContext gains `chart_colours` (template primary, `#000000`, `#CCCCCC`), the name the tool
  packages read; `context_for` gains `primary_color=`.
- An unmapped risk (no objective) is hidden when a requirement-group filter is set, as for an objective filter
  (R-V6.2 names only "objective filter"; a group filter narrows the objectives too).

## Group 4 step 4.4: wiring (done)

- pyproject: the three packages (path sources, editable), python-docx, cairosvg, lxml; Dockerfile: three
  `COPY --from=` build contexts. Commit: see the commit list at the end.
- After groups 2 to 4: generator 520 total, 17 failed = test_docx (14) + test_e2e_v2 (1) + the 2 known.
  Goldens 11/11 green with the dedicated renderers.

## Group 5: the composer (done, by a helper agent)

- Start 330 total, 189 failed. After 5.1 to 5.3: 262 passed, 68 failed; after 5.4: 311/19; after 5.5:
  **321 passed, 9 failed** (the 8 known helper defects and test_e2e_v2, which waited for the renderer).
- Commits (aisc-install, feat/unified-modules, only paths under apps/report-composer/): bee8ff2 (section 4 test
  update), d24527d (test fix), 2689256 (migration 0005), 1af887f (layouts: language, document settings, coverage
  map, optional template, PDF or Word, and presets), e664b2b (forms and pages), 57f2491 (composer.js, 456 lines,
  no alert/confirm/prompt). guard-frozen.sh matched 00-baseline.md after each commit.
- Test fix (d24527d): `tests/test_v2_renderer_client_unit.py` used a callable instance as a stand-in for a
  method, so Python never passed it `self`; it is now wrapped in a function (plainly wrong helper).
- Deviations: plan commits 2 and 3 are one commit (api.py needs both); the macros `message_region` and
  `confirm_dialog` live in a new `templates/_ui.html.j2`; the legacy per-field check of a Summary block's own
  `links` skips a field for which the renderer offers no choices (else a layout with legacy links could not be
  saved against the v2 fake); an empty header or footer text is stored as NULL (default header, no footer).

## Group 6: DOCX and the French review (done)

- `report_renderer/docx.py` (lxml.html walk, python-docx, cairosvg for inline SVG). Inline SVG is taken from
  the HTML string by position (lxml's HTML parser lowercases `viewBox`). `document.margin_texts()` gives the
  margin texts to both the PDF `@page` rule and the DOCX header and footer.
- test_docx 14/14. Generator suite: **518 passed, 2 failed** (the 2 known). Commit 7585b3b.
- French review: renderer fr.json (no word "catalogue", no em dash) and the three package files read end to end.

## Group 7: verification at the end of stage 4 (done)

`env | grep -iE 'DATABASE|DSN|DB_URL'` printed nothing before every run; every database suite used its own
`aisc-t-*` container; `docker ps -a --filter name=aisc-t-` is empty at the end. Nothing was run against the
live stack.

| suite | result | expected by the plan | remaining failures and cause |
|---|---|---|---|
| aisc-report-plugin-interface | 121 passed | 121 | none |
| aisc-report-langbite | 28 passed | 28 | none |
| aisc-report-strongreject | 23 passed | 23 | none |
| aisc-report-promptfoo | 21 passed | 21 | none |
| aisc-report-mlareject | 19 passed | 19 | none |
| aisc-report-generator | 518 passed, 2 failed (520) | 501 + 2 (grows by 10 registry cases and 7 new tests) | test_block_ai_card.py::test_r2_2_2_tags (pre-existing, contradicts the spec); test_service.py::test_r5_4_1_no_token_no_answer[get-/v1/block-types] (pre-existing helper defect, `client.get(json={})`) |
| apps/report-composer | 322 passed, 8 failed (330) | 322 + 8 | test_api_access.py::test_r4_4_3_a_stranger_gets_404 x4 (`get(json=None)`), test_api_reports.py x4 (`Throwaway.rows()` footer parsing): pre-existing helper defects |
| scripts/tests report stack + grants | 75 passed, 7 failed | 75 + 7 | the 7 known: guard and launcher card count and init text follow other people's working tree; 4 grants tests hit the `rows()` helper defect |

- End-to-end: generator `tests/test_e2e_v2.py tests/test_e2e.py` 4 passed; composer `tests/test_e2e_v2.py
  tests/test_e2e.py` 3 passed (the real renderer started with uvicorn from the generator repo).
- guard-frozen.sh: G1 FAIL (238 lines), G2 PASS, G3 PASS (hashes), G3 PASS (tests/test_vendored.py), the three
  G4 FAIL lines, G5 PASS, GUARD FAIL: the same lines as 00-baseline.md (temporary paths aside).
- Image smoke: `aisc-report-renderer:report-v2-test` built with the five build contexts; `report_service`,
  `docx`, `cairosvg`, `lxml` and the three packages import; the registry lists MLA-Reject, Promptfoo,
  StrongREJECT, LangBiTe. `aisc-report-composer:report-v2-test` built; its four built-in presets load. Both
  images removed. No stack image was rebuilt or retagged.
- Manual, browser only (not automated, for stage 5 or the user): R-U3.4 debounce, single request in flight and
  stale answers ignored; R-U3.5 inline error keeps the last preview; R-U7.3 Esc and focus order of the dialog;
  R-V4.15 hidden fields not sent; R-U1.3 the reset question flow; R-V3.13 disclosure toggling.

## Deviations (all groups)

- D4-1 (renderer): `languages.language_files()` instead of the plan's `languages.catalogues()`; the old guard
  test forbids the word "catalogue" in any renderer .py/.j2. The interface gains neutral aliases (1193ab2).
- D4-2 (renderer): metric choices and evaluation choice labels are built in `views.py`/the block from the
  scoped readers, not as new SQL in `data/engine.py`.
- D4-3 (renderer): `BlockContext.chart_colours` (the name the tool packages read) and `context_for(...,
  primary_color=)`.
- D4-4 (renderer): an unmapped risk is hidden under a requirement-group filter too, not only under an objective
  filter (both narrow the objectives).
- D4-5 (renderer): plan commits 3 to 5 of group 2 and 4 to 5 of group 3 are single commits (shared files).
- D4-6 (packages, helper agent): `detail="summary"` also hides the tables of StrongREJECT and promptfoo's
  "Other measurements" (the spec defines summary only for LangBiTe).
- D4-7 (composer, helper agent): see the group 5 section (one commit for plan commits 2 and 3, `_ui.html.j2`,
  legacy links check without choices, empty header or footer stored as NULL).
- By-design test changes outside the plan's section 4, each in its own commit: interface f44fbd7
  (test_r1_6 common defaults); generator 539fef5 (test_r5_4_2 mode example, test_r1_3 options), 6c8da28
  (test_r2_5 tools filter), and the extra reference options in test_r3_6 (inside d71ead9); composer d24527d
  (plainly wrong helper in test_v2_renderer_client_unit).
- New tests added (DV2-5): generator tests/test_v2_changes_since_unit.py (6) and
  tests/test_v2_key_figures_source_error.py (1).

## Questions for the user

- The ten questions of 01-specs.md section 20 and Q2-1 are still open; the code follows their defaults.
- Q3-1 (deploy, unchanged): before the next deploy the renderer service in the compose file needs the build
  contexts `langbite`, `strongreject`, `promptfoo`. `DEFAULT (user to confirm)`: not changed in this run.
- Q3-2: composer.js is 456 lines (limit raised to 500). `DEFAULT (user to confirm)`: accepted.
- Q4-1: French marking label for "Public" is "Diffusion libre" (the test requires a text different from the
  English word). `DEFAULT (user to confirm)`.

## Commits per repo (local, dev or feat/unified-modules, nothing pushed)

- aisc-report-plugin-interface (dev): f44fbd7, c77fc0b, 69549e8, 1193ab2.
- aisc-report-mlareject (dev): 4942594.
- aisc-report-langbite (dev): 4db2bf4. aisc-report-strongreject (dev): 4af9b42. aisc-report-promptfoo (dev): 41c4ab8.
- aisc-report-generator (dev): d71ead9, 539fef5, 03688d0, 8473143, ac65a02, ead5924, 6c8da28, 617acf3, 52702df,
  50b38ae, 5bb6f13, 800276d, 4c6e453, 5f1fd3c, 38d818e, a92502f, 7585b3b.
- aisc-install (feat/unified-modules): bee8ff2, d24527d, 2689256, 1af887f, e664b2b, 57f2491, and the docs commit
  of this file and PROGRESS.md.
- `git status` is clean in the five report repos; in aisc-install only other people's files and caches remain.
