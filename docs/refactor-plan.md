# Refactor plan — phased implementation, with the gates that hold the line

> **Audience:** a developer or an agent doing the work. This file is **self-contained**.
> **Date:** 2026-11-12. **Status:** binding for sequencing; the *rules* live in [`../ARCHITECTURE.md`](../ARCHITECTURE.md)
> and the *decisions* in [`unified-modules-and-pilot-brief.md`](unified-modules-and-pilot-brief.md) (D1–D12).
>
> **The one-line goal:** one backend, one webapp, one database, one way to do each thing — reached by moving
> the code in the order below, with the architectural guards **green at every step** so drift cannot accumulate.

---

## 0. How to use this plan

1. Read the **enforcement spine** ([§1](#1-the-enforcement-spine-invariant-guard-step)) — it says, per invariant,
   *which guard enforces it* and *which step fixes it*. That mapping is the plan's whole point.
2. Work the phases **in order**. Phases 0 and 3 are wrappers; the substance is Phase 1 then Phase 2 (the two
   phases of the [brief](unified-modules-and-pilot-brief.md)).
3. Before writing any code, run the guards:
   `uv run --no-project --with pytest python -m pytest tests/architecture -q`.
   **A red guard is a stop, not a warning.**
4. Each step below names the invariant(s) it satisfies and the **gate** that proves it. Do not mark a step done
   until its gate is green **and** the `xfail` marker it retires is removed (never delete a guard to pass it).
5. If a step cannot be done without changing an invariant: **write an ADR** (`docs/adr/`) and add the
   allowlist entry the guard needs. That combination is the *only* acceptable way to diverge.

**A guard's three states**

| state | meaning | what you do |
|---|---|---|
| **pass** | the code meets the invariant | keep it green |
| **xfail** | the code does **not** yet meet it; the gap is named | fix the code; the guard then `xpass`es |
| **xpass** | it just started passing | **remove the `xfail` marker** — do not delete the test |

---

## 1. The enforcement spine: invariant, guard, step

The invariants are [`ARCHITECTURE.md`](../ARCHITECTURE.md) I1–I11. Guards live in `tests/architecture/`
(see [`../tests/architecture/README.md`](../tests/architecture/README.md)). *Step* is where this plan closes the gap.

| invariant | guard (file · test) | today | closed by |
|---|---|---|---|
| **I1** run self-contained | `test_invariants.py · test_i1_worker_does_not_fetch_from_backend_midrun` | **xfail** | step 2.10 (+ the acceptance test) |
| **I1** (acceptance) | *to write* — run with backend/platform down | — | step 0.6, step 2.10 |
| **I2** door not credential | *to write* — extend `apps/eval/tests/test_plugin_environment.py` | — | step 2.6 |
| **I3** one implementation | `test_invariants.py · test_i3_plugin_interface_is_independent` | pass | keep green |
| **I3** one implementation | `test_invariants.py · test_i3_eval_worker_has_no_backend_import` | pass | keep green |
| **I3** one project-DB path | `test_invariants.py · test_i3_one_project_database_module` | **xfail** | step 2.1 |
| **I3** one ledger | *to write* — flag a second record of who changed what | — | step 0.6, step 2.5 |
| **I3** / **I9** one UI | *to write* — no product UI outside the webapp | — | step 0.6, step 2.8 |
| **I4** flags not modes | `test_invariants.py · test_i4_one_deployment_contract` | **xfail** | step 2.2 |
| **I4** (app graph) | *to write* — `INSTALLED_APPS`/`MIDDLEWARE` identical across flags | — | step 0.6, step 2.3 |
| **I5** domain is the model layer | *to write* — no app names another app's schema; one migration tool; **an app owns tables** | — | step 0.6, step 2.3 |
| **I6** one version cut | *(covered by I5 + the ledger guard)* | — | step 2.5 |
| **I7** no secret leaves use | *to write* — extend the existing scrub tests | — | step 0.6 |
| **I8** new moving part ⇒ ADR | process (review) | — | every step |
| **I9** boundary on the axis | `test_invariants.py · test_i9_no_domain_slice_module` | **xfail** | step 2.7 |
| **I9** (no domain UI) | *to write* — flag a product UI outside the webapp | — | step 0.6, step 2.8 |
| **I10** core first | *to write* — core imports no optional package; core runs alone | — | step 0.6, step 2.7 |
| **I11** one container per process | `test_invariants.py · test_i11_no_step_containers` | **xfail** | step 2.9 |
| layering | *to write* — `import-linter` contracts in `pyproject.toml` | — | step 0.5 |

**Reading the spine:** the `xfail`s are the live violations the refactor removes; the *to-write* guards are
enforcement that must exist **before** the code moves (Phase 0), so the refactor cannot reintroduce the smell.

---

## 2. Phase 0 — Foundations (make the rules enforceable *before* moving code)

**Why first.** A guard written after the code has already drifted only documents the drift. The whole point of
Phase 0 is that the shortest path to a feature *is* the compliant one, and that an agent working blind hits a
**red check**, not a reviewer.

| step | do | invariant | gate / exit |
|---|---|---|---|
| **0.1** | Land the rules: `ARCHITECTURE.md` (I1–I11), `AGENTS.md`, this plan, the brief, `docs/adr/`. | all | files reviewed; AGENTS.md is the entrypoint |
| **0.2** | Wire the guards into CI as a **required** check (the repository-checks job). | all | a PR that breaks a guard cannot merge |
| **0.3** | Add `CODEOWNERS` for `ARCHITECTURE.md`, `docs/adr/`, `tests/architecture/`. | I8 | review required on rule changes |
| **0.4** | Write the **ADR process** check: a PR touching an allowlist needs a linking ADR. | I8 | template + README in `docs/adr/` |
| **0.5** | Add `import-linter` contracts: `plugins → plugin-interface`; `eval → not platform, not backend internals`; `webapp → the backend HTTP API only`; `shared/*` acyclic. | I3, I9 | contracts in `pyproject.toml`, CI runs them |
| **0.6** | Write the **missing guards** (§1 "to write"): I1 acceptance, I2, I3-one-ledger, I3/I9-no-domain-UI, I4-app-graph, I5 (schema + one tool + app-owns-tables), I7, I10. | I1–I10 | each guard exists; each is `pass` or a named `xfail` |
| **0.7** | Record the **current** status board ([§7](#7-status-board)) so progress is visible. | — | the board matches `pytest -rxX` output |

**Exit:** every invariant has a guard; CI runs them as required; a rule change needs an ADR; the board is honest.

---

## 3. Phase 1 — `unified-modules` (the shared contracts)

The shared cross-cutting modules every app uses — the caller's identity, opening a project's data, keeping a
secret, writing a ledger event, calling a service. Run the **five steps of the [brief §2](unified-modules-and-pilot-brief.md)**
for **each** feature, in order.

| step | do | output | gate / exit |
|---|---|---|---|
| **1.1** | **Feature extraction.** Read `feat/unified-modules`; list features by **user-visible behaviour**. | a feature list (behaviour, actors, I/O, open questions, where to read it) | no file names as the deliverable (behaviour only) |
| **1.2** | **Architecture discussion.** Per feature: which existing mechanism it varies; where it lives; data/secret/version handling; ADR if needed. | a decision per feature | **I3** — extend a mechanism, never a second path; **I9** — no new repo |
| **1.3** | **Ticket creation.** One issue per shippable slice, naming its invariant(s) and guard(s). | tickets | small enough to review and demo |
| **1.4** | **Test plan.** Per ticket: unit + integration + one fixture driving manual+e2e, plus the invariant guard it turns. | test plans | the test shows the feature drives the system |
| **1.5** | **Implementation.** Merge against the main architecture. | code | guards green; ADR if an invariant changed |

**Exit:** the shared contracts exist as **features** with tests; no `unified-modules` code was merged verbatim;
guards introduced in 0.6 have moved toward `pass`.

---

## 4. Phase 2 — `pilot` consolidation (the substance)

Ordered by dependency: the database first (it removes the plumbing that makes everything else hard), then the
mode switch, then the backend shape, then the folds, then the edges.

### 2.1 One database + row-level security — `project_id`, one schema (D3, D9; **I3**)
- **What:** retire the per-project database (`project_<pid>`) and the second `projectdb.py`; every tenant row
  carries `project_id`; enforce isolation with RLS. Django migrations are the **one** tool.
- **Why first:** it removes the alias/router/`open_alias`/per-project-migrate machinery (I3), and it is what lets
  the core run alone (I10).
- **Gate:** `test_i3_one_project_database_module` turns **xfail → xpass** (remove the marker); a cross-tenant
  read test fails closed; RLS policy test green.
- **Exit:** one database; no per-project connection; membership and data resolve from `project_id`.

### 2.2 One app graph; flags, not modes (D4; **I4**)
- **What:** delete `AISC_DEPLOYMENT` and the `deployment.py` contracts in backend and worker; replace every
  branch with a **feature flag** read at the point of use.
- **Gate:** `test_i4_one_deployment_contract` turns **xpass**; the *to-write* app-graph guard shows
  `INSTALLED_APPS`/`MIDDLEWARE`/URLconf identical across flag combinations.
- **Exit:** no configuration changes `INSTALLED_APPS`, `MIDDLEWARE` or the URLconf; a lean install is a
  **profile** of flags.

### 2.3 Split the backend into Django apps (D11; **I5**, **I9**, **I10**)
- **What:** one app per **table-owning** domain — `core`, `evaluation`, `plugins`, `audit` (the one
  governed-change record) — plus optional apps later (2.7). Auth adapter and the door are **modules in `core`**
  (they own no tables).
- **How:** **schema-preserving** — keep `Meta.db_table` stable, use `SeparateDatabaseAndState` (state-only)
  migrations; cross-app FKs keep the DAG acyclic.
- **Gate:** the *to-write* I5 guard (an app owns `models.py` + `migrations/`; no app names another's schema);
  the I4 app-graph guard stays green; import-linter `core ← optional` holds.
- **Exit:** the backend is many small apps in one repo; no data moved; one migration tool.

### 2.4 Fold the `platform` service into `backend` + `eval` (D3, D8, D12; **I3**, **I9**)
- **What:** move the platform's domains into their destinations (D12 table): projects/membership → `core`;
  connections/adapters → a `connections` app (see 2.6); secrets → the one secret store; evidence, LLM catalogue,
  helpers, catalogue, reports, dashboards-bridge, engine → their apps. Delete the FastAPI app, its routers and
  its `migrations/`.
- **Gate:** no reference to `platform` as a service (import-linter + a grep guard); the platform's routes answer
  from the backend; the platform's SQL migrations are replaced by Django migrations.
- **Exit:** `platform/` is gone; its behaviour lives in `backend`/`eval`.

### 2.5 One ledger, one audit (I6, I3; D3)
- **What:** collapse the two records of who changed what into **one** — merge the platform ledger and the
  backend `audit/` writer; the outbox/relay/token/advisory-lock machinery disappears with the second service.
- **Gate:** the *to-write* one-ledger guard (no second outbox/record); the version/immutability tests stay green.
- **Exit:** one append-only governed-change record; no delivery container; no `LedgerOutbox`.

### 2.6 Connections and adapters beside `AIComponent` (D5; **I3**, **I2**)
- **What:** connections/adapters become a first-class, shipped concept beside `AIComponent` (`data`/`resource`;
  "agent" = resource + session; no `surface` axis; an adapter is needed iff the target is non-native). The plugin
  reaches a system through a **door**, never a credential.
- **Gate:** the *to-write* I2 guard (the plugin environment carries no assessed-system credential).
- **Exit:** one connection/adapter model; the door withholds the key, enforces the allowlist, scrubs.

### 2.7 Fold the optional domains, gated coreward (D8; **I9**, **I10**)
- **What:** `qualification`, `control_objectives`, `controls`, `report` become **optional apps** inside
  `backend` (and their UIs become webapp features). Dependencies point coreward; the core imports none of them.
- **Gate:** `test_i9_no_domain_slice_module` turns **xpass**; the *to-write* I10 guard shows the core imports no
  optional package, and the **core alone runs an evaluation** (I1 acceptance with compliance features off).
- **Exit:** module count is layers + apps; the core runs with the optional domains absent.

### 2.8 The launcher flow becomes the webapp (D12; **I9**, **I3**)
- **What:** re-express `homepage/*.html` + `assets/` as **webapp pages** (same flow: list → project → steps →
  evidence → results → manage), pointed at the one backend API.
- **Gate:** the *to-write* I3/I9 no-domain-UI guard (no product UI outside the webapp); the launcher's browser
  tests are replaced by webapp e2e.
- **Exit:** `homepage/` is gone; the `/api/* → platform` Caddy hop is gone; one origin.

### 2.9 One container per deployable process (D10; **I11**)
- **What:** migrations/init become **steps** of the one runner; dev/admin tools become **profiles**; a domain is
  never split across containers; one instance per infra service (drop the second Redis).
- **Gate:** `test_i11_no_step_containers` turns **xpass**; the compose lists only long-lived services by default.
- **Exit:** ~3 layer + ~3 published + ~8 infra services, plus opt-in profiles.

### 2.10 A run is self-contained (I1; D1)
- **What:** hand the worker everything at dispatch; it finishes with the backend and platform **down**; results
  post at the end. Remove the mid-run fetches.
- **Gate:** `test_i1_worker_does_not_fetch_from_backend_midrun` turns **xpass**; the **I1 acceptance test** (mock
  kit, backend unreachable) passes.
- **Exit:** the run path makes no mid-run call to a backend/platform endpoint.

### 2.11 Retire `scripts/` and the exploration branches
- **What:** delete the ~25k-line `scripts/` launcher (its tests moved to 2.8); `pilot` and
  `feat/unified-modules` are **spent** — their features are folded, their code is not kept (see
  [`exploration-branches.md`](exploration-branches.md)).
- **Gate:** no app logic in the parent repo (composition root only); the guards all `pass`.
- **Exit:** the composition root holds orchestration, CI/CD, deployment, e2e and docs — no app logic.

---

## 5. Phase 3 — Verification & hardening

| step | do | gate / exit |
|---|---|---|
| **3.1** | Every guard that was `xfail` is now **`pass`** with the marker removed. | `pytest tests/architecture -q` shows no `xfail` |
| **3.2** | `import-linter` contracts enforced in CI; no layer leak. | contracts green |
| **3.3** | The I1 acceptance test + the core-alone test run in CI as the flagship checks. | both green |
| **3.4** | Docs match behaviour: `ARCHITECTURE.md`, the brief, this plan, the nearest `README`s. | review |
| **3.5** | A fresh clone starts the stack with **one** command and runs the mock-kit use cases end to end. | the smoke path passes |

**Exit:** the invariants are enforced by a **green required check**, the code has one way to do each thing, and
an agent that ignores the docs is stopped by CI rather than by a reviewer.

---

## 6. The agent working agreement (drift resistance)

An agent doing heavy development here is expected to follow this loop. It is duplicated in
[`../AGENTS.md`](../AGENTS.md) on purpose — the agent may read either file first.

1. **Read the rules first.** [`../ARCHITECTURE.md`](../ARCHITECTURE.md) (invariants, binding) and this plan.
2. **Run the guards before proposing a change.** `uv run --no-project --with pytest python -m pytest tests/architecture -q`.
   A **red guard is a stop**.
3. **Port the need, not the code.** Do not port a module, endpoint or page because it *exists* on an
   exploration branch or in `platform/`. For each thing ask: **(a) is it needed?** (name the user-visible
   behaviour it serves) · **(b) does it duplicate or overlap something we already have?** (I3 — one
   implementation per concern) · **(c) can an existing mechanism be extended instead?** Then take a
   disposition, and **record it**:

   | disposition | when | what |
   |---|---|---|
   | **keep** | needed, no overlap | port it as a **feature** (behaviour, not code) |
   | **extend** | needed, overlaps | fold into the existing mechanism; do not add a second path |
   | **merge** | two branch things are one concern | port **once**, as the one implementation |
   | **drop** | not needed — dead pilot code, or already covered | a one-line reason on the ticket; **a decision to drop is as valuable as one to keep** |
   | **ask** | genuinely ambiguous — a plausible case both ways | **stop and ask a human**; the default stays *do not port* until answered |

   **Basic assumptions are fine** — a helper with no caller, a field nothing reads, a flag nothing consults:
   act on it and note the assumption. But when it is genuinely ambiguous — the thing is large, its need is
   unclear, or keeping it would add a second path — **ask a human rather than port it.** The default is
   **don't add**; the burden of proof is on keeping.
4. **Prefer, in order:** extend an existing module over adding one · a model over a query · a flag over a mode ·
   a local call over a network hop · a step over a container.
5. **Never** add a second implementation of a concern (I3), a second record, a parallel model/app, an
   `INSTALLED_APPS` branch (I4), a domain repo/service/UI (I9), a step as a container (I11), a mid-run call (I1),
   or a secret on an outbound path (I7).
6. **An invariant change is an ADR**, plus the guard's allowlist entry — nothing else. Do not edit an invariant
   to match code.
7. **New moving part (service, DB, datastore, top-level dependency) ⇒ ADR** with an owner, a cost, and a removal
   condition (I8).
8. **Keep changes inside the app that owns the concern.** If unsure which app owns it, **ask**.
9. **When a guard `xpass`es, remove the marker** — do not delete or relax the test.

---

## 7. Status board

Fill in from `uv run --no-project --with pytest python -m pytest tests/architecture -q -rxX`.

Recorded from `uv run --no-project --with pytest python -m pytest tests/architecture -q -rxX` on
`refactor/architecture-consolidation` (cut from `dev`, 2026-11-12). 14 passed, 4 xfailed.

| item | guard | state |
|---|---|---|
| I1 run independent | `test_i1_worker_does_not_fetch_from_backend_midrun` | **pass** — dispatch embeds the bytes; the run path never fetches |
| I2 door not credential | `test_i2_plugin_environment_is_an_allowlist` | **pass** — the plugin gets an allowlisted env, not the worker's |
| I3 one implementation | `test_i3_plugin_interface_is_independent`, `test_i3_eval_worker_has_no_backend_import`, `test_i3_shared_artifacts_are_acyclic` | **pass** |
| I3 one project-DB path | `test_i3_one_project_database_module` | **pass** (smell is `pilot`-only) |
| I3 one ledger | `test_i3_no_second_ledger` | **pass** (smell is `pilot`-only) |
| I4 flags not modes | `test_i4_one_deployment_contract`, `test_i4_app_graph_is_static`, `test_i4_urlconf_is_static` | **pass** (smell is `pilot`-only) |
| I5 domain is the model layer | `test_i5_installed_app_owns_tables` | **pass** (one app owns its tables) |
| I5 one migration tool | `test_i5_one_migration_tool` | **xfail** — Prisma under `qualification`/`controls` |
| I7 no secret leaves use | `test_i7_outbound_paths_scrub` | **pass** — stdout, stderr, logs, artifacts and errors are scrubbed |
| I8 new moving part ⇒ ADR | `test_allowlist_entries_are_adr_backed` | **pass** (allowlist empty) |
| I9 boundary on the axis | `test_i9_no_domain_slice_module`, `test_i3_no_product_ui_outside_webapp` | **xfail** — `qualification`, `controls` |
| I10 core first | `test_i10_core_does_not_import_optional` | **pass** |
| I11 one container per process | `test_i11_no_step_containers` | **xfail** — `make_buckets`, `controls-migrate`, `qualification-migrate` |
| CI runs the guards as **required** | `.github/workflows/architecture-guards.yaml` | **wired** — mark it a required status check in branch protection |
| `import-linter` enforced | static AST layer guards in this suite | **pass** — deliberate: apps are separate repos with separate venvs (see `tests/architecture/README.md`) |
| `homepage/`, `platform/`, `scripts/` retired | — | **n/a on `dev`** — those exist only on `pilot`; nothing to retire here |

The four remaining xfails are one cause seen from four angles: the `qualification` and `controls`
submodules are domain slices (I9) that ship their own migration tool (I5) and their own UI (I3),
and their per-domain `*-migrate` containers are step containers (I11). 2.7 folds the domains; 2.9
turns the migration into a step.

**Done on this branch so far (2026-11-12):** Phase 0 (docs, guards, CI, CODEOWNERS, allowlist);
the run is self-contained (I1); the plugin gets an allowlisted environment (I2); every outbound run
path scrubs (I7).

---

## 8. The doc set (portable, durable)

Keep these together; each has one job. An agent picking the work up cold needs only this set.

| file | job |
|---|---|
| [`../ARCHITECTURE.md`](../ARCHITECTURE.md) | **the rules** — invariants I1–I11, enforcement, ADR process, PR checklist |
| [`../AGENTS.md`](../AGENTS.md) | **the entrypoint** — one line per invariant; the map |
| `docs/refactor-plan.md` | **this file** — the phased plan and the invariant→guard→step spine |
| [`unified-modules-and-pilot-brief.md`](unified-modules-and-pilot-brief.md) | **the decisions** — D1–D12 and the five-step method |
| [`exploration-branches.md`](exploration-branches.md) | **how to treat pilot branches** — features, not code |
| [`../tests/architecture/README.md`](../tests/architecture/README.md) | **the gates** — what each guard checks, and what's still to write |
| [`adr/`](adr/) | **the exceptions** — the only sanctioned way to change an invariant |
| [`architecture.md`](architecture.md), [`appendices/`](appendices/) | **reference** — how AISC works today (descriptive; subordinate to the rules) |
| [`../SCRATCH-platform-adapters/`](../SCRATCH-platform-adapters/README.md) | **non-binding** design notes and code smells |

Everything needed to do the work — the rules, the decisions, the order, the gates — lives in this set.
