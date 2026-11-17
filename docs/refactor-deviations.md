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
`uv run --no-project --with pytest python -m pytest tests/architecture -q -rxX` → **5 passed, 3 xfailed,
0 failed** on this tree.

| invariant | state | evidence / owner |
|---|---|---|
| **I1** worker fetch mid-run | xfail (baseline) | the 5 findings are the **dispatcher** (`run_evaluation`) and `_embed_input_files` attaching inputs/settings **before** dispatch, plus status reconciliation in `finalize_evaluation`. `run_plugin` is self-contained, so I1 holds; the AST heuristic cannot tell dispatcher from runner. ADR 0003 / EXEC-01 #120 |
| **I9** domain-slice module | xfail (baseline) | `apps/qualification`, `apps/controls` are still full-stack slices (ADR 0001) |
| **I11** no step containers | xfail (baseline) | main's compose keeps one-shot `make_buckets` steps in `docker-compose.yml` and `docker-compose-infra*.yml`; the docs tree renamed these to `engine-standalone` (ADR 0001). REL-01/REL-02 |
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
