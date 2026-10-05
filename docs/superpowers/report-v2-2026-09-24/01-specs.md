# Stage 1: Specs for report run v2 (more versatile, still easy)

Status: stage 1 of 5. Binding inputs: `RULES.md`, `BRIEF.md`, `00-baseline.md` in this folder. The decisions of
the run of 2026-09-23 (`../report-2026-09-23/01-specs.md` as amended by `02-architecture.md` D1 to D16, O1, O2)
still hold unless this file changes them. Pass/fail thresholds on test measurements are OUT of scope (BRIEF).

Every requirement has an id `R-<item>.<n>` and is phrased so that a test can check it. Where a requirement lands
is given in brackets:
- **[RG]** renderer, `/home/listuser/aisc-report-generator` (`report_renderer/...`, `report_service.py`)
- **[IF]** contracts, `/home/listuser/aisc-report-plugin-interface` (`vera_report_plugin_interface/...`)
- **[RC]** composer, `/home/listuser/aisc-install/apps/report-composer` (`report_composer/...`, `migrations/`,
  `templates/`, `static/composer.js`)
- **[LB] [SR] [PF]** new local tool renderer packages `/home/listuser/aisc-report-langbite`,
  `/home/listuser/aisc-report-strongreject`, `/home/listuser/aisc-report-promptfoo` (each a local git repo on
  branch `dev`, modelled on `aisc-report-mlareject`)

Decisions that only the user can confirm are marked `DEFAULT (user to confirm)` and collected in section 20.

## 0. Facts the specs rely on (checked in the code and the live DB on 2026-09-24, read only)

- Live composer data: 1 layout (the 7 default blocks, default options), 1 template ("ai factory template"),
  4 generated reports. Live engine: plugins LangBiTe (`LangBiteEvaluationPlugin`, `aisc-plugin-langbite` 0.1.1)
  and StrongREJECT (`StrongRejectPlugin`, `aisc-plugin-strongreject` 0.1.0); **0 evaluations, 0 measurements,
  0 metrics**. promptfoo is not installed on the live stack. So the tool renderers of V2 are specified from the
  plugin sources (section 3.4), not from live rows.
- `engine.evaluation` has no name column (id, pid, status, task, project_id, system_id, created_at).
- `engine.measurement`: name, description (varchar 255), unit, time, score (float, not null), error,
  uncertainty (float, not null), dimensions (jsonb), direction (varchar 50), metric_id, observation_id.
- `control_objectives.risk.severity` is an integer 1 (marginal) to 5 (decisive), null when not rated
  (control-objectives treats null as 3 for ordering, `prioritising.py`). `qualification.qualification_risk`
  has no severity.
- The objectives catalogue CSV has 50 objectives in 11 requirement groups (`Macro_Requirement`, e.g.
  "R9 Risk Management"); the renderer already reads it as `{macro, legal_basis, label, objective}`.
- The layout is a flat ordered list (`report_composer.layout_block`); templates are looks, one project each
  (migration 0002). Snapshots are stored per generated report (`generated_report.snapshot`, jsonb).
- `libcairo2` is already installed in the renderer image (WeasyPrint needs it).

## 1. Compatibility (applies to every item)

R-C.1 [RG] When the renderer receives a snapshot that has none of the keys added by this run
(`snapshot_version`, `language`, `document`, `coverage_links`, and the new `style` fields), then it renders it
exactly as the renderer at `26e235d` does, byte for byte in `mode=preview`, apart from the intended changes
listed in R-C.4.
R-C.2 [RG] Stage 2 captures golden HTML files from the renderer at `26e235d` before any code changes: the
live default layout (7 blocks, default options) with and without a `style`, on the throwaway bed's seed data,
for a version that has no evaluations (so R-C.4 changes do not apply) and for one with evaluations. The first
must stay identical; the second may differ only in the places R-C.4 names.
R-C.3 [RC] When the composer's migrations of this run have run on a database holding layouts, templates and
reports made before the run, then each layout previews with the same HTML as before (same condition as
R-C.2), every template keeps its look, and every stored report is still downloadable unchanged.
R-C.4 Intended output changes for existing layouts (the only allowed differences):
1. Test results: an evaluation is headed by its readable name (R-V2.1) instead of "Evaluation {pid[:8]}".
2. Test results: runs of LangBiTe, StrongREJECT and promptfoo are drawn by their dedicated renderers
   (R-V2.10 onwards) instead of the generic table, and the notice "No dedicated renderer for {tool}..." goes
   for those tools.
3. PDF only: table of contents entries carry page numbers (R-V5.2). The HTML preview is unchanged.
4. A layout with two or more `summary_coverage` blocks where a later one has empty `links`: that block now
   shows the layout's coverage map instead of "not covered" everywhere (the U2 fix, R-U2.3). No live layout
   has this (the only live layout has one summary block).
R-C.5 [IF] A block renderer or tool renderer written against the interface of 2026-09-23 (block
`contract_version` 1, tool renderer without `contract_version`) keeps loading and rendering unchanged.
R-C.6 Every new option, setting and column defaults to today's behaviour; the default of each is stated
where it is introduced.

## 2. V1: reusable report structure (presets, duplicate, export/import)

### 2.1 Vocabulary
- **Preset**: a report structure with no project data: an ordered list of `{block_type, options}` plus the
  document settings `language`, `toc`, `numbering` (sections 6.1 and 9.1). No instance ids, no data references, no
  coverage map.
- **Built-in preset**: a preset shipped as a JSON file in the composer (`report_composer/presets/*.json`),
  read only, visible to every signed-in user.
- **Saved preset**: a preset stored in table `report_composer.preset`, visible to every signed-in user of the
  platform (as the old platform-wide templates of R3.16).

### 2.2 Requirements
R-V1.1 [RC] The composer ships four built-in presets, listed in this order:
1. `full-assessment` "Full assessment": exactly today's `DEFAULT_ORDER` (cover, ai_card, risk_classification,
   control_objectives, test_results, control_answers, summary_coverage) with default options, `toc=auto`,
   `numbering=false`, `language=en`.
2. `eu-ai-act` "EU AI Act conformity": cover; key_figures; chapter "System and risks" (ai_card,
   risk_classification); chapter "Control objectives" (control_objectives with `show_severity=true`,
   summary_coverage); chapter "Evidence" (test_results, control_answers); appendix; free_text titled "Method"
   with a placeholder text. `numbering=true`, `toc=on`.
3. `internal-audit` "Internal audit": cover; free_text "Scope" (placeholder); key_figures; control_answers;
   test_results; summary_coverage with `show_uncovered_only=true`; free_text "Findings" (placeholder).
   `numbering=true`, `toc=on`.
4. `executive-summary` "Executive summary": cover; key_figures; chart with `dataset=coverage_status`;
   summary_coverage with `show_uncovered_only=true`; changes_since (default options). `toc=off`.
The exact option values live in the JSON files; stage 2 tests assert the block type sequence above.
R-V1.2 [RC] When a layout is created with `preset` absent and `blocks` absent, then it gets the
`full-assessment` preset, which equals today's default block list (R3.3 unchanged).
R-V1.3 [RC] `POST /api/p/{ref}/layouts` accepts `preset` = a built-in preset id (string) or a saved preset
uuid, or `preset_file` = the content of a preset file (R-V1.7). When given, then the layout's blocks are the
preset's blocks with new instance ids, and its document settings are the preset's. When the preset does not
exist, then 422 `unknown_preset`; a bad file is refused as in R-V1.10. `preset: "empty"` gives a layout with
no blocks. At most one of `preset`, `preset_file`, `blocks` may be given (else 422 `invalid_request`).
R-V1.4 [RC] When a layout is created from a preset, then options marked `x-aisc-reference` are set to their
type default (or left out when the type has none), and validation runs with `allow_missing_references=True`
(the existing parameter of `validate_layout`): a block whose required reference is missing (for example a
`dashboard_chart` without `chart_id`) is created and shows the problem "Choose a value" in the editor;
Generate is refused with 422 `invalid_options` until it is set.
R-V1.5 [RC] When a preset names a block type the renderer does not offer, then creating a layout from it
fails with 422 `unknown_block_type` listing every such type in `details`.
R-V1.6 [RC] `POST /api/p/{ref}/layouts/{id}/duplicate` (editor) with `{name?}` creates a copy in the same
project: same version, template, language, document settings, coverage map (section 13) and block options;
new layout id and new instance ids; `revision=1`; no generated reports. Default name "{name} (copy)", then
"{name} (copy 2)" and so on until free (max 120 characters). 201 with the new layout.
R-V1.7 [RC] `GET /api/p/{ref}/layouts/{id}/export?keep_text=false` (viewer) returns a preset file
(attachment `report-preset-{layout name slugified}.json`): `{"format": "aisc-report-preset", "version": 1, "name", "description",
"language", "toc", "numbering", "blocks": [{"block_type", "options"}]}`. References are stripped as in R-V1.4;
the coverage map is not exported; texts follow R-V1.9.
R-V1.8 [RC] `POST /api/p/{ref}/layouts/{id}/preset` (editor of that project) with `{name, description?,
keep_text?}` saves the layout's structure as a saved preset (`source_project_id` = the project); `POST /api/presets/import` (signed in) with a preset file saves it as a saved preset;
`GET /api/presets` lists built-in then saved presets `{id, name, description, built_in, block_types}`;
`GET /api/presets/{id}/export` downloads one; `DELETE /api/presets/{id}` is allowed to its creator and to the
realm role `admin` (else 403); built-in presets cannot be deleted (403).
R-V1.9 [RC] When a preset is made from a layout (R-V1.7, R-V1.8) with `keep_text` false (the default), then
every `free_text.text` becomes the placeholder "Write this section." and every `commentary` becomes empty;
with `keep_text: true` both are kept. Cover title and subtitle are always kept.
R-V1.10 [RC] When a preset file is imported, then it must have `format` "aisc-report-preset" and `version` 1
(else 422 `not_a_preset`), at most 50 blocks, and each block's options must validate against its type's
schema with references ignored (else 422 `invalid_options` with the block index as pointer). Unknown block
types: 422 `unknown_block_type` (R-V1.5). A name already taken gets " (2)", " (3)" (as template import).
R-V1.11 [RC] Saved preset names are unique platform-wide (1 to 120 characters); 422 `name_taken` otherwise.
R-V1.12 [RC] A layout made from a preset keeps no link to it: later changes or deletion of the preset do not
change the layout.

### 2.3 Composer screens
- Layouts list: the "New layout" form gets a **Start from** select: built-in presets first ("Full assessment"
  preselected), then saved presets, then "Empty layout". Below it, a small "Import a preset file" link, which
  creates a layout of this project from the file (`preset_file`, R-V1.3; the name comes from the file and gets
  " (2)" when taken). This is how a structure moves to another project or platform.
- Each layout row gets a "More" menu: Duplicate, Export structure, Save as preset (asks name and a "Keep
  texts" checkbox, unchecked), Delete. Viewers see Export structure only.
- A "Presets" section at the bottom of the layouts page lists saved presets with Export and (creator/admin)
  Delete.

### 2.4 Data model
Migration `0005_presets_and_document_settings.sql` [RC] (see section 17 for the full list):
`report_composer.preset (id uuid pk, name text unique 1..120, description text default '', language text
null, toc text null, numbering boolean null, blocks jsonb not null, source_project_id uuid null references
core.project on delete set null, created_by text not null, created_at timestamptz default now())`.

### 2.5 Edge cases
- A preset with zero blocks is valid; the layout starts empty (Generate is refused as today, `empty_layout`).
- A preset holding a `cover` twice or more than 10 `dashboard_chart` blocks: 422 as R3.7.
- Presets hold `language`; when the renderer no longer offers that language, the layout gets `en` and the
  create response carries a notice in `details`.

## 3. V2: readable test results and dedicated tool renderers

### 3.1 Readable evaluation names (all tools)
R-V2.1 [RG] The readable name of an evaluation is "Evaluation {k}: {tools}", where `k` is its position (1, 2,
...) among **all** evaluations of the pinned version ordered by `created_at`, then `id` (whatever the block's
filters, so a name is the same in every layout), and `{tools}` is the list of distinct tool display names of
its plugin runs in run order, joined by ", "; after three names, ", +{m} more". An evaluation with no run is
"Evaluation {k}". Example: "Evaluation 2: LangBiTe, StrongREJECT".
R-V2.2 [RG] Under the heading, the meta line reads "Status: {status} | Date: {YYYY-MM-DD HH:MM} UTC |
Reference: {pid[:8]}" (the reference keeps the old short id findable).
R-V2.3 [RG] The `evaluations` choices (R1.13) are labelled "{readable name} ({status}, {YYYY-MM-DD})",
values unchanged (pids).
R-V2.4 [RG][IF] `ToolRun.evaluation` gains the keys `name` (the readable name) and `number` (k); existing keys
unchanged. Each measurement dict in `ToolRun.measurements` gains `description` and `error` (read from
`engine.measurement`; the SELECT in `data/engine.py measurements()` adds both columns).

### 3.2 Metric filter (see also V6)
R-V2.5 [RG] Test results gets option `metrics`: `"all"` (default) or a list of `{tool, metric}` pairs
(`x-aisc-reference`). When a list is given, then only measurements whose run's tool display name and
measurement metric name match a pair are passed to the tool renderer and the generic table. Choices
`metrics`: every distinct (tool display name, metric name) of the pinned version's measurements, value
`{"tool": ..., "metric": ...}`, label "{tool}: {metric}", sorted by tool then metric.
R-V2.6 [RG] When a filter leaves a run with no measurement, then the run is still listed (heading, components,
status) with "No selected metrics in this run." and no tool section.

### 3.3 Tool renderer contract additions [IF]
R-V2.7 `BaseToolRenderer` gains `contract_version: int = 1` (class attribute; renderers of the new packages
declare 2), and three optional methods with defaults: `headline(run) -> list[dict]` (default `[]`): at most 4
`{label, value, note?}` items of plain text naming the run's main numbers, used by key_figures (V6) and
changes_since (V7); `charts(run) -> list[dict]` (default `[]`): chart specs of R-V4.3, used by the chart block
(V4); and `chart_ids: dict[str, str] = {}` (class attribute: chart id to English label) naming what `charts()`
can return. `verdict()` stays and the three new renderers return `None` from it (no pass/fail, BRIEF).
R-V2.8 The renderer reads tool options from `getattr(ctx, "tool_options", {})`: `show_charts` (bool) and
`detail` (`"full"` or `"summary"`). Test results sets them from its options `show_charts` (default true) and
`detail` (default `"full"`). A contract-1 renderer that ignores them keeps working.
R-V2.9 A tool renderer never reads artifact contents (it has names and sizes only, R2.5.7). Artifacts of these
tools hold prompts and model responses, some harmful (StrongREJECT `strongreject_per_prompt.csv`, promptfoo
`promptfoo_results.json`, `promptfoo_per_test.*`, `plugin_execution.log`); the report never prints them.

### 3.4 What the three tools write (from the plugin sources; no live rows exist)
Common to all three (engine `routers/internal.py`): one observation per run (`tool =
"{package}::{Class} (v{version})"`); the engine creates one `engine.metric` per measurement **name** (so
metric name = measurement name); `dimensions`, `direction` are never set; `uncertainty` is always 0; `unit`
is null except for promptfoo. Direction and grouping therefore come from fixed name tables in each renderer.

| tool (display, package, class) | measurements (name: score) |
|---|---|
| LangBiTe, `aisc-plugin-langbite` 0.1.1, `LangBiteEvaluationPlugin` | `LangBiTe Run Success`: 1 or 0, description = error text or "LangBiTe execution finished"; one per group `"{Concern} \| {Model} \| {Language} \| {Input Type} \| {Reflection Type}"`: passed share 0..1, description `"Tolerance Evaluation: {Passed\|Failed\|Not evaluated} \| Tolerance: {t} \| Passed: {p}/{n} \| Failed: {f}/{n}"`; `Overall Pass Rate`: mean of group shares 0..1 (0 with an error description when no group); `All Tolerances Passed`: 1 or 0, description `"{a}/{b} tolerance checks passed"` |
| StrongREJECT, `aisc-plugin-strongreject` 0.1.0, `StrongRejectPlugin` | `StrongREJECT Harmfulness` 0..1 (higher is worse); `Jailbreak Resistance` = 1 - harmfulness; `Worst-Case Jailbreak Harmfulness`, description "Most effective jailbreak: {key} (lower is safer)."; `Baseline Harmfulness (no jailbreak)`; one `Harmfulness \| {jailbreak}` per jailbreak incl. `none`, description "Mean StrongREJECT score over {n} prompts (lower is safer)." On failure every summary score is 0.0 and the description is the error or "No score produced" / "Not measured" / "No attacked jailbreaks" / "No 'none' baseline run" |
| Promptfoo, `aisc-plugin-promptfoo` 0.1.0, `PromptfooPlugin` (not installed on the live stack) | `pass_rate` (unit "rate (higher is better)"), `fail_rate` ("rate (lower is better)"), `refusal_rate` ("rate"), `mean_latency_ms` ("ms (lower is better)"), `total_cost` ("USD (lower is better)"), `n_tests` ("count"); the first three may be absent |

### 3.5 LangBiTe renderer [LB]
R-V2.10 Package `vera-report-plugin-langbite`, module `vera_report_plugin_langbite`, class
`LANGBITEToolRenderer(BaseToolRenderer)`, `tool_names = ("LangBiTe",)`, entry point
`aisc_report.tools: langbite`, `contract_version = 2`, `chart_ids = {"pass_rate_by_concern": "Pass rate by
concern"}`. It matches the live plugin row (display name "LangBiTe", name `LangBiteEvaluationPlugin`).
R-V2.11 When rendered, then it shows: (a) a summary line "Overall pass rate: {Overall Pass Rate as %} across
{g} groups" and "Run: finished" or "Run: failed ({description})" from `LangBiTe Run Success`; (b) a table, one
row per group measurement (a name with exactly four " | " separators), columns Concern, Model, Language,
Input type, Reflection type, Passed (p of n), Failed (f of n), Pass rate (%), "Tolerance set in LangBiTe"
(t as %), "LangBiTe's tolerance check" (Passed, Failed or Not evaluated, copied from the description);
rows ordered by concern, then model, language; (c) when `show_charts`, a horizontal bar chart of pass rate by
concern (mean of the concern's group shares), bars sorted by concern name, axis 0 to 100 %.
R-V2.12 The tolerance check column is the tool's own result, labelled as such; the report computes no
verdict. `verdict()` returns None. DEFAULT (user to confirm) (question Q3).
R-V2.13 When a group description cannot be parsed, then Passed, Failed, Tolerance and check cells show "n/a"
and the pass rate comes from the score. Measurements matching no known name are listed in a generic table
under "Other measurements" (never dropped).
R-V2.14 `headline(run)`: "Overall pass rate" = Overall Pass Rate as %; "Tolerance checks passed" = "{a} of
{b}" from `All Tolerances Passed`'s description; "Groups" = number of group rows.
R-V2.15 With `detail = "summary"`, only (a) and the chart are shown.

### 3.6 StrongREJECT renderer [SR]
R-V2.16 Package `vera-report-plugin-strongreject`, class `STRONGREJECTToolRenderer`, `tool_names =
("StrongREJECT",)`, entry point `aisc_report.tools: strongreject`, `contract_version = 2`, `chart_ids =
{"harmfulness_by_jailbreak": "Harmfulness by jailbreak"}`.
R-V2.17 When rendered, then it shows: (a) key numbers with their direction stated in words: "Harmfulness
(mean, 0 to 1, lower is safer)", "Jailbreak resistance (1 minus harmfulness, higher is safer)", "Baseline
harmfulness, no jailbreak", "Worst jailbreak: {key}" with its harmfulness (key parsed from the description);
(b) a table of `Harmfulness | {jailbreak}` rows: Jailbreak, Harmfulness (3 decimals), Prompts (n parsed
from the description), ordered with `none` first, then by jailbreak name; (c) when `show_charts`, a bar chart
of harmfulness by jailbreak on a fixed 0 to 1 axis.
R-V2.18 A summary measurement is **not scored** when its description does not start with the success text
the plugin writes for it (compared after trimming): `StrongREJECT Harmfulness` "Mean harmfulness across all
jailbreaks"; `Jailbreak Resistance` "1 - harmfulness."; `Worst-Case Jailbreak Harmfulness` "Most effective
jailbreak: "; `Baseline Harmfulness (no jailbreak)` "Harmfulness with no jailbreak applied". Per-jailbreak rows
are written only on success and are always scored. A not-scored value is shown as
"not scored: {description}" instead of the number and is excluded from charts and headline, and the section
carries the notice "StrongREJECT did not produce scores in this run." (The plugin writes 0.0 on failure,
which would read as "perfectly safe".)
R-V2.19 `headline(run)`: harmfulness, resistance, worst jailbreak (each only when scored). `verdict()` None.
No colour bands (the old report module's green/amber/red bands are thresholds, out of scope).

### 3.7 promptfoo renderer [PF]
R-V2.20 Package `vera-report-plugin-promptfoo`, class `PROMPTFOOToolRenderer`, `tool_names = ("Promptfoo",
"promptfoo")`, entry point `aisc_report.tools: promptfoo`, `contract_version = 2`, `chart_ids = {"rates":
"Pass, fail and refusal rates"}`.
R-V2.21 When rendered, then it shows a table: Tests run (`n_tests`, integer), Pass rate, Fail rate, Refusal
rate (each as %, "not reported" when absent), Mean latency (ms, 0 decimals), Total cost (USD, 4 decimals); the
direction words come from the unit ("higher is better" / "lower is better") and are shown after the label;
the refusal rate carries the note "estimated from the grader's reasons". When `show_charts`, a bar chart of
the three rates present on a 0 to 100 % axis.
R-V2.22 When a run has no measurement at all (promptfoo writes none when it fails), then the section says
"promptfoo wrote no results for this run." and the run status is shown as usual.
R-V2.23 `headline(run)`: pass rate, tests run. `verdict()` None.

### 3.8 Packaging and the image
R-V2.24 Each new package mirrors `aisc-report-mlareject`: `pyproject.toml` with a path source to
`../aisc-report-plugin-interface`, templates under `templates/*.j2`, i18n catalogues under `i18n/*.json`
(R-V8.8), tests (`uv run --extra dev pytest`), no database access, no import-time side effects.
R-V2.25 [RG] The renderer's `pyproject.toml` depends on the three packages through path sources (as
mlareject) and its Dockerfile installs them from additional build contexts (`langbite`, `strongreject`,
`promptfoo`, defaults `../aisc-report-*`); `GET /health` lists their tool names. No compose change is made
to the live stack in this run (A4).
R-V2.26 [RG] When two renderers claim the same tool name, then startup fails (R5.3.4, unchanged).

## 4. V3: commentary on every block, light formatting

### 4.1 The formatting dialect ("light formatting")
R-V3.1 [IF] The interface provides `vera_report_plugin_interface.richtext.render(text) -> Markup`, used for
commentary, free text in `markdown` format, and any plugin that wants it. It parses with `markdown-it-py`
(CommonMark preset plus the table extension, raw HTML disabled, `breaks=True` so a single newline is a line
break, `linkify` off) and then sanitises the result with `nh3` using an allowlist.
R-V3.2 Allowed output tags: `p, br, strong, em, ul, ol, li, a, table, thead, tbody, tr, th, td, code,
blockquote`. Allowed attributes: `href` on `a` only; `nh3` adds `rel="noopener noreferrer"`. Allowed URL
schemes in `href`: `http`, `https`, `mailto`. Everything else is removed; the text inside a removed element is
kept as escaped text.
R-V3.3 The following behave as stated (each a test):
- `**bold**` gives `<strong>`, `*it*` and `_it_` give `<em>`; `- a` / `1. a` lines give lists; a pipe table
  with a header separator line gives a table; `[x](https://e.org)` gives a link.
- `<script>alert(1)</script>` and `<b>x</b>` appear as literal text (raw HTML disabled, then escaped).
- `[x](javascript:alert(1))` and `[x](data:text/html,...)` give the text `x` with no link.
- `# Heading` lines give a paragraph with the heading text (headings are not allowed, so the report's own
  heading and TOC structure cannot be broken).
- `![alt](https://e.org/i.png)` gives the text `alt`, no image (nothing is ever fetched, R5.1.5).
- A single newline inside a paragraph gives `<br>`; a blank line starts a new paragraph.
R-V3.4 The input is limited to 20000 characters (free text) and 10000 (commentary) by the schemas; the
renderer never raises on any input (fuzz test with random bytes and nested markup).
R-V3.5 [RG] In the PDF, links are clickable and printed as their text; in DOCX they become hyperlinks.

### 4.2 Commentary on every block
R-V3.6 [IF] `COMMON_PROPERTIES` gains `commentary` (string, 0 to 10000 characters, default `""`) and
`commentary_position` (`"after"` default, or `"before"`). Every block type, built-in or plugin, accepts them
through `full_options_schema()` / `full_default_options()`; block code does nothing.
R-V3.7 [RG] When `commentary` is non-empty after trimming, then the section contains
`<div class="commentary">{richtext}</div>` after the block's HTML (`after`) or between the notices and the
block's HTML (`before`). When it is empty, then the section HTML is exactly as today (R-C.1).
R-V3.8 [RG] Commentary is shown also when the block is `empty`, `stale` or `error` (the editor may explain
missing data). It does not change the block's status.
R-V3.9 [RG] The commentary is headed by nothing by default; the CSS gives it a left border in the accent
colour and the label "Commentary" as a small caption (translated, V8). DEFAULT (user to confirm): caption on.
R-V3.10 [RG] Chapter and appendix blocks (V5) also accept commentary; it is printed under their heading.

### 4.3 Free text
R-V3.11 [RG] `free_text` gains option `format`: `"plain"` (default in `default_options`, today's behaviour:
escaped, blank line = paragraph, newline = `<br>`) or `"markdown"` (R-V3.1). An existing block without
`format` renders exactly as today.
R-V3.12 [IF][RG] `BaseBlockRenderer` gains an optional class attribute `new_instance_options: dict = {}`:
options the composer puts on a block when the user **adds** it (on top of `default_options`). `free_text`
declares `{"format": "markdown"}`, so new free text blocks use light formatting while stored ones keep plain.
`GET /v1/block-types` returns it; the composer's palette uses it (R-V3.14).

### 4.4 Composer
R-V3.13 [RC] Each block card shows, under its main options, a "Commentary" textarea (6 rows) inside a
disclosure "Add a commentary" that is open when the commentary is non-empty; `commentary_position` sits under
"More options" (label "Place the commentary", values "After the section" / "Before the section").
R-V3.14 [RC] When the user adds a block from the palette, then its options are `default_options` merged with
`new_instance_options`.
R-V3.15 [RC] Textareas that take light formatting (free text in markdown format, commentary) show one help
line: "Light formatting: **bold**, *italic*, lists with - or 1., links [text](https://...), tables with |."
There is no rich-text editor (keeps the JS thin).
R-V3.16 [RC] The composer never interprets the markup itself; the preview (U3) shows the result.

## 5. V4: charts drawn by the renderer (no Superset screenshots)

### 5.1 Chart drawing [IF]
R-V4.1 The interface provides `vera_report_plugin_interface.charts.svg(spec, colours) -> Markup`, a pure
function (no I/O, no randomness): the same spec and colours give the same bytes.
R-V4.2 `colours` is `{"primary": "#rrggbb", "text": "#rrggbb", "grid": "#rrggbb"}`; bars use `primary`
only. The renderer passes the template's `primary_color` (platform default `#000FDF`), text `#000000`, grid
`#CCCCCC`. Charts never use a red/amber/green scale (no verdict meaning, BRIEF).
R-V4.3 A chart spec is `{"id": str, "title": str, "kind": "bar" | "hbar", "value_format": "percent" |
"number", "axis_min": number (default 0), "axis_max": number | null (null = rounded-up maximum), "series":
[{"label": str, "value": number | null}], "note": str (optional)}`. `percent` values are shares 0..1 printed
as 0 to 100 %. A `null` value draws no bar and prints "n/a" at its label.
R-V4.4 The SVG has `role="img"`, an `aria-label` equal to the title, a `<title>` element, explicit width and
height (max 160 mm wide), value labels at the end of each bar, axis tick labels, and escapes every label.
Labels longer than 40 characters are cut to 39 plus "..." in the drawing (the data table keeps them whole).
R-V4.5 Invalid specs (unknown kind, non-numeric value, more than 60 series items) raise `ValueError`; the
caller turns it into an error box (R1.10) for the block or the tool section.

### 5.2 The Chart block (`chart`) [RG]
R-V4.6 New built-in block type `chart`, title "Chart", `reads = ("platform", "engine", "controls",
"control_objectives")`. Options:
- `dataset` (main): `"coverage_status"` (default), `"checklist_scores"`, `"tool_chart"`,
  `"metric_by_evaluation"`, `"metric_by_dimension"`;
- `tool_chart` (main, shown for `tool_chart`): `{"tool", "chart"}`, choices from every registered tool
  renderer's `chart_ids` for tools that have runs in the pinned version, label "{tool}: {chart label}"
  (`x-aisc-reference`);
- `metric` (main, shown for the two metric datasets): `{"tool", "metric"}`, choices as R-V2.5;
- `dimension` (main, shown for `metric_by_dimension`): string, choices = keys found in `dimensions` of the
  version's measurements of that tool (empty today for the three Mijke tools, see 3.4);
- more options: `runs` (`"latest"` default or `"each"`, for `tool_chart`), `show_table` (default true),
  `max_bars` (3 to 40, default 20), `orientation` (`"auto"` default, `"vertical"`, `"horizontal"`).
R-V4.7 Data, for the pinned version only:
- `coverage_status`: one bar per coverage status in the fixed order of `coverage.STATUSES`, value = number
  of objectives with that status, computed from the layout's coverage map (section 13); empty when no
  control-objectives assessment.
- `checklist_scores`: one bar per checklist with at least one scored answer, value = its mean score
  (R2.6.5), axis 0 to 5, ordered by checklist title.
- `tool_chart`: the tool renderer's `charts(run)` item with that id, for the latest `Done` run of that tool
  (`runs=latest`), or one chart per `Done` run titled with the evaluation's readable name (`runs=each`).
- `metric_by_evaluation`: one bar per `Done` evaluation that has the metric for that tool, label
  "Evaluation {k}", value = mean score of the matching measurements in that evaluation.
- `metric_by_dimension`: mean score of the matching measurements grouped by `dimensions[dimension]`
  (missing key = group "unknown"), ordered by group label.
R-V4.8 When there is nothing to draw, then `status=empty` with a placeholder naming what is missing and the
version number, for example "No scored checklist answers for version 2." A `tool_chart` whose tool has no
renderer offering that chart: `status=error`, "This chart is not available on this platform."
R-V4.9 `orientation=auto` draws `hbar` when there are more than 6 bars or a label is longer than 12
characters, else `bar`.
R-V4.10 When there are more bars than `max_bars`, then the first `max_bars` in the dataset's order are drawn
and the notice says "{k} more groups are not shown."; the data table (when `show_table`) lists all rows.
R-V4.11 When `show_table` is true, then a two-column table (label, value formatted as in the chart) follows
the chart. The table is also what DOCX falls back to (R-V8.9).
R-V4.12 The `chart` block is stale (R1.9) when its source has data for a newer version, exactly as the block
reading the same source (engine for tool and metric datasets, controls for checklist_scores,
control_objectives for coverage_status).

### 5.3 Tool sections
R-V4.13 [LB][SR][PF] The dedicated renderers draw their charts with `charts.svg` inside their tool section
when `tool_options.show_charts` is true (R-V2.8).

### 5.4 Dashboard chart block
R-V4.14 `dashboard_chart` is unchanged (O1 still holds: screenshots off unless `REPORT_CHART_IMAGES=superset`).
Its palette help text says: "Shows a Superset chart's comments and data. For a chart drawn in the report,
use the Chart block."

### 5.5 Composer
R-V4.15 [RC] Fields with `x-aisc-show-if: {"<option>": [values]}` in the schema are drawn but hidden while
the named option has another value; the JS toggles visibility from this annotation only (generic, no chart
logic in JS). Hidden fields are not sent on save.
R-V4.16 [RG] The `chart` schema requires the dependent option of the chosen dataset (`if`/`then` in JSON
Schema): `dataset=tool_chart` without `tool_chart`, or a metric dataset without `metric`, or
`metric_by_dimension` without `dimension`, is `invalid_options` "is required" at that pointer.

## 6. V5: document structure, header and footer

### 6.1 Document settings (per layout)
R-V5.1 [RC][RG] A layout has the document settings `toc` (`"auto"` default, `"on"`, `"off"`) and `numbering`
(boolean, default false). The snapshot carries them as `document.toc` and `document.numbering`; absent means
`auto` / false. `auto` is today's rule: a TOC when the layout has more than 3 blocks, placed after the cover
(or first when there is no cover). `on` always shows it (when there is at least one entry); `off` never.

### 6.2 Table of contents with page numbers
R-V5.2 [RG] In `mode=pdf`, each TOC entry shows the page number of its section, right-aligned with a dotted
leader, using WeasyPrint's `target-counter(attr(href), page)`. In `mode=preview` the TOC is unchanged (no
page numbers). Test: the PDF text of the TOC line of a section on page 3 ends with "3".
R-V5.3 [RG] TOC entries are the sections except the cover (as today), plus chapter and appendix headings;
entries of blocks inside a chapter are nested under it (`<ol>` in `<li>`). With `numbering`, each entry is
prefixed by its number (R-V5.6).
R-V5.4 [RG] The TOC heading is "Contents" (translated, V8).

### 6.3 Chapters and appendix (grouping)
R-V5.5 [RG] Two new built-in block types, both reading no source (never `empty` or `stale`):
- `chapter` "Chapter": options `title` (common option, **required** here, 1 to 200, default "Chapter"),
  `intro` (light formatting, 0 to 5000, default ""), default `page_break_before=true`. It renders `<section
  class="chapter" id="block-{iid}"><h1 class="chapter-title">{number} {title}</h1>{intro}</section>`.
  A chapter groups every following block up to the next chapter, appendix or the end. (The chapter
  redeclares `title` and `page_break_before` in its own `options_schema`, which overrides the common ones in
  `full_options_schema()`, so `validate_declaration` accepts its defaults.)
- `appendix` "Appendix": no own options, at most one per layout (422 `duplicate_appendix`), always starts a
  new page. It renders a heading "Appendix" (translated; the common `title` option overrides it). Every block
  after it belongs to the appendix part.
R-V5.6 [RG] Numbering, when `numbering` is true (none otherwise, as today). "Top-level items" are chapters and
the content blocks (every block except cover, chapter, appendix) that are not inside a chapter. Main part
(before the appendix): top-level items are numbered 1, 2, 3, ... in order; a content block inside chapter
`c` is numbered `c.1`, `c.2`, ... Appendix part: the same with capital letters A, B, ..., Z, AA, AB (top
level) and `A.1`, `A.2` (inside a chapter). The number precedes the section's `<h2>` / chapter's `<h1>` text
and its TOC entry, separated by one space. The cover, the appendix heading and the TOC are never numbered.
Examples (tests): [cover, a, b] gives a=1, b=2; [cover, a, chapter X, b, c, chapter Y, d, appendix, e,
chapter Z, f] gives a=1, X=2, b=2.1, c=2.2, Y=3, d=3.1, e=A, Z=B, f=B.1.
R-V5.7 [RG] Without chapters and appendix, and with `numbering` false and `toc` auto, the document is exactly
today's (R-C.1).
R-V5.8 [RC] A chapter with no following content block before the next chapter/appendix/end is allowed; the
editor shows the hint "This chapter is empty." (not an error).
R-V5.9 [RC] In the editor outline, blocks inside a chapter are drawn indented under it (computed in Python
from the order; no nesting is stored: the layout stays a flat ordered list, `layout_block` unchanged).

### 6.4 Header, footer, marking, document id (per template)
R-V5.10 [RC] A template gains: `header_text` (0 to 120 characters, null = default), `footer_text` (0 to 120,
null = none), `marking` (`"none"` default, `"public"`, `"internal"`, `"confidential"`,
`"strictly_confidential"`), `show_document_id` (boolean, default false). The template export file becomes
version 2 with these fields; import accepts version 1 (fields default) and 2.
R-V5.11 [RG] The snapshot `style` object may carry these four fields; absent means default (a layout on the
platform default look, U6, always has the defaults). Placement in
the PDF: top-left `header_text` (default "{project}, Version {version}", which is today's header), top-right
the marking label in capitals in the accent colour, bottom-left `footer_text`, bottom-centre the document id
line (when `show_document_id`), bottom-right "Page {page} of {pages}" (today's, translated).
R-V5.12 [RG] Placeholders in `header_text` and `footer_text`: `{project}`, `{version}` (the number),
`{release}` (`core.system.version` or empty), `{layout}`, `{date}` (generation date, YYYY-MM-DD). An unknown
placeholder or a lone brace is printed literally. The result is escaped for a CSS string (`_css_string`).
R-V5.13 [RG] Marking labels (translated): Public, Internal, Confidential, Strictly confidential. When the
marking is not `none`, then it is also printed on the cover under the title (when the layout has a cover).
R-V5.14 [RG][RC] Document id: the composer sends `document.id` = the `generated_report.id` (the report row is
created before rendering, as today) and `mode`. The id line reads "Document {id[:8]} | Fingerprint
{fingerprint[:12]}". In `mode=preview` it reads "Preview, not a generated document".
R-V5.15 [RG] The fingerprint is the SHA-256 (hex) of the snapshot serialised as JSON with sorted keys,
separators `(",", ":")`, `ensure_ascii=False`, after removing the keys `mode`, `requested_by` and `document`.
The render response returns it as `fingerprint`; the composer stores it in `generated_report.fingerprint`
and shows it next to the file's own SHA-256 in the reports list. (The file's own hash cannot be printed
inside the file; the fingerprint identifies the exact content and settings it was made from.)
R-V5.16 [RG] With all four template fields at their defaults, header and footer are exactly today's.
R-V5.17 [RC] The template form shows Header text, Footer text (each with the placeholder help line) and
Marking as main fields; "Print the document id and fingerprint" under "More options".

## 7. V6: filters and a key-figures block

### 7.1 Control objectives subset and risk severity
R-V6.1 [RG] `control_objectives` gains options (defaults = everything, today's output):
- `requirements` (main): `"all"` (default) or a list of requirement groups, values = the distinct
  `Macro_Requirement` strings of the objectives catalogue (e.g. "R9 Risk Management"), choices listing all 11
  in catalogue order;
- `objectives` (more options): `"all"` (default) or a list of objective ids (`x-aisc-reference`), choices =
  the objective ids of the pinned version's assessment, label "{id} {label}";
- `min_severity` (main): `null` (default, "All risks") or 1 to 5;
- `include_unrated` (more options): boolean, default true;
- `show_severity` (more options): boolean, default false.
R-V6.2 [RG] An objective is shown when its requirement group is selected (or `all`) **and** it is selected
(or `all`) **and**, when `min_severity` is set, at least one of its mapped risks passes the severity filter.
A risk passes when its severity is at least `min_severity`, or when it is unrated and `include_unrated` is
true. With `group_by=risk`, a risk is shown when it passes and it maps to at least one shown objective; its
objective list shows only shown objectives. A risk with no objective (a LEFT JOIN row) is shown only when no
objective filter is set and it passes the severity filter.
R-V6.3 [RG] When `show_severity` is true, then each risk shows "Severity {n} of 5" or "Severity not rated".
R-V6.4 [RG] When filters hide everything, then `status=ok` with "No objective matches the filters of this
section." and the notice "Filtered: {requirements / objectives / severity summary}." When any filter is set,
the notice "Filtered: ..." is always added, so a reader knows the list is partial.
R-V6.5 [RG] `summary_coverage` gains `requirements` (same as R-V6.1, default all); its counts cover the
shown objectives only, and the same "Filtered" notice applies.
R-V6.6 Risk classification (qualification chains) has no severity in the data, so it gets no severity filter
(stated in section 18).

### 7.2 Test results metrics
R-V6.7 The metric filter is R-V2.5; the evaluation and tool filters exist already.

### 7.3 Key figures block (`key_figures`)
R-V6.8 [RG] New built-in block type `key_figures`, title "Key figures", `reads = ("platform",
"qualification", "control_objectives", "engine", "controls")`. Option `figures` (main): a list of figure ids,
drawn as checkboxes, default all of: `version`, `risks`, `objectives`, `coverage`, `tests`, `checklists`.
Option `show_tool_headlines` (more options), default true.
R-V6.9 [RG] It renders a grid of tiles (label, big value, small note), in the order of the list above, for the
pinned version:
- `version`: "Version {n}", note = release string and version date (YYYY-MM-DD).
- `risks`: number of control-objectives risks, note "by severity: 5: a, 4: b, 3: c, 2: d, 1: e, not rated: u"
  (only non-zero parts).
- `objectives`: number of mapped objectives, note "in {g} requirement groups".
- `coverage`: "{e} of {n} objectives with evidence" (statuses `evidence` and `evidence, attention` counted
  together, from the layout's coverage map), note listing the other status counts. Status names are the
  existing coverage statuses; no new verdict.
- `tests`: "{d} evaluations" (status Done), note = tool display names; plus, when `show_tool_headlines`, one
  tile per tool with a dedicated renderer: the tool's `headline()` of its latest Done run (at most 2 items per
  tool, label = "{tool}: {item label}").
- `checklists`: "{answered} of {questions} questions answered" over all checklists answered for the version,
  note "mean score {m} (1 to 5)" when any score.
R-V6.10 [RG] A figure whose source has no data for the version shows its tile with value "n/a" and a note
naming the missing source ("No control objectives for version 2."); the block is `empty` only when every
selected figure is n/a. A source error makes only that tile "n/a (ref {error_ref})" and the block `error`.
R-V6.11 [RG] `key_figures` is stale when any of its sources has data for a newer version (R1.9 rule, max over
sources).
R-V6.12 [RC] In the editor the figures are a checkbox list labelled with the figure names (R-U4.4, R-U5.3).

## 8. V7: changes since an earlier version (`changes_since`)

R-V7.1 [RG] New built-in block type `changes_since`, title "Changes since an earlier version", `reads` = all
sources except superset. The report stays of the pinned version S; the block compares it with a base
version B of the same project.
R-V7.2 [RG] Options: `compare_to` (main): `"previous"` (default: the version numbered S.number - 1, or the
highest number below S when numbers have gaps) or a `core.system` pid (`x-aisc-reference`; choices = the
project's versions with a number lower than S, newest first, label "Version {n} ({release})" or "Version
{n}"); `sections` (main): list of `card`, `objectives`, `tests`, `controls`, default all four, drawn as
checkboxes; `show_unchanged` (more options): default false.
R-V7.3 [RG] `ScopedData.for_version(pid)` returns a `ScopedData` for B after checking that B is a
`core.system` row of the same project with a lower number; otherwise it raises `NotInProject` and the block
renders `status=error` "The version to compare with is not an earlier version of this project." Every read for
B goes through the same scoped data functions (R6.2 holds: project and version on every query).
R-V7.4 [RG] When S has no earlier version, then `status=empty`: "No earlier version to compare with."
R-V7.5 [RG] Section **card** compares: the version fields name, release (`core.system.version`), provider,
description; the AI card fields system name, company, description, target use case, target users, intended
deployers; each tag group as a set (added and removed tags); components as a set of (name, component type)
(added, removed); qualification risks as a set of risk texts (added, removed). A changed text field shows
"before" and "after" (each cut to 300 characters with "..."). A card missing on one side: "No AI card for
version {n}." on that side.
R-V7.6 [RG] Section **objectives** compares the control-objectives assessments: objective ids added and
removed (with labels); risks added and removed (by `risk_id`, shown with `short_label`); severity changes
per `risk_id` present on both sides ("{label}: 3 to 5", "not rated" for null); coverage status changes per
objective present on both sides, where both statuses are computed with the **same** layout coverage map
(section 13), each from its own version's data.
R-V7.7 [RG] Section **tests** compares, per tool display name: number of `Done` evaluations in B and S; per
(tool, metric name), the mean score of that metric in the tool's latest `Done` run of each version, shown as
"B value", "S value", "change" (S minus B, signed, 3 significant decimals) or "only in version {n}". No word
judges a change as better or worse (direction is not known for most metrics, and thresholds are out of
scope). Rows are ordered by tool, then metric; at most 200 rows, then "and {k} more".
R-V7.8 [RG] Section **controls** compares, per checklist answered in either version: "answered {a} of {q}"
and the mean score in B and S, and the change of the mean. Checklists answered in one version only show
"only in version {n}".
R-V7.9 [RG] With `show_unchanged` false, unchanged fields and rows are left out; a section with no change
says "No change." When every selected section has no change, then the block is `ok` with "No changes between
version {b} and version {s} in the selected parts."
R-V7.10 [RG] The block heading keeps the type title; the first line of the block says "This section compares
version {s} (this report) with version {b}." The block is never `stale` (it names both versions explicitly).
R-V7.11 [RC] When the layout's pinned version changes and `compare_to` names a version that is no longer
lower, then saving gives `invalid_reference` for `/compare_to` and "Reset" puts it back to `"previous"`
(existing reset flow, R3.9).

## 9. V8: DOCX export and languages (English, French)

### 9.1 Languages
R-V8.1 [RC][RG] The report language is chosen **per layout** (column `layout.language`, default `'en'`) and
sent as snapshot `language` (absent = `en`). Reason: the language is about content; a template is a look,
reused across layouts that may need different languages.
R-V8.2 [RG] Catalogues are JSON files `report_renderer/i18n/{code}.json` (`code` matches
`^[a-z]{2}(-[A-Z]{2})?$`), plus any `*.json` in the directories of `REPORT_I18N_PATH` (colon-separated,
optional) so a language can be added without rebuilding the image. Format:
`{"_meta": {"code": "fr", "name": "Français", "decimal_separator": ",", "percent_format": "{value} %"},
"messages": {"<English text>": "<translation>", ...}}`.
R-V8.3 [RG] The message id is the English text itself, with named placeholders (`"Newer results exist for
version {number}."`). `t(msgid, **params)` returns the catalogue's translation, else the msgid, then fills
the placeholders; a missing parameter leaves `{name}` in place, never raises. English needs no messages, so
English output is unchanged (R-C.1).
R-V8.4 [RG] `en.json` (meta only) and `fr.json` ship with the renderer. `fr.json` translates every msgid the
renderer and the three new tool renderers use; stage 2 has a test that collects every `t("...")` msgid in
Python and templates (static scan) and asserts each has a French entry.
R-V8.5 [RG] `GET /v1/languages` returns `[{code, name}]`, English first, then by code. A snapshot `language`
not in that list gives 422 `invalid_snapshot` at `/language`.
R-V8.6 Adding a language is data only: dropping `de.json` into `REPORT_I18N_PATH` makes `GET /v1/languages`
list it and a snapshot with `language=de` render with its messages (test with a one-message catalogue).
R-V8.7 [RG] Translated: every fixed text of the document (document title parts, "Contents", "Page {page} of
{pages}", banners, notices, placeholders, error boxes, table headers, labels, block type titles when the
block has no `title` option, coverage status names, evaluation and run status words, stated risk class names,
marking labels). Not translated: anything from data or users (layout name, option texts, free text,
commentary, header/footer text, tool and metric names, measurement descriptions, objective and AIRO labels,
checklist texts, answers, comments). Dates stay `YYYY-MM-DD` in every language. Numbers use the catalogue's
decimal separator; `<html lang>` is the code.
R-V8.8 [IF] `BlockContext` gains `language` (code) and `t(msgid, **params)` (renderer catalogue), and
`translate_for(package) -> callable` that looks up the package's own `i18n/{code}.json` first, then the
renderer's. The interface provides the catalogue loader (`vera_report_plugin_interface.i18n`) so plugin
packages ship catalogues in the same format. A plugin without a catalogue for the language renders in
English (MLA-Reject stays English in this run).

### 9.2 DOCX
R-V8.9 [RG] The snapshot `mode` accepts `"docx"`. The renderer builds the same document HTML as for PDF and
converts it with `report_renderer/docx.py` (python-docx), returning `{docx_base64, sha256, fingerprint,
block_statuses}`. Mapping: cover `h1` to the Title style; chapter `h1` to Heading 1; section `h2` to Heading
2; `h3`/`h4` to Heading 3/4; `p` to Normal; `strong`/`em`/`code` to bold/italic/monospace runs; `a` to a
hyperlink; `ul`/`ol` to bullet/numbered lists (3 levels); `table` to a table with a bold, repeated header
row; `dl` to a borderless two-column table; `img` with a `data:` PNG/JPEG to a picture at most 16 cm wide;
inline `svg` (charts, SVG logos) to a PNG made with `cairosvg` at 2x; notices to italic paragraphs; error
boxes, banners and commentary to shaded or bordered paragraphs; `break-before: page` to a page break.
When an SVG cannot be converted, then the chart's data table is used instead with the notice "Chart shown as
a table." Any other element contributes its text; no text of the HTML body is lost (test: every non-blank
text node of the HTML body appears in the DOCX text, TOC page numbers aside).
R-V8.10 [RG] DOCX header and footer carry the same texts as the PDF (R-V5.11), with Word PAGE/NUMPAGES
fields for "Page {page} of {pages}" (translated). The TOC is a Word TOC field (levels 1 and 2) whose cached
text lists the entries without page numbers, and the document settings ask Word to update fields on open.
Fonts: the template font's first family, base size and heading colour from the template.
R-V8.11 [RG] Document properties: title = layout name, subject = project name, language = the report
language; no user name in the properties.
R-V8.12 [RG] The same size limit applies (25 MB, `pdf_too_large` code kept, message "The document is larger
than 25 MB and was not stored").

### 9.3 Composer
R-V8.13 [RC] Editor toolbar: a **Language** select (from `GET /v1/languages`, default English) next to
Version and Template; changing it marks the layout unsaved.
R-V8.14 [RC] Generate becomes two buttons: "Generate PDF" (primary, as today) and "Generate Word (DOCX)"
(secondary). `POST /api/p/{ref}/layouts/{id}/reports` accepts `{"format": "pdf" | "docx"}`; absent = pdf.
R-V8.15 [RC] `generated_report` gains `format text not null default 'pdf' check (format in ('pdf','docx'))`
and `fingerprint text null`. The document bytes stay in the existing `pdf` column (kept name, holds either
format; see Deviations). `GET /api/p/{ref}/reports/{rid}/download` serves any format with its media type
(`application/pdf` or
`application/vnd.openxmlformats-officedocument.wordprocessingml.document`) and filename
`{slug}-v{number}-{layout}-{YYYYMMDD-HHMM}.{pdf|docx}`; `GET .../pdf` keeps working for PDF rows and answers
404 for DOCX rows. The reports list shows the format.
R-V8.16 [RC] The composer's own screens stay in English (out of scope).

## 10. U3: preview of unsaved changes

R-U3.1 [RC] `POST /api/p/{ref}/layouts/{id}/preview` (editor; same-origin check as other writes) takes the
editor's current state `{system_id, template_id, language, toc, numbering, coverage, blocks}` and stores
nothing. It answers 200 JSON `{html, problems, block_statuses}`: `problems` is what `validate_layout` (and the
coverage check, section 13) would report on save; problems do **not** stop the preview (blocks with invalid
options render as error boxes, R1.11; references are scoped by the renderer anyway, R6.2).
R-U3.2 [RC] The version must be one of the project's and the template one of the project's (or null), else
422 as on save; a body over 1 MB gives 413 `too_large`; renderer failures give 502/504 as today.
R-U3.3 [RC] The returned `html` has `<meta http-equiv="Content-Security-Policy" content="default-src 'none';
img-src data:; style-src 'unsafe-inline'">` inserted as the first element of `<head>` (the page sets it as
the iframe's `srcdoc`; the iframe keeps `sandbox=""`, so no script runs).
R-U3.4 [RC] composer.js: after any change in the editor (input, change, add, move, remove, coverage tick), it
waits 1.5 s without further change, then posts the state; at most one request is in flight; a change during a
request queues exactly one more request with the newest state; an answer to an older state is ignored. A
"Refresh preview" button posts at once. An "Auto-refresh" checkbox (default on) is remembered per browser
(localStorage, wrapped in try/catch).
R-U3.5 [RC] Above the iframe a label says "Preview of unsaved changes" while there are unsaved changes and
"Preview of revision {n}" otherwise; when a preview fails, the label shows the error inline and the iframe
keeps its last content.
R-U3.6 [RC] Viewers keep the GET preview of the saved revision (unchanged). Generate still renders only the
saved revision (unchanged); the "Save first" message is inline (U7).

## 11. U4: selection widgets without Ctrl+click and without the "none means all" trap

R-U4.1 [RC] No `<select multiple>` remains in the composer's pages (test over rendered pages).
R-U4.2 [RC] An "all or list" option (schema `oneOf` of `const "all"` and an array) is drawn as two radio
buttons, "All (also ones added later)" and "Only these:", followed by a checkbox list of the choices (with a
text filter box when there are more than 10 choices). "All" sends `"all"`; "Only these" sends the ticked
values.
R-U4.3 [RC] When "Only these" is chosen with no box ticked, then the block shows inline "Pick at least one,
or choose All." and Save is refused by the server with 422 `invalid_options` at that pointer, message "Pick at
least one, or choose All." (The renderer's schemas are unchanged.) A stored empty list (possible only through
the API) is shown as "Only these" with nothing ticked and the same problem.
R-U4.4 [RC] A plain list of enum values (e.g. `statuses`, `figures`, `sections`) is a checkbox list.
R-U4.5 [RC] A single choice among data (e.g. `chart_id`, `compare_to`) stays a single select.

## 12. U5: labels, help texts and "More options"

R-U5.1 [RG][IF] Every property of every built-in block type and of `COMMON_PROPERTIES` carries a JSON Schema
`title` (the label) and `description` (one plain sentence of help); enum values carry labels in
`x-aisc-enum-labels` (`{value: label}`). Annotations do not change validation. Test: over `GET
/v1/block-types`, every built-in property has a non-empty `title` and `description`, and every enum value
has a label.
R-U5.2 [IF] `BaseBlockRenderer` gains the optional class attribute `description` (one sentence, default "");
`GET /v1/block-types` returns it; the palette shows it under each block name.
R-U5.3 [RC] `forms.form_fields` uses `title` as the label when present (else today's generated label),
`description` as a help line under the field, and `x-aisc-enum-labels` for option labels.
R-U5.4 [RC][RG] A property with `x-aisc-more: true` is drawn inside a closed `<details>` "More options" at
the end of the block's form. Every built-in block has at most 4 main fields (commentary not counted). The
split for built-in blocks (main | more):

| block | main | more options |
|---|---|---|
| cover | report_title, subtitle | show_logo, show_generated_by |
| ai_card | show_components, show_tags | show_graph_stats |
| risk_classification | stated_risk_class, show_chains | show_impact_areas |
| control_objectives | group_by, requirements, min_severity, show_status | show_rationale, show_quotes, objectives, include_unrated, show_severity |
| test_results | evaluations, tools, metrics, detail | statuses, show_measurements, show_artifacts, show_charts |
| control_answers | checklists, show_unanswered, show_scores | include_archived |
| dashboard_chart | chart_id, show_comments | include_replies, width, height |
| summary_coverage | show_uncovered_only, requirements | links (legacy, only when non-empty, R-U2.6) |
| free_text | text | format |
| chart | dataset, tool_chart, metric, dimension (shown per dataset) | runs, show_table, max_bars, orientation |
| key_figures | figures | show_tool_headlines |
| changes_since | compare_to, sections | show_unchanged |
| chapter | title, intro | page_break_before |
| appendix | (none) | title |
| common (all blocks) | commentary (own disclosure, R-V3.13) | title, page_break_before, commentary_position |

R-U5.5 [RC] A plugin block without annotations shows all its fields as main fields with generated labels
(today's behaviour).

## 13. U1 and U2: one coverage map per layout, edited as a checkbox grid

R-U2.1 [RC] A layout has one coverage map: column `layout.coverage jsonb not null default '[]'`, a list of
`{objective_id, tests: [tool display names], checklists: [checklist ids]}` (the shape of today's `links`, at
most 200 items, no duplicate `objective_id`). The snapshot carries it as `coverage_links` (always present in
snapshots made by the new composer, even when empty).
R-U2.2 [RG] When the snapshot has the key `coverage_links`, then `ctx.report.coverage_links` is that list,
and the Control objectives status, the Summary block, the `coverage` key figure, the `coverage_status` chart
and the objectives part of changes_since all read it. When the key is absent (an old snapshot), then today's
rule applies: the links of the first `summary_coverage` block (R-C.1).
R-U2.3 [RG] A `summary_coverage` block whose own `links` option is non-empty uses its own links (legacy
behaviour); with empty or absent `links` it uses the layout's map. The block's `links` option stays in its
schema so old layouts validate.
R-U2.4 [RC] Migration (in `0005`) moves the map: for each layout whose `coverage` is empty and which has a
`summary_coverage` block with non-empty `links`, `coverage` becomes the links of the lowest-position such
block, and that block's `links` becomes `[]`. Other summary blocks are untouched. `revision` and
`updated_at` do not change. After it, R-C.3 holds (same preview), except R-C.4 item 4.
R-U2.5 [RC] Validation on save and on draft preview: each `objective_id` must be in the objective choices
for the pinned version, each test in the tool choices, each checklist in the checklist choices (422
`invalid_reference`, `instance_id` null, pointer `/coverage/{i}/objective_id`, `/coverage/{i}/tests/{j}`,
`/coverage/{i}/checklists/{j}`). With `reset_invalid`, invalid values are removed from the map (an entry left
with no test and no checklist is removed).
R-U2.6 [RC] A summary block with non-empty legacy links shows them read only with the text "This block uses
its own links, set before the coverage map existed." and a checkbox "Use the layout's coverage map instead"
that, when ticked, sends `links: []` on save.
R-U2.7 [RG] `POST /v1/coverage-choices` `{project_id, system_id}` returns `{objectives: [{value, label,
group}], tests: [{value, label}], checklists: [{value, label}]}` for the pinned version (group = the
objective's requirement group); scoped as `/v1/choices`.
R-U1.1 [RC] The editor shows a **Coverage map** panel under the block list (closed by default, summary line
"Coverage map: {m} of {n} objectives linked"). It is a table: one row per objective of the pinned version,
grouped under requirement-group rows; one column per test (tool with results for this version) and per
checklist; one checkbox per cell. The first column (objective id and label) stays visible when the table
scrolls sideways. Python computes rows, columns and ticks; JS only collects the ticked boxes.
R-U1.2 [RC] When the version has no control-objectives assessment, then the panel says "No control
objectives for version {n}, so there is nothing to link."; when it has no tool results and no checklists,
it says "No test results or checklists for version {n} yet."
R-U1.3 [RC] Stored map entries whose objective, tool or checklist is not a choice for the pinned version are
listed in a "Not available for this version" group with their ticks, and saving triggers the existing
reset question (U7 dialog), which removes them.
R-U1.4 [RC] The typed "objective: tests | checklists" textarea is gone from the composer.
R-U1.5 [RC] Viewers see the grid read only (disabled checkboxes).

## 14. U6: a layout without a project template

R-U6.1 [RC] `template_id` may be null on save and on generate: null means "Platform default", the platform
look with default header and footer (the snapshot has no `style`, which is how preview renders today). The
errors `template_required` go away; `template_not_in_project` stays for a non-null id of another project.
R-U6.2 [RC] The Template select's first option is "Platform default"; for a new layout it is preselected when
the project has no template, else the first template by name is preselected (as today).
R-U6.3 [RC] "Create" on the layouts page is never disabled for lack of a template; the hint reads "Reports
use the platform look until you make a template."
R-U6.4 [RC] When a layout's template is deleted (`ON DELETE SET NULL`), then the layout uses the platform
default and says so in the editor; it can be saved and generated.

## 15. U7: no browser alert or confirm dialogs

R-U7.1 [RC] `static/composer.js` contains no `alert(`, `confirm(` or `prompt(` (static test).
R-U7.2 [RC] Every page has one message region `<div data-message role="alert" aria-live="polite">` at the top
of `main`; API errors appear there (message from `error.message`, plus "ref {error_ref}" when given) with a
close button; problems tied to a block appear inside that block, problems tied to the coverage map inside the
panel.
R-U7.3 [RC] Confirmations (delete a layout, template or preset; reset invalid references) use one
`<dialog data-confirm>` element rendered by the page, whose texts come from the server-side template
(`data-confirm-text` on the triggering button). The dialog has Cancel (focused first) and a confirm button
named for the action ("Delete layout", "Reset and save"); Esc cancels.
R-U7.4 [RC] Leaving the editor with unsaved changes asks the browser's own "leave page" question
(`beforeunload`), which is not an alert in the sense of U7.

## 16. Contracts in one place

### 16.1 Snapshot (composer to renderer) [RG][RC]
New composer snapshots are version 2; the renderer accepts both.
```
{
  "snapshot_version": 2,                        // optional; absent = 1
  "project_id", "system_id", "layout": {id, name, revision}, "blocks": [...], "requested_by",   // unchanged
  "mode": "preview" | "pdf" | "docx",           // "docx" is new
  "language": "en",                             // optional; absent = "en"; must be in GET /v1/languages
  "document": {"id": uuid | null, "toc": "auto" | "on" | "off", "numbering": false},   // optional
  "coverage_links": [{objective_id, tests, checklists}],   // optional; absent = legacy rule (R-U2.2)
  "style": {font, font_size_pt, primary_color, accent_color, logo?,                  // unchanged part
            header_text?, footer_text?, marking?, show_document_id?}                 // new, optional
}
```
R-S.1 Every new key is optional and validated by `snapshot.SCHEMA` (types, enums, lengths as in the sections
above); a v1 snapshot passes unchanged.
R-S.2 The render response gains `fingerprint` (R-V5.15) in every mode, and `docx_base64` in `docx` mode.
R-S.3 The composer stores the snapshot it sent (as today), now including the new keys, so every generated
document stays explainable.

### 16.2 Interface (`vera_report_plugin_interface`) [IF]
R-S.4 `INTERFACE_VERSION = 2` is exported. Additions (all backwards compatible, R-C.5): `COMMON_PROPERTIES`
`commentary`, `commentary_position` and annotations (`title`, `description`, `x-aisc-more`) on all common
properties; `BaseBlockRenderer.description` and `.new_instance_options`; `BaseToolRenderer.contract_version`
(default 1), `.chart_ids`, `.headline()`, `.charts()`; modules `richtext`, `charts`, `i18n`; `ToolRun`
evaluation keys `name`, `number`, measurement keys `description`, `error`. New dependencies: `markdown-it-py`,
`nh3`.
R-S.5 [RG] The registry accepts tool renderers with `contract_version` 1 or 2; a higher one is skipped with
the warning "needs a newer report renderer" (not fatal). Built-in blocks whose options change this run
(`control_objectives`, `test_results`, `free_text`, `summary_coverage`) declare `contract_version = 2`; new
built-in blocks declare 1.
R-S.6 [RG] New renderer dependencies: `python-docx`, `cairosvg` (libcairo2 is already in the image), and the
three tool packages (R-V2.25).

### 16.3 Renderer service [RG]
R-S.7 New routes (same token rule, R5.4.1): `GET /v1/languages`, `POST /v1/coverage-choices`. `GET
/v1/block-types` items gain `description` and `new_instance_options`; `GET /health` gains
`interface_version` and `languages`.

## 17. Data model changes

R-D.1 [RC] One migration `migrations/0005_presets_and_document_settings.sql`, additive only, run by the
composer's own migrate at start (as 0001 to 0004):
- `layout`: `language text not null default 'en'` (check `^[a-z]{2}(-[A-Z]{2})?$`), `toc text not null
  default 'auto'` (check in auto/on/off), `numbering boolean not null default false`, `coverage jsonb not
  null default '[]'` (check `jsonb_typeof(coverage) = 'array'`).
- `template`: `header_text text` (null, at most 120 characters), `footer_text text` (null, at most 120),
  `marking text not null default 'none'` (check in none/public/internal/confidential/strictly_confidential),
  `show_document_id boolean not null default false`.
- new table `preset` (section 2.4).
- `generated_report`: `format text not null default 'pdf'` (check in pdf/docx), `fingerprint text`.
- the coverage data move of R-U2.4 (in the same transaction).
R-D.2 No change to `core`, the engine, the catalogue, AIRO or any other module's schema; no new grant for
`report_ro` (the renderer reads the same tables; `engine.measurement` is already granted table-wide).
`scripts/guard-frozen.sh` prints the same lines as in `00-baseline.md`.
R-D.3 [RC] API shapes: layout views gain `language`, `toc`, `numbering`, `coverage`; PUT and POST accept
them (absent on PUT = keep current value, so an older client does not wipe them); template views and bodies
gain the four fields of R-V5.10; report list items gain `format` and `fingerprint`.
R-D.4 [RC] Validation of the new layout fields on save: unknown language 422 `unknown_language`; `toc`
outside the enum or `numbering` not boolean 422 `invalid_request`; coverage per R-U2.5.

## 18. Out of scope (explicitly)

- Pass/fail thresholds, verdicts, colour bands or "better/worse" wording on test measurements (BRIEF),
  including the old StrongREJECT report module's green/amber/red bands. The existing coverage `attention`
  rule is left as it is.
- Superset: screenshots, image rebuilds, any change in `apps/results-dashboard` (O1 stands).
- Translating the composer's own screens; translating data (objective texts, AIRO labels, tool and metric
  names, user texts); shipping languages other than English and French; a French catalogue for MLA-Reject.
- A rich-text (WYSIWYG) editor; images in light formatting.
- Severity on the qualification's risk chains (no such data).
- Layout revision history or restore; comparing layouts; comparisons across projects.
- Reading or printing artifact contents (prompts, responses).
- Fixing the test plugins (found while reading them, for the user's information: StrongREJECT writes 0.0 when
  it fails; promptfoo's per-test dimensions are dead code; the second LangBiTe copy in `~/aisc-plugin-langbite`
  is 0.1.0 and writes its CSV with `;`).
- Engine, catalogue, AIRO and other modules (RULES FROZEN list); deploys, compose changes on the live stack,
  pushes, new GitHub repos (A4).
- DOCX import, ODT, scheduled or emailed reports; chapters nested more than one level.

## 19. Order and dependencies

1. **Compatibility goldens first** (R-C.2): captured from the current renderer before any code change.
2. **[IF] contracts** (R-S.4): richtext (V3), charts (V4), i18n (V8), common options and annotations (V3, U5),
   tool renderer additions (V2). Everything below depends on it.
3. **[RG] core**: snapshot v2 (16.1), i18n plumbing (9.1), document structure and header/footer (V5),
   commentary and free text format (V3), fingerprint. Depends on 2.
4. **[RG] blocks**: evaluation names and metric filter (V2.1, V2.2), filters (V6.1), coverage map reading and
   `/v1/coverage-choices` (U2), key_figures (V6.3), chart (V4.2), changes_since (V7), annotations (U5). Depends
   on 3.
5. **[LB][SR][PF]** tool renderers (V2.4 to V2.8). Depend on 2; key_figures headlines and `tool_chart`
   charts use them (4 works without them: tiles and charts fall back to "not available").
6. **[RG] DOCX** (V8.2). Depends on 3 and 4 (charts, tables).
7. **[RC]** migration 0005 (17); then U6 (template optional) and U2 map (it touches save and generate); then
   U5 forms and U4 widgets (form rendering); then V1 presets (they need the block types of 4 to validate);
   then V8 language and format; then U3 draft preview and U7 dialogs (JS last, as it only draws what Python
   returns). The composer can be built against a fake renderer, so 7 can run in parallel with 3 to 6 once the
   renderer's API shapes (16.1, 16.3) are fixed.
8. **French catalogue completeness** test last in each renderer repo (it scans every msgid).

## 20. Questions for the user

- Q1 Where is the language chosen? `DEFAULT (user to confirm)`: per layout (R-V8.1); the template is a look.
- Q2 Who sees saved presets? `DEFAULT (user to confirm)`: every signed-in user of the platform, with free
  texts and commentaries stripped unless "Keep texts" is ticked (R-V1.8, R-V1.9); delete by creator or admin.
- Q3 LangBiTe reports its own tolerance check (Passed/Failed per group, against a tolerance set in the LangBiTe
  configuration). `DEFAULT (user to confirm)`: shown, labelled as the tool's own result, with no verdict from
  the report (R-V2.12). The alternative is to hide that column.
- Q4 The four built-in presets and their contents (R-V1.1) are a proposal. `DEFAULT (user to confirm)`: ship
  them as listed.
- Q5 TOC page numbers change the PDFs of existing layouts (R-C.4 item 3). `DEFAULT (user to confirm)`: on for
  every layout, no option to turn them off.
- Q6 Evaluation name format "Evaluation {k}: {tools}" (R-V2.1). `DEFAULT (user to confirm)`.
- Q7 The Word TOC fills its page numbers when Word updates fields on opening (Word asks the reader).
  `DEFAULT (user to confirm)`: accepted.
- Q8 A small "Commentary" caption above each commentary (R-V3.9). `DEFAULT (user to confirm)`: on.
- Q9 The French texts are written by the coding stage, not by a native speaker. `DEFAULT (user to confirm)`:
  shipped as is; the user reviews `fr.json`.
- Q10 Marking levels Public, Internal, Confidential, Strictly confidential; document id and fingerprint off
  by default (R-V5.10). `DEFAULT (user to confirm)`.

## 21. Deviations (from BRIEF suggestions, with reasons)

- DV1 (V1) "Report types" are presets (built-in, saved platform-wide, and files), not a type attribute on a
  layout: a layout keeps no link to its preset (R-V1.12), so editing a preset never changes existing reports.
- DV2 (V4) BRIEF suggests SVG charts "from the version's own measurements". The three Mijke tools write no
  `dimensions` and put their breakdown into measurement names (3.4), so a generic grouping chart would be
  empty for them. Charts therefore come from the tool renderers' own chart definitions (`tool_chart`), a
  metric across evaluations, coverage status and checklist scores; the generic `metric_by_dimension` stays
  for tools that do write dimensions.
- DV3 (V6) Only control-objectives risks have a severity, so the severity filter lives in the Control
  objectives (and Summary) block, not in Risk classification.
- DV4 (U2) One coverage map per layout, as suggested, but a Summary block with its own non-empty links keeps
  using them (R-U2.3), so old layouts render the same; the one visible change is R-C.4 item 4.
- DV5 (V3) Free text keeps plain text as the stored default (`format=plain`); new blocks get light formatting
  through `new_instance_options` (R-V3.12). This honours "existing layouts render the same".
- DV6 (V8) A DOCX is stored in the existing `generated_report.pdf` column (with the new `format` column)
  instead of renaming it, so migration 0005 stays additive and existing download code keeps working.
- DV7 (U4) The "pick at least one" rule is enforced by the composer (422) and not by the renderer's schemas,
  so stored snapshots and plugin blocks are unaffected.
- DV8 (V2) StrongREJECT failures are detected from the measurement descriptions of plugin 0.1.0 (R-V2.18),
  because the plugin writes 0.0 and sets no `error`. If a later plugin version changes those texts, values are
  shown as "not scored" (the safe side) until the renderer's table is updated.

## 22. Notes for stage 2 (test data)

- No live evaluation exists, so the throwaway bed's seed gains, for project A version 2 (and a smaller set for
  version 1, for changes_since): one LangBiTe run (4 group rows with the exact name/description formats of
  3.4, one with "Not evaluated", plus the three summary measurements), one StrongREJECT run (4 jailbreaks incl.
  `none`) and one failed StrongREJECT run (all summary scores 0.0 with "No score produced"), and one promptfoo
  run (all six measurements, and one run with only `mean_latency_ms`, `total_cost`, `n_tests`). Observation
  `tool` strings must be `"{package}::{Class} (v{version})"` so D8 matching works.
- Control-objectives risks in the seed need severities 1, 3, 5 and one null.
- Artifacts named like the real ones (`strongreject_per_prompt.csv`, `promptfoo_results.json`) must never have
  their names turned into content reads (R-V2.9): a test can assert no artifact table column other than name
  and size is selected.
