# Brief — folding `unified-modules` and `pilot` into the main line

> **Audience:** a developer or an agent picking this up cold. **This file is self-contained** — it does not
> assume the reader has the `SCRATCH-*` notes. It is *the decisions* — the **how and in what order** is
> [`refactor-plan.md`](refactor-plan.md).
>
> **Date:** 2026-11-12. **Status:** agreed framing + decisions; binding rules in
> [`../ARCHITECTURE.md`](../ARCHITECTURE.md); the phased implementation in [`refactor-plan.md`](refactor-plan.md).
>
> **Read this first, then the [plan](refactor-plan.md), then start at [§2 the method](#2-the-method-five-steps-per-phase).**

---

## 0. How to use this brief

1. Read [§1 framing](#1-the-framing-exploration-branches) and [§3 roadmap](#3-the-roadmap-two-phases) — two minutes.
2. The work is **two phases**, in order: **Phase 1 `unified-modules`, then Phase 2 `pilot`.**
3. Each phase runs the **same five steps** ([§2](#2-the-method-five-steps-per-phase)):
   **feature extraction → architecture discussion → ticket creation → test plan → implementation.**
4. Before writing any code, read the **invariants** ([§5](#5-binding-invariants-the-rules-any-implementation-must-obey))
   and run the guards: `uv run --no-project --with pytest python -m pytest tests/architecture -q`.
5. If a feature needs an invariant changed, **write an ADR** (`docs/adr/`), do not silently break it.

**The one-line goal:** take two exploration branches, extract the **features** worth keeping, and
re-implement them **properly** on the main line — one way to do each thing, no second architecture.

---

## 1. The framing: exploration branches

`origin/pilot` and `origin/feat/unified-modules` are **exploration branches**. They existed to explore
features for **short-lived pilots**. They are **not release lines and not merge sources**.

- Think of them as **scratch projects at the scale of the entire application** — what a scratch file is to
  one design question, but spanning the app.
- A pilot communicates **behaviour and requirements**, not architecture. Its code is **evidence that the
  feature is feasible**, not a design to preserve.
- When a feature is folded in, **the implementation and the architecture may change completely.** Folding
  in means *deliver this behaviour*, not *merge this code*.
- **Never fast-forward or merge a release to a pilot.** Extract features one at a time and build each
  against the main architecture.

Full statement: [`exploration-branches.md`](exploration-branches.md). This is the branch-scale form of
invariant **I3** (one implementation per concern).

---

## 2. The method (five steps per phase)

The same loop, applied to **each** phase. Each step has a concrete output; do not start the next step
until the previous output exists.

| # | step | output (the deliverable) | rule |
|---|---|---|---|
| 1 | **Feature extraction** | a feature list — one entry per feature: name, **user-visible behaviour**, actors, inputs/outputs, requirements, open questions, and *where in the branch to read it* | **behaviour only** — no code structure, no file names as the deliverable |
| 2 | **Architecture discussion** | a decision per feature: which existing **invariant/mechanism it is a variation of**, where it lives (app/module), how data/secrets/versioning are handled, alternatives, and any **ADR** it needs | extend the existing mechanism (I3); never add a second path |
| 3 | **Ticket creation** | one issue per **shippable slice**, each linking its feature + architecture decision, tagged with the phase, and naming the invariant(s) and guard(s) it must satisfy | small enough to review and to demo |
| 4 | **Test plan** | per ticket: unit, compatibility/integration, and manual+e2e **driven by the same fixture**; plus the **invariant guard** it turns red/green | the test must show the feature drives the system, not just that it passed |
| 5 | **Implementation** | code merged against the main architecture; guards green; ADR if an invariant changed; docs updated | the shortest path must also be the compliant path |

**Definition of done for a phase:** features extracted and agreed · architecture decisions recorded (ADRs
where needed) · tickets created and estimated · test plans written (with guards) · implementation merged
with the guards green.

**Work-breakdown shape to aim for:**

```
Phase ─▶ Feature ─▶ Ticket(s) ─▶ (test plan + guard)
```

**Port the need, not the code.** A branch feature is a *claim* that something is needed, not proof of it — and
the same goes for everything in `platform/`. For every module, endpoint or page you consider, ask: is it
**needed** (name the behaviour)? does it **duplicate or overlap** something we already have (I3)? can an
existing mechanism be **extended** instead? Then record a disposition — **keep · extend · merge · drop · ask**
(definitions and the `ask` rule in [`refactor-plan.md`](refactor-plan.md) §6). Basic assumptions are fine and
should be noted; where the need is **genuinely ambiguous, ask a human and default to not porting.** A decision
to drop is as valuable as one to keep.

---

## 3. The roadmap: two phases

```
Phase 1: unified-modules        →   Phase 2: pilot
(shared cross-cutting modules)      (platform, connections, adapters, run model)
        │                                   ▲
        └── the contracts Phase 2 builds on ┘
```

**Why this order.** `unified-modules` unifies the **shared cross-cutting modules** every app uses — the
caller's identity, opening a project's data, keeping a secret, writing a ledger event, calling a service.
Phase 2 (the `pilot` features — the platform app, connections, adapters, the run/worker model) *builds on*
those contracts. Doing pilot first would build the platform and adapters on top of un-unified modules and
then have to redo them. **Phase 1 first.**

Each phase is independent enough to finish before the next begins. Do **not** interleave them. The
**ordered steps** (and the guards each one turns green) are in [`refactor-plan.md`](refactor-plan.md) §3–§4.

---

## 4. What we decided (the features/decisions to fold in)

Compact decision blocks. `Phase` says where it belongs. These are the *decisions*; the *rules* are §5.

### D1 — A run is self-contained (Phase 2)

A run is dispatched with **everything it needs** (the evaluation, its tests and inputs, dataset/model
bytes, connection URLs with a run-scoped secret, helper-model keys, project settings). The eval worker then
runs **without needing the backend or platform to be up**, and **posts results at the end** (measures,
artifacts, status). The backend observes status **by id**.

- **Why:** long runs must survive a backend/platform restart; every assessed call should cost one *local*
  hop, not a network hop to a shared service.
- **Today (broken):** the worker fetches request/inputs/files **mid-run**
  (`apps/eval/aisc_eval/service/api_client.py`), and `pilot` routes the plugin's calls through the
  **platform's doors** with a `PLATFORM_RUN_PASS`.

### D2 — A plugin reaches a system through a door, not a credential (Phase 2)

A plugin is never handed the assessed system's secret. It calls a **door** that speaks its protocol; the
door withholds the key, enforces the project's allowlist/timeout, and scrubs the answer. The door lives
**with the run** (the eval worker) so it does not re-introduce D1.

### D3 — Consolidate: one backend, one webapp, one database (Phase 2)

Retire the `platform` app and the `scripts/` control plane.

- **One backend (Django) + one webapp**; **connections and adapters move into the backend beside
  `AIComponent`**. (Whether the submodules stay independent is under discussion — see D8.)
- **One database with project-scoped access** (`project_id` + Postgres row-level security), not one
  database per project.
- Fold the platform's real jobs in: per-project DB provisioning (**already in the backend**), membership,
  encrypted secrets, run tickets (**already**), the ledger, evidence/dashboards.
- Replace `scripts/` (env generation + compose assembly, ~25k lines) with a **committed compose file + a
  short Makefile**.
- **Why:** the platform's only *runtime* job — proxying plugin calls — moves to the worker (D1/D2), so it
  has no runtime role left. Everything else it does already exists in the backend.

### D4 — One app graph; feature flags, not a deployment mode (Phase 2)

Replace the binary `AISC_DEPLOYMENT` (`standalone`|`configurator`) with **named feature flags** read at the
point of use, recorded in one registry, validated at startup. `INSTALLED_APPS`/`MIDDLEWARE`/URLconf must
**not** change with configuration. A fresh install works with no flags set. Likely v1 flags: `LOCAL_AUTH`,
`PROJECT_DB_PER_PROJECT`, `PLATFORM_MEMBERSHIP_SOURCE`, `RUN_TICKET_KEY`.

### D5 — Adapters are a first-class, shipped concept (Phase 2)

- **Two kinds:** `data` (feed plugin inputs) and `resource` (reach a system). **"Agent" = resource +
  session**, not a third kind.
- **No `surface` axis.** The boundary follows the kind:
  - `data` → a **local file** in the run workspace (runs in the plugin process, where today's
    `input_providers` run); selectable via a `produces`/input-type **registry**.
  - `resource` → a **loopback HTTP door in the eval worker**; the adapter is only the handler
    (`open`/`call`/`close`), never a server.
- **An adapter is needed iff the target is non-native**; a native target uses the built-in client behind the
  door.
- **Session scope** per adapter: per **run** (conversation testing) or per **row** (table scoring).
- **Selection** is by plugin+input, stored on the binding, and **recorded on the run** (adapter + version).
- Loaded by the **shared plugin manager** (`list_adapters`/`load_adapter`), from the same two sources as
  plugins (local folder + devpi); listed/selected by the backend+webapp, executed by the worker.
- A **shipped library** plus a **supported bespoke path** (a folder or a UI); **no user catalogue**.

**Adapter manifest (the contract):**

```python
MANIFEST = {
  "name": "website-chat", "version": "0.1.0", "kind": "resource",
  "protocol": "openai",                  # what the plugin sees
  "capabilities": ["text", "history"],   # needs ⊆ capabilities
  "session": "run",                       # run | row
  "config": [{"name": "url", "required": True}, {"name": "login", "secret": True}],
}
class Adapter(ResourceAdapter):
    def open(self, binding): ...           # once per session
    def call(self, session, req) -> Answer: ...   # per turn/row
    def close(self, session): ...
```

**Compatibility (builds the dropdown):** resource = `kind == resource ∧ adapter.protocol ∈ plugin.protocols
∧ plugin.needs ⊆ adapter.capabilities`; data = `kind == data ∧ adapter.produces == plugin.input.type ∧
adapter.accepts ∋ uploaded file`.

### D6 — Versioning lives in the model layer (Phase 2)

Versioning is **yes**, but not where pilot put it (rows in the per-project DB, immutability in **DB
triggers** with a `DELETE` hole, each step stamping in a separate transaction). It belongs in the
**Django/ORM model layer**: versioned models, app-enforced invariants, **one place** that cuts a version
(on an explicit publish, not every save).

### D7 — The `unified-modules` shared contracts (Phase 1)

The cross-cutting modules every app should use **one way**: the caller's identity and access
(`shared/identity/aisc_identity/`), opening a project's database, keeping a secret, writing a ledger event
(`shared/ledger-ts`, `aisc_identity.ledger_events`), calling a service, and the plugin interface/manager.
**Phase 1's first deliverable is the feature list for this** ([§2 step 1](#2-the-method-five-steps-per-phase)) — the
exact inventory is to be extracted from the branch.

### D8 — Independence by architectural axis, or fold? (Phase 2 — **under discussion**)

**Not a decision yet.** The tree is **many git submodules** (`apps/*`, `shared/*`); the original premise was
that a service could be **replaced with someone else's implementation**. The open question is whether to
**fold** the modules into one backend + webapp, or to **keep independent repos but unify DB access and
migrations**. (A third option — keep the repos fully independent — is the status quo and is the source of the
duplication smells.)

**The axis that decides it.** A repo boundary is justified by an **architectural concern** (a layer), a
**published/external artifact** (an ABI, a public site, a registry), or the **composition root** (the
parent/orchestration repo, **no app logic**) — **not** by a **business domain**, which is a slice *through*
the layers. The tree supports that distinction:

| repo | what it is | boundary justified? |
|---|---|---|
| `backend`, `webapp`, `eval`, `results-dashboard` | **layers** (API/ORM · presentation · execution · analytics) | **yes** |
| `shared/plugin-*` | **published ABI** (shipped to plugin authors) | **yes** |
| `catalogue` | **published site** (a public website, not a local instance) | **yes** |
| `qualification`, `controls`, `control-objectives` | **domain slices** — each re-implements frontend + API + DB + migration | **no** |
| `platform` (app) | a **second implementation of the backend layer** (I3) | **no** — folds into `backend` + `eval` |
| report generation (`report-generator`, `report-composer`) | depends on the DB/ORM/schema → a **domain** | **no** — folds into `backend` |

The coupling and duplication live in the **vertical slices** (qualification carries its own frontend, Python
services, API, DB connection and migration); the **layer repos are genuinely independent** (`eval`, for one,
opens no database at all). The layer repos already hold domains as *features*, which shows the fold is
natural: `backend` carries evaluation, plugins, AI components, results/measures, artifacts, ledger/audit,
stats and versioning (`aisc_backend/{models,routers,repositories,services}`); `webapp` carries the plugin,
evaluation, project and AI-system UI; `eval` carries the evaluation/project run model.

**Pros of keeping independent repos (with unified access + migrations).** Independent lifecycle/scaling (the
worker scales on queue depth; the webapp is a static build); blast-radius and credential isolation (the
worker needs no DB or identity credentials — the I1 argument); toolchains stay uncoupled; the contract is a
hard wall; ownership is a repo.

**Cons.** Cross-repo versioning tax (the shared access/migration package must satisfy every consumer);
contract drift — the boundary is *why* the two `projectdb.py`s, two memberships and two secret stores exist;
atomic changes span repos; a local-dev composition layer grows (how `scripts/aisc.py` happened); the guards
only see one repo.

**Pros of folding.** One toolchain, CI, migration tool (I5), auth/membership/secret store (I3) and test
story; atomic cross-layer changes; clone-and-run; layering enforceable with one import-linter run.

**Cons of folding.** Bigger repo, slower CI, larger blast radius; Node + Python envs together; ownership
becomes directories; it fights genuinely different lifecycles (the worker, analytics).

**The crux.** Unified access/migrations unifies the **pipe, not the model**: qualification (Prisma), the
backend (Django ORM) and control-objectives (Alembic) would still each need their own model of the same
schema — which is where the duplication lives. So the middle option pays most of the tax while the coupling
stays. It is coherent for the **layers** (which do not share a DB: `eval` has none, `webapp` goes over HTTP)
and weak for the **domain slices** (which *do* share the project DB and therefore need one model owner).

**The fork.** *Bounded contexts + a platform* (pilot's bet: domains own their stacks; cross-cutting concerns
get a platform service) **vs** *layers + one shared domain model* (cross-cutting concerns live in the
backend; domains become features of the layers).

**Leading position (for discussion, not decided):** keep the **layer repos** (`backend`, `webapp`, `eval`,
`results-dashboard`), the **published artifacts** (`catalogue`, `shared/*`), and the **composition root** (the
`aisc` parent repo — orchestration only, **no application logic**); fold the **domain slices**
(`qualification`, `controls`, `control-objectives`) into webapp (UI) + backend (API/ORM); and fold the
**`platform` app** into `backend` + `eval` (it is a duplicate of the backend layer, I3 — nothing in it is an
independent concern). **Report generation** is a domain to fold into `backend` (a `report` feature); **Superset
analytics stays separate** (its own service/repo/container, `results-dashboard`).

**The composition root holds no application logic.** `aisc` is the parent repo: compose, CI/CD, deployment,
e2e and docs. In-tree application code today — `platform/`, `report-composer/`, `shared/identity/`,
`shared/ledger-ts/` — moves to a component repo. This is itself an I9 boundary (the composition root), not a
licence to keep app code in the parent.

### D9 — Data access and migrations (Phase 2; provisional — depends on D8)

Target **if the domain slices fold**: one database with project-scoped access and one migration runner +
history (D3), with app-owned schema. If they stay independent, multiple migration tools are the price of that
choice (see the D8 pros/cons).

- Modules folded into the backend: their tables become **Django ORM models + migrations** (I5) — one tool.
- Modules that stay independent (the layers): `eval` has no DB; `results-dashboard`/Superset reads read-only;
  anything that does reach the project DB goes through the **shared access package**
  (`shared/identity/aisc_identity/projectdb`) and the **one runner**, which records `(module, revision,
  applied_at)` in a single history table.
- **If a multi-tool reality survives, it needs an ADR.** I5 says *one migration tool*; keeping more than one
  requires an **ADR** that refines I5 to "one migration **runner and history**; app-owned artifacts" — or
  commits to a single tool. Do not diverge silently.

### D10 — Container topology: one container per deployable process (Phase 2 — **under discussion**)

The dev compose carries **~41 service definitions** (29 app + 12 infra across `docker-compose*.development.yml`),
and they mix three different things: genuine long-running **services**, **one-shot init/migration steps** dressed
as services, and **dev/admin tools**. Several are also split on the **wrong axis** — the same mistake as the repos
(I9), at the container level. The rule to adopt: **one container per deployable process** — a layer service, a
published service, or an infra service.

| kind | what it is | rule | examples today |
|---|---|---|---|
| **service** | a long-running process of a layer, a published artifact, or infra | **one container each** | `aisc-backend`, `aisc-webapp`, `aisc-eval-worker`; `catalogue-private`, `dashboard`, `plugin-publisher`; `postgres`, `redis`, `rabbitmq`, `minio`, `immudb`, `keycloak`, `caddy`, `devpi` |
| **step** | a migration, grant, bucket/key setup — runs once, exits | **NOT a container** — a step of the one migration runner (D9) or an init hook | `aisc-backend-migrate`, `{controls,qualification,control-objectives,report-composer,dashboard}-migrate`, `report-grants`, `make_buckets`, `postgres-setup`, `immudb-key` |
| **tool** | dev/admin/observability, not needed to serve | **opt-in profile**, never default | `aisc-eval-flower`, `pgadmin`, `schema-docs`, `docker-compose.admin-ports.yml` |
| **wrong-axis split** | a domain exploded into peer containers (each with its own DB/migrate) | **collapse** — one service per concern; the domain folds per D8 | qualification: `-web -prefill -agents -ontology -pdf -migrate` (6); controls: `-web -pdf -migrate`; reports: `report-composer` + `report-renderer`; `dashboard-redis` (a second Redis beside the shared one) |

**The tell:** a service whose `command` exits, or named `*-migrate` / `*-setup` / `*-grant`; a second instance of
shared infra (`dashboard-redis`); or a domain split into `-web` / `-pdf` / `-agents` containers.

**Target shape:** ~**3 layer services** (backend, webapp, eval worker) + ~**3 published** (catalogue, Superset
dashboard, plugin-publisher) + ~**8 infra** (postgres, redis, rabbitmq, minio, immudb, keycloak, caddy, devpi) +
opt-in tool profiles — down from ~41 default definitions. Migrations/init run **once, as a step**; a domain never
gets a container of its own.

**Why it matters.** Each container is a moving part (I8) — to build, start, monitor, secure, migrate, delete — and
a per-domain `*-migrate` container is also a per-domain migration tool (I5). **The container count is the repo
count (I9) seen from the deployment side**; they are split on the same wrong axis, so the two are fixed together.

**Candidate invariant I11:** one container per deployable process (a layer, a published service, or an infra
service); migrations and init are **steps**, dev tools are **profiles**, and a domain is **never** split across
containers. **Adopted as I11.**

### D11 — Backend structure: one Django app per domain (Phase 2)

The backend is a single Django app, `aisc_backend`, holding every domain in one package. Split it into **one
Django app per domain** — a **core** set plus the **optional** domains — all **inside the same `backend` repo**
(a Django app is a packaging unit, not a repo/service; I9). This is the enforcement unit for I5 (each app owns
its tables and migrations), I9 (a domain is a package, not a service) and I10 (optional apps depend on core).

**The unit is the table, not the noun.** A Django app is the **table-owning unit** (I5): it owns ORM models and
a `migrations/` directory. A *noun that owns no tables* — an auth adapter, a request door, the audit/ledger
writer — is a **module inside a core app**, not an app. Do not mint an app per noun; mint one per table-owning
domain. (This correction removes `ledger` and `identity`, which an earlier sketch of D11 proposed as apps.)

**Target app set** (pattern, not a final boundary; some rows are settled in the fold):

| app | kind | today (in `aisc_backend/models/`) | routers / areas |
|---|---|---|---|
| `core` | core | `common` (`Base`, `HasData`, `StorageContainer`), `project` (`Project`), `project_config` (`ProjectConfig`), `ai_system` (`AIComponent`, `AIComponentType`, `AISystem`) | project, project_by_name, project_config, component |
| `evaluation` | core | `evaluation`, `measure`, `metric`, `observation`, `artifact`; the per-evaluation bindings `EvaluationInput`, `EvaluationPlugin`, `EvaluationPluginStatus` | evaluation, file, task, internal, stats |
| `plugins` | core | `Plugin`, `PluginConfig`, `PluginConfigProjectConfig` | plugin |
| `audit` | core | the **one** governed-change record (I6): today `audit/` (immudb `audit_log`) | audit |
| `qualification` | **optional** | its Prisma tables → models | its APIs |
| `control_objectives` | **optional** | its Alembic tables → models | — |
| `controls` | **optional** | its Prisma tables → models | — |
| `report` | **optional** | folded report generation (D8) | — |

**Modules, not apps** (they own no tables — I5): the **auth adapter** (`keycloak`, the `membership` shim over
`aisc_identity.access`) and the **door** (request→project scoping). Both live in `core`.

**What the earlier sketch got wrong** (recorded so it is not reintroduced):

- **`ledger` is a platform shim and a duplicated concern.** `ledger.py` (+ `models.LedgerOutbox`) is the
  engine's half of a ledger the **platform owns**, bridged by a transactional outbox: each change inserts a
  row in its own transaction, and `manage.py deliver_ledger_events` (the `aisc-backend-ledger` container)
  HTTP-POSTs them to `POST /internal/projects/{pid}/ledger/events` with `PLATFORM_LEDGER_ENGINE_TOKEN`. Every
  part of that machinery — `PLATFORM_URL`, the token, the refusal codes, the per-database advisory lock — exists
  **only because the platform is a separate service**. Meanwhile `audit/` (immudb `audit_log`, single writer
  `clerk.write_event`) is a **second** append-only record of the same changes; the module's own docstring says so
  ("The engine's own audit log … is kept as it is"). Two records of who changed what is **I3** (one
  implementation per concern) and **I6** (governed changes are ledgered). **D3** (one backend, one DB) makes the
  outbox/relay machinery collapse to an insert in the same transaction; the *record* merges into the **one**
  `audit` app. There is no second app and no second record.
- **`identity` conflates an auth adapter with project-DB plumbing.** `keycloak.py`/`membership.py` are real but
  are an **adapter** — the one membership rule lives in `shared/identity` (`aisc_identity.access`). `projectdb.py`
  (alias-per-project router, `open_alias`, per-project `migrate_database`, run-ticket minting) and
  `project_door.py` exist **only because each project is a separate Postgres database today**; D3/D9 (one DB,
  `project_id` + RLS) collapse the alias/router/per-project-migrate and most of the door. Both are entangled with
  `deployment.py` (I4) and `platform_projects.py` (another platform shim). Neither owns a table → a module in
  `core`, reshaped by D3.

**Rules.**

1. **Never branch `INSTALLED_APPS` (I4).** Every app stays installed; a domain's *behaviour* is gated by a
   feature flag at the point of use. Dropping an app from `INSTALLED_APPS` to "disable" it is the
   `AISC_DEPLOYMENT` anti-pattern in a nicer dress.
2. **A Django app is not a repo or a service (I9).** One repo (`backend`), many apps; do not let "one app per
   domain" become "one repo/service per domain".
3. **An app owns tables (I5).** If the split would create an app with no `models.py` and no `migrations/`, it is
   a module, not an app.
4. **Dependency points coreward (I10).** Optional apps import core; core imports no optional app — enforced by
   an `import-linter` contract inside the backend.
5. **Schema-preserving move.** Keep `Meta.db_table` stable and use `SeparateDatabaseAndState` (state-only
   migrations) so no table moves and no data migrates; cross-app FKs keep the DAG acyclic.

**Why.** Each domain gets its own migration history, admin and label in the one tool (I5/D9); the core/optional
split becomes structural (I10); and the D8 folds land as **apps**, not services. It is the backend-level
expression of I9. Sorting by *tables* rather than *nouns* is what keeps the app count small and stops the
"an app per concept" drift that produced the domain slices in the first place.

### D12 — The platform application: domains into `backend`, the launcher flow into `webapp` (Phase 2)

The `platform` app is **not** one thing and is **not** one Django app. It is **a second backend layer** (I9/I3),
and it ships the Configurator's product UI as **static pages outside the webapp**. Split it in two:

**The service (`platform/platform_service/`, ~12.5k lines, 11 routers) is domains to fold into `backend`+`eval`:**

| platform module(s) | destination |
|---|---|
| `projects.py`, `membership.py`, `routes/{projects,authz,admission}` | `core` + the identity module — the *other* implementation of project/membership (I3) |
| `db.py`, `projectdb.py`, `migrate.py`, `migrations/`, `project-template/` | deleted/reshaped by D3/D9 — one DB, Django the one migration tool (I5) |
| `connection_store.py`, `target_store.py`, `connection_allowlist.py`, `connection_facade.py`, `adapters.py`, `targets.py`, `routes/{connections,facade}` | the **connections/adapters** concern beside `AIComponent` (D5) — a `connections` app |
| `secret_box.py`, `ledger/secrets.py`, `ledger/config_secrets.py` | the **one secret store** (I3) |
| `ledger/*` + `ledger-identity/` | the **one ledger/audit** concern (I6/I3) — merges with backend `audit/` (see D11) |
| `evidence.py`, `routes/evidence` | evidence domain |
| `llm_catalogue.py`, `llm_store.py`, `routes/llm` | LLM catalogue/keys domain |
| `helpers.py`, `helper_store.py`, `routes/helpers` | helper-models domain |
| `catalogue.py`, `plugin_sources.py`, `publisher.py`, `routes/catalogue` | `core`; the published **`catalogue` site stays separate** (a published artifact) |
| `reports.py` | the **`report`** domain (D8) |
| `dashboards.py`, `dashboard_bridge.py` | bridge folds to `core`; **Superset stays its own service** |
| `systems.py`, `engine_components.py`, `engine_runs.py`, `run_passes.py`, `local_controls.py`, `routes/engine` | **`evaluation`** (backend) + `eval` |
| `app.py` | the middleware/router wiring — the door (I2) and the run path (I1) in `backend` |

**The UI (`homepage/*.html`, 11 pages + assets; the launcher on Caddy:8100) is the product flow to re-express as
`webapp` pages**, pointed at the one backend API:

| launcher page | the step | becomes |
|---|---|---|
| `index.html` | project list (Configurator home) | a webapp page |
| `project.html` | a project — "plan the assessment", the four steps | a webapp page |
| `connections.html` · `llm.html` · `helpers.html` · `logs.html` | Manage: connections · LLM keys · helpers · activity | webapp pages |
| `evidence.html` · `evidence-map.html` | Collect evidence · Evidence map | webapp pages |
| `results.html` · `catalogue.html` | Results (→ Superset) · catalogue pages | webapp pages |

**Keep the flow, move the surface.** What falls out of the move (why it is worth one decision):

- **`scripts/` retires** — its `homepage`/launcher tests (`scripts/tests/*`) become webapp e2e.
- **The `/api/* → platform` Caddy hop dies** — one API, one origin (I3), no proxy rewrite.
- **`AISC_DEPLOYMENT` (I4) retires** — the webapp already expresses it as a flag (`standalone | configurator`).

**Do not:** make `platform` one Django app (a second monolith beside `aisc_backend` — I3/I9); or re-express the
launcher as Django templates/admin. The webapp is the **presentation layer** (I9); Django admin is ops, not the
product UI.

---

## 5. Binding invariants (the rules any implementation must obey)

These are normative and enforced (`ARCHITECTURE.md`; guards in `tests/architecture/`). `MUST`/`MUST NOT` are
not stylistic.

- **I1 — A run is self-contained.** Hand the worker everything at dispatch; it finishes with the backend
  and platform **down**; the backend observes status by id; results are posted at the end. *Never add a
  mid-run call from the run path to a backend/platform endpoint.*
- **I2 — A door, not a credential.** A plugin never receives the assessed system's secret; it calls a door
  that lives with the run, withholds the key, enforces the allowlist, and scrubs.
- **I3 — One implementation per concern.** One project/identity model, one membership, one secret store,
  one project-DB path, one connection/adapter model (beside `AIComponent`). Extend the backend/webapp; do
  not add a parallel model or app.
- **I4 — One app graph; flags, not modes.** No configuration changes `INSTALLED_APPS`/`MIDDLEWARE`/URLconf.
- **I5 — The domain is the model layer.** Own your tables via ORM models/migrations; never query another
  app's tables with raw SQL; one migration tool.
- **I6 — One place cuts a version; governed changes are ledgered.** Immutability in app code, not only in a
  trigger.
- **I7 — No secret leaves the point of use.** Scrub every outbound path (plugin, artifact, log, message).
- **I8 — A new moving part needs an ADR.** A service/database/datastore/dependency needs an owner, a cost,
  and a removal condition.
- **I9 — A boundary follows the architectural axis, never a business domain.** Justified by a **layer**
  (presentation, API/domain, execution, analytics), a **published artifact** (ABI, public site, registry) or
  the **composition root** (the parent repo — orchestration only, no app logic) — never a business domain. A
  domain lives as a *feature inside* `backend`/`webapp`/`eval`.
- **I10 — The core never depends on the optional domains.** The core (projects, components/connections, plugins,
  evaluation, runs, results) MUST run with qualification / control-objectives / controls **absent**; optional
  domains depend on the core, never the reverse. A lean install is a **profile**, not a fork (see §8).
- **I11 — One container per deployable process.** A container is one long-lived service (layer, published, or
  infra); migrations/init are **steps**, dev tools are **profiles**, a domain is never split across containers
  (see D10). The deployment view of I9.

**Enforcement (defense in depth):** `AGENTS.md` (agents read first) → guards in `tests/architecture/` →
`import-linter` contracts → a **required CI check** → `CODEOWNERS` + the PR checklist → an **ADR** for any
exception. A red guard is a stop, not a warning. Current guard status: **2 pass, 4 xfail** (the xfails
name invariants the code does not yet meet: I1, I3, I4, I9).

---

## 6. The development plan & mock kit (how to make it visible)

So the design is understood *by seeing it*, not by reading it.

- **Coverage:** a minimal set of use cases exercising every combination of **plugin (ML/LLM) × input
  (dataset/model/datashape/resource) × adapter (none/data/resource) × target (none/native/bespoke/agent)**.
- **Mock kit** (tiny, transparent, request-recording, so one fixture is both manually clickable and
  e2e-assertable):
  - *mock plugins:* `mock-llm`, `mock-table`, `mock-model`.
  - *mock adapters:* `rows-csv`, `rows-json` (data); `website-chat`, `agent-run` (resource).
  - *mock targets:* `mock-openai`, `mock-rest`, `mock-website` (not OpenAI-shaped, forces an adapter),
    `mock-agent` (submit→poll).
- **User flow (same shape per use case):** adapter present → connection (Manage → Components and
  connections) → evaluation (bind inputs, pick a compatible adapter) → run → inspect (the run names the
  adapter + version).
- **Test plan per use case:** unit (adapter contract) · compatibility (dropdown shows/hides correctly) ·
  manual+e2e (assert the metric **and** that the mock target recorded the call the adapter should have
  made).
- **Build order:** **Phase 0 = stand on the pilot's existing adapter path to make the first use cases
  visible in the real UI** (before any relocation), then the door (native), then resource adapters, then
  data adapters, then combinations, then polish.

Detail: [`../SCRATCH-platform-adapters/07-development-plan.md`](../SCRATCH-platform-adapters/07-development-plan.md).

---

## 7. Code smells to remove (and not recreate)

Each is a **second implementation** of something the backend/webapp already own. Full write-up:
[`../SCRATCH-platform-adapters/03-code-smells.md`](../SCRATCH-platform-adapters/03-code-smells.md).

| # | smell | where | resolved by |
|---|---|---|---|
| 1 | Two project-DB implementations | `platform/…/projectdb.py` **and** `apps/backend/…/projectdb.py` | D3, I3 |
| 2 | A binary mode forks the app graph | `AISC_DEPLOYMENT` rewrites apps/middleware/URLs/DB/schema; two `deployment.py` | D4, I4 |
| 3 | Parallel domain models | platform `connection`/`target` vs backend `AIComponent` | D3, I3 |
| 4 | Raw SQL across app boundaries | platform `psycopg` reads/writes Django's `engine.*` tables | D3, I5 |
| 5 | A control plane in `scripts/` | ~25,400 lines; `aisc.py` 1,906; a dozen `verify-*.sh` | D3 |
| 6 | N databases × 5 migration tools | Django / Prisma / Alembic / platform SQL / project-template SQL | D3, I5 |
| 7 | Adapter install = copy a folder + `docker restart platform` | `adapters/README.md` | D5 |
| 8 | Duplicated membership | `platform_service/membership.py` vs backend `auth/membership.py` | D3, I3 |
| 9 | Duplicated secret storage | `platform_service/secret_box.py` vs backend `config_secrets*.py` | D3, I3 |
| 10 | Version invariants in DB triggers | `project-template/0006…sql`; `DELETE` hole; migration reversal | D6, I6 |
| 11 | ~50 compose service definitions | 29 + 24 across dev compose files | D3, I8 |
| 12 | Runtime config generated, not committed | `aisc.py` writes `env.runtime`/`env.secrets`/`env.local` | D3 |
| 13 | Two notions of "the project" | platform project vs backend `aisc_backend_project`; `platform_projects.py` | D3 |
| 14 | E2E suite + published compose dropped on `pilot` | `e2e/*`, published `docker-compose*.yml` | decide at reset |
| 15 | Module boundaries justified by "replaceable services" that is not real | 12 git submodules; cross-app raw SQL (§4) | D8 (under discussion) |
| 16 | Containers split on the wrong axis; migrations/init as containers | ~41 compose services; `*-migrate`/`*-setup`/`*-grant`; `dashboard-redis`; qualification's six | D10, I5, I9 |
| 17 | An app (module) per *concern* that owns no tables | `audit/`, `auth/` proposed as Django apps in the D11 sketch; neither has `models.py` or `migrations/` | D11, I5 |
| 18 | A second record of who changed what | immudb `audit_log` **and** the platform ledger (`ledger.py` + `LedgerOutbox` + `aisc-backend-ledger`) | D3, I3, I6 |
| 19 | A product UI maintained as static HTML outside the webapp | `homepage/*.html` (11 pages, Caddy:8100) + the `/api/* → platform` hop; `scripts/` tests drive it | D12, I3, I9 |

---

## 8. Open questions / decisions to force

- **Native target:** for a target the runtime already speaks, keep the door always (recommended), or point
  the plugin straight at the endpoint with a run-scoped key? (D2)
- **Session lifetime:** is `open`/`call`/`close` enough for an agent session, and who owns it — the run or
  the row? (D5)
- **`produces`/input-type registry:** the id vocabulary that data adapters and plugins agree on. (D5)
- **Version cut:** who cuts a version, and when (on publish vs on save)? (D6)
- **Reset:** what are we happy to drop from `master` (the e2e suite, the published compose stack)?
- **Boundaries to keep (D8, under discussion):** the leading position keeps the **layer repos**
  (`backend`, `webapp`, `eval`, `results-dashboard`), the **published artifacts** (`catalogue`, `shared/*`) and
  the **composition root**; folds the **domain slices** (`qualification`, `controls`, `control-objectives`)
  and the **`platform` app** (into `backend` + `eval`).
- **Research vs compliance — profiles, not modes.** A researcher wants only the **core** (write a plugin, run
  it, see results — no qualification / control-objectives / controls); a compliance user wants the full four
  steps. The split MUST be **feature composition (I4)**, not a second app or a schema fork: define the
  **core**, make each compliance step an **optional domain**, and keep the dependency **one-way**
  (compliance → core, never core → compliance). Shipped as **install profiles** (compose) in the composition
  root, on one app graph and one schema. Invariant [**I10**](#5-binding-invariants-the-rules-any-implementation-must-obey).
- **Report generation vs Superset (D8) — decided.** Report generation depends on the DB/ORM/schema, so it is a
  **domain to fold** into `backend` (a `report` feature); **Superset analytics stays separate** — its own
  service/repo/container (`results-dashboard`).
- **I11 (containers) — adopted.** One container per deployable process (D10): migrations/init are **steps**,
  dev/admin tools are **profiles**, a domain is never split across containers.
- **Multi-turn/agent evaluation:** which agent-style plugin (agentdojo? promptfoo?) ships, since no
  evaluator drives a conversation today.

---

## 9. Known evidence (so claims can be checked)

Read against `origin/pilot`, `origin/master`, `origin/dev`, `origin/feat/unified-modules` (2026-11-09) and
the working tree (2026-11-11).

- **Branches:** base of divergence `f96264d`; `master`/`dev` +38, `feat/unified-modules` +247, `pilot` +25.
  `pilot` strictly supersets `feat/unified-modules` at the **submodule** level; their **superprojects** are
  independent lines. A reset to pilot is a rewrite (740 files, +121,391 / −2,467 vs master).
- **`unified-modules`:** `shared/identity/aisc_identity/{access,projectdb,ledger_events,service,gateway,headers}.py`,
  `shared/identity/projectdb-cases.json`, `shared/ledger-ts/*`.
- **Run/worker:** `apps/eval/aisc_eval/{celery_tasks,plugin_runtime,service/api_client,service/run_pass}.py`,
  `apps/eval/aisc_eval/deployment.py`; plugin env whitelist + run pass `celery_tasks.py:110-165`.
- **Platform/duplication:** `platform/platform_service/*` (12,489 lines; tests 21,569),
  `platform/platform_service/{projectdb,membership,secret_box,evidence,dashboards,adapters}.py`,
  `apps/backend/aisc_backend/{projectdb,deployment,project_door}.py`,
  `apps/backend/config/settings.py:132-154`, `apps/backend/aisc_backend/auth/membership.py`.
- **Adapters:** `adapters/README.md`, `platform/platform_service/adapters.py`,
  `shared/plugin-interface/src/aisc_plugin_interface/input_providers/`,
  `shared/plugin-manager/src/aisc_plugin_manager/loader.py`.
- **Versioning:** `platform/platform_service/db.py:330-371`,
  `platform/project-template/0006_project_system.sql:27-42`, `platform/migrations/0002…` then `0003…`.
- **Numbers:** `scripts/` ~25,400 Python lines (~40 scripts; `aisc.py` 1,906); ~50 compose service
  definitions; 27 project-template SQL files; 5 migration tools.

---

## 10. Glossary & conventions

- **Exploration branch** — a pilot (`pilot`, `feat/unified-modules`): a discussion point, not a release.
- **Independent module** — a module with its own repo/deploy, justified by an **architectural concern** (a
  layer) or a **published ABI** — not by a business domain (see D8, under discussion).
- **Module** — an app/service/package with a unified contract (Phase 1's subject).
- **Door** — the run-local endpoint (serving the plugin's protocol) behind which a connection/adapter sits.
- **Native vs bespoke target** — a system the runtime already speaks vs one that needs an adapter.
- **Data vs resource adapter** — feeds inputs (once) vs reaches a system (per call).
- **Session scope** — per run vs per row.
- `MUST`/`MUST NOT` are normative (invariants); "should/prefer" is a guideline.
- `file:line` refs are approximate; verify against the branch before relying on one.

---

### Related files in this repository

- [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — the binding invariants and enforcement.
- [`../AGENTS.md`](../AGENTS.md) — agent entrypoint.
- [`exploration-branches.md`](exploration-branches.md) — the framing in full.
- [`../docs/adr/`](adr/) — decision records (the sanctioned way to change an invariant).
- `SCRATCH-platform-adapters/` — the full design notes this brief condenses (not binding).
