# Plugin dashboards: report (2026-10-05)

The plan is 01-plan.md, as revised by 04-coding-plan.md. Built test-first, step by step; proven on a fresh
clone.

## What a person sees

- **Tiles:** the sandbox's Visualisation button goes through the platform, which syncs, then opens Superset's
  dashboard list, with one tile per engine plugin of the project ("dashproof · Data Drift", "dashproof · Data
  Anomaly").
- **Default charts:** a tile opens with its plugin's default charts under "Default charts · <plugin>
  <version>". Each chart is titled "Default · …".
  - They are what the plugin declares in its contract (`get_metric_visualizations`), read from the engine with
    the latest run's results.
  - No import is needed.
- **Filters:** Run, on the latest run on load; several runs can be chosen to compare. Target.
- **Your charts:** below the defaults, with "+ Build a chart of your own", which opens a starter chart on the
  project's results.
  - An editor or owner saves charts there. They survive every sync and plugin update.
  - A viewer can look but not save.
- **Assessment › Import charts:** adds charts from a Superset chart export into a tile, as the person's own.
  Owners and admins only.
- **The results page:** each tool's link opens that tool's tile with the Target set; "Every tool's tile →"
  opens the list.

## What changed, by repo

| Repo | Commits | What |
|---|---|---|
| aisc-plugin-data-evaluation | 66cec94 (0.4.1, pushed) | Per-feature measures carry `feature`, `statistic`, `p_value`, `flag` as dimensions; default charts per feature, after the plugins' own |
| aisc-plugin-langbite | 12dc285 (0.2.5, pushed) | A concern's measures are named by their metric, with the row as dimensions (before, pass rate and refusals shared one name, so averages mixed them); 3 default charts |
| aisc-results-dashboard | 98a7d4d, 0bacf93, 0f1d84f, 4f76c1b, 514050b, f761fd4 | The run and the dimensions as dataset columns; the translator (`aisc_ext/charts.py`); the tiles (`aisc_ext/plugin_tiles.py`) through Superset's own import, with people's charts kept; the generic project dashboard retired; editors' rights and ownership; the import page; one sign-in for both paths |
| aisc | 4b8368a … 1ece6cf | Plan and findings; the platform's sync and open routes (`platform_service/dashboards.py`); the homepage links; the Superset upgrade check (`scripts/check-superset-upgrade.sh`, `verify.sh --superset-upgrade`); the gateway's sign-in |

The engine was not touched, and neither was `aisc-plugin-interface`: the defaults are its existing
`MetricVisualization`.

## Tests

| Where | Result |
|---|---|
| aisc-plugin-data-evaluation | 72 passed |
| aisc-plugin-langbite | 80 passed |
| aisc-results-dashboard, unit | 225 passed |
| aisc-results-dashboard, real Postgres | 22 passed |
| platform | 72 passed (dashboards sync, bridge client, evidence) |
| homepage page tests | 37 passed; in the wider page suite 1 failure, `test_final_guard_frozen_passes`, which failed before this work too |
| `scripts/check-superset-upgrade.sh` on 4.1.1 | **all checks held** (sync, every chart draws, Run filter on the latest run, a person's chart survives a re-sync, import page, viewer refused) |
| `scripts/check-superset-upgrade.sh --break` | fails and names the two charts that read the removed column, as it should |

## The proof (fresh clone ~/aisc-proof-2026-10-05, compose project aisc-proof, removed after)

- **Install:** data-monitor 0.4.1 was installable from the fresh stack's own index (cloned from GitHub), and
  installed.
- **Runs:** Data Drift twice and Data Anomaly once, on the workshop's applicant files (no target endpoint);
  321 measures stored their `feature` as data.
- **Sync:** Data Drift got its 4 default charts and Data Anomaly its 2.
- **As the editor (the realm's `user`, editor of the project):**
  - Visualisation opened their tiles;
  - every Data Drift chart drew, on run 2 only;
  - they own the tile from sign-in;
  - they saved a chart of their own onto it (201), which a re-sync kept under "Your charts".
- **As a viewer (a test account made on the proof stack):** sees the tile; saving a chart is refused (403).
- **Not run live:** LangBiTe, which needs the qualification card and an MCAS endpoint. Its default charts are
  covered by the upgrade check, built from the plugin's own `get_metric_visualizations`.

## Found and fixed on the way

- **P0, on Superset 4.1.1:**
  - a chart builder link drops a preset filter, so the "+" card opens a starter chart instead;
  - imports need a signed-in user with the right to create charts, so the bridge has its own inactive Admin
    service account, `aisc-bridge`;
  - a re-import resets the layout, so the bridge puts people's part back;
  - the import stops linking charts at the first one not in its bundle, so the bridge links them itself;
  - "first value by default" selects without applying, so the latest run is written as the filter's default.
- **The proof:** the ownership step sat only on the OAuth sign-in path, and the stack signs in through the
  gateway. Fixed with one sign-in function for both (f761fd4, 1ece6cf).

## Left for later

- **Old dashboards:** existing stacks keep their old generic project dashboard (`aisc-<hex>`) as it was; nothing
  deletes it.
- **Drawing the raw statistic:** charts draw a metric's score. Data Drift's raw statistic and p-value are columns
  of the data (in the starter chart and anyone's charts), but the defaults do not draw them, because
  `MetricVisualization` has no field for "which value".
- **Ownership timing:** an editor added after their last sign-in owns their tiles from their next sign-in.
- **Opening Superset directly:** the tiles are synced when someone opens them from the sandbox or the results
  page; opening Superset directly shows them as of the last sync.

## After the first deploy (2026-10-05, on the stack)

The mcas LangBiTe tile showed "Cannot load filter: Columns missing in dataset: ['run']" and "No results yet".

- **The dataset was stale.** The platform re-registers every project once per start. It started 17 seconds
  before the dashboard was restarted, so the registration ran the old dashboard code and kept the old dataset
  (no `run` column). Fix: a tile sync brings the results dataset up to date first when its SQL or columns are
  not this code's (`projects.results_dataset_current`, `results_dataset_spec`), so restart order does not
  matter.
- **"No results yet" was wrong.** mcas has LangBiTe 0.2.4, which declares no default charts. Fix: a plugin
  with a run but no defaults gets "<plugin> <version> declares no default charts" and the starter link.
- **Two syncs at once gave a 500** (both made the new dashboard; unique slug). Fix: a sync holds the project's
  Postgres advisory lock on Superset's own database (`SupersetStore.project_lock`), across workers.
- **The upgrade check** now runs Superset on Postgres as the stack does (on SQLite the lock is not exercised),
  syncs one plugin three times at once, and makes the dataset stale before a sync. With the old code on
  Postgres it fails both (`[200, 500, 500]`, dataset not current); with the fix all checks hold; `--break`
  still fails on the two charts.
- **A test left behind by f761fd4** (`test_s11_2_the_sso_manager_uses_the_membership`) still looked for
  `roles_for_login` in sso.py: now it checks `apply_sign_in`.

Tests: results-dashboard 232 unit + 22 real Postgres; the upgrade check as above.
