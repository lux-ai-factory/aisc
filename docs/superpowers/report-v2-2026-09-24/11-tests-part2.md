# Part 2, stage 2: Tests first for D1 to D3 (report run v2)

Status: done. Inputs: RULES.md, BRIEF-2.md, 10-specs-part2.md, and 02-tests.md and 09-final-verify.md for the
conventions. Every R2 id of 10-specs-part2.md that a test can check has at least one test whose name carries the
id. Section 6 of 10-specs-part2.md was carried out: the French tests are removed (user decision D1), the tests the
decisions change are changed, each in its own commit. No implementation code was written. The two test-helper
defects in test files (`json=` on GET) are fixed because they are test code (R2-D3.5.2, R2-D3.5.3); the helper
`Throwaway.rows()` is NOT fixed (code, stage 4) but pinned by a new failing test. Nothing pushed, no new branch.

## 1. Baseline (2026-09-25 09:20, before any change of this stage)

`env | grep -iE 'DATABASE|DSN|DB_URL'` printed nothing. Database suites used their own `aisc-t-*` containers,
removed by their helpers. No test was skipped. Commands as in 02-tests.md section 5.

| suite | head | result | failures |
|---|---|---|---|
| aisc-report-plugin-interface | dev 7999876 | 135 passed | none |
| aisc-report-langbite | dev 4bbf943 | 31 passed | none |
| aisc-report-strongreject | dev 8611f44 | 24 passed | none |
| aisc-report-promptfoo | dev 2dcd7c1 | 22 passed | none |
| aisc-report-mlareject | dev 4942594 | 19 passed | none |
| aisc-report-generator (incl. goldens, e2e) | dev f211e16 | 589 passed, 2 failed | test_block_ai_card.py::test_r2_2_2_tags; test_service.py::test_r5_4_1_no_token_no_answer[get-/v1/block-types] |
| apps/report-composer (incl. browser tests, e2e) | aisc-install dc7bf07 | 331 passed, 8 failed | test_api_access.py::test_r4_4_3_a_stranger_gets_404 [get /api/p/alpha/systems, /layouts, /choices?..., /p/alpha/]; test_api_reports.py::test_r4_2_5_generate_stores_the_snapshot_and_the_pdf, ::test_r3_12_the_snapshot_survives_edits, ::test_r4_3_5_the_renderer_failing_is_502_and_failed, ::test_r7_2_5_a_pdf_over_25_mb_is_not_stored |
| scripts/tests test_report_stack + test_report_grants | aisc-install dc7bf07 | 75 passed, 7 failed | stack: test_d6_guard_init_files_do_not_mention_report_roles, test_r4_1_2_launcher_card_seven, test_final_guard_frozen_passes; grants: test_d6a_report_ro_logs_in_read_only, test_r6_5_report_ro_never_reads_the_catalogue, test_d13_composer_role_owns_its_schema, test_d13_composer_role_search_path |
| scripts/pipeline_chain/test_dashboard_queries.py (R2-D3.5.5, recorded only) | same | 3 failed | all three, JSONDecodeError from `Throwaway.rows()` |

These equal 09-final-verify.md exactly.

### The 13 hidden tests (R2-D3.5.4) and the helper pin

- 5 are hidden by `TestClient.get(..., json=...)` (TypeError): generator `test_r5_4_1_no_token_no_answer[get-/v1/block-types]`
  and the 4 composer stranger GET cases. Fixed in the test files this stage (generator d213334, aisc-install 43bb723);
  all 5 now run and pass, so the behaviour was already right.
- 8 are hidden by `Throwaway.rows()` reading psql's last output line (the row-count footer): composer
  `test_api_reports.py` r4_2_5, r3_12, r4_3_5, r7_2_5 and grants d6a, r6_5, d13 x2. They stay failing until stage 4
  fixes `scripts/pipeline_chain/throwaway.py`.
- New pin: `scripts/tests/test_throwaway_rows.py` (12 tests on its own `aisc-t-rows-*` container): 0 rows, 1 row,
  3 rows spread over lines, text with a newline, double quotes, a single quote, the literal "(1 row)", non-ASCII,
  `|` and `+`, a multi-line query, the signature, AssertionError with psql's message. 10 fail today with
  `JSONDecodeError: Expecting value` (the defect); 2 pass (signature and error, compatibility of R2-D3.5.1).
- Check that the pin and the hidden tests agree with a correct helper: with `rows()` replaced in memory by a
  `-t -A` version that parses the whole output (a scratch pytest plugin, not committed), `test_throwaway_rows.py`
  gives 12 passed, `test_report_grants.py` 58 passed (the 4 hidden grants tests included), and
  `test_dashboard_queries.py` 3 passed. So the R2-D3.5.5 outcome for other people's suite is expected to turn green.

## 2. Totals after this stage (last full run 2026-09-25, about 10:05)

| repo, suite | total | passed | failed | new tests (F / P) | changed (F / P) | removed |
|---|---|---|---|---|---|---|
| aisc-report-plugin-interface | 139 | 137 | 2 | 4 (2 / 2) | 0 | 0 |
| aisc-report-langbite | 43 | 26 | 17 | 16 (12 / 4) | 5 (5 / 0) | 4 |
| aisc-report-strongreject | 26 | 24 | 2 | 5 (1 / 4) | 1 (1 / 0) | 3 |
| aisc-report-promptfoo | 29 | 17 | 12 | 10 (6 / 4) | 6 (6 / 0) | 3 |
| aisc-report-mlareject | 20 | 20 | 0 | 1 (0 / 1) | 0 | 0 |
| aisc-report-generator | 640 | 581 | 59 | 68 (49 / 19) | 11 (10 / 1) + 2 helper/test fixes (P) | 19 |
| apps/report-composer | 409 | 345 | 64 | 76 (50 / 26) | 13 (10 / 3) + 1 helper fix, 4 cases (P) | 6 (incl. 2 params) |
| scripts/tests stack + grants + throwaway_rows | 94 | 77 | 17 | 12 (10 / 2) | 0 | 0 |
| **all** | | | | **192 (130 / 62)** | **36 (32 / 4)** | **35** |

Remaining failures besides the new and changed tests: composer 4 (`rows()`), scripts 7 (3 stack tests caused by
other people's work, 4 grants tests hidden by `rows()`). No collection or setup error in any suite; no skip.

Why the passing new tests may pass today (all compatibility guards):
- Interface (2): other common options carry no `x-aisc-prose: true`; the annotation does not change validation.
- LangBiTe (4): headline unchanged (R2-D2.4); English ctx gives the same headline as none (R2-D1.8); `verdict()`
  None on a failed check (R2-D2.8); no run-result line when `All Tolerances Passed` is absent (R2-D2.3 last case).
- StrongREJECT (4): no Pass or Fail word in a scored and a failed run (R2-D2.6 asks for a pin), `verdict()` None,
  English ctx headline equals none.
- promptfoo (4): no note when neither rate is present, no counts derived from shares (Q2-4), `verdict()` None,
  English ctx headline equals none.
- mlareject (1): R2-D2.7 guard, no Pass / Fail word and no verdict.
- Generator (19): pattern mismatch "French" still 422 (R2-D1.3); fingerprint over the snapshot as received
  (R2-D1.4); nouns after a total need no singular (R2-D3.4.2); a tool's Fail does not change coverage (R2-D2.8);
  12 of 13 surrogate placements already encode (fix round 2, R2-D3.1.2); `&#55296;` in an href does not crash today
  (lxml yields no storable surrogate), both schemes; a clean link keeps its hyperlink (R2-D3.2.1).
- Composer (26): no notice when nothing was reset (R2-D3.6.2); identifiers, enums, patterns, reference sub-options
  and the fixed-list fallback are never prose (R2-D3.7.3, 11 cases); wrong-shape values left alone (R2-D3.7.4);
  "Keep texts" keeps all 11 prose shapes (R2-D3.7.5, 11 cases); the placeholder constant is already
  "Write this section." (R2-D3.8.1 pin); the unwritten hint does not block Save or Generate (R2-D3.8.3).
- Scripts (2): `rows()` signature and error type (R2-D3.5.1).

## 3. Requirement to test

F fails today for the missing feature (reason given), P passes today (section 2). IF interface, LB/SR/PF/ML the tool
packages, RG `aisc-report-generator/tests`, RC `aisc-install/apps/report-composer/tests`, SC `aisc-install/scripts/tests`.

### 3.1 D1: English only

| id | tests | repo | status |
|---|---|---|---|
| R2-D1.1 | test_p2_english::test_r2_d1_1_the_renderer_ships_only_en_json, ::test_r2_d1_1_language_files_read_only_the_built_in_folder; test_i18n::test_r2_d1_1_a_catalogue_in_report_i18n_path_is_ignored (changed) | RG | F: fr.json exists, `REPORT_I18N_PATH` is read |
| R2-D1.2 | test_p2_english::test_r2_d1_2_languages_route_and_health_are_english_only; test_i18n::test_r_v8_5_languages_route_lists_english_first (changed); test_service_v2::test_r_s_7_health_gains_interface_version_and_languages (changed) | RG | F: French is listed |
| R2-D1.3 | test_p2_english::test_r2_d1_3_absent_en_and_fr_give_byte_identical_html, ::test_r2_d1_3_any_pattern_valid_language_is_accepted_and_renders_english[de,xx,fr-BE], ::test_r2_d1_3_docx_text_and_language_property_are_english_with_fr, ::test_r2_d1_3_percent_and_decimal_follow_english_with_fr (F); ::test_r2_d1_3_a_pattern_mismatch_is_still_422_at_language (P); test_i18n::test_r2_d1_3_dates_stay_iso_numbers_use_the_decimal_point_with_fr, ::test_r2_d1_3_page_x_of_y_is_english_in_the_pdf_css_with_fr; test_snapshot_v2::test_r_v8_5_an_unknown_language_is_invalid_snapshot_at_language (changed) | RG | F: `lang="fr"`, French numbers, "xx" is 422 |
| R2-D1.4 | test_p2_english::test_r2_d1_4_the_fingerprint_keeps_its_definition_for_a_fr_snapshot | RG | P |
| R2-D1.5 | test_p2_english::test_r2_d1_5_the_context_is_english_whatever_the_language, ::test_r2_d1_5_translate_for_uses_the_package_en_json_then_the_renderer | RG | F: context is French; no package en.json |
| R2-D1.6 | test_compat_golden.py (unchanged), test_v2_key_figures::test_fix_r2_3_english_label_value_texts_are_unchanged | RG | P |
| R2-D1.7 | LB test_p2_langbite::test_r2_d1_7_no_french_catalogue, SR/PF test_p2_*::test_r2_d1_7_no_french_catalogue; LB/SR/PF test_packaging::test_r_v2_24_templates_and_catalogues_ship_with_the_package (changed) | LB SR PF | F: fr.json exists (LB: en.json missing) |
| R2-D1.8 | LB/SR/PF test_p2_*::test_r2_d1_8_an_english_context_gives_the_same_headline_as_none; LB test_tool_renderer::test_fix2_headline_without_a_context_stays_english (kept) | LB SR PF | P |
| R2-D1.9 | test_p2_english_only::test_r2_d1_9_the_editor_has_no_language_control, ::..._composer_js_neither_reads_nor_sends_a_language, ::..._the_composer_no_longer_calls_get_v1_languages | RC | F |
| R2-D1.10 | test_p2_english_only::test_r2_d1_10_post_accepts_and_ignores_a_language[fr,de,xx,en], ::..._put_accepts_and_ignores_a_language[fr,de,xx], ::..._draft_preview_accepts_and_ignores_a_language, ::..._the_layout_views_carry_no_language, ::..._unknown_language_is_never_an_error | RC | F: 422 `unknown_language` or `language` in the view |
| R2-D1.11 | test_p2_english_only::test_r2_d1_11_db_default_settings_have_no_language, ::..._a_new_row_gets_the_column_default, ::..._an_update_never_writes_the_language, ::..._a_saved_preset_stores_no_language | RC | F |
| R2-D1.12 | test_p2_english_only::test_r2_d1_12_preview_and_generate_snapshots_carry_no_language; test_v2_layout_settings::test_r_s_3_... and test_v2_draft_preview::test_r_u3_1_... (changed) | RC | F |
| R2-D1.13 | test_p2_english_only::test_r2_d1_13_built_in_preset_files_have_no_language[x4], ::..._exports_write_no_language, ::..._import_with_any_language_is_accepted_and_ignored[fr,de,xx]; test_v2_presets r_v1_1, r_v1_2, r_v1_6, r_v1_7, r_v1_edge (changed) | RC | F |
| R2-D1.14 | test_v2_pages::test_r_v8_16_the_composer_screens_stay_in_english (changed, no language argument) | RC | P |
| R2-D1.15 | interface i18n tests unchanged (DV2-4) | IF | P |
| R2-C.1 | RG test_p2_english::test_r2_c_1_a_v2_snapshot_with_fr_renders_english_through_the_service, test_i18n::test_r2_c_1_fixed_texts_are_english_when_the_snapshot_says_fr, test_e2e_v2::test_e2e_v2_preview_pdf_and_docx (changed); RC test_p2_english_only::test_r2_c_1_a_layout_row_holding_fr_previews_and_generates_without_a_language, ::test_r2_c_1_a_saved_preset_row_holding_fr_makes_an_english_layout | RG RC | F |
| R2-C.2 | test_compat_golden.py unchanged (only the "Sommaire" alternative in a helper dropped, allowed by 10 section 6.1) | RG | P |
| R2-C.3 | test_p2_english::test_r2_c_3_one_observation_is_singular_in_the_test_results_section[a_v2_live, a_v2_live_styled, a_v2_legacy_links] | RG | F: "1 observations" |
| R2-C.4 | not testable in this stage beyond existing R-C.3 tests (stored bytes returned as stored) | RC | P (existing) |

### 3.2 D2: the tool's own Pass / Fail

| id | tests | repo | status |
|---|---|---|---|
| R2-D2.1 | covered by R2-D2.2 to R2-D2.7 together (no threshold option exists to test) | | |
| R2-D2.2 | LB test_p2_langbite::test_r2_d2_2_the_pass_fail_column_follows_the_tolerance_set_column, ::test_r2_d2_2_realistic_not_evaluated_group_and_other_texts_as_written, ::test_r2_d2_2_prompt_count_columns_stay; test_tool_renderer::test_r_v2_11_group_table_columns, ::test_r_v2_11_group_cells, ::test_r_v2_12_no_verdict_words_of_the_report (changed) | LB | F: header "LangBiTe's tolerance check", cells "Passed"/"Failed" |
| R2-D2.3 | LB test_p2_langbite::test_r2_d2_3_all_checks_passed_is_pass, ::..._a_failed_check_is_fail, ::..._no_group_is_not_evaluated_not_fail, ::..._unparsable_description_is_not_evaluated, ::..._the_line_is_shown_with_summary_detail (F); ::..._no_line_when_the_measurement_is_absent (P); test_tool_renderer::test_r_v2_15_summary_detail_shows_line_and_chart_only (changed) | LB | F: no run-result line |
| R2-D2.4 | LB test_p2_langbite::test_r2_d2_4_headline_is_unchanged; test_r_v2_14_headline (kept) | LB | P |
| R2-D2.5 | PF test_p2_promptfoo::test_r2_d2_5_rows_are_labelled_pass_and_fail, ::..._the_note_says_whose_results_they_are, ::..._chart_series_labels, ::..._headline_label_is_pass (F); ::..._no_note_when_neither_rate_is_present, ::..._no_counts_are_derived_from_the_shares (P); test_tool_renderer r_v2_21 x4, r_v2_23_headline (changed); RG test_p2_english::test_r2_d2_5_the_promptfoo_key_figure_tile_is_labelled_pass | PF RG | F: "Pass rate", "Fail rate" |
| R2-D2.6 | SR test_p2_strongreject::test_r2_d2_6_no_pass_or_fail_word_in_a_scored_run, ::..._in_a_failed_run | SR | P (pin asked by the spec) |
| R2-D2.7 | ML test_p2_no_pass_fail::test_r2_d2_7_no_pass_or_fail_word_and_no_verdict | ML | P |
| R2-D2.8 | LB test_p2_langbite::test_r2_d2_8_verdict_stays_none_on_a_failed_check; SR/PF test_p2_*::test_r2_d2_8_verdict_stays_none; RG test_p2_english::test_r2_d2_8_verdict_stays_none_and_coverage_is_unchanged | LB SR PF RG | P |
| R2-D2.9 | existing R-V2.9 tests in LB/SR/PF (artifact contents never printed) | LB SR PF | P |
| R2-D2.10 | LB test_p2_langbite::test_r2_d2_10_pass_and_fail_appear_only_as_the_tool_stated_them; PF test_p2_promptfoo::test_r2_d2_10_wording | LB PF | F: no Pass / Fail values yet ("Pass rate" label in PF) |

### 3.3 D3: remaining bugs

| id | tests | repo | status |
|---|---|---|---|
| R2-D3.1.1 | test_p2_fixes::test_r2_d3_1_1_a_lone_surrogate_in_the_instance_id_is_422[preview,pdf,docx] | RG | F: 500 |
| R2-D3.1.2 | test_p2_fixes::test_r2_d3_1_2_every_problem_list_encodes_as_utf8[13 placements] | RG | 1 F (instance_id, UnicodeEncodeError), 12 P |
| R2-D3.2.1 | test_p2_fixes::test_r2_d3_2_1_a_forbidden_character_in_a_link_address_keeps_the_text[5 refs x https/mailto], ::test_r2_d3_2_1_a_clean_link_address_keeps_its_hyperlink | RG | 8 F (`ValueError: All strings must be XML compatible`), 3 P |
| R2-D3.3.1 | test_p2_browser::test_r2_d3_3_1_a_failed_outline_request_clears_the_outline_and_offers_try_again (Playwright, /usr/bin/google-chrome) | RC | F: the message never shows (timeout) |
| R2-D3.4.1 | test_p2_english::test_r2_d3_4_1_en_json_holds_only_singular_entries_and_keeps_the_default_rule; test_i18n::test_r2_d3_4_1_en_catalogue_has_the_format_and_is_the_only_one (changed); test_i18n::test_fix_every_singular_form_belongs_to_a_used_message (changed to en.json, P, empty until en.json has entries) | RG | F |
| R2-D3.4.2 | test_p2_english::test_r2_d3_4_2_english_singular_form[9 messages, counts 1/0/3] (F); ::test_r2_d3_4_2_nouns_after_the_total_need_no_singular (P) | RG | F |
| R2-D3.4.3 | LB test_p2_langbite::test_r2_d3_4_3_en_json_holds_the_singular_form_only, ::test_r2_d3_4_3_one_group_is_singular_four_are_plural | LB | F: no en.json |
| R2-D3.4.4 | test_p2_english::test_r2_d3_4_4_the_singular_keys_are_exactly_the_listed_ones (list `SINGULARS`; stage 3 extends it with any addition it records) | RG | F |
| R2-D3.5.1 | SC test_throwaway_rows.py (12) | SC | 10 F (JSONDecodeError), 2 P |
| R2-D3.5.2 | test_service::test_r5_4_1_no_token_no_answer (fixed) | RG | P |
| R2-D3.5.3 | test_api_access::test_r4_4_3_a_stranger_gets_404 (fixed) | RC | P |
| R2-D3.5.4 | the 13 tests of section 1 | RG RC SC | 5 P now, 8 F until stage 4 |
| R2-D3.5.5 | test_dashboard_queries.py recorded (3 F now, 3 P with a repaired helper) | | recorded only |
| R2-D3.5.6 | v2_fakes workaround kept | RC | n/a |
| R2-D3.6.1 | test_p2_presets::test_r2_d3_6_1_import_stores_no_reference_of_the_source | RC | F: chart_id kept |
| R2-D3.6.2 | test_p2_presets::test_r2_d3_6_2_import_names_every_reset_reference, ::..._a_layout_from_a_preset_file_names_every_reset_reference, ::..._the_composer_shows_notices_as_information (F); ::..._no_notice_when_nothing_was_reset (P) | RC | F: no `notices` |
| R2-D3.6.3 | existing R-V1.4 tests | RC | P |
| R2-D3.7.1 | test_p2_prose::test_r2_d3_7_1_commentary_is_marked_as_prose, ::..._the_docstring_documents_x_aisc_prose (F); ::..._other_common_options_are_not_marked_as_prose, ::..._the_annotation_does_not_change_validation (P) | IF | F |
| R2-D3.7.2 | test_p2_fixes::test_r2_d3_7_2_every_built_in_string_leaf_is_classified, ::test_r2_d3_7_2_the_named_options_carry_their_annotation | RG | F: unclassified leaves are exactly the spec's list |
| R2-D3.7.3 | test_p2_presets::test_r2_d3_7_3_prose_options_are_dropped_without_keep_texts[11 shapes] (F); ::..._identifiers_enums_patterns_are_kept[9], ::..._a_string_under_a_reference_option_is_not_prose, ::..._without_a_description_the_fixed_list_applies (P) | RC | F: text kept |
| R2-D3.7.4 | test_p2_presets::test_r2_d3_7_4_a_required_prose_value_becomes_the_placeholder_cut_to_max_length, ::..._titles_stay (F); ::..._a_value_of_the_wrong_shape_is_left_as_it_is (P) | RC | F |
| R2-D3.7.5 | test_p2_presets::test_r2_d3_7_5_prose_options_are_kept_with_keep_texts[11] (P); test_v2_presets::test_fix4_* unchanged (P) | RC | P |
| R2-D3.8.1 | RG test_p2_fixes::test_r2_d3_8_1_the_renderer_constant_is_the_placeholder, ::..._an_unwritten_free_text_is_left_out_of_the_preview[2], ::..._left_out_of_pdf_and_docx, ::..._a_placeholder_commentary_is_not_printed, ::..._a_placeholder_chapter_intro_is_not_printed (F); RC test_p2_presets::test_r2_d3_8_1_the_composer_placeholder_constant (P) | RG RC | F: the section is printed |
| R2-D3.8.2 | no test (renderer does not look into plugin options; composer side is R2-D3.8.3) | | n/a |
| R2-D3.8.3 | test_p2_unwritten::test_r2_d3_8_3_built_in_blocks_holding_the_placeholder_are_flagged, ::..._plugin_blocks_..._are_flagged, ::..._the_outline_answer_lists_unwritten_options, ::..._the_outline_answer_flags_plugin_blocks_too (F); ::..._a_hint_not_a_problem_save_and_generate_go_through (P) | RC | F |
| R2-D3.8.4 | RG test_p2_fixes::test_r2_d3_8_4_a_preset_layout_generated_at_once_has_no_placeholder[eu-ai-act, internal-audit]; RC test_e2e_v2::test_e2e_v2_preset_coverage_draft_pdf_and_docx (changed) | RG RC | F |
| R2-D3.9.1 | a document correction; checked by reading in stage 5 (no test) | docs | n/a |
| R2-D3.10.1 | test_block_ai_card::test_r2_2_2_tags (test fix) | RG | P |
| R2-D3.10.2 | the generator suite at 0 failures after stage 4 | RG | n/a |

## 4. Removed and changed tests (all by the user's decisions, each in its own commit)

### Removed (35)
- generator 73c43ea (D1): test_i18n `test_r_v8_4_every_msgid_has_a_french_entry`, `test_r_v8_4_the_core_texts_are_translated`,
  `test_r_v8_3_t_in_french`, `test_r_v8_2_a_bad_file_name_in_the_path_is_ignored`, `test_fix_french_singular_forms` (12
  cases); test_commentary `test_r_v3_9_the_caption_is_translated`; test_v2_key_figures
  `test_fix2_french_tool_tiles_use_french_numbers_and_words`, `test_fix_r2_3_french_label_value_texts_use_the_french_colon`
  (19 test items). Helper `fr()` removed in 8167003.
- langbite 8389157 (D1): `test_r_v8_4_every_msgid_has_a_french_entry`, `test_r_v8_8_french_uses_the_package_catalogue`,
  `test_fix2_headline_values_follow_the_report_language`, `test_fix_french_one_group_is_singular` (replaced by
  R2-D3.4.3 tests), helper `french_ctx`.
- strongreject 440c697, promptfoo b5fc3a6 (D1): each `test_r_v8_4_every_msgid_has_a_french_entry`,
  `test_r_v8_8_french_uses_the_package_catalogue`, `test_fix2_headline_values_follow_the_report_language`, helper
  `french_ctx` (the spec's "test_fix2_headline_without_a_context_stays_english stays" exists only in langbite; SR/PF got
  the new English-context test instead).
- composer 3041352 (D1): `test_r_d_3_the_layouts_list_carries_the_language`, the `language=xx` and `language=de` params
  of `test_r_d_4_bad_settings_are_refused`, `test_r_v8_1_the_language_is_sent_in_the_preview_snapshot` (replaced by
  R2-C.1), `test_r_v8_13_the_language_select` (replaced by R2-D1.9), `test_r_s_7_languages_is_get_v1_languages`;
  v2_fakes `LANGUAGES` and `languages()` (safe: `renderer_calls.languages` falls back when the method is missing).

### Changed (36)
- generator 8167003 (D1): the 6 test_i18n tests renamed to their R2 ids (each keeps a "Was ..." docstring),
  test_e2e_v2 (keeps `language="fr"`, expects English), test_service_v2 health, test_snapshot_v2 unknown language,
  test_v2_key_figures contract-2 tile test, test_fix_every_singular_form_belongs_to_a_used_message (over en.json);
  "Sommaire" alternative dropped from test_compat_golden's helper. fe30ed2 holds the promptfoo tile change as a new test.
- generator d213334 (R2-D3.5.2) and 8410eac (R2-D3.10.1): helper and assertion aim fixed, behaviour unchanged.
- langbite 8c5d646 (D2, D1): group table columns and cells, no-verdict words, summary detail, packaging.
- strongreject 60a03fe, promptfoo b33df81 (D1, D2): packaging; promptfoo labels in r_v2_21 x4 and r_v2_23_headline.
- composer 43bb723 (R2-D3.5.3) and 3041352 (D1): the 13 tests listed in 10-specs-part2 section 6.5 (see section 3).

## 5. Commits (local, not pushed)

| repo | commits |
|---|---|
| aisc-report-plugin-interface | cd3cc1e |
| aisc-report-langbite | 8389157, 8c5d646, 5f0fe82 |
| aisc-report-strongreject | 440c697, 60a03fe, 8fa948f |
| aisc-report-promptfoo | b5fc3a6, b33df81, 918bc36 |
| aisc-report-mlareject | 247a0d9 |
| aisc-report-generator | d213334, 8410eac, 73c43ea, 8167003, fe30ed2 |
| aisc-install | 43bb723, b162d16, 3041352, d446ee2, and this document's commit |

Other people's working-tree changes in aisc-install (apps/qualification pointer, homepage/project.html, the LLM-keys
files of another session, form-assembly docs, `__pycache__`) were not staged. Container `aisc-t-llmtok-*` running
at the end belongs to that other session and was left alone; no container of this stage is left.

## 6. Deviations

- DV11-1 R2-D3.10.1 is a test fix in its own commit (generator 8410eac): the hidden-tags assertion looks at the tag
  list (`dl.tags`) only. It passes on today's code and still fails if tags are shown when hidden.
- DV11-2 R2-D3.5.2 and R2-D3.5.3 are fixed now (test code, not implementation), so 5 of the 13 hidden tests are
  visible and pass already. `Throwaway.rows()` is left for stage 4 as instructed.
- DV11-3 The renderer placeholder constant is expected at `report_renderer.blocks.free_text.PLACEHOLDER` (the spec
  names no place). Stage 3 may move it and update that one test.
- DV11-4 Composer outline tests send `options` with each block, because `unwritten` (R2-D3.8.3) cannot be computed
  from the block type alone. composer.js must send options in its outline request.
- DV11-5 The composer fakes (`tests/v2_fakes.py`) do not yet carry the R2-D3.7.2 `x-aisc-prose: false` annotations
  (`chart.dimension`, `test_results.tools` items). Once the schema-driven prose rule lands, stage 4 must add them to
  the fakes in a listed test commit, or exports of fake layouts would drop those values.
- DV11-6 The unrealistic `Not evaluated` row (1 passed, 1 failed) in the LangBiTe package fixture and seed row 7204 is
  left as it is (changing the seed would invalidate the goldens; changing the fixture would change stage-2 tests
  without need). The new test `test_r2_d2_2_realistic_not_evaluated_group_and_other_texts_as_written` uses a realistic
  0/0 row.
- DV11-7 R2-D3.6.2 notice labels are taken from the schema property `title` in the tests (for example the fake's
  "Chart id").
- DV11-8 The R2-D3.8.4 renderer test copies the block lists of the two composer presets inline instead of reading
  aisc-install files (the generator tests do not depend on aisc-install).

## 7. Questions for the user

None new. The part-2 questions Q2-1 to Q2-8 of 10-specs-part2.md stand; the tests follow their defaults.
