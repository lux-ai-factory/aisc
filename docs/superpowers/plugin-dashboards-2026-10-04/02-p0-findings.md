# P0 findings: Superset 4.1.1 (2026-10-04)

Run in a throwaway `apache/superset:4.1.1` container (sqlite metadata, a sqlite results table with two runs), with
`superset.commands.dashboard.importers.dispatcher.ImportDashboardsCommand` called from Python, and a browser
(Playwright) for the chart builder.

| # | Question | Answer | What changes in the plan |
|---|---|---|---|
| 1 | Does a bundle we generate import? | Yes, once each chart in the layout carries a `chartId` placeholder next to its `uuid` (the importer remaps it; without it `KeyError: 'chartId'`). | The translator writes `chartId` placeholders. |
| 1b | Can the bundle leave out the connection and dataset? | No: charts are skipped and the import fails (`KeyError` on the dataset uuid). They must be in it, by their existing uuids. | The bundle names the project's connection and dataset. |
| 1c | Does importing then overwrite the connection or the dataset (and the connection's password)? | No. Superset imports databases and datasets with `overwrite=False` whatever the command's flag (`v1/__init__.py`): existing ones are kept as they are. Only charts and the dashboard are overwritten. | None: the bridge keeps managing the connection and dataset as today. |
| 1d | What does the import need besides the bundle? | A signed-in user (`g.user`) inside a request context, for owners (`AttributeError: user` without one). | The bridge runs imports as a service account of its own (`aisc-bridge`), made at start, never used to sign in. |
| 2 | Does a re-import keep a chart someone added to the dashboard? | Partly. The chart still exists and stays attached to the dashboard (`slices`), but the dashboard's layout is replaced by the bundle's, so its place, its section header and the "+" card are gone. | The layout merge after each import, as planned, is required: the bridge reads the "Your charts" part of the layout before importing and puts it back after. |
| 3 | Is the Run filter as planned accepted and kept? | Yes: `filter_select` with `multiSelect`, `defaultToFirstItem` and `sortMetric` on a run-order column are kept through import, and so is a key of our own in the dashboard metadata (`aisc_plugin`). | None. |
| 4 | Does a chart builder link keep a preset filter? | No. `/explore/?form_data=…` keeps the dataset and drops the filter and the query mode. `/explore/?slice_id=<chart>` opens a saved chart with its filters. | The "+" card opens a **starter chart** per plugin tile: a saved chart the bridge keeps off the dashboard, on the project's dataset, filtered to the plugin, titled "New chart · <plugin>". *Save as* makes it the user's, the same rule as for a default. |

Screenshots: `q4-form_data.png` (filter dropped) and `q4b.png` (saved chart with its filter), in the session's
scratchpad.

## After the translator was built (2026-10-05)

A bundle made by `aisc_ext/charts.py`, imported in the same container on a results table with the bridge's columns:

| # | Question | Answer | What changes |
|---|---|---|---|
| 5 | Does it import and draw? | Yes: five default charts (bars, bars per feature, table, line, pie), both headers, the starter link (it opens "New chart · Data Drift"), no failed request. | None. |
| 6 | Does the Run filter apply the latest run on load? | Not with "first value by default" alone: 4.1.1 selects it but applies nothing until Apply is pressed (8 rows of both runs). With the latest run written as the filter's default value it applies on load (4 rows, run 2 only), and it survives the import. | The bridge writes the latest run as the Run filter's default at each sync, read from the project's own results dataset; "first value by default" only before any run. |
