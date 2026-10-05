# Plugin dashboards in Superset (plan, 2026-10-04)

## Goal

In the results dashboard (Superset), every test installed in a project has its own tile. Opening it shows
that test's default charts at once, defined by the test itself, on the project's results. A Run filter (the
latest run by default) and a Target filter apply to every chart. Below the defaults, people build and keep
their own charts. Nothing breaks when Superset is upgraded without anyone noticing first.

Mockups of the flow: https://claude.ai/artifact/31fuuiPL2CfZ3Tx6CuEZmC (screens 1 to 6). With defaults inside the
plugins, screens 2 and 3 (an empty tile, the import page) become the exception: a test with no chart file yet,
or charts beyond the defaults.

## Where it stands (checked 2026-10-04)

- **Superset:** 4.1.1, extended by `apps/results-dashboard` with no source changes: `superset_config.py` plus the
  `aisc_ext` package. `superset.commands.dashboard.importers` (dispatcher, v1) is present in the image.
- **Per project, the bridge makes** (`aisc_ext/projects.py`, called by the platform's `dashboard_bridge.register`
  when a project is created):
  - a connection to the project's own database;
  - two datasets, `engine_results_<hex>` and `controls_answers_<hex>`;
  - a role `AiscProject_<hex>` that may read only those two datasets;
  - one dashboard `aisc-<hex>` with three generic charts: a line by card version, a table of answers, and a bar
    by target.
- **Those three charts mix every metric on one axis**, so they mean little (screenshot of 2026-10-04 22:58):
  LangBiTe pass rates (higher is better) and Data Drift scores (about 1 minus a p-value, higher is more drift)
  side by side, colours repeating across 26 metrics, averages hiding the features.
- **How the bridge writes today:** straight into Superset's tables, through its ORM models (`Slice.params` as
  form data, `Dashboard.json_metadata`, native filter JSON). These are internal formats with no compatibility
  promise across versions.
- **Who may do what in Superset:**
  - **Viewers:** every ordinary AISC account is mapped to `AiscViewer` (`aisc_ext/security.py`). It can look and
    comment, and has no `can_write` on charts or dashboards.
  - **Project roles:** given at each sign-in from `core.project_member`, as one role per project. The membership
    SQL reads `project_id` only, not the member's rank (owner, editor, viewer).
- **Feature flags:** `THUMBNAILS` and `TAGGING_SYSTEM` are off (`superset_config.py`), so dashboard tiles show
  Superset's placeholder image and tags are not shown.
- **What the results data carries:**
  - **Data Drift:** stores the feature only inside the measurement's text `description`
    (`"target.score | raw_stat=1.754 | ... | flag=no"`); `dimensions` is empty.
  - **LangBiTe:** packs the concern into the metric name (`"ageism | AISCTarget | en_us | constrained |
    observational"`).
  - **Neither can be grouped by feature or by concern in Superset as it stands.**
- **Runs:** a run is identified by `evaluation_pid` and `evaluated_at` only; nothing gives it a readable name.
- **The engine is frozen** (Sean's). The platform already knows each project's installed plugins (it reads the
  engine's tables: the sandbox tiles, `evidence.py`) and already reads the stack's devpi (`catalogue.py`).

## Decisions

Taken in conversation on 2026-10-04:

- **D1 One tile per engine plugin per project:** a Superset dashboard named `<project> · <plugin>`, such as
  "mcas · Data Drift". Data Drift and Data Anomaly get one each, though they ship in one package.
- **D2 Templates and runs kept apart:** a chart never names a run. Every plugin dashboard has a **Run** filter
  (newest first, the latest preselected, several at once to compare) and a **Target** filter.
- **D3 Defaults inside the plugin:** each plugin declares its default charts in its contract, so they appear
  with no import. An import page remains for extra charts.
- **D4 Default charts, then your charts:**
  - **Default charts:** the first section. Its header names the plugin and version; each chart is marked as a
    default; updated with the plugin.
  - **Your charts:** below, never touched by AISC, with a "+ Build a chart of your own" card.
  - **Changing a default:** done by *Save as*, which makes the copy the user's.
- **D5 Upgrade-safe:**
  - **The plugins' files are in our own small format, never Superset's.**
  - **One translator** turns that format into charts.
  - **The import path:** charts reach Superset through its own versioned import code, not by writing its tables.
  - **An upgrade check** runs any new Superset version before it is used.

Open, for the user (defaults proposed):

- **O1** Who may build charts: **owners and editors of the project** (proposed), or viewers too.
- **O2** The three generic charts on `aisc-<hex>`: **retired** (proposed) once the plugin tiles exist, or kept.
- **O3** The DEFAULT mark: **title prefix** "Default · PSI per feature" (proposed), or the chart description
  (shown on hover). Superset has no badge; tags are off and do not show on dashboard charts anyway.
- **O4** First plugins with default charts: **Data Drift, Data Anomaly, LangBiTe** (proposed). The others get
  an empty tile with the import link until their authors add a file.
- **O5** Tile previews: leave `THUMBNAILS` off (proposed; it needs screenshot workers), so all tiles share
  Superset's placeholder.

## Design

### The chart file (the plugin's defaults)

A JSON file inside the plugin's package, one per plugin class, written by hand:

```json
{
  "format": 1,
  "dashboard": "Data Drift",
  "charts": [
    {"id": "drifted", "title": "Features drifted", "kind": "number", "metric": "Number of Drifted Features"},
    {"id": "psi", "title": "PSI per feature", "kind": "bar", "metric": "psi", "x": "feature", "value": "statistic"},
    {"id": "tests", "title": "Drift tests per feature", "kind": "table",
     "metrics": ["psi", "smd", "levene", "chi2"], "rows": "feature", "columns": ["statistic", "p_value", "flag"]}
  ]
}
```

- **Kinds (format 1):** `number`, `bar`, `line`, `table`. More kinds are added to the translator, never written in
  Superset's terms.
- **What a chart may name:**
  - the plugin's own metrics, by name;
  - the standard columns: `run`, `target`, `card_version`, `metric`, `score`, `statistic`, `p_value`, `flag`;
  - the dimension keys the plugin declares, such as `feature` or `concern`.
- **What a chart never names:** a run, a project or a dataset.
- **`id`:** stable across plugin versions, so an update finds "the same chart" again.
- **Validation:** a schema in `plugin-interface` (below), checked in the plugin's own tests.

### The declaration (the plugin contract)

`shared/plugin-interface` gains `@default_charts("charts.json")`, next to `@system_under_test` and
`@dataset_through_target`:

- **What it records:** the file's path inside the package, readable without running the plugin, because the
  platform never imports plugin code. The engine's plugin listing is untouched.
- **A check** (`aisc_plugin_interface.charts.check(path)`, also on the CLI in `cli.py`) validates the file against
  the schema and the plugin's declared dimension keys.
- **A conformance test** that every plugin runs: "my declared chart file exists, is in the package and passes
  the check".
- **Measurement dimensions:** a plugin writes a measurement's dimensions as data (`{"feature": "target.score",
  "flag": "no"}`), declared once, for example `@dimensions(feature=..., flag=...)`. Text descriptions stay for
  people.
- **Version:** plugin-interface 0.2.7 → 0.3.0 (new contract surface), published to devpi by `plugin-publisher`.

### Delivery: from the plugin to Superset

1. The chart file ships in the plugin's package (wheel and sdist), so devpi has it with the plugin.
2. **Sync**, on the platform: `POST /projects/{slug}/dashboards/sync`.
   - **Inputs:** reads the project's installed plugins with their exact versions, from the engine's tables as
     `evidence.py` does.
   - **For each plugin with no tile, or a newer version than its tile:** takes that version's chart file from
     the package on devpi, caching by package and version; a plugin without one gets an empty tile.
   - **Output:** sends the result to the bridge.
3. **When sync runs:**
   - from the sandbox: the Visualisation column's per-tool links go through the platform, which syncs, then
     redirects to the tool's dashboard;
   - from Superset itself: the extension asks the platform to sync when someone opens the Dashboards page
     (best-effort, short timeout; Superset never waits on a broken platform).
4. **Bridge route:** `PUT /api/v1/aisc_project/<pid>/plugins/<package>/<plugin>`, with the plugin's label,
   version and chart file (or none). Same bridge token as today.

### The bridge: tiles, sections, filters, import

- **Translator:** `aisc_ext/charts.py` is the only module that knows Superset's chart and dashboard formats. It
  turns a chart file into a Superset export bundle (the ZIP of YAML that Superset's own Export makes):
  - charts pointed at the project's dataset;
  - the dashboard layout with its two sections;
  - the Run and Target native filters, with Run's "first value by default" newest first;
  - the project's connection and dataset, named by their uuids (required; Superset never overwrites them on
    import), and a `chartId` placeholder for each chart in the layout (P0).
- **Import path:** the bundle goes to `ImportDashboardsCommand`, Superset's own versioned import. The existing
  three generic charts move to this path too, or are retired (O2).
- **Marking:** every object the bridge makes carries `aisc_project`, `aisc_plugin` and `aisc_chart_id` in its
  metadata.
  - **Defaults:** charts with `aisc_chart_id` are the plugin's.
  - **User charts:** anything without it, never updated, moved or deleted.
- **Layout:** `[header: Default charts · <plugin> <version>] [defaults…] [header: Your charts] [+ card] [user
  charts…]`.
  - **On update:** the bridge rebuilds only the defaults section and keeps whatever follows "Your charts" exactly
    as it is (the one place it edits the layout JSON; covered by the upgrade check).
  - **Placement:** Superset adds a newly saved chart at the bottom of the dashboard, which is the "Your charts"
    section.
- **Plugin upgrade:**
  - matched by `aisc_chart_id`, defaults are updated in place;
  - new ones are added;
  - ones the new version dropped are removed, unless someone took a copy (the copy is theirs anyway).
- **The "+" card:** a Markdown block linking to the plugin's **starter chart** (`/explore/?slice_id=…`): a saved
  chart the bridge keeps off the dashboard, on the project's dataset, filtered to the plugin, titled "New chart ·
  <plugin>". *Save as* makes it the user's. (P0: a preset filter in a chart builder link is dropped on 4.1; a saved
  chart keeps its filters.)
- **The bridge's service account:** imports run as `aisc-bridge`, made at start and never used to sign in (P0:
  Superset's import needs a signed-in user, for owners).
- **Default charts are read-only by convention:** their description says "Use Save as to change it". The
  default mark is the title prefix (O3).
- **Removed plugins:** an uninstalled plugin's tile stays, with its charts and people's charts, until someone
  deletes it.
- **The import page (extras):** `Assessment › Import charts`, an extension view.
  - It takes a Superset export ZIP or a chart file in our format.
  - It points the charts at the project's dataset and imports them into a plugin's tile, as the user's charts.
  - Owners and editors only.

### The data the charts read

`engine_results_<hex>` (the bridge's dataset SQL) gains:

- **`run`:** a readable label, "Run 2 · 4 Oct 2026, 20:39". The number counts evaluations in the project, in
  order. It sorts newest first through a hidden sort column.
- **`statistic`, `p_value`, `flag`:** from the measurement's `dimensions`. The score stays as it is.
- **One column per declared dimension key (`feature`, `concern`, …):** from `dimensions`. The keys allowed are
  a fixed list in the bridge, extended when a plugin needs a new one, so the dataset's columns stay declared up
  front (the 2026-09-29 rule: datasets declare their columns).

### Who may build charts (O1)

- **Membership with rank:** `MEMBER_PROJECTS_SQL` also reads the member's rank.
- **Owners and editors:** at sign-in they get `AiscProjectEditor_<hex>`, which holds:
  - `can_write` on Chart, limited in effect to their project's datasets by the project role's
    `datasource_access`;
  - ownership of their project's plugin dashboards, set at sign-in, so they can add charts to them.
- **Viewers:** stay as today, reading and commenting only.
- **Off for everyone, as now:** SQL Lab, exports, other projects' datasets.

### Upgrade safety (D5)

- **Plugins never contain Superset's format,** so a Superset upgrade never forces a plugin release.
- **One module translates** (`aisc_ext/charts.py`); the layout merge sits next to it.
- **Imports go through Superset's own import code,** whose format Superset keeps backward compatible.
- **`scripts/check-superset-upgrade.sh <image>`:**
  - starts the given Superset image on a throwaway database;
  - registers a sample project with fixture results for Data Drift and LangBiTe;
  - syncs their tiles;
  - asks Superset's chart-data API (`/api/v1/chart/data`) for every default chart's numbers, comparing them with
    expected values;
  - checks that a planted user chart survives a re-sync;
  - names the first failing chart. It is run before any Superset upgrade, and in `verify.sh --stack`.

## Work, in order (each phase test-first; nothing pushed without a yes)

| Phase | Repo(s) | What | Done when |
|---|---|---|---|
| P0 spike | results-dashboard | On 4.1.1, in a throwaway container: import a hand-made bundle with ImportDashboardsCommand; check native filter "first value by default" newest-first; check the chart builder link's preset filter; check what re-importing a dashboard does to charts placed on it | a short note with each answer; the design adjusted where an answer differs |
| P1 contract | plugin-interface | the chart file schema, `@default_charts`, the dimension declaration, the check (API + CLI), docs; 0.3.0 | its tests pass; a sample plugin with a broken file fails its conformance test |
| P2 plugins | aisc-plugin-data-evaluation, aisc-plugin-langbite | dimensions as data (`feature`, `flag`, `statistic`, `p_value` for Data Drift and Data Anomaly; `concern` for LangBiTe); a chart file per plugin; conformance tests | each plugin's tests pass; a fresh run stores the dimensions (checked in a project database) |
| P3 dataset | results-dashboard | `run`, `statistic`, `p_value`, `flag` and the dimension columns in `engine_results_<hex>` | dataset tests (dict store) and a real query on fixture rows |
| P4 translator | results-dashboard | `aisc_ext/charts.py`: chart file → export bundle → import; the three generic charts moved to it or retired (O2) | unit tests per kind; the bundle imports in the P0 container |
| P5 tiles | results-dashboard | the bridge's plugin route; tiles, sections, filters, marking, layout merge, plugin-upgrade rules | tests: create, update, new version, dropped chart, user chart untouched |
| P6 sync | platform, homepage | `POST /projects/{slug}/dashboards/sync` (installed plugins, chart files from devpi by version, bridge calls); the sandbox's per-tool links through it; the Superset-side sync on the Dashboards page | platform tests with a stub devpi and a stub bridge; page tests |
| P7 rights | results-dashboard | rank in the membership SQL; `AiscProjectEditor_<hex>`; dashboard ownership at sign-in | tests: an editor can save a chart on their dataset and not on another project's; a viewer cannot save |
| P8 import page | results-dashboard | `Assessment › Import charts` | tests: a Superset ZIP and a chart file both land as user charts in the right tile; a viewer is refused |
| P9 upgrade check | aisc | `scripts/check-superset-upgrade.sh`, added to `verify.sh --stack` | it passes on 4.1.1 and names the chart when a fixture is broken on purpose |
| P10 proof | all | fresh clone, README setup, the workshop path: install LangBiTe and Data Drift, run each twice, open the tiles | defaults appear with no import; Run filter switches runs and compares two; an editor builds and keeps a chart through a re-sync; a viewer cannot; screenshots |

Repos touched: `lux-ai-factory/aisc-results-dashboard` (`apps/results-dashboard`), `lux-ai-factory/aisc-plugin-interface`
(`shared/plugin-interface`), `lux-ai-factory/aisc-plugin-data-evaluation` (Data Drift, Data Anomaly),
`lux-ai-factory/aisc-plugin-langbite`, and `lux-ai-factory/aisc` (platform, homepage, scripts). Every one on `feat/unified-modules`. The engine (backend, eval, webapp) is not touched.

## Risks

- **Re-import and user charts (P0):** if Superset's import drops charts the bundle does not list from a
  dashboard's layout, the layout merge must run after each import. This is the main thing P0 settles.
- **Ownership at sign-in:** a user becomes owner of a dashboard only after signing in to Superset once. Until
  then they can view but not add charts. Acceptable; the "+" card says so when the user may not save.
- **Plugins without a chart file:** they get an empty tile. Expected for most plugins at first.
- **Old runs:** measurements stored before P2 have no dimensions, so per-feature and per-concern charts show
  them under an empty feature. The Run filter defaults to the latest run, which after P2 has them.

## Not in this

- Redesigning the generic project dashboard beyond O2.
- Alerts and scheduled reports (`ALERT_REPORTS` stays off).
- Tile thumbnails (O5).
- The report composer's charts (they do not read Superset).
