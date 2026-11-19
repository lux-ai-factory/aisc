# Scratch — report plugins (pre-move reference)

> **Scratch/reference, not a repo document.** This folder holds the per-tool report renderers as
> they were **before** the reporting change in ADR 0008, so the plugin migration
> ([`docs/migrations/v1.3.0-to-v1.4.0.md`](../docs/migrations/v1.3.0-to-v1.4.0.md) §1.1–1.2) can be
> run against each plugin with the original code in hand. It is a snapshot, not live code — nothing
> imports it and it must not be wired back into the backend.

Copied from `apps/backend` at commit `c633877` (the merged frozen-unified-app, before the vendored
packages were deleted).

## What changed

One document engine now lives in the backend (`aisc_backend/report_renderer/`, ADR 0008). The
per-tool fragment renderers moved **into the eval plugin that produced the run**, reached through
`BaseEvaluationPlugin.get_report_renderer()`. A plugin that does not implement it (or returns
`None`, or whose renderer raises) still renders: the backend prints the generic measurements table
for its run, so nothing is lost.

The reusable ABI (`BaseToolRenderer`, `ToolRun`, the `i18n` / `templating` / `charts` helpers) moved
from the vendored `aisc_report_plugin_interface` into the published plugin interface at
`aisc_plugin_interface.report`, behind the `[report]` extra (`aisc-plugin-interface` 0.4.0).

## Where each renderer went

| here (old vendored package) | new home |
|---|---|
| `aisc_report_plugin_langbite/` | `aisc-plugin-langbite` → `aisc_plugin_langbite/report/` (done) |
| `aisc_report_plugin_promptfoo/` | `aisc-plugin-promptfoo` → `aisc_plugin_promptfoo/report/` (done) |
| `aisc_report_plugin_strongreject/` | `aisc-plugin-strongreject` → `aisc_plugin_strongreject/report/` (done) |
| `aisc_report_plugin_mlareject/` | **not placed** — no eval plugin in this tree declares the `MLA-Reject` tool (see below) |
| `aisc_report_plugin_interface/` | `shared/plugin-interface` → `aisc_plugin_interface/report/` (done) |

`blocks.py` and `richtext.py` in `aisc_report_plugin_interface/` were dead in the backend and were
**not** moved.

## The MLA-Reject renderer (open)

`aisc_report_plugin_mlareject/` draws a run of a tool named **`MLA-Reject`**
(`tool_names = ("MLA-Reject",)`): jailbreak/harmfulness statistics from measurements whose metric is
`score`, with `language` / `jailbreak` / `category` dimensions. No plugin repository here declares
that tool — `MLA-BiTe_a4s-plugin` is `MLA BiTe` (bias), `aisc-plugin-llm-eval` is different, and the
only other `mlareject` artifact is the pilot's `vera-report-plugin-mlareject` (a report plugin for
the withdrawn external report service, not an eval plugin). It is kept here until its eval plugin is
identified; until then the `MLA-Reject` run renders through the generic measurements table.

## Moving a renderer into its plugin (recipe)

See [`docs/migrations/v1.3.0-to-v1.4.0.md`](../docs/migrations/v1.3.0-to-v1.4.0.md) §1.2. In short:
move the code into the plugin's `report/` subpackage, repoint imports from `aisc_report_plugin_interface`
to `aisc_plugin_interface.report`, implement `get_report_renderer()`, and depend on
`aisc-plugin-interface[report]>=0.4.0`.
