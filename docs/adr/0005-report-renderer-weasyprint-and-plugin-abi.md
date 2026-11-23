# 0005. Report renderer: the pilot's WeasyPrint/Jinja renderer and report-plugin ABI

**Status:** superseded by [ADR 0008](0008-report-renderer-one-engine-in-backend.md) (its external-service seam and bundled per-tool renderer packages are withdrawn)
**Supersedes:** [ADR 0004](0004-reporting-renderer-dependencies.md) (its `reportlab` choice is withdrawn)
**Invariant:** I8 — new production dependencies decided (not waived)
**Owner:** AISC project owner (reporting workstream, epic E5); renderer code ported from the pilot
**Date:** 2026-11-17

## Context

ADR 0003 (decision 7) requires the unified app to **preserve real pilot PDF/Word report functionality** and
to inventory the renderer's production dependencies before choosing a deployment approach. ADR 0004
chose an in-process `reportlab` renderer instead of the pilot's WeasyPrint renderer. Two problems with
that, found on review:

1. **It is not the pilot's renderer.** The pilot renders HTML→PDF with **WeasyPrint** from **Jinja
   templates and CSS** (`report_renderer/templates/document.html.j2`, `report.css`, per-block templates
   and CSS), draws SVG logos with **cairosvg**, and renders each tool's section through the
   **report-plugin ABI** (`aisc_report_plugin_interface`, entry-point groups `aisc_report.blocks` /
   `aisc_report.tools`, the `aisc-report-plugin-*` packages). `reportlab` reproduces the *information*
   but neither the templates nor the plugin ABI, so E5 parity is not met.
2. **Ordering.** ADR 0004 was written *after* `reportlab`/`python-docx` had already landed on the
   branch (`74b752e` added the dependencies; `cbab369` added the ADR). I8 requires the decision
   **before** the dependency. That ordering is recorded as a deviation in
   [`../refactor-deviations.md`](../refactor-deviations.md); this ADR is written **before** the
   renderer dependencies below are added, so the ordering holds for them.

The pilot's renderer is a FastAPI service (`apps/report-generator`) whose data layer reads the platform
Postgres (schema `engine.*`, `project.system`, per-project databases). The unified app owns the same
engine tables (the `aisc_backend` Django app) in one database, so the renderer can run **in-process**
against the unified ORM rather than as a second service.

## Decision

1. **Adopt the pilot's renderer, not a re-implementation.** Vendor `report_renderer/` (blocks, Jinja
   templates, CSS, `style.py`, `svg_print.py`, `docx.py`, `pdf.py`, `registry.py`) and
   `aisc_report_plugin_interface` into the backend, and render PDF/Word/HTML from the frozen snapshot
   with WeasyPrint and python-docx. `reportlab` is **dropped**.
2. **Adopt the report-plugin ABI.** Port `aisc_report_plugin_interface` (the block/tool contracts) and
   the four bundled tool renderers (`aisc-report-plugin-langbite`, `-mlareject`, `-promptfoo`,
   `-strongreject`), discovered through the `aisc_report.tools` entry point with a **generic table
   fallback** for a tool without a renderer. A tool renderer that raises degrades to the generic table,
   as in the pilot.
3. **cairosvg for SVG logos.** The cover logo and any SVG image is prepared with the pilot's
   `svg_print.for_print` and drawn by WeasyPrint/cairosvg, not by a browser.
4. **No browser, no new service.** Rendering stays in-process in the backend. The existing
   `REPORT_SERVICE_URL` seam remains for a deployment that prefers the pilot service.
5. **New top-level production dependencies (the I8 decision).** `weasyprint`, `cairosvg`, `jinja2`,
   `markupsafe`, `lxml`, `defusedxml`, `pillow` (WeasyPrint/cairosvg/SVG need the last four), and the
   interface's own `markdown-it-py` and `nh3` (rich text), plus the vendored
   `aisc-report-plugin-interface` (+ the four plugin packages, vendored under
   `apps/backend/aisc_report_plugin_interface/` and `apps/backend/aisc_report_plugin_*/`).
   `python-docx` stays. `reportlab` is removed.

## Consequences

- **Cost:** WeasyPrint needs system libraries — `libcairo2`, `libpango-1.0-0`, `libpangocairo-1.0-0`,
  `libharfbuzz0b`, `libgdk-pixbuf-2.0-0`, `libffi`, `libxml2`, `libxslt1.1` and a font (DejaVu). The
  backend image is Alpine, so the runtime stage gains `RUN apk add --no-cache pango cairo gdk-pixbuf
  fontconfig ttf-dejavu …`. The image grows and the build gains an apt/apk step; no browser is added.
- **Fidelity:** the pilot's templates, CSS and plugin ABI are used verbatim, so a rendered report
  matches the pilot's structure and styling, and each tool's section is drawn by its own plugin.
- **Guard:** none added; `tests/architecture` is unchanged (5 passed, 3 xfailed, 0 failed).
- **Removal condition:** if a report must be produced without the cairo/pango system libraries, the
  `report_service.generate` seam allows pointing `REPORT_SERVICE_URL` at an external renderer; the
  in-process renderer is then unused and can be dropped. Revisit if WeasyPrint's dependency footprint
  becomes unacceptable for the backend image, or if the pilot renderer diverges and vendoring drift
  outweighs the seam.
