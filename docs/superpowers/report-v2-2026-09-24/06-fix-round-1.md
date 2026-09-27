# Fix round 1 of report run v2

Status: done. Inputs: RULES.md, 01-specs.md, 04-code-report.md, 05-verify.md and the code. Every fix was made
test-first: the new or tightened test was run and seen failing for the finding, then the code was changed, then the
test and the repo's whole suite passed. One commit per finding per repo, local only, nothing pushed. The live `aisc`
stack and its databases were not touched; every database suite made its own `aisc-t-*` container and none is left.

## Findings fixed

| # | finding (05-verify.md) | test that pins it | commit(s) |
|---|---|---|---|
| 1 | Numbered reports showed two numbers per TOC entry ("1. 1 Chiffres clés", numbered appendix) | generator `tests/test_document_structure.py::test_fix1_pdf_toc_shows_each_number_once` (lays out the HTML handed to WeasyPrint and lists the list markers: 5 markers before, none after; pypdf cannot see markers), `::test_fix1_without_numbering_the_toc_keeps_its_list_markers` (compatibility), `::test_fix1_docx_toc_shows_each_number_once` (the Word TOC text; it already had one number) | generator 2047eea: feature CSS `css/numbering.css` (`#toc ol { list-style: none }`), added only when numbering is on, so layouts without numbering and the goldens stay identical |
| 2 | French key-figure tool tiles showed "0.2", "68.8%", "1 of 4" | interface `tests/test_v2_contracts.py::test_fix2_*` (4: base accepts ctx, ctx passed to a renderer that takes it, a renderer with `headline(self, run)` still called as before, `**kw` accepted); each tool package `tests/test_tool_renderer.py::test_fix2_headline_values_follow_the_report_language` ("68,8 %", "1 sur 4", "0,2", "85 %"); generator `tests/test_v2_key_figures.py::test_fix2_french_tool_tiles_use_french_numbers_and_words`, `::test_fix2_english_tool_tiles_are_unchanged`, `::test_fix2_a_contract_2_renderer_whose_headline_takes_only_the_run_still_gets_tiles` | interface e9755a2 (`headline(run, ctx=None)`, new `tools.headline_items(renderer, run, ctx)` that passes `ctx` only when the method accepts it); langbite db7adbf, strongreject 8611f44, promptfoo 2dcd7c1 (values formatted with `ctx`; without ctx unchanged); generator 057e2df (key_figures calls `headline_items`) |
| 3 | CSS injection through header/footer text (form feed and other controls) | generator `tests/test_header_footer.py::test_fix3_css_string_is_one_string_token_with_the_text` (9 cases: form feed, controls incl. NUL/ESC/DEL/NEL, backslash, quotes, newlines, U+2028/2029, `</style>`, unicode incl. NBSP and zero-width, trailing backslash; tinycss2 must see exactly one string token equal to the text), `::test_fix3_a_form_feed_in_the_header_does_not_restyle_the_pdf` (the verifier's payload hid the body paragraph before the fix), `::test_fix3_control_characters_in_the_header_do_not_break_the_word_file` (the DOCX render raised `ValueError` before) | generator 27e868f: `_css_string` hex-escapes every character that is not printable (plus `<`), keeps the pinned escapes for `\`, `"`, `<`; the DOCX margins turn XML-forbidden characters into spaces |
| 4 | Chapter intros leaked into saved presets without "Keep texts" | composer `tests/test_v2_presets.py::test_fix4_a_saved_preset_drops_the_chapter_intro`, `::test_fix4_the_layout_export_drops_the_intro_and_keep_text_keeps_it`, `::test_fix4_any_long_text_option_of_a_plugin_block_is_dropped_too` | aisc-install 8cf13ef: `presets._free_text_options` treats as free text the common commentary, `free_text.text`, `chapter.intro` and every string option whose schema allows more than 300 characters (titles and the cover subtitle stay); a required one gets the placeholder, the others become empty |

## Mechanical notes fixed

| note | test | commit(s) |
|---|---|---|
| 5: preview stopped refreshing after a network failure | composer `tests/test_v2_browser.py::test_fix_the_preview_recovers_after_a_network_failure` (Playwright on the system Chrome against the composer served by uvicorn: the first draft request is aborted, the label shows "The composer could not be reached.", the next click sends a request and the preview updates; before: an uncaught "Failed to fetch" and no second request) | aisc-install f03e6d5: `call()` turns a failed fetch into an answer with status 0, `refresh()` resets `inFlight` in `finally`. Adds `playwright>=1.40` to the composer's dev extras (uv.lock updated; the image installs no dev extras) |
| 6: chapter indentation and "This chapter is empty." stale after moving blocks | composer `tests/test_v2_browser.py::test_fix_chapter_indentation_follows_a_move` (browser: move a block out of and back into a chapter), `tests/test_v2_pages.py::test_fix_outline_route_gives_depth_and_empty_chapter_for_any_order`, `::test_fix_outline_route_is_for_editors_and_checks_its_input` | aisc-install 576b157: the depth rule moved to `layouts.outline_depths`/`layouts.outline` (Python); new route `POST /api/p/{ref}/layouts/{id}/outline` (editor); composer.js redraws depth and hint after add, move, remove and drag (483 lines, limit 500) |
| 13: "1 objectifs" and other plurals built the same way | interface `tests/test_v2_i18n.py::test_fix_plural_*` (10); generator `tests/test_i18n.py::test_fix_french_singular_forms` (12 messages, singular for 1 and plural unchanged for 3), `::test_fix_every_singular_form_belongs_to_a_used_message`; langbite `::test_fix_french_one_group_is_singular` | interface 7999876: a catalogue may hold `"<msgid>\|one"`, chosen when the first whole-number parameter is in `_meta.plural_one` (default [1]); generator 7bc92ca (fr.json `plural_one: [0, 1]` and 12 singular forms); langbite 4bbf943 ("sur 1 groupe") |
| 11: weak test (a word in composer.js) | composer `tests/test_v2_pages.py::test_r_u1_1_python_computes_the_grid_and_js_only_collects` now runs in the browser: the PUT on save carries exactly the ticked boxes, the summary count does not change in the page, after reload it reads Python's new count | aisc-install 80508ba (tightened, not weakened) |
| 12: golden `a_v2_live_styled.pdf.json` compared by no test | generator `tests/test_compat_golden.py::test_fix_r_c_4_pdf_text_with_evaluations_only_the_test_results_section_may_change`: the PDF text flow (margin lines, lone list markers, TOC page numbers and repeated table headers removed) must equal the golden before the Test results heading and from the Control answers heading on. KEPT and compared, not removed. A mutation check (checklist heading changed in the template) makes it fail | generator 7e7024e |

## Final counts (stage 6, every suite run once more after the last commit)

`env | grep -iE 'DATABASE|DSN|DB_URL'` printed nothing before the runs.

| suite | result now | after stage 4/5 | remaining failures |
|---|---|---|---|
| aisc-report-plugin-interface | 135 passed | 121 | none |
| aisc-report-langbite | 31 passed | 28 | none |
| aisc-report-strongreject | 24 passed | 23 | none |
| aisc-report-promptfoo | 22 passed | 21 | none |
| aisc-report-mlareject | 19 passed | 19 | none |
| aisc-report-generator | 549 passed, 2 failed | 518 + 2 | the 2 known: test_r2_2_2_tags, test_r5_4_1[get-/v1/block-types] (`get(json=...)`) |
| apps/report-composer | 329 passed, 8 failed | 322 + 8 | the 8 known helper defects (4 x `get(json=None)`, 4 x `Throwaway.rows()`) |
| scripts/tests report stack + grants | 75 passed, 7 failed | 75 + 7 | the 7 known (other people's work, guard, `rows()`) |
| generator e2e (test_e2e_v2.py, test_e2e.py) | 4 passed | 4 | none |
| composer e2e (test_e2e_v2.py, test_e2e.py) | 3 passed | 3 | none |

guard-frozen.sh: G1 FAIL (238 lines), G2 PASS, G3 PASS (hashes), G3 PASS (tests/test_vendored.py), the three G4
FAIL lines, G5 PASS, GUARD FAIL: the same lines as 00-baseline.md apart from the temp path.
No `aisc-t-*` container and no headless Chrome left. In aisc-install only paths under `apps/report-composer/` and
this folder were committed; other people's uncommitted files (apps/qualification pointer, homepage/project.html,
form-assembly docs, caches) are untouched and unstaged.

## Deviations

- Finding 2 keeps the tool renderers' contract at `contract_version = 2` (01-specs.md 16.2 and R-S.5: the registry
  skips anything above 2). The context is an optional keyword argument, so older contract-2 renderers keep working
  (tested). Labels and notes stay English message ids translated by key_figures as before; only values change.
- Finding 3: CR, LF and CRLF still become one space (CRLF was two spaces before). The composer still accepts
  control characters in the 120-character header and footer texts; they are now harmless in the renderer, so the
  composer was left unchanged (not needed for the fix).
- Note 13 is fixed for French only. English "1 evaluations" and "in 1 requirement groups" in Key figures remain:
  the stage-2 test `test_i18n.py::test_r_v8_2_en_and_fr_catalogues_have_the_format` pins `en.json` to no messages
  (R-V8.3), and the tool packages have no English catalogue. Fixing English needs a spec change (see below).
- The browser tests add a dev dependency (playwright) to the composer and need `/usr/bin/google-chrome`.

## Not done, and why

- Left for the user as instructed: imported presets keeping another platform's reference ids (note 7), the
  "Write this section." placeholder in reports generated straight from a preset (note 8), English preset chapter
  titles in a French layout (note 9), the test-helper defects `Throwaway.rows()` and `TestClient.get(json=None)`
  (note 10).
- English singular forms (above): would need R-V8.3 changed to allow `|one` entries in `en.json`.

## Commits (local, nothing pushed)

- aisc-report-generator (dev): 2047eea, 27e868f, 057e2df, 7bc92ca, 7e7024e
- aisc-report-plugin-interface (dev): e9755a2, 7999876
- aisc-report-langbite (dev): db7adbf, 4bbf943; aisc-report-strongreject (dev): 8611f44; aisc-report-promptfoo (dev): 2dcd7c1
- aisc-install (feat/unified-modules): 8cf13ef, f03e6d5, 576b157, 80508ba, and the docs commit of this file and PROGRESS.md
