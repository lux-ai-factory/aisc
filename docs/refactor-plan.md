# Refactor plan — frozen unified-app on main → pilot feature port

**Updated:** 2026-11-16 after unified-app review and owner decisions.
**Status:** binding sequencing and scope under [ADR 0003](adr/0003-frozen-unified-app-port-and-worker-boundary.md).
[ADR 0002](adr/0002-unified-app-first-feature-port.md) is superseded; its execution-design rationale remains historical.
[ADR 0001](adr/0001-mainline-first-consolidation.md) retains the audit, upgrade and cache decisions.
Rules: [`ARCHITECTURE.md`](../ARCHITECTURE.md). Feature decisions:
[`unified-modules-and-pilot-brief.md`](unified-modules-and-pilot-brief.md).

## 0. Goal and scope

Start from **main/master**, selectively merge the **frozen** `feat/unified-app` backend, webapp, eval,
plugin-interface and plugin-manager commits (§3), then complete the retained pilot features and
architectural consolidation. Keep main's parent files; do not merge the unified-app parent wholesale.
The result combines
unified-app's existing backend/webapp work with pilot's richer features in one coherent product.
Improve how plugins execute **after** this merge/port.

- **Data:** preserve existing mainline installations, IDs, files and migration history. No pilot,
  unified-modules or unified-app database importer is required. No one has deployed unified-app with
  data to preserve: rewrite its unshipped compliance migrations in the owning Django apps, keeping
  shipped mainline history untouched (ADR 0003).
- **Ownership:** one backend, one webapp, one shared product database and Django migrations; layer and
  published-artifact boundaries remain. Domain features live inside those layers.
- **Product UI:** preserve the **pilot launcher's look, feel, navigation and assessment flow** in the
  existing React webapp. Reuse unified-app functionality beneath that presentation. The screen-to-app
  mapping and visual/workflow acceptance contract are in §2.1 below.
- **Isolation:** one ORM/access mechanism enforces project membership and roles on reads and writes.
  PostgreSQL row-level security (RLS) is not a refactor requirement.
- **Audit:** extend main/unified-app's one best-effort backend audit helper and immudb store/history.
  Pilot's ledger, witness, outbox and relay stack is excluded.
- **Versions:** one assessed-system identity and explicit publish operation; published snapshots are
  immutable in application code and evidence/reports name the version they describe.
- **Reporting:** pilot supplies the functional reporting requirements. Fold them into the existing
  backend/webapp report feature, replacing unified-app's incomplete rendering/fallback path.
- **Execution:** retain working runtime and make the **small plugin child-environment allowlist fix
  now**: never pass worker-wide service secrets to arbitrary plugins. Self-contained dispatch and
  run-local doors are post-port work; remaining per-run credential exposure is documented (ADR 0003).
- **Adapters:** retain native/bespoke targets and required data/resource adapter selection, bindings,
  compatibility and recorded versions through the existing mechanisms. Functional porting is in scope;
  a new execution framework, sandbox or general session framework is not.
- **Deployment:** retain Superset as analytics with its isolated Redis, the public catalogue and needed
  infrastructure. Consolidate domain services and use simple committed deployment configuration.

## 1. Working method and checks

For each feature: **extract behaviour → decide its owner → make a reviewable ticket → identify its
acceptance evidence → implement**. Record **keep / extend / merge / drop / ask**. Preserve all agreed
features; a differing or missing implementation is work to resolve, not permission to silently drop it.
Ambiguous new requirements go to a human. Useful source code can be reused in its correct owning layer.

Maintain a feature matrix with source commit/path, user behaviour, destination owner, disposition,
dependencies, acceptance evidence and completion status. Compare **main, unified-app and pilot**;
use unified-modules only for relevant behaviour not already accounted for. Start with §2's inventory.

Instructions/review own architectural judgement. Keep a small regression suite and meaningful feature
tests; no checker-per-invariant or up-front tooling project is required.

```bash
uv run --no-project --with pytest python -m pytest tests/architecture -q -rxX
```

A failure is a stop. Named debt is allowed only under its linked ADR; newly detected findings fail.
The current pilot baseline is not automatically the merged-tree baseline: review each changed finding
when integrating the guards. Consolidation baselines expire at completion; the **I1 execution baseline
alone may remain** until the post-port execution milestone (ADR 0003).

| Concern | Evidence for this merge/port |
|---|---|
| Pilot UI fidelity | pragmatic desktop/mobile review of shell, project landing and evidence hub; walkthrough of Projects → four steps → report with roles and version context (no pixel-perfect gate) |
| Existing execution | real core/native/bespoke/file-input smoke paths; failure, stop and result persistence still work |
| I1/I2 runtime design | recorded follow-up; backend-down completion and local-door tests belong to that milestone |
| I3 one owner | review models/call paths; one project, system identity, membership, secret and audit mechanism |
| I4/I10 optional domains | same app graph across flags; core evaluation works with compliance disabled |
| I5 tenancy/migrations | mainline upgrade, clean install, ORM read/write/related-object/download isolation |
| I6 versions/audit | publish/reopen/history/concurrency tests; one audit helper; historical reports remain stable |
| I7 outbound handling | plugin child never receives worker service environment; ported APIs, reports, logs and artifacts omit secrets; per-run credential limitation documented |
| I8/I9/I11 boundaries | review ownership and deployment; eliminate duplicated domain services; keep cache isolation |

## 2. Phase 0 — pin sources and capture the feature inventory

1. Freeze the reviewed unified-app commit pins in §3 and record current main tips in the parent and
   affected repositories. Do not automatically advance the source branches; later author changes are
   explicit reviewed additions. Preserve current build,
   deployment, documentation and smoke-test improvements when merging.
2. Capture a representative mainline database/storage fixture, audit-history fixture and core smoke.
3. Record all retained features in the matrix below before treating any source branch as redundant.
4. Carry the binding docs/ADRs and small guards onto the integration branch with reviewed baselines.
5. Use the pinned pilot launcher/theme reference in §2.1 for a pragmatic visual/workflow review; no
   exhaustive screenshot fixtures or pixel-by-pixel matching are required.
6. Assign one integration coordinator to manage gitlinks/contract conflicts; the worker-ready issue
   graph in [`refactor-issues.json`](refactor-issues.json) lists parallel tracks and dependency gates.

### Starting feature inventory

| Capability | Starting implementation / source | Destination and completion requirement |
|---|---|---|
| Core projects, components, plugins, evaluations, results | main + unified-app | retain existing behaviour and mainline data |
| Product shell, styling and assessment navigation | **pilot `homepage/` launcher + assets** | existing React webapp adopts pilot visual design, four-step landing, Manage and evidence hub; §2.1 |
| Membership, ownership, Keycloak users | unified-app + pilot semantics | one backend ORM/access path, consistent roles on all endpoints |
| Qualification, questionnaires, AI card/graph/corrections | unified-app + pilot parity review | backend-owned models/logic, webapp UI; consolidate headless/ontology domain paths |
| Risks, objectives, priorities, matrices | unified-app + pilot | version-consistent assessments; project-local custom data and shared catalogue |
| Checklists, sources/catalogue, answers, review, readiness | unified-app + pilot | one controls feature with preserved history and required exports |
| Connections, target/component bindings, helper models and keys | main/unified-app components + pilot | extend components and one secret mechanism; retain supported native/bespoke use cases |
| Data/resource adapters and plugin configuration versions | shared unified-app changes + pilot | selectable compatible bindings and recorded versions; current runtime |
| Evidence map, links, notes, review, gaps and carry-forward | pilot; extend unified-app coverage | versioned evidence tied to objectives, tests and checklists |
| Results analytics and dashboard bridge | pilot Superset integration | separate analytics layer; backend-scoped bridge and webapp entry points; isolated Redis |
| Report composer, layouts, blocks, generation and downloads | **pilot** + useful unified-app report/UI foundations | one report feature; detailed requirements in §5.3 |
| Catalogue discovery/publication and management flow | main/unified-app + pilot | one integrated product UI; retain independently published catalogue/ABIs |
| Audit/activity | main/unified-app | one immudb writer/API/UI, project-scoped reads and readable historical events |
| Deployment and operations | main + required pilot operational behaviour | committed compose, simple launcher, init/migration steps and opt-in tools |

The matrix is a starting inventory, not a claim that parity has been verified. Expand it using the
descriptive appendices and source behaviour; explicitly record approved exclusions.

**Exit:** pinned sources, upgrade fixtures and retained feature matrix are available.

### 2.1 Pilot UI contract and screen-to-owner map

**The pilot launcher is the presentation reference.** Use `homepage/index.html`, `project.html`,
`evidence.html`, `evidence-map.html`, `catalogue.html`, `results.html` and the four Manage pages, plus
`homepage/assets/launcher.css`, its fonts/logo and `shared/theme/brand.json`. Follow the pilot tools
linked from those pages for the detailed qualification, objectives, checklist and report workflows.
Record any intentional departures in the feature matrix for owner review.
The reviewed launcher/theme source is at pilot commit
`6197dc1aff55a582f5bdb39b10b0910b81b7a07b`; this is a reference snapshot, not a
requirement to track later pilot changes.

**Visual contract:** electric blue `#000fdf`, hot pink `#ff007e`, pale `#f2f3fd` background, white panels,
square corners, hairline borders, generous grid-based spacing and prominent numbered step headings.
Use MuseoModerno headings, Raleway body text and IBM Plex Mono labels. Preserve the branded sticky
topbar, project/back links, signed-in user/sign-out controls, hover/focus states and responsive stacking
(the launcher uses an 820px breakpoint). The grid is a layout, not a drawn background. Apply the tokens
through the existing React theme/styles so dialogs, forms and detailed pages share the same design.

**Navigation contract:** Projects → project landing → **Plan the assessment** with **1. Qualify the AI
system → 2. Set control objectives → 3. Choose tests and checklists**, then the downward connector to
**4. Collect evidence**. Preserve the project title/context and the role-aware **Manage** menu. The
numbering communicates the workflow; it does not make qualification a prerequisite for a core test run.

Collect evidence keeps the **AI card version** selector, **Evidence map** link/coverage summary, and
the four columns **Answer checklists / Run tests / Results / Report**. Preserve the pilot's distinction:
  selected version scopes test counts, assessment results, map and report history; checklist tiles show
the latest answers; local-model runs are separately identified and excluded from assessment reports.
Historical reports use their frozen snapshots. Editing a draft does not silently publish a version.

The table gives **logical page areas and table ownership**, not new services or a mandatory URL rename.
Extend existing page files/routes; preserve working deep links through the router when regrouping them.

| Pilot screen / user task | React area in `apps/webapp/src/` (existing starting point) | Django table owner / composition |
|---|---|---|
| Projects, create/select project | `pages/GlobalHome.tsx` | `core`: project, membership and shared access rules |
| Project landing, four steps, Manage | `pages/ProjectHome.tsx`, shared shell components | `core` project context; UI composes enabled feature summaries |
| 1. Qualify the AI system | `pages/QualificationPage.tsx` | `qualification`: questionnaires, AI cards and corrections; references core system/version |
| 2. Set control objectives, risks/priorities | `pages/ControlObjectivesPage.tsx`, `RiskRegister.tsx` | `control_objectives`: risk/objective assessments and mappings |
| 3. Choose tests and checklists | existing `pluginCatalogue/`, `pages/Plugins.tsx` and catalogue page composition | `plugins`: test catalogue/install/config; `controls`: checklist catalogue/install; UI combines enabled types |
| 4. Collect evidence hub | extend `pages/SandboxPage.tsx` with pilot layout and labels | UI composes scoped `evaluation`, `controls`, `control_objectives` and `report` APIs |
| Answer checklists | `pages/ChecklistsPage.tsx` | `controls`: answers, readiness and checklist review |
| Run tests, run detail and measurements | existing `StartEvaluation`, `PluginStartEvaluation`, `PluginEvaluations*` pages | `evaluation`: inputs, bindings, runs, status, results and artifacts; uses `plugins` configs |
| Evidence map, links/notes/gaps/review/carry-forward | evidence-map page and components under the evidence area | `control_objectives`: objective-to-evidence links, notes and review records; references core run/artifact data and optional checklist evidence |
| Results, visualizer and analytics | existing measurement pages + `pages/DashboardPage.tsx` | `evaluation`: result data and scoped dashboard bridge; Superset remains analytics |
| Report, composer/layouts, generation/history/download | `pages/ReportPage.tsx` and report components | `report`: layouts, block configuration, immutable generation snapshots and document records |
| Manage → Components and connections | extend `pages/Settings.tsx` and component editors | `core`: `AIComponent`, connection bindings and the one secret mechanism; adapter definitions/configs extend `plugins` |
| Manage → AI assistant models and keys; helper models | settings subpages/components | `core`: project settings, model/helper-role bindings, same components/secrets |
| Manage → Activity log | `pages/LogsPage.tsx` | existing audit module/API, hosted with core; immudb remains its store |
| Manage → membership, account, admin/inspection, deletion | existing project/settings/task components and authorised tool links | `core` membership/deletion; existing auth and ops integrations; role visibility matches server permissions |

**React organisation:** keep the existing `pages/`, `components/`, `api/`, `context/`, `styles/` and
`pluginCatalogue/` mechanisms. Group growing components by the page areas above. Adapt `MyApp.tsx`,
`TopBar` and navigation into one pilot-style shell; its project landing and Manage menu become the
primary navigation. Reuse the merged page logic, API clients, forms and editors inside it. Share step
cards, evidence tiles, version selection and project context instead of creating another launcher SPA.
Carry project/version selection through links, refresh and browser back/forward; clear stale selections
when changing project and validate them against scoped backend data.

**Django organisation:** the core apps are `core`, `plugins`, `evaluation`; optional apps are
`qualification`, `control_objectives`, `controls`, `report` (brief D11). Each owns its models, migrations,
API and domain logic. `core` owns the single system identity and shared version/publish mechanism;
qualification owns card content. Optional contributions participate through the existing shared
mechanism and backend wiring without core importing optional models. Keep raw results/artifacts in
`evaluation`; their compliance links/review live in `control_objectives`. The checklist review itself
stays in `controls`. A screen combining these records is composition, not a new table owner.
Report assembly uses the owning apps' scoped ORM interfaces and stores its own snapshot. Optional
cross-feature integrations honour flags and an acyclic migration graph; absence of checklist or
qualification data must not prevent core evaluation. Preserve table names, IDs, migration history,
content types and permissions when moving models; extend existing mechanisms as described in §4.

**Feature flags and roles:** use the same shell and routes in full and lean profiles. Hide unavailable
optional cards/actions and handle direct navigation with an explicit unavailable state; backend
endpoints enforce flags and access independently. Keep tests, runs, results, components and helpers
reachable without an AI card or compliance steps. Manage retains pilot groupings and role visibility;
integrate unified-app membership functionality there. Existing account/admin tools remain authorised
links, with inspection wording updated for the shared database.

**Acceptance:** review the shell, project landing and evidence hub at desktop and mobile widths for
recognisable pilot styling and responsive usability (close enough, not pixel-perfect). Walk Projects →
all four steps → versioned evidence → report and return via back links; exercise Manage as
viewer/editor/owner/admin, keyboard navigation, deep links, refresh and project switching. Check the
lean profile and explicit publish/history behaviour. Use targeted existing frontend/e2e tools and a
short recorded visual review; do not require an exhaustive screenshot/state matrix for every page.

## 3. Phase 1 — selectively integrate frozen unified-app into main

1. Create coordinated integration branches from **main/master** in the parent and five affected
   layer/shared repositories. Do not move the frozen feature source tips.
2. Merge the **frozen commit** in backend, webapp, eval, plugin-interface and plugin-manager; reconcile
   mainline changes. Update parent gitlinks to resulting commits. Do **not** merge the unified-app
   parent tree; preserve main's published compose, e2e, compose-validation CI, `DEVELOPER_GUIDE.md`
   and `env.example`. Add only required backend/webapp/deployment wiring deliberately.
   `apps/qualification` and `apps/controls` unified-app tips are reference only (diverged legacy
   frontend/Prisma stacks); do not merge their histories into those modules.
3. Retain unified-app's Django models/routes, React page functionality, project audit extension,
   plugin/config improvements and worker failure/stop fixes. Adapt the React shell and page presentation
   to the pilot UI contract (§2.1), reusing the useful components and behaviour already supplied here.
4. Preserve main's published-image compose, local-build overlay, CI, guides and smoke tests.
5. Check fresh migrations, mainline upgrade, frontend build and focused backend/frontend/worker tests;
   do not carry unshipped unified-app migration 0015–0032 as a deployed-data compatibility promise.
   Record remaining feature-branch defects as Phase 2 tasks. A successful merge is not release acceptance.

### Reviewed source snapshot (refresh before implementation)

Review parent: `256712ef2710a038fbdd86a6718d6d16aab766c4` (`feat/unified-app`).

| Submodule | Reviewed feature pin |
|---|---|
| `apps/backend` | `a8cf87399654d1366d36bfa423840559ac231fdd` |
| `apps/webapp` | `ea0a7710f661ffbb0b5caeabbea5bff9dc1fc4bc` |
| `apps/eval` | `4767cf51f08ca434e48202c29432e573a694bed4` |
| `apps/qualification` | `498782ec89538916a59701201958bd1a4c0b9f8c` |
| `apps/controls` | `2590779131cec0ce868c457ee12de02dbfa4da91` |
| `shared/plugin-interface` | `0d13ec1877c16fcef4b4bbf8a8802431304b93f9` |
| `shared/plugin-manager` | `308e452840015559c33b1d057c2f758c707fdb86` |

The parent's `.gitmodules` tracks main/master, despite these feature pins. Merge only the five named
layer/shared repositories, pin resulting gitlinks, and use the parent commit as a **reference only**.
`apps/qualification` and `apps/controls` pins above are reference snapshots, not merge instructions.
Do not use `submodule update --remote` as a substitute for deliberate integration.

Review evidence: 132 frontend tests and production build, 70 targeted backend tests, 10 worker tests,
no missing Django migrations, and representative SQLite `0014 → 0032` upgrade passed. This does not
prove full-stack operation, PostgreSQL upgrade or live Keycloak/immudb compatibility. The mainline
backend migration baseline reviewed was `bc879c8340b840627b7409b05ace29f3cc6330f3`.

**Exit:** reproducible merged checkout with pinned submodules and a working core baseline.

**Security checkpoint (not a release promise):** land the plugin subprocess environment fix and
deny-by-default project access as soon as the merged baseline exists. An interim build may be
demonstrated after these gates; preserve all existing functionality until the full feature port.

## 4. Phase 2 — correct and consolidate shared contracts

### 2.1 Project permissions and one ORM data path

- Extend unified-app's membership/access helpers across **all** project-scoped entry points: core
  components, evaluations, tasks, settings, files, artifacts and new compliance/report endpoints.
- Check both the requested object and related-object ownership on writes. A valid UUID or login alone
  is not authorisation. Viewers read, editors write, owners manage membership; preserve admin semantics.
- Fix the existing-member update (`asave()` returns `None`), viewer project rename, unscoped evaluation
  access and last-owner races. Test strangers and each role across two projects.
- Bootstrap mainline projects' ownership explicitly and idempotently. Keep one shared database,
  one membership and one secret store. ORM enforcement is sufficient; RLS is optional future work.
- Deny access by default for all project-scoped public routes; introduce one small route-coverage
  regression guard with named public/global/internal exceptions and exercise two-project, role-based
  behavioural tests. The internal API must tie evaluation/file/settings requests to their project;
  possession of `INTERNAL_API_KEY` is not a project capability.
- Make the eval worker child environment a closed allowlist (see ADR 0003 and issue JSON). Do not copy
  the worker's `DJANGO_SECRET_KEY`, `INTERNAL_API_KEY`, registry/database/Redis secrets into plugin
  subprocesses. Keep only required explicit per-run plugin settings for now; do not cherry-pick the
  unrelated I1 dispatch changes from `e05a231`.

**Gate:** cross-project reads/writes/downloads fail, role restrictions hold, mainline owners retain
access, the route guard covers new endpoints, and a plugin child cannot read worker service secrets.

### 2.2 System identity, publish and immutable history

- Reconcile qualification `System` with core `AISystem`; one assessed-system identity owns the
  relationships. Extend the existing destination model rather than keeping parallel identities.
- One transactionally safe explicit publish operation cuts a version. Editing/reopening creates a
  draft or successor without moving or mutating the old published card; concurrent publication is safe.
- Align questionnaires, risks/objective assessments, checklists and evidence with that lifecycle.
  Preserve project-local custom identifiers rather than globally colliding custom objectives.
- Bind report snapshots to the selected published version. A later draft must not hide its card;
  version references and data must describe the same snapshot.

**Gate:** historical cards and evidence survive reopen/edit/delete attempts; version and concurrency tests pass.

### 2.3 Stable app graph, ownership and audit

- Apply the agreed core/optional table-owning app boundaries inside backend while preserving **mainline**
  tables, IDs, migration history, content types and permissions. Rewrite **unshipped** unified-app
  0015–0032 in destination apps as needed; do not use state-only migration gymnastics for disposable
  unified-app data. Use §2.1/brief D11; verify clean install and real PostgreSQL mainline upgrade.
  Layer code follows its tables: routers, services, schemas, repositories and tests live in the app that owns
  the tables they serve, while the URLconf stays the one composition root and every app stays installed.
- Register feature flags at behaviour seams; never change installed apps, middleware or URLconf by mode.
  Core must run with qualification, objectives and controls disabled and without their data.
- Extend the one audit module. Preserve mainline immudb history and verify its project-scoped read
  behaviour after the added project column; do not silently lose access to older events.
- Keep best-effort delivery. Scrub ported metadata and use the same helper for all governed changes.

**Gate:** optional-domain/core tests, upgrade checks and single-audit history checks pass.

## 5. Phase 3 — complete pilot feature parity in the owning layers

Start by landing the pilot theme/shared shell, Projects and four-step landing, then the Collect evidence
hub with its project/version context. Port each detailed page and Manage destination into that structure
alongside its owning backend feature. Capture visual/workflow acceptance per slice rather than leaving
  the launcher design until after feature completion. Follow §2.1 throughout the workstreams below.

### 3.1 Components, adapters and management

- Port retained component/helper-role/configuration-import-export, adapter discovery, compatibility/
  selection and run-provenance metadata beside existing components/plugins/settings. One component model
  and one adapter mechanism ([ADR 0009](adr/0009-components-adapters-and-the-run-door.md)): `Connection`,
  `Helper` and `RunBinding` fold into `AIComponent`/`EvaluationInput`, and adapters live in
  `aisc_plugin_interface.adapters`.
- Keep existing execution and result-posting mechanisms; make only the compatibility/relocation changes
  required for those behaviours. Port supported session behaviour without inventing a general framework.
- Demonstrate file inputs, native targets and required bespoke adapters through the webapp; the run
  records the selected adapter/config version and the mock target confirms the intended request.
- Consolidate platform-owned feature logic into backend/eval as appropriate. The endpoint run door is now
  built (ADR 0009); self-contained dispatch (I1) and inherited per-run target credentials for non-endpoint
  paths remain the later execution milestone.

**Gate:** retained component/adapter flows and failure/stop/result behaviour work end to end.

### 3.2 Qualification, controls, evidence and analytics

- Extend unified-app's page functionality and models within the pilot presentation to close the feature matrix, including
  questionnaire/card editing, versioned risk/objective assessments, checklists and readiness/review.
- Fold qualification headless/ontology domain logic into the owning layers; retain the real card
  computation instead of accepting a fallback summary as feature parity.
- Port the evidence map: dimension-compatible links, notes, stale/gap states, independent review,
  review invalidation and appropriate carry-forward to a new version. Reconcile mutability with §4.2.
- Port Superset's dashboard bridge, version/run filtering and charts. Keep local-model runs distinct
  from assessment evidence and preserve the isolated dashboard cache.
- Complete launcher/manage/results/catalogue visual and workflow parity in the existing webapp (§2.1).

**Gate:** full assessment flow works; evidence/history is version-consistent; compliance-disabled core works.

### 3.3 Pilot reporting — a first-class port workstream

Keep the full retained renderer feature set while inventorying its dependencies and actual runtime
needs. Before adding new production packages or a Chromium/backend browser requirement, record the
I8 decision with named owner, cost and removal condition; do not preemptively strip Playwright,
WeasyPrint or python-docx just to simplify the port (ADR 0003).

Functional reference: [Collect evidence, Report](appendices/4-collect-evidence.md#report), pilot's
composer/renderer/report-plugin implementations and `platform` report integration. Reuse the useful
unified-app report records, snapshot helpers and React pages, extending them to the full retained flow.

- **Composition:** ordered blocks; templates, index and numbering; the five built-in read-only layouts;
  duplicate/edit custom layouts and import/export between projects; chapters, free text and commentary.
- **Content:** AI card/risk classification, objectives, checklist answers/readiness, evidence coverage
  and review, test runs/results, generic and plugin-specific result blocks, dashboard charts and
  report-plugin blocks. Preserve the published report-plugin ABI where needed, with one loader path.
- **Selection:** an explicit AI-card version, optional period, additional versions and comparison
  version; include only the applicable evidence/runs. Preserve exclusion of local-model-only runs.
- **Outputs:** real PDF and Word documents, optional PDF companion for Word where supported; correct
  content types/filenames; persisted generation inputs/snapshot, document checksum and downloads.
- **Ownership:** Django models/migrations and ORM-scoped snapshot assembly in backend; composer UI
  in webapp. Reuse rendering functions in that feature instead of retaining a parallel report stack.
  Renderer/plugins receive prepared data, not direct cross-app SQL or a separate project DB path.
- **Integration:** one report API/history and one audit path. Remove the dead `report-headless` wiring
  and HTML-labelled-as-PDF behaviour as the real renderer lands. No fallback counts as report parity.

**Gate:** generate/open PDF and Word for a selected published version using real rendering; verify
blocks, evidence/analytics, comparison and local-run exclusion; edit the project and confirm old
report content/provenance stays stable; check project permissions and custom-layout round trips.

## 6. Phase 4 — deployment consolidation and release acceptance

- Inventory superseded platform/domain APIs, UIs, databases and migration plumbing; **only retire
  proven duplicates after parity and owner review**. Preserve working functionality while learning
  how each part operates; do not indiscriminately delete legacy components at integration time.
  Keep one implementation for reports, qualification, controls, membership, secrets and audit.
- Preserve main's deployment paths; consolidate configuration into committed compose and a small
  documented launcher. Setup/migrations are steps; dev/admin tools are profiles. Retain necessary
  operational/secrets setup behaviour, Superset and its isolated Redis. There is no container-count target.
- Check real PostgreSQL mainline upgrade and fresh startup, storage/audit history, full assessment/report
  flow, analytics, and lean core. Verify the completed feature matrix and update nearest documentation.
- Complete the pragmatic pilot desktop/mobile visual review and navigation acceptance in §2.1 before retiring
  the static launcher; the single React product UI preserves its look, feel and flow.
- Retire consolidation baselines. The specifically reviewed execution baseline may remain under
  ADR 0003; it must not hide any other incomplete architecture work.

**Exit:** mainline data upgrades, all agreed unified-app/pilot features work in the consolidated product,
core works with compliance disabled, and no duplicate domain/platform stack remains. Plugin execution
retains its documented current limitations; backend-down execution is not a release acceptance test here.

## 7. Post-port improvements (separate milestone)

- Self-contained dispatch and results posted at completion; real backend/platform-down acceptance test.
- Run-local doors for **non-endpoint** paths and further execution hardening; retire ADR 0003's remaining
  per-run waiver and the I1 baseline. (The endpoint door is built, ADR 0009.) Worker-wide secrets are
  excluded now.
- Durable recovery after worker loss; comprehensive attempts/retries/deduplication and credential expiry.
- Adapter sandboxing, general session/concurrency framework and authoring tools.
- Stronger audit delivery/verification; PostgreSQL RLS if later requirements justify it.

These preserve the agreed destination architecture without becoming hidden blockers for the feature port.
