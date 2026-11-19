# 0008. Report renderer: one engine in the backend, per-tool fragments in the eval plugin

**Status:** accepted
**Supersedes:** [ADR 0005](0005-report-renderer-weasyprint-and-plugin-abi.md) (its external-service seam and its four bundled per-tool renderer packages are withdrawn)
**Invariant:** I3 — one implementation per concern (the second renderer is withdrawn); I8 referenced (no new moving part); I11 referenced (no new container)
**Owner:** AISC project owner (reporting workstream, epic E5)
**Date:** 2026-11-19

## Context

ADR 0005 ported the pilot's WeasyPrint/Jinja renderer **and** kept the pilot's separate report service
behind `REPORT_SERVICE_URL`, and vendored the report-plugin ABI plus four per-tool renderer
distributions (`aisc_report_plugin_{langbite,mlareject,promptfoo,strongreject}`) into the backend. The
merge of the colleague's `feat/unified-app` branch landed his version of that seam in full: a headless
`apps/report` service (`aisc-report`), a `REPORT_SERVICE_URL` POST path and `apps/report` registered as
a submodule and a compose service. The merged backend now carries **two implementations of the same
concern** — the in-process `report_renderer/` engine and the external `apps/report` renderer, chosen at
run time by configuration. I3 forbids that; whether the second one merely wins or merely exists, the
core has two renderers to keep aligned.

Two things are also true of the per-tool renderers as vendored:

- They are **tool-specific code in the core**. The langbite / mlareject / promptfoo / strongreject
  fragments exist to draw one tool's run; their home is the eval plugin that produced that run, not the
  backend that renders documents for every tool.
- The backend **already runs eval plugin code** to build the report: `services/report_snapshot.py`
  (`_declared_charts`) loads the plugin through `routers.plugin.plugin_loader.load_plugin(...)` and calls
  the plugin's `get_metric_visualizations(...)` to learn what to chart. Calling a plugin's fragment
  renderer is the **same mechanism**, not a new one, so no second discovery path is justified — the
  `aisc_report.tools` entry-point group plus the bundled packages is the second path.

The fragment ABI itself is already a **pure data contract**: a `ToolRun` (read-only rows — observations,
measurements, components, artifacts; no database session) becomes an HTML fragment. It is not a service
contract. "Bring your own report tool" therefore means "implement a renderer for the assessment's
versioned snapshot / `ToolRun` shape", which is a plugin-interface concern, not a reason for a
container.

## Decision

1. **Exactly one document engine, and it lives in the backend.** The in-process
   `aisc_backend/report_renderer/` (snapshot → PDF/DOCX/HTML via WeasyPrint, the Jinja templates/CSS and
   python-docx) is the renderer. The external path is withdrawn: drop `REPORT_SERVICE_URL`, the
   `httpx` POST in `services/report_service.py` and the `apps/report` (`aisc-report`) submodule and
   compose service. There is one renderer, with one behaviour (a configured renderer is never
   substituted silently). This reverses ADR 0005 decision 4 and rejects the merged branch's
   second implementation.
2. **Per-tool fragment renderers move into the eval plugins, reached through the existing plugin
   contract.** The `ToolRun → HTML fragment` ABI becomes an **optional method on the eval plugin
   interface** (`aisc-plugin-interface`, the published package the backend already loads plugins
   through), beside `get_metric_visualizations`. The backend hands the read-only `ToolRun` to the
   plugin's renderer for that run, exactly as it already asks the plugin what to chart. This is the
   "bring your own renderer" seam: a plugin that implements it owns its fragment; the ABI is a data
   contract over our versioned snapshot, not a generic renderer service.
3. **The vendored per-tool packages and the entry-point discovery path are removed.** The four
   `aisc_report_plugin_*` distributions and the backend's `aisc_report_plugin_interface` copy leave
   `apps/backend`; each tool's renderer is ported into its `aisc-plugin-*` repository. The reusable ABI
   pieces (`BaseToolRenderer`, `ToolRun`, the i18n/templating helpers) fold into the published
   plugin-interface package rather than a second vendored interface. The `aisc_report.tools`
   entry-point group (and `tools_abi.registry()`) is dropped in favour of the plugin contract.
4. **The generic fallback stays.** A tool whose plugin declares no fragment renderer still prints the
   pilot's generic measurements table, as it does today — moving the renderer into the plugin changes
   where the real renderer comes from, not what happens without one.
5. **No service, no container, no new repository.** Rendering runs in-process in the backend (I11: the
   deployable set does not grow); the fragment ABI is a Python interface published with the plugin
   contract, not a microservice. The security-sensitive engine dependencies (WeasyPrint, cairosvg,
   lxml, defusedxml, pillow) and the `python-docx` Word export stay as ADR 0005 recorded them — that
   I8 decision is unchanged and still holds.

## Consequences

- **Cost:** removing the second path touches `services/report_service.py`, `config/settings.py`
  (`REPORT_SERVICE_URL`), the compose/Caddy wiring and the parent's `apps/report` registration, and
  rewrites the renderer registry to call the plugin. Moving the per-tool renderers is **cross-repo**:
  the `aisc-plugin-*` eval repositories each gain a fragment renderer and the plugin-interface package
  gains the ABI — they are separate repositories, so the change lands there, not in this tree.
- **The "BYO renderer" story is narrower and truthful.** It is a versioned data ABI you implement in a
  plugin (or by extending the plugin interface), not an HTTP endpoint that renders arbitrary input. A
  third party adopts it by depending on `aisc-plugin-interface`, the same way an eval plugin does.
- **Fidelity behaviour changes in one place.** A configured-but-unreachable external renderer is no
  longer a failure mode, because there is no external renderer: generation either renders locally or
  raises from the local engine and the worker marks the report failed. The merged fail-loudly handling
  for the *qualification* service is unaffected.
- **Guard:** none added; `tests/architecture` is unchanged. The renderer's own tests live beside the
  code (the report router/layout tests, the tool-renderer tests) and move with the code.
- **Removal condition:** revisit only if the backend image's cairo/pango footprint becomes unacceptable
  or a deployment must scale rendering independently of the request path. Even then the external piece
  is a **remote deployment of this same engine**, not a second implementation, and it needs its own ADR
  (an I8/I11 decision with an owner, a cost and a removal condition).
