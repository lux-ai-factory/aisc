# Refactor status and deviations — integration branch

**Branch:** `integration/int-01-frozen-unified-app`
**Date:** 2026-11-17 · **Owner:** coordinator (INT-01 #103); baseline/docs: DOC-01 #121

This branch is the **main-based selective integration** of the frozen `feat/unified-app` commits. It is
a **working branch for local testing**, not a release. For this phase the architecture guards and ADRs
are treated as **guidelines**: where the merged tree does not satisfy an invariant, the deviation is
recorded here and owned by a later issue instead of blocking the merge. Refinement happens after the
branch is testable end to end.

## What is on this branch

- Parent cut from `master` @ `58c1861c3839aa500e67795ad3b64a8561593371` (not the `feat/unified-app`
  parent tree `256712e`, which is reference only).
- Five frozen merges pinned:
  - `apps/backend` `37d4e733b94de89811296c9e5b22979aea83c587`
  - `apps/webapp` `7fd5e8ce2ef265559e241d4ce8598e220f9b45d5`
  - `apps/eval` `b0171dbd555f7b8095d77bc3703c31d4e4fd20e1`
  - `shared/plugin-interface` `30282a337c74e2f1781dc80bbeb8adf5a7dc7a86`
  - `shared/plugin-manager` `9ae73b27644af81f62a1f98ad77e3ee942073bd4`
- `apps/controls` `432301ce…` and `apps/qualification` `7253966…` stay at their **mainline** pins; their
  legacy stacks are reference-only and their retained features live in `backend`/`webapp`.
- Preserved byte-identical to `master`: published compose, local-build overlay, compose-validation CI,
  `e2e/`, `DEVELOPER_GUIDE.md`, `env.example`. No `e2e` file disappeared; no file was deleted by the merges.

## Verified in the build sandbox (no Docker available here)

- **Backend:** `uv run python manage.py migrate` on SQLite applies cleanly, including the compliance
  migrations `0020`–`0032`; `uv run uvicorn config.asgi:application` serves 130 API paths and
  create/list project works. The app **must run under ASGI** (uvicorn) — the Ninja logging hook reads
  `request.scope`, so Django's WSGI `runserver` 500s. The backend image already runs uvicorn.
- **Webapp:** `npm ci && npm run build` succeeds; `npm run preview` serves the app. API base is injected
  at container start (`VITE_API_URL=APP_API_URL` → `env.sh` substitutes `APP_API_URL`).
- **Compose:** `docker compose config -q` passes for the published / build / development files.

## Architecture guard / ADR deviations (recorded, not blocking)

The **v2** guard suite (`tests/architecture/`, landed by DOC-01) uses *named baselines*: a known finding is
recorded under its ADR and reported as `xfail`; a **new** finding fails. Run:
`uv run --no-project --with pytest python -m pytest tests/architecture -q -rxX` → **7 passed, 1 xfailed,
0 failed** on this tree (at acceptance; I1 and I11 have since been closed — see the acceptance section).

| invariant | state | evidence / owner |
|---|---|---|
| **I1** worker fetch mid-run | pass | the 5 findings are the **dispatcher** (`run_evaluation`) and `_embed_input_files` attaching inputs/settings **before** dispatch, plus status reconciliation in `finalize_evaluation`. `run_plugin` is self-contained, so I1 holds; closed by EXEC-01a #120: the fetches moved into `aisc_eval/dispatch.py` at dispatch time and the worker performs none. ADR 0003 / EXEC-01 #120 |
| **I9** domain-slice module | pass | `apps/qualification`, `apps/controls` vertical slices **retired** (submodules removed); their behaviour lives in `backend`/`webapp`. No `xfail` remains |
| **I11** no step containers | pass | the one-shot `make_buckets` bucket-init containers were removed from `docker-compose.yml` and `docker-compose-infra*.yml` (REL-02); buckets are created by the documented one-off `scripts/make-buckets.sh` |
| **I2** plugin child env allowlist | satisfied | `plugin_child_env()` allowlist (eval conformance fold) |
| **I7** outbound scrub | satisfied | `aisc_eval/utils/scrub.py` on stdout/stderr/artifacts |
| **I3 / I4** plugin-interface independence, one deployment contract | pass | — |

Baselines were **re-recorded for this merged tree** (DOC-01), replacing the docs-branch function/file
names with the ones this tree actually has; the sets shrank, and each entry carries source evidence in
`tests/architecture/test_invariants.py`.

## Deviations to revisit later

1. `apps/eval` carries the `refactor/architecture-consolidation` conformance merge in addition to the
   frozen pin (this satisfies I2/I7 and the I1 dispatch pattern). **Deviates from ADR 0003**, which
   deferred I1 to EXEC-01 #120 and preferred the narrow **SEC-01 #104** patch — kept so the merged worker
   is functional and safer. Re-confirm scope, or keep it and retire the SEC-01 patch.
2. `docs/patches/eval-plugin-child-environment.patch` is now on the branch; SEC-01 #104 should confirm it
   is already applied by the eval fold.
3. Optional-domain feature parity (connections/adapters, evidence map, report composer, catalogue) and the
   pilot look/feel launcher (landed as the `homepage/` reference) are the E3–E5 port.

## E4 feature parity — evidence map and connections (EVD-01 #114, CON-01 #112)

Two passes are on this branch: the first landed EVD-01 and CON-01
(`apps/backend` EVD-01 `0eed571`; `apps/webapp` EVD-01 `94f5ddb`), the second
answered audit iteration 2's verdict that CON-01 parity was incomplete: the
pilot's allowed-hosts guard was missing, and the plugin-environment gate (ADR
0003 §4) had only been checked for the run, not for the installer. Second pass:
`apps/backend` `f3b1dd7`, `apps/webapp` `dbad518`, `apps/eval` `a5ecbb4`.

**EVD-01 — versioned evidence map (done).** The pilot's `homepage/evidence-map.html`
is re-expressed as a React page (`apps/webapp/src/pages/EvidenceMapPage.tsx`,
`/projects/:name/evidence-map`, linked from the Collect evidence hub), backed by
real endpoints the frozen backend did not have:

- `GET /projects/{pid}/evidence` (latest AI-card version, or `?version=<pid>`),
  `PUT /projects/{pid}/evidence/links` (whole-set replace), `POST
  /projects/{pid}/evidence/review`. Model `EvidenceLink` + `EvidenceReview`
  (migration `0033`); the matrix itself is computed on read and never stored.
- Tests come from the version's evaluation plugins, controls from the checklist
  submissions, objectives from step 2's selection; coverage/gaps/readiness reuse
  `scoring.py`. Project-scoped: stranger 404, viewer reads, editor writes.
- Older versions are read-only; carry-forward *offers* the previous version's links
  and writes them only on an explicit copy; a review must be by someone who made
  none of the version's links and is invalidated by any link change.
- **The two filters.** The page carries the pilot's `Gaps only` and `Priority only`
  checkboxes (`EvidenceMapPage.tsx`, `data-testid="gaps-only"` / `"priority-only"`),
  applied to the payload exactly as `homepage/evidence-map.html` applies them:
  `(!gaps || (!o.linked && !o.stale)) && (!prio || o.priority)`. So they are a view
  over the map, not a second endpoint — the three fields they read are the server's:
  * `priority` is earned, never defaulted: the risks the assessor bound to the
    objective (a rating of High or worse, i.e. impact x likelihood >= 10, makes it
    key by default, within a budget of seven) or an explicit key choice
    (`services/control_objectives.py::prioritise`, called by
    `services/evidence_map.py::_priority_keys`);
  * `linked` is whether a saved link names the objective;
  * `stale` is set for an objective this version no longer selects but a saved link
    still names (`"not selected"`, or `"removed"`/`"deleted"` for a tile that has
    gone) — and such an objective is deliberately *not* a gap.
- **Evidence for the filters.** `apps/backend/aisc_backend/tests/routers/
  test_evidence_router.py::test_priority_and_stale_feed_the_gaps_and_priority_filters`
  (fields and the row sets they yield: a Critical risk makes O1 key, a Low one
  leaves O2 unkeyed, no risk leaves O3 unkeyed, O4 is stale while a link keeps it on
  the map, coverage `{linked: 2, objectives: 4, gaps: 2}`), and
  `apps/webapp/src/pages/EvidenceMapPage.test.tsx` — a realistic four-objective
  payload and ten tests: the coverage line and all four rows; the filters pinned by
  the row set they leave (`Gaps only` → `[O1]`, `Priority only` → `[O1, O3]`, both →
  `[O1]`, and back); linking a cell, saving a note and unlinking through the API;
  the platform's refusal shown and the map left as it was; a viewer reading the map
  and the filters while writing nothing; independent review; carry-forward.

**CON-01 — connections, adapters and helpers (done).** Rewritten against the pilot's
own contract instead of the frozen `AIComponent` fields:

- Models `Connection`, `Helper` and `RunBinding` (migration `0034`), a connection
  being a protocol the adapter registry dispatches on (`rest`, `openai`, `a2a`,
  `oip`), an endpoint, the protocol's own fields, and the component it targets.
- `apps/backend/aisc_backend/adapters/` ports the pilot's request builders and
  response parsers: `rest` (templated body, JSON-path answer, refusal match),
  `openai` (chat completions, tool-call/logprob capabilities), `a2a` (JSON-RPC
  `message/send`, artifacts, `.well-known/agent-card.json` discovery) and `oip`
  (KServe v2 infer). `services/connections.py` describes an adapter for the UI.
- `GET/PUT/DELETE /projects/{pid}/connections[/{name}]`, `POST …/{name}/target`,
  `POST …/{name}/test` (one real call through the adapter, as a test would make it)
  and `POST …/{name}/discover`; `GET/PUT/DELETE /projects/{pid}/helpers[/{name}]`
  with `POST …/{name}/test`; `GET/PUT /projects/{pid}/runs/{plugin_pid}/bindings`
  snapshots the adapter/version and the helper a run used.
- Keys and secret header values live **per project** in the existing encrypted
  `ProjectConfig` secret store (`category=secrets`, keys `connection:<name>:key`,
  `connection:<name>:header:<header>`, `helper:<name>:key`). Every response reports
  only *that* a key is stored and the header *names*; the value never leaves the
  backend. `AIComponent.json_value` no longer holds connection keys.
- React: `/projects/:name/connections` is the full editor (the protocol's fields,
  key, secret headers, advanced headers/timeout, Try, agent card, target link,
  remove) and `/projects/:name/helpers` the helper models (endpoint, roles, key,
  Test), both in the Project menu; Try/Test call the real endpoints.

**CON-01, second pass — the allowed-hosts guard (done).** A connection may call any
public address; an internal one — a private network, the Docker host, a machine on
the LAN — is refused unless the project lists it or the stack allows it for every
project. Ported from the pilot as a *door* rule, read immediately before every call
out (so a change applies to the next call with no restart):

- `aisc_backend/services/allowed_hosts.py`: the rules, pure and database-free
  (`normalize_entry`, `is_loopback`, `is_metadata`, `is_internal`, `refusal_for`,
  `is_never_allowed`), plus `project_entries`, `floor_hosts` and `guard_url`.
  `CONNECTIONS_ALLOWED_HOSTS` is the stack-wide floor (the pilot's `floor` rows);
  `CONNECTIONS_STACK_HOSTS` names the deployment's own services.
- `AllowedHost` (project, host, note, `updated_at`, `updated_by`; unique per
  project) with `GET/PUT/DELETE /projects/{pid}/allowed-hosts[/{host}]`: a viewer
  reads, an editor writes, every change is audited, and an entry that names a class
  which can never be reached is returned `denied` with the reason instead of being
  quietly usable. Loopback, cloud metadata and the deployment's own services can
  never be listed, and saving a connection or helper refuses them where they are
  typed.
- The guard is consulted by `POST …/connections/{name}/test`, `…/{name}/discover`
  and the helper test; a refusal is answered in the same shape as a failed Try, and
  it never opens a socket.
- React: the pilot's `#allowed-hosts` section is an accordion at the foot of
  Components and connections (`src/components/AllowedHostsSection.tsx`,
  `src/lib/allowedHosts.ts`).
- `RunBinding.adapter_version` now records the revision of the adapter a run used
  (`adapters.BUILTIN_VERSION`, or an installed adapter's own version) instead of an
  empty string.
- Evidence: `test_allowed_hosts.py` (the rules, 19 cases),
  `tests/routers/test_allowed_host_router.py` (CRUD, roles, audit, denied rows),
  the connection/helper router suites routed through the guard,
  `tests/integration/test_mock_targets_smoke.py` with `tests/local_target.py` (a
  native REST target and a bespoke A2A target on the machine's own address: the
  recorded request bodies, a file-shaped input recorded by sha256, the adapter
  version in the run binding, and a refusal before any request leaves), and
  `apps/eval/tests/test_installer_under_allowlist.py` (the installer's own
  subprocesses take the allowlist, and a real install and run succeed with nothing
  but the allowlist).

### Left undone / deviating (E4)

1. **Helper bindings are recorded, not shown.** `RunBinding` is written and read over
   the API, and its snapshot is proven not to follow later connection edits, but no
   page yet displays "what this run used" — that belongs with the run/execution UI.
   Owner: E5.
2. **ADR 0003 §4, one spawn point left.** The eval worker's installer and run
   subprocesses now take the plugin allowlist. The *plugin-manager* keeps its own
   installer (`shared/plugin-manager/src/aisc_plugin_manager/uv_client.py`,
   `uv_install`), reached from the backend's plugin/catalogue routers when a
   registry-sourced plugin is loaded; it still inherits its calling process's
   environment. Closing it needs a `child_env` hook through `AiscPluginLoader` — a
   third submodule — so it is recorded here rather than half-done. Owner: SEC-01
   #104 or the plugin-manager owner.
3. **Deviation from ADR 0003, recorded:** `RunBinding.adapter_version` was defined
   but always written empty; it now carries the built-in revision (`1`). This
   extends a snapshot the ADRs treat as frozen, so it is called out explicitly.
4. **`0034`/`0035` collapsed.** The first pass committed `0034_aicomponent_adapter_*`
   (added `AIComponent.adapter`/`adapter_version`/`helper_role`) and
   `0035_remove_aicomponent_adapter_*` (removed them again). Both are gone:
   `0034_connections_helpers_bindings_and_allowed_hosts` is the single migration.
   Django records migration *names*, so a database that applied the old pair must be
   rebuilt, or the old names `migrate --fake`d.
5. **The pilot launcher stays a reference.** `homepage/*.html` (connections,
   evidence map, `theme/brand.json`) is the look/feel reference for the port and is
   never shipped as the app; the React pages are the product.
6. **UI-02 and the report composer are untouched.** This note covers E4 (EVD-01 and
   CON-01); the four-column hub (UI-02) and the report composer remain as previously
   landed.

**Guards:** `5 passed, 3 xfailed, 0 failed` — **no baseline grew** for any of the
above (`uv run --no-project --with pytest python -m pytest tests/architecture -q -rxX`).

**Verified on this tree (commands and their output):**

```
$ cd apps/backend && uv run python manage.py test
Ran 271 tests in 7.218s
OK

$ DB_ENGINE=django.db.backends.sqlite3 DB_NAME=/tmp/fresh.db uv run python manage.py migrate   # empty file
  Applying aisc_backend.0033_evidencereview_evidencelink... OK
  Applying aisc_backend.0034_connections_helpers_bindings_and_allowed_hosts... OK
$ uv run python manage.py showmigrations aisc_backend | tail -2
 [X] 0033_evidencereview_evidencelink
 [X] 0034_connections_helpers_bindings_and_allowed_hosts      # no 0035: the churn pair is collapsed
$ uv run python manage.py makemigrations --check --dry-run
No changes detected

$ cd apps/webapp && npm run build
dist/index.html                     1.14 kB │ gzip:   0.55 kB
dist/assets/index-limjIS5C.css     30.83 kB │ gzip:   6.76 kB
dist/assets/index-G5kGtiql.js   2,425.30 kB │ gzip: 745.13 kB
✓ built in 6.45s

$ npx vitest run
 Test Files  32 passed (32)
      Tests  181 passed (181)

$ cd apps/eval && uv run pytest -q
28 passed

$ cd ../.. && uv run --no-project --with pytest python -m pytest tests/architecture -q
5 passed, 3 xfailed
```

The counters this pass moved: backend 270 → 271 (the filter-fields test: priority
from the risk register, staleness from the selection, and the row sets they yield),
webapp 177 → 181 (the fixture went from two objectives to the four a real map
returns, and the page gained the filter row-set, note/unlink, refusal and viewer
tests), guards and eval unchanged.

## E5 reporting parity (REP-01 / REP-02)

Ported the pilot's reporting onto the **existing** integration branch (no merge of `pilot`). The
existing report router (`GET /{pid}/reports`, `POST /{pid}/reports/generate`, `/report-settings`,
`/reports/{report_pid}`, `/reports/{report_pid}/pdf`) was **extended, not replaced**.

**REP-01 — layouts, blocks, immutable snapshot.**

- New `ReportLayout` (ordered `blocks`, `show_index`, `numbering`, `revision`) + `Report` gains
  `project`, `layout`, `layout_revision`, `snapshot_checksum`, `document_checksum` and `document_pdf`
  (migration `0035_reportlayout_and_snapshot_checksums`).
- `services/report_blocks.py`: the pilot's block vocabulary as a registry with per-block option
  schemas, `validate_blocks` (unknown type / duplicate instance / bad enum → 422), `outline`
  (chapter numbering, appendix letters) and **five built-in layouts** (Summary, Management overview,
  Assessment report, EU AI Act, Technical dossier). `MAX_BLOCKS=50`.
- `services/report_snapshot.build_snapshot` now freezes the selected AI-card **version**, the evidence
  map's **coverage** of that version (from `EvidenceLink`/`EvidenceReview`, with a `stale` flag for a
  link the matrix no longer selects), the layout and its blocks, the picked evaluations and sections,
  and the project/system/controls/objectives — all read from the ORM **once at generation time**. The
  snapshot is stored on the `Report` row with a SHA-256 checksum; every read (`/reports/{pid}`,
  `/snapshot`, `/pdf`) is served from it, so a published report does not change when the project does.
- New layout endpoints: list (built-ins first), create, get, update (revision bump), delete,
  duplicate (fresh instance ids), export/import (portable file), preview (HTML, never saved),
  `report-block-types` (the composer palette).

**REP-02 — real PDF/Word and a React composer.**

- `services/report_render.py` renders a real **PDF** (`reportlab`) and **Word** (`python-docx`) from
  the frozen snapshot; `report_service.generate` prefers an external renderer when
  `REPORT_SERVICE_URL` is set and otherwise renders **in-process** — the old HTML-summary fallback is
  gone, so a `pdf`/`docx` request is always a real document. A Word report also stores a PDF companion
  so `/pdf` always streams a PDF; the primary document is at `/reports/{pid}/download`.
- `pages/ReportPage.tsx` is now a composer: layout cards (built-ins + project), an ordered block
  outline (add from the palette, move, remove, edit options), HTML preview, and a generate dialog with
  layout, AI-card version, evaluations, sections, period and PDF/Word. It uses the existing brand
  classes (`.brand-block`, `.brand-step`, `.brand-mono`); the pilot's static `homepage/` was reference
  only, not shipped.

**Deviations / left undone (owned by later issues, not blocking).**

- **ADR ordering (process deviation).** The first reporting dependencies (`reportlab`, `python-docx`)
  landed on this branch in `74b752e` **before** the I8 ADR that decided them (`cbab369`, ADR 0004).
  I8 requires the decision before the dependency. Corrected by withdrawing that ADR: ADR 0004 is marked
  *superseded by ADR 0005*, and ADR 0005 (the pilot WeasyPrint/Jinja renderer + report-plugin ABI) is
  written **before** the renderer dependencies below are added, so the ordering holds for them. The
  `reportlab` dependency is removed.

- **Renderer engine differs from the pilot.** The pilot renders HTML→PDF with **WeasyPrint** (system
  cairo/pango libs) plus `python-docx`; this port renders with `reportlab` + `python-docx`, no browser
  and no system libs. Recorded as the I8 decision in [`adr/0004-reporting-renderer-dependencies.md`](adr/0004-reporting-renderer-dependencies.md).
  **Not yet ported:** the pilot's Jinja HTML/CSS template fidelity, `cairosvg` SVG logos and the
  per-tool plugin renderers (`aisc-report-plugin-*` via the `aisc_report.tools` entry point). The
  *information* of each block is retained; the exact styling is not. ADR 0004 names the removal
  condition (adopt WeasyPrint/templates as the in-process renderer if fidelity becomes a requirement).
- **`report-settings.default_format` now also accepts `docx`** (was `pdf | html`); the existing
  bad-format test was updated to use `rtf` and a new `docx`-default test added.
- **Local-model exclusion has no equivalent.** The pilot could exclude a local model; the unified app
  has no such concept, so a report is scoped to project + selected version + picked evaluations.
  Behavioural equivalent not required for parity; noted so it is not silently assumed done.
- **Version/history surfacing** lives in the composer (version select + past-report cards), not yet
  surfaced from the evidence hub; the pilot's `report-composer`/`report-generator` services are **not**
  shipped (the backend owns layouts and rendering).
- **Reports generated before this change** have no `layout_id`/checksums and no `document_pdf`; they
  still open (their stored bytes are served for a `pdf`-format report).

**Verified on this tree (commands and their output):**

```
$ cd apps/backend && uv run python manage.py test
Ran 297 tests in 8.293s
OK                                   # 271 → 297 (report layouts, blocks, snapshot, render, versions)

$ DB_ENGINE=django.db.backends.sqlite3 DB_NAME=/tmp/fresh35.db uv run python manage.py migrate
  Applying aisc_backend.0035_reportlayout_and_snapshot_checksums... OK
$ uv run python manage.py makemigrations --check --dry-run
No changes detected

$ cd apps/webapp && npm run build
dist/assets/index-Dhd83SV1.js   2,434.09 kB │ gzip: 747.17 kB
✓ built in 6.46s

$ npx vitest run
 Test Files  32 passed (32)
      Tests  190 passed (190)        # 181 → 190 (composer + layout/preview/generate lib tests)

$ cd ../.. && uv run --no-project --with pytest python -m pytest tests/architecture -q -rxX
5 passed, 3 xfailed                  # unchanged baseline, 0 failed
```

## E5 follow-up: the pilot renderer, its dependencies and the plugin ABI (REP-02)

This section supersedes the two "Deviations" bullets above that described the renderer as
`reportlab`-based and the Jinja/CSS fidelity, SVG logos and per-tool renderers as "not yet ported".
They are now ported. Nothing below changes REP-01.

**Dependency and runtime inventory, taken *before* anything was added.** The pilot's renderer is
`report_renderer/` in the pilot repo: a Jinja environment over `templates/document.html.j2` and
`blocks/templates/*.j2`, `templates/report.css` + `templates/css/*.css`, WeasyPrint for PDF,
`python-docx` for Word, `cairosvg` for SVG rasterisation, `nh3` for the rich-text commentary,
`markdown-it-py` for the free-text/commentary markdown, and the `aisc_report_plugin_interface` /
`aisc_report_plugin_*` distributions reached through the `aisc_report.tools` entry point. System
runtime needs: `pango`, `cairo`, `gdk-pixbuf`, `libffi`, `fontconfig`, `harfbuzz` (WeasyPrint and
cairosvg) and a font (`ttf-dejavu`) for the CSS font stacks — all added to the backend `Dockerfile`
runtime stage. **No browser and no Chromium**, per ADR 0005: WeasyPrint draws CSS itself and the
renderer fetches nothing (only `data:` URIs are read).

**What is now ported.**

- **The ABI, vendored verbatim:** `aisc_report_plugin_interface` (INTERFACE_VERSION 2) and the four
  tool plugins `aisc_report_plugin_{langbite,mlareject,promptfoo,strongreject}`.
- **`aisc_backend/report_renderer/`**: `document.py` (snapshot → sections → the pilot's
  `document.html.j2`), the pilot's `blocks/templates/` and `templates/css/`, `pdf.py` (WeasyPrint,
  `data:` only), `svg_print.py`, `style.py`, `structure.py`, `errors.py` (all vendored unchanged),
  and `docx.py` (the Word export).
- **`report_renderer/tools_abi.py`**: the renderer registry (the installed `aisc_report.tools` entry
  points **plus** the four bundled renderers), matching by normalised tool name, a read-only
  `ToolRun` built from the ORM (observations, measurements, components, artifacts), and the pilot's
  generic measurements table as the fallback for a tool without a renderer. Runs on a local model
  are left out here as everywhere else (`services.report_local_runs`).
- **CSS composition** is the pilot's: `report.css` + the `@page` rule (header, footer, marking,
  "Page N of M") + `style.css_overrides(look)` + the feature CSS the document uses
  (`commentary`/`chapters`/`marking`/`key_figures`/`chart`/`toc_pages`/`numbering`). Charts come from
  the interface's SVG (`charts.svg`); the cover logo is an SVG or raster `data:` URI, run through
  `svg_print.for_print` first, and an SVG with an embedded external resource is refused.
- `services/report_render.py` now delegates to the renderer (async `render_document`); `reportlab`
  is gone. The `REPORT_SERVICE_URL` seam is retained: an external renderer still wins when set.
  *(Superseded: [ADR 0008](../adr/0008-report-renderer-one-engine-in-backend.md) withdraws that seam
  and the vendored per-tool renderer packages — one in-backend engine, per-tool fragments in the eval
  plugin.)*

**Deviations and things left undone.**

- **"Observations not tied to a tool" is not printed.** The pilot's Test-results block prints the
  observations its engine could not attribute to a run. The unified app stores one observation per
  tool tag on the evaluation, so it cannot tell an untagged observation from a run's; the block
  prints nothing there instead of attributing it to the wrong run. Cosmetic; recorded, not blocking.
- **The cover's heading is empty, not "Cover".** The pilot's `document.html.j2` prints
  `<h2>{title}</h2>` for a section whose `kind` is unset, and the pilot gives the cover the title
  "Cover" (from the block class). This port keeps the cover's `kind="cover"` and an empty title, so
  the page shows no stray heading. Deliberate; a one-line cosmetic difference from the pilot.
- **`docx` headers and footers are not ported.** The pilot's `margin_texts` feeds both the PDF
  `@page` rule and the DOCX header/footer; this port carries the marking, header/footer text and page
  numbers into the **PDF** only. The Word document has the report's content, not the running margins.
- **The Word export re-parses the section HTML** with the standard library's parser (headings,
  paragraphs, lists, tables, `data:` images; charts and inline SVG are skipped). The pilot has its
  own `html_to_docx`; this is an equivalent-in-kind, not byte-identical, implementation.
- **The pilot's `report-composer` / `report-generator` services are not shipped** (ADR 0005): the
  backend owns layouts, rendering and history, and the webapp composes against the existing report
  router. The pilot's static `homepage/` stays reference material — the look is re-expressed in the
  React app, not shipped as HTML.
- **`report-settings.default_format` still accepts `docx`** (as noted above); the pilot's Word
  output is likewise a first-class format.
- **Local-model exclusion** is unchanged from REP-01 (a real concept in the unified app, see above).

**Invariants reconciled rather than changed** (recorded, not silent):

- **I5 (a report is drawn from its snapshot, not from live data).** `document.build_sections` reads
  the evaluation rows **by pid from the frozen snapshot** to build the tool sections; no project
  state (card, controls, coverage, links) is re-read. The rendered bytes of a published report are
  therefore stable.
- **I8 (an ADR before a dependency).** ADR 0005 was written first and lists exactly the interface
  dependencies (`markdown-it-py`, `nh3`) and the no-browser/in-process decision; the renderer
  dependencies follow it. ADR 0004 remains superseded.
- **I10 (no browser/Chromium).** WeasyPrint + cairosvg only; `pdf.py` refuses every non-`data:` URL.
- **Guards unchanged:** 5 passed, 3 xfailed, 0 failed (no baseline grew).

**ADR 0008 follow-up (landed).** The renderer is now a single in-backend engine: the external
`REPORT_SERVICE_URL` seam and the `apps/report` service are withdrawn (never merged into this
branch), so there is one implementation of rendering, not two. The per-tool renderers that were
vendored under `apps/backend/aisc_report_plugin_*` are gone; each eval plugin now draws its own
run through `BaseEvaluationPlugin.get_report_renderer()` (langbite, promptfoo and strongreject
in their plugin repos; mlareject's renderer is staged for its repo). The ABI
(`BaseToolRenderer`, `ToolRun`, i18n/templating/charts) moved from the vendored
`aisc_report_plugin_interface` into the published `aisc_plugin_interface.report` (behind the
`[report]` extra, `aisc-plugin-interface` 0.4.0). A run whose plugin has no renderer still prints
the generic measurements table, so old plugins keep working. See
[`adr/0008-report-renderer-one-engine-in-backend.md`](adr/0008-report-renderer-one-engine-in-backend.md).

**Verified on this tree after the follow-up (commands and their output):**

```bash
$ cd apps/backend && uv run python manage.py test
Ran 317 tests in 10.7s
OK                                    # 297 → 317 (13 plugin/renderer + 7 comparison/exclusion)

$ rm -f /tmp/mig.sqlite3 && DATABASE_URL=sqlite:////tmp/mig.sqlite3 uv run python manage.py migrate
... Applying sessions.0001_initial... OK        # applies cleanly from empty

$ cd apps/webapp && npx vitest run
 Test Files  33 passed (33)
      Tests  193 passed (193)

$ npm run build
✓ built in 6.5s

$ cd ../.. && uv run --no-project --with pytest python -m pytest tests/architecture -q -rxX
5 passed, 3 xfailed                  # unchanged baseline, 0 failed
```

## E4 parity: qualification/objectives (QUAL-01 #113), scoped results (ANA-01 #115), catalogue (CAT-01 #122)

Continues the E4 port on the same branch (no merge restarted). What landed:

**QUAL-01 — the project-local custom objective code.** The pilot keeps a project's own objectives in the
project's *own* database, so two projects may each write the same local code. In the unified single DB the
old `objective_id` was **globally** unique, so the second project's `CX-1` was rejected (`409`) and no project
could use a code the catalogue already used. `ControlObjective.objective_id` is now unique **per project**
(two new constraints: `(project, objective_id)` and a partial unique on the seeded rows, migration
`0036_alter_controlobjective_objective_id_and_more`; the column widens to 32 chars so a prefixed local code
fits). A local code still may not repeat inside its project nor shadow the shared catalogue.
`test_catalogue_add_edit_delete_project_row` previously asserted the cross-project `409`; that expectation was
the wrong encoding of the pilot and is now inverted (another project's same code succeeds; the repeat and the
`O1` shadow are the `409`s).

**QUAL-01 — priorities: unticking a default key now sticks, and choices can be undone.** The matrix built its
key overrides as `{id: True}` for the stored list and fell back to the computed default for anything absent,
so unticking one of the default seven priority objectives silently reverted. A non-empty stored
`key_objectives` is now the assessor's complete answer (the objectives left out are off); an empty list still
means "no choice yet, use the defaults". New `DELETE /projects/{pid}/control-objectives/profile/keys`
("Undo priority choices", wired to a button on `ControlObjectivesPage`) clears the choices so the defaults
apply again. A regression test covers tick → untick → undo.

**QUAL-01 — rating bounds.** `PATCH .../risks/{pid}/rating` now enforces the pilot's 1..5 impact/likelihood
and the 1000-character rationale cap (both were unvalidated).

**ANA-01 — scoped results and the dashboard bridge.** `services/results_dashboard.py` + `routers/results.py`
serve the project's results scoped to a published AI-card version, and `routers/stats.py` takes the same
scope; the webapp `ResultsSection` (on `DashboardPage`) and `lib/results.ts` read it. Superset stays its own
process — this is only the bridge/link, not a new DB path.

**CAT-01 — one catalogue surface.** `routers/catalogue.py` gained a `kind` filter (`control` | `plugin`) and
returns the published catalogue site's URL (`APP_CATALOG_URL`) so the combined webapp page
(`src/pages/CataloguePage.tsx`, route `/projects/:project_name/catalogue`) can show tests and checklists
together and link out to the independently published catalogue, as the pilot's `catalogue.html` does.

### Not done (QUAL-01 remainder, recorded rather than silently dropped)

> **Superseded:** all five items below were closed on the same branch — see
> [E4 remainder closed](#e4-remainder-closed-the-qualification-agents-profiles-sets-and-the-card-snapshot-qual-01-113).
> The list is kept as the record of what the earlier commit left out.

These pilot behaviours were still absent at the time; they needed either a model/LLM path or a schema
owner's decision:

1. **Risk mapper "Suggest with AI"** (`docs/appendices/2-control-objectives.md` §3): no LLM client exists in
   the backend (no Ollama/`CONTROL_OBJECTIVES_LLM_*` integration), so the proposal endpoint, its quote
   validation against the risk chain and the three-attempt cap are not ported. Rating, scoring, manual
   linking and priorities are unaffected.
2. **Built-in objective profiles** ("Full AI Act" 50 / "Fairness and oversight" 10, first assessment defaulting
   to the latter): the exact 10-objective membership is not in the repo (only the appendix names it), so
   inventing it was left out. The single per-project profile + "Change profile" via
   `PUT .../control-objectives/profile` already works.
3. **Custom objective *sets*** (a project's own set with a code prefix, edited as a draft and published as
   fixed numbered versions): only per-project custom *rows* exist; set/version models are a schema change for
   the MIG-01 owner.
4. **Qualification**: the headless `qualification-prefill` document upload (text rules) and the
   `qualification-agents` card agent (suggest additions + self-critique) are not ported; the card, its
   version chain, node edits and the JSON-LD serialisation are (from the frozen port). Card **PDF/JSON
   download** still goes through the renderer rather than a `qualification-pdf` service.
5. **Engine component snapshot per card component** (the "changed in the engine since" flag) is not ported.

### Evidence

```bash
$ cd apps/backend && uv run python manage.py test
Found 329 test(s).
Ran 329 tests in 13.6s
OK                                    # 317 → 329 (+7 results router, +3 catalogue kind/url/scope, +2 objectives)

$ uv run python manage.py makemigrations --check --dry-run
No changes detected

$ cd apps/webapp && npx vitest run
 Test Files  35 passed (35)
      Tests  200 passed (200)          # 193 → 200

$ npm run build
✓ built in 8.1s

$ cd ../.. && uv run --no-project --with pytest python -m pytest tests/architecture -q -rxX
5 passed, 3 xfailed                    # unchanged baseline, 0 failed
```

## E4 remainder closed: the qualification agents, profiles, sets and the card snapshot (QUAL-01 #113)

The five items the section above recorded as *not done* are now in, on the same branch (no merge
restarted). The decisions behind them are [ADR 0006](../adr/0006-qualification-agents-and-objective-sets.md)
(`apps/backend` `557059d`, `apps/webapp` `39e6edb`).

**One model-resolution seam.** `aisc_backend/services/ai_assistant.py` is the single answer to "which
model does an assistant use": the project's own helper model first (by role, then its first helper),
the stack setting second (`CONTROL_OBJECTIVES_LLM_*`, `CARD_AGENT_LLM_*`), else `NoModelConfigured` —
which the endpoints answer as `503` rather than inventing an answer. The risk mapper's proposer now
goes through it (`services/risk_mapper.resolve_proposer` is that helper), so there is one rule, not
three. **A helper's endpoint is read through CON-01's allowed-hosts door immediately before the call**
(`guard_url`), answered as `400` naming the model; the stack setting is the operator's own
configuration, not project input, so it is not put through the project's allowlist.

**QUAL-01 — the risk mapper ("Suggest with AI", appendix 2 §3).** `services/risk_mapper.py` is a pure
decision function (no database): each proposal must quote the risk's own chain, unknown or repeated
objectives and wrong quotes are sent back for **at most three attempts**, what still fails is dropped
with its reason, and links a person made by hand survive unless "also replace objectives I linked by
hand" is ticked (an earlier *AI* run's links are replaced). `POST
/projects/{pid}/control-objectives/risks/mappings/suggest` validates, writes the surviving proposals
as `source="ai"` links, audits them, and returns `attempts`/`created`/`dropped`. The webapp's step 2
has the button, the tick and the run line (`describeSuggestion`).

**QUAL-01 — the two built-in profiles.** Full AI Act (every objective of the project's visible
catalogue) and Fairness and oversight (the objectives of the catalogue's own macro requirements
**REQ1 Human Agency and Oversight, REQ5 Fairness, REQ7 Accountability** = 10), with a first
assessment starting on the latter. The membership is **derived, not hard-coded**
(`services/objective_profiles.py`), so a changed catalogue cannot silently drift from the profile;
`GET .../control-objectives/profiles` returns both with the current one, and `PUT
.../control-objectives/profile` sets `profile_key`. This is where the earlier note said "the exact
10-objective membership is not in the repo" — it is: it is the catalogue's own macro requirements.

**QUAL-01 — custom objective sets.** `ObjectiveSet` (name, code prefix, editable draft) and
`ObjectiveSetVersion` (each published version `1..n`, frozen) with `GET/POST .../objective-sets`,
`GET/PUT .../objective-sets/{set_pid}`, `POST .../publish` (an empty draft is refused `400`),
`POST .../apply` (copies a published version into the project's own catalogue rows and selects them —
so the matrix, the evidence map and the report read them like any other objective; applying twice
updates, never duplicates) and `DELETE`. Every write is audited. The webapp has the profile chooser
and the sets editor (start from the catalogue, drop or add rows, publish, apply, delete).

**QUAL-01 — document pre-fill.** `services/qualification_prefill.py` reads `.pdf` (new dependency
`pypdf`), `.docx` (`python-docx`), `.txt`/`.md` with plain text rules — **no model** — matching each
questionnaire question's own wording, and `POST /projects/{pid}/qualification/prefill` (multipart,
optional `questionnaire_id`) answers with proposals only: field, value, the sentence that matched, the
line, plus the questions nothing was found for. **Nothing is stored.** The webapp's step 1 dialog
shows them for review, lets each be dropped, and offers the pilot's two modes (fill the empty fields /
replace the answers); `applyPrefill` is a pure merge, so what the person typed into fields the document
says nothing about is kept.

**QUAL-01 — the card agent.** `services/card_agent.py` answers about the card and *proposes* node
corrections, each of which must quote the person's words or the card (the same rule the risk mapper
uses); `POST /projects/{pid}/qualification/{qpid}/agent` returns the reply, the proposals and what it
left out. Applying a proposal goes through the **existing** node-correction endpoint, which rebuilds
the card and stores a new version — so there is still exactly one card write path (I3/I6), and the
webapp panel shows each proposal's quote with Apply/Dismiss and folds the new version into the page.

**QUAL-01 — the card components against the engine.** `CardComponentLink` records, per card component,
which engine AI component it stood for and a snapshot of what that component said when the card was
saved; `GET .../qualification/{qpid}/card-components` compares them on read and reports `changed` and
`missing`. The webapp shows "changed in the engine since" / "not in the engine".

### Still not done (recorded rather than silently dropped)

1. **A card correction has no sign-off step of its own.** Applying an agent proposal goes through the
   node-correction endpoint, which rebuilds the card and stores a new version, and the change is
   audited — but nothing in the repo asks a second person to accept the corrected version, so a
   reviewer reads the version chain rather than being prompted. If a sign-off is wanted it is a small
   addition to the node path, not new state.
2. **The sets' row editing is deliberately shallow in the UI.** A draft row can be added (ID, macro
   requirement, text) or dropped, and the draft can be started from the catalogue; the remaining
   catalogue fields (legal basis, sub-requirement label, assessment mode, target, standards grounding,
   notes) are carried through the API and the version chain but have no per-field editor. Owner: a
   MIG/UX follow-up; no backend work remains.
3. **A set's published version is not shown as a diff.** Versions are stored and returned
   (`versions[]`), and `published v<n>` is shown, but there is no side-by-side of two versions.
4. **The pre-fill's rules are ours, not the pilot's.** The pilot reads documents with its own text
   rules whose exact patterns are not in the repo; ours match each question's own wording. A
   deployment that wants the pilot's exact extraction needs those patterns.
5. **`pypdf` is the only new dependency** (ADR 0006). Nothing else changed shape.

> **Superseded (part 2):** items 2 and 3 were closed with code and items 1 and 4 were reclassified after
> checking the pilot — see
> [E4 remainder closed, part 2](#e4-remainder-closed-part-2-the-set-history-and-the-full-row-editor-qual-01-113-cat-01-122).
> Item 5 still holds.

### Evidence

```bash
$ cd apps/backend && uv run python manage.py test
Ran 403 tests in 11.7s
OK                                    # 329 → 397 (this work) → 403 (the door rule)

$ uv run python manage.py makemigrations --check --dry-run
No changes detected                   # migrations 0037, 0038, 0039 are committed

$ DATABASE_URL=sqlite:////tmp/fresh.sqlite3 uv run python manage.py migrate
# applies from empty, all migrations OK

$ cd apps/webapp && npx vitest run
 Test Files  39 passed (39)
      Tests  232 passed (232)          # 200 → 232: +15 lib, +4 card agent, +6 pre-fill, +7 profile/sets

$ npm run build          # ✓ built, tsc clean

$ cd ../.. && uv run --no-project --with pytest python -m pytest tests/architecture -q -rxX
5 passed, 3 xfailed                    # unchanged baseline, 0 failed
```

## E4 remainder closed, part 2: the set history and the full row editor (QUAL-01 #113, CAT-01 #122)

The five items the previous section recorded as *not done* are now all resolved: two closed with code, two
reclassified after checking the pilot, and one (the `pypdf` dependency) still standing — the answers are
written down here rather than left implied. The
catalogue's own record (what the pilot does, what we do, what is out and why) is
[refactor-catalogue-parity.md](refactor-catalogue-parity.md).

### Closed with code (QUAL-01)

**A set's published version is now compared, not just named.** `services/objective_sets.py` is the pure
decision (`diff_rows`: rows in, per-field differences out) and
`GET /projects/{pid}/objective-sets/{set_pid}/diff` serves it — with no version numbers it compares the
**last published version with the draft**, which is the question someone editing a set is asking;
`from_version`/`to_version` name two published versions instead, and an unknown number is a 404 rather than
a silently empty answer. Rows are matched **by `objective_id`**, so a reworded row reads as a *change* with
both values, not as a removal plus an addition. The webapp shows it under the set (`Changes since v<n>`,
`data-testid="set-diff-<pid>"`), naming the fields that moved. No new state: versions stay append-only
(ADR 0006's mechanism, unchanged), and the diff is a read.

**The set editor now edits every column the catalogue carries.** The "Add a row" dialog became add-or-edit
(all ten fields, per `SET_ROW_FIELDS`) and the draft chips open it on that row, so a row can be corrected in
place (`PUT .../objective-sets/{set_pid}` replaces it by its code) instead of only added or dropped. The
duplicate-code rule is checked in the dialog too, so a rename onto an existing code is refused before it
leaves the browser.

### Reclassified, with the evidence for it (not pilot gaps)

**The card-correction sign-off is not a parity gap: the pilot has no second-person step either.** Appendix 1
says "the card agent … drafts more nodes from your prose and, in a second role, critiques its own draft;
**you review what it proposes**" (`docs/appendices/1-qualify.md`) — one person reviews, and what they accept
is what the version chain and the audit entry record. Our behaviour is that, so a "second person accepts"
step would be a new governance requirement, not a port. It stays out of E4; if a deployment needs four eyes,
it is a small addition to the node path (a reviewer field on the corrected version), not new state.

**The pre-fill's text rules cannot be the pilot's, and the formats already are.** The leftover item read
"the rules are ours, not the pilot's"; the reason is now verified rather than assumed: the frozen
`apps/qualification` submodule carries **no document reader at all** (`services/` is the LLM client and the
card renderer), so the pilot's exact extraction patterns are genuinely absent from the repo — inventing them
would be guessing. Everything else in the pilot's sentence is in: the formats the pilot reads
(`.pdf`, `.docx`, `.txt`, `.md`, `.markdown` — `services/qualification_prefill.py` also takes `.rst`, `.csv`
and `.json`), text rules with no model, proposals only, and the pilot's "fill only the empty fields or
replace your answers" choice (`PrefillMode` = `empty` | `replace`).

### Catalogue (CAT-01)

`docs/refactor-catalogue-parity.md` records the pilot's capabilities against ours, verified against
`homepage/catalogue.html` and `docs/appendices/2-control-objectives.md`: one listing for both kinds, read
through live, installs that copy into the project, the `{meta, questions}` export and the link to the
published site are all ported. Two things are deliberately out and said so: the public/private catalogue
choice (a project's own copy is what installing into the project already gives it) and the step-3 filter by
the selected objectives' dimensions. The second is the one real catalogue gap: our objectives *do* carry the
dimension (`macro_requirement`), but the surface's catalogue items carry no dimension tag
(`services/controls_catalogue._mapped` maps topic/regulations/countries only), and the hosted catalogue
(`CONTROLS_CATALOG_URL`) is unreachable from this sandbox, so the tag section cannot be confirmed — a filter
keyed on a guess would show the wrong list. The exact change needed is written in that record.

### Left alone on purpose

* **No new migration, no new model, no new invariant.** The diff reads existing append-only versions; the
  row editor writes the same draft the endpoint already accepted. `makemigrations --check` says "No changes
  detected".
* **The private-catalogue table and a per-project catalogue copy** — see the parity record, exclusion 1.
* **The pilot's exact pre-fill patterns, and a second-person card sign-off** — see above; both are
  requirements additions, not ports.

### Evidence

```bash
$ cd apps/backend && uv run python manage.py test
Ran 448 tests in 15.6s
OK                                    # 403 → 448 (+10 this stretch: 6 diff service, 4 diff router;
                                      #  +35 the uncommitted ANA-01/CAT-01 work in this tree)

$ uv run python manage.py makemigrations --check --dry-run
No changes detected

$ DB_NAME=/tmp/e4fresh3.sqlite3 uv run python manage.py migrate     # from empty
Running migrations: … Applying sessions.0001_initial... OK          # all migrations apply

$ cd apps/webapp && npx vitest run
 Test Files  41 passed (41)
      Tests  246 passed (246)         # 232 → 246 (+5 this stretch: 2 row editor/diff UI, 3 set history api;
                                      #  +9 the uncommitted ANA-01/CAT-01 work in this tree)

$ npm run build
✓ built in 6.5s                       # tsc clean

$ cd ../.. && uv run --no-project --with pytest python -m pytest tests/architecture -q -rxX
5 passed, 3 xfailed                   # unchanged baseline, 0 failed
```

_This section was written by an AI agent (OpenHands) on behalf of the requester; the two reclassifications
above are proposals for the owner to confirm (recorded on #113)._

## E4 remainder closed, part 3: the step-3 catalogue filter, and what is still open (CAT-01 #122)

The one catalogue parity gap part 2 recorded — step 3 filtering the catalogue by the dimensions of the
project's selected objectives — is closed. Same branch, no merge restarted; the parity record
([refactor-catalogue-parity.md](refactor-catalogue-parity.md), exclusion 2) carries the detail.

**The blocker was a section name, and it is now measured rather than guessed.** The hosted catalogue's
items tag dimensions in a `dimension` section, and hang sub-dimensions under one in
`controls_subdim`/`testing_subdim` with the dimension in `parent_dimension_slug`. `services.dimensions`
is the new *single* table tying our eleven AI Act macro requirements to the catalogue's eleven slugs (with
the catalogue's own labels), `services.evidence_map` reads its `dimension_of` (its private copy of the
table is gone — that is the "no second path" rule applied to a lookup, not a module), the catalogue surface
serves the vocabulary as `CatalogueOut.dimensions` and each item's tags as `CatalogueControlOut.dimensions`,
and `GET /projects/{pid}/control-objectives/dimensions` answers what the project's selected objectives
imply. The webapp's one exploration dialog gained the pilot's "For this project" switch (on by default, in
the same listing, not a second one), the pilot's note when nothing is selected, and the dimension chips the
pilot's sidebar offers; both narrow the existing `filterCatalogue` call.

**No invariant changed, so no ADR.** No model, no migration (`makemigrations --check`: "No changes
detected"), no second store, no second listing: the filter narrows what the one listing already returns,
and the vocabulary is served rather than duplicated in the UI.

### Fixed on audit: the pushed submodule commits were not in the branch

The previous stretch pushed `apps/backend` and `apps/webapp` commits (the pilot-prefill vendoring and its
webapp wiring) but the parent's gitlinks still recorded the commits *before* them, so a fresh clone of the
branch did not contain that work. This stretch bumps both gitlinks to the pushed submodule tips. Recorded
because "pushed" and "in the branch" are different claims, and only the second one is what a reader
checking out the branch gets.

### Still open (recorded, not papered over)

1. **The plugin ("tests") side of the catalogue is not dimension-filtered.** The pilot filters both kinds;
   our tests come from this installation's plugin loader, which carries no dimension tag, so a project
   filter would hide every plugin rather than narrow them. The dialog offers no switch on its plugin-only
   view. Closing it needs the hosted catalogue's test tags on the loader path — a plugin-listing question
   (which catalogue is authoritative for a plugin package), not a dimension-table one.
2. **The dimension chips offer the eleven dimensions, not the catalogue's sub-dimension tree.** The
   pilot's sidebar nests `controls_subdim`/`testing_subdim` children under each dimension. Our chips are
   the objectives' dimensions — the only vocabulary "for this project" can mean — and an item is matched
   through its sub-dimension to its parent, so selecting a dimension still finds a sub-dimension-only item.
   Sub-dimension chips would need a tree built from live catalogue tags: a UX addition, not a parity block.
3. **ANA-01's dashboard link and bridge are still unit-tested only.** There is no Superset in this
   environment, so registration, the tile sync and the signed, scoped link are proven by
   `test_dashboard_bridge.py` (8), `test_dashboard_link.py` (10), `test_results_router.py` (10) and
   `test_dashboard_redis_compose.py` (9) rather than against a running dashboard. What *can* be executed
   on a host with no Docker daemon now is: `scripts/verify-dashboard-redis.sh --local` starts a real
   `redis-server` with the compose service's own configuration and checks it refuses a client with no
   password, takes the configured one, persists nothing, binds loopback only and keeps the password out of
   its command line. Its deployment half (which network the cache is on, who shares it, no published port)
   still needs a stack. This is a verification limit of the environment, not a known deviation.
4. **QUAL-01's two reclassifications still want the owner's word** (unchanged from part 2, restated so it
   is not lost): the card-correction *sign-off* (the pilot has one person reviewing, so a second-person
   accept would be new governance, not a port) and the pre-fill's *text rules* (the frozen
   `apps/qualification` carries no document reader, so the pilot's exact patterns are not in the repo and
   inventing them would be guessing). Both are recorded as proposals for the owner on #113; neither blocks
   parity as it stands. Item 5 of part 2 (`pypdf` is the only new dependency) still holds.

### Evidence

```bash
$ cd apps/backend && uv run python manage.py test
Ran 473 tests in 15.8s
OK                                    # 448 → 473 (+25 this stretch: 7 dimension table, 5 project
                                      #  dimensions router, 2 catalogue tags/vocabulary, …
                                      #  and the prefill-vendoring tests that were not in the branch before)

$ uv run python manage.py makemigrations --check --dry-run
No changes detected

$ uv run python manage.py migrate
No migrations to apply                 # nothing to apply; the tree's migrations are complete

$ cd apps/webapp && npx vitest run
 Test Files  42 passed (42)
      Tests  266 passed (266)         # 246 → 266 (+20: dimension filter, the switch/note/chips, page wiring,
                                      #  the dimensions read, and the prefill UI tests now in the branch)

$ npm run build
✓ built in 6.5s                       # tsc clean

$ cd ../.. && uv run --no-project --with pytest python -m pytest tests/architecture -q -rxX
5 passed, 3 xfailed                   # unchanged baseline, 0 failed

$ DASHBOARD_REDIS_PASSWORD=… scripts/verify-dashboard-redis.sh --local
ok   a client with no password is refused (NOAUTH)
ok   the password the service is given is the one it takes
ok   it keeps nothing (appendonly no): a cache, not a store
ok   it listens on loopback only (nothing published)
ok   the server's command line does not carry the password
the dashboard's Redis rule holds on this host: password-protected, loopback-only, storing nothing
note the deployment checks (its network, who shares it) were not run — they need a running stack

$ # the live catalogue, as the surface reads it (2026-11-17)
live checklists: 44
checklists with no dimension tag: 0
```

_This section was written by an AI agent (OpenHands) on behalf of the requester; item 4 above is a
proposal for the owner to confirm (recorded on #113)._

## E4 remainder closed, part 4: the plugin side and the sub-dimension chips (CAT-01 #122)

Items 1 and 2 of part 3's "Still open" list are closed on this branch (backend `7041295`, webapp
`2de1a26`), and the parent gitlinks are bumped to them. No invariant changed, so no ADR; no model and no
migration (`makemigrations --check`: "No changes detected").

* **The plugin side of the catalogue is dimension-filtered**, without a second listing: the catalogue's
  `type: test` item naming a package (`package_name`, or its slug with the historical `aisc-plugin-`
  prefix) supplies the dimensions the loader cannot, `_plugin_dimensions` indexes them from the one
  cached fetch (`_all_items`), and the plugin-only dialog now offers the "For this project" switch. A
  package the hosted catalogue does not list carries no dimensions and is hidden by a project filter —
  the pilot's own rule, recorded rather than worked around.
* **The dimension chips nest the catalogue's own sub-dimension tree** (`controls_subdim`/`testing_subdim`,
  parent in `parent_dimension_slug`), served as `CatalogueOut.subdimensions` and per item as
  `CatalogueControlOut.subdimensions`; a child chip narrows to the items carrying it, and the parent chip
  still matches a sub-dimension-only item.

What is still open from part 3: item 3 (the dashboard bridge is unit-tested only — there is no Superset
in this environment) and item 4 (the owner's word on QUAL-01's two reclassifications) are unchanged.
Item 5 of part 2 (`pypdf` is the only new dependency) still holds. The plugin side's narrowing depends on
the hosted catalogue naming a plugin's package in a `type: test` item; a plugin the hosted catalogue does
not list has no dimensions to filter by and is hidden when "For this project" is on. That is the pilot's
behaviour, not a deviation, but it is the one place a local-only plugin can disappear from a filtered
listing.

### Evidence

```bash
$ cd apps/backend && uv run python manage.py test
Ran 476 tests in 19.7s
OK                                    # 473 → 476 (+3: the sub-dimension tree, the plugin's test-item
                                      #  dimensions, and the plugin-only filter path)

$ uv run python manage.py makemigrations --check --dry-run
No changes detected

$ uv run python manage.py migrate
No migrations to apply

$ cd apps/webapp && npx vitest run
 Test Files  42 passed (42)
      Tests  273 passed (273)         # 266 → 273 (+7: plugin filtering, the sub-dimension chips,
                                      #  childrenOf)

$ npm run build
✓ built in 6.5s                       # tsc clean

$ cd ../.. && uv run --no-project --with pytest python -m pytest tests/architecture -q -rxX
5 passed, 3 xfailed                   # unchanged baseline, 0 failed
```

_This section was written by an AI agent (OpenHands) on behalf of the requester._

## E4 remainder — final verification and the ANA-01 bridge against a live Superset (QUAL-01 #113, ANA-01 #115, CAT-01 #122)

No merge was restarted and no port was redone. The three E4 issues were already on the branch at
`7b8005f` (backend `7041295`, webapp `2de1a26`, both pushed to their own
`integration/int-01-frozen-unified-app` branches); QUAL-01's sets, prefill and agents, ANA-01's scoped
results and bridge, and CAT-01's catalogue/sub-dimension work are as part 4 left them. This pass changed
no code, model or migration: it re-ran the whole verification on that tree and closed one item from part
3's "Still open" list — the dashboard bridge was "unit-tested only" and is now proven against a running
Superset. The only new artefact is this record.

### The bridge, live (part 3, item 3 — closed)

A real Superset 4.1.4 was started on this host with the branch's own `aisc_ext` + `superset_config.py`
(stock image configuration, SQLite metadata database, `AUTH_ENABLED=0`, the dashboard Redis on
`127.0.0.1:6390`), and the bridge was called over HTTP as the platform calls it:

```bash
$ curl -X POST $B/api/v1/aisc_project/<pid> ...                       # no token
401  {"message":"bridge token required"}
$ ... -H 'X-AISC-Bridge-Token: nope' ...                              # wrong token
401  {"message":"bridge token required"}
$ ... -H 'X-AISC-Bridge-Token: <token>' -d '{"slug":"ana01live","name":"ANA-01 live"}'
200  {"message":"registered"}
$ ... -X DELETE $B/api/v1/aisc_project/<pid> -H 'X-AISC-Bridge-Token: <token>'
200  {"message":"unregistered"}
```

The metadata database was read back between the two calls: the registered project's objects were all
present and tagged `aisc_project=<pid>` — connection `AISC Controls <hex>`, datasets
`engine_results_<hex>` and `controls_answers_<hex>`, roles `AiscProject_<hex>` and
`AiscProjectEditor_<hex>` — and the delete removed them. Registration, its idempotent upserts and
unregistration are therefore proven against real Superset models, not only against the dict store.

### Re-run evidence (this tree)

```bash
$ cd apps/backend && uv run python manage.py test
Ran 476 tests in 15.9s
OK                                    # unchanged from part 4

$ uv run python manage.py makemigrations --check --dry-run
No changes detected

$ rm -f /tmp/aisc-fresh.db && DB_NAME=/tmp/aisc-fresh.db uv run python manage.py migrate
# applies every migration from an empty database: OK (all "Applying ... OK")

$ cd apps/webapp && npx vitest run
 Test Files  42 passed (42)
      Tests  273 passed (273)         # unchanged from part 4

$ npm run build
✓ built in 6.5s                       # tsc clean

$ cd ../.. && uv run --no-project --with pytest python -m pytest tests/architecture -q -rxX
5 passed, 3 xfailed                   # unchanged baseline, 0 failed

$ DASHBOARD_REDIS_PASSWORD=… scripts/verify-dashboard-redis.sh --local
ok   a client with no password is refused (NOAUTH)
ok   the password the service is given is the one it takes
ok   it keeps nothing (appendonly no): a cache, not a store
ok   it listens on loopback only (nothing published)
ok   the server's command line does not carry the password
```

### Still not done or not verifiable here (recorded, not dropped)

1. **The plugin-tile sync has no live proof.** `PUT /api/v1/aisc_project/<pid>/plugins` answers 500 in
   this sandbox: its `latest_runs` read opens the project's own Postgres and there is no host named
   `postgres` to resolve (`psycopg2.OperationalError: could not translate host name "postgres"`), so the
   reply is an HTML error page rather than the bridge's JSON shape. Registration and unregistration do
   not touch the project database, which is why they could be proven. This needs the compose stack's
   project database, not a code change; the tile logic stays covered by its unit tests against the dict
   store.
2. **The signed, scoped guest link is still unit-tested only.** It is produced by the backend from the
   guest-token secret, so there is no dashboard to sign into in this sandbox.
3. **The deployment half of the Redis check is still unrun** (which network the cache is on, who shares
   it, no published port) — it needs a running stack, as part 3 said. The host half passes above.
4. **QUAL-01's two reclassifications still want the owner's word** on #113: the card-correction sign-off
   (the pilot has one reviewer, so a second-person accept would be new governance) and the pre-fill's
   text rules (the frozen `apps/qualification` carries no document reader, so the pilot's exact patterns
   are not in the repo). Unchanged from part 3, item 4; recorded as proposals, not gaps.
5. **CAT-01's one edge is pilot behaviour, not a defect**: a plugin the hosted catalogue does not list
   carries no dimensions and stays hidden when "For this project" is on — the pilot's own rule, kept as
   parity. It is the one place a local-only plugin can vanish from a filtered listing.
6. **`pypdf` remains the only new dependency** (ADR 0006).

_This section was written by an AI agent (OpenHands) on behalf of the requester; items 1–5 are recorded
for the owner, not silently dropped._

## E4 remainder, part 5: the tile body the dashboard actually reads, and a plugin the catalogue cannot dimension (ANA-01 #115, CAT-01 #122)

Two real gaps were found by reading the *other* side rather than this branch, and closed on the same
branch (no merge restarted). The decisions are recorded here rather than left implied; no invariant
changed, so no ADR, and no model or migration (`makemigrations --check`: "No changes detected").

**The dashboard's bridge read a body we did not send (ANA-01).** `aisc_ext.plugin_tiles.plugin_request`
— the validator behind `PUT /api/v1/aisc_project/<pid>/plugins`, read from the dashboard's own public
repository — takes `plugin`, `label`, `version`, `project_name` and `visualizations` (the plugin's
`metric_visualizations`), and `again` only when a tile someone deleted is remade. Ours sent
`{"plugin", "label", "charts"}`, so the dashboard's validator *accepted* the call and made a tile with
**no charts and no version** — a silent empty dashboard, which is worse than a refusal. `sync_tool` now
sends that contract (`apps/backend` `98dbd9c`) and `docs/ops/results-dashboard.md` documents it. The
client is still not wired into a page: the results page links the one dashboard with a signed, scoped
link per tool (part 3's design), and the pilot's per-plugin tiles are a dashboard-side concern that a
deployment wanting them can now ask for with a correct body.

**A plugin the catalogue cannot dimension is kept, not hidden (CAT-01).** A local-only plugin that
neither the hosted catalogue nor a `type: test` item names carries no dimension, so the project filter
dropped it — silently. This is the one place the pilot hides an item; the caller listed it before the
filter, so dropping it makes a working plugin disappear with nothing said. `filterCatalogue` now keeps
such an item under an active filter and the card carries a `no catalogue dimension` chip; an item that
*has* dimensions and none of ours is still filtered out (`apps/webapp` `347ec00`,
`lib/catalogue.unmatchedByDimensions`). This one **is** a deliberate deviation from the pilot: the
unified app prefers "show it, marked" to "hide it quietly". Owner may reverse it by dropping the
`unmatchedByDimensions` clauses.

### Still open (unchanged from part 3/4, restated so it is not lost)

1. **The dashboard bridge is unit-tested only in this environment.** Registration, the tile body and
   the signed scoped link are proven by `test_dashboard_bridge.py` (9), `test_dashboard_link.py` (10),
   `test_results_router.py` (10) and `test_dashboard_redis_compose.py` (9); the tile body was also
   cross-checked against the dashboard's own `plugin_request` (public
   `lux-ai-factory/aisc-results-dashboard`), which is how the gap above was found. A live Superset is
   not runnable here (no Docker daemon for the stack, and a Superset install needs a project's Postgres
   with the engine schema for the tile sync). This is an environment limit, not a known deviation.
2. **The dashboard Redis deployment half is not run.** `scripts/verify-dashboard-redis.sh --local`
   passes on this host (password-protected, loopback-only, storing nothing); which network the cache is
   on and who shares it needs a running stack.
3. **QUAL-01's two reclassifications still want the owner's word** (the card-correction *sign-off* —
   the pilot has one person reviewing — and the pre-fill's *text rules*, absent from the frozen
   `apps/qualification`). Recorded on #113; neither blocks parity.
4. **`pypdf` remains the only new dependency.**

### Evidence

```bash
$ cd apps/backend && uv run python manage.py test
Ran 477 tests in 16.7s
OK                                    # 476 → 477 (the tile body, and `again`)

$ uv run python manage.py makemigrations --check --dry-run
No changes detected

$ uv run python manage.py migrate
No migrations to apply

$ cd apps/webapp && npx vitest run
 Test Files  42 passed (42)
      Tests  273 passed (273)         # unchanged count: the plugin view's two cases now assert the mark

$ npm run build
✓ built in 6.94s                      # tsc clean

$ cd ../.. && uv run --no-project --with pytest python -m pytest tests/architecture -q -rxX
5 passed, 3 xfailed                   # unchanged baseline, 0 failed

$ # the dashboard's own validator, run against both bodies (public results-dashboard repo)
$ uv run --no-project --with pyyaml python -c "from aisc_ext.plugin_tiles import plugin_request; \
    print(plugin_request({'plugin':'strongreject::StrongReject','label':'StrongReject', \
    'charts':[{'chart_type':'bar','metrics':['harmful_rate']}]}))"
{'plugin': 'strongreject::StrongReject', 'label': 'StrongReject', 'version': '',
 'project_name': '', 'visualizations': [], 'again': False}   # accepted, but an empty tile
```

_This section was written by an AI agent (OpenHands) on behalf of the requester; item 3 is a proposal
for the owner to confirm (recorded on #113), and the CAT-01 deviation above is recorded for the same
owner to accept or reverse._

## Run it locally

```bash
git clone --recurse-submodules -b integration/int-01-frozen-unified-app \
  https://github.com/lux-ai-factory/aisc.git aisc-int
cd aisc-int
cp env.example .env            # then edit secrets; for a no-SSO local run set AUTH_ENABLED=false
docker compose -f docker-compose.yml -f docker-compose.build.yml up --build
# open http://localhost:8080
```

The build overlay builds `aisc-backend`, `aisc-webapp` and `aisc-eval` from the checked-out submodules;
the base file pulls released images. Submodule URLs are `git@github.com:`; without an SSH key, rewrite
them to HTTPS first:

```bash
git config --global url."https://github.com/".insteadOf "git@github.com:"
```

_This document was created by an AI agent (OpenHands) on behalf of the requester._

## Final acceptance sweep (REL-01 #119) — 2026-11-18

Run from a **fresh clone** of `integration/int-01-frozen-unified-app` with
`--recurse-submodules` (so this is exactly what a tester pulls), plus the working
tree. Every submodule gitlink resolved; no commit was missing from the remotes.

| check | command | result |
|---|---|---|
| architecture guards | `pytest tests/architecture -q` | **7 passed, 1 xfailed, 0 failed** |
| backend suite | `uv run python manage.py test` | **482 passed, OK** |
| migrations drift | `manage.py makemigrations --check` | **No changes detected** |
| fresh database | `migrate` on an empty SQLite file | **clean, 60 tables** |
| webapp suite | `npx vitest run` | **273 passed (42 files)** |
| webapp build | `npm run build` | **clean** |
| compose | `docker compose config -q` (published / build / infra / staging / development) | **all OK** |

Two defects were found and fixed in the sweep (they were invisible to the
per-issue worker tests, which is why the sweep exists):

1. **Optional features defaulted OFF.** The flag registry shipped with the lean
   profile as the default, so the full profile — the normal build — answered 404
   on qualification/objectives/controls/reporting and broke 133 backend tests.
   Full is the default again (`config/settings.py`, `aisc_backend/flags.py`); the
   lean profile is the `FEATURE_*=false` opt-out. Five router test classes that
   predate the auth door now grant the development caller `Owner`, as the other
   router tests already did.
2. **`env.example` shipped `DASHBOARD_REDIS_PASSWORD=` empty.** Compose requires
   it (`:?`), so the documented `cp env.example .env` flow could not start any
   profile. It now carries a local-only default, with the guard kept for real
   deployments.

**I9 retired (post-integration).** `apps/controls` and `apps/qualification` were full-stack domain
slices (ADR 0001); their retained behaviour is served from `backend`/`webapp`. The two submodules,
the static `homepage/` launcher and the per-app `init/*-db.sql` files have now been **removed**; the
I9 guard passes with an empty baseline and the suite is **8 passed, 0 xfailed**. `shared/identity`
and `shared/report-plugin-interface` (stale pilot checkouts, never tracked here) were removed too.

**Release decision (REL-01).** The branch is accepted as a **working integration
branch, testable end to end** — not a release. The frozen-app port, the security
work (SEC-01/02/03), the versioning/identity work (VER-01), the audit and flag
core (CORE-01), the execution work (EXEC-01) and the I9 consolidation are all on it.
