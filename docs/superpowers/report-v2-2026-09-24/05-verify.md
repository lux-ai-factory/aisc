# Stage 5: Verification of report run v2

Status: stage 5 of 5, done. Inputs: RULES.md, BRIEF.md, 00-baseline.md, 01-specs.md, 02-tests.md,
03-coding-plan.md, 04-code-report.md and the code. Every number below was re-measured by this stage; no earlier
report was taken on trust. No code or test was changed. Helper scripts used for checking live only in the session
scratchpad (pytest plugins loaded with `-p`, a headless-browser script); none is committed.

## Verdict: PASS WITH NOTES

All suites give the numbers 04-code-report.md claims, and every remaining failure is a pre-existing test-helper
defect or a check that follows other people's working tree (proven by re-running the masked tests with the
helpers repaired in memory: they pass). Both end-to-end tests pass and produce a French PDF and DOCX with page
numbers in the TOC, commentary, chapters, SVG charts and the three tool sections. The goldens are untouched and
still pass, also when fed the v2 snapshot the new composer sends. Every test change after stage 2 is by design and
recorded. Boundaries hold: guard output equals the baseline, nothing is pushed, nothing leaked into frozen areas,
the live stack is untouched. All six browser-only behaviours pass in headless Chrome.

There is no blocker. Four findings should be fixed before users rely on the features (numbered TOC shows two
numbers per entry; French key-figure tool values stay English; header/footer text can inject CSS; saved presets keep chapter intros), plus notes.

## A. Suites

`env | grep -iE 'DATABASE|DSN|DB_URL'` printed nothing before the runs. Every database suite made its own
`aisc-t-*` container; none of mine was left behind.

| suite | command | result (stage 5) | 04-code-report.md | remaining failures |
|---|---|---|---|---|
| aisc-report-plugin-interface | `uv run --extra dev pytest -q` | 121 passed | 121 | none |
| aisc-report-langbite | same | 28 passed | 28 | none |
| aisc-report-strongreject | same | 23 passed | 23 | none |
| aisc-report-promptfoo | same | 21 passed | 21 | none |
| aisc-report-mlareject | same | 19 passed | 19 | none |
| aisc-report-generator | same | 518 passed, 2 failed (88.8 s) | 518 + 2 | test_block_ai_card.py::test_r2_2_2_tags; test_service.py::test_r5_4_1_no_token_no_answer[get-/v1/block-types] |
| apps/report-composer | same | 322 passed, 8 failed (150.9 s) | 322 + 8 | test_api_access.py::test_r4_4_3_a_stranger_gets_404 x4; test_api_reports.py x4 (r4_2_5, r3_12, r4_3_5, r7_2_5) |
| scripts/tests report stack + grants | `uv run --no-project --with pytest python -m pytest -q scripts/tests/test_report_stack.py scripts/tests/test_report_grants.py` | 75 passed, 7 failed | 75 + 7 | 3 stack checks, 4 grants tests |

Each remaining failure, judged by reading the test and the traceback:
- generator test_r2_2_2_tags: listed in 00-baseline.md as failing before the run (contradicts the spec). Pre-existing.
- generator test_r5_4_1[get-/v1/block-types]: `TypeError: Client.get() got an unexpected keyword argument 'json'`.
  Helper defect (the test passes `json={}` to a GET). Re-run with an in-memory shim that drops `json=None/{}` on
  GET: test_service.py 18 passed.
- composer test_api_access x4: same `Client.get(json=...)` TypeError. With the shim: pass.
- composer test_api_reports x4 and grants x4: `JSONDecodeError ... s = '(1 row)'` in
  `scripts/pipeline_chain/throwaway.py:69` (`Throwaway.rows()` parses psql's row-count footer as JSON). The
  assertions behind them (generate stores snapshot and PDF, snapshot survives edits, renderer failure is 502 and
  failed, 25 MB limit; grants) never ran. I re-ran them with `rows()` repaired in memory (a scratch pytest plugin
  that ignores the footer): composer test_api_access.py + test_api_reports.py 34 passed, scripts suites 79 passed,
  3 failed. So no regression hides behind the helper defects.
- stack test_d6_guard_init_files_do_not_mention_report_roles (init/project-databases.sql mentions
  report_composer, last changed 2026-09-24 19:34 by 3e20ffb, before the run), test_r4_1_2_launcher_card_seven
  (homepage/project.html, another session's uncommitted change), test_final_guard_frozen_passes (guard FAILs as at
  baseline). All three follow other people's work, not this run.

## B. End-to-end tests and the documents they produce

- Renderer: `tests/test_e2e_v2.py tests/test_e2e.py` 4 passed. The render answers were saved by a scratch plugin
  wrapping `httpx.Client.post`. Composer: `tests/test_e2e_v2.py tests/test_e2e.py` 3 passed (real renderer started
  with uvicorn from the generator repo, stopped afterwards); the downloads were saved the same way.
- Renderer PDF (Mike v2, fr, 10 pages), text extracted with pypdf and pages 1, 2, 6 viewed as images:
  French throughout (Couverture, Sommaire, Chiffres clés, Résultats des tests, Annexe, "Page 1 sur 10", decimal
  commas in the tool sections, "INTERNE" marking top right and on the cover, "Document 3c9d1f2e | Empreinte
  de2a412d7264" id line). TOC entries end with page numbers (for example "2.2 Graphique ...... 6"). Chapters
  "2 Tests" and "3 Versions" with nested 2.1, 2.2, 3.1 and the appendix part "A Réponses aux contrôles".
  Commentary boxes with the caption "COMMENTAIRE". SVG charts drawn (LangBiTe pass rate by concern, StrongREJECT
  harmfulness by jailbreak, promptfoo rates, checklist scores). StrongREJECT failed run shows "non noté : ..."
  instead of 0.0. No "No dedicated renderer" notice, no HARMFULPROMPTCONTENT. Defects seen: finding 1 (double
  numbers in the TOC) and finding 2 (tool tiles "0.2", "68.8%", "1 of 4" in a French report).
- Renderer DOCX: core properties title "Quarterly report", subject "Mike project", language "fr", author empty;
  header "Mike project, version 2 / INTERNE"; footer with the id line and PAGE / NUMPAGES fields; TOC field
  `TOC \o "1-2" \h \z \u` and `updateFields` in settings.xml; 4 PNG pictures (the charts); Heading 1 "2 Tests",
  Heading 2/3/4 for sections, evaluations and runs; 14 tables.
- Composer PDF (preset eu-ai-act, French, 12 pages) and DOCX: "Sommaire" with page numbers, "Page 1 sur",
  chapters "2 System and risks", "3 Control objectives", "4 Evidence", appendix, LangBiTe, StrongREJECT and
  Promptfoo sections. Chapter titles and the cover title stay English (preset data, see finding 9).

## C. Compatibility

- `git log --oneline 8611de9..HEAD -- tests/golden` in aisc-report-generator is empty: the goldens (and
  capture.py, MANIFEST.json with `renderer_commit: 26e235d`) are unchanged since the stage-2 golden commit, and
  the working tree is clean. test_compat_golden.py: 11 passed inside the full run.
- The goldens were rendered a second time with the snapshot the new composer sends for an old layout after
  migration 0005 (snapshot_version 2, language en, document defaults, coverage_links = the first summary block's
  links with that block's links emptied, style with the four new fields at their defaults), by patching
  `golden_cases.snapshot_for` in a scratch plugin: 11 passed. A control run with `language="fr"` failed 10 of 11,
  so the patch was in effect. This covers R-C.3 at the renderer, which the composer's own test checks only at
  snapshot level.
- The tests pin the allowed differences: byte-identical HTML and statuses for Delta v1 (no evaluation, R-C.1);
  PDF text equal apart from TOC page numbers (R-C.4 item 3); only the Test results section may change on Alpha v2
  and Mike v2 (items 1, 2), the Mystery Tool keeps its generic table; only the second summary block may change with
  legacy links (item 4). `report.css` is unchanged since 26e235d. I found no other output change for an existing
  layout. Gap (note): `a_v2_live_styled.pdf.json` was captured but no test compares it.

## D. Test integrity (stage-2 commit to HEAD, every repo)

`git diff --stat <stage-2 commit> HEAD -- tests` (interface 7d93a31, langbite f4af1d0, strongreject 34cad23,
promptfoo d7b8a4f, mlareject 2dd5649, generator 29c54cc, aisc-install 1752778 incl. scripts/tests and
report_bed.py). Tool packages and mlareject: no test change. No pytest config, conftest or golden change. No
`skip`, `xfail` or `importorskip` was added (the only `importorskip("weasyprint")` in generator test_e2e.py is
older). No test was deleted.

| repo, commit | test and change | judgement |
|---|---|---|
| interface f44fbd7 | test_blocks::test_r1_6: `full_default_options()` gains `commentary`, `commentary_position` | by design (R-V3.6), recorded in 04 |
| generator c2382fe | test_docx::test_r_v8_9_no_text_lost drops "Generated by: preview"; `v2_core_helpers.body_text_nodes` skips text inside `<svg>` | by design, recorded as D3-3 (DOCX turns SVG into a picture; preview vs document author line) |
| generator d71ead9 | test_registry: BUILTINS +5, EXPECTED_DEFAULTS new keys, full defaults +2 common options, test_r3_6 allowlist +5 reference options | planned (03 section 4) plus the R-V1.4 options, recorded |
| generator 539fef5 | test_snapshot::test_r5_4_2 invalid example `mode="docx"` becomes `"word"`; test_document::test_r1_3 options +2 | by design (R-V8.9, R-V3.6), recorded |
| generator 6c8da28 | test_block_test_results::test_r2_5: "Mystery Tool not in whole section" becomes "not among the run headings (h4)"; "LangBiTe" must equal a run heading | by design (R-V2.1 puts every tool of the evaluation in its heading), recorded; the filter is still checked per run, not a weakening |
| generator 800276d, 38d818e | new files test_v2_changes_since_unit.py (6), test_v2_key_figures_source_error.py (1) | additive, recorded (DV2-5) |
| aisc-install bee8ff2 | test_api_templates: 3 tests renamed and inverted (layout without template allowed), export version 2; test_pages: script limit 300 to 500 lines, handler checks "/download" | planned (03 section 4), recorded |
| aisc-install d24527d | test_v2_renderer_client_unit: the Recorder is bound as a method via a lambda | helper fix, recorded; the Recorder's `__call__(self, client_self, ...)` signature shows it was always meant to receive the client |

Every modified assertion is by design and recorded; none is a silent weakening.

## E. Requirement coverage (32 ids sampled)

For each id I read the mapped test(s) and the implementing code; the tests pass (section A).

| id | test (file::name) | asserts the requirement? | code |
|---|---|---|---|
| R-V1.4 | test_v2_presets::test_r_v1_4_references_are_reset_and_generate_is_refused | yes: chart_id dropped, evaluations reset to all, "Choose a value" problem, generate 422 | presets.py `_without_references`, `blocks_for_layout` |
| R-V1.6 | ::test_r_v1_6_a_copy_keeps_everything_but_ids_revision_and_reports | yes: 6 settings equal, options equal, new ids, revision 1, no reports | api.py duplicate, `copy_name` |
| R-V1.9 | ::test_r_v1_9_texts_become_placeholders_unless_kept | yes: placeholder, commentary empty, cover kept, keep_text restores | presets.py `from_layout` (see finding 4) |
| R-V1.10 | ::test_r_v1_10_invalid_options_name_the_block_index | yes: 422 invalid_options with /blocks/1 | presets.py `from_file` |
| R-V2.1 | test_v2_test_results::test_r_v2_1_evaluations_are_named..., ::test_r_v2_1_the_number_does_not_depend... | yes: exact heading list, numbering stable under filters | blocks/test_results |
| R-V2.5 | ::test_r_v2_5_only_selected_metrics_reach_the_tool_renderer | yes: a recording renderer sees only the chosen metric | test_results metric filter |
| R-V2.13 | LB test_tool_renderer::test_r_v2_13_* | yes: n/a cells, pass rate from score, "Other measurements" | langbite parsing.py, renderer.py |
| R-V2.18 | SR ::test_r_v2_18_a_failed_run_is_not_scored, ::..._excluded_from_charts_and_headline | yes: notice, "not scored: ..." per summary, no 0.0, no chart, empty headline | strongreject renderer |
| R-V3.2 | IF test_v2_richtext::test_r_v3_2_output_tags..., ::test_r_v3_2_no_attribute_but_href_and_rel | yes: allowlist over hostile input, only href/rel | richtext.py (raw HTML off, nh3 allowlist) |
| R-V3.3 | ::test_r_v3_3_dangerous_link_gives_text_without_link[javascript, data] | yes | richtext.py `_allowed_href` + nh3 url_schemes |
| R-V3.4 | ::test_r_v3_4_fuzz_never_raises (400 random inputs) | yes | richtext.py fallback to escaped text |
| R-V4.4 | IF test_v2_charts::test_r_v4_4_labels_are_escaped, ::..._long_labels_are_cut | yes | charts.py `escape`, `_cut` |
| R-V4.9 | test_v2_chart_block::test_r_v4_9_auto_orientation | yes: hbar for long labels, bar for 2 short | blocks/chart.py |
| R-V4.10 | ::test_r_v4_10_more_bars_than_max | yes: notice and full table | blocks/chart.py |
| R-V5.2 | test_document_structure::test_r_v5_2_pdf_toc_entries_end_with_the_page_number | yes: real PDF, page 3 | css/toc_pages.css `target-counter` |
| R-V5.6 | ::test_r_v5_6_numbering_with_chapters_and_appendix | yes for headings and TOC text; does not look at the `<ol>` markers (finding 1) | structure.py |
| R-V5.12 | test_header_footer::test_r_v5_12_placeholders... | yes: 5 names filled, unknown and lone brace kept | document.py `fill_placeholders` |
| R-V5.15 | ::test_r_v5_15_the_fingerprint_is_the_sha256... | yes: recomputed independently in the test | snapshot fingerprint |
| R-V6.2 | test_v2_filters::test_r_v6_2_min_severity_keeps_unrated..., ::..._hides_unmapped_risks | yes | objective_filters.py |
| R-V6.9 | test_v2_key_figures::test_r_v6_9_tool_headline_tiles | yes for labels and at most 2 per tool; values not checked in French (finding 2) | blocks/key_figures.py |
| R-V7.3 | test_v2_changes_since::test_r_v7_3_for_version_refuses_other_projects_and_later_versions | yes | context.py `ScopedData.for_version` |
| R-V7.7 | ::test_r_v7_7_tests_per_tool_and_metric | yes: values, change, "only in version 2", no judging words | blocks/changes_since.py |
| R-V8.4 | test_i18n::test_r_v8_4_every_msgid_has_a_french_entry | yes for `t("...")` msgids; texts built outside `t()` escape it (finding 2) | i18n/fr.json |
| R-V8.7 | ::test_r_v8_7_fixed_texts_are_french_data_is_not | yes | languages.py, templates |
| R-V8.15 | test_v2_reports::test_r_v8_15_docx_is_stored..., ::..._old_pdf_route_answers_404 | yes: format, bytes, media type, filename, 404 | reports.py, api.py |
| R-U1.1 | test_v2_pages::test_r_u1_1_the_grid (substantive); ::test_r_u1_1_python_computes_the_grid_and_js_only_collects | the second only checks that two words occur in composer.js (weak, note 11); I read composer.js `coverage()`: it only collects ticks | coverage_map.py, editor.html.j2 |
| R-U2.4 | test_v2_migration::test_r_u2_4_the_lowest_summary_links_become_the_layout_map | yes: map moved, revision and updated_at kept, other block untouched | migrations/0005 |
| R-U3.3 | test_v2_draft_preview::test_r_u3_3_the_html_has_the_csp_meta_as_first_head_element | yes | api.py draft preview |
| R-U4.3 | test_v2_layout_settings::test_r_u4_3_an_empty_list_is_refused... | yes: 422, pointer, message, instance id | layouts.py |
| R-U5.4 | test_service_v2::test_r_u5_4_main_and_more_options_split[14] | yes: exact main/more sets, at most 4 main | block schemas |
| R-U6.1 | test_v2_layout_settings::test_r_u6_1_a_layout_is_saved_and_generated_without_a_template | yes: 201, no style in the snapshot | api.py, reports.py |
| R-U7.1 | test_v2_pages::test_r_u7_1_no_alert_confirm_or_prompt_in_composer_js | yes (static); confirmed by reading the script | composer.js |

## F. Boundaries

- `scripts/guard-frozen.sh` (stage 5): G1 FAIL 238 lines, G2 PASS, G3 PASS (hashes), G3 PASS
  (tests/test_vendored.py), the three G4 FAIL lines (Sean's files; files outside the allowed set; Dockerfile),
  G5 PASS, GUARD FAIL. Identical to 00-baseline.md apart from the temp path.
- Files of the run's 13 aisc-install commits (9edb1e2, 1752778, 5f47cf2, b25b464, c0cabf8, e5fefde, bee8ff2,
  d24527d, 2689256, 1af887f, e664b2b, 57f2491, d884c52): only `apps/report-composer/**`, `scripts/lib/report_bed.py`,
  `scripts/tests/fixtures/report/seed_*.sql` and this folder. The other files changed since 09a7cb2
  (apps/control-objectives, apps/qualification, homepage/llm.html, docs/.../llm-keys) come from the LLM keys
  pipeline's commits (31de564 to 1ed8fed), not from this run. No engine, AIRO, catalogue or other module file is
  in a run commit. Other people's uncommitted files (apps/qualification pointer, homepage/project.html,
  form-assembly docs, caches) are still uncommitted and modified.
- In the report repos: `base_report_plugin.py` and `report.css` unchanged; mlareject only has the lock refresh.
- Nothing pushed: `git ls-remote origin` heads are interface dev e9420af, mlareject dev ac84039, generator dev
  e0a3ec4, aisc-install feat/unified-modules 0b94640; none contains a run commit (`git branch -r --contains`
  empty); local branches are ahead 7, 3, 33, 132. The three new packages have no remote.
- Leftovers: `docker ps -a --filter name=aisc-t-` shows none of this run's containers (one `aisc-t-qual-*` from
  another session appeared during my checks and was left alone); no `*:report-v2-test` image exists.
- Live stack: start times of every running container are identical before and after this stage (compared with
  `docker inspect .State.StartedAt`); report-renderer and report-composer started 2026-09-24 16:02 UTC, before the
  run; `aisc-report-renderer:latest` and `aisc-report-composer:latest` were built 2026-09-24 10:58 and 11:02. A
  read-only query on the live platform DB shows `report_composer.layout` without `language` and no
  `report_composer.preset`: migration 0005 never ran on the live DB.

## G. Browser-only behaviours

Run from source instead of `*:report-v2-test` images (the behaviours are in composer.js; stage 4 already smoke-
built both images): a scratch script built an `aisc-t-verify-*` bed, started the real renderer (uvicorn, generator
repo) and the composer (uvicorn in process, auth on with a test key), and drove headless Chrome
(/usr/bin/google-chrome through Playwright) as mia on project Mike. All stopped and removed afterwards.

| behaviour | result | evidence |
|---|---|---|
| R-V3.13 commentary disclosure | PASS | closed when empty, opens on click |
| R-U3.4 debounce | PASS | three edits 0.4 s apart give one request 1.50 s after the last one, with the newest title and the commentary |
| R-U3.4 single flight and one queued request | PASS | responses delayed 2.5 s: at most 1 in flight, 2 requests in total, the second carries the newest state ("Rapport Q2") |
| R-U3.5 labels and inline error | PASS | "Preview of unsaved changes"; a 502 gives "The preview could not be made: The report renderer failed." with class error, iframe srcdoc unchanged (30805 characters) |
| R-V4.15 hidden fields not sent | PASS | chart with coverage_status: tool_chart, metric, dimension hidden and absent from the posted options; switching to metric_by_evaluation shows only metric |
| R-U1.3 reset question | PASS | an entry "ZZ9.9" written into the throwaway DB is listed under "Not available for this version"; Save opens the dialog with "Reset and save"; Esc keeps it; confirm removes it (coverage `[]`) |
| R-U7.3 dialog | PASS | Cancel focused first, Tab reaches the confirm button ("Delete layout"), Esc cancels, confirm deletes |
| JavaScript errors | none | `pageerror` listener empty |

## H. Quality spot check

- Light-formatting sanitiser (interface richtext.py): markdown-it with raw HTML off, links filtered to
  http/https/mailto before rendering, then nh3 with a tag allowlist and only `href` on `a`; headings and images
  neutralised; any exception falls back to escaped text. Sound.
- SVG charts (charts.py): spec validated (kinds, numbers finite, at most 60 items), every label, title, note and
  formatted value escaped, colours escaped, no I/O. Sound.
- DOCX (docx.py): cairosvg 2.9.1 (`>=2.7` pinned) with `unsafe=False`, whose default fetcher only resolves
  `data:` URLs and forbids XML entities, so an SVG logo cannot read files or reach the network; hyperlinks only
  for http/https/mailto; pictures only from `data:` PNG/JPEG/SVG. Sound.
- Page margins (document.py `_css_string`): escapes backslash, quote, CR, LF and `<`, but not form feed or other
  control characters. A header or footer text containing `\f` ends the CSS string and injects CSS (finding 3).
- Preset import (presets.py `from_file`): format, version, 50 blocks, known types and options checked; stored
  presets keep reference values and an unchecked language (finding 7).
- composer.js (456 lines): no business logic found. It collects values, applies `x-aisc-show-if`, shows the
  "Pick at least one" hint, and draws what Python returns. Two robustness notes (findings 5 and 6).

## Findings

1. **should fix**: numbered reports show two numbers per TOC entry.
   `aisc-report-generator/report_renderer/templates/document.html.j2:12` draws the TOC as `<ol>`; `report.css`
   keeps the decimal list markers and `css/chapters.css:3` adds none. With `numbering=true` the PDF TOC reads
   "1. 1 Chiffres clés", "2. 2 Tests", nested "1. 2.1 Résultats des tests", "4. Annexe", "5. A Réponses aux
   contrôles" (seen on page 1 of the e2e PDF). The appendix heading gets a number, against R-V5.6. It hits every
   layout made from the built-in presets eu-ai-act and internal-audit (numbering on). The tests check the entry text
   only. Fix: `#toc ol { list-style: none }` when numbering is on (a feature CSS, so the goldens stay identical).
2. **should fix**: in a French report the tool tiles of Key figures keep English numbers and words.
   `aisc-report-langbite/vera_report_plugin_langbite/renderer.py:72,76`, `aisc-report-strongreject/.../renderer.py:71,75,80`,
   `aisc-report-promptfoo/.../renderer.py:64` format headline values with `format_number(None, ...)` /
   `format_percent(None, ...)` and `f"{a} of {b}"`, because `headline(run)` gets no context (R-V2.7), and
   `report_renderer/blocks/key_figures.py:150` passes the value through untranslated. Result on page 2 of the e2e
   PDF and in the DOCX: "0.2", "0.8", "68.8%", "85%", "1 of 4" next to "score moyen 4,0". This breaks R-V8.7.
   The static msgid scan (R-V8.4) cannot see these texts. Fix: return raw numbers with a kind from `headline()`
   and format them in key_figures with the report's `t`, separator and percent format (or pass a context).
3. **should fix** (security, low): CSS injection through the template's header or footer text.
   `aisc-report-generator/report_renderer/document.py:96-98` does not escape form feed (and other control
   characters), and `aisc-install/apps/report-composer/report_composer/templates.py:48-52` accepts any string up to
   120 characters. Verified: header text `"x\f}} p { display: none } @page { @top-left {"` makes every paragraph of
   the PDF body disappear. A project editor, or anyone whose template file is imported, can restyle or hide parts
   of generated reports (for example the marking or the document id and fingerprint line). External fetches stay
   blocked by the renderer's data:-only url_fetcher. Fix: escape every character below U+0020 (and U+2028/2029) as
   a CSS hex escape in `_css_string`, and refuse control characters in the composer.
4. **should fix** (privacy): a saved preset keeps chapter intros. `apps/report-composer/report_composer/presets.py:172-176`
   (`from_layout`) replaces only `free_text.text` and `commentary` when `keep_text` is false. The `chapter.intro`
   option added in this run is also project text, and saved presets are visible to every signed-in user of the
   platform (Q2 default). Scenario: an editor saves an audit layout as a preset without "Keep texts"; the chapter
   intro "Findings for Bank X show ..." is visible to users of every other project and in the exported file.
   R-V1.9 does not name `intro`; a spec gap. Fix: treat `chapter.intro` like `free_text.text`.
5. **note**: the draft preview can stall. `composer.js:318-321`: when `fetch` rejects (network drop, composer
   restart), `inFlight` stays true, so every later change only sets `queued` and the preview never refreshes
   until the page is reloaded; no error label is shown (R-U3.5 covers answered errors only). Fix: try/finally
   around the call.
6. **note**: chapter indentation and the "This chapter is empty." hint are computed only when the page is drawn
   (`editor.html.j2` `data-depth`, R-V5.9). After adding or moving blocks in the editor they are stale until
   reload. Cosmetic.
7. **note**: `POST /api/presets/import` (`api.py:405-412`, `presets.py:from_file`) stores the file's blocks with
   their reference values (evaluation pids, chart ids of another platform) and any `language` string. They are
   reset when a layout is made from the preset (R-V1.4, language falls back to en), but the saved preset and its
   export still carry foreign ids, against BRIEF V1 ("no project-specific references").
8. **note**: a report generated straight from a built-in preset prints the placeholder "Write this section."
   (seen in the composer e2e PDF). By spec (R-V1.1), but a user can generate without noticing; consider a
   problem or notice on free text that still holds the placeholder.
9. **note**: built-in presets carry English texts (chapter titles "System and risks", "Evidence", cover title).
   A French layout from a preset shows them in English (seen in the composer e2e). By spec (option texts are
   data), worth telling the user.
10. **note**: pre-existing test-helper defects still hide 13 tests per run (`throwaway.py:69` row footer,
    `client.get(json=...)` in generator test_service.py:28 and composer test_api_access.py). This stage showed with
    in-memory fixes that they pass; fixing the helpers would make the suites green without this manual step.
11. **note**: `test_v2_pages.py::test_r_u1_1_python_computes_the_grid_and_js_only_collects` only checks that
    "coverage" occurs in composer.js; the other U1 tests and my reading of the script carry the requirement.
12. **note**: the golden `a_v2_live_styled.pdf.json` is captured but compared by no test (PDF text of a version
    with evaluations).
13. **note** (spec, for the user): French wording "1 objectifs sur 4 avec éléments probants" (no plural
    handling in the catalogue format); Q9 already asks the user to review fr.json.

## Questions for the user

None new. The questions of 01-specs.md section 20, Q2-1, Q3-1, Q3-2 and Q4-1 remain open with their defaults.
