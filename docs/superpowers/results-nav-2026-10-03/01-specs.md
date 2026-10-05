# Results navigation: step 4 tiles → a target's tools → the pre-filtered dashboard (2026-10-03)

Mockup: https://claude.ai/artifact/NTdXVgvDMSg9AqLyit2VLb (three screens).

## Goal

From step 4, a person reaches the charts of one tool on one target in two clicks, without reading
other tools' numbers:

1. **Step 4, under the Visualisation button**: one tile for the system and one per component (the
   project's assessment targets), each with the number of tools and runs on it for the AI card
   version shown. Clicking a tile opens screen 2.
2. **A target's tools** (`/results.html?project=<slug>&target=<key>[&version=<pid>]`): one big
   button per tool run on that target, with its run counts and last run date, and a link to all
   tools on that target. Clicking a tool opens screen 3.
3. **The project's Superset dashboard**, opened with its two new filters set: Target = the
   target's label, Tool = the tool's name. The charts then show that tool's metrics only.

Nothing is made per tool or per target: the tiles and buttons are computed from the project
database on every page load, and the dashboard has two filters instead of one view per tool.

## R1 Dashboard (apps/results-dashboard/aisc_ext, Superset untouched)

- R1.1 The engine results dataset gains a column `tool`: the plugin's display name, else its name,
  else `'unknown'` for a result whose plugin row cannot be found (never NULL, like `target_label`).
  It is declared in `ENGINE_RESULTS_COLUMNS` (STRING), last.
- R1.2 The project dashboard carries two native filters, written by the bridge on every
  registration (`json_metadata.native_filter_configuration`), in Superset's own shape (as
  `superset/migrations/shared/native_filters.py` writes a `filter_select`):
  - `NATIVE_FILTER-target`, name "Target", column `target_label` of the engine results dataset;
  - `NATIVE_FILTER-tool`, name "Tool", column `tool` of the same dataset;
  - single select (`multiSelect: false`), not required, no default value;
  - scope: the whole dashboard (`rootPath: ["ROOT_ID"]`) except the charts on another dataset
    (the controls answers table), listed in `excluded` by their chart ids.
  The ids are fixed so a link can set them without looking anything up.
- R1.3 `json_metadata` keeps the project tag (`aisc_project`) beside the filters.
- R1.4 A link opens the dashboard with filters set:
  `/superset/dashboard/aisc-<hex>/?native_filters=<rison>` where the rison is
  `(NATIVE_FILTER-target:(id:NATIVE_FILTER-target,extraFormData:(filters:!((col:target_label,op:IN,val:!('<label>')))),filterState:(value:!('<label>')),ownState:()),NATIVE_FILTER-tool:(…tool…))`;
  a link for all tools of a target sets the Target filter only. Proved by hand on the live
  Superset once deployed (the store is not unit-tested against Superset, by this repo's rule).

## R2 Platform (platform/platform_service/evidence.py, read as report_ro)

- R2.1 The evidence view gains `targets`: every row of `target.target`, the system first, then the
  components by label: `{key, kind, component_kind, label, stale, tools: [...]}`. `stale` is true
  for a component the latest card no longer lists (`last_card_number < max(project.system.number)`).
- R2.2 Each target's `tools`: the tools with at least one run on that target on the card version
  shown: `{key (package_name), label (display name, else name), executed, failed, running,
  last_run (ISO date-time of the latest evaluation, or null)}`, by label. Counts as for the test
  tiles (Done / Failed / Pending+Running; archived evaluations not counted).
- R2.3 A run's target is its evaluation input named `target` → its engine component → the target
  whose `engine_component` is that component, as the dashboard's SQL resolves it.
- R2.4 Runs on the version shown with no target input are counted in one more entry
  `{key: null, kind: "unassigned", label: "No target", ...}`, last, only when there are some.
- R2.5 `installed_tools`: the installed tools (enabled) with no run on a target are not listed under
  it; the tool page shows them greyed as "installed, not run on this target" from `tests` (already
  in the view).
- R2.6 No new table and no new grant: `target.target`, `engine.aisc_backend_evaluationinput` and
  `engine.aisc_backend_aicomponent` are already readable by report_ro. A project whose engine or
  target tables are not there yet reads as no targets / no runs.

## R3 Launcher

- R3.1 Step 4 (`homepage/evidence.html`): under Visualisation, a column of tiles from `targets`:
  kind (SYSTEM, or the component kind in capitals), label, "N tools · M runs" (· "F failed" when
  any). A target with no runs is greyed, says "No runs yet", and is not a link. A stale component
  says "Not in the latest card" and stays greyed unless it has runs.
- R3.2 A tile links to `/results.html?project=<slug>&target=<key>` (+ `&version=<pid>` when an older
  version is shown); the unassigned entry links with `target=none`.
- R3.3 `homepage/results.html`: same header and look as step 4; title the project name; a
  breadcrumb "Step 4 · Visualisation › <target label> (<kind>)" whose first part links back to step 4;
  one big button per tool of that target (label, counts, last run date as DD.MM.YYYY, "Open charts
  →") linking to the dashboard with Target and Tool set; "All tools on this target →" linking with
  Target only; installed tools with no run on this target listed greyed; an unknown target says so.
- R3.4 The dashboard links are built from the platform's answer only (pid → hex, labels), with
  rison quoting of the values (`'` doubled as `!'`, `!` as `!!`).
  The Target value is the target's label, except the "No target" entry, whose runs the dashboard
  labels `unassigned` (its SQL), so its links filter on `unassigned`.
- R3.5 The Visualisation button itself keeps opening the dashboard unfiltered.

## Out of scope (decided defaults)

- A headline metric per tool (the mockup's "82% pass rate"): tools report different metrics and
  none is marked as the headline; counts and last run only.
- Controls in the dashboard filters: the controls table is excluded from both filters' scope.
- Charts per tool beyond what the filters give (the three existing charts, filtered).

## Tests

- aisc_ext (`tests/test_projects.py`, FakeStore): the tool column in the SQL and the declared
  columns; the dashboard spec's two filters with fixed ids, columns and dataset; the controls
  chart excluded; `_upsert_dashboard` writing `native_filter_configuration` in Superset's shape
  with the real dataset id and keeping `aisc_project`.
- Platform (`tests/test_evidence.py`, throwaway Postgres): targets listed system first; per-target
  tool counts on the version shown; another version's runs not counted; unassigned entry only when
  needed; stale component flagged; no target table reads as no targets.
- Launcher (`scripts/tests/test_evidence_page.py`, new `scripts/tests/test_results_page.py`): the
  tiles column under Visualisation, their links, greyed tiles; the results page's links, rison
  quoting, breadcrumb back, greyed installed tools.
- By hand after deploy: a tool button's link opens the live dashboard with both filters set.
