# Stage 3: Coding plan for report run v2 (more versatile, still easy)

Status: stage 3 of 5, done. Inputs: `RULES.md`, `BRIEF.md`, `00-baseline.md`, `01-specs.md`, `02-tests.md`, the
committed failing tests (interface 7d93a31, langbite f4af1d0, strongreject 34cad23, promptfoo d7b8a4f, generator
29c54cc, aisc-install 1752778), and the previous run's plan (`../report-2026-09-23/04-coding-plan.md`). Stage 4
follows this plan group by group, in order. Where this plan names a file, function, class, markup or route, that
is the name to use (the tests import or look for it). No implementation code is written here.

## 0. Failing counts, re-measured by stage 3 (2026-09-25, throwaway beds only)

`env | grep -iE 'DATABASE|DSN|DB_URL'` printed nothing; every database run used `aisc-t-*` postgres:14-alpine
containers made by `scripts/lib/report_bed.py`; none were left behind.

| suite | total | failed | passed | matches 02-tests.md |
|---|---|---|---|---|
| aisc-report-plugin-interface | 121 | 72 | 49 | yes (72 new failing; 45 old + 4 guards pass) |
| aisc-report-langbite | 28 | 27 | 1 | yes |
| aisc-report-strongreject | 23 | 22 | 1 | yes |
| aisc-report-promptfoo | 21 | 20 | 1 | yes |
| aisc-report-mlareject | 19 | 0 | 19 | yes |
| aisc-report-generator | 503 | 237 | 266 | yes (235 new + 2 known: test_r2_2_2_tags, test_r5_4_1_no_token_no_answer[get-/v1/block-types]) |
| apps/report-composer | 330 | 189 | 141 | yes (181 new + 8 known: test_api_access x4, test_api_reports x4) |
| scripts/tests report suites | 82 | 7 | 75 | yes (the 7 known stack/grants failures) |
| guard-frozen.sh | | | | identical to 00-baseline.md (G1 FAIL 238 lines, G2 PASS, G3 PASS x2, G4 FAIL x3, G5 PASS) |

Failing tests per file (new ones): interface test_v2_charts 17, test_v2_contracts 16, test_v2_i18n 15,
test_v2_richtext 24. Generator test_blocks_v2_contracts 10, test_commentary 13, test_document_structure 14,
test_docx 14, test_e2e_v2 1, test_header_footer 15, test_i18n 11, test_service_v2 38, test_snapshot_v2 17,
test_v2_changes_since 21, test_v2_chart_block 27, test_v2_coverage_map 8, test_v2_filters 17, test_v2_key_figures 13,
test_v2_test_results 16. Composer test_e2e_v2 1, test_v2_draft_preview 16, test_v2_forms_unit 12,
test_v2_layout_settings 24, test_v2_migration 15, test_v2_pages 38, test_v2_presets 45,
test_v2_renderer_client_unit 2, test_v2_reports 13, test_v2_templates 15. Each tool package: test_packaging 6 and
test_tool_renderer 21 (LB), 16 (SR), 14 (PF).

## 1. Ground rules for stage 4

1. **Before every test run** `env | grep -iE 'DATABASE|DSN|DB_URL'` prints nothing (else `unset`). Database suites
   make their own `aisc-t-*` container; afterwards `docker ps -a --filter name=aisc-t- --format '{{.Names}}'` prints
   nothing (remove leftovers with `docker rm -f`). Never `docker compose up/down/build/restart/run/exec` on the
   stack, never write to 127.0.0.1:5432.
2. **TDD:** the failing tests exist. Write code until they pass. The only test edits allowed are the by-design
   changes of section 4 (each in its own commit, message given) and new unit tests you add for the untested corners
   of 02-tests.md DV2-5 (additive, seen failing first). Any other old test that breaks: decide whether the change is
   intended by 01-specs.md (then add it to 04-code-report.md under "by-design test changes" with the reason, own
   commit) or a regression (fix the code).
3. **Commits:** local only, never push, no new branch. Stage files by explicit path, never `git add -A`/`.`. Never
   stage `__pycache__/`, `.venv/`, `.pytest_cache/`, `*.egg-info/`. In aisc-install, other people's changes
   (`apps/qualification` pointer, `homepage/project.html`, `docs/superpowers/form-assembly-2026-09-24/`, any
   `__pycache__`) stay unstaged. Commit messages are plain sentences.
4. **uv:** each repo tests with `uv run --extra dev pytest -q`. After a `pyproject.toml` change in the interface or a
   tool package, run `uv lock` in every repo that depends on it (network is available) and
   `uv sync --extra dev --reinstall-package vera-report-plugin-interface` (plus `--reinstall-package` for each changed
   tool package: entry points are only picked up on reinstall).
5. **Guard:** after each aisc-install commit, `cd ~/aisc-install && scripts/guard-frozen.sh` must print exactly the
   lines of 00-baseline.md (the run only touches `apps/report-composer` and this folder, which the guard does not
   read; re-run anyway, it takes about a minute).
6. **Words the old tests forbid:** under `aisc-report-generator/report_renderer/` no file contains `catalogue` in
   any case (the objectives file is the "objectives CSV"; the French word "catalogue" must not appear in `fr.json`
   either: use "référentiel"). No `.py` file under `apps/report-composer/report_composer/` contains
   `qualification.`, `control_objectives.`, `engine.`, `controls.`, `aisc_comment` or `catalogue` (watch f-strings
   and docstrings such as "control_objectives.show_severity"; the preset JSON files are not `.py` and may name block
   types freely).
7. **No em dashes** in any file, UI text or message; plain short sentences.
8. **Compatibility is byte level** (R-C.1, goldens in `tests/golden/`): see decision C1 to C4 in section 2. Never
   re-capture the goldens.

## 2. Cross-cutting decisions stage 4 builds on

**C1. The document shell stays byte identical.** The goldens compare everything outside the sections, including
the whole `<style>` element and `<html lang="en">`. Therefore `report.css` is not edited, and every CSS rule this
run needs is appended only when the document uses the feature: one file per feature under
`report_renderer/templates/css/` (`commentary.css`, `chapters.css`, `marking.css`, `key_figures.css`, `chart.css`,
`toc_pages.css`), appended after `style.css_overrides(look)` in this fixed order, each only when present
(`toc_pages.css` only in `pdf`/`docx` mode, where no golden compares the HTML). Tool renderers (the three new
packages) add no CSS at all: they use the existing classes (`table`, `.note`, `.placeholder`, `ul.notices`,
`.stat-box`) and attributes inside their section, which the goldens allow to change.

**C2. English output is today's output.** Every fixed text goes through `t("English msgid", **params)`; with
`language` absent or `en` the catalogue has no messages, so `t` returns the msgid with its placeholders filled.
When a template line is converted to `t(...)`, keep its whitespace and punctuation exactly (for example
`{{ t("Status: {status} | Date: {date}", status=e.status, date=e.date) }}` only where the spec changes the line;
lines the spec does not change produce the same bytes). Pass `t` into every template context.

**C3. Numbers in French.** Numbers are localised by replacing the `.` of the string today's code already produces
(`str(x)`, `f"{x:g}"`, `f"{x:.3f}"`) with the catalogue's `decimal_separator`. So English is byte identical and
French gets `0,125`. `BlockContext.number(text_or_value)` does this; the interface's `i18n.format_number(ctx, ...)`
does the same for plugins (reading `getattr(ctx, "decimal_separator", ".")`). Dates stay `YYYY-MM-DD`.

**C4. What a snapshot without the v2 keys means.** No `coverage_links` key: the links of the first
`summary_coverage` block (today's rule). No `document`: `toc=auto`, `numbering=false`, `id=None`. No `language`: `en`.
No new style fields: today's header and footer. A contract-1 block or tool renderer is untouched.

**C5. The block context (renderer).** `BlockContext` gains fields with defaults, so `context_for(...)` calls of the
old tests keep working: `language="en"`, `t`, `translate_for`, `decimal_separator="."`, `percent_format="{value}%"`,
`tool_options={}` (a plain dict), and methods `number(value)` and `percent(share, decimals=1)`. `ReportInfo` gains
`language`, `marking="none"`, `document_id=None`, `toc="auto"`, `numbering=False`, `header_text=None`,
`footer_text=None`, `show_document_id=False`, `fingerprint=""` (existing fields unchanged). `context_for(project_id,
system_id, *, deps, mode="preview", layout=None, requested_by="", coverage_links=(), language="en", report=None)`.
Test results passes `dataclasses.replace(ctx, tool_options={"show_charts": ..., "detail": ...})` to tool renderers.

**C6. Plugins without the renderer's context.** Tool renderers get their translator with
`vera_report_plugin_interface.i18n.translator_for(ctx, __package__)`: `ctx.translate_for(package)` when present,
else `ctx.t`, else an English formatter. Options with `getattr(ctx, "tool_options", {})`, defaults
`show_charts=True`, `detail="full"`. The tool package tests pass a bare `SimpleNamespace`; nothing else may be
assumed of `ctx`.

**C7. Mode docx is a document, not a preview.** The cover's author line, the document id line and the TOC CSS treat
`docx` exactly as `pdf` (`ctx.mode in ("pdf", "docx")`). `html_to_docx` receives the HTML built for `docx` mode,
which is the PDF's HTML (R-V8.9).

**C8. Coverage map in the composer vs the renderer.** The composer stores `layout.coverage` and always sends
`coverage_links` (even `[]`). The renderer's `ctx.report.coverage_links` is that list, or the legacy first-summary
links when the key is absent. `summary_coverage` uses its own `links` when non-empty, else
`ctx.report.coverage_links` (R-U2.3; this is R-C.4 item 4 for old snapshots).

**C9. Reference options in the composer.** `layouts._reference_problems` must (a) accept a value equal to the block
type's default for that option (`"previous"`, `"all"`), (b) compare dict values (`metrics` items, `tool_chart`,
`metric`) against the choice values by equality, using a list, not a set (dicts are not hashable), and (c) keep the
legacy per-field check for `links` items (choices keyed `links.objective_id` and so on). A required reference option
that is missing gets the message `Choose a value` (code `invalid_options`); a missing non-reference option keeps
`is required`. An "all or list" option holding `[]` gets `invalid_options` "Pick at least one, or choose All." at
`/{name}` (R-U4.3, composer only).

**C10. A renderer without the v2 calls.** The old composer tests use `conftest.FakeRenderer`, which has no
`languages()` or `coverage_choices()` and returns no `fingerprint`. `renderer_calls.languages(request)` falls back to
`[{"code": "en", "name": "English"}]` when the renderer object has no `languages`; `coverage_choices` falls back to
empty lists; `result.get("fingerprint")` may be None (stored as NULL). The composer calls `coverage_choices` only when
the map is non-empty or the editor page draws the grid. So conftest.py is not edited.

## 3. Deviations and the test fix of this stage

- **D3-1 (interface, not in the specs).** `import vera_report_plugin_interface` loads SQLAlchemy today, because
  `__init__.py` imports `base_report_plugin` (which imports `sqlalchemy.orm`). The tool packages' test
  `test_r_v2_24_imports_cleanly_prints_nothing_no_database` forbids that (checked: the import puts `sqlalchemy` in
  `sys.modules`). So `__init__.py` loads `BaseReporterPlugin` lazily through a module `__getattr__` (PEP 562);
  `from vera_report_plugin_interface import BaseReporterPlugin` keeps working (registry, legacy tests).
  `base_report_plugin.py` stays untouched, and the interface keeps its `sqlalchemy` dependency for the legacy class.
- **D3-2 (renderer).** New CSS only when the feature is used (C1). Not written in 01-specs.md, forced by the goldens.
- **D3-3 (test fix, committed in this stage):** aisc-report-generator `c2382fe` "The DOCX no-text-lost test ignores
  chart labels drawn inside the SVG picture and the cover's preview-only author line". Two changes, both in the one
  test `test_docx.py::test_r_v8_9_no_text_of_the_html_body_is_lost`: (1) `tests/v2_core_helpers.py::body_text_nodes`
  skips strings inside an `<svg>` element: R-V8.9 itself turns inline SVG into a PNG picture, so its tick and value
  labels cannot be Word text (the chart's data table carries them); (2) the test drops the node
  `Generated by: preview` before comparing: it compares a preview with a DOCX, and the cover's author line differs by
  design (R2.1 preview line vs the requester in a document, C7). Without the fix the test is impossible to pass
  without making a generated Word file claim to be a preview. Re-run after the fix: the file still fails 14 of 14 for
  the missing feature.
- **D3-4 (composer).** `min_severity` is `{"type": ["integer", "null"], "minimum": 1, "maximum": 5}` (as the test fake
  and the filter test assume), with the annotation `x-aisc-null-label: "All risks"`. `forms.form_fields` draws a
  nullable integer with a range of at most 10 values as a select: first option value "" labelled with
  `x-aisc-null-label` (else empty), then minimum to maximum; kind `int-or-null`. R-U5.1's enum-label rule does not
  apply (not an enum).
- **D3-5 (composer).** Viewers must not see the text "Delete" or "New layout" anywhere in the layouts page HTML (old
  `test_r4_2_6`). The page renders the one `<dialog data-confirm>` only for editors (viewers have nothing to
  confirm), with a neutral confirm button "Confirm" whose label composer.js sets from the trigger's
  `data-confirm-action` ("Delete layout", "Delete template", "Delete preset", "Reset and save"). The message region is
  on every page for everyone.
- **D3-6 (composer).** The typed links widget and `multiselect` are removed from `_form.html.j2`; a
  `summary_coverage` block with non-empty legacy links shows them read only (R-U2.6).
- **D3-7 (renderer).** `charts.svg(spec, colours, *, decimal_separator=".", percent_format="{value}%")`: two optional
  keyword arguments so charts follow the report language (R-V8.7); the tested signature `svg(spec, colours)` is
  unchanged and stays pure.
- **D3-8 (renderer).** The i18n module is `report_renderer/languages.py`, not `report_renderer/i18n.py`: the tests
  need the folder `report_renderer/i18n/` for the JSON files, and a module and a folder of the same name would clash.
- **D3-9 (renderer).** The DOCX converter parses the HTML with `lxml.html` (lxml is python-docx's own dependency;
  declared explicitly). Beautiful Soup stays a dev dependency.
- **D3-10 (by design, section 4).** composer.js may grow to under 500 lines (old test says 300); the generate handler
  downloads through `/download`.
- **D3-11 (for the user, not code).** The renderer's Dockerfile gains three build contexts; the live compose file is
  not changed in this run (A4), so its `additional_contexts` must be added before the next deploy (Questions).

Nothing else in the tests contradicts the specs or is impossible. 02-tests.md Q2-1 (a layout made from a preset file
takes the file's name when the request has none, " (2)" when taken) is followed.

## 4. Existing tests that must change by design (each in its own commit, before the code that breaks them)

| repo, file::test | exact change | why |
|---|---|---|
| generator `tests/test_registry.py` (module constants) | `BUILTINS` gains `"chart", "key_figures", "changes_since", "chapter", "appendix"` (14 types; `test_r5_2_2_the_nine_blocks_are_built_in` keeps its name, its list grows; line 119 follows automatically). `EXPECTED_DEFAULTS`: `control_objectives` adds `"requirements": "all", "objectives": "all", "min_severity": None, "include_unrated": True, "show_severity": False`; `test_results` adds `"metrics": "all", "show_charts": True, "detail": "full"`; `summary_coverage` adds `"requirements": "all"`; `free_text` becomes `{"format": "plain"}`; new entries `chart` `{"dataset": "coverage_status", "runs": "latest", "show_table": True, "max_bars": 20, "orientation": "auto"}`, `key_figures` `{"figures": ["version", "risks", "objectives", "coverage", "tests", "checklists"], "show_tool_headlines": True}`, `changes_since` `{"compare_to": "previous", "sections": ["card", "objectives", "tests", "controls"], "show_unchanged": False}`, `chapter` `{"title": "Chapter", "intro": "", "page_break_before": True}`, `appendix` `{}` | R-V6.1, R-V2.5, R-V2.8, R-V6.5, R-V3.11, R-V4.6, R-V6.8, R-V7.2, R-V5.5 |
| generator `tests/test_registry.py::test_section_2_default_options` | the expected `full_default_options()` becomes `{"title": "", "page_break_before": False, "commentary": "", "commentary_position": "after", **EXPECTED_DEFAULTS[type_id]}` | R-V3.6 adds two common options (the chapter's own `title`/`page_break_before` override through the `**`) |
| composer `tests/test_api_templates.py::test_a_layout_is_not_saved_without_a_template` | rename to `test_a_layout_is_saved_without_a_template`; assert `201` and `template_id is None` | R-U6.1 |
| composer `tests/test_api_templates.py::test_saving_changes_the_template_and_needs_one` | rename to `test_saving_changes_the_template`; the last PUT with `template_id=None` answers 200 with `template_id is None` | R-U6.1 |
| composer `tests/test_api_templates.py::test_a_layout_without_a_template_is_not_generated` | rename to `test_a_layout_whose_template_was_deleted_is_generated_in_the_platform_look`; generate answers 201 and the pdf snapshot has no `style` | R-U6.1, R-U6.4 |
| composer `tests/test_api_templates.py::test_a_template_exports_as_one_file_with_its_logo` | expected document `version: 2` plus `"header_text": None, "footer_text": None, "marking": "none", "show_document_id": False` | R-V5.10 |
| composer `tests/test_pages.py::test_r4_1_1_one_small_script` | `< 300` becomes `< 500` lines | U3 draft preview, U4 widgets, U7 dialog, coverage grid and presets are browser behaviour; the logic stays in Python, the script stays one file |
| composer `tests/test_pages.py::test_generate_answers_next_to_the_button_and_downloads_the_pdf` | `'"/pdf"' in handler` becomes `'"/download"' in handler` (the handler branch must still start with `what === "generate"`) | R-V8.15: one download route for both formats |

Commit messages: generator "The registry tests expect the five new built-in blocks and the new default options of
report run v2"; composer "The template and page tests follow report run v2: layouts without a template, template
export version 2, a larger script and one download route".

No existing generator test_block_* test is expected to break (Alpha's LangBiTe runs go to the LangBiTe renderer's
"Other measurements" table, which must print `0.125` and `0.5` exactly as `f"{x:g}"`, and the meta line keeps the
short pid). If one does, rule 2 of section 1 applies.

## 5. DO NOT EDIT

- Frozen per RULES: `apps/backend`, `apps/eval`, `shared/*`, AIRO files, `apps/catalogue`, other modules,
  `init/*`, `platform/*`, `scripts/guard-frozen.sh`, `scripts/lib/throwaway-pg.sh`, `docker-compose*.yml`.
- `aisc-report-plugin-interface/vera_report_plugin_interface/base_report_plugin.py` and the mlareject legacy template.
- The goldens (`tests/golden/*.html`, `*.json`, `MANIFEST.json`) and `tests/golden/capture.py`.
- Stage 2's tests, fixtures and seeds (`*/tests/*`, `scripts/tests/*`, `scripts/lib/report_bed.py`,
  `scripts/tests/fixtures/report/*`), except the by-design rows of section 4.

---

## Group 1: the interface (aisc-report-plugin-interface, dev)

### 1.1 Files and responsibilities

- `pyproject.toml`: add `"markdown-it-py>=3.0"` and `"nh3>=0.2.17"` to `dependencies`.
- `vera_report_plugin_interface/__init__.py`: `INTERFACE_VERSION = 2`; export `BaseBlockRenderer`, `BlockResult`,
  `InvalidBlockType`, `SOURCES`, `BaseToolRenderer`, `ToolRun`, `normalise_tool_name`, `tool_keys` as today;
  `BaseReporterPlugin` through `def __getattr__(name)` importing `.base_report_plugin` on first access (D3-1);
  `__all__` unchanged plus `INTERFACE_VERSION`.
- `vera_report_plugin_interface/blocks.py`:
  - `COMMON_PROPERTIES`: `title` (+ `title: "Section title"`, `description: "Replaces the block's own heading."`,
    `x-aisc-more: true`), `page_break_before` (+ "Start on a new page", "Starts this section on a new page in the
    PDF.", more), `commentary` (`{"type": "string", "minLength": 0, "maxLength": 10000, "title": "Commentary",
    "description": "Your own words about this section, printed with it."}`, not more), `commentary_position`
    (`{"enum": ["after", "before"], "title": "Place the commentary", "description": "Where the commentary goes.",
    "x-aisc-enum-labels": {"after": "After the section", "before": "Before the section"}, "x-aisc-more": true}`).
  - `COMMON_DEFAULTS` adds `"commentary": ""`, `"commentary_position": "after"`.
  - `BaseBlockRenderer`: class attributes `description: str = ""`, `new_instance_options: dict = {}` (never mutated);
    `validate_declaration` also checks `description` is a string and `new_instance_options` a dict whose merge over
    `default_options` validates against the relaxed schema. `full_options_schema()` unchanged (own properties still
    override common ones, which the chapter relies on).
- `vera_report_plugin_interface/tools.py`: `BaseToolRenderer.contract_version: int = 1`, `chart_ids: dict = {}`,
  `headline(self, run) -> list[dict]` returns `[]`, `charts(self, run) -> list[dict]` returns `[]`. `verdict`,
  `matches`, `render_package_template` unchanged.
- `vera_report_plugin_interface/richtext.py` (new): `render(text) -> Markup`. One module-level `MarkdownIt("commonmark",
  {"html": False, "breaks": True, "linkify": False}).enable("table")`. Token pass before rendering: `heading_open` /
  `heading_close` (ATX and setext) become paragraph tokens (tag `p`), so `# Heading` gives `<p>Heading</p>`; `image`
  inline tokens become a text token holding the alt text; `link_open` whose `href` scheme is not http, https or mailto
  is dropped with its `link_close` (the text stays). Then `nh3.clean(html, tags=ALLOWED_TAGS, attributes={"a":
  {"href"}}, url_schemes={"http", "https", "mailto"}, link_rel="noopener noreferrer")`. `ALLOWED_TAGS` = the 16 tags
  of R-V3.2. Never raises: any exception falls back to the escaped text in one `<p>`; input longer than 20000
  characters is cut first (the schemas already limit it). Must finish the deep-nesting test quickly (markdown-it's
  `maxNesting` stays at its default).
- `vera_report_plugin_interface/charts.py` (new): `svg(spec, colours, *, decimal_separator=".",
  percent_format="{value}%") -> Markup`. `validate_spec(spec)` raises `ValueError` for an unknown `kind`, an unknown
  `value_format`, more than 60 series items, a value that is neither a number (bool refused) nor None, a label that is
  not text. Geometry is pure arithmetic (no randomness, no I/O, no fonts measured): width `160mm` (never more), height
  from the number of bars, `viewBox` in user units, `role="img"`, `aria-label` = escaped title, first child
  `<title>`. One `<rect fill="{colours['primary']}">` per non-null value and no other element with that fill; axis,
  ticks and grid lines use `colours["grid"]`, text uses `colours["text"]`. Axis from `axis_min` (default 0) to
  `axis_max` or, when null, the maximum rounded up to 1, 2 or 5 times a power of ten. Five tick labels. Value label at
  the end of each bar; a null value draws no bar and prints `n/a`. Labels over 40 characters are cut to 39 plus
  `...`. `percent` values print as `value*100` with at most one decimal, trailing `.0` dropped, through
  `percent_format`; `number` values print with `:g`; `.` replaced by `decimal_separator`. Every text escaped with
  markupsafe. Optional `note` printed as a last `<text>` line.
- `vera_report_plugin_interface/i18n.py` (new):
  - `CODE = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")`; `@dataclass(frozen=True) class Catalogue(code, name, messages,
    decimal_separator=".", percent_format="{value}%")`.
  - `load_catalogue(path) -> Catalogue`: JSON object with `_meta` (code matching CODE, non-empty name) and
    `messages` (dict of str to str); anything else raises `ValueError`.
  - `package_catalogue(package, code) -> Catalogue | None`: `i18n/{code}.json` in the package folder
    (`importlib.util.find_spec(package).submodule_search_locations`), None when absent.
  - `fill(msgid, params) -> str`: replaces `{name}` when `name` is in params, leaves every other brace as it is (a
    regex, never `str.format`).
  - `translator(*catalogues) -> t(msgid, **params)`: the first catalogue holding msgid wins, else msgid; then `fill`.
  - `translator_for(ctx, package)` (C6), `format_number(ctx, value, decimals=None)` and
    `format_percent(ctx, share, decimals=1)` (C3, reading `decimal_separator` and `percent_format` from ctx with
    English defaults).

Data flow: none of these modules reads a database or a file at import; `package_catalogue` reads only when called.

### 1.2 Tests that turn green

All of `tests/test_v2_richtext.py` (24), `tests/test_v2_charts.py` (17), `tests/test_v2_i18n.py` (15),
`tests/test_v2_contracts.py` (16); the 4 guards and 45 old tests stay green: **121 passed**.

### 1.3 Commands

```
cd ~/aisc-report-plugin-interface && uv lock && uv sync --extra dev && uv run --extra dev pytest -q      # 121 passed
cd ~/aisc-report-mlareject && uv lock && uv sync --extra dev --reinstall-package vera-report-plugin-interface \
    && uv run --extra dev pytest -q                                                                          # 19 passed
cd ~/aisc-report-langbite && uv run --extra dev python -c "import vera_report_plugin_interface, sys; print('sqlalchemy' in sys.modules)"
                                                                                                             # False (after uv lock + sync there too)
```
In the generator, `uv lock && uv sync --extra dev --reinstall-package vera-report-plugin-interface` now; its
`test_registry` default-options cases fail until the by-design commit of section 4, the rest is unchanged.

### 1.4 Commits (interface, dev)

1. "Light formatting, SVG charts and a catalogue loader for block and tool renderers" (richtext.py, charts.py,
   i18n.py, pyproject.toml, uv.lock).
2. "Every block gets a commentary, and options carry labels, help and a more-options mark; tool renderers may declare
   contract 2 with headlines and charts; the legacy plugin class loads lazily" (blocks.py, tools.py, __init__.py).

---

## Group 2: the renderer core (aisc-report-generator, dev)

Order inside the group: 2.0 test update, 2.1 languages, 2.2 snapshot and fingerprint, 2.3 context, 2.4 document
structure, 2.5 header, footer, marking, document id, 2.6 commentary and free text, 2.7 translation of the existing
blocks, 2.8 service and registry.

### 2.0 By-design test update

The generator row of section 4 (test_registry), own commit. Its cases for chart, key_figures and changes_since stay
red until group 3.

### 2.1 Languages

- `report_renderer/i18n/en.json`: `{"_meta": {"code": "en", "name": "English", "decimal_separator": ".",
  "percent_format": "{value}%"}, "messages": {}}`.
- `report_renderer/i18n/fr.json`: `_meta` `{"code": "fr", "name": "Français", "decimal_separator": ",",
  "percent_format": "{value} %"}`; `messages` holds every msgid the renderer uses, added in the same commit as the
  code that uses it (so `test_i18n.py::test_r_v8_4_every_msgid_has_a_french_entry` stays green from this group on).
  It must also hold texts translated through a variable: block type titles ("Cover", "AI card", "Risk
  classification", "Control objectives", "Test results", "Control answers", "Dashboard chart", "Summary and
  coverage", "Free text", "Chart", "Key figures", "Changes since an earlier version", "Chapter", "Appendix"), coverage
  statuses, evaluation and run status words, stated risk class names, marking labels, figure labels.
- `report_renderer/languages.py` (new; D3-8): `BUILTIN_DIR`; `catalogues(env=None) -> dict[str, Catalogue]` reads
  the built-in folder then each folder of `REPORT_I18N_PATH` (colon separated) at call time; a file that
  `load_catalogue` refuses is skipped with a warning (never fatal); a later file of the same code wins.
  `languages(env=None) -> [{"code", "name"}]` English first, then by code. `translator(code) -> (t, catalogue)` with
  English fallback. Read per request (cheap), never at import.

### 2.2 Snapshot and fingerprint (`report_renderer/snapshot.py`, `report_renderer/style.py`)

- `SCHEMA` gains, all optional: `snapshot_version` `{"type": "integer", "enum": [1, 2]}`; `mode` enum
  `["preview", "pdf", "docx"]`; `language` `{"type": "string", "pattern": "^[a-z]{2}(-[A-Z]{2})?$"}`; `document`
  `{"type": "object", "additionalProperties": false, "properties": {"id": {"type": ["string", "null"], "pattern":
  UUID_PATTERN}, "toc": {"enum": ["auto", "on", "off"]}, "numbering": {"type": "boolean"}}}`; `coverage_links`
  `{"type": "array", "maxItems": 200, "items": {"type": "object", "required": ["objective_id"], "properties":
  {"objective_id": {"type": "string", "minLength": 1}, "tests": {"type": "array", "items": {"type": "string"}},
  "checklists": {"type": "array", "items": {"type": "string"}}}}}`.
- `style.SCHEMA` gains `header_text` and `footer_text` (`{"type": ["string", "null"], "maxLength": 120}`),
  `marking` (enum none, public, internal, confidential, strictly_confidential), `show_document_id` (boolean).
- `_message` gains `maxLength` ("must be at most N characters") and `pattern` stays "must be a UUID" only for UUID
  patterns (else "is not valid").
- `fingerprint(snapshot) -> str`: SHA-256 hex of `json.dumps(copy without mode, requested_by, document,
  sort_keys=True, separators=(",", ":"), ensure_ascii=False)` encoded UTF-8 (R-V5.15).
- `structure_problems(blocks) -> list[dict]`: a second `appendix` gives `{"instance_id", "code":
  "duplicate_appendix", "pointer": "/blocks/{i}", "message": "a layout has one appendix at most"}`.

### 2.3 Context (`report_renderer/context.py`)

C5. `context_for` builds `t` from `languages.translator(language)`, `translate_for(package)` =
`translator(package_catalogue(package, language), renderer catalogue)`, and fills `ReportInfo` from the snapshot
(document, style fields, fingerprint). `ScopedData` keeps a reference to `deps` and gains `system` (the pinned
system row, read only) for group 3.

### 2.4 Document structure (`report_renderer/document.py`, `report_renderer/structure.py`, template)

- `document.render(snapshot, deps)`, in this order: `snapshot.validate` (problems: `InvalidSnapshot`); language not
  in `languages.catalogues()` gives `InvalidSnapshot([{"instance_id": None, "code": "invalid_snapshot", "pointer":
  "/language", "message": "is not an offered language"}])`; `structure_problems` likewise (`duplicate_appendix`);
  coverage links (C4, C8); logo; `fingerprint`; `context_for`; `_render_block` per block; `structure.plan`; CSS
  (C1); template; mode output. Every result carries `fingerprint`; `pdf` adds `pdf_base64`, `sha256`; `docx` comes in
  group 6.
- `_render_block`: title = `options.get("title") or ctx.t(cls.title)`; chapter and appendix blocks get
  `kind="chapter"` / `"appendix"`; `commentary` = `richtext.render(text)` when `text.strip()`, with
  `commentary_position`; the appendix always gets `page_break=True`.
- `report_renderer/structure.py` (new): `plan(sections, *, toc="auto", numbering=False) -> Plan(toc_entries,
  toc_after)`. It sets on each section `number` ("" when none), `depth` (1 inside a chapter), and builds the TOC tree
  (chapters with `children`). Numbering algorithm exactly R-V5.6 (main part 1, 2, ...; `c.1`; appendix A..Z, AA, AB,
  `A.1`); cover, appendix heading and TOC never numbered. TOC: `auto` = more than 3 sections (cover counted, as today),
  `on` = at least one entry, `off` = none; placed after the cover when there is one, else first.
- `report_renderer/templates/document.html.j2`: `<html lang="{{ language }}">`; section heading
  `<h2>{% if s.number %}{{ s.number }} {% endif %}{{ s.title }}</h2>` for blocks, `<h1 class="chapter-title">` for
  chapter and appendix sections (`class="block block-chapter chapter"` / `"block block-appendix appendix"`, id and
  data-status as today); commentary `<div class="commentary"><p class="commentary-caption">{{ t("Commentary") }}</p>
  {{ s.commentary }}</div>` after the block HTML, or between the notices and the block HTML for `before`, nothing
  when empty; TOC `<nav id="toc"><h2>{{ t("Contents") }}</h2><ol>...</ol></nav>` with `<li><a href="#block-...">
  {number} {title}</a></li>` and a nested `<ol>` only inside a chapter's `li`. With no chapter, no numbering and no
  commentary the bytes equal today's (goldens).
- `templates/css/toc_pages.css` (pdf and docx modes only): `#toc a::after { content: leader('.')
  target-counter(attr(href), page); }` and a right-aligned layout.
- `blocks/chapter.py` (new): `ChapterBlock` (`type_id "chapter"`, title "Chapter", contract 1, reads `()`,
  description "Groups the following blocks under one heading.", own `title` {string, minLength 1, maxLength 200,
  title "Chapter title", description}, `intro` {string, maxLength 5000, title "Introduction", description},
  `page_break_before` {boolean, title, description, x-aisc-more}, `required: ["title"]`, defaults
  `{"title": "Chapter", "intro": "", "page_break_before": True}`; render = richtext of intro, status ok) and
  `AppendixBlock` (`type_id "appendix"`, title "Appendix", contract 1, reads `()`, schema with no own property,
  defaults `{}`, description "Everything after it is the appendix."; render empty HTML, status ok). Both in
  `BUILTIN_BLOCKS` after `FreeTextBlock`. `templates/css/chapters.css` when either is present.

### 2.5 Header, footer, marking, document id

- `document._css(...)` becomes `page_css(project_name, number, *, report, t, mode)`: `@top-left` = `header_text`
  filled by `fill_placeholders(text, project, version, release, layout, date)` (only the five names; unknown names
  and lone braces kept), default `t("{project}, Version {version}")`; `@top-right` = the marking label upper-cased
  (`t("Confidential").upper()` and so on) with `color: {accent}` only when marking is not none; `@bottom-left` =
  `footer_text` when set; `@bottom-center` = the id line when `show_document_id` (`t("Document {id} | Fingerprint
  {fingerprint}")` with `id[:8]`, `fingerprint[:12]` in pdf/docx, `t("Preview, not a generated document")` in
  preview); `@bottom-right` = the translated "Page {page} of {pages}" split at `{page}` and `{pages}` into CSS strings
  around `counter(page)` and `counter(pages)`. Every string through `_css_string`. With the four fields at their
  defaults the string equals today's exactly (test_r_v5_16 and the styled goldens).
- `blocks/cover.py` and `cover.html.j2`: the marking label (translated, not upper-cased) in `<p class="marking">`
  right after the title/subtitle when not none (`templates/css/marking.css` then); author line per C7.

### 2.6 Commentary and free text

- `blocks/free_text.py`: option `format` `{"enum": ["plain", "markdown"], "title": "Format", "description": "Plain
  text or light formatting.", "x-aisc-enum-labels": {"plain": "Plain text", "markdown": "Light formatting"},
  "x-aisc-more": true}`, `default_options = {"format": "plain"}`, `new_instance_options = {"format": "markdown"}`,
  `contract_version = 2`; markdown renders `richtext.render(text)`, plain is today's code. `templates/css/
  commentary.css` when any section has a commentary.

### 2.7 Translation of the existing blocks

Every fixed text of `blocks/*.py`, `blocks/templates/*.j2`, `tools/templates/generic.html.j2`, `templates/*.j2`,
`_common.py` (`newer_notice`, `empty_result` callers) goes through `t` (C2). Numbers through `ctx.number` (C3);
`tools/generic.py::render_generic(measurements, limit=500, number=None)` (default keeps today's `:g`). Status words
and coverage statuses are translated where printed, never in attributes such as `data-coverage-count`.

### 2.8 Service and registry

- `report_service.py`: `GET /v1/languages` (`languages.languages()`); `/health` adds `interface_version`
  (`vera_report_plugin_interface.INTERFACE_VERSION`) and `languages` (list of `{code, name}`); `/v1/block-types`
  items add `description` and `new_instance_options`. The 422 body for `InvalidSnapshot` stays `{"problems": [...]}`.
- `report_renderer/registry.py::Registry.register_tool`: `getattr(cls, "contract_version", 1)` above 2 is skipped
  with the warning "tool renderer {origin} needs a newer report renderer" (not fatal); 1 and 2 load; duplicates still
  raise.

### 2.9 Tests that turn green in group 2

`tests/test_snapshot_v2.py` (17), `tests/test_document_structure.py` (14), `tests/test_header_footer.py` (15),
`tests/test_commentary.py` (13), `tests/test_i18n.py` (11), and in `tests/test_service_v2.py`:
`test_r_s_7_new_routes_follow_the_token_rule[get-/v1/languages-None]`, `test_r_s_7_health_gains_interface_version_and_languages`,
`test_r_s_7_block_types_gain_description_and_new_instance_options`, `test_r_s_5_contract_1_and_2_load_a_higher_one_is_skipped`.
`tests/test_compat_golden.py` (11) and every old test stay green. Expected: 237 - 74 = 163 failing (161 new + 2 known)
plus the test_registry cases of the three group-3 blocks.

Command: `cd ~/aisc-report-generator && uv run --extra dev pytest -q` (about 70 s); focused:
`uv run --extra dev pytest -q tests/test_compat_golden.py tests/test_snapshot_v2.py tests/test_document_structure.py
tests/test_header_footer.py tests/test_commentary.py tests/test_i18n.py tests/test_service_v2.py tests/test_registry.py`.

### 2.10 Commits (generator, dev)

1. The section 4 test update (message in section 4).
2. "Snapshot version 2: language, document settings, coverage links, header and footer fields, mode docx, and the
   fingerprint of every render" (snapshot.py, style.py, languages.py, i18n/*.json, context.py, service routes).
3. "Chapters, an appendix, section numbering and a table of contents with page numbers in the PDF" (structure.py,
   document.py, document.html.j2, blocks/chapter.py, blocks/__init__.py, css/chapters.css, css/toc_pages.css).
4. "Header and footer text, a confidentiality marking and the document id line from the template" (document.py,
   cover, css/marking.css).
5. "A commentary under every block and light formatting in free text" (document template, free_text.py,
   css/commentary.css).
6. "The report's fixed texts are translated, French first; data stays as written" (templates, blocks, generic.py,
   fr.json).
7. "Tool renderers declaring a newer contract are skipped with a warning" (registry.py).

---

## Group 3: the renderer's blocks and data (aisc-report-generator, dev)

### 3.1 Readable evaluations and the metric filter (V2.1 to V2.9)

- `report_renderer/data/engine.py`: `measurements()` also selects `m.description, m.error`; new
  `metric_choices(project_id, system_id, *, sources)` = distinct (tool display name, metric name) over every
  evaluation of the version (any status; the test pins 21 for Mike v2), sorted by tool then metric;
  `evaluation_choices` labels "{readable name} ({status}, {YYYY-MM-DD})". No `a.data` or storage column is ever
  selected from `engine.artifact` (guard test).
- `report_renderer/views.py`: `evaluation_names(ctx) -> dict[pid, (number, name)]` from `engine.evaluations()` (all
  statuses, order created_at, id) and `engine.runs(evaluation_ids=all)` (called through `ctx.data.engine`, so the
  monkeypatch test sees its fake); "Evaluation {k}: {tools}", after three names ", +{m} more", no run "Evaluation
  {k}". `load_runs(..., metrics="all")` filters each run's measurements to the chosen (tool, metric) pairs; `ToolRun`
  evaluation dict gains `name` and `number`; measurement dicts gain `description` and `error`.
- `blocks/test_results.py`: options `metrics` (`{"oneOf": [{"const": "all"}, {"type": "array", "items":
  {"type": "object", "required": ["tool", "metric"], "properties": {"tool": {"type": "string"}, "metric":
  {"type": "string"}}, "additionalProperties": false}}], "x-aisc-reference": true}`), `detail` (enum full, summary),
  `show_charts` (boolean); defaults `"all"`, `"full"`, `True`; `contract_version = 2`; `choice_options` adds
  `metrics`. Heading `<h3>` = readable name; meta line `Status: {status} | Date: {YYYY-MM-DD HH:MM} UTC | Reference:
  {pid[:8]}`; runs stay `<div class="run">`; a run left without measurements by the filter says "No selected metrics
  in this run." and gets no tool section; tool renderers receive `dataclasses.replace(ctx, tool_options=...)`.
  Choices `metrics` from `engine.metric_choices`.

### 3.2 Filters (V6.1 to V6.5)

- `report_renderer/objective_filters.py` (new): `requirement_groups(labels) -> list[str]` (distinct macro strings in
  objectives CSV order); `Filters(requirements, objectives, min_severity, include_unrated)` with `.active`,
  `.risk_passes(risk)`, `.objective_shown(oid, info, risks)`, `.notice(t)` giving "Filtered: {parts}.".
- `data/control_objectives.py::mappings` also selects `r.severity`.
- `blocks/control_objectives.py`: the five options of R-V6.1 (`requirements` all-or-list of strings, not a
  reference; `objectives` all-or-list, `x-aisc-reference`; `min_severity` D3-4; `include_unrated`; `show_severity`),
  `contract_version = 2`, `choice_options = ("requirements", "objectives")`; objective rows keep
  `data-objective`, risk rows keep `data-risk`; "Severity {n} of 5" / "Severity not rated" when `show_severity`;
  "No objective matches the filters of this section." with status ok.
- `blocks/summary_coverage.py`: option `requirements`, counts over shown objectives only, the Filtered notice,
  `contract_version = 2`, `choice_options` adds `requirements`; links rule C8.

### 3.3 Coverage map (U2)

- `blocks/control_objectives.py` and every consumer read `ctx.report.coverage_links` (C8).
- `report_service.py`: `POST /v1/coverage-choices` `{project_id, system_id}` answers `{objectives: [{value, label,
  group}], tests: [{value, label}], checklists: [{value, label}]}` (objectives from the version's assessment with
  label "{id} {label}" and group = macro, tests from `engine.tool_choices`, checklists from
  `controls.checklist_choices`); `NotInProject` gives 404 `not_found`, platform down gives 503 as `/v1/choices`.

### 3.4 Key figures (V6.8 to V6.11): `blocks/key_figures.py`, `templates/key_figures.html.j2`

`KeyFiguresBlock`, reads `("platform", "qualification", "control_objectives", "engine", "controls")`, options
`figures` (array of the six ids, `uniqueItems`, enum labels) and `show_tool_headlines` (more), description "The main
numbers of the version on one page.". `load` collects each selected figure separately and catches `SourceUnavailable`
per figure (tile "n/a (ref {ref})", block `error`). Tiles `<div class="figure" data-figure="{id}">` with label, value,
note; tool tiles `data-figure="tool"`, label "{tool}: {item label}", at most 2 per tool, from `renderer.headline(run)`
of the latest Done run of each tool with a contract-2 renderer. `empty` only when every selected figure is n/a; stale
by the maximum `newest_newer` over the sources read. `templates/css/key_figures.css` when present.

### 3.5 Chart (V4.6 to V4.12): `blocks/chart.py`, `templates/chart.html.j2`

`ChartBlock`, reads `("platform", "engine", "controls", "control_objectives")`, the options of R-V4.6 with
annotations and `x-aisc-show-if` on `tool_chart` (`{"dataset": ["tool_chart"]}`), `metric`
(`{"dataset": ["metric_by_evaluation", "metric_by_dimension"]}`) and `dimension` (`{"dataset": ["metric_by_dimension"]}`);
`tool_chart` and `metric` are objects with `x-aisc-reference`; `allOf` of three `if`/`then` making the dependent option
required (R-V4.16). `choice_options = ("tool_chart", "metric", "dimension")`: tool charts from every registered tool
renderer's `chart_ids` for tools with runs in the version (`registry.tool_renderers()`, a new read-only accessor
listing classes), metrics from `engine.metric_choices`, dimensions from the version's measurements' `dimensions` keys.
Datasets per R-V4.7 (coverage status via `coverage.coverage_for` and `coverage.STATUSES`; checklist means via
`views.load_answers`; tool chart via `renderer.charts(run)`; metric means per Done evaluation labelled "Evaluation
{k}"; groups by `dimensions[dimension]`, missing = "unknown"). Orientation R-V4.9, `max_bars` R-V4.10, table R-V4.11
(`<table>` of label and value formatted as the chart). Markup `<figure class="chart" data-kind="bar|hbar">{svg}
<figcaption>{title}</figcaption></figure>`; `charts.svg` gets the template's primary colour (platform default
`#000FDF`), `#000000`, `#CCCCCC` and the report's decimal separator and percent format. `ValueError` from a spec
becomes an error box. Stale per source R-V4.12. `templates/css/chart.css` when present.

### 3.6 Changes since (V7): `blocks/changes_since.py`, `templates/changes_since.html.j2`

- `context.ScopedData.for_version(pid) -> ScopedData`: checks with `platform_data.pinned_system(project, pid)` that
  pid is a version of the same project with a lower number, else raises `NotInProject`; returns a `ScopedData` bound
  to that version (same deps, `newer=()`).
- `ChangesSinceBlock`, reads all sources except superset, options `compare_to` (`{"type": "string", "minLength": 1,
  "x-aisc-reference": true}`, default "previous"), `sections` (array of card, objectives, tests, controls, enum
  labels), `show_unchanged` (more). `choices("compare_to")` = lower versions newest first, "Version {n} ({release})".
  It builds `base_ctx = dataclasses.replace(ctx, system=base.system, data=base, newer_versions=())` and reuses the
  same readers for both sides (card, components, qualification risks, mappings with severity, coverage through
  `coverage_for(base_ctx, ids, ctx.report.coverage_links)`, `load_runs` latest Done run per tool, `load_answers`).
  Parts `<section data-changes="card|objectives|tests|controls">`; neutral words only (no "better", "worse").
  `NotInProject` gives status error with "The version to compare with is not an earlier version of this project.";
  no earlier version gives empty "No earlier version to compare with."; never stale. Cut texts at 300 characters;
  at most 200 test rows then "and {k} more" (add unit tests on fake data for the DV2-5 corners: "No change.", the
  all-unchanged sentence, the 300-character cut, the 200-row cap, gaps in version numbers).

### 3.7 Help texts and more options (U5)

Every property of every built-in block type carries `title`, `description`, enum labels, and `x-aisc-more: true`
exactly as the MAIN/MORE table of `tests/test_service_v2.py` (the same as 01-specs.md R-U5.4); every built-in
declares a one-sentence `description`; `dashboard_chart.description` is exactly "Shows a Superset chart's comments and
data. For a chart drawn in the report, use the Chart block.". `BUILTIN_BLOCKS` order: the nine of today, then
`ChapterBlock`, `AppendixBlock`, `ChartBlock`, `KeyFiguresBlock`, `ChangesSinceBlock`. Contract versions per R-S.5.

### 3.8 Tests that turn green in group 3

`tests/test_blocks_v2_contracts.py` (10); `tests/test_v2_filters.py` (17); `tests/test_v2_coverage_map.py` (8);
`tests/test_v2_changes_since.py` (21); `tests/test_v2_key_figures.py` except `test_r_v6_9_tool_headline_tiles` (12);
`tests/test_v2_chart_block.py` except `test_r_v4_7_tool_chart_latest_run`, `test_r_v4_7_tool_chart_each_run`,
`test_r_v4_6_tool_chart_choices` (24); `tests/test_v2_test_results.py` except
`test_r_c_4_the_mijke_tools_have_dedicated_renderers` (15); in `tests/test_service_v2.py`
`test_r_s_7_new_routes_follow_the_token_rule[post-/v1/coverage-choices-...]`, `test_r_v4_14_...`,
`test_r_s_5_built_in_contract_versions`, the 28 `test_r_u5_1_*`/`test_r_u5_4_*` cases; the test_registry cases of the
new blocks. Goldens stay green. Remaining after group 3: the 5 package-dependent tests, `test_r_v2_25_*` x2,
`test_r_s_6_new_dependencies`, test_docx (14), test_e2e_v2 (1), and the 2 known failures.

### 3.9 Commits (generator, dev)

1. "Evaluations are named by number and tools, with date and reference; Test results can pick metrics and passes
   chart and detail options to tool renderers".
2. "Control objectives and Summary can be limited to requirement groups, objectives and a risk severity".
3. "One coverage map per report read by every coverage consumer, and its choices from the renderer".
4. "A key figures block for an executive summary".
5. "A chart block drawn by the renderer from the version's own data".
6. "A block that compares the report's version with an earlier one".
7. "Every built-in option has a label, a help text and its place under More options".

---

## Group 4: the three tool renderer packages, then wiring them into the renderer

Group 4 depends only on group 1 and may be done in parallel with groups 2 and 3; its wiring step (4.4) comes after
group 3 so the renderer suite is judged once.

### 4.1 Common shape (each of `~/aisc-report-langbite`, `~/aisc-report-strongreject`, `~/aisc-report-promptfoo`)

- `pyproject.toml`: keep what stage 2 wrote; add `[project.entry-points."aisc_report.tools"]` (`langbite =
  "vera_report_plugin_langbite:LANGBITEToolRenderer"`, `strongreject = "vera_report_plugin_strongreject:
  STRONGREJECTToolRenderer"`, `promptfoo = "vera_report_plugin_promptfoo:PROMPTFOOToolRenderer"`) and
  `[tool.setuptools.package-data] <module> = ["templates/*.j2", "i18n/*.json"]`. Dependencies stay
  `vera-report-plugin-interface` only (no SQLAlchemy, no psycopg).
- `<module>/__init__.py`: imports the class from `renderer.py`, `__all__`; nothing printed, nothing read.
- `<module>/parsing.py`: pure functions on the measurement names and descriptions of 01-specs.md 3.4 (regexes; a
  description that does not parse gives None fields, never an exception).
- `<module>/renderer.py`: the class, `contract_version = 2`, `chart_ids`, `render(run, ctx)`, `headline(run)`,
  `charts(run)`, `verdict(run)` returning None. Fixed texts `t("...")` with literal msgids (the French completeness test
  scans the AST and templates), `t = translator_for(ctx, __package__)`; numbers through `format_number` /
  `format_percent`; charts drawn with `charts.svg` inside the section only when `tool_options.show_charts` and the
  spec has at least one non-null value. Measurements matching no known name go to an "Other measurements" table
  (metric, value with `:g`, unit). Artifacts are never read or printed (the Test results block lists names and sizes).
- `<module>/templates/<tool>.html.j2` (autoescaped), `<module>/i18n/fr.json` holding every msgid.
- A run holding none of the tool's own measurements (Alpha's `bias_rate` LangBiTe runs) renders only the "Other
  measurements" table, without a summary line; it never raises.

### 4.2 Per tool

- LangBiTe (`LANGBITEToolRenderer`, `tool_names = ("LangBiTe",)`, `chart_ids = {"pass_rate_by_concern": "Pass rate by
  concern"}`): R-V2.11 to R-V2.15 (group = a name with exactly four " | "; table columns and order as the test; share
  as percent; tolerance from the description as percent, "n/a" when absent or unparsable; `detail="summary"` shows
  the summary line and the chart only; chart hbar, axis 0 to 1, concerns by name, value = mean of the concern's
  shares).
- StrongREJECT (`STRONGREJECTToolRenderer`, `tool_names = ("StrongREJECT",)`, `chart_ids =
  {"harmfulness_by_jailbreak": "Harmfulness by jailbreak"}`): R-V2.17 to R-V2.19 (success texts of R-V2.18 compared
  after `strip()` with `startswith`; not scored values print "not scored: {description}" and leave charts and headline;
  the notice "StrongREJECT did not produce scores in this run." when every summary is not scored; table none first
  then by name, 3 decimals, prompts from the description; chart `value_format` number, axis 0 to 1). No colour words
  or red/amber/green values anywhere in the HTML.
- promptfoo (`PROMPTFOOToolRenderer`, `tool_names = ("Promptfoo", "promptfoo")`, `chart_ids = {"rates": "Pass, fail
  and refusal rates"}`): R-V2.21 to R-V2.23 (one two-column table, label with the direction words taken from the unit,
  "not reported" for absent rates, the refusal note, "promptfoo wrote no results for this run." for an empty run;
  chart of the rates present, none when no rate).

### 4.3 Tests that turn green

Each package's whole suite: LB **28 passed**, SR **23 passed**, PF **21 passed**. Commands per package:
`uv lock && uv sync --extra dev --reinstall-package <distribution> && uv run --extra dev pytest -q`.

### 4.4 Wiring into the renderer (aisc-report-generator)

- `pyproject.toml` `dependencies` add `"python-docx>=1.1"`, `"cairosvg>=2.7"`, `"lxml>=5"`,
  `"vera-report-plugin-langbite"`, `"vera-report-plugin-strongreject"`, `"vera-report-plugin-promptfoo"`;
  `[tool.uv.sources]` add the three path sources `../aisc-report-langbite`, `../aisc-report-strongreject`,
  `../aisc-report-promptfoo` (editable). `uv lock && uv sync --extra dev`.
- `Dockerfile`: after the mlareject line add `COPY --from=langbite . /aisc-report-langbite`, `COPY --from=strongreject .
  /aisc-report-strongreject`, `COPY --from=promptfoo . /aisc-report-promptfoo`, and update the header comment listing
  the build contexts. `libcairo2` is already installed.
- Check again: `tests/test_compat_golden.py` (the Mike and Alpha goldens now meet the dedicated renderers: only the
  Test results section may change, the shell and CSS must not).
- Turns green: `tests/test_service_v2.py::test_r_v2_25_health_lists_the_three_tool_renderers`,
  `::test_r_v2_25_the_dockerfile_installs_them_from_build_contexts`, `::test_r_s_6_new_dependencies`;
  `tests/test_v2_test_results.py::test_r_c_4_the_mijke_tools_have_dedicated_renderers`;
  `tests/test_v2_key_figures.py::test_r_v6_9_tool_headline_tiles`; `tests/test_v2_chart_block.py::
  test_r_v4_7_tool_chart_latest_run`, `::test_r_v4_7_tool_chart_each_run`, `::test_r_v4_6_tool_chart_choices`.
  `test_i18n.py::test_r_v8_7_dates_stay_iso_numbers_use_the_decimal_comma` must stay green (Alpha's `0.125` is now in
  the LangBiTe "Other measurements" table, localised by `format_number`).

### 4.5 Commits

- Each package (dev): "The {tool} tool renderer: {one line of what it shows}, with its French catalogue and its entry
  point" (for example "The LangBiTe tool renderer: overall pass rate, one row per group with the tool's own tolerance
  check, and a pass rate chart, with its French catalogue and its entry point").
- Generator: "The renderer installs the LangBiTe, StrongREJECT and promptfoo tool renderers and the DOCX libraries".

---

## Group 5: the composer (aisc-install, `apps/report-composer`)

Start with the composer row of section 4 (own commit). The composer is tested against `tests/v2_fakes.py`; nothing
here needs the real renderer except the e2e (group 7).

### 5.1 Migration `migrations/0005_presets_and_document_settings.sql` (R-D.1, R-U2.4)

Additive only; one transaction (the runner wraps it). Statements, all on `report_composer.*`:
- `layout`: columns `language text NOT NULL DEFAULT 'en'` with check `layout_language_check`
  (`language ~ '^[a-z]{2}(-[A-Z]{2})?$'`), `toc text NOT NULL DEFAULT 'auto'` check `layout_toc_check` (auto, on, off),
  `numbering boolean NOT NULL DEFAULT false`, `coverage jsonb NOT NULL DEFAULT '[]'` check `layout_coverage_check`
  (`jsonb_typeof(coverage) = 'array'`).
- `template`: `header_text text` check `template_header_text_check` (`char_length(header_text) <= 120`),
  `footer_text text` (same, `template_footer_text_check`), `marking text NOT NULL DEFAULT 'none'` check
  `template_marking_check` (the five values), `show_document_id boolean NOT NULL DEFAULT false`.
- `generated_report`: `format text NOT NULL DEFAULT 'pdf'` check `generated_report_format_check` (pdf, docx),
  `fingerprint text`.
- new table `preset` as 01-specs.md 2.4 (`name` unique with check `char_length(name) BETWEEN 1 AND 120`,
  `language`/`toc`/`numbering` nullable with the same checks as the layout, `blocks jsonb NOT NULL` checked as an
  array, `source_project_id` references `core.project (pid) ON DELETE SET NULL`, `created_by text NOT NULL`,
  `created_at timestamptz NOT NULL DEFAULT now()`).
- the data move of R-U2.4 in two statements: set `layout.coverage` from the `options->'links'` of the lowest-position
  `summary_coverage` block with a non-empty `links` array, for layouts whose coverage is empty; then set that block's
  `links` to `[]`. Neither statement touches `revision` or `updated_at`.
Keep the words UPDATE, INSERT INTO, DELETE FROM, ALTER TABLE, CREATE TABLE, DROP and GRANT out of comments (the static
test reads every occurrence and wants a `report_composer.` table name after each).

### 5.2 Data layer and API shapes (`db.py`, `records.py`, `api.py`, `templates.py`, `reports.py`, renderer client)

- `db.py`: layout selects and writes `language`, `toc`, `numbering`, `coverage` (`list_layouts` adds `language`);
  `insert_layout` / `update_layout` take them; `copy_layout(conn, project_pid, layout_id, name, who, now)` for
  duplicate; template queries add the four fields (`_TEMPLATE`, `_look_values`); `insert_report` takes `format`;
  `finish_report` takes `fingerprint`; `list_reports` adds `format`, `fingerprint`, `sha256`; `get_report` adds
  `format`; preset queries `list_presets`, `get_preset`, `insert_preset`, `delete_preset`, `preset_names`.
- `records.chosen_template(conn, pid, template_id) -> str | None`: None allowed (R-U6.1); another project's id still
  422 `template_not_in_project`.
- `renderer_client.HttpRendererClient`: `languages()` GET `/v1/languages`; `coverage_choices(project_id, system_id)`
  POST `/v1/coverage-choices` with `{"project_id", "system_id"}` as strings.
- `renderer_calls.py`: `languages(request)` and `coverage_choices_for(request, project_pid, system_pid)` with the C10
  fallbacks.
- `report_composer/settings.py` (new): `document_settings(body, current, languages) -> dict` (absent key keeps the
  current value on PUT; unknown language 422 `unknown_language`; bad toc or numbering 422 `invalid_request`);
  `snapshot_document(layout, report_id)`.
- `report_composer/coverage_map.py` (new): `shape_problems(coverage)` (list, at most 200, objects with a string
  `objective_id`, list `tests`/`checklists` of strings, no duplicate objective: 422 `invalid_request`),
  `reference_problems(coverage, choices)` (pointers `/coverage/{i}/objective_id`, `/coverage/{i}/tests/{j}`,
  `/coverage/{i}/checklists/{j}`, `instance_id` None, code `invalid_reference`), `reset(coverage, choices)` (removes
  invalid values and entries left empty), `grid(coverage, choices) -> Grid(groups, columns, ticks, unavailable,
  linked, total, message)` for the page (Python computes everything; R-U1.1 to R-U1.3).
- `layouts.py`: C9; `_layout_problems` adds `duplicate_appendix`; `validate_layout(..., coverage=None,
  coverage_choices=None)` adds the map problems; `reset_invalid` also takes the map. `DEFAULT_ORDER` stays (the
  full-assessment preset equals it).
- `api.py`: `layout_view` adds `language`, `toc`, `numbering`, `coverage`; POST and PUT accept them (PUT: absent keeps);
  the save path validates blocks and map together and `reset_invalid` resets both; `template_id` may be null. Generate
  route reads an optional body `{"format": "pdf" | "docx"}` (anything else 422 `invalid_request`). New route
  `GET /api/p/{ref}/reports/{rid}/download` (viewer) serves either format with its media type and filename
  (`reports.document_filename(slug, number, layout, when, format)`, `.pdf` or `.docx`); `GET .../pdf` answers 404 for a
  DOCX row.
- `templates.py`: `checked()` validates the four fields (pointers `/header_text`, `/footer_text`, `/marking`,
  `/show_document_id`, code `invalid_template`); `view()` adds them; `style()` adds `header_text`/`footer_text` only
  when not null, `marking` only when not none, `show_document_id` only when true (so a default template sends
  today's style, R-V5.16); `EXPORT_VERSION = 2`, `export_doc` writes the four fields; `from_export` accepts version 1
  (fields default) and 2.
- `reports.py`: `snapshot_of(project, layout, mode, caller, template=None, *, document_id=None)` adds
  `snapshot_version: 2`, `language`, `document: {"id": document_id, "toc", "numbering"}`, `coverage_links` (always);
  `_start` no longer requires a template (no `style` when None) and inserts the row first, so `document.id` is the
  report id; `generate(..., fmt)` asks mode `fmt`, reads `pdf_base64` or `docx_base64`, stores bytes in the `pdf`
  column with `format` and `fingerprint`; the size message becomes "The document is larger than 25 MB and was not
  stored" (code `pdf_too_large` kept).

Tests green after 5.1 and 5.2: `tests/test_v2_migration.py` (15), `tests/test_v2_layout_settings.py` (24), `tests/test_v2_templates.py` except `test_r_v5_17_the_template_form_has_the_new_fields` (14),
`tests/test_v2_reports.py` except `test_r_v8_15_the_editor_page_lists_the_format` and
`test_r_v5_15_the_editor_shows_the_fingerprint_next_to_the_sha256` (11), `tests/test_v2_renderer_client_unit.py` (2),
and the section 4 composer rows.

### 5.3 Presets (V1): `report_composer/presets.py`, `report_composer/presets/*.json`

- The four JSON files (`full-assessment.json`, `eu-ai-act.json`, `internal-audit.json`, `executive-summary.json`),
  each `{"format": "aisc-report-preset", "version": 1, "id", "name", "description", "language", "toc", "numbering",
  "blocks": [{"block_type", "options"}]}`: sequences, chapter titles, free text titles and placeholders ("Write this
  section.", `format: "markdown"`), `show_severity`, `show_uncovered_only`, `dataset` and document settings exactly as
  `tests/test_v2_presets.py` pins. `full-assessment` has empty options (defaults are merged on creation, so it equals
  today's default layout). Packaged with the app (the composer Dockerfile copies the package folder; check it).
- `presets.py`: `BUILT_IN_ORDER`; `built_in()`; `from_file(doc, block_types) -> Preset` (R-V1.10: `not_a_preset`,
  at most 50 blocks, options checked with references ignored, pointer `/blocks/{i}{option pointer}`,
  `unknown_block_type` listing every unknown type in `details`, `duplicate_cover` through `layouts._layout_problems`);
  `blocks_for_layout(preset, block_types) -> list` (new instance ids, `{**default_options, **preset options}` with
  reference options reset to their type default or removed, R-V1.4); `from_layout(layout, block_types, keep_text)`
  (R-V1.7, R-V1.9: free text becomes "Write this section.", commentary "", cover title and subtitle kept, references
  stripped, coverage not exported); `export_doc(preset)`; `free_name` reused from `templates.free_name`;
  `copy_name(name, taken)` giving "{name} (copy)", "{name} (copy 2)" (at most 120 characters).
- `api.py` routes: `POST /api/p/{ref}/layouts` accepts `preset` (built-in id, saved uuid or "empty") or `preset_file`,
  at most one of `preset`, `preset_file`, `blocks` (else 422 `invalid_request`), unknown 422 `unknown_preset`,
  validation with `allow_missing_references=True`, a preset language no longer offered becomes `en` and the response
  carries `details` naming it; the name comes from the body, else the file (with " (2)"). `POST
  /api/p/{ref}/layouts/{id}/duplicate` (editor), `GET /api/p/{ref}/layouts/{id}/export?keep_text=false` (viewer,
  attachment `report-preset-{slug}.json`), `POST /api/p/{ref}/layouts/{id}/preset` (editor; name 1 to 120 else 422
  `invalid_request`, taken 422 `name_taken`), `GET /api/presets`, `POST /api/presets/import`, `GET
  /api/presets/{id}/export`, `DELETE /api/presets/{id}` (creator or realm role `admin`, else 403; built-in 403). The
  non-project routes use `signed_in` plus the same-origin check for writes.

Tests green: `tests/test_v2_presets.py` (45).

### 5.4 Forms and pages (U1, U4 to U7, V3.13 to V3.15, V4.15, V5.8, V5.9, V8.13, V8.14)

- `forms.py::form_fields(schema, values, choices)`: field keys add `help` (description), `more` (bool),
  `show_if` (dict or None), `hidden` (bool: the named option's current value is not listed), `filter` (bool, more than
  10 choices); `label` = `title` when present, else today's generated label; enum options labelled from
  `x-aisc-enum-labels`; widgets `all-or-list` (radios "All (also ones added later)" / "Only these:" then checkboxes,
  options from choices or the items enum), `checkboxes` (array of enum), `commentary` (the `commentary` property,
  never more), `select` for single data choices, D3-4 for nullable integers; `multiselect` and `links` are gone
  (legacy links: read-only list plus the switch, R-U2.6). Order: main fields in schema order, then more fields.
  A plugin block without annotations keeps today's labels, all main (R-U5.5).
- `pages.py`: palette entries add `description` and use `{**default_options, **new_instance_options}`; outline entries
  add `depth` (computed from the order: 1 after a chapter until the next chapter or appendix) and the hint "This
  chapter is empty."; the stored problems of a block (a stored empty list: "Pick at least one, or choose All.") are
  printed in its `data-problems`; the coverage grid from `coverage_map.grid` (viewer: disabled); languages for the
  select; presets for the layouts page (built-in, saved with `may_delete` per caller); reports list with format,
  fingerprint and the download link.
- Templates: `base.html.j2` gets two macros used first in every page's `<main>`: `message_region()` (`<div
  data-message role="alert" aria-live="polite" hidden></div>` with a close button filled by the script) and
  `confirm_dialog()` (D3-5; editors only). `_form.html.j2`: `details[data-more]` "More options" (closed) at the end of
  each block form, `details[data-commentary]` "Add a commentary" (open when non-empty) holding `<textarea
  data-option="commentary" rows="6">` and the help line of R-V3.15; fields with `data-show-if` (JSON) and `hidden`;
  all-or-list and checkbox markup with `data-field`, `data-option`, `data-kind`. `editor.html.j2`: language select
  `select[data-control=language]`, template select first option "Platform default" (value ""), buttons
  `[data-control=generate]` "Generate PDF" and `[data-control=generate-docx]` "Generate Word (DOCX)", preview label
  `[data-preview-label]` "Preview of revision {n}", `[data-control=refresh-preview]` "Refresh preview",
  `input[data-control=auto-refresh]` (checked) labelled "Auto-refresh", `li[data-depth]`, the palette descriptions,
  `details[data-coverage-map]` with summary "Coverage map: {m} of {n} objectives linked" and checkboxes
  `data-objective`/`data-kind`/`data-value`, reports list with "PDF"/"DOCX", the first 12 characters of the fingerprint
  next to the SHA-256 and `/download` links. `layouts.html.j2`: `select[name=preset]` (built-ins, saved, "Empty
  layout" with value "empty"), `[data-control=import-preset]`, row controls `duplicate`, `export-structure`,
  `save-preset`, `delete` (viewers: `export-structure` only), a presets section with `export-preset` and
  `delete-preset` (creator or admin), Create never disabled, template select starting with "Platform default"
  preselected when the project has no template, the hint "Reports use the platform look until you make a template.".
  `templates.html.j2`: header text, footer text (with the placeholder help line naming `{project}`, `{version}`,
  `{release}`, `{layout}`, `{date}`), marking select (None, Public, Internal, Confidential, Strictly confidential),
  `details` "More options" with "Print the document id and fingerprint".
- `static/composer.css`: sticky first column of the coverage table (`position: sticky`), grid, dialog, message region.

Tests green: `tests/test_v2_forms_unit.py` (12), `tests/test_v2_pages.py` except its six script checks that need
5.5 (`test_r_u4_3_composer_js_says_pick_at_least_one`, `test_r_v4_15_composer_js_toggles_from_the_annotation_and_skips_hidden_fields`,
`test_r_u1_1_python_computes_the_grid_and_js_only_collects`, `test_r_u7_1_*`, `test_r_u7_3_composer_js_uses_the_dialog`,
`test_r_u7_4_*`), `test_v2_templates.py::test_r_v5_17_*`, `test_v2_reports.py` editor-page tests (2).

### 5.5 Draft preview and the script (U3, U7)

- `api.py`: `POST /api/p/{ref}/layouts/{id}/preview` (editor, same-origin), an `async` route that reads
  `await request.body()`: over 1 MB (1 048 576 bytes) 413 `too_large`; JSON body `{system_id, template_id, language,
  toc, numbering, coverage, blocks}`; version and template checks as on save (422); problems from `validate_layout`
  plus the map (returned, never blocking); snapshot mode preview with the draft; renderer failures 502/504 through
  `renderer_call`; answer `{html, problems, block_statuses}` where `html` has `<meta http-equiv="Content-Security-Policy"
  content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">` inserted as the first child of `<head>`
  (`reports.with_csp_meta(html)`). Nothing is stored.
- `static/composer.js` (under 500 lines, no `alert(`, `confirm(`, `prompt(`): collects the editor state (options by
  `data-option`/`data-kind`, all-or-list radios and checkboxes, skipping `hidden` fields, commentary, the coverage ticks
  from `details[data-coverage-map]`, language, template, version); debounced draft preview (1500 ms, one request in
  flight, one queued, older answers ignored, `srcdoc` into the sandboxed iframe, label "Preview of unsaved changes" /
  "Preview of revision {n}", inline error); Refresh button; Auto-refresh remembered in `localStorage` inside
  `try { } catch`; show-if toggling from `data-show-if`; "Pick at least one, or choose All." inline; generate PDF or
  DOCX with the `what === "generate"` branch downloading `"/download"`; presets actions (duplicate, export, save as
  preset with name and "Keep texts", import, delete); the confirm dialog with `showModal()` and `data-confirm-text`;
  messages into `div[data-message]`; `beforeunload` while unsaved. The JS never computes validity, coverage or labels.

Tests green: `tests/test_v2_draft_preview.py` (16) and the remaining `tests/test_v2_pages.py` cases. After 5.5 the
composer suite is **321 passed, 9 failed** (the 8 known failures and `tests/test_e2e_v2.py`, which waits for
group 7).

### 5.6 Commands and commits (aisc-install, feat/unified-modules)

```
cd ~/aisc-install/apps/report-composer && uv run --extra dev pytest -q          # about 150 s
cd ~/aisc-install && scripts/guard-frozen.sh                                     # the 00-baseline lines
git status --short                                                               # only own files staged
```
Commits (explicit paths under `apps/report-composer/`): 0. the section 4 composer test update; 1. "Migration 0005:
layout language, document settings and coverage map, template header, footer and marking, report format and
fingerprint, and saved presets"; 2. "Layouts carry a language, document settings and one coverage map, may use the
platform look, and are generated as PDF or Word"; 3. "Report structures start from presets, can be duplicated,
exported and saved as presets for every project"; 4. "Block forms show labels, help, More options, checkbox lists and
a commentary; the editor draws the coverage map as a grid"; 5. "The preview shows unsaved changes, and messages and
confirmations stay on the page".

---

## Group 6: DOCX export and the French review (aisc-report-generator, dev)

### 6.1 `report_renderer/docx.py` (new)

`html_to_docx(html, *, title, subject, language, look, header, footer, page_label) -> bytes`. It parses the
document HTML (built in `docx` mode, C7) with `lxml.html`, walks the body in order and writes a `docx.Document()`:
- Styles: `Normal` font = the first family of the template's font stack (quotes stripped), size = `font_size_pt`;
  `Heading 1..4` colour = primary colour (platform default when no style).
- Mapping of R-V8.9: cover `h1` to `Title`; `h1.chapter-title` to `Heading 1`; section `h2` to `Heading 2`; `h3`/`h4`
  to `Heading 3`/`4`; `p` to `Normal`; `strong`/`b`, `em`/`i`, `code` to bold, italic, monospace runs (Courier New);
  `a` to a `w:hyperlink` with an external relationship; `ul`/`ol` to `List Bullet`/`List Number` (levels 2 and 3 use the
  numbered style variants); `table` to a Word table whose first row repeats (`w:tblHeader`) and is bold; `dl` to a
  borderless two-column table; `img` with a `data:` PNG or JPEG to a picture at most 16 cm wide; inline `svg` to a PNG
  with `cairosvg.svg2png(..., scale=2)` then a picture, and when that fails the chart's data table stays and the
  italic notice "Chart shown as a table." is added; `ul.notices` items to italic paragraphs; `.error-box`,
  `.banner`, `.commentary` to paragraphs with shading (`w:shd`) or a border (`w:pBdr`); `style="break-before: page"`
  to `pageBreakBefore` on the next paragraph; the TOC `nav` to a `TOC \o "1-2" \h` field whose cached result lists
  the entries (no page numbers); any other element contributes its text.
- Section header: the header text and the marking label (upper case); footer: the footer text, the id line when set,
  and "Page {page} of {pages}" (translated) with `PAGE` and `NUMPAGES` fields.
- `word/settings.xml` gets `<w:updateFields w:val="true"/>`; core properties: title = layout name, subject = project
  name, language = report language, author and last_modified_by empty.
- `document.render` in `docx` mode returns `{"docx_base64", "sha256", "fingerprint", "block_statuses"}`.

### 6.2 French review

Read `fr.json` end to end (renderer and packages): every msgid present (`test_r_v8_4` in each repo), plain French, no
em dashes, no word "catalogue" in the renderer's file (rule 6). Q9 stays open for the user.

### 6.3 Tests that turn green

`tests/test_docx.py` (14) and `tests/test_e2e_v2.py` (1). The generator suite is then **501 passed, 2 failed** (the two
known failures only).

### 6.4 Commit

"Reports can be generated as Word documents with the PDF's structure, header, footer and table of contents".

---

## Group 7: end to end and the verification at the end of stage 4

1. `env | grep -iE 'DATABASE|DSN|DB_URL'` prints nothing; no `aisc-t-*` container before or after.
2. Every suite, with the expected result:
   ```
   cd ~/aisc-report-plugin-interface && uv run --extra dev pytest -q     # 121 passed
   cd ~/aisc-report-langbite         && uv run --extra dev pytest -q     # 28 passed
   cd ~/aisc-report-strongreject     && uv run --extra dev pytest -q     # 23 passed
   cd ~/aisc-report-promptfoo        && uv run --extra dev pytest -q     # 21 passed
   cd ~/aisc-report-mlareject        && uv run --extra dev pytest -q     # 19 passed
   cd ~/aisc-report-generator        && uv run --extra dev pytest -q     # 501 passed, 2 failed (test_r2_2_2_tags,
                                                                          #   test_r5_4_1_no_token_no_answer[get-/v1/block-types])
   cd ~/aisc-install/apps/report-composer && uv run --extra dev pytest -q  # 322 passed, 8 failed (test_api_access x4,
                                                                          #   test_api_reports x4: the known helper defects)
   cd ~/aisc-install && uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider \
       scripts/tests/test_report_stack.py scripts/tests/test_report_grants.py   # 75 passed, 7 failed (unchanged)
   ```
   (The totals grow by the unit tests stage 4 adds for DV2-5; report them.)
3. Both end-to-end tests, explicitly, and the old ones:
   `cd ~/aisc-report-generator && uv run --extra dev pytest -q tests/test_e2e_v2.py tests/test_e2e.py` and
   `cd ~/aisc-install/apps/report-composer && uv run --extra dev pytest -q tests/test_e2e_v2.py tests/test_e2e.py`
   (the composer ones start the real renderer with `uv run --extra dev uvicorn report_service:app` in the generator
   repo on a free port).
4. `cd ~/aisc-install && scripts/guard-frozen.sh`: the output lines equal 00-baseline.md (G1 FAIL with 238 lines, G2
   PASS, G3 PASS twice, the three G4 FAIL lines, G5 PASS, GUARD FAIL). Compare with `diff` against the lines copied
   from 00-baseline.md, ignoring only the temporary paths.
5. Optional image smoke (allowed by RULES; nothing of the stack is rebuilt or retagged):
   ```
   docker build --build-context interface=$HOME/aisc-report-plugin-interface --build-context mlareject=$HOME/aisc-report-mlareject \
     --build-context langbite=$HOME/aisc-report-langbite --build-context strongreject=$HOME/aisc-report-strongreject \
     --build-context promptfoo=$HOME/aisc-report-promptfoo -t aisc-report-renderer:report-v2-test ~/aisc-report-generator
   docker run --rm --entrypoint python aisc-report-renderer:report-v2-test -c "import report_service, docx, cairosvg, \
     vera_report_plugin_langbite, vera_report_plugin_strongreject, vera_report_plugin_promptfoo"
   docker build -t aisc-report-composer:report-v2-test ~/aisc-install/apps/report-composer
   docker rmi aisc-report-renderer:report-v2-test aisc-report-composer:report-v2-test
   ```
6. Manual, browser only (not automated; list them in 04-code-report.md): R-U3.4 debounce, single flight and ignored
   stale answers; R-U3.5 inline error keeping the last preview; R-U7.3 Esc and focus order; R-V4.15 hidden fields not
   sent; R-U1.3 reset question flow; R-V3.13 disclosure toggling.
7. Clean state: `git status --short` in each repo shows only other people's files and caches; `git log --oneline`
   lists this plan's commits; nothing pushed; `docker ps -a --filter name=aisc-t-` empty.
8. Write 04-code-report.md (counts per suite, guard lines, commit shas, by-design test changes, deviations) and a
   PROGRESS.md row.

## 8. Questions for the user

- The ten questions of 01-specs.md section 20 and Q2-1 of 02-tests.md are still open; this plan follows their
  defaults.
- Q3-1 Deploy note (D3-11): before the next deploy, the renderer service in the compose file needs the build contexts
  `langbite`, `strongreject`, `promptfoo` (as `interface` and `mlareject` today). `DEFAULT (user to confirm)`: not
  changed in this run (A4); stage 5 lists it for the user.
- Q3-2 composer.js may grow to under 500 lines (section 4). `DEFAULT (user to confirm)`: accepted; all decisions stay
  in Python.
