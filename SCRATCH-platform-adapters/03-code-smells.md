# Bad code smells

> New (2026-11-11). This is the evidence behind §11/§12, itemised. Each entry names the smell, where it
> is, why it hurts, and where it goes. Numbers are approximate and labelled. Evidence refs are in
> [`appendix-c-evidence-index.md`](appendix-c-evidence-index.md).
>
> Fairness note: several of these were **pragmatic shortcuts** (e.g. reusing the Django backend to reach
> the engine's tables), not carelessness. The point is not blame — it is that the **costs are now bigger
> than the shortcuts saved**, and consolidation removes them.

## The list at a glance

| # | smell | where | resolves in |
|---|---|---|---|
| 1 | **Two project-DB implementations** | `platform/platform_service/projectdb.py` **and** `apps/backend/aisc_backend/projectdb.py` | §11.6, §1 |
| 2 | **A binary deployment mode forks the app** | `AISC_DEPLOYMENT` rewriting apps/middleware/URLs/DB/migrations; two `deployment.py` | §12 |
| 3 | **Parallel domain models** | platform `connection`/`target` vs backend `AIComponent` | §11.3, §4 |
| 4 | **Raw SQL across app boundaries** | platform `psycopg` reads/writes the Django `engine.*` tables | §11.4 |
| 5 | **A control plane in `scripts/`** | ~25,400 lines; `aisc.py` 1,906; a dozen `verify-*.sh` | §11.6 |
| 6 | **N databases × 5 migration tools** | Django / Prisma / Alembic / platform SQL / project-template SQL | §1 |
| 7 | **Adapter install = copy a folder + `docker restart platform`** | `adapters/README.md:22-27` | §8/§9 |
| 8 | **Duplicated membership** | `platform_service/membership.py` vs backend `auth/membership.py` | §11.3 |
| 9 | **Duplicated secret storage** | `platform_service/secret_box.py` vs backend `config_secrets*.py`/`secret_cleanup.py` | §11.3 |
| 10 | **Version invariants in DB triggers** | `project-template/0006…sql`; `DELETE` hole; migration `0002`→`0003` reversal | §3 |
| 11 | **~50 compose service definitions** | 29 + 24 across dev compose files | §11.3 |
| 12 | **Runtime config generated, not committed** | `aisc.py` writes `env.runtime`/`env.secrets`/`env.local` | §11.6 |
| 13 | **Two notions of "the project"** | platform project vs backend `aisc_backend_project`; `platform_projects.py` bridge | §11 |
| 14 | **E2E suite + published compose dropped on pilot** | `e2e/*`, published `docker-compose*.yml` | §0, agenda |

---

## 1. Two project-DB implementations

Two modules do the same job: "which database does this project's data live in?"

- `platform/platform_service/projectdb.py` — name a DB `project_<pid>`, `CREATE DATABASE`, apply the
  **27-file** `project-template/*.sql`, drop on failure.
- `apps/backend/aisc_backend/projectdb.py` — a full Django **alias + router + `ProjectDoor`** that opens
  and admits a project DB per request, and mints the worker's run ticket.

The backend's is the more complete one (Django-native, testable, connection lifecycle handled). Two
implementations means two places to fix a bug, two schemas to keep in step, and two answers to "what is
a project?".

**Where it goes:** the backend's is the survivor (§11.4 row 1); the platform's `provision()` is a
one-time migration. Ultimately per-project DBs collapse to one DB + RLS (§1).

## 2. A binary deployment mode forks the app

`AISC_DEPLOYMENT` (`standalone` | `configurator`) is read once and then branched on: it **removes apps
and middleware** (`settings.py:132-154`), **swaps the URLconf** (`config/urls.py:56`), **swaps the DB
routing**, and **changes the schema** (migration `0019` drops the login tables only in configurator;
`0021` stamps `engine_deployment`). It is re-implemented in the worker
(`apps/eval/aisc_eval/deployment.py`).

The smell: the mode bundles several independent features (local auth, per-project DBs, platform
membership) into one all-or-nothing switch, and forks the app's *structure* — not just a value — at
import time. See §12 for the full case and the flags that replace it.

**Where it goes:** feature flags (§12): one app, same app graph, independent toggles.

## 3. Parallel domain models: `connection`/`target` vs `AIComponent`

The backend/webapp already model `AIComponent` (`AIComponentType`, `AISystem`, `ProjectConfig`).
pilot adds a **platform-level** `connection` (schema `connection`) plus `target`, edited through
`platform/platform_service/routes/connections.py` / `connection_store.py`. `AIComponent` still exists in
the backend. So the same idea — "a system under test and how to reach it" — lives twice, in two vocabularies,
under two UIs.

**Where it goes:** connection models beside `AIComponent` in the backend (§11.3/§4); delete the
platform tables.

## 4. Raw SQL across app boundaries

The platform is a Python service with no ORM; it reaches the engine's data with **`psycopg` and
hand-written SQL against the Django-owned `engine.*` tables**:

- `platform/platform_service/evidence.py` — reads `engine.aisc_backend_evaluationplugin`,
  `…_evaluation`, `…_pluginconfig`, `…_plugin`, and **writes** `evidence.link` / reads `evidence.review`
  (`:582`, `:781`).
- `platform/platform_service/dashboards.py` — the same joins for dashboard tiles.

This couples the platform to the backend's table names, columns and semantics with no model, no
migration, no type check. A backend migration silently breaks the platform; the two apps cannot in fact
deploy independently.

**Where it goes:** backend models/queries (§11.4 row 7) — this is exactly the "no raw SQL" goal of §4.

## 5. A control plane in `scripts/`

`scripts/` is **~25,400 lines of Python across ~40 scripts**. `scripts/aisc.py` alone is **1,906 lines**:
it generates `env.runtime`/`env.secrets`/`env.local` and **assembles the `docker compose` command**. A
dozen `verify-*.sh` + `db_consistency/`, `superset_upgrade_check.py`, `report-grants.sh`,
`rotate-infra-password.sh`, `stackcheck/`, `suites.py` surround it.

A launcher this large is a service in all but name, with no tests that run it as a product and no way to
review a deployment as a diff. It is the most visible "non-cohesive" surface.

**Where it goes:** a committed compose file + a short Makefile (§11.6 step 4); the verifiers become
ordinary CI jobs.

## 6. N databases × 5 migration tools

Databases: `platform`, `keycloak`, `superset`, `controls`, `qualification`, `control_objectives`,
`report_composer`, **plus one per project** (~15 role/db SQL files in `init/`). Migration tools:
**Django** (backend), **Prisma** (controls, qualification), **Alembic** (control-objectives,
report-composer), the platform's own **SQL migrations** (`platform/migrations/`), and the
**per-project template SQL** (27 files). Drift across project DBs is policed by `scripts/db_consistency`.

Five tools, N× per-project copies, and a consistency checker to reconcile them. Every schema change is a
fan-out.

**Where it goes:** one DB + Django migrations (§1), with the other tools' tables folded into models.

## 7. Adapter install = copy a folder + restart

To add a bespoke adapter today: copy a folder into `adapters/`, then **`docker restart platform`**
(`adapters/README.md:22-27`). The platform reads the folder once; a removed adapter leaves its
connections listed but broken until it returns. There is no versioning and no listing outside the
running service.

The smell: packaging and lifecycle are manual, service-coupled, and unversioned — for code the plugin
depends on.

**Where it goes:** adapters as first-class, loaded by the shared plugin manager, listed/selected by the
UI and recorded with the run (§8, §9, Appendix B).

## 8. Duplicated membership

`platform/platform_service/membership.py` and `apps/backend/aisc_backend/auth/membership.py` both answer
"may this caller see this project?". The platform's route checks and the backend's `ProjectDoor` each
enforce it their own way, over the same platform data.

**Where it goes:** one membership service — Django auth + object permission (§11.3/§11.4).

## 9. Duplicated secret storage

Two secret systems, twice the tests:

- `platform/platform_service/secret_box.py` (**196 lines**) — encrypt/decrypt connection secrets.
- `apps/backend/aisc_backend/config_secrets.py` (**296**) + `secret_cleanup.py` (**135**) +
  `config_secret_fields.py` (**228**).

Two encryption paths, two cleanup paths, two sets of tests (`test_secret_box.py`,
`test_encoded_secrets.py`, `test_connection_secret_headers.py` alongside the backend's).

**Where it goes:** one secret store in the backend (§11.4).

## 10. Version invariants in DB triggers

Versioning lives in the database, not the app:

- A version is a row of `project.system`, created only by the platform, `number = max+1` under
  `pg_advisory_xact_lock` (`platform/platform_service/db.py:330-351`).
- Immutability is enforced by **triggers** (`system_only_latest_changes`), and each step **stamps** by
  reading "latest" in a *separate* transaction — so concurrent saves can stamp the wrong number.
- **Nothing blocks `DELETE`** of `project.system`, so deleting the newest rows makes an older
  "immutable" version editable again.
- The history is muddied by a migration (`0002`) that built `core.ai_system`/`ai_system_version`, then
  `0003` that **reversed** it back to numbered `core.system`.

Business invariants implemented as triggers, off the ORM, with a hole in them.

**Where it goes:** versioned ORM models in the backend, app-enforced invariants, one place that cuts a
version (§3).

## 11. ~50 compose service definitions

**29** service definitions in `docker-compose.development.yml` and **24** in
`docker-compose-infra.development.yml` — ~50 services to build, start, health-check and name. Most are
infrastructure (fine); the avoidable ones are the parallel app services.

**Where it goes:** the consolidation removes whole services (§11.3); a committed compose makes the
remainder reviewable.

## 12. Runtime config generated, not committed

`scripts/aisc.py` **generates** `env.runtime`, `env.secrets` and `env.local`, and builds the compose
command at launch. The effective configuration of a deployment is therefore not a file you can review,
diff or roll back — it is an output of a 1,906-line script.

**Where it goes:** committed compose + a small, documented env contract (§11.6); secrets from the
platform's secret store, not a generated file.

## 13. Two notions of "the project"

The platform has projects (its own tables); the backend has `engine.aisc_backend_project` and a
`platform_projects` bridge; the eval worker reaches the backend for project data. "Project" is a
different record in each place, reconciled by adapters (`platform_helpers.py`, `platform_projects.py`).

**Where it goes:** one project model (§11), with backend/worker reading it through one API.

## 14. E2E suite + published compose dropped on `pilot`

`pilot` drops the Playwright `e2e/` suite and the published-image `docker-compose.yml` / `-build` /
`-infra` that master has (§0). Some removals are renames; these two look like **regressions** — the
very tests and packaging a consolidation would want to stand on.

**Where it goes:** decide at the reset (§0, agenda) — restore the e2e suite and a committed published
compose rather than lose them.

---

## Smells, grouped

- **Duplication** — 1 (project DB), 3 (domain model), 8 (membership), 9 (secrets), 13 (the project).
- **Boundary leakage** — 4 (raw SQL), 10 (invariants in triggers), 13 (project bridge).
- **Control plane / config** — 2 (mode), 5 (`scripts/`), 12 (generated env).
- **Schema** — 1, 6 (N DBs × 5 tools), 10 (triggers), 2 (mode-conditional migrations).
- **Packaging / lifecycle** — 7 (adapter restart), 11 (compose), 14 (dropped e2e).

**The pattern:** every smell is a place where a **second implementation** of something the backend +
webapp already own was added — a second project DB, a second domain model, a second membership, a second
secret store, a second control plane. Consolidation is the single move that removes the category.
