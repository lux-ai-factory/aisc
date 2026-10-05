# Plugin dashboards: tests (2026-10-04)

Every test below is written before its code and fails first. Names are the test files and what each test pins.
Built on 01-plan.md as revised by 04-coding-plan.md (defaults come from the plugin's existing
`get_metric_visualizations`, read through the engine; no new decorator).

## T1 plugins write their dimensions and their default charts

`aisc-plugin-data-evaluation`, `tests/test_dashboard_contract.py`:

- **T1.1** Every per-feature Data Drift measure carries `dimensions = {"feature", "statistic", "flag"}`, plus
  `"p_value"` when the test has one.
  - The values are strings, so the engine's flat str/int/bool rule holds.
  - `statistic` and `p_value` are formatted with 6 significant digits.
  - `flag` is `"yes"` or `"no"`.
  - The `description` text is unchanged.
- **T1.2** Run-level measures (`drift_flag`, `drift_score`, `Drift Score`, `Number of Drifted Features`, `c2st`,
  `mmd`) carry no `feature`.
- **T1.3** Every per-feature Data Anomaly measure carries `{"feature": <name>}`; Pass, Low and Severe carry none.
- **T1.4** `DataDriftPlugin.get_metric_visualizations(config)` keeps its two charts first:
  - `Drift Score` (a line with time windows, else bars) and `Number of Drifted Features` (bars), now titled;
  - then `PSI per feature` (bars of `psi`, grouped by `feature`);
  - then `Drift tests per feature` (a table of `psi`, `smd`, `ks`, `wasserstein`, `levene`, `chi2`, `psi_cat`,
    grouped by `feature`).
  - Every metric it names is one the plugin exports.
- **T1.5** `DataAnomalyPlugin.get_metric_visualizations(config)` keeps its pie of Pass, Low and Severe first, now
  titled `Outcome`, then adds `Checks per feature` (a table of the per-feature checks, grouped by `feature`).
- **T1.6** Each chart's grouping dimensions are dimensions its measures actually carry (checked against T1.1 and
  T1.3 on a real small run of the detector).

`aisc-plugin-langbite`, `tests/test_dashboard_contract.py`:

- **T1.7** `Bias Evaluation Results` and `Refusals` measures are named by their metric, and carry
  `{"concern", "model", "language", "input_type", "reflection_type"}` as dimensions.
  - **Before:** each was named by its row (`"ageism | AISCTarget | en_us | …"`), the same name for a row's pass
    rate and its refusal rate. Any average of a concern mixed the two (mcas, 2026-10-04: 0.50 = pass 1.0 with
    refused 0.0). The engine's own results page, which asks for the metric names, found neither.
  - **Who read the row names:** nothing (checked: report composer, report renderer, platform, bridge).
- **T1.8** `get_metric_visualizations(config)` returns:
  - `Overall pass rate` (a table);
  - `Pass rate per concern` (bars of the bias results, grouped by `concern`);
  - `Refusals per concern` (bars of `Refusals`, grouped by `concern`).
- **T1.9** Every metric named is exported, and every grouping dimension is carried.

## T2 the bridge's dataset

`aisc-results-dashboard`, `tests/test_dataset_columns.py` (extended):

- **T2.1** `engine_results_<hex>` declares these columns, in this order after the existing ones:
  - `run` (STRING);
  - `run_order` (INTEGER);
  - `feature`, `concern`, `flag`, `language`, `input_type`, `reflection_type`, `model` (STRING);
  - `statistic`, `p_value` (FLOAT).
- **T2.2** The dataset SQL:
  - computes `run` as `'Run ' || n || ' · ' || <date, DD Mon YYYY, HH24:MI>`, with `n` the evaluation's number
    in the project (`dense_rank` over the evaluation's creation time);
  - computes `run_order` as that same `n`;
  - reads each dimension column as `dimensions->>'<key>'`, and `statistic` and `p_value` cast to double
    precision when numeric, else NULL.
- **T2.3** On the real Postgres test bed (`AISC_DASHBOARD_TEST_PG_CONTAINER`), fixture rows of two evaluations
  give runs 1 and 2 with the expected labels, features and numbers.

## T3 the translator

`aisc-results-dashboard`, `tests/test_charts.py` (new, pure Python):

- **T3.1 Chart kinds:** each kind maps to a Superset chart type with a fixed setting shape:
  - `bars` → `echarts_timeseries_bar`, x = the first grouping dimension (or `metric`), one series per
    `metric_label_dimension` (or `metric`);
  - `line` → `echarts_timeseries_line`, x = `run_order`;
  - `table` → `table` (aggregate: rows = grouping dimensions, columns = metrics as AVG(score));
  - `pie` → `pie`;
  - `scatter`, `radar`, `kde`, `csv` → `table`, with the chart description saying which kind was asked for.
- **T3.2 Filters:**
  - every chart filters `tool` to the plugin's label and `metric` to its `metrics`;
  - `filter_dimensions` become IN filters on those columns.
- **T3.3 The default mark:** every chart is titled `Default · <title>` and described "Made by the <plugin>
  plugin. Use Save as to change it."
- **T3.4 The bundle:**
  - it holds `metadata.yaml`, the project's connection and dataset by their uuids, one YAML per chart and one
    dashboard;
  - each chart in the layout has `chartId` and `uuid`;
  - chart uuids are stable: `uuid5(project pid + plugin + chart index + title)`.
- **T3.5 The layout:** a header "Default charts · <plugin> <version>", the defaults in rows of two, a header
  "Your charts", then a Markdown block linking to the plugin's starter chart.
- **T3.6 Native filters:**
  - Run: `filter_select` on `run`, `multiSelect`, `defaultToFirstItem`, `sortMetric = run_order`, descending;
  - Target: `filter_select` on `target_label`.
- **T3.7 An unknown grouping dimension** (not a declared column) is dropped from the chart, and its description
  says so. It never fails the import.

## T4 tiles, sync and the merge

`aisc-results-dashboard`, `tests/test_plugin_tiles.py` (new, fake store plus a fake importer):

- **T4.1** `sync_plugin(pid, plugin, label, version, visualizations)` makes:
  - the dashboard `aisc-<hex>-<plugin slug>`, titled `<project name> · <label>`, for the project role only;
  - the starter chart (off the dashboard);
  - the defaults through the importer.
- **T4.2** With no visualizations yet (the plugin never ran), the dashboard holds the two headers and a Markdown
  block "No results yet: run <label> in the engine". There is no starter chart link until there are results.
- **T4.3** Re-sync with the same input changes nothing: no new chart, same uuids.
- **T4.4 A newer plugin version:** its defaults replace the old ones (matched by uuid), new ones are added, dropped
  ones are deleted.
- **T4.5 The merge:**
  - a chart someone added (no `aisc_chart_id`), placed under "Your charts", is still on the dashboard, in the same
    place, after a re-sync;
  - charts with no place in the layout are appended under "Your charts".
- **T4.6** `unregister_project` also removes the plugin dashboards and their AISC charts. Users' charts are kept
  but no longer on any AISC dashboard. Deleting a project already drops its data, so their charts would show
  nothing; they are removed too.
- **T4.7** The project dashboard `aisc-<hex>` loses its three generic charts (O2). The Visualisation link goes to
  the project's tiles instead (T6).

`tests/test_project_bridge.py` (extended):

- **T4.8** `PUT /api/v1/aisc_project/<pid>/plugins/<plugin>` with the bridge token calls `sync_plugin`, and answers
  200 with the dashboard's slug. A wrong token gets 401; an unknown project gets 404.
- **T4.9** Imports run as the `aisc-bridge` service account, which is made at start (inactive, no password).

## T5 rights

`aisc-results-dashboard`, `tests/test_security.py` (extended):

- **T5.1** `MEMBER_PROJECTS_SQL` returns `project_id` and `role`.
- **T5.2** `roles_for_login`:
  - an owner or editor gets `AiscProject_<hex>` and `AiscProjectEditor_<hex>`;
  - a viewer gets `AiscProject_<hex>` only.
- **T5.3** `AiscProjectEditor_<hex>` holds `can_write` on Chart and `can_explore` / `can_save` on the chart
  builder, and nothing on Dashboard. SQL Lab and export stay off.
- **T5.4** At sign-in, an owner or editor becomes an owner of their projects' plugin dashboards, so they can add
  charts; a viewer is removed from that list if their rank fell.

## T6 platform and homepage

`aisc` platform, `tests/test_dashboards_sync.py` (new; stub engine and stub bridge):

- **T6.1** `POST /projects/{slug}/dashboards/sync`:
  - needs a member;
  - for each engine plugin in the project, takes its latest run (evaluation plugin and evaluation pids from the
    engine tables);
  - asks the engine for that run's `metric_visualizations` (`GET /api/v1/plugins/{ep}/evaluations/{e}/result`,
    with the caller's token);
  - PUTs the plugin, label, version and visualizations to the bridge.
- **T6.2** A plugin with no run is sent with no visualizations. A plugin whose results the engine refuses is
  sent with none, and named in the answer's `warnings`.
- **T6.3** It answers `{"dashboards": [{"plugin", "label", "slug", "url"}], "warnings": [...]}`; a bridge that is
  down gives 502 with no partial claim.
- **T6.4** `GET /projects/{slug}/dashboards/open?plugin=&target=` syncs, then answers 303 to that plugin's
  dashboard URL, with the Target filter set in the URL as `results.html` sets it today.

`aisc` scripts, `tests/test_results_page.py` and `tests/test_evidence_page.py` (extended):

- **T6.5** The Visualisation button goes through `/api/projects/<slug>/dashboards/open`, which opens the
  project's tiles.
- **T6.6** On a target's results page, each tool's "Open charts" link goes through `dashboards/open` with
  `plugin` and `target`.

## T7 import page

`aisc-results-dashboard`, `tests/test_import_page.py` (new):

- **T7.1** `Assessment › Import charts`:
  - lists the plugin dashboards the user may change;
  - takes a Superset export ZIP;
  - points its charts at the project's dataset;
  - imports them as the user's charts, with no `aisc_chart_id`, under "Your charts".
- **T7.2** A viewer is refused (403). A ZIP naming another project's dataset is pointed at this project's, never
  at the other's.

## T8 upgrade check

`aisc` scripts, `scripts/check-superset-upgrade.sh` plus `scripts/tests/test_superset_upgrade_check.py`:

- **T8.1** On `apache/superset:4.1.1` with the extension mounted:
  - registers a sample project with fixture results (two Data Drift runs, one LangBiTe run);
  - syncs its plugins;
  - asks `/api/v1/chart/data` for every default chart, and compares the row counts with expected ones;
  - checks a planted user chart survives a re-sync.
  - Exit 0.
- **T8.2** With a fixture chart broken on purpose (an unknown column), it exits non-zero and names the chart.

## T9 proof (P10)

On a fresh clone:
- **Setup:** install LangBiTe and Data Drift (the new versions), and run each twice on MCAS.
- **Tiles and defaults:** Visualisation shows one tile per plugin, and each opens with its default charts.
- **Run filter:** it preselects the latest run and switches to the other.
- **Rights:** an editor saves a chart of their own, and it survives a re-sync; a viewer cannot save.
- **Upgrade check:** passes.
