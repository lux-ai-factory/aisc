# Stage 3: Tests first for the modular AISC report

Status: stage 3 of 5, done. Inputs: `RULES.md`, `01-specs.md`, `02-architecture.md` (deviations D1 to D16,
amendments O1 and O2). All tests are written and committed. There is no implementation yet. Apart from
the few checks listed as "already passing", every test fails with `missing feature: ...`: a module,
name, file, role or grant that stage 5 has to write. Stage 4 plans against the test API in section 2.

## 1. Totals (last run, 2026-09-24)

| repo, branch | suite | tests | failing as expected | already passing |
|---|---|---|---|---|
| aisc-report-plugin-interface, dev | `tests/` | 45 | 40 | 5 (legacy `BaseReporterPlugin` behaviour) |
| aisc-report-mlareject, dev | `tests/` | 19 | 18 | 1 (path source, set in this stage) |
| aisc-report-generator, dev | `tests/` | 218 | 218 | 0 |
| aisc-install, feat/unified-modules | `apps/report-composer/tests/` | 107 | 107 | 0 |
| aisc-install, feat/unified-modules | `scripts/tests/test_report_stack.py`, `test_report_grants.py` | 82 | 78 | 4 (see table) |

A "failing as expected" test fails in its own body with `missing feature: <module/name/file>`, or on a
missing role or privilege (`role "report_ro" does not exist`). No test errors at collection or setup:
fixtures hand out a `Missing` stand-in, and using it fails the test body. The mlareject tests fail first on
`ModuleNotFoundError: resources` at package import. That import is the D9 defect itself: the eager
`resources.sql_alchemy` import has to go.

## 2. What the tests assume (the API stage 5 implements)

**Interface** (`vera_report_plugin_interface`, D10): `BlockResult(html, status, notices=[])` (status in
ok/empty/stale/error, and html must be a fragment); `BaseBlockRenderer` with the R1.1 attributes, abstract
`load(ctx, options)` and `render(data, options, ctx)`, `choices(ctx, option_name) -> []`, classmethods
`validate_declaration()` (raises `InvalidBlockType`), `full_options_schema()`, `full_default_options()`,
`options_problems(options) -> [{pointer, message}]`, and the method `render_package_template(rel, **ctx)`;
`SOURCES`; `templating.render_package_template(package, rel, **ctx)` with autoescape ON for `.html.j2`
(today's `select_autoescape(["html","xml"])` leaves `.html.j2` unescaped, and the test catches that);
`BaseToolRenderer` (`tool_names`, abstract `render(run, ctx)`, `verdict(run) -> None`, classmethod
`matches(plugin_row)`); `normalise_tool_name`; `tool_keys(display_name, name, package_name)` (D7);
`ToolRun(evaluation, evaluation_plugin, tool, components, observations, measurements, artifacts)`: frozen,
deeply read-only, no session.

**MLA-Reject**: `MLAREJECTToolRenderer`; `statistics.compute_statistics(measurements)` (one case per
`score` measurement; dimensions language/jailbreak/category; missing key shown as "unknown"; no
harmful-case texts); entry point `aisc_report.tools`; the package imports without the old generator model and
prints nothing.

**Renderer** (`report_renderer`, `report_service`): `data.Sources(platform_dsn, superset_dsn,
project_db_template, airo_vocab_path, objectives_csv_path, superset_url=None)` and `Sources.from_env(env)`;
`registry.build_registry(builtins=True, entry_points=None, plugin_dirs=())` returning a Registry with
`block`, `block_types`, `tool_for`, `register_block(cls, origin)`, `register_tool`, and raising
`DuplicateBlockType` / `DuplicateToolRenderer`; `context.Deps(registry, sources, images, clock,
chart_data=None)`; `context.context_for(project_id, system_id, *, deps, mode)` (used for `choices`);
`document.render(snapshot, deps)` returning `{html | pdf_base64, sha256, block_statuses}` and raising
`document.NotFound`; `errors.new_error_ref()` and `errors.PlatformUnavailable`; `pdf.url_fetcher` and
`pdf.html_to_pdf`; `snapshot.validate(snapshot)`; `superset.NoImageProvider`, `FakeImageProvider`,
`SupersetScreenshotProvider(base_url, username, password, http, monotonic, sleep)`, `ImagesUnavailable`,
`FakeChartData`, `NoChartData` and `image_provider_from_env(env)` (only an exact `REPORT_CHART_IMAGES=superset`
turns screenshots on, per O1); `data.platform.pinned_system`; `data.controls.database_name`; `data.scope.NotInProject`;
public functions in `data.{platform, qualification, control_objectives, engine, controls, superset_db}` take
`(project_id, system_id, ...)` first; `report_service.create_app(deps=, token=None)`, with the token read from
`REPORT_SERVICE_TOKEN`, and module-level `app` served by uvicorn.

**Markup contract**: `section.block.block-{type}#block-{iid}[data-status]` + `h2` (R1.5); `#toc`; per-objective
`[data-objective]`, per-risk `[data-risk]`, `[data-coverage-count]`; option schemas mark data references with
`"x-aisc-reference": true` (test_results.evaluations, control_answers.checklists, dashboard_chart.chart_id,
summary_coverage.links). The composer uses this marker for R3.6 and R3.14.

**Composer** (`report_composer`): `app.create_app(*, database_url, renderer, clock=None)`, with migrations at
start; routes `/api/...` and `/p/{slug}/...` (Caddy strips `/report-composer`); a renderer object with
`block_types()`, `choices(project_id, system_id, block_type)` and `render(snapshot)`;
`renderer_client.HttpRendererClient(base_url, token, timeout=120.0)` with `RendererUnavailable` and
`RendererTimeout`; `layouts.{default_blocks, validate_layout, reset_invalid, to_template, from_template}`;
`reports.pdf_filename`; `access.{Access, decide, same_origin, role_in_project}`; `forms.form_fields`;
`static/composer.js`; error body `{"error": {code, message, details}}`; list rows carry `system_number` and
`last_report`; env `PLATFORM_ORIGIN` for R4.4.6. Editor controls carry `data-control` (palette, save,
generate, save-template, move-up, move-down, remove, configure, version), and blocks carry `data-instance-id`.

**Stack**: see `scripts/tests/test_report_stack.py`. It covers the services `report-composer` (expose 8095),
`report-renderer` (expose 8001, backend network only, not in the Caddyfile) and `report-grants`
(postgres:14-alpine, `/setup/report-grants.sh` and `/setup/report-ro-grants.sql`, runs after the three module
migrate jobs). `init/report-roles.sql` is mounted in initdb after `50-superset-db.sql` and run by
`postgres-setup`. `platform/project-template/0003_report.sql`. Launcher card `report-composer-card`.
`secrets.sh` names. Dev passwords equal the role names.

## 3. Rule to test

Files: IF = aisc-report-plugin-interface/tests, ML = aisc-report-mlareject/tests, GE =
aisc-report-generator/tests, CO = aisc-install/apps/report-composer/tests, ST = aisc-install/scripts/tests.
Status F = failing as expected, P = already passing, M = manual.

| rule | tests (file::name) | repo | status |
|---|---|---|---|
| R1.1 | IF test_blocks::test_r1_1_* (declares contract, bad declaration refused x7, sources); GE test_registry::test_r1_1_every_built_in_declares_a_valid_contract, ::test_r1_1_reads_name_the_section_6_sources | IF, GE | F |
| R1.2 | GE test_registry::test_r1_2_a_duplicate_type_id_refuses_to_start, ::test_r1_2_register_block_names_both_origins | GE | F |
| R1.3 | GE test_document::test_r1_3_a_block_gets_exactly_its_context, ::test_r1_3_no_newer_versions_for_the_latest | GE | F |
| R1.4 | IF test_blocks::test_r1_4_* (fields, four statuses, other status refused, fragment only) | IF | F |
| R1.5 | GE test_document::test_r1_5_each_block_is_wrapped_in_its_section, ::test_r1_5_the_instance_title_overrides_the_type_title | GE | F |
| R1.6 | IF test_blocks::test_r1_6_*; GE test_registry::test_section_2_default_options; GE test_document::test_r1_6_page_break_before_starts_a_new_page (PDF page count) | IF, GE | F |
| R1.7 | GE test_block_ai_card::test_r2_2_5_*, test_block_test_results::test_r1_7_no_results_for_the_version, and the `empty` tests of every block | GE | F |
| R1.8 | every block's `assert_no_foreign_data` (markers V1MARK, V3MARK, NULLMARK, BETAMARK) | GE | F |
| R1.9, R6.3 | test_block_{ai_card,risk,control_objectives,test_results,control_answers}::test_r1_9_*; GE test_e2e::test_e2e_pinned_to_version_1_says_version_2_is_newer | GE | F |
| R1.10 | GE test_document::test_r1_10_a_failing_block_becomes_an_error_box[load/render]; GE test_errors::test_r1_10_an_error_ref_is_8_hex_characters | GE | F |
| R1.11 | IF test_blocks::test_r1_11_*; GE test_document::test_r1_11_invalid_options_are_an_error_and_nothing_is_read; GE test_block_free_text::test_r1_11_* | IF, GE | F |
| R1.12 | IF test_blocks::test_r1_12_block_templates_are_autoescaped_even_as_html_j2; GE test_document::test_r1_12_*, plus escaping tests in risk, control_answers, dashboard_chart, free_text; ML test_tool_renderer::test_r1_12_values_are_escaped | IF, GE, ML | F |
| R1.13 | IF test_blocks::test_r1_13_*; GE test_block_{test_results,control_answers,dashboard_chart}::test_r1_13_*, test_block_summary_coverage::test_r2_8_2_choices_for_links; GE test_service::test_r5_4_choices | IF, GE | F |
| R2.1.1 to R2.1.4, D12 | GE test_block_cover::* (9 tests, including the PDF text for the requester) | GE | F |
| R2.2.1 to R2.2.5 | GE test_block_ai_card::* (9) | GE | F |
| R2.3 (D2, D3, O2) | GE test_block_risk::* (11): operators from JSON-LD, stated class, labelled chains, escape, empty rules | GE | F |
| R2.4.1 to R2.4.5, D14 | GE test_block_control_objectives::* (8) | GE | F |
| R2.5.1 to R2.5.7, D8, D16 | GE test_block_test_results::* (22) | GE | F |
| R2.6.1 to R2.6.6, D15 | GE test_block_control_answers::* (14) | GE | F |
| R2.7 (D4, D5, O1) | GE test_block_dashboard_chart::* (13); GE test_superset::* (14: providers, env switch, mocked screenshot API, 30 s poll) | GE | F |
| R2.8.1 to R2.8.5 | GE test_block_summary_coverage::* (7) | GE | F |
| R2.9.1, R2.9.2 | GE test_block_free_text::* (3) | GE | F |
| R3.1 | CO test_api_layouts::test_r3_1_the_version_must_belong_to_the_project, ::test_r3_1_names_are_unique_per_project | CO | F |
| R3.2 | CO test_api_layouts::test_r3_2_a_layout_never_moves_between_projects | CO | F |
| R3.3, R3.4 | CO test_layouts_unit::test_r3_3_the_default_block_list; CO test_api_layouts::test_r3_3_a_new_layout_gets_the_default_blocks_and_the_latest_version | CO | F |
| R3.5 to R3.9 | CO test_layouts_unit::test_r3_5_* .. test_r3_9_*; CO test_api_layouts::test_r3_5_*, ::test_r3_6_*, ::test_r3_7_limits, ::test_r3_8_zero_blocks_saves, ::test_r3_9_*; GE test_registry::test_r3_6_* (reference markers) | CO, GE | F |
| R3.10 | CO test_api_layouts::test_r3_10_a_block_type_that_went_away; GE test_document::test_r3_10_an_unknown_block_type_renders_as_an_error | CO, GE | F |
| R3.11 | CO test_api_layouts::test_r3_11_* | CO | F |
| R3.12 | CO test_api_reports::test_r4_2_5_generate_stores_the_snapshot_and_the_pdf, ::test_r3_12_the_snapshot_survives_edits | CO | F |
| R3.13 | CO test_api_layouts::test_r3_13_deleting_a_layout_deletes_its_reports | CO | F |
| R3.14, R3.15, R7.3.2 | CO test_layouts_unit::test_r3_14_*, ::test_r3_15_*; CO test_api_templates::test_r3_14_*, ::test_r3_15_* | CO | F |
| R3.16 | CO test_api_templates::test_r3_16_only_the_creator_or_an_admin_deletes, ::test_r3_14_saving_as_template_strips_project_data (visible to bob) | CO | F |
| R4.1.1 | CO test_pages::test_r4_1_1_one_small_script; CO test_forms_unit::* | CO | F |
| R4.1.2, D11 | ST test_report_stack::test_r4_1_2_* (service, Caddy route, launcher card 7); CO test_api_layouts::test_d11_the_project_may_be_named_by_pid | ST, CO | F |
| R4.1.3, D13 | CO test_api_layouts::test_r4_1_3_migrations_run_at_start; ST test_report_stack::test_r4_1_3_*; ST test_report_grants::test_d13_* | CO, ST | F |
| R4.2.1, R4.2.2, R4.2.6 | CO test_pages::test_r4_2_1_layouts_list, ::test_r4_2_2_the_editor, ::test_r4_2_6_a_viewer_sees_no_edit_controls; CO test_forms_unit::test_r4_2_2_* | CO | F |
| R4.2.3 | save sends the full ordered list: CO test_api_layouts::test_r3_11_saving_bumps_the_revision_and_keeps_the_order. Drag, move and "unsaved changes" flag: browser only | CO | F / M |
| R4.2.4 | CO test_api_reports::test_r4_2_4_preview_is_of_the_saved_revision_with_a_strict_csp | CO | F |
| R4.2.5 | CO test_api_reports::test_r4_2_5_*; the progress display itself: browser only | CO | F / M |
| R4.3 table | CO test_api_layouts::test_r4_3_* (systems, block-types, choices, shape, list, validate), test_api_reports::test_r4_3_* | CO | F |
| R4.3.1 | CO test_api_layouts::test_r3_5_unknown_block_type_and_invalid_options (body shape); test_api_access::test_r4_4_1_no_sign_in_is_401 | CO | F |
| R4.3.2, R7.3.1 | CO test_api_layouts::test_r4_3_2_*, test_api_reports::test_r4_3_2_*, test_api_layouts::test_r7_3_1_*; GE test_data_access::test_r7_3_1_*, ::test_r6_2_a_system_of_another_project_raises_not_in_project | CO, GE | F |
| R4.3.3 | CO test_api_reports::test_r4_3_3_one_generation_at_a_time | CO | F |
| R4.3.4 | CO test_filename_unit::test_r4_3_4_filename; CO test_api_reports::test_r4_3_4_download | CO | F |
| R4.3.5 | CO test_api_reports::test_r4_3_5_* | CO | F |
| R4.4.1 to R4.4.6 | CO test_access_unit::*; CO test_api_access::* (401, stranger 404, viewer 403, 503 fail closed, role read per request, admin, same origin) | CO | F |
| R5.1.1 to R5.1.7 | GE test_document::test_r5_1_* ; GE test_snapshot::test_r5_1_1_*; GE test_pdf::test_r5_1_4_*, test_r5_1_5_* | GE | F |
| R5.2.1 | IF test_blocks::test_r5_2_1_* | IF | F |
| R5.2.2 | GE test_registry::test_r5_2_2_the_nine_blocks_are_built_in | GE | F |
| R5.2.3, D10 | GE test_registry::test_r5_2_3_* (entry points, broken import skipped, plugin dir); ML test_packaging::test_d10_* | GE, ML | F (path source P) |
| R5.3.1, D7 | IF test_tools::*; GE test_registry::test_d10_mlareject_tool_renderer_is_discovered; GE test_block_test_results::test_r5_3_1_* | IF, GE | F |
| R5.3.2 | IF test_tools::test_r5_3_2_*; ML test_tool_renderer::test_r5_3_2_* | IF, ML | F |
| R5.3.3, D9 | IF test_legacy_plugin::* ; GE test_registry::test_r5_3_3_*; GE test_block_test_results::test_r5_3_3_*, ::test_d9_a_legacy_plugin_that_raises_falls_back; ML test_packaging::test_d9_*; ML test_statistics::*; ML test_tool_renderer::* | IF, GE, ML | IF legacy P, rest F |
| R5.3.4 | GE test_registry::test_r5_3_4_* | GE | F |
| R5.3.5 | GE test_registry::test_r5_3_5_*; GE test_block_test_results::test_r2_5_3_* | GE | F |
| R5.4, R5.4.1 to R5.4.4 | GE test_service::* (17: token 401, constant time, token from env, health, block types, choices, preview, pdf, 422, 404, legacy routes gone, no files left) | GE | F |
| R6.1, D6 | ST test_report_grants::test_r6_1_*, ::test_d6a_*, ::test_d6b_*, ::test_d6c_*; GE test_data_access::test_r6_1_*; ST test_report_stack::test_r6_1_renderer_reads_as_report_ro | ST, GE | F |
| R6.2 | GE test_data_access::test_r6_2_* (x6 modules + NotInProject) | GE | F |
| R6.4, D1 | GE test_block_control_answers::test_r6_4_*; GE test_data_access::test_d1_the_project_database_name_is_validated | GE | F |
| R6.5 | GE test_data_access::test_r6_5_*; ST test_report_grants::test_r6_5_*; IF test_blocks::test_r1_1_sources_* | GE, ST, IF | F |
| R7.1.1 | GE test_data_access::test_r7_1_1_* ; GE test_service::test_r7_1_1_platform_unreachable_is_503 | GE | F |
| R7.1.2 | GE test_data_access::test_r7_1_2_logs_carry_ids_and_counts_never_bodies | GE | F |
| R7.2.1, R7.2.2 | GE test_performance::*; CO test_api_reports::test_r7_2_2_* | GE, CO | F |
| R7.2.3 | GE test_block_test_results::test_r7_2_3_*, test_block_control_answers::test_r7_2_3_* | GE | F |
| R7.2.4 | GE test_block_dashboard_chart::test_r7_2_4_*; GE test_superset::test_r7_2_4_* | GE | F |
| R7.2.5 | CO test_api_reports::test_r7_2_5_a_pdf_over_25_mb_is_not_stored | CO | F |
| R7.2.6 | CO test_api_reports::test_r4_2_5_* (POST returns the final status) | CO | F |
| R7.3.3 | ST test_report_grants::test_r7_3_3_*; CO test_pages::test_r7_3_3_the_composer_code_names_no_module_schema | ST, CO | F |
| R7.3.4 | CO test_api_reports::test_r4_2_4_* (CSP header); CO test_pages::test_r7_3_4_* | CO | F |
| R7.3.5 | GE test_service::test_r7_3_5_*; GE test_superset::test_r7_3_5_*; CO test_api_reports::test_r7_3_5_*; ST test_report_stack::test_r7_3_5_* | GE, CO, ST | F |
| R7.3.6, FROZEN | ST test_report_stack::test_final_guard_frozen_passes; ST ::test_d6_guard_init_files_do_not_mention_report_roles | ST | P |
| R7.4.1 | by construction: fake renderer (CO conftest), fake image and chart-data providers, fixed clock (GE conftest) | CO, GE | F |
| O1 | GE test_superset::test_o1_*, test_block_dashboard_chart::test_o1_*; ST test_report_stack::test_o1_chart_images_off_tonight (F), ::test_o1_no_superset_worker (P) | GE, ST | F / P |
| D3 | ST test_report_stack::test_d3_renderer_mounts_vocab_and_objectives_read_only; GE risk tests use the vocab fixture | ST, GE | F |
| D10 | ST test_report_stack::test_d10_renderer_builds_with_interface_and_mlareject | ST | F |
| Stack, R5.4.1 | ST test_report_stack::test_r5_4_1_caddy_never_routes_the_renderer | ST | P |
| E2E (renderer) | GE test_e2e::test_e2e_every_block_in_order_version_2_only, ::test_e2e_pinned_to_version_1_says_version_2_is_newer, ::test_e2e_the_pdf_has_the_blocks_in_order | GE | F |
| E2E (composer to real renderer) | CO test_e2e::test_e2e_compose_preview_and_generate, ::test_e2e_pinned_to_version_1 (the renderer runs as a subprocess with `uv run --extra dev uvicorn report_service:app` in the generator repo, so stage 5 adds uvicorn there) | CO | F |

**End-to-end test.** Project Echo (seed) has versions 1 and 2, a card per version, an objectives assessment per
version, one evaluation per version with measurements, one checklist with answers of both versions, and
chart 36 with a comment. A layout with all nine block types, in the order cover, summary, free text, chart,
answers, tests, risk, card, objectives, is rendered as HTML and PDF. The tests assert the section order
(HTML ids, block statuses, PDF text order), that only E2MARK data appears, and that no "newer" notice
appears. Pinned to version 1, they assert the banner and "Newer results exist for version 2." instead.

## 4. Commands (never the live DB)

Check first: `env | grep -iE 'DATABASE|DSN|DB_URL'` must print nothing. The bed also refuses to start when
any report DSN variable points outside it or at `:5432/`. Each database suite starts its own throwaway
`postgres:14-alpine` container `aisc-t-<label>-<hex>` on a kernel-chosen port. The container is built by
`aisc-install/scripts/lib/report_bed.py` (on top of `scripts/pipeline_chain/throwaway.py`) and removed at
session end. No `docker compose` command is run.

```
cd ~/aisc-report-plugin-interface && uv run --extra dev pytest -q
cd ~/aisc-report-mlareject       && uv run --extra dev pytest -q
cd ~/aisc-report-generator       && uv run --extra dev pytest -q          # AISC_INSTALL_DIR defaults to ../aisc-install
cd ~/aisc-install/apps/report-composer && uv run --extra dev pytest -q    # REPORT_GENERATOR_DIR defaults to ../../../aisc-report-generator (e2e)
cd ~/aisc-install && uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider \
    scripts/tests/test_report_stack.py scripts/tests/test_report_grants.py
cd ~/aisc-install && scripts/guard-frozen.sh        # final check; GUARD PASS on 2026-09-24 (also run by test_final_guard_frozen_passes)
```

Bed contents, in order: `init/platform-db.sql`, `init/project-databases.sql`, `init/superset-db.sql`;
`init/report-roles.sql` if present; platform migrations as `platform_rw`; the module schemas restored as
their own roles; superset; project databases A, B and E with `platform/project-template/*.sql` and controls as
`controls_rw`; `scripts/report-grants.sh` if present, run inside the container with PG* env and files in
`/setup`; the seeds. Schema fixtures: `scripts/tests/fixtures/report/schema_*.sql`, made by `refresh_schema.sh`,
which runs `pg_dump --schema-only --no-owner --no-privileges` in the live `postgres` container. That is a read
only. The seeds, vocabulary and objectives CSV fixtures sit next to them. Deviation from 02 section 5: the
fixtures and the bed live once in aisc-install (not per repo). The generator and composer tests import the
bed from there.

## 5. Commits (local, not pushed)

| repo | branch | commit |
|---|---|---|
| aisc-report-plugin-interface | dev | c743d64 Tests first: block and tool renderer contract, legacy plugin behaviour |
| aisc-report-mlareject | dev | 533f310 Tests first: MLA-Reject tool renderer, statistics from measurements, packaging |
| aisc-report-generator | dev | 6b00397 Tests first: renderer, nine block renderers, tool renderers, service, data scoping, end-to-end |
| aisc-install | feat/unified-modules | 17b70b4 Tests first: report composer, stack wiring and report_ro grants, shared report test bed |

Only my own files are staged. Skeletons only: `pyproject.toml` (dev extras, path sources per D10),
`uv.lock`, and the empty modules `vera_report_plugin_interface/{blocks,tools,templating}.py`,
`vera_report_plugin_mlareject/{statistics,tool_renderer}.py`, `report_renderer/__init__.py` and
`report_composer/__init__.py`. Other people's uncommitted files in aisc-install are left untouched. That
includes submodules, `docker-compose.development.yml` and `scripts/verify.sh`. This docs folder is not
committed either.

## 6. Rules that are not (fully) automated, and choices made for the tests

- **Manual:** R4.2.3 (drag and drop, and the "unsaved changes" flag in the browser) and R4.2.5 (the progress
  display). Both are frontend-only behaviour. Save's contract is automated.
- **Not asserted:** R2.1.1 `show_logo` (only the logo image, no data); R2.7.1 "rendering time" (under O1
  there is no rendered image).
- **R2.4.3 ambiguity:** the Control objectives block has no `links` option, so R2.8.3 coverage can only be
  "not covered" there, unless stage 4 decides otherwise. The test only asserts that one of the four statuses
  is shown when `show_status` is on and none when it is off.
- **O1 chart status:** with `NoImageProvider` the chart block is expected to be `ok` with a note (nothing
  failed). `error` is reserved for R2.7.2 and R2.7.6.
- **R2.6.3:** the count "{k} answers were given for other versions" counts the answers of the submission
  shown. Null-stamped answers are included (D15).
- **R5.4.1:** `/health` is called with the token in the tests. The spec does not say whether `/health` is open.
- **Passwords:** the bed logs in `report_ro` and `report_composer_rw` with the dev password equal to the role
  name (D6/D13 dev default). If stage 5 changes the default, the bed must follow.
- **Stack tests** read the working tree (compose, Caddyfile, launcher), including other people's uncommitted
  hunks.
