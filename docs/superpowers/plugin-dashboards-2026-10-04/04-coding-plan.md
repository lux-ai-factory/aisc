# Plugin dashboards: coding plan (2026-10-04)

The tests are in 03-tests.md. P0's findings are in 02-p0-findings.md. Every step is test-first: write the step's
tests, see them fail, write the code, see them pass, commit locally. Nothing is pushed without a yes. The engine
(backend, eval, webapp) and the user's `~/aisc` stack are not touched.

## Revision of 01-plan.md (from reading the code, 2026-10-04)

- **No new decorator and no chart file.** The plugin contract already has default charts:
  - `MetricVisualization` (`chart_type`, `metrics`, `title`, `description`, `filter_dimensions`,
    `metric_label_dimension`, `group_by_dimensions`);
  - `BaseEvaluationPlugin.get_metric_visualizations(config)`, whose default is one table of all metrics.
  - The engine already serves them per run: `GET /api/v1/plugins/{evaluation_plugin_pid}/evaluations/{evaluation_pid}/result`
    → `metric_visualizations`. The engine's own results page draws them.
  - The defaults are therefore what each plugin returns there; the platform reads them from the engine, with the
    caller's token; the bridge translates them.
- **`aisc-plugin-interface` is not changed.** That also avoids the version clash: PyPI already has an older
  0.3.0 without the AISC standard.
- **The plugins change:**
  - **`aisc-plugin-data-evaluation`** 0.4.0 → 0.4.1: it writes dimensions and overrides
    `get_metric_visualizations` for Data Drift and Data Anomaly.
  - **`aisc-plugin-langbite`** 0.2.4 → 0.2.5: the same for LangBiTe.
  - **Dimension values are strings:** the engine accepts only str, int or bool (`schemas/measure.py`), so the
    bridge's dataset casts `statistic` and `p_value` back to numbers.
- **Defaults appear once a plugin has a run.** The engine serves visualizations per run, with that run's config.
  Before the first run the tile says to run the test.
- **Sync entry points:** the sandbox's Visualisation button and the results page's "Open charts" links go through
  the platform, which syncs, then redirects. A sync triggered from inside Superset is left for later (noted in
  05-report).

## Where the code is

| Repo | Working copy | Branch |
|---|---|---|
| `lux-ai-factory/aisc` | `~/aisc-dev` | feat/unified-modules |
| `lux-ai-factory/aisc-results-dashboard` | `~/aisc-dev/apps/results-dashboard` | feat/unified-modules |
| `lux-ai-factory/aisc-plugin-data-evaluation` | `~/aisc-dev-plugins/aisc-plugin-data-evaluation` (a new clone from GitHub) | feat/unified-modules |
| `lux-ai-factory/aisc-plugin-langbite` | `~/aisc-dev-plugins/aisc-plugin-langbite` (a new clone from GitHub) | feat/unified-modules |

## Steps

### S1 plugins (T1)

- **data-evaluation:**
  - `src/data_monitor/utils.py` (`add_metrics`): pass `dimensions` from the measure dict to `Measure`.
  - `data_drift/drift_detector.py`: per-feature rows gain `dimensions` built from the same values as the text
    description (feature, raw statistic, p-value, flag).
  - `data_anomaly/anomaly_detector.py`: per-feature rows gain `{"feature": …}`.
  - Each plugin class gains `get_metric_visualizations`.
  - Version 0.4.1. Tests: `uv run --with pytest --with-editable ~/aisc-dev/shared/plugin-interface python -m pytest -q tests`.
- **langbite:**
  - `aisc_plugin_langbite/plugin.py`: `_row_dimensions(row)` beside `_row_name(row)`; measures of
    `Bias Evaluation Results` and `Refusals` carry it.
  - `get_metric_visualizations`.
  - Version 0.2.5. Same test command.

### S2 dataset (T2)

`apps/results-dashboard/aisc_ext/projects.py`:
- `_ENGINE_RESULTS_SQL` gains `run`, `run_order` and the dimension columns.
- `ENGINE_RESULTS_COLUMNS` follows.
- The column list is one constant, `DIMENSION_COLUMNS`, shared with the translator.

Tests:
- `tests/test_dataset_columns.py`, `tests/test_projects.py`;
- the real-Postgres bed: `tests/test_project_datasets_db.py`, with `AISC_DASHBOARD_TEST_PG_CONTAINER`.

### S3 translator (T3)

New `aisc_ext/charts.py`, pure Python with no Superset import:
- `chart_settings(viz, *, plugin_label, columns) -> (viz_type, params, description)`.
- `bundle(project, plugin, visualizations, *, connection, dataset, starter) -> dict[path, yaml text]`.
- `layout(defaults, user_part) -> position dict`.
- `native_filters(dataset_uuid) -> list`.

The YAML is built with `yaml.safe_dump`; PyYAML is already in the Superset image.

### S4 tiles and the bridge route (T4)

- **`aisc_ext/plugin_tiles.py`:** `sync_plugin(pid, project_name, plugin, label, version, visualizations, *, store,
  importer)`, `plugin_slug(...)`, and the merge (reads the dashboard's "Your charts" part, re-imports, puts it
  back).
- **`SupersetStore`:**
  - `_upsert_chart` / `_items_chart`, for the starter chart;
  - `read_layout` / `write_layout` for one dashboard;
  - an `importer` that runs `ImportDashboardsCommand(bundle, overwrite=True)` as `aisc-bridge` inside a request
    context.
- **`project_bridge_api.py`:** `PUT /<pid>/plugins/<plugin>`.
- **`superset_config.py` `_install_extension`:** makes `aisc-bridge` (inactive, no password, role Admin, used only
  by the import inside the bridge's own request handling).
- **`unregister_project`:** also removes plugin dashboards and their charts.
- **`register_project`:** no generic charts any more (O2).

### S5 rights (T5)

- **`projects.py`:** `MEMBER_PROJECTS_SQL` reads `role`; `editor_role_name(pid)`.
- **`security.py`:** `roles_for_login(realm_roles, memberships)`, where `memberships` is `[(pid, rank)]`; the
  editor role is made by the bridge's `register_project`.
- **`sso.py`:** dashboard ownership at sign-in.

### S6 platform and homepage (T6)

- **`platform/platform_service/dashboards.py`** (new):
  - `latest_runs(pid)` (engine tables, as `evidence.py` reads them);
  - `visualizations(ep, e, token)` (engine API through `engine_components`' base URL);
  - `sync(pid, name, token)`;
  - `open_url(...)`.
- **`dashboard_bridge.py`:** `sync_plugin(pid, plugin, body)`.
- **`app.py`:** `POST /projects/{slug}/dashboards/sync` and `GET /projects/{slug}/dashboards/open`.
- **`homepage/evidence.html` and `results.html`:** the links go through `dashboards/open`.

### S7 import page (T7)

`aisc_ext/import_view.py`, an FAB view under `Assessment`. It reuses `charts.py`'s dataset pointing, and
`plugin_tiles.py`'s merge to place the charts under "Your charts".

### S8 upgrade check (T8)

`scripts/check-superset-upgrade.sh`:
- starts the given image with the extension mounted, a sqlite metadata database and a throwaway Postgres for
  results (fixture rows);
- runs `scripts/superset_upgrade_check.py` inside the container;
- removes everything.

It is added to `verify.sh --stack` as an opt-in (`--superset-upgrade`), since it starts containers.

### S9 proof (T9)

A fresh clone of `~/aisc-dev` (local submodules, as on 2026-10-04).
- **Plugins:** the new plugin versions reach the proof stack's devpi through `local_plugins/` (to check:
  plugin-publisher publishes them) or, failing that, a push the user approves.
- **Users:** the editor and viewer accounts are made on the proof stack's Keycloak with test passwords recorded in
  the proof folder.
- **Stack:** it runs as compose project `aisc-proof`, after pausing the user's `~/aisc` stack and restoring it
  afterwards, as before. This needs the user's yes, asked at that checkpoint.

## Checkpoints

- **After S1:** plugins.
- **After S2 to S5:** the bridge.
- **After S6:** the platform.
- **After S7 and S8:** the import page and the upgrade check.
- **Before S9:** asking to pause the stack.

## Stop rule

As in the contract: a design that cannot work, an engine change needed, or a step still failing after two fix
rounds.
