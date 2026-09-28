# Report composer: modules, layouts, reports (design)

Date: 2026-09-28. Status: approved 2026-09-28. Scope: `apps/report-composer`, the report renderer, and the
results dashboard's comment table. Supersedes the "preset" and "layout pinned to a version" parts of
report run v2.

## 1. Why

What the user hit on the running stack (project Demo):

- "Start from" in the New layout form lists four presets by name only. Built-in presets are shown
  nowhere else; saved presets only as a name with Export and Delete. Nothing can be inspected.
- Creating a layout failed with "The version is not one of this project." Demo has no AI card version
  yet (`project.system` is empty), the form's Version menu was empty, and a layout cannot exist
  without a version (`report_composer.layout.system_id` is NOT NULL, foreign key to `project.system`).
- A layout mixes two things that change at different times: the report's structure (blocks, order,
  template) and the data it reports on (one version, fixed at creation).

## 2. The model

Three things, each edited in one place:

| Concept | What it is | Holds data? | Where it lives |
|---|---|---|---|
| **Template** | a report's look: font, colours, logo, header, footer, marking | no | project database (exists) |
| **Layout** | which modules, in which order, with which template; appendix; index on or off; heading numbering | no | project database |
| **Report** | one generation of a layout for a chosen selection of data | yes | project database |

A layout is built and saved like a template (one editor, section 5). The data is chosen only when a
report is generated (section 6).

## 3. Modules

The blocks a layout is made of, in groups. "Exists" means a renderer block already does this.

| Group | Module | Block type | Status |
|---|---|---|---|
| AI card | AI card: the system as described in qualification | `ai_card` | exists |
| AI card | Risk classification | `risk_classification` | exists |
| Control objectives | Control objectives: the assessment of the chosen version | `control_objectives` | exists |
| Control objectives | Control answers | `control_answers` | exists |
| Control objectives | Coverage: what is covered and what is not | `summary_coverage` | exists |
| Tests run | Test runs: the runs in the report's period, when they ran, the tools and the configuration of each | `test_runs` | **new** |
| Results | Test results: scores per tool and metric | `test_results` | exists, options change |
| Results | Chart from the dashboard, **with its comments** | `dashboard_chart` | exists, comments change (section 7.4) |
| Results | Chart drawn from the scores (no comments) | `chart` | exists |
| Summary | Key figures | `key_figures` | exists |
| Summary | Changes since the previous version | `changes_since` | exists, option changes |
| Document | Cover, Chapter, Free text, Appendix | `cover`, `chapter`, `free_text`, appendix | exist |

The palette in the layout editor shows these groups with these names.

### 3.1 What a module's options may hold

A layout holds no data, so its options follow one rule:

- **Allowed:** things that belong to the project or the platform and survive new versions and new
  runs: a tool or metric by name, an objective id (`R1.1`), a checklist, a dashboard chart, texts,
  display choices (detail, grouping, show comments).
- **Not allowed:** anything that names one version or one run. These move to the report's selection:
  - `test_results.evaluations` (a list of run ids) is removed. The block shows the runs of the report's
    selection, optionally narrowed by tool and metric (both kept).
  - `changes_since.compare_to` keeps only "the version before". Picking a specific earlier version
    becomes part of the selection (section 6).
  - The layout's coverage map (objective id to tool names and checklists) stays: it names only
    project-level things. What changes is when it is checked: against the preview's version in the
    editor, and against the chosen version when a report is generated (correction of 2026-09-28).
  - Other reference options (checklists, objective ids, tools, metrics, dashboard charts) are checked
    the same way: in the editor against the preview's version, at generation against the anchor.
- Built-in layouts use "all" for every reference option, since they know no project.

The renderer's `x-aisc-reference` marker already flags every such option; validation checks each one
against the rule above.

## 4. Built-in layouts (the former presets)

- The built-ins are five files in the composer (`report_composer/presets/*.json`, section 4.1),
  shared and read-only. They replace today's four.
- They appear in the project's Layouts list, marked "Built-in", beside the project's own layouts.
- Opening one shows it in the layout editor, read-only, with its preview. **Duplicate** makes an
  editable copy in the project.
- "Start from", "Save as preset" and the saved-preset library go away. Sharing a structure between
  projects is Export and Import of a layout file.
- The file format stays `aisc-report-preset` version 1 for reading old files. Export writes version 2,
  which drops `system_id`, `language` and version-bound references.

### 4.1 The five built-in layouts

They replace today's four presets and form a ladder: each level answers a more detailed question than
the one before, for a different reader. Only the options named below differ from a module's defaults;
every reference option is "all" (section 3.1). No built-in holds a dashboard chart, since a chart
belongs to a project; a duplicated layout can add them, with their comments.

| Level | Name | For | Question it answers |
|---|---|---|---|
| 1 | **Summary** | board, a first look | Where do we stand, in one page? |
| 2 | **Management overview** | management, the provider's owner | What is the system, how risky, what is missing? |
| 3 | **Assessment report** | the project team, the default | What did we assess, and what came out? |
| 4 | **EU AI Act conformity** | the conformity file, a notified body | Can every claim be traced to its evidence? |
| 5 | **Technical dossier** | auditors, engineers | Everything, down to each tool run and quote |

**1. Summary**
- Cover
- Key figures: version, risks, objectives, coverage, tests
- Coverage: only objectives without evidence
- Changes since the version before: all parts, changed items only

**2. Management overview**
- Cover
- Key figures: all figures, with the tool headlines
- AI card: no components, tags or graph numbers
- Risk classification: the risk class and impact areas, without the risk chains
- Chart: coverage status
- Coverage: only objectives without evidence
- Changes since the version before

**3. Assessment report** (the default when a project has no layout)
- Cover, Key figures (all)
- Chapter "The AI system": AI card (with components), Risk classification (with risk chains)
- Chapter "Control objectives": Control objectives (grouped by objective, with coverage status and
  severity), Coverage (all objectives)
- Chapter "Tests": Test runs (summary), Test results (summary), Chart: metric by run
- Changes since the version before

**4. EU AI Act conformity**
- Cover, Free text "Scope" (placeholder), Key figures (all)
- Chapter "The AI system": AI card (components and tags), Risk classification (risk chains and
  impact areas)
- Chapter "Control objectives": Control objectives (with rationale and severity, unrated risks
  included), Control answers (with scores), Coverage (all objectives)
- Chapter "Evidence": Test runs (full: each tool with its times and configuration name), Test results (full),
  Chart: metric by run, Chart: checklist scores
- Changes since the version before
- Free text "Findings" (placeholder)
- Appendix: Free text "Method" (placeholder)

**5. Technical dossier**
- Everything in level 4, and:
  - Control objectives grouped by risk, with quotes of the source text
  - Control answers with unanswered questions and archived submissions
  - Test results of every status, not only completed runs
  - Chart: metric by dimension, Chart: per-tool chart
  - Changes since: unchanged items shown too
- Appendix: Free text "Method", AI card knowledge-graph numbers

The retired "Internal audit" preset's two free texts (scope and findings) live on in level 4.
Today's "Executive summary" is closest to level 2, "Full assessment" to level 3, "EU AI Act
conformity" to level 4.

**The new Test runs module's options** (used above): `detail` "summary" (one line per run: date,
version, status, tools) or "full" (one section per run, each tool with its start and end time and the
name of its configuration). Default: summary. A configuration's settings are never shown: they may hold
credentials, and the report login may read only a configuration's id, plugin and name (decision D6 (b),
kept by the user on 2026-09-28; the `configuration` option of the first version of this spec is gone).

## 5. Layouts and the layout editor

Same interaction rules as the templates screen:

- **Layouts page:** the page's actions in its header (**New layout**, **Import from file**); the list of
  built-in and project layouts; each row: Open, Duplicate, Export. Delete is inside the editor.
- **One editor** for a new layout, a reopened one, a duplicated one and a just-imported one. It holds:
  name, template, **Index** (on or off), **Numbering** of headings (on or off, as today), and the
  modules in order, taken from the grouped palette.
  Appendix is a module: everything after it goes in the appendix.
- **Preview with:** a selector in the preview pane only, not saved in the layout: AI card version and
  test period (default: the latest version, all runs of that version). With no version in the project,
  the preview shows each module's empty state and says why.
- Saving keeps a revision number, as today.

## 6. Generating a report

A **Generate report** page, opened from a layout (editor or list): a plain form drawn and handled in
Python, no browser script (the composer's one script is capped at 500 lines):

1. **AI card version** (required). The anchor: the control-objectives assessment and the control
   answers of that version follow from it. There is no separate control-objectives version: the
   assessment is already per version (`control_objectives.project.system_id` is unique), and the
   objectives' wording has no versions yet.
2. **Test period:** from and to (default: all). Only runs made against the chosen version are
   included (`evaluation.system_id`).
3. **Include runs made against other versions:** a switch, off by default. When on, those runs are
   included, marked with their version in Test runs and Test results, and the report's cover says so.
4. **Compare with** (only when the layout has Changes since): the version before (default) or a
   version picked here.
5. **Format** (PDF, as today).

The project's reports list shows, for each report: layout and revision, version, period, the switch,
who, when, status, download.

When the project has no AI card version, Generate is disabled and says: "This project has no AI card
version yet. Save the AI card in qualification first."

## 7. Data

### 7.1 What exists and is used as is

Checked on the live databases on 2026-09-28. Engine tables are named as on Sean's `master`, which the
engine adapt plan (`docs/superpowers/plans/2026-09-28-engine-adapt-to-master.md`) restores.

| Need | Source |
|---|---|
| AI card versions | `project.system` |
| Control-objectives assessment of a version | `control_objectives.project` (unique `system_id`, foreign key) |
| Control answers of a version | `controls.submission_answer.system_version_pid` (foreign key) |
| Runs, their version and date | `engine.aisc_backend_evaluation`: `system_id` (foreign key, SET NULL on delete), `created_at` |
| Tool runs, start and end, configuration name | `engine.aisc_backend_evaluationplugin` (`started_at`, `finished_at`) to `engine.aisc_backend_pluginconfig.name` |
| Scores | `engine.aisc_backend_measurement` to `aisc_backend_observation` to `aisc_backend_evaluation` |

A run belongs to the period when its `created_at` is inside it. A run whose version was deleted
(`system_id` NULL) counts as "another version".

### 7.2 Report composer schema (migration in `report_composer`, project database)

- `layout`: drop `system_id` and `language`; `coverage` stays (section 3.1). `toc` (`auto`, `on`, `off`) becomes
  `show_index boolean NOT NULL DEFAULT true`: `off` maps to false, `on` and `auto` to true.
  `numbering` stays.
- `generated_report`: keep `system_id` (the anchor); add `period_from timestamptz NULL`,
  `period_to timestamptz NULL`, `other_versions boolean NOT NULL DEFAULT false`,
  `compare_to uuid NULL REFERENCES project.system(pid)`.
- The snapshot keeps the full selection, so a report can be regenerated as it was.
- Live data: 0 layouts, 0 reports on the running stack, so no row migration. Existing installs with
  layouts: each layout keeps its blocks; version-bound options are dropped with a notice, as the
  import path already does for references.

### 7.3 Platform database

`report_library.preset` (0 rows) is dropped with its schema migration. **Needs the user's yes.**

### 7.4 Chart comments (option A, corrected 2026-09-28)

Findings while planning: each project has its own dashboard, datasets and charts (the results
dashboard's `register_project`), and the renderer already reads only the comments of the project's
dashboards (through the `AiscProject_<hex>` role). A dashboard chart plots every version at once, so
"the version a chart showed" does not exist. So the dashboard's comment table does **not** change:

- Project: a comment belongs to the chart's project (already enforced by the renderer's query).
- Version: a comment is about the AI card version that was current when it was written: the newest
  `project.system` row with `created_at <= comment.created_at`. This is the rule the engine uses for
  runs (a run records the version current at its start).
- The report's rules then apply as for runs: comments of the anchor version, inside the period; with
  "other versions" on, all of them, each marked with its version.

The renderer's own `chart` block (drawn from the scores) has no comments.

### 7.5 Not available, out of scope

- No "test set" entity: a run is a group of tool runs. Test runs lists the tools and configurations.
- No versions of the control objectives' wording (planned "objective sets"). The report uses the
  current objectives.

## 8. Errors and empty states

| Situation | What the user sees |
|---|---|
| No AI card version | Generate disabled with the message in section 6; the preview shows empty modules |
| No runs in the period | Test runs and Test results say "No test runs between <from> and <to> for version N." |
| A layout option names a checklist or chart that no longer exists | the editor marks the module, as today's reference problems |
| Import of an old preset file with version-bound options | imported without them, with a notice naming each |

## 9. Testing

Test first, as always.

- Composer: API and page tests for layouts without a version, the built-ins in the list and read-only
  in the editor, Duplicate, Export v2 and Import v1/v2, the Generate dialog (anchor, period, switch,
  compare), the reports list columns, the migration (layout columns dropped, report columns added).
- Browser tests (Playwright, system Chrome) for New, Duplicate, Import, Generate, as for templates.
- Renderer: `test_runs` block; the period and switch filters in its engine queries; `changes_since`
  with a version from the selection; comments of a chart filtered by project, version and period.
- Seeded data: the project bed needs versions, runs across two versions and dates, answers and comments.

## 10. Order and dependencies

1. The engine adapt plan's table names and reader changes have landed (superproject `31e6c46`);
   build on them in `~/aisc-definitive`.
2. Bring today's uncommitted `~/aisc-modes` work (templates editor, projects page, Framework menu) into
   `~/aisc-definitive` first, so there is one source.
3. The renderer to change is `~/aisc-report-generator`, branch `dev` (section 11).
4. Then: composer schema and API, then the screens, then the renderer blocks, then comments (after the
   decision in 7.4).

## 11. Decisions

Approved by the user on 2026-09-28 ("do it"), with the defaults of this spec:

1. Chart comments: option A (section 7.4).
2. Renderer to change: `~/aisc-report-generator`, branch `dev` (the isolation work was merged into it
   on 2026-09-28, head `0ef838b`), in place of `~/aisc-isolation-report-generator`.
3. Dropping `report_library.preset` (section 7.3): the plan's last task, run only after the user
   confirms it at that point.
