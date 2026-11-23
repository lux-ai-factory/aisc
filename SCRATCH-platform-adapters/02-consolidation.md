# Consolidation — one backend, one database, one UI

> From `SCRATCH-platform-adapters-discussion.md` §1, §4 and §11, plus **§12 (new: feature flags)**.
> This is the capstone argument: the `platform` app and the `scripts/` control plane duplicate what the
> backend + webapp already do. The fix is **one backend + one webapp + one database with
> project-scoped access**, and **feature flags instead of a deployment mode**.
> Related: [`03-code-smells.md`](03-code-smells.md) (the same problems, itemised as smells).

---

## §1. One database per project — I don't buy it

**My position.** I've never seen this pattern. Why not **one database**, with access scoped by the project row (a `project_id` column on the shared tables) plus per-user/per-role row access, rather than N physical databases? Per-project DBs add real complexity for a benefit I can't see.

**What pilot does (evidence).**
- Project DB is `"project_" + pid` without hyphens (`platform/platform_service/projectdb.py:34-38`).
- `provision()` runs `CREATE DATABASE` then applies a **27-file template** `platform/project-template/*.sql`, tracked in `provision.template_migration` (`projectdb.py:63-77`).
- It runs **synchronously in the request** (`POST /projects` → `provision_or_undo`, which **drops the DB on failure**) (`platform/platform_service/routes/projects.py:75,89-104`).
- One schema per step (qualification, control_objectives, controls, engine, report_composer, …), each app role gets USAGE+CREATE **only on its schema**; three read-only roles (`report_ro`, `dashboard_ro`, `inspector_ro`).
- Drift across N DBs is managed by `scripts/db_consistency` (C1 orphans, C7 "every DB at every head") and `scripts/superset_upgrade_check.py`.

**Costs this creates (to name in the meeting).**
- **No connection pooling per DB** — every call opens/closes a per-project connection (`platform/platform_service/db.py:283-303`); pilot's own verifier warns above 80% `max_connections` and suggests PgBouncer.
- **No cross-project queries or FKs** (`projectdb.py:1-5`) → any platform-wide view is N queries.
- **Migrations × N databases × 5 different migration tools** (Django / Prisma / Alembic / platform SQL / per-project template SQL) — `scripts/db_consistency/heads.py`; C7 compares only tracker names, not data.
- **No cross-DB transactions**; project delete is `DROP DATABASE … FORCE` (`projectdb.py:94-97`); partial restore leaves orphans.
- Five places must agree on the same schema shape.

**The other side will say.** Isolation/security per tenant, "blow away one project cleanly", per-project immudb ledger, simple `DROP DATABASE` deletion. I should be ready to answer: a single DB with `project_id` + Postgres **Row-Level Security** and per-app roles gives the same isolation with one migration target and normal pooling.

**Decision to force:** single DB + RLS vs per-project DBs; if we stay per-project, accept/own the pooling and migration-fan-out costs.

---

## §4. Platform app vs extending webapp/backend — and folding in controls/qualification

**My position (biggest one).** There should be a platform app concept, yes. But **backend, eval and webapp were built first and independently** of controls, qualification and the platform app. The platform app now **repeats or moves concepts that already exist**:

- backend/webapp/eval already model **`AIComponent`** (`AIComponentType`, `AISystem`, `ProjectConfig`) — `apps/backend aisc_backend/models/ai_system.py:6-64`, edited in the webapp (`apps/webapp src/components/AISystemSettings.tsx`).
- pilot adds a parallel **`connection`** concept at the platform level (`platform/platform_service/routes/connections.py`, `connection_store.py`, schema `connection`, plus `target`), i.e. **"Connections" at the super-app level duplicating AIComponent's connection/llm/resource role**.
- pilot's platform reaches into other apps' tables with **raw SQL**, not models (`platform/platform_service/evidence.py:93-196`, `dashboards.py:24-34`).
- The backend on pilot **still keeps `AIComponent`**, so now both models exist.

**What I want.**
- If we need a platform web UI, **extend the existing webapp/backend** rather than stand up another app. The backend already has a good Django setup — admin, migrations, tests, ORM, auth.
- **Fold controls and qualification into webapp/backend** (or at least put them on the same ORM/migration base), so we get: one DB access path, **no raw SQL**, versioned models/ORM only, one test story, one auth story.
- Stop having the platform re-implement engine concepts (connections/llm/resources) as strings and raw tables.

**The other side will say.** Submodule boundaries and independent deployability; controls/qualification are separate products/repos; Next apps vs Django; the platform is the only shared place for cross-step data. Rebut: the duplication and the raw-SQL coupling already break "independent"; a shared Django app with apps/modules + versioned models is the cheaper path.

**Decision to force:** is the platform app a *new* codebase or a set of modules in webapp/backend? Do controls/qualification move under it? (The full consolidation case — and a plan to retire the `platform` app — is §11.)

---

## §11. Consolidation: retire the platform app — one backend, one database, one UI (2026-11-11)

**My position (the capstone; extends §1 and §4).** The `platform` service, the `scripts/` control plane, and the per-project-DB machinery are three parallel implementations of things the Django backend + webapp already do. The coherent system is **one backend (Django) + one webapp**, holding `AIComponent`, `connection` and `adapters` together, over **one database with project-scoped access**. Retire `platform` as a separate app and the script control plane.

### 11.1 The shape today (evidence)

- **Two service worlds.** ~**50 service definitions** across the compose files (29 in `docker-compose.development.yml`, 24 in `docker-compose-infra.development.yml`).
- **A control plane in scripts.** `scripts/`: **~25,400 lines of Python** across ~40 scripts — `aisc.py` alone is **1,906 lines** (it generates `env.runtime`/`env.secrets`/`env.local` and assembles the compose command), plus a dozen `verify-*.sh`, `db_consistency/`, `superset_upgrade_check.py`, `report-grants.sh`, `rotate-infra-password.sh`, …
- **A whole parallel app.** `platform/platform_service`: **12,489 lines**, with **21,569 lines of tests** (~34k total).
- **Many databases and many ways in.** `platform`, `keycloak`, `superset`, `controls`, `qualification`, `control_objectives`, `report_composer`, **plus one database per project**; ~15 role/db SQL files in `init/`. Access is split between platform raw SQL, Django ORM, Prisma (controls/qualification), and script SQL.
- The webapp already carries a `src/platform/` area — the "platform UI" is *already* partly inside the webapp.

### 11.2 The boundary has already dissolved (so this is not a big leap)

- **Two project-DB implementations exist**: `platform/platform_service/projectdb.py` **and** `apps/backend/aisc_backend/projectdb.py`. The backend's is a full Django alias/router/door (`configurator_databases`, `DATABASE_ROUTERS`, `ProjectDoor`).
- `apps/backend/config/settings.py:132-154`: in CONFIGURATOR mode the backend **drops admin/auth/sessions** and swaps DB routing — i.e. the backend **already is** the platform's engine backend.
- The backend already mints the worker's **run ticket** and already handles platform concerns in `aisc_backend/{ledger,platform_helpers,platform_projects,config_secrets,secret_cleanup}.py`.
- The platform reaches into other apps' tables with **raw SQL** (`platform/platform_service/evidence.py:93-196`, `dashboards.py:24-34`).

So we already have two services, two DB routers, two notions of "the project", sharing tables by raw SQL. The separation is not buying independence; it is paying for duplication.

### 11.3 What consolidation buys (benefits)

- **One stack** — ORM, migrations, admin, auth, tests: the backend's Django setup.
- **One home for the domain** — move `connection` and `adapters` into the backend **beside `AIComponent`**; delete the platform's `connection`/`target` tables and `platform_service/adapters.py`. (Connections and adapters as backend models, edited in the webapp.)
- **One test story** — instead of pytest (platform) + Django + Prisma + script suites: far less surface to keep green (11.1: 21.5k lines of platform tests alone).
- **One auth** — no duplicate membership tables (`platform_service/membership.py`) beside Django auth.
- **Fewer services** → smaller compose, faster start, fewer moving parts; the `scripts/` control plane shrinks to a compose file + a short Makefile.

### 11.4 What we must keep (the platform's real jobs, and where they go)

| platform job (today) | where it goes |
|---|---|
| per-project DB provisioning (`projectdb.py`, `project-template/*.sql`) | **already in the backend** (`aisc_backend/projectdb.py`, `migrate_projects`) |
| membership / who-sees-what (`membership.py`, route checks) | Django auth + object permission (RLS or a `project_id` column, §1) |
| encrypted secrets (`secret_box.py`) | backend `config_secrets.py` / `secret_cleanup.py` equivalents |
| connections + adapters | **backend models beside `AIComponent`** |
| run passes / run keys (`run_passes.py`) | **already** the backend's run ticket (`aisc_backend/projectdb.py`) |
| immudb ledger (`ledger/`, inbox/outbox) | backend `aisc_backend/ledger.py` + `deliver_ledger_events` |
| cross-step evidence / dashboards (raw SQL) | backend models/queries |
| the plugin-call facade/door (`routes/facade.py`) | **the eval worker** (§8/§9) |

The last row is the key one: the platform's only *runtime* reason to exist — proxying plugin calls — is already moving to the worker. Once §8/§9 land, the platform has no runtime role left.

### 11.5 The other side will say — and the answer

- **Isolation / security.** A single DB with `project_id` + Postgres Row-Level Security and per-app roles gives the same logical isolation, with one migration target and normal pooling (§1).
- **Independent deployability / submodule boundaries.** The raw-SQL coupling and the two `projectdb.py`s already break independence (§4). **Under discussion (2026-11-11):** the boundaries were meant to let a service be replaced with someone else's implementation — whether to keep them or fold them is open (brief D8). The leading position: a boundary is justified by an **architectural axis** (a layer — `backend`, `webapp`, `eval`, `results-dashboard`) or a **published ABI** (`shared/*`), not by a **business domain** (`qualification`, `controls`, `control-objectives`).
- **Tamper-evidence (immudb).** Keyed to the ledger identity/signing key, not to the platform process; the backend already delivers ledger events.
- **Risk of a big-bang migration.** Slice it (§11.6); keep the platform serving until parity, then delete.

### 11.6 Sliced migration (aligns with §10)

1. **Adapters + connections → backend models** and webapp UI, beside `AIComponent`. The platform keeps serving behind the same API until parity.
2. **Move run-pass issuing + the facade to the worker** (§8/§9); the platform stops proxying.
3. **Move membership / secrets / ledger uses** to the backend.
4. **Collapse the databases** (`project_id` + RLS, §1); replace `scripts/aisc.py`'s env-generation + compose assembly with a committed compose file + Makefile.
5. **Delete the `platform` service and its tests**; fold the useful ones into the backend suite.

### 11.7 Decision to force

**Scrap the `platform` app (and the `scripts/` control plane) in favour of backend + webapp — or keep it and justify its runtime role now that the facade and run-pass leave it.** If kept, name the one thing it does that the backend cannot.

---

## §12. Configuration: feature flags, not a deployment mode (2026-11-11)

**My position.** The binary `AISC_DEPLOYMENT` mode (`standalone` | `configurator`) is the wrong shape. It bundles several *independent* features into one all-or-nothing switch, and it forks the app's structure at import time. Consolidating into one app means **one app with feature flags** — each feature enabled or disabled on its own — not two modes of the same app.

### 12.1 What the mode does today (evidence)

One variable, read once, then branched on everywhere (`apps/backend/aisc_backend/deployment.py:3`, `apps/eval/aisc_eval/deployment.py:3`). In CONFIGURATOR it:

- **rewrites the app graph** (`apps/backend/config/settings.py:132-154`): drops `django.contrib.{admin,auth,sessions,messages}` and `allauth`/`ninja_jwt` from `INSTALLED_APPS`; strips their middleware and template context processors; **inserts** `aisc_backend.project_door.ProjectDoor`; and swaps `DATABASES`/`DATABASE_ROUTERS` for per-project routing (`configurator_databases`).
- **changes the URLconf** (`apps/backend/config/urls.py:56`), app-ready behaviour (`aisc_backend/apps.py:33`), and request handling (`routers/project.py:130`, `target_input.py:72`).
- **changes the schema**: migration `0019` drops the login tables **only in configurator**, migration `0021` writes an `engine_deployment` marker, and `assert_database_mode()` refuses to run a database made by the other mode (`deployment.py:95-101`).
- **is re-implemented in the worker**: `apps/eval/aisc_eval/deployment.py` is the worker's own copy of the same contract, read by `service/api_client.py:29` and `celery_service.py:78`.
- **has mode-specific validation** (`check_environment`): Postgres required, `RUN_TICKET_KEY` required and distinct from `DJANGO_SECRET_KEY`, `AUTH_ENABLED` required true.

### 12.2 Why a single binary switch is a smell

- **Two shapes of one app.** The mode changes installed apps, middleware, URLconf, DB routing *and* migrations. Every `is_configurator()` is a hidden fork: a code path is either untested in one mode or dead in the other.
- **The mode is not one feature.** "Per-project DBs", "the ProjectDoor", "membership from the platform", and "no local login" are separable concerns; a binary switch forces all-or-nothing.
- **Migrations encode the fork.** A conditional migration (0019) and a schema marker (0021) exist *because* a runtime flag changes the schema — the database is stamped with the mode it was made in and can't move between them.
- **It duplicates itself.** A second `deployment.py` in the worker repeats the contract.
- **It hides the real knob.** The thing anyone actually wants to change is one feature (e.g. "authenticate locally") — not the whole deployment identity.

### 12.3 The proposal: one app, a registry of flags

Replace the mode with explicit, independent, env-backed flags read through **one small registry**:

| flag | what it turns on | replaces |
|---|---|---|
| `LOCAL_AUTH` | Django auth + admin + allauth + sessions + ninja_jwt | the mode's app/middleware removal |
| `PROJECT_DB_PER_PROJECT` | per-project DB routing + `ProjectDoor` | `PROJECT_DATABASES` + `configurator_databases` |
| `PLATFORM_MEMBERSHIP_SOURCE` | membership resolved from the platform vs locally | the door's membership branch |
| `RUN_TICKET_KEY` (presence) | worker-ticket minting/verification | the mode's key checks |
| `PER_PROJECT_DBS` (default off) | the whole per-project schema path | §1 — expected to go away |

**Principles.**

- **One code path.** Flags select *behaviour at one seam* (a provider/service), not a different app graph. `INSTALLED_APPS`/`MIDDLEWARE`/URLconf are the same in every configuration; the seam is where the feature is consumed.
- **Composable.** Any combination works — e.g. local auth **and** one DB; or platform membership **and** per-project DBs during the migration.
- **Neutral default.** A fresh install runs with no flags set (the standalone-equivalent behaviour); flags opt in.
- **Registered & validated.** One registry lists every flag, its default and its allowed values; startup rejects unknown or incoherent combinations (replacing `check_environment`'s mode-specific checks).
- **Testable.** A **flag matrix test** instead of a mode matrix: each flag exercised on and off in CI, without a combinatorial explosion.

**Risks, and the guard.**

- *Flag sprawl.* Guard with the registry and a rule: a flag must map to a real, independent feature; remove it when the feature is always on.
- *Test explosion.* Test flags at their **seams** and pairwise, not all 2ⁿ combinations.
- *Stale forks.* When a feature is always on (e.g. per-project DBs, if §1 lands), delete the flag with it.

### 12.4 Migration from the mode

1. Replace each `AISC_DEPLOYMENT`/`is_configurator()` call site with **the specific flag it is really about** (~10 call sites; each maps to exactly one feature).
2. Stop rewriting `INSTALLED_APPS`/`MIDDLEWARE`/URLconf in `settings.py`; move each toggle to where the feature is consumed.
3. Retire migration `0019`/`0021`'s conditional schema and the `engine_deployment` marker once per-project DBs go (§1).
4. Delete `apps/eval/aisc_eval/deployment.py`; the worker reads the flags it needs.

### 12.5 Decision to force

**Adopt feature flags (one app, composable) in place of the binary `AISC_DEPLOYMENT` mode** — and agree the v1 flag set (`LOCAL_AUTH`, `PROJECT_DB_PER_PROJECT`, `PLATFORM_MEMBERSHIP_SOURCE`).

---

*Itemised as smells — see [`03-code-smells.md`](03-code-smells.md) #2 and #6. Agenda items are in
[`08-meeting-agenda.md`](08-meeting-agenda.md).*
