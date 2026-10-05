# What the user asked for (report run v2, 2026-09-24)

The user asked to make the AISC reports **more versatile without losing user-friendliness**.
A read-only diagnosis of the report system (renderer: ~/aisc-report-generator; composer:
~/aisc-install/apps/report-composer) found the gaps below. The user then asked to build **all of
them except pass/fail thresholds on test measurements** (thresholds are explicitly OUT of scope).

The file references describe the state before the run. Each item says what is wrong and what the
user needs; HOW to solve it is for the specs stage to decide (a suggestion from the diagnosis is
given where there was one; it is a suggestion, not a decision).

## Guiding principle (binding)
Power goes into presets and defaults; each block shows its few main options and the rest sits
behind a "more options" disclosure; every new option defaults to today's output, so existing
layouts render the same.

## Orchestrator assumptions (the user can correct them; treat as decided unless impossible)
- A1 Languages: English and French. Adding another language must be data only (a new catalogue
  file), no code change. English stays the default.
- A2 DOCX export is wanted, as well as PDF. PDF stays the default.
- A3 Dedicated tool renderers are built for LangBiTe, StrongREJECT and promptfoo (the tools used in
  the Mijke assessment). Look at real measurement shapes read-only in the live DB (engine.measurement /
  engine.observation) and in the plugin sources (~/aisc-plugin-langbite, the devpi packages).
- A4 No deploy to the live stack and no push in this run.

## Versatility gaps

V1. A report structure cannot be reused. Since migration 0002_templates_are_looks.sql, templates only
carry the look; layouts belong to one project; the only starting point is DEFAULT_ORDER
(apps/report-composer/report_composer/layouts.py:14). No duplicate, no export/import, no report
"types". Users must rebuild e.g. an EU AI Act report and an internal audit report in every project.
Need: start a layout from a preset (report type), duplicate a layout, and carry a layout's structure
to another project (presets hold blocks and options but no project-specific references).

V2. Test results are raw for almost every tool. The live renderer loads one tool renderer
(vera_report_plugin_mlareject); all other tools fall back to a Metric/Value/Unit table capped at
500 rows (report_renderer/tools/generic.py). Evaluations are shown as a UUID prefix
("Evaluation 3fa2b1c9", blocks/test_results.py). Need: readable evaluation names and dates, and
dedicated renderers for LangBiTe, StrongREJECT and promptfoo (A3). NOT thresholds or pass/fail.

V3. No commentary per section. Commentary only exists as a separate Free text block, plain text only
(blocks/free_text.py). Need: an optional commentary on every block (the plugin interface already has
common options for every block, COMMON_PROPERTIES in vera_report_plugin_interface/blocks.py), and
light formatting (bold, italic, lists, links, simple tables) in free text and commentary, safely
sanitised.

V4. Charts are effectively missing. REPORT_CHART_IMAGES=off on the live renderer, so the Dashboard
chart block has comments but no chart; turning Superset screenshots on needs a dashboard image
rebuild (out of bounds). Need: the report can show charts without Superset screenshots, e.g. simple
SVG charts drawn by the renderer from the version's own measurements.

V5. Document structure is basic. The TOC appears only above 3 blocks and has no page numbers; no
section numbering; blocks cannot be grouped into chapters; no appendix; header and footer are fixed
(document.py `_css`): no confidentiality marking, no document ID or hash on the page.
Need: TOC with page numbers, optional section numbering, chapters (grouping), an appendix, and header
and footer text settable (the template is the natural home for header/footer/marking).

V6. Filtering is shallow. Control objectives cannot be limited to a subset; risks cannot be filtered
by severity; Test results cannot pick metrics; there is no compact "key figures" block for an
executive summary. Need: those filters (defaulting to "everything", as today) and a key-figures block.

V7. No comparison across versions. A report is of one version; blocks can only say "newer results
exist". Need: a "changes since version N" block (what changed in the card, tests, controls, objectives
between two versions of the same project). The report stays of ONE version; the block compares it to
an earlier one the editor picks.

V8. Output formats and language: PDF only (HTML is the preview), everything hardcoded English
(lang="en", "Page X of Y", "Contents", notices). Need: DOCX export (A2) and English + French (A1),
the language chosen per layout (or per template: specs decide).

## Existing usability problems (fix, do not make worse)

U1. Coverage links are typed in a mini-syntax "objective: tests | checklists", one line per objective,
with valid IDs listed in a hint (templates/_form.html.j2, links widget).
U2. Hidden coupling: the Control objectives statuses read the links from the first Summary block
(report_renderer/document.py render(), blocks/control_objectives.py:35). Removing the Summary block
silently changes the objectives section. Suggestion: one coverage map per layout, edited as a
checkbox grid, read by both blocks.
U3. The preview refreshes only on Save (static/composer.js:144-162); every tweak is a new revision.
Need: preview of unsaved changes.
U4. Multi-selects need Ctrl+click, and "None selected means all" is a trap.
U5. Option labels are generated from field names ("Show graph stats", "Include archived") with no
help text. Schemas have no descriptions.
U6. A layout cannot be created until the project has a template (layouts.html.j2 disables Create).
Suggestion: a default platform template.
U7. Errors are shown with browser alert() and confirm() dialogs.
