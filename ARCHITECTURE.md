# AISC — architecture invariants (binding)

> **Status: binding, clarified 2026-11-16 by [ADR 0001](docs/adr/0001-mainline-first-consolidation.md)
> and [ADR 0003](docs/adr/0003-frozen-unified-app-port-and-worker-boundary.md) (superseding
> [ADR 0002](docs/adr/0002-unified-app-first-feature-port.md)).** Written because several long-standing design
> rules exist only in people's heads and are broken, one feature at a time, by contributors (and
> agents) moving fast. This file makes them explicit and testable.
>
> **This file is normative.** `MUST` / `MUST NOT` are not stylistic. [`docs/architecture.md`](docs/architecture.md)
> *describes* how AISC works today; this file says what must stay true. **When they disagree, this
> file wins and `docs/architecture.md` is out of date** — fix the description, not the invariant.

## Why this file exists

AISC has a handful of load-bearing architectural decisions. They were made deliberately, are understood
by some of the team, and are **not written down anywhere that a contributor or an agent reads first**.
The result is predictable: someone needs a feature, takes the shortest path that ships, and the shortest
path quietly re-implements a concern, adds a callback, or stands up a second store — accruing debt that
is expensive to remove later.

A contributor familiar with the codebase would have recognised the feature as a *variation of an existing
mechanism* and implemented it inside that mechanism. This file is how we give everyone — human or agent —
that recognition, and how we make non-compliance **fail a check** instead of quietly merging.

**The design goal of every rule below is the same:** one way to do each thing, at the layer that already
owns it, with the smallest number of moving parts.

## How to use this file

- **Read it before you change anything structural.** If a change touches a service boundary, a
  database, a secret, a run, or a plugin, it touches an invariant.
- **Find the invariant your feature is a variation of, and extend that.** Do **not** add a second path.
- **If you believe an invariant must change, stop and write an ADR** (see [Changing the architecture](#changing-the-architecture)).
  A PR that breaks an invariant without an ADR is rejected — that is the whole point of this file.
- **Run the guards before proposing a change** (see [How compliance is enforced](#how-compliance-is-enforced)):
  `uv run --no-project --with pytest python -m pytest tests/architecture -q`.
- **To change the code to match these rules, follow [`docs/refactor-plan.md`](docs/refactor-plan.md)** — the
  phased plan, and the invariant → guard → step spine that turns each red guard green.

---

## The invariants

**Delivery scope (ADR 0003):** selectively merge frozen `feat/unified-app` layer commits onto main;
complete the pilot feature port (including reporting) in the consolidated layers. I1/I2 and inherited
*per-run target credential* exposure are deferred to the post-port execution milestone. Immediately
stop plugin subprocesses from inheriting worker-wide service secrets. Project isolation is
required through the shared ORM/access mechanism; PostgreSQL RLS is not required. Other consolidation
rules remain in force. The detailed sequence and acceptance gates live in `docs/refactor-plan.md`.

### I1. A run is self-contained — the worker never needs the backend to finish it

> **A run is handed everything it needs at dispatch, then completes on its own.** The eval worker MUST
> receive, with the run, every input it will use: the evaluation and its tests, their inputs, the dataset
> and model bytes, the connection descriptors (URLs) with a run-scoped secret, the helper-model keys, and
> the project settings. During the run the worker MUST NOT depend on `aisc-backend` or `platform` being
> up. The backend observes the run's **status by id** (the queue's result backend); when the run is done
> the eval module **posts its results** (measures, artifacts, final status) to the backend to store.

**Why.** A run can be long. Deployments, restarts, and outages happen. If the worker needs the backend
mid-run, then a backend restart fails or stalls every in-flight run, and every run is exposed to a network
hop it does not need. Making the run self-contained turns "the backend was restarted" from an incident
into a non-event: the run finishes; the results are posted when the backend is back.

**Today.** Broken, in two ways:
- the worker *fetches* its request, inputs, and dataset/model files from the backend **during** the run
  (`apps/eval/aisc_eval/service/api_client.py`: `get_evaluation_request`, `get_evaluation_inputs`,
  `get_dataset_file_content`, `get_model_file_content`) — so an outage mid-run fails the run; and
- `pilot` routes the **plugin's own calls to the system under test back through the platform's doors**
  (`docs/architecture.md` §4; `PLATFORM_RUN_PASS`) — so every assessed call depends on `platform` being up.

**Broken when (the tell).** Someone adds a call from the run path to a backend or platform HTTP endpoint,
or injects a service address/credential that only resolves while that service is up. If a reviewer can
say *"and if this service is down, the run still finishes"* and the answer is no, I1 is broken.

**Correct shape.** `run_plugin` receives a **self-contained job payload**; it writes intermediate state to
its own workspace and the queue's result backend; a single `post_results` step sends measures, artifacts
and status at the end (idempotent, retried). See [the worked example](#worked-example-the-worker-rule-i1).

**Delivery scope (ADR 0003):** dispatch independence and the local door are deferred until after the
merge/feature port, along with worker-loss recovery, retry design and execution hardening. Existing
backend-dependent execution is explicitly accepted for this delivery. The worked example below is the
follow-up acceptance target, not a consolidation gate.

### I2. A plugin reaches a system through a door, not a credential

> **A plugin MUST NOT be given the credential of the system it assesses.** It calls a **door** that speaks
> its protocol; the door (a) withholds the key, (b) enforces the project's allowlist and timeout, and
> (c) scrubs the answer. The door MUST live **with the run**, not on a shared service — otherwise it
> re-introduces I1.

**Why.** Plugins are catalogue code and run arbitrary Python; a plugin given the target key can exfiltrate
it. Handing the plugin a short-lived door instead keeps the key out of the plugin process and gives a
single place to enforce the allowlist — at the cost of one *local* hop, which is free. This is the
existing `@system_under_test` design; it only works if the door is in the worker.

**Today.** On `pilot` the door is the **platform** (the plugin calls `PLATFORM_URL` with a run pass);
the intended shape is a loopback door inside the eval worker, with the plugin unchanged
(see [`SCRATCH-platform-adapters/06-adapters.md`](SCRATCH-platform-adapters/06-adapters.md) §9).

**Broken when.** A plugin environment contains a target/connection secret (`AISC_TARGET_API_KEY` and the
like), or the plugin is pointed at a URL that is not the run's own door.

**Delivery scope (ADR 0003):** the plugin subprocess must not inherit worker-wide service secrets;
existing explicit per-run target credentials remain a temporary exception. Preserve required adapter
functionality; implement the run-local door after the feature port.

### I3. One implementation per concern

> **A concern the backend or webapp already owns MUST NOT be re-implemented.** One project/identity model,
> one membership check, one secret store, one project-database path, one connection/adapter model (beside
> `AIComponent`), one auth, one test story. New work **extends** the backend/webapp; it does not add a
> second application or a parallel model.

**Why.** Every second implementation is a place to fix the same bug twice, a schema to keep in step, and
two answers to "what is a project?". The cost compounds; the duplication is what makes the system hard to
change.

**Today.** The `pilot` branch adds a `platform` service that duplicates backend concerns: a second
project-DB module (`platform/platform_service/projectdb.py` beside `apps/backend/aisc_backend/projectdb.py`),
a second membership (`platform_service/membership.py`), a second secret store
(`platform_service/secret_box.py`), and a parallel `connection`/`target` domain beside `AIComponent`.
See [`SCRATCH-platform-adapters/03-code-smells.md`](SCRATCH-platform-adapters/03-code-smells.md).

**Broken when.** A new module answers a question another module already answers, or a new service holds
state another service already holds.

### I4. One application graph; features are flags, not modes

> **`INSTALLED_APPS`, `MIDDLEWARE` and the URLconf MUST NOT change with configuration.** A behaviour that
> differs between deployments is a named **feature flag**, read at the point of use, recorded in one
> registry, validated at startup. A fresh install works with **no flags set**; flags opt in.

**Why.** A mode that rewrites the application graph creates two apps that are each half-tested, and hides
the real knob ("authenticate locally") behind a deployment identity. Independent features should toggle
independently.

**Today.** `AISC_DEPLOYMENT` (`standalone`|`configurator`) rewrites the app graph and the schema
(`apps/backend/config/settings.py`, `aisc_backend/deployment.py`; migration `0019`/`0021`). It is
re-implemented in the worker. See [`SCRATCH-platform-adapters/02-consolidation.md`](SCRATCH-platform-adapters/02-consolidation.md) §12.

**Broken when.** Settings branch on a mode, or a second copy of the mode contract appears.

### I5. The domain lives in the model layer; one migration tool

> **Tables are owned by an app's ORM models and its migrations.** An app MUST NOT read or write another
> app's tables directly, and MUST NOT carry a second migration tool. Cross-app reads go through an API or
> a model, never through hand-written SQL against another app's schema.

**Why.** Models and migrations are how schema change is made safe and reviewable. Raw SQL across a
boundary has no migration, no type check and no owner: a change on one side silently breaks the other, and
the two apps cannot in fact deploy independently.

**Today.** The `platform` reads and writes the engine's Django-owned `engine.*` tables with `psycopg`
(`platform/platform_service/evidence.py`, `dashboards.py`); the tree carries five migration tools
(Django, Prisma, Alembic, platform SQL, per-project template SQL).

**Broken when.** A query names another app's table/schema from outside that app.

**Scope (ADR 0001):** Django owns AISC's relational domain tables. Main's existing immudb audit store
keeps its provisioning mechanism, and third-party services keep their upstream metadata migrations.

**Project isolation (ADR 0003):** deny-by-default shared ORM query scoping and role checks enforce tenancy for this
refactor. Cover core and optional-domain reads, writes, related-object references and downloads.
PostgreSQL RLS is a possible later improvement, not a required mechanism or acceptance gate.

### I6. Every governed change is versioned from one place, and ledgered

> **A version is cut in exactly one place, its immutability is enforced in application code, and every
> governed change uses the one backend audit writer.** A report names the version it is about.

**Why.** The version is what ties the steps together and makes a report defensible; if any step can cut
or mutate it, the guarantee is gone. The one audit store records governed actions under the delivery
scope below.

**Pilot today.** Versions are rows in the per-project DB, created only by the platform, with immutability
enforced **by triggers** that do not block `DELETE` (§3; smell #10).

**Broken when.** A second code path writes a version, or an invariant lives only in a trigger.

**Delivery scope (ADR 0001):** retain main's `aisc_backend.audit` + immudb implementation and history.
Audit calls are best-effort, as on main: an immudb failure can lose an event without rolling back the
business action. Guaranteed delivery and atomicity across Postgres/immudb are not promised by this
refactor. Do not port pilot's separate ledger/witness/outbox/relay system. The audit writer remains a
module rather than a new Django app with invented Postgres tables.

### I7. No secret leaves the point of use

> **A secret is decrypted only where it is used, and MUST NOT appear in a plugin, an artifact, a log or a
> message.** Answers and errors are scrubbed. A run record names the plugin and the adapter used — never
> their secrets.

**Why.** The scrub layer is the difference between a leak and a non-issue; it only holds if it is applied
on every path that can carry a secret outward.

**Broken when.** A new outbound path (a log, an artifact, an error, a message) is added without the scrub.

**Delivery scope (ADR 0003):** plugin child environments must exclude worker service secrets **now**.
Inherited explicit per-run target credentials are deferred to the run-local door milestone. Ported
feature APIs, reports, logs and artifacts still must omit secrets; no new disclosure path is authorised.

### I8. A new moving part needs a decision record

> **A new service, database, datastore or top-level dependency requires an ADR** that names the owner, the
> cost, and the condition under which it is removed. Prefer fewer moving parts; every one is something to
> build, start, monitor, secure, migrate and eventually delete.

**Why.** The single biggest source of complexity in `pilot` is the number of moving parts that arrived one
at a time without a recorded cost.

### I9. A boundary follows the architectural axis, never a business domain

> **A repo, app or service boundary MUST be justified by an architectural concern (a layer), a
> published/external artifact (an ABI, a public site, a registry), or the composition root (the repository
> that deploys, tests and versions the parts, holding **no application logic**) — never by a business
> domain.** A business domain — a new assessment step, "qualification", "controls" — MUST be a *feature
> inside* the layer that already owns it: the UI in `webapp`, the API and models in `backend`, the execution
> in `eval`. A domain module MUST NOT re-implement a layer it could use from that layer's repo.

**Why.** A domain slice ships its own frontend + API + DB + migration tool, so it duplicates the layers (I3)
and leaves nowhere for the cross-cutting concerns — project, membership, secrets, ledger, version,
`AIComponent` — to live. Those gaps are exactly what spawned the `platform` service and the raw SQL across
schemas. One repo per layer gives each concern a single owner; a domain then *composes* the layers instead of
copying them.

**Today.** Three domain slices are their own repos — `qualification`, `controls`, `control-objectives` — each
re-implementing a frontend, API, DB connection and migration tool (qualification ships a frontend + Python
services + Prisma; control-objectives ships its own Alembic). `catalogue` is **not** a violation: it is a
**public website** (a published artifact), so it stays its own repo. The `platform` app is a fourth kind —
neither layer nor domain, but a **second implementation of the backend layer** (I3) — so it folds into
`backend`/`eval` (brief D3). Meanwhile the layer repos already hold domains as *features*, which is the
intended shape: `backend` carries evaluation, plugins, AI components, results, audit and versioning
(`aisc_backend/{models,routers,repositories,services}`); `webapp` carries the plugin, evaluation, project and
AI-system UI; `eval` carries the evaluation/project run model.

**Broken when.** A new repo/submodule is created to hold a *feature* instead of a layer, or a layer is
re-implemented for one domain — a second API, a second DB connection/migration tool, a second frontend, a
second auth. **The tell:** a module carrying a `package.json` *and* a schema/migration *and* an HTTP API is a
domain slice.

**Correct shape.** One repo per **layer** (`backend`, `webapp`, `eval`, `results-dashboard`); one per
**published artifact** (`catalogue` the public site; `shared/plugin-interface`, `plugin-manager`,
`report-plugin-interface` the ABIs); and the **composition root** (the `aisc` parent repo: compose, CI/CD,
deployment, e2e, docs — **no application logic**). Business domains are features inside the layers.

### I10. The core never depends on the optional domains

> **A core capability MUST NOT depend on an optional domain.** The **core** — projects, components/connections,
> plugins, evaluation, runs, results/visualizer — MUST work with the optional domains (qualification,
> control-objectives, controls) **absent**. An optional domain MAY depend on the core; the core MUST NOT depend
> on an optional domain, and the split MUST NOT be a deployment mode (I4).

**Why.** Some users — researchers — want only the core: write a plugin, run it, see the results. They are not
interested in qualification, control objectives or controls. If the core depends on a compliance step, that
lean install is impossible without a fork. A one-way dependency makes "the core alone" a supported
configuration, not a stripped-down build.

**Today.** The steps are **peers, not layers**: each is its own service with its own DB and migrations (I9), so
there is no core to run alone — you run all of them or hand-strip containers.

**Broken when.** A core module imports or reads an optional domain, or a compliance step is required for a run
to execute. **The test:** start the core alone and run an evaluation — it MUST work.

**Correct shape.** The core is the base; each compliance step is an optional module layered on top, gated by a
feature flag (I4) and shipped as an **install profile**. Dependencies point coreward.

### I11. One container per deployable process

> **A container MUST run exactly one long-lived deployable process** — a layer service, a published service, or
> an infra service. **Migrations, grants and setup are steps, not containers** (they run once through the one
> migration runner, D9/I5, or an init hook). **Dev/admin/observability tools are opt-in profiles**, never
> default. **A business domain MUST NOT be split across containers.**

**Why.** Every container is a moving part (I8) to build, start, monitor, secure, migrate and delete. A fleet of
one-shot containers and per-domain fragments cannot be reasoned about (the dev compose has ~41 definitions and
~10 of them run-and-exit). A per-domain `*-migrate` container is also a per-domain migration tool (I5) in
costume. This is the *deployment* view of I9 — the container count is the repo count seen from the other side,
so the two are split and fixed on the same axis.

**Today.** ~41 service definitions; ~10 are one-shot (`*-migrate`, `*-setup`, `*-grant`); tools (`aisc-eval-flower`,
`pgadmin`, `schema-docs`) are default; domains are exploded (`qualification` = 6 containers).

**Broken when.** A service's `command` exits; a container is named `*-migrate` / `*-setup` / `*-grant`;
or a domain is split into peer containers.

**Correct shape.** Layer services + published services + necessary infrastructure, plus opt-in tools.
Migrations/init run **once, as a step**. Retain Superset's isolated `dashboard-redis` (ADR 0001): its
pickle-backed cache must not be writable by evaluation plugins. Container count is not an acceptance target.

---

## Worked example: the worker rule (I1)

This is the rule that `pilot` broke, and the template for the others.

**What the rule means.** A run is a job, not a conversation. The backend *dispatches* it and *observes*
it; it is not in the loop.

```
backend ──(dispatch: the whole job, incl. bytes + run-scoped secrets + descriptors)──▶ worker
backend ◀──(observe: status by task id)── queue result backend
worker  ──(run to completion; the plugin calls the run's own door)──▶ system under test
worker  ──(on finish, post: measures, artifacts, final status)──▶ backend  [the only run→backend call]
```

**What `pilot` does instead.**

```
worker ──(mid-run: fetch request/inputs/files; mark status)──▶ backend     ← breaks I1
plugin ──(every assessed call + run pass)──▶ platform door ──▶ system       ← breaks I1 (and I2)
```

It looks reasonable — "the platform holds the secret, so let it proxy" — but it makes every run depend on
`platform` being up, which is exactly what the self-contained design avoids. The same feature is delivered
correctly by putting the door **in the worker** and handing the run a run-scoped secret up front.

**The post-port acceptance test (and the guard; ADR 0003).** With everything dispatched, take the backend's API URL away
(point it at a black hole / stop the container) and run a real evaluation with the mock kit
([`SCRATCH-platform-adapters/07-development-plan.md`](SCRATCH-platform-adapters/07-development-plan.md)):
**the run MUST complete and produce its measures.** Then restore the backend and assert the results post.
That single test is worth more than any prose: it fails the moment someone re-introduces a mid-run call.

## How compliance is enforced

Agent instructions and human review own architectural judgement. A small set of automated regression
checks complements them: tests catch repeatable mistakes, not whether an architecture is good. A new
bespoke checker for each invariant is not a prerequisite for the refactor (ADR 0001).

1. **`AGENTS.md` (root).** The first file a coding agent reads: one line per invariant, the command to run
   the guards, and the instruction to stop and write an ADR rather than break one. (Also summarised in
   `CONTRIBUTING.md` for people.)
2. **Mechanical guards — `tests/architecture/`** (pytest). The authoritative table is
   [`tests/architecture/README.md`](tests/architecture/README.md). Today `test_invariants.py` holds the
    checks; the list below identifies candidate behavioural checks to add with the owning feature,
    rather than a mandatory Phase 0 tooling project:
    - **I1** `test_i1_worker_does_not_fetch_from_backend_midrun` (named baseline under ADR 0003) +
     post-port acceptance test (backend/platform unreachable → the run completes and posts).
    - **I2** now — plugin child gets no worker-wide service secrets; post-port — the plugin receives a
      run-local door instead of a target/connection credential.
   - **I3** `test_i3_plugin_interface_is_independent` · `test_i3_eval_worker_has_no_backend_import` (pass) ·
     `test_i3_one_project_database_module` (xfail) + *to write* one-ledger and no-domain-UI.
   - **I4** `test_i4_one_deployment_contract` (xfail) + *to write* `INSTALLED_APPS`/`MIDDLEWARE`/URLconf
     identical across flag combinations.
    - **I5** feature checks — no cross-owner table access; Django owns product relational migrations;
      respect ADR 0001's existing immudb and third-party metadata exceptions. New domain apps own tables.
   - **I7** *to write* — extend the existing scrub tests.
   - **I9** `test_i9_no_domain_slice_module` (xfail) + *to write* no product UI outside the `webapp`.
   - **I10** *to write* — the core imports no optional-domain package; the core alone runs an evaluation.
    - **I11** `test_i11_no_step_containers` (named baseline) — no new step service; preserve the
      justified Superset cache isolation.
3. **Import contracts** where useful; an extra tool is not required up front. The concrete DAG:
   `plugins` → `aisc_plugin_interface` only; `aisc_eval` → **not** `platform`, **not** the backend's
    internals; `webapp` → the backend's HTTP API only; `shared/*` is acyclic. Python import checks do
    not enforce JavaScript/TypeScript dependencies; review those with the frontend's tooling.
4. **CI.** Run the small architecture suite alongside feature tests. Require the relevant checks for
    merge; no claim is made that a green heuristic suite proves every invariant.
5. **Ownership + review.** `CODEOWNERS` on the boundary files; a PR-template line: *"Does this change break
   an invariant? If yes, link the ADR."*

**Existing violations** are itemised baselines under ADR 0001; ADR 0003 extends only the execution
baseline's expiry to the post-port milestone. New detected findings fail normally; only known findings
are expected failures. Review the source-specific baseline when merging main/unified-app rather than
blindly copying the pilot findings. A cleared baseline passes; remove its retired entries.

**Exceptions** are allowed but explicit: a **temporary allowlist entry** in the relevant guard, with an
issue link and an expiry, plus an ADR. An allowlist entry without an expiry is itself a smell.

## Changing the architecture

Architecture changes go through a short **ADR** in [`docs/adr/`](docs/adr/):

```
# NNNN. <title>
Status: proposed | accepted | superseded by NNNN
Invariant: I<n> (changed or waived)
Context: what forces the change
Decision: what we will do
Consequences: cost, owner, and the condition under which we would remove it
```

An ADR is what turns "an individual ran ahead" into "the team decided". The guard is then updated with the
ADR's id. This is intentionally heavier than a code change and lighter than a meeting.

## Pre-flight checklist (paste into a PR)

- [ ] I read the relevant invariant and my change **extends** the existing mechanism (I3).
- [ ] **Porting** — if this comes from an exploration branch or `platform/`: is it **needed**, and does it not
  duplicate or overlap what we already have? (recorded as keep / extend / merge / drop / ask; **ambiguous ⇒ ask
  a human**, default not to port.)
- [ ] **I1/I2** — during the port, prevent worker-wide secrets reaching plugin subprocesses and retain
  existing per-run behaviour within ADR 0003's named scope; post-port, verify backend-down completion
  and the run-local credential-withholding door.
- [ ] **I4** — if this changes settings: is it a flag at the point of use, not a mode?
- [ ] **I5** — if this touches data: is it an ORM model/migration in its owning app, not raw SQL across a boundary?
- [ ] **I7** — if this can carry a secret: is it scrubbed?
- [ ] **I8** — if this adds a service/database/store/dependency: is there an ADR?
- [ ] **I9** — if this adds a repo/app/module: is the boundary a **layer** or a published **ABI**, not a
  business domain? Is the domain a feature inside `backend`/`webapp`/`eval`?
- [ ] **I10** — if this touches the core: does the core still run with the optional domains absent?
- [ ] **I11** — if this adds a container: is it **one long-lived process**, not a step (`*-migrate`/`*-setup`),
  a dev tool, or a domain fragment?
- [ ] `uv run --no-project --with pytest python -m pytest tests/architecture -q` passes (or the ADR/allowlist explains why not).
