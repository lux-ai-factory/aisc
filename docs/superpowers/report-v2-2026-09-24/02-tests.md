# Stage 2: Tests first for report run v2

Status: stage 2 of 5, done. Inputs: RULES.md, BRIEF.md, 00-baseline.md, 01-specs.md. Every requirement id of
01-specs.md (179 ids) is mapped to at least one test (section 4). No implementation code was written. Every new
test fails in its own body for a missing feature (`missing feature: ...` from a `need()`-style helper, a new option
refused by today's schema, or an assertion on today's output). The few tests that pass today are compatibility
guards and are justified one by one. There are no collection or setup errors.

## 1. Baseline, re-measured before any test was written (2026-09-24, throwaway beds only)

`env | grep -iE 'DATABASE|DSN|DB_URL'` printed nothing. Every database run used `aisc-t-*` postgres:14-alpine
containers made by `scripts/lib/report_bed.py`; none were left behind. The live stack was only read (the live
layout's options and template look, to build the goldens).

| suite | command dir | result | pre-existing failures |
|---|---|---|---|
| aisc-report-plugin-interface (dev 631b62b) | repo | 45 passed | none |
| aisc-report-mlareject (dev 2dd5649) | repo | 19 passed | none |
| aisc-report-generator (dev 26e235d) | repo | 237 passed, 2 failed (239) | test_block_ai_card.py::test_r2_2_2_tags (contradicts the spec), test_service.py::test_r5_4_1_no_token_no_answer[get-/v1/block-types] (`client.get(json={})` TypeError) |
| apps/report-composer (aisc-install 9edb1e2) | apps/report-composer | 134 passed, 8 failed (142) | test_api_access.py::test_r4_4_3_a_stranger_gets_404 [4 GET routes] (`get(json=None)`), test_api_reports.py::test_r4_2_5_generate_stores_the_snapshot_and_the_pdf, ::test_r3_12_the_snapshot_survives_edits, ::test_r4_3_5_the_renderer_failing_is_502_and_failed, ::test_r7_2_5_a_pdf_over_25_mb_is_not_stored (all `Throwaway.rows()` footer parsing) |
| scripts/tests/test_report_stack.py + test_report_grants.py | aisc-install | 75 passed, 7 failed (82) | test_report_stack.py::test_d6_guard_init_files_do_not_mention_report_roles, ::test_r4_1_2_launcher_card_seven (homepage now shows 6), ::test_final_guard_frozen_passes (guard FAILs as in 00-baseline); test_report_grants.py::test_d6a_report_ro_logs_in_read_only, ::test_r6_5_report_ro_never_reads_the_catalogue, ::test_d13_composer_role_owns_its_schema, ::test_d13_composer_role_search_path (`rows()` defect) |

The counts differ from 00-baseline.md (218/220, 99/107) because the generator and composer gained tests after the
previous run (style/template work, 26e235d and 6876d82). The failing names are the known defects of
../report-2026-09-23/05-report.md section 2 (F1, F2, F3, F5) plus three stack checks that follow other people's
working-tree changes (guard, launcher card count, init file text). After adding the new seed (section 3) the
generator and the grants suite were run again: identical results.

## 2. Totals after stage 2 (last run 2026-09-25)

| repo, branch | suite | total | new tests | new failing (feature missing) | new passing (justified) | old tests |
|---|---|---|---|---|---|---|
| aisc-report-plugin-interface, dev | tests/ | 121 | 76 | 72 | 4 | 45 passed |
| aisc-report-langbite, dev (new local repo) | tests/ | 28 | 28 | 27 | 1 | - |
| aisc-report-strongreject, dev (new local repo) | tests/ | 23 | 23 | 22 | 1 | - |
| aisc-report-promptfoo, dev (new local repo) | tests/ | 21 | 21 | 20 | 1 | - |
| aisc-report-mlareject, dev | tests/ | 19 | 0 | 0 | 0 | 19 passed |
| aisc-report-generator, dev | tests/ | 503 | 264 | 235 | 29 | 237 passed, 2 known failures |
| aisc-install, feat/unified-modules | apps/report-composer/tests/ | 330 | 188 | 181 | 7 | 134 passed, 8 known failures |
| aisc-install | scripts/tests report suites | 82 | 0 | 0 | 0 | unchanged (75/7) |
| **all** | | | **600** | **557** | **43** | |

Passing new tests, and why they may pass now:
- Interface (4): R-C.5 x2 (an old block declaration and an old tool renderer keep working), R-V2.4 (ToolRun already
  freezes any mapping, pins the new keys), R-V2.8 (a contract-1 renderer ignoring tool_options). All are
  backwards-compatibility guards.
- Each tool package (1 each): the path source to ../aisc-report-plugin-interface, set in this stage so the tests run.
- Generator (29): the 11 golden compatibility tests (R-C.1, R-C.2, R-C.4, R-V5.7, R-V5.16); 12 pins of today's
  behaviour the spec keeps (v1 snapshot valid, full v2 snapshot valid as a pair to 15 failing negatives, toc auto,
  no numbering by default, "Contents", preview TOC without page numbers, default header/footer, no marking on the
  cover, no id line, plain free text, English default, R-V2.26 duplicate tool refused); 6 block guards (R-V2.9 x2
  artifact contents never shown and only name/size selected, R-V6.6 no severity on risk classification, R-U2.2
  legacy first-summary rule, R-U2.3 own links win and links stay in the schema).
- Composer (7): R-U5.5, R-U4.5, R-U6.1 (template of another project still refused), R-V3.16, R-V8.16, R-V5.16
  (old style keys unchanged), R-U3.3 (sandbox="" kept).

Manual (browser only, visible parts pinned statically): R-U3.4 debounce, single flight and stale answers; R-U3.5
inline error keeps the last iframe content; R-U7.3 Esc and focus order; R-V4.15 hidden fields not sent; R-U1.3 the
reset question flow; R-V3.13 disclosure toggling.

## 3. Fixtures created

- **Seed, shared by all database suites** (aisc-install/scripts/tests/fixtures/report/): `seed_tools.sql`,
  `seed_controls_mike.sql`, `seed_controls_delta.sql`, loaded by `scripts/lib/report_bed.py` after the old seeds
  (22 changed lines; new IDS `M`, `M_V1`, `M_V2`, `D`, `D_V1`, `EVAL_M_*`; SLUGS mike, delta).
  - Project **Mike** (member mia, owner), the Mijke tools with the exact measurement names, descriptions and units of
    the plugin sources (LangBiTe 0.1.1, StrongREJECT 0.1.0, promptfoo 0.1.0), observation tool strings
    `"{package}::{Class} (v{version})"`. Version 2 has five evaluations in time order: 1 StrongREJECT with no scores
    (all 0.0, "No score produced"...), 2 LangBiTe (4 groups, one "Not evaluated", plus the 3 summaries) and
    StrongREJECT (4 jailbreaks incl. none), 3 promptfoo with only latency/cost/tests, 4 promptfoo with all six,
    5 a Failed promptfoo with no measurement. Version 1 has a smaller LangBiTe + StrongREJECT run (changes_since).
    Control-objectives risks with severities 5, 3, 1, null and one unmapped risk; version 1 differs (R-1 severity 3,
    R3.1 removed, R-9 removed). Two checklists (one answered in both versions). Artifacts named like the real ones
    (`strongreject_per_prompt.csv`, `promptfoo_results.json`, `plugin_execution.log`) with the content
    HARMFULPROMPTCONTENT, which must never reach a report. Version-1-only data carries M1MARK.
  - Project **Delta**: one version with a card, an assessment and a checklist and no engine rows at all (the
    no-evaluation golden).
  - Deviation from 01-specs.md 22: the tool data sits on the new project Mike, not on Alpha v2, so no existing test's
    evaluation counts or orderings change (verified: identical baseline results with the new seed).
- **Compatibility goldens** (aisc-report-generator/tests/golden/, own commit 8611de9): captured from the renderer at
  26e235d before any change by `capture.py` (renders each case twice, asserts determinism; MANIFEST.json records the
  commit). Cases in `golden_cases.py`: the live layout (7 blocks, the exact live options) with and without the live
  template look ("inter", 10 pt, #000fdf, #ff007e) on Delta v1 (must stay identical, HTML and PDF text), Alpha v2
  and Mike v2 (only the Test results section may change), Alpha v2 with legacy links plus a second empty summary
  block (only that block may change), Delta v1 with plain free text, titles and a page break.
- **Tool package fixtures**: tests/fixtures.py in each new package, identical to the seed runs, each citing the plugin
  source file and line it copies. Interface: tests/fake_i18n_pkg (a package with i18n/fr.json), tests/v2_helpers.py.
- **Composer**: tests/v2_fakes.py (FakeRendererV2 with the v2 block type shapes and annotations, languages(),
  coverage_choices(), fingerprint in every mode, docx_base64 in docx mode). The migration test builds its own bed
  (0001-0004, old-shape rows, then the app's migrate runs 0005).
- **Dev dependency**: aisc-report-generator dev extra `python-docx>=1.1` (reading DOCX in tests), uv.lock updated.

## 4. Requirement to test

Repos: IF interface, LB/SR/PF the new tool packages, RG aisc-report-generator/tests, RC
aisc-install/apps/report-composer/tests. Status F failing as expected, P passing now (justified in section 2),
M manual. Every one of the 179 ids of 01-specs.md appears below (checked with a script). Untestable parts are
named in the rows and in section 7.

### 4.1 Interface and tool renderers
| requirement | tests (file::name) | repo | status |
|---|---|---|---|
| R-C.5 | test_v2_contracts::test_r_c_5_an_old_block_declaration_still_validates, ::test_r_c_5_an_old_tool_renderer_still_matches_and_renders | IF | P (compat guard) |
| R-V2.4 (IF part) | test_v2_contracts::test_r_v2_4_tool_run_carries_the_new_keys_read_only | IF | P (ToolRun freezes any mapping today; pins it) |
| R-V2.7 | test_v2_contracts::test_r_v2_7_tool_renderer_defaults, ::test_r_v2_7_a_renderer_may_declare_contract_2_and_charts; LB/SR/PF test_tool_renderer::test_r_v2_1{0,6}/20_declaration (contract_version 2, chart_ids) | IF, LB, SR, PF | F |
| R-V2.8 | test_v2_contracts::test_r_v2_8_a_contract_1_renderer_ignoring_tool_options_works (P, compat); LB test_tool_renderer::test_r_v2_8_a_context_without_tool_options_still_renders, ::test_r_v2_15_*, ::test_r_v4_13_no_chart_when_show_charts_is_off | IF, LB | P / F |
| R-V2.9 | LB/SR/PF test_tool_renderer::test_r_v2_9_artifact_contents_are_never_printed | LB, SR, PF | F |
| R-V2.10 | LB test_tool_renderer::test_r_v2_10_declaration, ::test_r_v2_10_matches_the_live_plugin_row_only; LB test_packaging::test_r_v2_10_entry_point_in_the_tools_group, ::test_r_v2_10_the_installed_distribution_advertises_a_tool_renderer | LB | F |
| R-V2.11 | LB test_tool_renderer::test_r_v2_11_summary_line, ::test_r_v2_11_failed_run_says_why, ::test_r_v2_11_group_table_columns, ::test_r_v2_11_group_rows_ordered_by_concern_model_language, ::test_r_v2_11_group_cells, ::test_r_v2_11_chart_of_pass_rate_by_concern | LB | F |
| R-V2.12 | LB test_tool_renderer::test_r_v2_12_verdict_is_none, ::test_r_v2_12_no_verdict_words_of_the_report | LB | F |
| R-V2.13 | LB test_tool_renderer::test_r_v2_13_unparsable_description_gives_n_a_and_score_pass_rate, ::test_r_v2_13_unknown_measurements_are_listed_never_dropped | LB | F |
| R-V2.14 | LB test_tool_renderer::test_r_v2_14_headline | LB | F |
| R-V2.15 | LB test_tool_renderer::test_r_v2_15_summary_detail_shows_line_and_chart_only | LB | F |
| R-V2.16 | SR test_tool_renderer::test_r_v2_16_declaration, ::test_r_v2_16_matches_the_live_plugin_row_only; SR test_packaging::test_r_v2_16_entry_point_*, ::test_r_v2_16_the_installed_distribution_* | SR | F |
| R-V2.17 | SR test_tool_renderer::test_r_v2_17_key_numbers_state_their_direction, ::test_r_v2_17_jailbreak_table, ::test_r_v2_17_chart_of_harmfulness_by_jailbreak, ::test_r_v2_17_chart_spec_has_a_fixed_0_to_1_axis | SR | F |
| R-V2.18 | SR test_tool_renderer::test_r_v2_18_a_failed_run_is_not_scored, ::test_r_v2_18_not_scored_values_are_excluded_from_charts_and_headline, ::test_r_v2_18_one_not_scored_summary_leaves_the_others, ::test_r_v2_18_success_text_is_compared_after_trimming | SR | F |
| R-V2.19 | SR test_tool_renderer::test_r_v2_19_headline_when_scored, ::test_r_v2_19_verdict_is_none_and_no_colour_bands | SR | F |
| R-V2.20 | PF test_tool_renderer::test_r_v2_20_declaration, ::test_r_v2_20_matches_its_plugin_row_only; PF test_packaging::test_r_v2_20_entry_point_*, ::test_r_v2_20_the_installed_distribution_* | PF | F |
| R-V2.21 | PF test_tool_renderer::test_r_v2_21_table_of_the_six_measurements, ::test_r_v2_21_direction_words_come_from_the_unit, ::test_r_v2_21_refusal_rate_note, ::test_r_v2_21_absent_rates_are_not_reported, ::test_r_v2_21_chart_of_the_rates_present | PF | F |
| R-V2.22 | PF test_tool_renderer::test_r_v2_22_a_run_without_measurements | PF | F |
| R-V2.23 | PF test_tool_renderer::test_r_v2_23_headline, ::test_r_v2_23_verdict_is_none | PF | F |
| R-V2.24 | LB/SR/PF test_packaging::test_r_v2_24_imports_cleanly_prints_nothing_no_database, ::test_r_v2_24_no_database_dependency, ::test_r_v2_24_templates_and_catalogues_ship_with_the_package (F); ::test_r_v2_24_the_interface_comes_from_the_local_path (P, set in stage 2 so tests run) | LB, SR, PF | F / P |
| R-V3.1 | test_v2_richtext::test_r_v3_1_render_returns_markup, ::test_r_v3_1_bare_urls_are_not_linked | IF | F |
| R-V3.2 | test_v2_richtext::test_r_v3_2_mailto_link_is_allowed, ::test_r_v3_2_ftp_link_is_not_a_link, ::test_r_v3_2_code_and_blockquote_are_allowed, ::test_r_v3_2_output_tags_are_within_the_allowlist, ::test_r_v3_2_no_attribute_but_href_and_rel | IF | F |
| R-V3.3 | test_v2_richtext::test_r_v3_3_bold, _italic[*it*,_it_], _bullet_list, _numbered_list, _pipe_table, _link_with_rel, _script_is_literal_text, _bold_tag_is_literal_text, _dangerous_link_gives_text_without_link[javascript,data], _heading_becomes_a_paragraph, _image_gives_its_alt_text_only, _single_newline_is_a_line_break, _blank_line_starts_a_new_paragraph | IF | F |
| R-V3.4 | test_v2_richtext::test_r_v3_4_fuzz_never_raises, ::test_r_v3_4_deep_nesting_never_raises; test_v2_contracts::test_r_v3_6_commentary_limits_are_checked (10000) | IF | F |
| R-V3.6 | test_v2_contracts::test_r_v3_6_common_properties_gain_commentary, ::test_r_v3_6_every_block_accepts_commentary_through_the_full_schema, ::test_r_v3_6_commentary_limits_are_checked | IF | F |
| R-V3.12 | test_v2_contracts::test_r_v3_12_new_instance_options_default_empty | IF | F |
| R-V4.1 | test_v2_charts::test_r_v4_1_same_spec_same_bytes, ::test_r_v4_1_no_io | IF | F |
| R-V4.2 | test_v2_charts::test_r_v4_2_bars_use_primary_only, ::test_r_v4_2_other_colours_follow_the_argument | IF | F |
| R-V4.3 | test_v2_charts::test_r_v4_3_percent_values_print_as_0_to_100, ::test_r_v4_3_number_format_prints_plain_numbers, ::test_r_v4_3_null_value_draws_no_bar_and_says_n_a, ::test_r_v4_3_note_is_optional | IF | F |
| R-V4.4 | test_v2_charts::test_r_v4_4_accessible_svg_with_title, ::test_r_v4_4_explicit_size_at_most_160mm, ::test_r_v4_4_value_labels_at_the_bars, ::test_r_v4_4_labels_are_escaped, ::test_r_v4_4_long_labels_are_cut_to_39_plus_dots | IF | F |
| R-V4.5 | test_v2_charts::test_r_v4_5_invalid_specs_raise_value_error[3 cases], ::test_r_v4_5_sixty_items_are_fine | IF | F |
| R-V4.13 | LB test_tool_renderer::test_r_v4_13_no_chart_when_show_charts_is_off, ::test_r_v4_13_charts_returns_the_spec_drawn, ::test_r_v4_13_chart_is_drawn_with_charts_svg; SR ::test_r_v4_13_no_chart_when_show_charts_is_off; PF ::test_r_v4_13_no_chart_when_show_charts_is_off_or_no_rate | LB, SR, PF | F |
| R-V8.2, R-V8.3 (loader format, interface part) | test_v2_i18n::test_r_v8_2_* (4 + 5 params), ::test_r_v8_3_* (4) | IF | F |
| R-V8.4 (per package) | LB/SR/PF test_packaging::test_r_v8_4_every_msgid_has_a_french_entry | LB, SR, PF | F |
| R-V8.8 | test_v2_i18n::test_r_v8_8_package_catalogue_is_found, ::test_r_v8_8_package_first_then_renderer, ::test_r_v8_8_no_catalogue_for_the_language_means_english; LB/SR/PF test_tool_renderer::test_r_v8_8_french_uses_the_package_catalogue. BlockContext.language/.t/.translate_for live in the renderer (fork 2) | IF, LB, SR, PF | F |
| R-U5.1 (IF part) | test_v2_contracts::test_r_u5_1_common_properties_carry_title_and_description, ::test_r_u5_1_common_enum_values_carry_labels, ::test_r_u5_1_annotations_do_not_change_validation | IF | F |
| R-U5.4 (common row) | test_v2_contracts::test_r_u5_4_common_more_options | IF | F |
| R-U5.2 | test_v2_contracts::test_r_u5_2_description_default_empty | IF | F |
| R-S.4 | test_v2_contracts::test_r_s_4_interface_version_is_2, ::test_r_s_4_new_dependencies_are_declared, ::test_r_s_4_new_modules_exist[richtext,charts,i18n] | IF | F |
| R1.12 (escaping, new packages) | LB/SR test_tool_renderer::test_r1_12_values_are_escaped; PF ::test_r1_12_units_are_escaped | LB, SR, PF | F |

### 4.2 Renderer core (document, snapshot, languages, DOCX, service, compatibility)
| requirement | tests (file::name) | repo | status |
|---|---|---|---|
| R-C.1 | test_compat_golden::test_r_c_1_an_old_snapshot_without_evaluations_renders_byte_for_byte[3] | RG | P |
| R-C.2 | test_compat_golden::test_r_c_2_the_goldens_come_from_the_renderer_before_the_run; tests/golden/capture.py, golden_cases.py | RG | P |
| R-C.4 (1,2) | test_compat_golden::test_r_c_4_with_evaluations_only_the_test_results_section_may_change[3], ::test_r_c_4_the_mystery_tool_keeps_its_generic_table | RG | P |
| R-C.4 (3) | test_compat_golden::test_r_c_4_the_pdf_text_is_the_same_apart_from_toc_page_numbers[2]; test_document_structure::test_r_v5_2_* | RG | P/F |
| R-C.4 (4) | test_compat_golden::test_r_c_4_legacy_links_only_the_second_summary_block_may_change | RG | P |
| R-S.1 | test_snapshot_v2::test_r_s_1_* (v1 passes, full v2 passes, mode docx, 10 key validations, 4 style fields, 200 links) | RG | F (2 P) |
| R-S.2 | test_header_footer::test_r_s_2_every_mode_returns_the_fingerprint[preview,pdf]; test_docx::test_r_s_2_docx_mode_returns_the_document_and_its_hashes | RG | F |
| R-S.5 | test_service_v2::test_r_s_5_contract_1_and_2_load_a_higher_one_is_skipped, ::test_r_s_5_built_in_contract_versions | RG | F |
| R-S.6 | test_service_v2::test_r_s_6_new_dependencies | RG | F |
| R-S.7 | test_service_v2::test_r_s_7_new_routes_follow_the_token_rule[2], ::test_r_s_7_health_gains_interface_version_and_languages, ::test_r_s_7_block_types_gain_description_and_new_instance_options | RG | F |
| R-V2.25 | test_service_v2::test_r_v2_25_health_lists_the_three_tool_renderers, ::test_r_v2_25_the_dockerfile_installs_them_from_build_contexts; test_service_v2::test_r_s_6_new_dependencies | RG | F |
| R-V2.26 | test_service_v2::test_r_v2_26_two_contract_2_renderers_of_one_tool_refuse_to_start | RG | P |
| R-V3.5 | test_commentary::test_r_v3_5_links_are_clickable_in_the_pdf_and_printed_as_their_text; test_docx::test_r_v8_9_links_become_hyperlinks | RG | F |
| R-V3.6 (renderer side) | test_commentary::test_r_v3_7_empty_commentary_changes_nothing (option accepted on every block via common options) | RG | F |
| R-V3.7 | test_commentary::test_r_v3_7_commentary_after_the_block_by_default, ::test_r_v3_7_commentary_before_sits_between_notices_and_the_block, ::test_r_v3_7_empty_commentary_changes_nothing[2] | RG | F |
| R-V3.8 | test_commentary::test_r_v3_8_commentary_on_an_empty_block / _stale_block / _error_block | RG | F |
| R-V3.9 | test_commentary::test_r_v3_9_the_commentary_has_a_small_caption, ::test_r_v3_9_the_caption_is_translated | RG | F |
| R-V3.10 | test_document_structure::test_r_v3_10_chapter_and_appendix_accept_commentary[2] | RG | F |
| R-V3.11 | test_commentary::test_r_v3_11_free_text_without_format_is_plain_as_today (P), ::test_r_v3_11_free_text_format_plain_is_accepted, ::test_r_v3_11_free_text_format_markdown; test_compat_golden d_v1_free_text | RG | F/P |
| R-V3.12 | test_commentary::test_r_v3_12_block_types_return_new_instance_options | RG | F |
| R-V4.14 | test_service_v2::test_r_v4_14_dashboard_chart_points_to_the_chart_block | RG | F |
| R-V5.1 | test_document_structure::test_r_v5_1_toc_auto_is_todays_rule (P), ::test_r_v5_1_toc_on_shows_it_for_two_blocks, ::test_r_v5_1_toc_off_never_shows_it, ::test_r_v5_1_toc_on_is_placed_after_the_cover | RG | F/P |
| R-V5.2 | test_document_structure::test_r_v5_2_pdf_toc_entries_end_with_the_page_number, ::test_r_v5_2_the_preview_toc_has_no_page_numbers (P) | RG | F/P |
| R-V5.3 | test_document_structure::test_r_v5_3_toc_lists_chapters_with_their_blocks_nested; test_r_v5_6_numbering_with_chapters_and_appendix (TOC numbers) | RG | F |
| R-V5.4 | test_document_structure::test_r_v5_4_the_toc_heading_is_contents (P); test_i18n::test_r_v8_7_fixed_texts_are_french_data_is_not (translated) | RG | P/F |
| R-V5.5 | test_document_structure::test_r_v5_5_chapter_and_appendix_are_built_in, ::test_r_v5_5_a_chapter_renders_its_heading_and_intro, ::test_r_v5_5_the_appendix_heading_and_its_title_override, ::test_r_v5_5_the_appendix_starts_a_new_page, ::test_r_v5_5_two_appendices_are_refused | RG | F |
| R-V5.6 | test_document_structure::test_r_v5_6_simple_numbering, ::test_r_v5_6_numbering_with_chapters_and_appendix, ::test_r_v5_6_no_numbering_by_default (P) | RG | F/P |
| R-V5.7 | test_compat_golden::test_r_c_1_* (no chapters, numbering off, toc auto = today) | RG | P |
| R-V5.11 | test_header_footer::test_r_v5_11_header_footer_and_marking_are_placed_in_the_margins, ::test_r_v5_11_the_pdf_shows_them_on_every_page | RG | F |
| R-V5.12 | test_header_footer::test_r_v5_12_placeholders_are_filled_and_unknown_ones_kept, ::test_r_v5_12_the_text_is_escaped_for_a_css_string | RG | F |
| R-V5.13 | test_header_footer::test_r_v5_13_marking_labels[4], ::test_r_v5_13_the_marking_is_printed_on_the_cover_under_the_title, ::test_r_v5_13_no_marking_none_on_the_cover (P) | RG | F/P |
| R-V5.14 | test_header_footer::test_r_v5_14_the_document_id_line_in_a_pdf, ::test_r_v5_14_the_preview_says_it_is_not_a_document, ::test_r_v5_14_no_id_line_when_off (P) | RG | F/P |
| R-V5.15 | test_header_footer::test_r_v5_15_the_fingerprint_is_the_sha256_of_the_canonical_snapshot, ::test_r_v5_15_mode_requester_and_document_do_not_change_it_content_does | RG | F |
| R-V5.16 | test_header_footer::test_r_v5_16_defaults_keep_todays_header_and_footer; test_compat_golden styled cases | RG | P |
| R-V8.1 | test_i18n::test_r_v8_1_english_stays_the_default (P); test_e2e_v2 (language fr) | RG | P/F |
| R-V8.2 | test_i18n::test_r_v8_2_en_and_fr_catalogues_have_the_format, ::test_r_v8_2_a_bad_file_name_in_the_path_is_ignored | RG | F |
| R-V8.3 | test_i18n::test_r_v8_3_t_fills_placeholders_and_never_raises, ::test_r_v8_3_t_in_french | RG | F |
| R-V8.4 | test_i18n::test_r_v8_4_every_msgid_has_a_french_entry (static scan), ::test_r_v8_4_the_core_texts_are_translated | RG | F |
| R-V8.5 | test_i18n::test_r_v8_5_languages_route_lists_english_first; test_snapshot_v2::test_r_v8_5_an_unknown_language_is_invalid_snapshot_at_language | RG | F |
| R-V8.6 | test_i18n::test_r_v8_6_a_catalogue_in_report_i18n_path_adds_a_language | RG | F |
| R-V8.7 | test_i18n::test_r_v8_7_fixed_texts_are_french_data_is_not, ::test_r_v8_7_dates_stay_iso_numbers_use_the_decimal_comma, ::test_r_v8_7_page_x_of_y_is_translated_in_the_pdf_css | RG | F |
| R-V8.8 (renderer side) | test_i18n::test_r_v8_3_* (BlockContext.language, .t) | RG | F |
| R-V8.9 | test_docx::test_r_v8_9_* (9: headings, runs, hyperlinks, lists, table header, charts, page break, commentary shading, no text lost); test_snapshot_v2::test_r_s_1_mode_docx_is_accepted | RG | F |
| R-V8.10 | test_docx::test_r_v8_10_header_and_footer_carry_the_pdf_texts_and_page_fields, ::test_r_v8_10_the_toc_is_a_word_field_updated_on_open, ::test_r_v8_10_fonts_follow_the_template | RG | F |
| R-V8.11 | test_docx::test_r_v8_11_document_properties | RG | F |
| R-V8.12 | not in the renderer: the 25 MB check and "was not stored" happen where the document is stored (composer, R7.2.5). Left to the composer fork (DOCX over 25 MB). | RC | - |
| R-U5.1 | test_service_v2::test_r_u5_1_every_property_has_a_title_a_description_and_enum_labels[14 block types] | RG | F |
| R-U5.2 (renderer route) | test_service_v2::test_r_s_7_block_types_gain_description_and_new_instance_options | RG | F |
| R-U5.4 (renderer part) | test_service_v2::test_r_u5_4_main_and_more_options_split[14 block types] | RG | F |
| E2E (renderer) | test_e2e_v2::test_e2e_v2_preview_pdf_and_docx (Mike v2, fr, numbering, chapters, appendix, commentary, key_figures, chart, changes_since; preview + pdf + docx, one fingerprint) | RG | F |

### 4.3 Renderer blocks and data
| requirement | tests (file::name) | repo | status |
|---|---|---|---|
| R-V2.1 | test_v2_test_results::test_r_v2_1_evaluations_are_named_by_number_and_tools, ::test_r_v2_1_the_number_does_not_depend_on_the_filters, ::test_r_v2_1_more_than_three_tools_and_no_run | RG | F |
| R-V2.2 | test_v2_test_results::test_r_v2_2_meta_line_with_time_and_reference | RG | F |
| R-V2.3 | test_v2_test_results::test_r_v2_3_evaluation_choices_are_labelled_by_name | RG | F |
| R-V2.4 (RG) | test_v2_test_results::test_r_v2_4_measurements_carry_description_and_error, ::test_r_v2_4_tool_run_has_name_number_and_measurement_descriptions | RG | F |
| R-V2.5 | test_v2_test_results::test_r_v2_5_only_selected_metrics_reach_the_tool_renderer, ::test_r_v2_5_only_selected_metrics_in_the_generic_table, ::test_r_v2_5_metric_choices, ::test_r_v2_5_metrics_default_all_is_today; test_blocks_v2_contracts::test_r_v2_5_test_results_new_defaults | RG | F |
| R-V2.6 | test_v2_test_results::test_r_v2_6_a_run_left_without_metrics_is_still_listed | RG | F |
| R-V2.8 (RG) | test_v2_test_results::test_r_v2_8_tool_options_defaults, ::test_r_v2_8_tool_options_from_the_block; test_blocks_v2_contracts::test_r_v2_8_detail_values | RG | F |
| R-V2.9 | test_v2_test_results::test_r_v2_9_artifact_contents_never_reach_the_report, ::test_r_v2_9_the_artifact_query_selects_name_and_size_only | RG | P (guard) |
| R-C.4 items 1, 2 | test_v2_test_results::test_r_c_4_the_mijke_tools_have_dedicated_renderers, ::test_r_c_4_an_unknown_tool_keeps_the_generic_table | RG | F |
| R-V4.6 | test_v2_chart_block::test_r_v4_6_declaration_and_defaults, ::test_r_v4_6_max_bars_range[2,41], ::test_r_v4_6_choices, ::test_r_v4_6_tool_chart_choices | RG | F |
| R-V4.7 | test_v2_chart_block::test_r_v4_7_coverage_status_from_the_layout_map, ::test_r_v4_7_checklist_scores, ::test_r_v4_7_metric_by_evaluation, ::test_r_v4_7_metric_by_dimension, ::test_r_v4_7_tool_chart_latest_run, ::test_r_v4_7_tool_chart_each_run | RG | F |
| R-V4.8 | test_v2_chart_block::test_r_v4_8_no_scored_checklist_answers, ::test_r_v4_8_coverage_status_without_an_assessment, ::test_r_v4_8_a_tool_chart_nobody_offers | RG | F |
| R-V4.9 | test_v2_chart_block::test_r_v4_9_auto_orientation, ::test_r_v4_9_forced_orientation | RG | F |
| R-V4.10 | test_v2_chart_block::test_r_v4_10_more_bars_than_max | RG | F |
| R-V4.11 | test_v2_chart_block::test_r_v4_7_coverage_status_from_the_layout_map (table rows), ::test_r_v4_11_table_can_be_hidden | RG | F |
| R-V4.12 | test_v2_chart_block::test_r_v4_12_stale_as_the_block_reading_the_source[4 cases] | RG | F |
| R-V4.16 | test_v2_chart_block::test_r_v4_16_the_chosen_dataset_requires_its_option[4 cases], ::test_r_v4_16_coverage_status_needs_nothing_else | RG | F |
| R-V6.1 | test_v2_filters::test_r_v6_1_new_options_default_to_everything, ::test_r_v6_1_defaults_render_as_today, ::test_r_v6_1_requirement_choices_in_catalogue_order, ::test_r_v6_1_objective_choices_of_the_version | RG | F |
| R-V6.2 | test_v2_filters::test_r_v6_2_requirement_group_filter, ::test_r_v6_2_objective_filter, ::test_r_v6_2_min_severity_keeps_unrated_by_default, ::test_r_v6_2_min_severity_without_unrated, ::test_r_v6_2_group_by_risk_with_severity, ::test_r_v6_2_group_by_risk_with_an_objective_filter_hides_unmapped_risks, ::test_r_v6_2_all_filters_combine, ::test_r_v6_2_severity_out_of_range_is_invalid | RG | F |
| R-V6.3 | test_v2_filters::test_r_v6_3_show_severity | RG | F |
| R-V6.4 | test_v2_filters::test_r_v6_4_a_filter_adds_the_filtered_notice, ::test_r_v6_4_filters_that_hide_everything | RG | F |
| R-V6.5 | test_v2_filters::test_r_v6_5_summary_counts_only_the_shown_objectives, ::test_r_v6_5_summary_requirements_default_all | RG | F |
| R-V6.6 | test_v2_filters::test_r_v6_6_risk_classification_has_no_severity_option | RG | P (decision guard) |
| R-V6.7 | covered by the R-V2.5 tests | RG | F |
| R-V6.8 | test_v2_key_figures::test_r_v6_8_declaration, ::test_r_v6_8_unknown_figure_is_invalid | RG | F |
| R-V6.9 | test_v2_key_figures::test_r_v6_9_tiles_in_order, ::test_r_v6_9_version_tile, ::test_r_v6_9_risks_tile, ::test_r_v6_9_objectives_tile, ::test_r_v6_9_coverage_tile_reads_the_layout_map, ::test_r_v6_9_tests_tile, ::test_r_v6_9_tool_headline_tiles, ::test_r_v6_9_checklists_tile | RG | F |
| R-V6.10 | test_v2_key_figures::test_r_v6_10_a_figure_without_data_is_na, ::test_r_v6_10_empty_only_when_every_figure_is_na (source-error "n/a (ref ...)" case not tested: no fault injection in the seed) | RG | F |
| R-V6.11 | test_v2_key_figures::test_r_v6_11_stale_when_a_source_is_newer | RG | F |
| R-V7.1 | test_v2_changes_since::test_r_v7_1_declaration | RG | F |
| R-V7.2 | test_v2_changes_since::test_r_v7_2_options_and_defaults, ::test_r_v7_2_compare_to_choices, ::test_r_v7_2_previous_is_the_version_below (gaps in numbers: not in the seed) | RG | F |
| R-V7.3 | test_v2_changes_since::test_r_v7_3_for_version_returns_scoped_data_of_the_earlier_version, ::test_r_v7_3_for_version_refuses_other_projects_and_later_versions[A_V1,M_V2], ::test_r_v7_3_a_bad_base_version_is_an_error_box[2 cases] | RG | F |
| R-V7.4 | test_v2_changes_since::test_r_v7_4_no_earlier_version[M_V1, D_V1] | RG | F |
| R-V7.5 | test_v2_changes_since::test_r_v7_5_card_changes (300-character cut not tested: no long text in the seed) | RG | F |
| R-V7.6 | test_v2_changes_since::test_r_v7_6_objectives_and_risks_added_and_removed, ::test_r_v7_6_severity_change_3_to_5, ::test_r_v7_6_coverage_status_change_with_the_same_map | RG | F |
| R-V7.7 | test_v2_changes_since::test_r_v7_7_tests_per_tool_and_metric, ::test_r_v7_7_done_evaluation_counts (200-row cap not tested) | RG | F |
| R-V7.8 | test_v2_changes_since::test_r_v7_8_controls_per_checklist | RG | F |
| R-V7.9 | test_v2_changes_since::test_r_v7_9_show_unchanged, ::test_r_v7_5_card_changes (unchanged left out), ::test_r_v7_9_version_one_data_is_allowed_only_in_this_block. "No change." and the all-unchanged sentence: untested, the seed has no pair of versions with an unchanged part | RG | F / partly untested |
| R-V7.10 | test_v2_changes_since::test_r_v7_10_first_line_and_never_stale | RG | F |
| R-U2.2 | test_v2_coverage_map::test_r_u2_2_control_objectives_read_the_snapshot_map, ::test_r_u2_2_the_snapshot_map_wins_over_the_first_summary, ::test_r_u2_2_summary_with_empty_links_reads_the_snapshot_map (F); ::test_r_u2_2_an_old_snapshot_keeps_the_first_summary_rule (P, compat); consumers: test_v2_key_figures::test_r_v6_9_coverage_tile_reads_the_layout_map, test_v2_chart_block::test_r_v4_7_coverage_status_from_the_layout_map, test_v2_changes_since::test_r_v7_6_coverage_status_change_with_the_same_map | RG | F / P |
| R-U2.3, R-C.4 item 4 | test_v2_coverage_map::test_r_u2_3_a_later_summary_with_empty_links_uses_the_layout_map_in_an_old_snapshot (F); ::test_r_u2_3_own_links_win, ::test_r_u2_3_links_option_stays_in_the_schema (P, legacy guard) | RG | F / P |
| R-U2.7 | test_v2_coverage_map::test_r_u2_7_coverage_choices_shape, ::test_r_u2_7_scoped_to_the_version, ::test_r_u2_7_a_version_of_another_project_is_404, ::test_r_u2_7_needs_the_token | RG | F |
| R-V1.4 (RG side) | test_blocks_v2_contracts::test_r_v1_4_reference_options_are_marked[4], ::test_r_v1_4_structural_options_are_not_references[4] | RG | F |
| R-S.5 | not here: pinned by fork 2a in test_service_v2.py (test_r_s_5_*) | RG | - |

### 4.4 Composer
| requirement | tests (file::name) | repo | status |
|---|---|---|---|
| R-C.3 | test_v2_migration::test_r_c_3_an_old_layout_previews_with_the_same_snapshot_apart_from_new_keys, ::test_r_c_3_templates_keep_their_look, ::test_r_c_3_stored_reports_download_unchanged | RC | F |
| R-C.6 | test_v2_layout_settings::test_r_c_6_new_fields_default_to_todays_behaviour; test_v2_templates::test_r_c_6_template_fields_default_to_todays_behaviour; test_v2_reports::test_r_v8_14_absent_format_is_pdf | RC | F |
| R-V1.1 | test_v2_presets::test_r_v1_1_built_in_preset_files_hold_the_block_sequence[x4], ::test_r_v1_1_built_in_preset_document_settings, ::test_r_v1_1_the_list_starts_with_the_four_built_ins_in_order | RC | F |
| R-V1.2 | test_v2_presets::test_r_v1_2_no_preset_and_no_blocks_is_the_full_assessment | RC | F |
| R-V1.3 | test_v2_presets::test_r_v1_3_a_layout_from_a_built_in_preset[x4], ::test_r_v1_3_new_instance_ids_every_time, ::test_r_v1_3_empty_preset_gives_no_blocks, ::test_r_v1_3_unknown_preset, ::test_r_v1_3_at_most_one_source_of_blocks[x3], ::test_r_v1_3_a_layout_from_a_preset_file_takes_its_name_from_the_file; test_e2e_v2 | RC | F |
| R-V1.4 | test_v2_presets::test_r_v1_4_references_are_reset_and_generate_is_refused | RC | F |
| R-V1.5 | test_v2_presets::test_r_v1_5_unknown_block_types_are_all_listed, ::test_r_v1_10_unknown_block_type_on_import | RC | F |
| R-V1.6 | test_v2_presets::test_r_v1_6_duplicate_names_copy_then_copy_2, ::test_r_v1_6_a_copy_keeps_everything_but_ids_revision_and_reports, ::test_r_v1_6_a_viewer_cannot_duplicate | RC | F |
| R-V1.7 | test_v2_presets::test_r_v1_7_export_is_a_preset_file | RC | F |
| R-V1.8 | test_v2_presets::test_r_v1_8_save_list_export_a_saved_preset, ::test_r_v1_8_keep_text_on_a_saved_preset, ::test_r_v1_8_a_viewer_cannot_save_a_preset, ::test_r_v1_8_delete_by_creator_or_admin_only, ::test_r_v1_8_built_in_presets_cannot_be_deleted, ::test_r_v1_8_import_a_preset_file_and_the_name_gets_a_suffix, ::test_r_v1_8_a_saved_preset_is_a_starting_point | RC | F |
| R-V1.9 | test_v2_presets::test_r_v1_9_texts_become_placeholders_unless_kept (+ keep_text test above) | RC | F |
| R-V1.10 | test_v2_presets::test_r_v1_10_not_a_preset[x3], ::test_r_v1_10_at_most_50_blocks, ::test_r_v1_10_invalid_options_name_the_block_index, ::test_r_v1_10_unknown_block_type_on_import, ::test_r_v1_10_a_preset_with_two_covers_is_refused | RC | F |
| R-V1.11 | test_v2_presets::test_r_v1_11_preset_names_are_1_to_120_characters[x2], ::test_r_v1_11_preset_names_are_unique_platform_wide | RC | F |
| R-V1.12 | test_v2_presets::test_r_v1_12_deleting_a_preset_does_not_change_the_layout | RC | F |
| V1 2.3/2.5 | test_v2_pages::test_r_v1_screens_start_from_select, ::test_r_v1_screens_row_menu_editor_and_viewer, ::test_r_v1_screens_presets_section; test_v2_presets::test_r_v1_edge_zero_block_preset_starts_empty_and_is_not_generated, ::test_r_v1_edge_a_language_no_longer_offered_falls_back_to_english_with_a_notice | RC | F |
| R-V3.13 | test_v2_pages::test_r_v3_13_commentary_disclosure_closed_when_empty_open_when_set; test_v2_forms_unit::test_r_v3_13_commentary_is_a_six_row_textarea_of_its_own | RC | F |
| R-V3.14 | test_v2_pages::test_r_v3_14_the_palette_adds_free_text_in_light_formatting | RC | F |
| R-V3.15 | test_v2_pages::test_r_v3_15_help_line_under_light_formatting_textareas | RC | F |
| R-V3.16 | test_v2_pages::test_r_v3_16_the_composer_never_interprets_markup | RC | P (guard) |
| R-V4.15 | test_v2_forms_unit::test_r_v4_15_show_if_is_passed_on_and_decides_hidden; test_v2_pages::test_r_v4_15_show_if_fields_are_drawn_hidden, ::test_r_v4_15_composer_js_toggles_from_the_annotation_and_skips_hidden_fields; "hidden fields not sent" in the browser | RC | F / M |
| R-V5.8 | test_v2_pages::test_r_v5_8_an_empty_chapter_is_a_hint_not_an_error | RC | F |
| R-V5.9 | test_v2_pages::test_r_v5_9_blocks_inside_a_chapter_are_indented | RC | F |
| R-V5.10 | test_v2_templates::test_r_v5_10_the_four_fields_are_saved_and_shown, ::test_r_v5_10_bad_fields_are_refused[x4], ::test_r_v5_10_the_five_markings[x5], ::test_r_v5_10_export_is_version_2_with_the_fields, ::test_r_v5_10_import_accepts_version_1_with_defaults, ::test_r_v5_10_import_accepts_version_2 | RC | F |
| R-V5.11 (composer side) | test_v2_reports::test_r_v5_11_the_style_carries_header_footer_marking_and_document_id | RC | F |
| R-V5.14 | test_v2_reports::test_r_v5_14_the_document_id_is_the_generated_report_id; test_v2_layout_settings::test_r_v5_14_the_preview_has_no_document_id; test_e2e_v2 | RC | F |
| R-V5.15 (composer side) | test_v2_reports::test_r_v5_15_the_fingerprint_is_stored, ::test_r_v5_15_the_editor_shows_the_fingerprint_next_to_the_sha256; test_e2e_v2 | RC | F |
| R-V5.16 (composer side) | test_v2_reports::test_r_v5_16_a_default_template_sends_the_old_look_and_default_fields | RC | P (guard) |
| R-V5.17 | test_v2_templates::test_r_v5_17_the_template_form_has_the_new_fields | RC | F |
| R-V6.12 | test_v2_forms_unit::test_r_v6_12_key_figures_are_labelled_checkboxes_all_ticked_by_default | RC | F |
| R-V7.11 | test_v2_layout_settings::test_r_v7_11_compare_to_no_longer_lower_is_invalid_and_resets_to_previous | RC | F |
| R-V8.1 | test_v2_layout_settings::test_r_v8_1_the_language_is_sent_in_the_preview_snapshot, ::test_r_d_3_*; test_e2e_v2 | RC | F |
| R-V8.12 (composer side) | test_v2_reports::test_r_v8_12_a_document_over_25_mb_is_not_stored | RC | F |
| R-V8.13 | test_v2_pages::test_r_v8_13_the_language_select | RC | F |
| R-V8.14 | test_v2_reports::test_r_v8_14_docx_is_asked_of_the_renderer, ::test_r_v8_14_absent_format_is_pdf, ::test_r_v8_14_an_unknown_format_is_refused; test_v2_pages::test_r_v8_14_two_generate_buttons | RC | F |
| R-V8.15 | test_v2_reports::test_r_v8_15_docx_is_stored_with_its_format_and_downloads_as_word, ::test_r_v8_15_the_old_pdf_route_answers_404_for_a_docx, ::test_r_v8_15_download_serves_a_pdf_too, ::test_r_v8_15_the_reports_list_shows_format_and_fingerprint, ::test_r_v8_15_the_editor_page_lists_the_format; test_e2e_v2 | RC | F |
| R-V8.16 | test_v2_pages::test_r_v8_16_the_composer_screens_stay_in_english | RC | P (guard) |
| R-U1.1 | test_v2_pages::test_r_u1_1_the_grid, ::test_r_u1_1_the_first_column_stays_visible, ::test_r_u1_1_python_computes_the_grid_and_js_only_collects | RC | F |
| R-U1.2 | test_v2_pages::test_r_u1_2_no_objectives_for_the_version, ::test_r_u1_2_no_tests_or_checklists_for_the_version | RC | F |
| R-U1.3 | test_v2_pages::test_r_u1_3_entries_not_available_for_the_version (the reset question itself: browser, M) | RC | F / M |
| R-U1.4 | test_v2_pages::test_r_u1_4_the_typed_links_textarea_is_gone | RC | F |
| R-U1.5 | test_v2_pages::test_r_u1_5_viewers_see_the_grid_read_only | RC | F |
| R-U2.1 | test_v2_layout_settings::test_r_u2_1_the_map_is_saved_and_returned, ::test_r_u2_1_map_shape_is_checked[x3], ::test_r_u2_1_coverage_links_are_always_in_new_snapshots | RC | F |
| R-U2.4 | test_v2_migration::test_r_u2_4_the_lowest_summary_links_become_the_layout_map, ::test_r_u2_4_a_layout_without_links_keeps_an_empty_map | RC | F |
| R-U2.5 | test_v2_layout_settings::test_r_u2_5_map_values_must_be_choices_of_the_version[x3], ::test_r_u2_5_reset_invalid_cleans_the_map; test_v2_draft_preview::test_r_u3_1_problems_are_returned_but_do_not_stop_the_preview | RC | F |
| R-U2.6 | test_v2_pages::test_r_u2_6_legacy_links_are_read_only_with_a_switch | RC | F |
| R-U2.7 (client) | test_v2_renderer_client_unit::test_r_u2_7_coverage_choices_is_post_v1_coverage_choices | RC | F |
| R-U3.1 | test_v2_draft_preview::test_r_u3_1_the_draft_is_rendered_and_nothing_is_stored, ::test_r_u3_1_problems_are_returned_but_do_not_stop_the_preview, ::test_r_u3_1_a_viewer_cannot_post_a_draft, ::test_r_u3_1_a_draft_needs_the_same_origin; test_e2e_v2 | RC | F |
| R-U3.2 | test_v2_draft_preview::test_r_u3_2_the_version_must_be_of_the_project, ::test_r_u3_2_the_template_must_be_of_the_project, ::test_r_u3_2_a_body_over_1_mb_is_413, ::test_r_u3_2_renderer_failures[x2] | RC | F |
| R-U3.3 | test_v2_draft_preview::test_r_u3_3_the_html_has_the_csp_meta_as_first_head_element (F), ::test_r_u3_3_the_iframe_keeps_an_empty_sandbox (P guard) | RC | F / P |
| R-U3.4 | test_v2_draft_preview::test_r_u3_4_composer_js_posts_drafts_with_a_1_5_s_pause, ::test_r_u3_4_refresh_button_and_auto_refresh_checkbox, ::test_r_u3_4_auto_refresh_is_remembered_in_local_storage_inside_try_catch; debounce timing, single flight, stale answers ignored: browser only | RC | F / M |
| R-U3.5 | test_v2_draft_preview::test_r_u3_5_preview_labels, ::test_r_u3_5_the_label_is_on_the_page; inline error label: browser | RC | F / M |
| R-U3.6 | test_v2_draft_preview::test_r_u3_6_viewers_keep_the_get_preview_and_generate_uses_the_saved_revision | RC | F |
| R-U4.1 | test_v2_pages::test_r_u4_1_no_select_multiple_on_any_page; test_v2_forms_unit::test_r_u4_1_no_multiselect_widget_is_left | RC | F |
| R-U4.2 | test_v2_pages::test_r_u4_2_all_or_list_radios_then_checkboxes; test_v2_forms_unit::test_r_u4_2_all_or_list_is_radios_and_checkboxes, ::test_r_u4_2_a_filter_box_above_10_choices | RC | F |
| R-U4.3 | test_v2_layout_settings::test_r_u4_3_an_empty_list_is_refused_with_pick_at_least_one; test_v2_pages::test_r_u4_3_a_stored_empty_list_shows_only_these_and_the_problem, ::test_r_u4_3_composer_js_says_pick_at_least_one | RC | F |
| R-U4.4 | test_v2_forms_unit::test_r_u4_4_a_plain_enum_list_is_a_checkbox_list, ::test_r_u4_4_statuses_and_sections_are_checkbox_lists | RC | F |
| R-U4.5 | test_v2_forms_unit::test_r_u4_5_single_choices_among_data_stay_selects | RC | P (guard) |
| R-U5.2 (palette) | test_v2_pages::test_r_u5_2_the_palette_shows_block_descriptions | RC | F |
| R-U5.3 | test_v2_forms_unit::test_r_u5_3_title_is_the_label_and_description_the_help, ::test_r_u5_3_enum_labels_come_from_the_schema; test_v2_pages::test_r_u5_3_help_lines_are_shown | RC | F |
| R-U5.4 (composer) | test_v2_forms_unit::test_r_u5_4_more_options_are_flagged, ::test_r_u5_4_more_fields_come_after_main_fields; test_v2_pages::test_r_u5_4_more_options_are_a_closed_disclosure_at_the_end | RC | F |
| R-U5.5 | test_v2_forms_unit::test_r_u5_5_a_plugin_block_without_annotations_keeps_generated_labels_all_main | RC | P (guard) |
| R-U6.1 | test_v2_layout_settings::test_r_u6_1_a_layout_is_saved_and_generated_without_a_template (F), ::test_r_u6_1_template_of_another_project_still_refused (P guard); test_e2e_v2 | RC | F / P |
| R-U6.2 | test_v2_pages::test_r_u6_2_template_select_starts_with_platform_default | RC | F |
| R-U6.3 | test_v2_pages::test_r_u6_3_create_is_never_disabled_for_lack_of_a_template | RC | F |
| R-U6.4 | test_v2_layout_settings::test_r_u6_4_a_deleted_template_leaves_a_layout_that_saves_and_generates; test_v2_pages::test_r_u6_4_a_deleted_template_shows_platform_default | RC | F |
| R-U7.1 | test_v2_pages::test_r_u7_1_no_alert_confirm_or_prompt_in_composer_js | RC | F |
| R-U7.2 | test_v2_pages::test_r_u7_2_every_page_has_one_message_region_first_in_main[x3] | RC | F |
| R-U7.3 | test_v2_pages::test_r_u7_3_one_confirm_dialog_cancel_first, ::test_r_u7_3_composer_js_uses_the_dialog; Esc and focus: browser | RC | F / M |
| R-U7.4 | test_v2_pages::test_r_u7_4_leaving_with_unsaved_changes_asks_the_browser | RC | F |
| R-D.1 | test_v2_migration::test_r_d_1_new_columns_with_their_defaults, ::test_r_d_1_checks_refuse_bad_values[x7], ::test_r_d_1_preset_names_are_unique | RC | F |
| R-D.2 (composer part) | test_v2_migration::test_r_d_2_0005_touches_only_report_composer | RC | F |
| R-D.3 | test_v2_layout_settings::test_r_d_3_post_and_put_accept_the_new_fields, ::test_r_d_3_absent_on_put_keeps_the_current_value, ::test_r_d_3_the_layouts_list_carries_the_language; test_v2_reports::test_r_v8_15_the_reports_list_shows_format_and_fingerprint; template fields: test_v2_templates | RC | F |
| R-D.4 | test_v2_layout_settings::test_r_d_4_bad_settings_are_refused[x4] | RC | F |
| R-S.3 | test_v2_layout_settings::test_r_s_3_the_stored_snapshot_is_version_2_with_the_new_keys; test_e2e_v2 | RC | F |
| R-S.7 (client) | test_v2_renderer_client_unit::test_r_s_7_languages_is_get_v1_languages | RC | F |
| E2E | test_e2e_v2::test_e2e_v2_preset_french_coverage_draft_pdf_and_docx (fails today at the first step: template_required) | RC | F |

## 5. How to run each suite (never the live DB)

Check first: `env | grep -iE 'DATABASE|DSN|DB_URL'` must print nothing (the bed also refuses a DSN pointing at
`:5432/` or outside it). Database suites start their own `aisc-t-<label>-<hex>` container on a kernel-chosen port and
remove it at the end. No `docker compose` command is run.

```
cd ~/aisc-report-plugin-interface && uv run --extra dev pytest -q
cd ~/aisc-report-langbite         && uv run --extra dev pytest -q
cd ~/aisc-report-strongreject     && uv run --extra dev pytest -q
cd ~/aisc-report-promptfoo        && uv run --extra dev pytest -q
cd ~/aisc-report-mlareject        && uv run --extra dev pytest -q
cd ~/aisc-report-generator        && uv run --extra dev pytest -q          # about 65 s, one bed; e2e: tests/test_e2e_v2.py
cd ~/aisc-install/apps/report-composer && uv run --extra dev pytest -q     # about 130 s; e2e with the real renderer: tests/test_e2e_v2.py
cd ~/aisc-install && uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider \
    scripts/tests/test_report_stack.py scripts/tests/test_report_grants.py
cd ~/aisc-install && scripts/guard-frozen.sh                             # must print the lines of 00-baseline.md
```

Goldens: never re-capture after stage 4 starts. `tests/golden/capture.py` is kept only to show how they were made.
A seed change would invalidate them; if a later stage must extend the seed, it re-captures from 26e235d in a
worktree (for example `git worktree add /tmp/g 26e235d`) and says so under Deviations.

End-to-end tests: the renderer's `tests/test_e2e_v2.py` (Mike v2 in French, numbering, chapters, appendix,
commentary, key figures, chart, changes_since, as preview, PDF and DOCX through report_service, one fingerprint) and
the composer's `tests/test_e2e_v2.py` (mia on project mike: layout from preset eu-ai-act, language fr, a coverage
map, draft preview, Generate PDF and Generate Word, both downloaded; PDF magic, `lang="fr"`, DOCX zip with
word/document.xml holding a section title, document id and fingerprint stored). The composer one starts the real
renderer with `uv run --extra dev uvicorn report_service:app` in the generator repo, as the previous run's e2e.

## 6. Commits (local, not pushed)

| repo | branch | commit |
|---|---|---|
| aisc-report-generator | dev | 8611de9 Compatibility goldens captured from the renderer at 26e235d before report run v2 changes anything |
| aisc-report-generator | dev | 29c54cc Tests first for report run v2: compatibility, snapshot v2, document structure, ... coverage map |
| aisc-report-plugin-interface | dev | 7d93a31 Tests first: light formatting, SVG charts, catalogue loader, commentary and help annotations on common options, tool renderer contract 2 |
| aisc-report-langbite (new, git init -b dev) | dev | f4af1d0 Tests first: the langbite tool renderer, its packaging and French catalogue |
| aisc-report-strongreject (new) | dev | 34cad23 Tests first: the strongreject tool renderer, ... |
| aisc-report-promptfoo (new) | dev | d7b8a4f Tests first: the promptfoo tool renderer, ... |
| aisc-install | feat/unified-modules | 1752778 Tests first for report run v2: composer ..., the report bed gains project Mike ... and project Delta |
| aisc-install | feat/unified-modules | (docs commit: this file and PROGRESS.md) |

aisc-report-mlareject is untouched. Only my own files were staged in aisc-install; other people's changes
(homepage/project.html, apps/qualification, the form-assembly docs, BRIEF/RULES/00-baseline of this folder) stay
unstaged. The new packages hold only pyproject.toml (setuptools, a package include that matches nothing yet),
uv.lock, .gitignore and tests; the entry point and package data are deliberately not declared (R-V2.10/16/20/24,
their tests fail until stage 4 adds them with the module).

## 7. Test API and markup the tests assume (stage 3 plans against it; changing a name means changing the test in a listed commit)

- Interface: `richtext.render(text) -> Markup`; `charts.svg(spec, colours) -> Markup` (ValueError on a bad spec);
  `i18n.load_catalogue(path)` (Catalogue with code, name, messages, decimal_separator, percent_format),
  `i18n.package_catalogue(package, code)`, `i18n.translator(*catalogues) -> t`; `INTERFACE_VERSION = 2`.
  Tool renderers get a ctx with `tool_options`, `language`, `t`, `translate_for(package)` and work when
  `tool_options` is absent; fixed texts go through `t("literal msgid")` (the French completeness scans read the AST
  and templates). headline items `{label, value, note?}`.
- Renderer: `context_for(..., language=...)`, `BlockContext.language`, `.t`; `ScopedData.for_version(pid)`;
  `REPORT_I18N_PATH` read when the service renders (not at import); header/footer as `@page` margin boxes
  (@top-left, @top-right, @bottom-left, @bottom-center, @bottom-right) through `_css_string`;
  `<div class="commentary">` with the caption; `<h1 class="chapter-title">`; key figure tiles `data-figure="<id>"`
  (tool tiles `data-figure="tool"`); charts in `<figure class="chart" data-kind="bar|hbar">` followed by a 2-column
  table; changes_since parts `data-changes="card|objectives|tests|controls"`; duplicate appendix is a 422 problem
  `duplicate_appendix` from POST /v1/render.
- Composer: renderer client `languages()` (GET /v1/languages), `coverage_choices(project_id, system_id)` (POST
  /v1/coverage-choices), `render()` returning `fingerprint` always and `docx_base64` in docx mode;
  `forms.form_fields` keys `help`, `more`, `show_if`, `hidden`, `filter`, widgets `all-or-list`, `checkboxes`,
  `commentary` (no `multiselect`); page hooks `details[data-coverage-map]` with checkboxes
  `data-objective/data-kind/data-value`, `select[data-control=language]`, `[data-control=generate-docx]`,
  `li[data-depth]`, `details[data-more]`, `details[data-commentary]`, `[data-show-if]` (JSON),
  `[data-preview-label]`, `[data-control=refresh-preview]`, `input[data-control=auto-refresh]`,
  `input[data-control=use-coverage-map]`, `[data-control=duplicate|export-structure|save-preset|import-preset|export-preset|delete-preset]`,
  `select[name=preset]` (last option value "empty", "Empty layout"), `div[data-message]`, `dialog[data-confirm]`,
  `data-confirm-text`; routes GET /api/p/{ref}/reports/{rid}/download and POST /api/p/{ref}/layouts/{id}/preview
  (JSON body). Full lists: docstrings of generator tests/v2_core_helpers.py, tests/v2_block_helpers.py and composer
  tests/v2_fakes.py.

## 8. Existing tests that the intended changes will break (stage 4 fixes each in its own commit and lists it)

None was edited in this stage.
- generator tests/test_registry.py::test_section_2_default_options (new defaults, e.g. free_text `format: "plain"`),
  ::test_r5_2_2_the_nine_blocks_are_built_in and the plugin-dir count near line 119 (five new built-ins).
- generator tests/test_block_test_results.py tests that expect "Evaluation {pid[:8]}" headings or the generic table
  for Alpha's LangBiTe runs (R-C.4 items 1, 2), and possibly test_d8_* once the LangBiTe renderer matches those runs
  (Alpha's `bias_rate` must then appear under "Other measurements", R-V2.13).
- composer tests/test_api_templates.py::test_a_layout_is_not_saved_without_a_template,
  ::test_saving_changes_the_template_and_needs_one, ::test_a_layout_without_a_template_is_not_generated (R-U6.1),
  ::test_a_template_exports_as_one_file_with_its_logo (export version 2, R-V5.10).
- composer tests/test_pages.py::test_r4_1_1_one_small_script (composer.js under 300 lines) and
  ::test_generate_answers_next_to_the_button_and_downloads_the_pdf (reads the handler for "/pdf").
- composer conftest.py FakeRenderer has no languages()/coverage_choices(): the composer must tolerate a renderer
  without them, or stage 4 adds them to the fake in a listed test commit.

## 9. Deviations

- DV2-1 Seed placement: the tool runs of 01-specs.md 22 live on the new project Mike (and the no-evaluation version
  on Delta), not on Alpha v2, so the existing tests and their counts stay valid.
- DV2-2 Compatibility goldens: the "version with no evaluations" is Delta v1 (Alpha has evaluations on every
  version). The "with evaluations" goldens compare everything outside the Test results section byte for byte; the
  PDF text comparison ignores only the TOC page numbers (R-C.4 item 3).
- DV2-3 R-V8.12 (25 MB limit) is tested in the composer, where the document is stored; the renderer has no store.
- DV2-4 R-V5.5 duplicate appendix: the spec names the code, not the layer; the renderer test expects a 422 problem
  from /v1/render; the composer save path is not separately tested.
- DV2-5 Not testable on the frozen seed (a seed change would invalidate the goldens): changes_since "No change." and
  the all-unchanged sentence (R-V7.9), the 200-row cap (R-V7.7), the 300-character cut (R-V7.5), gaps in version
  numbers (R-V7.2), the source-error key figure tile (R-V6.10). Stage 4 may cover them with unit tests on fake data.
- DV2-6 R-V2.1 "+{m} more" and "no run" names are tested by monkeypatching `report_renderer.data.engine.runs`.
- DV2-7 Interface helpers: tests/v2_helpers.py (`want`) because the existing conftest `need` lets
  ModuleNotFoundError escape; tests/fake_i18n_pkg added. No existing test or conftest was edited in any repo.
- DV2-8 Manual items listed in section 2 (browser-only behaviour of composer.js).
- DV2-9 Loose formats where the spec fixes none: percentage decimals, metric choice sort case, R-V1.10 over-50-blocks
  error code (only a 422 is asserted).

## 10. Questions for the user

- Q2-1 A layout created from a preset file with no `name` in the request: which name? DEFAULT (user to confirm): the
  file's own name, with " (2)" when taken (01-specs.md 2.3).
- The ten questions of 01-specs.md section 20 are still open; the tests follow their defaults (notably Q3 LangBiTe's
  tolerance column shown, Q5 TOC page numbers always on in PDF, Q6 "Evaluation {k}: {tools}", Q8 commentary caption on).
