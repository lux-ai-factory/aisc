# Backend Django app split — plan

**Status:** phases 1–3 executed. Branch `integration/int-01-frozen-unified-app`.
**Scope:** `apps/backend` only. No repo, service or container changes (I9/I11).
**Decision source:** `docs/unified-modules-and-pilot-brief.md` D11 and `docs/refactor-plan.md` §2.3.

This is integration scaffolding, not a binding invariant. Fold anything that survives into
`ARCHITECTURE.md`/the nearest README and delete this file before the branch merges (HANDOVER §5.1).

---

## 1. Why split, and what "split" means here

The backend is still one Django app, `aisc_backend`, holding 45 registered models and one migration
history (`0001…0042`). D11 asks for **table-owning Django apps** inside the one backend repo:

- A Django app is the **table-owning unit** (I5): it owns ORM models and a `migrations/` directory.
- A noun that owns no tables (audit writer, auth adapter, request scoping, report renderer) stays a
  **module inside a core app**, not its own app.
- An app is a **packaging unit**, not a repo or service (I9). One repo, many apps.
- **Never branch `INSTALLED_APPS`** (I4). Every app stays installed; behaviour is gated by flags.
- **Core never depends on optional domains** (I10). Optional apps depend on core; never the reverse.

The split is therefore about **ownership and dependency direction**, not about deployables.

---

## 2. Current facts (measured on this branch)

- `aisc_backend` is the only app. `INSTALLED_APPS` in `config/settings.py` lists it once.
- 45 models are registered by `aisc_backend.models`; `Artifact` is concrete but **not imported** by
  `models/__init__.py`, so it is registered only when `schemas.artifact`/`repositories` import it.
  That is a latent ordering bug worth fixing in the split.
- Migration history:
  - `0001…0014` = **mainline** (0001 initial through the AI-system/project-config squash).
  - `0015…0042` = **unshipped** integration/unified-app work (0015 collapses the frozen 0015–0032
    compliance chain; 0033–0042 are the integration additions).
- `0015` creates both **core** rows (`ProjectMember`, `System`, `SystemVersion`) and all the
  **optional** domain rows. `0033–0042` interleave optional and core changes.
- No core model has a forward FK into an optional model. The apparent edges (`Project.report_settings`,
  `SystemVersion.evidence_review`) are **reverse** relations on optional models, so the dependency
  direction is already clean.
- Mainline tables/IDs/migration history must be preserved. Unshipped 0015–0042 may be rewritten;
  integration-only databases need no importer and can be reset.

---

## 3. Target app set

Keep the app label **`aisc_backend`** as the core app for mainline continuity. Renaming the app label
would mean rewriting mainline migration history and content types; the label is historical, not a
domain boundary. Its `verbose_name` can become "AISC Core".

| app | kind | models | migration source |
|---|---|---|---|
| `aisc_backend` | core | `Project`, `ProjectMember`, `ProjectConfig`, `AISystem`, `AIComponent`, `Connection`, `AllowedHost`, `Helper`, `RunBinding`, `System`, `SystemVersion`, plus the abstract common/storage models | 0001–0014; core parts of 0015/0034/0040 |
| `aisc_evaluation` | core | `Evaluation`, `EvaluationInput`, `EvaluationPlugin`, `Observation`, `Measurement`, `Metric`, `MetricCategory`, `Direct`, `Derived`, `Artifact` | 0001–0014 (phase 2) |
| `aisc_plugins` | core | `Plugin`, `PluginConfig`, `PluginConfigProjectConfig` | 0001–0014 (phase 2) |
| `aisc_qualification` | optional | `Questionnaire`, `QuestionnaireVersion`, `Qualification`, `CardComponentLink` | 0015/0039/0041 |
| `aisc_control_objectives` | optional | `ControlObjective`, `Risk`, `RiskVersion`, `RiskObjectiveMapping`, `ObjectiveProfile`, `ObjectiveSet`, `ObjectiveSetVersion`, `EvidenceLink`, `EvidenceReview` | 0015/0033/0036/0037/0038 |
| `aisc_controls` | optional | `ControlSource`, `ControlTemplate`, `ControlQuestion`, `ProjectChecklist`, `Submission`, `SubmissionAnswer` | 0015 |
| `aisc_report` | optional | `ReportLayout`, `Report`, `ProjectReportSettings` | 0015/0035/0042 |

Notes:

- `System`/`SystemVersion` are the shared AI-card version mechanism; D11 puts "shared version/publish"
  in core. They live in `qualification.py` today and should move to a core module (e.g.
  `aisc_backend/models/system.py`).
- `ProjectMember` is core membership but is created in `0015`; keep it in `aisc_backend`'s 0015.
- `EvaluationInput`/`EvaluationPlugin` are evaluation; `Plugin`/`PluginConfig` are plugins. They are
  all mainline and split in phase 2.

### Dependency direction

```
core (aisc_backend, aisc_evaluation, aisc_plugins)
  ↑
optional (aisc_qualification, aisc_control_objectives, aisc_controls, aisc_report)
```

- Optional apps may import core models and expose FKs to core tables.
- Core must not import optional models or expose FKs to optional tables.
- Optional-to-optional FKs are allowed only inside one app (or a documented acyclic edge).
- The existing reverse relations are fine; only forward FKs matter for the dependency rule.

---

## 4. Migration strategy

### 4.1 Mainline vs disposable

- **Freeze `0001…0014`.** Do not rewrite, squash or renumber them. They build the mainline tables,
  content types and permissions.
- **Rewrite `0015…0042`.** They were never deployed on mainline. Split their operations into the
  destination apps' initial migrations. Because the data is disposable, collapse each optional app's
  final schema into one `0001_initial` rather than preserving the intermediate history.
- Integration-only databases can be dropped and recreated; no data importer is needed.

### 4.2 Phase 1 — split the optional domains (recommended first)

This is the low-risk, high-value slice: it proves the app split without touching mainline tables or
content types. It also makes I10 enforceable, because core stops importing optional models.

1. **Create the four apps** under `apps/backend/`:
   - `aisc_qualification/`, `aisc_control_objectives/`, `aisc_controls/`, `aisc_report/`
   - each with `__init__.py`, `apps.py` (`AppConfig`, `default_auto_field`), `models.py` (or a
     `models/` package), `migrations/__init__.py`, and an `admin.py` for its registrations.
2. **Move the model classes** out of `aisc_backend/models/{qualification,control,control_objective,
   evidence,report}.py` into the owning app. Keep `System`/`SystemVersion` in a new core module
   `aisc_backend/models/system.py`. Set `Meta.app_label` to the new app label (or remove the explicit
   `app_label` and let the app config supply it).
3. **Trim `aisc_backend`'s unshipped migrations** to core only:
   - `0015_unified_app_compliance.py` → keep `ProjectMember`, `System`, `SystemVersion`; remove the
     optional `CreateModel`s and the objective seed. Move the seed to
     `aisc_control_objectives/migrations/0001_initial.py`.
   - `0034_connections_helpers_bindings_and_allowed_hosts.py` → keep as a core migration; change its
     dependency from `0033` to `0015`.
   - `0040_system_aisystem.py` → keep as a core migration; change its dependency from `0039` to
     `0034`.
   - Delete `0033`, `0035`, `0036`, `0037`, `0038`, `0039`, `0041`, `0042` from `aisc_backend`; their
     operations move into the destination apps' initial migrations. Optionally renumber the remaining
     core migrations to `0015/0016/0017` for a gap-free chain (safe because they are unshipped).
4. **Create each optional app's `0001_initial`** from the final state of its moved models, preserving
   create order and constraints. Dependencies:
   - all four depend on `aisc_backend` `0015` (for `Project`, `SystemVersion`, `AIComponent`);
   - `aisc_control_objectives` also needs the seed data migration;
   - no cross-optional dependencies are needed.
5. **Move admin registrations** from `aisc_backend/admin.py` to each app's `admin.py`.
6. **Update imports** across `routers/`, `services/`, `schemas/`, `repositories/`, `report_renderer/`
   and `tests/` from `aisc_backend.models.<optional>` to the owning app. Do not add optional
   re-exports to `aisc_backend/models/__init__.py` — that would reintroduce the core→optional edge.
7. **Add the four apps to `INSTALLED_APPS`** (statically; no mode branching).
8. **Fix the `Artifact` registration** while in `models/__init__.py`: import it explicitly so it is
   registered deterministically (it belongs to `aisc_evaluation` in phase 2, but for now keep it in
   `aisc_backend` and import it).

### 4.3 Phase 2 — split evaluation and plugins (follow-up)

These models are mainline, so the tables and content types already exist. Move model **state**, not
data.

1. Create `aisc_evaluation` and `aisc_plugins` as above.
2. Move the model classes. Set `Meta.db_table` to the existing `aisc_backend_<model>` table name so
   the split does not rename tables. Set the new `app_label`.
3. In `aisc_backend`, add a migration after the last core migration that removes the moved models
   from state without touching the database:
   ```python
   migrations.SeparateDatabaseAndState(
       state_operations=[migrations.DeleteModel(name="..."), ...],
       database_operations=[],
   )
   ```
4. In each new app, add an initial migration that adds the moved models to state without creating
   tables:
   ```python
   migrations.SeparateDatabaseAndState(
       state_operations=[migrations.CreateModel(...), ...],
       database_operations=[],
   )
   ```
   Depend on the `aisc_backend` state-delete migration. The `CreateModel` state must match the final
   model state exactly (fields, options, `db_table`, constraints).
5. **Rename content types on upgrade.** Add a `RunPython` in the new app's initial migration that
   updates the existing `django_content_type` row's `app_label` from `aisc_backend` to the new app
   label for each moved model. On a fresh install the old row does not exist, so the migration is a
   no-op and `post_migrate` creates the new row. On a mainline upgrade the old row exists and is
   renamed, so permissions (which FK to the content type) survive. Handle a pre-existing new-label
   row defensively (merge/skip) to avoid a unique-constraint failure.
6. Move admin registrations and update imports as in phase 1.
7. Grep for `ContentType`/`app_label` filters and update any that assume `aisc_backend`.

> Phase 2 is the risky part. Do it as its own change after phase 1 is green, with a real PostgreSQL
> upgrade from a mainline `0014` database as the gate.

### 4.4 Phase 3 — feature code follows its tables

The table split is not the end of the split. A table-owning app should also own the layer code that
serves its tables. Leaving all routers, services, schemas, repositories and tests in `aisc_backend`
makes the core app look like the whole system and hides the real optional-domain boundaries.

This is **code organisation**, not a new moving part:

- no new app, repo, service or container;
- no new URLconf, middleware or `INSTALLED_APPS` branch;
- no model or migration changes;
- one composition root (`config/urls.py`) still registers every router;
- feature flags still gate behaviour at the point of use.

**Rule:** layer code lives with the app that owns its tables. The unit is still the table-owning app;
we are not minting an app per noun or per layer. A `routers/`, `services/`, `schemas/` or
`repositories/` package inside an app is a layer module, not a new boundary.

**Target ownership.**

| App | Layer code |
|---|---|
| `aisc_backend` (core) | common/storage, project, membership, `AISystem`/`AIComponent`, `ProjectConfig`, connections/helpers, auth, audit, allowed hosts, stats, file storage, adapters, shared helpers |
| `aisc_evaluation` | evaluation/results/internal/task routers, evaluation/measurement repositories, results dashboard/bridge services, evaluation schemas, evaluation tests |
| `aisc_plugins` | plugin router, plugin repository, plugin schema, plugin tests |
| `aisc_qualification` | qualification/questionnaire routers, prefill package, qualification/card/publication services, qualification schemas, qualification tests |
| `aisc_control_objectives` | control-objectives/evidence/assessment routers, objectives/evidence/coverage/risk services, objective/evidence schemas, tests |
| `aisc_controls` | control/catalogue routers, controls catalogue/scoring services, control schemas, tests |
| `aisc_report` | report router, report renderer engine, report snapshot/blocks/render services, report schemas, tests |

**Dependency direction stays coreward.** The core set is `aisc_backend`, `aisc_evaluation` and
`aisc_plugins`; the optional set is `aisc_qualification`, `aisc_control_objectives`, `aisc_controls`
and `aisc_report`. Optional apps may import core. Core must not import optional. Optional-to-optional
edges are allowed only as a documented DAG. The current DAG is `aisc_control_objectives → aisc_controls,
aisc_qualification` and `aisc_report → aisc_controls, aisc_control_objectives, aisc_qualification`;
`aisc_controls` and `aisc_qualification` depend only on core.

**Shared exceptions.** Core cannot import an optional service just to register its exception. Define
the base exception in core and have optional services subclass it; the core exception handler
registers the base class.

**Execution order.** Move the optional-domain layer code first, because that removes the current
core→optional violations. Then move the core-set evaluation and plugin layer code to balance the
core app. Move tests with their features and keep only cross-cutting tests in `aisc_backend`.

---

## 5. Verification gates

Run these after each phase:

1. `python manage.py makemigrations --check --dry-run` — no pending model changes.
2. Fresh install: `migrate` on an empty SQLite DB and on an empty PostgreSQL DB.
3. Mainline upgrade: restore a database at `0014`, run `migrate`, and verify tables, IDs, content
   types, permissions and admin pages.
4. Full backend suite (`AUTH_ENABLED=false … manage.py test`) and the architecture guards
   (`tests/architecture`).
5. Dependency check: `grep` core for imports of optional models; expect none.
6. Content-type check: count content types and permissions before/after; no duplicates for moved
   models.
7. Optional-off check: core endpoints work with the optional feature flags disabled and optional
   tables empty.

---

## 6. Risks and open questions

- **Content-type duplication** is the main phase-2 risk. The rename data migration must run before
  `post_migrate` and must be idempotent.
- **Import churn** is broad but mechanical. Do it as a separate commit from the model move so a
  failure is easy to isolate.
- **Integration DBs** will not match the rewritten migration graph. Reset them; only mainline data is
  preserved.
- **`Artifact`** is currently registered only by side-effect imports; fix it during phase 1.
- **App label name:** keep `aisc_backend` as the core label. Renaming it to `core` would require
  rewriting mainline migration history and content types; not recommended for this port.
- **Phase 2 timing:** do phase 1 first. Phase 2 can wait until the optional split is proven and the
  mainline upgrade test exists.
