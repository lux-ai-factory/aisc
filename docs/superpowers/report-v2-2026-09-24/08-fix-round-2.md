# Fix round 2 of report run v2 (the last)

Status: done. Inputs: RULES.md, 06-fix-round-1.md, 07-reverify.md and the code. Every item was made test-first: the
new test was run and seen failing for the finding, then the code was changed, then the test and the repo's whole
suite passed. One commit per item, local only, nothing pushed. The live `aisc` stack and its databases were not
touched; every database suite and the guard made their own `aisc-t-*` container and none is left.

## Items fixed

| # | finding | test (seen failing first) | commit |
|---|---|---|---|
| 1 | DOCX export failed (500) on characters XML 1.0 forbids in body text (07 finding 1) | generator `tests/test_docx.py::test_fix_r2_1_html_to_docx_makes_every_text_xml_safe` (12 classes: NUL, SOH, BS, VT, FF, SO, ESC, US, lone high and low surrogate, U+FFFE, U+FFFF; each in the TOC, title, chapter heading, heading, paragraph, bold run, link, commentary, list item, table header and cell, definition list, picture alt text, figure caption, chart title and bar label, document title and subject, margin; every XML part of the package must be free of them and the chart must stay a picture), `::test_fix_r2_1_a_docx_render_with_forbidden_characters_in_the_texts_succeeds` (10, through the whole renderer: cover title and subtitle, chapter title and intro, free text titles, markdown and plain text, markdown table cells, commentary), `::test_fix_r2_1_character_references_to_forbidden_characters_are_safe_too` (5: `&#1;` and the like, which lxml turns into the character, incl. the nested-block paths of list items and table cells), `::test_fix_r2_1_a_character_reference_in_markdown_free_text_renders_as_docx`. Before the fix: 23 failed (ValueError from lxml, UnicodeEncodeError for surrogates); the 5 that passed are whitespace-like characters that the old folding already removed | generator dfb3a51: `docx._xml_text` turns every forbidden character into a space; applied to the whole HTML before parsing (so cairosvg can still draw charts), to every run, hyperlink, TOC entry, nested-block holder text, notice, page-number piece and the core properties |
| 2 | a lone surrogate anywhere in a snapshot crashed the renderer (07 note 6) | generator `tests/test_snapshot_v2.py::test_fix_r2_2_a_lone_surrogate_is_a_validation_problem` (5: block option, nested list/dict, dict key, layout name, style header text; pointer, instance id, and the problem list itself can be encoded), `::test_fix_r2_2_render_refuses_a_lone_surrogate_cleanly` (preview, pdf, docx raise InvalidSnapshot), `::test_fix_r2_2_the_service_answers_422_for_a_lone_surrogate` (raw JSON body with `\ud800`), `::test_fix_r2_2_a_valid_surrogate_pair_is_fine` (guard). Before: 9 failed | generator 69a9046: `snapshot.validate` walks every key and string and reports `invalid_snapshot` "holds a lone surrogate"; pointers show such characters as backslash escapes. The service already maps InvalidSnapshot to 422 |
| 3 | French colon spacing built outside `t()` (07 note 2) | generator `tests/test_v2_key_figures.py::test_fix_r2_3_french_label_value_texts_use_the_french_colon` (French key figures, summary and coverage, control objectives by objective with rationale and by risk: no "x: " left; "5 : 1", "StrongREJECT : ", "aucun élément probant : 1"), `::test_fix_r2_3_english_label_value_texts_are_unchanged`. Before: failed on key figures, then on the summary counts, the rationale and the risk headings, each seen failing in turn | generator f211e16: one message `"{label}: {value}"` (fr.json: `"{label} : {value}"`) used at key_figures.py (severities, coverage note, tool tile labels) and, found by the same test, in summary_coverage.html.j2 (coverage counts) and control_objectives.html.j2 (risk heading, rationale). English output is identical (goldens pass) |
| 4 | outline route had no block limit (07 note 3) | composer `tests/test_v2_pages.py::test_fix_r2_4_outline_route_refuses_more_blocks_than_a_layout_holds` (51 blocks: 422 `too_many_blocks`, pointer `/blocks`; 50 blocks: 200). Before: 200 | aisc-install f6ceb16: `api.outline` refuses more than `layouts.MAX_BLOCKS` with the same error code as layout save |
| 5 | stale outline after two quick moves answered out of order (07 note 4) | composer `tests/test_v2_browser.py::test_fix_r2_5_an_older_outline_answer_arriving_last_is_ignored` (Playwright, as the other browser tests: the first outline request is held, the second move's answer arrives, then the first is released; depth and hint must stay those of the latest order). Before: depth "0" after the late answer | aisc-install 6515735: composer.js numbers outline requests and drops an answer that is not the latest (3 lines, file now 486 lines) |

## Final counts (every suite run after the last commit; `env | grep -iE 'DATABASE|DSN|DB_URL'` empty)

| suite | now | after round 1 | remaining failures |
|---|---|---|---|
| aisc-report-plugin-interface | 135 passed | 135 | none |
| aisc-report-langbite | 31 passed | 31 | none |
| aisc-report-strongreject | 24 passed | 24 | none |
| aisc-report-promptfoo | 22 passed | 22 | none |
| aisc-report-mlareject | 19 passed | 19 | none |
| aisc-report-generator | 589 passed, 2 failed | 549 + 2 | the 2 known: test_r2_2_2_tags, test_r5_4_1[get-/v1/block-types] |
| apps/report-composer (incl. 3 browser tests + browser test_r_u1_1) | 331 passed, 8 failed | 329 + 8 | the 8 known helper defects (4 x `get(json=...)`, 4 x `Throwaway.rows()`) |
| scripts/tests report stack + grants | 75 passed, 7 failed | 75 + 7 | the 7 known |
| generator e2e (test_e2e_v2.py, test_e2e.py) | 4 passed | 4 | none |
| composer e2e (test_e2e_v2.py, test_e2e.py) | 3 passed | 3 | none |

Generator +40 tests (28 item 1, 10 item 2, 2 item 3); composer +2 (items 4 and 5).

guard-frozen.sh: G1 FAIL (238 lines), G2 PASS, G3 PASS (hashes), G3 PASS (tests/test_vendored.py), the three G4 FAIL
lines, G5 PASS, GUARD FAIL: the same lines as 00-baseline.md apart from the temp path.
No `aisc-t-*` container, no `*:report-v2-test` image, no headless Chrome, no extra worktree left. In aisc-install
only `apps/report-composer/**` and this folder were committed; other people's uncommitted files (apps/qualification
pointer, homepage/project.html, form-assembly docs, caches) are untouched and unstaged.

## Deviations

- Item 1: forbidden characters become a space (as the margins already did in round 1), not removed, so words on
  both sides stay apart. The PDF path is unchanged (WeasyPrint accepted them already).
- Item 2: refused, not replaced: a lone surrogate is a 422 `invalid_snapshot` problem with its pointer. The composer's
  jsonb storage already refuses them, so only a direct caller with the service token can meet this.
- Item 3: the language file decides the separator through a message, not a new `_meta` key, so the interface and
  en.json (pinned empty by R-V8.3) stay unchanged. The composer-side choice labels `"{tool}: {metric}"`
  (views.py:89, chart.py:244) were left: they are option labels shown in the English composer UI, not report text.
- Item 4: the pointer is `/blocks` (as the route's other input errors), where layout save gives an empty pointer;
  the error code `too_many_blocks` is the same.

## Not done (user decisions, as instructed)

The preset free-text rule for future plugin blocks (07 note 5); the items 06 left for the user (imported presets
keeping another platform's reference ids, the "Write this section." placeholder from presets, English preset chapter
titles in a French layout, English singular forms); the test-helper defects `Throwaway.rows()` and
`TestClient.get(json=None)`; the Chrome requirement of the composer suite (07 note 7).

## Commits (local, nothing pushed)

- aisc-report-generator (dev): dfb3a51, 69a9046, f211e16
- aisc-install (feat/unified-modules): f6ceb16, 6515735, and the docs commit of this file and PROGRESS.md
