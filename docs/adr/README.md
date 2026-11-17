# Architecture decision records (ADRs)

An ADR records a **decision that changes or waives an invariant** in [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md).
Ordinary code changes do not need one; a change that moves a boundary, adds a service/database/datastore,
or breaks an invariant does.

- One file per decision: `NNNN-short-title.md` (next number, zero-padded).
- Copy [`0000-template.md`](0000-template.md).
- Once **accepted**, an ADR is not edited. To change it, write a new ADR and mark the old one
  `superseded by NNNN`.
- An ADR that waives an invariant names the **guard allowlist entry** it corresponds to and the condition
  under which the waiver is removed.
- Link the ADR from the PR: *"breaks I<n>; see ADR NNNN."*

## Accepted decisions

- [0001 — Mainline-first consolidation](0001-mainline-first-consolidation.md): one best-effort immudb
  audit writer, mainline-only upgrades and isolated Superset cache.
- [0002 — Unified-app-first feature port](0002-unified-app-first-feature-port.md): superseded by 0003;
  historical rationale for deferring self-contained dispatch and the run-local door.
- [0003 — Frozen unified-app integration](0003-frozen-unified-app-port-and-worker-boundary.md):
  selective mainline integration, rewrite unshipped migrations, immediate plugin environment boundary,
  deny-by-default ORM access and pragmatic pilot UI review. Supersedes 0002, not 0001's audit decision.
- [0004 — Reporting renderer](0004-reporting-renderer-dependencies.md): **superseded by 0005**; its
  in-process `reportlab` choice is withdrawn (it reproduced the information, not the pilot's renderer).
- [0005 — Report renderer](0005-report-renderer-weasyprint-and-plugin-abi.md): adopt the pilot's
  WeasyPrint/Jinja renderer, CSS and cairosvg logos, and the `aisc_report_plugin_interface` ABI with the
  bundled `aisc-report-plugin-*` tool renderers; `reportlab` is dropped. The I8 decision for the E5
  reporting dependencies, written before they are added.

Worker-ready epics, dependency gates and detailed issue bodies: [`../refactor-issues.json`](../refactor-issues.json).

The point is to make "someone ran ahead" into "the team decided", with a cost and an exit — cheaply.
