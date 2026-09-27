# Stage 3: specs

Inputs: RULES.md, 02-work-plan.md, and the code (read only, plus read-only queries on the live DB).
Rule ids (S<wp>.<n>) are what stage 4 cites from a test. Every `DEFAULT (user to confirm)` from 02 is
carried forward unchanged. Where the code contradicts 02, the code wins; see "Deviations from 02" at
the end. Facts checked on the live DB on 2026-09-23: 1 project, 1 `core.system` row
(`1e722ea2-...`, MCAS, `v1.2.0`), 1 `core.ai_system_version` (same pid, number 1, frozen), 1 card
pointing at it, 0 `engine.ai_component`, 0 `engine.evaluation`, 1 `control_objectives.project` row,
4 `project_*` databases. `core.system` and `core.project` are owned by the superuser
`aisc-postgres-user`, not by `platform_rw`.

## 0. Test environment (all packages)

**Throwaway Postgres.** Same major version as the live stack (`postgres:14-alpine`, from
`docker-compose-infra.development.yml:102`):

```
docker run --rm -d --name aisc-t-$RANDOM_HEX -p 127.0.0.1:$PORT:5432 \
  -e POSTGRES_USER=aisc-postgres-user -e POSTGRES_PASSWORD=$RANDOM_PW -e POSTGRES_DB=platform postgres:14-alpine
psql "postgresql://aisc-postgres-user:$RANDOM_PW@127.0.0.1:$PORT/platform" -v ON_ERROR_STOP=1 -f init/platform-db.sql
psql ... -v ON_ERROR_STOP=1 -f init/project-databases.sql
```

The container is removed (`docker rm -f`) on exit, including on failure (`trap`). Never `docker
compose`. The live DB (`postgres` container, port 5432) is never a target.

| Repo | Command (run from the repo dir) | Env that MUST point at the throwaway DB |
|---|---|---|
| apps/backend | `DB_ENGINE=django.db.backends.sqlite3 DB_NAME=$SCRATCH/t.db .venv/bin/python manage.py test aisc_backend` (unit suite, sqlite, as the README says `manage.py test`) | none for sqlite; for migrate/dump: `DB_ENGINE=django.db.backends.postgresql DB_NAME=platform DB_USER=engine_rw DB_PASSWORD=engine_rw DB_HOST=127.0.0.1 DB_PORT=$PORT DB_SCHEMA=engine .venv/bin/python manage.py migrate` |
| platform | `uv run --extra dev pytest -q` | `PLATFORM_TEST_DATABASE_URL=postgresql://platform_rw:platform_rw@127.0.0.1:$PORT/platform` (conftest falls back to `PLATFORM_DATABASE_URL`, then to 127.0.0.1:5432, which is LIVE: always set it) |
| apps/qualification | `npx vitest run`, `npx tsc --noEmit`, migrations: `DATABASE_URL=postgresql://qualification_rw:qualification_rw@127.0.0.1:$PORT/platform?schema=qualification npx prisma migrate deploy` | `DATABASE_URL` as shown |
| qualification ontology / prefill / agents | `python -m pytest -q` in `services/<name>` inside `python:3.12-slim` with `pip install -r requirements.txt pytest` (as `scripts/verify.sh:59-60`); prefill also `PREFILL_FIELDS_PATH=/w/src/data/prefillFields.json` | none (no DB) |
| apps/control-objectives | `uv run pytest -q` | `CONTROL_OBJECTIVES_TEST_DATABASE_URL=postgresql+psycopg://aisc-postgres-user:$RANDOM_PW@127.0.0.1:$PORT/control_objectives_test` (default points at localhost:5432, LIVE) |
| apps/controls | `npx vitest run` (integration tests skip without the var) | `PROJECT_DATABASE_URL=postgresql://controls_rw:controls_rw@127.0.0.1:$PORT/{database}?schema=controls` |
| apps/webapp | `npx vitest run`, `npx tsc --noEmit` | none |
| apps/catalogue/frontend | `npx vitest run` | none |
| apps/catalogue/backend | `uv run pytest -q -p no:cacheprovider` | none (conftest sets sqlite `DATABASE_URL`) |
| apps/results-dashboard | `PYTHONPATH=. .venv/bin/python -m pytest -q --ignore=tests/test_sso_login.py` | none for unit tests |

`scripts/verify.sh --modules` runs the same table; its `engine backend` line execs into the running
`aisc-backend` container, so stage 4/5 use the local sqlite command above instead.

## Guard spec (G)

Implemented in WP0 as `scripts/guard-frozen.sh` (new, top-level repo), run after every package.

- **G1 Engine schema.** Two throwaway DBs, each prepared with the two init files above.
  - Reference: `git -C apps/backend archive e34fca3 | tar -x -C $SCRATCH/ref`; apply platform
    migration `0001_project_membership.sql` only (as `platform_rw`); run `manage.py migrate` from
    `$SCRATCH/ref` with `apps/backend/.venv/bin/python` and the Postgres env above.
  - Candidate: HEAD of `feat/unified-modules`: platform `0001..0003`, qualification migrations,
    engine `0001..0023`.
  - Dump each with `pg_dump --schema-only --schema=engine` (owners, privileges, constraint, index
    and sequence names included); delete the `-- Dumped from/by` lines; `diff -u`.
  - G1 passes when the diff is empty. The dump includes `engine.evaluation`'s FK into `core.system`,
    so G1 also checks the stamp FK.
- **G2 AIRO tables.** From the same two DBs (reference: qualification migrations as at
  `apps/qualification` `e112001`; candidate: HEAD),
  `pg_dump -s -t qualification.knowledge_graph -t qualification.qualification_risk` diffs empty (no
  new column, index, trigger or FK on either table). In addition, `git diff e112001 --
  prisma/schema.prisma` has no hunk inside `model QualificationRisk` or `model KnowledgeGraph`.
- **G3 Vendored files.** `sha256sum -c` against:
  - `6274d2d8711e046cf38f1b5b2980188094d4aa87b5af79804005a06468fd8469  apps/qualification/services/ontology/airo/airo.ttl`
  - `6b42323726e7a82a5c4782a6d9398fc44db21bd4e0ca9fd4807558190c173605  apps/qualification/services/ontology/airo/vair.ttl`
  - `a41460bdb536f2073b9ce43e499e817a5fe9032001603c23a5f6adbd0e782b59  apps/qualification/src/data/airo_vocab.json`

  `services/ontology/tests/test_vendored.py` stays green.
- **G4 Sean's code.**
  - Backend: `git diff --stat e34fca3 HEAD -- aisc_backend config` lists only
    `migrations/0022_*` (kept), `migrations/0023_*` (new),
    `repositories/system_version_repository.py` (new) and `routers/evaluation.py`. The last one
    differs from e34fca3 by exactly one import line and line 103 (S9.1).
  - `Dockerfile` differs by dfe4120 only.
  - Webapp: `git diff 429f62c HEAD --` over Sean's files of 2026-09-23 (`src/api/api.tsx`,
    `src/components/AISystemSettings.tsx`, `src/components/plugin/PluginConfigForm.tsx`,
    `PluginEvaluationForm.tsx` + test, `src/models/models.tsx`, `src/pages/PluginsConfig.tsx`,
    `PluginStartEvaluation.tsx` + test, `src/pages/Settings.tsx`) is empty.
  - `apps/eval` and `shared/plugin-interface`: no commits after `e5b1b0a` / `97eddea`.
  - `shared/plugin-manager`: `git status` clean.
- **G5 Models.** `git diff e34fca3 HEAD -- aisc_backend/models` is empty, and
  `manage.py makemigrations --check --dry-run` reports no changes.

## WP0 (R) Test bed and reference schema

- **Data**: none in any repo. Output files go to `$SCRATCH` only (the reference dump, baseline counts).
- **Interfaces**: `scripts/guard-frozen.sh [--reference-only]` prints the dump path, G1-G5 results
  and exits non-zero on any failure. `scripts/baseline.sh` runs the section 0 table and prints
  `<suite> <passed> <failed> <skipped>`.
- **Rules**
  - S0.1 When the script exits (success, failure or signal), then no `aisc-t-*` container remains.
  - S0.2 When run twice on an unchanged tree, then the two reference dumps are byte-identical.
  - S0.3 The script never connects to port 5432 of the host; its DSNs contain only `$PORT`.
- **Out of scope**: fixing failing baselines; any compose change.

## WP1 (R) Engine undo (apps/backend)

- **Data**: new migration `aisc_backend/migrations/0023_one_system_per_project_again.py`,
  depending on `0022_parts_belong_to_a_version_of_the_one_system`. The 0022 file stays. End state
  equals e34fca3 exactly:
  - `engine.ai_system`: `id bigint identity PK`, `pid uuid NOT NULL`, `name varchar(255) NOT NULL`,
    `description varchar(255) NOT NULL`, `created_at timestamptz NOT NULL`,
    `project_id bigint NOT NULL UNIQUE REFERENCES engine.project(id)`, deferrable initially deferred.
  - `engine.ai_component`: `system_id bigint NOT NULL` FK to `ai_system(id)`, with its index. No
    `project_id`, `system_version_id` or `lineage` column.
  - No `engine.system_version_parts`.
  - `engine.evaluation.system_id` FK named `aisc_backend_evaluation_system_id_fkey` to
    `core.system(pid) ON DELETE SET NULL`.
- **Names.** The reference was created under `aisc_backend_*` names (0020) and then renamed (0021).
  Postgres keeps constraint, index and sequence names across a table rename, so plain Django ops in
  0023 would produce different names. On Postgres only, 0023 renames what it creates to the names
  in the WP0 dump. Computed with Django 6.0.6's `_create_index_name`, they are expected to be:
  - `aisc_backend_aisystem_pkey`, `aisc_backend_aisystem_project_id_key`,
    `aisc_backend_aisystem_project_id_381e09a9_fk_project_id`;
  - sequence `aisc_backend_aisystem_id_seq`;
  - `aisc_backend_aicomponent_system_id_0909bda5`,
    `aisc_backend_aicompo_system_id_0909bda5_fk_aisc_back`.

  The dump is authoritative when it disagrees.
- **Operations, in order**:
  1. Drop the constraints `ai_component_system_version_id_fkey` and
     `evaluation_system_version_id_fkey`, each with IF EXISTS.
  2. CreateModel `AISystem` (`db_table="ai_system"`), fields as at e34fca3.
  3. AddField `AIComponent.system`, nullable.
  4. RunPython: for each engine `Project`, create one `AISystem`
     (`name=f"{project.name} system"`, `description=""`, as `get_or_create_aisystem` does), and
     set `component.system` from `component.project`.
  5. AlterField `system` to NOT NULL.
  6. RemoveField `project`, `system_version_id` and `lineage`; DeleteModel `SystemVersionParts`.
  7. The Postgres-only RunSQL renames.
  8. RunSQL: when `to_regclass('core.system')` is not null:
     - set `evaluation.system_id = NULL` where it is not in `core.system`;
     - add `aisc_backend_evaluation_system_id_fkey` unless it already exists.
- **Code**: revert e144bc9 and a38dbb4, except the 0022 file. This covers `models/ai_system.py`,
  `models/evaluation.py`, `models/project.py`, `admin.py`, `auth/membership.py`,
  `repositories/project_repository.py`, `repositories/stats_repository.py`, `routers/component.py`,
  `routers/evaluation.py`, `routers/internal.py`, `routers/project.py`, `schemas/ai_system.py`,
  and the three touched tests. It deletes `services/platform_client.py`,
  `services/platform_versions.py`, `services/system_versions.py`,
  `tests/routers/test_ai_system_versions.py` and `tests/test_system_versions.py`. dfe4120 stays.
- **Interfaces**: the engine API equals e34fca3. `GET /api/v1/projects/{pid}/aisystem` returns
  `{pid, name, description, components[]}`, and each component is
  `{pid, name, description, component_type, data, file_size, json_value, source_dataset_pid}`.
  - `POST /api/v1/evaluations/task` no longer returns 503 when the platform is down.
  - It no longer rejects inputs "outside the version".
- **Rules**
  - S1.1 When migrations `0001..0023` run on a DB prepared as in section 0, then G1 passes, both
    when platform `0003` ran before and when it ran after.
  - S1.2 When 0023 runs on a DB where 0022 had put components on a project, then every component
    keeps its `pid`, and has `system_id` set to the one `ai_system` of that project.
  - S1.3 When 0023 runs on sqlite, then it succeeds and skips every core-related SQL statement.
  - S1.4 After WP1, G4 (backend part, without the WP9 lines) and G5 pass.
  - S1.5 After WP1, the full backend suite passes, including Sean's tests
    (`test_evaluation_inputs_template`, `test_project_config_router`,
    `test_project_evaluations_serialization`).
  - S1.6 An engine project still has at most one `ai_system` (UNIQUE `project_id`).
- **Out of scope**: any other engine table or column; deleting the 0022 file; the stamp (WP9).

## WP2 (R) Platform core: card versions in `core.system`

- **Data**
  - Superuser prerequisite, appended to `init/project-databases.sql` (idempotent; it runs at
    initdb step 06 and on every start through `postgres-setup`, which `platform` waits on):
    `ALTER TABLE core.system OWNER TO platform_rw;`. See D1.
  - New `platform/migrations/0003_card_versions_in_core_system.sql`, applied by
    `platform_service.migrate` as `platform_rw`:
    1. Guard: `RAISE EXCEPTION` with the text "core.system must be owned by platform_rw: run
       init/project-databases.sql as the superuser" unless
       `pg_get_userbyid(relowner) = current_user`. The transaction rolls back, and the platform
       retries at the next `pool()`.
    2. If `core.ai_system_version` exists, insert its rows whose pid is not in `core.system` into
       `core.system (pid, project_id, name, version, provider, description, created_at)`, taking
       `project_id` from `core.ai_system` and `version` from `release`.
    3. `ALTER TABLE core.system ADD COLUMN IF NOT EXISTS number integer`, then
       `ADD COLUMN IF NOT EXISTS created_by text`.
    4. Fill `number` with `row_number() OVER (PARTITION BY project_id ORDER BY created_at, pid)`
       where it is NULL; then `SET NOT NULL`; add `CHECK (number > 0)`.
    5. `DROP INDEX IF EXISTS core.system_identity_idx`; drop the `UNIQUE (project_id, name,
       version)` constraint (`system_project_id_name_version_key`) IF EXISTS; add
       `system_project_number_key UNIQUE (project_id, number)`. `system_project_idx` stays.
    6. `DROP TABLE IF EXISTS core.ai_system_version CASCADE`, then
       `DROP TABLE IF EXISTS core.ai_system CASCADE`, then
       `DROP FUNCTION IF EXISTS core.ai_system_version_is_frozen()`.
    7. Function `core.system_only_latest_changes()` and trigger `system_only_latest_changes`
       `BEFORE UPDATE ON core.system FOR EACH ROW`. It raises
       `'system version % of project % is not the latest and cannot change'` when
       `OLD.number < (SELECT max(number) FROM core.system WHERE project_id = OLD.project_id)`, or
       when `NEW.number <> OLD.number` or `NEW.project_id <> OLD.project_id`.
    8. `COMMENT ON TABLE core.system` is set to "One saved AI card version of the project's one AI
       system; number 1, 2, ... per project."
  - Existing grants on `core.system` (SELECT to the module roles and dashboard_ro, REFERENCES to
    the module roles) are kept.
- **Code**: revert b723c73, e126a3f and 72edfbf (`platform_service/ai_system.py`, the
  AI-system parts of `app.py` and `db.py`, `tests/test_ai_system.py`,
  `tests/test_api_ai_system.py`). The 0002 file stays. Remove `PLATFORM_URL: http://platform:8000`
  from `aisc-backend` in `docker-compose.development.yml` (line 67, from c0f460e), staged with
  `git add -p`.
- **Interfaces** (`{project}` is a slug or a pid, resolved by `db.get_project`; authz through
  `role_or_404`):
  - `POST /projects/{project}/system-versions`. Body `{name: str, version?: str, provider?: str,
    description?: str}`. `201` with `{pid, project_id, number, name, version, provider,
    description, created_at, created_by}`.
    - `number` is the project's `max(number)+1`, or 1. `created_by` is `caller.subject`.
    - The insert runs in one transaction under `pg_advisory_xact_lock(hashtext(project_id))`.
    - Errors: 404 for a stranger or an unknown project, 403 for a viewer, 422 for an empty name
      (`systems.system_key`).
  - `GET /projects/{project}/system-versions` (viewer): the list, highest `number` first.
  - `GET /projects/{project}/system-versions/latest` (viewer): the highest-numbered row, or `200
    null` when there is none.
  - `GET /systems/{pid}` (viewer of its project) is kept, with `number` and `created_by` added.
  - Removed: `POST /projects/{slug}/systems`, `GET /projects/{slug}/systems`,
    `GET|PATCH /projects/{slug}/ai-system`, `POST /projects/{slug}/ai-system/draft`,
    `GET /ai-system-versions/{pid}`, `POST /ai-system-versions/{pid}/freeze`.
  - `POST /projects` creates no system row.
- **Rules**
  - S2.1 When an editor POSTs twice, then the rows have numbers 1 and 2, the same `project_id`, and
    they may carry identical `name` and `version`.
  - S2.2 When a viewer POSTs, then 403 and no row. When a non-member POSTs or GETs, then 404.
  - S2.3 When two POSTs for one project run concurrently, then the numbers are 1 and 2 (no
    duplicate, no gap).
  - S2.4 When anyone UPDATEs the row with number 1 while number 2 exists, then the DB raises. An
    UPDATE of number 2 (for example `description`) succeeds.
  - S2.5 When the project is deleted (`DELETE /projects/{slug}`), then its `core.system` rows are
    gone (cascade), and so are the rows that cascade from them.
  - S2.6 When 0003 runs on a fresh DB (after 0001, 0002), then it succeeds and `core.system` is
    empty.
  - S2.7 When 0003 runs on a DB holding 0002's rows (the live shape), then every existing pid is
    kept, MCAS's row has `number = 1`, and `core.ai_system*` are gone.
  - S2.8 When `core.system` is not owned by `platform_rw`, then 0003 fails with the guard message
    and `core.schema_migration` does not record it.
  - S2.9 `GET .../latest` returns the same pid as `SELECT pid FROM core.system WHERE project_id=$1
    ORDER BY number DESC LIMIT 1`.
- **Out of scope**: `core.project` ownership; any UPDATE route; deleting a version.

## WP3 (R) Qualification undo, and "save = next version"

- **Data**: new Prisma migration
  `prisma/migrations/20260923210000_card_versions_point_at_core_system/migration.sql`. The bcc7093
  migration file stays.
  1. `RAISE EXCEPTION` with the text "cards point at system versions missing from core.system:
     <ids>" if any `qualification.system_id` is not in `core.system`. Cards are never deleted.
  2. `DROP CONSTRAINT IF EXISTS qualification_system_id_fkey`, then
     `DROP CONSTRAINT IF EXISTS "Qualification_system_id_fkey"`. Add
     `qualification_system_id_fkey FOREIGN KEY (system_id) REFERENCES core.system(pid) ON DELETE
     CASCADE`. The unique index `qualification_system_id_key` stays.
  3. Function `qualification.card_is_latest(system uuid) returns boolean`: true when `system` is
     the highest-numbered `core.system` row of its project.
  4. Trigger `qualification_only_latest_changes` `BEFORE UPDATE ON qualification.qualification`
     raises unless `card_is_latest(OLD.system_id)`.
  5. Trigger `qualification_answer_only_latest_changes` `BEFORE INSERT OR UPDATE ON
     qualification.qualification_answer` raises unless the parent card is latest. There is no
     DELETE trigger, so the project-delete cascade is never blocked.
  6. `CREATE TABLE qualification.card_component` (WP6 fills it; created here to keep one
     migration per package boundary):
     - `id text PK`, `qualification_id text NOT NULL REFERENCES qualification(id) ON DELETE
       CASCADE`, `component_pid uuid NOT NULL`;
     - `airo_property text NOT NULL CHECK (airo_property IN ('hasModel','hasTrainingData',
       'hasTestingData','hasValidationData','hasComponent'))`;
     - `name text NOT NULL`, `component_type text NOT NULL`, `object_name text NOT NULL DEFAULT ''`,
       `linked_at timestamptz(3) NOT NULL DEFAULT CURRENT_TIMESTAMP`;
     - `UNIQUE (qualification_id, component_pid)`, `INDEX (component_pid)`;
     - trigger `card_component_only_latest_changes` `BEFORE INSERT OR UPDATE` with the same test as
       step 5.

  `schema.prisma` gains `model CardComponent @@map("card_component")` and
  `Qualification.components CardComponent[]`. The comment on `systemId` names `core.system`.
  `QualificationRisk` and `KnowledgeGraph` are unchanged (G2).
- **Code**:
  - `PlatformClient` becomes `latestVersion(project)`, `listVersions(project)` and
    `createVersion(project, identity)`, over the WP2 routes. The `aiSystem`, `versionForNewCard`
    and `freeze` methods go.
  - `domain/cardVersions.ts` keeps `cardAsFormStart`. `nextCard` and `cardStanding` take
    `{pid, number}` rows (no `frozen_at`).
  - `QualificationService.createFromForm(project, formData)`:
    1. parse the form;
    2. `createVersion(project, {name: systemName, version: systemVersion, provider: company,
       description})`;
    3. `repo.create({...parsed, projectId: version.project_id, systemId: version.pid})`.

    `CardExistsError` goes.
  - If step 3 fails, the new version exists without a card. The UI then shows "vN has no card yet"
    and the next save makes vN+1 (versions are never deleted).
- **UI** (705a288's screens kept):
  - `/p/{project}/system` shows the latest card. When there is none: "No AI card yet" and "Edit the
    AI system".
  - `/p/{project}/system/edit` is the form, prefilled from the latest card via `cardAsFormStart`.
    "Save" makes the next version and redirects to `/p/{project}/qualify/{id}`.
  - `/p/{project}/qualifications` ("Versions") lists `vN`, `created_by` and `created_at`, highest
    first.
  - `/p/{project}/qualify/{id}` for a non-latest card shows "vN, kept as it was" with a link to the
    latest. It has no edit, fill, patch or component controls.
  - `scripts/seed_mcas.mjs` calls `POST /projects/{project}/system-versions` only when it writes
    the MCAS card.
- **Rules**
  - S3.1 When a card is saved twice through the form, then there are 2 `core.system` rows (numbers
    1 and 2) and 2 cards, pointing at them.
  - S3.2 When the second save starts, then its form is prefilled with the first card's answers,
    tags and risks, in their order.
  - S3.3 When any code UPDATEs the v1 card (or inserts or updates its answers or components) after
    v2 exists, then the DB raises. Server actions on a non-latest card return 403 without calling
    the DB.
  - S3.4 When the ontology filler or a reviewer patch targets the latest card, then it is edited in
    place and no version is made. `DEFAULT (user to confirm)`
  - S3.5 When `seed_mcas` runs on a project that already has its card, then no version is made.
    On an empty project it makes v1.
  - S3.6 When the platform is unreachable on save, then nothing is stored and the form shows "The
    platform did not answer; nothing was saved", with the answers kept in the form.
  - S3.7 Deleting the project removes its cards, answers, risks, graphs and components (cascade).
  - S3.8 The vitest and tsc baselines hold. The prefill files listed as untracked in `git status`
    are not modified in WP3.
- **Out of scope**: the prefill (WP5); the engine-component linking (WP6); carry-forward (WP16).

## WP4 (R) Migration-order check

- **Data**: none new. The fixture is a throwaway DB in the live shape:
  - platform 0001 and 0002, one project, one `core.system` / `ai_system_version` pair with the same
    pid;
  - qualification migrations up to `20260923180000_one_ai_card_per_system_version`, with one card
    on that pid, 14 answers and 1 risk;
  - engine up to 0022, 0 components, 0 evaluations;
  - control-objectives Alembic at `3b91d0e7a52c`.
- **Interfaces**: `scripts/guard-frozen.sh --orders` runs engine 0023, the WP3 Prisma migration
  and platform 0003 in all 6 permutations, each on a fresh copy
  (`CREATE DATABASE ... TEMPLATE fixture`).
- **Rules**
  - S4.1 For every order, the engine dump equals the WP0 reference (G1).
  - S4.2 For every order, `pg_dump -s -n core -n qualification` is identical across the 6 runs.
  - S4.3 For every order, the MCAS card keeps `system_id = 1e722ea2-4ce3-47fa-81bf-11a6b53ad679`,
    `core.system` has that pid with `number = 1`, and `qualification_answer` still has 14 rows.
  - S4.4 An order in which `core.system` is not yet owned by `platform_rw` fails only at 0003, with
    S2.8's message, and succeeds on a re-run after the ownership fix.
- **Out of scope**: running anything on the live DB (02 section 6).

## WP5 (R) Finish the document prefill (W3)

- **Data**: none (the prefill stores nothing).
- **Interfaces**: the existing untracked files: `services/prefill/`, `DocumentUpload.tsx`,
  `prefill-actions.ts`, `PrefillClient.ts`, `prefillChoice.ts`, `prefillFlow.ts`,
  `prefillFields.json`, their tests, and the `next.config.ts` hunk (`bodySizeLimit: "11mb"`).
  - The upload control is rendered on `/p/{project}/system/edit`. 705a288 turned
    `/qualify/new` into a redirect.
  - Compose hunks: the `qualification-prefill` service, and `PREFILL_URL` on qualification-web.
  - `scripts/verify.sh` hunk: the prefill line.
- **Rules**
  - S5.1 When a document is uploaded on the edit page, then the 21 mapped fields and the risk rows
    are proposed. The user picks "fill empty only" or "replace", and only the chosen fields change.
  - S5.2 When the upload has no market-form tags and the user saves, then the form shows "Pick at
    least one market form". No typed or prefilled answer is lost.
  - S5.3 The prefill never writes the literal "no term" into a term field; an unmatched term is
    left empty (option B). `DEFAULT (user to confirm)`
  - S5.4 The upload does not set tags.
  - S5.5 Suites: prefill Python 69+ pass, qualification vitest 353+ pass, tsc clean.
- **Out of scope**: the pre-commit secret hook (WP17).

## WP6 (R) Card agent deployed, and components linked by AIRO

- **Data**: `qualification.card_component` (created in WP3). Nothing in the engine changes.
- **6a Compose (file edit only)**:
  - A new service `qualification-agents` builds `apps/qualification/services/agents` (its
    Dockerfile), on network `backend`.
  - It gets `LLM_SERVICE_URL=http://qualification-llm:4000`.
  - qualification-web gets `AGENT_SERVICE_URL: http://qualification-agents:<port from
    service.py>`.
  - `docker compose -f <copy> config -q` passes, run on a copy in `$SCRATCH` and never with `up`.
- **6b Linking**:
  - New `src/server/services/EngineClient.ts` uses `AISC_BACKEND_URL` (already set on
    qualification-web) and the caller's token (`callerToken`):
    - `GET /api/v1/projects?platform_project_id=<pid>` gives the engine project (the first; none
      means no components);
    - then `GET /api/v1/projects/{enginePid}/aisystem`, whose `components[]` are used.
  - On the latest card's page, a "Components" panel lists them. Each row has a property select,
    pre-set by `component_type`:
    - `model`, `llm`: `hasModel`;
    - `dataset`: `hasTestingData`, with `hasTrainingData` and `hasValidationData` also offered
      (`DEFAULT (user to confirm)`);
    - `datashape`, `resource`: `hasComponent`.
  - "Link" upserts a `card_component` row with snapshot `name`, `component_type` and
    `object_name = data`. "Unlink" deletes it.
  - The export shape (`toExport`) gains `engineComponents: [{pid, name, componentType, objectName,
    property}]`.
  - `airo_min/build.py` `build_graph` emits, for each entry:
    - a node `URIRef("urn:aisc:component:" + pid)` typed by the property's range: `airo:AIModel`
      for `hasModel`, `airo:Data` for the three data properties, `airo:AIComponent` otherwise;
    - `rdfs:label` = name, `qual:objectName` = objectName;
    - `link(g, system, property, node)`.
  - `airo_min/schema.py` adds the four sub-properties with those ranges; `tests/test_schema.py`
    cross-checks them against `airo.ttl`, which is unchanged (G3).
  - The filler's free-text `components` stay as `hasComponent` nodes. The panel shows them as
    "suggestions" beside the unlinked engine components; nothing is auto-linked.
- **6c Drift**: on `/p/{project}/system`, compare the latest card's `card_component` rows with the
  engine components:
  - `removed`: a linked pid is missing from the engine;
  - `added`: an engine pid is not linked;
  - `changed`: same pid, different `component_type` or `data` (a re-upload).

  Any drift shows a banner listing it, with "Start the next version" (to `/system/edit`).
- **Rules**
  - S6.1 When a card links 2 engine components (a model and a dataset), then its JSON-LD has
    `airo:hasModel` and `airo:hasTestingData` edges from the system node to
    `urn:aisc:component:<pid>` nodes, and parsing the JSON-LD back gives the same triples
    (roundtrip test).
  - S6.2 When an engine component is deleted, added or re-uploaded, then the banner shows removed,
    added or changed respectively, and no `card_component` or `qualification` row changes.
  - S6.3 When the engine is unreachable, then the panel says "The engine did not answer" and the
    card still renders; no drift is claimed.
  - S6.4 Linking on a non-latest card is refused (S3.3).
  - S6.5 When the agents service is reachable and the LLM answers, then "Fill" stores `techniques`
    in `ontologyExtracted`. With no LLM key, "Fill" reports it and stores nothing (degrades).
  - S6.6 The caller's token is what reaches the engine; a stranger to the project gets no
    components (the engine filters with `membership.visible`).
- **Out of scope**: writing to the engine; auto-fixing drift; `risk_types` in the filler.

## WP7 (R) Control objectives from the latest version's card

- **Data**: Alembic revision `4d2a9c1e7b60`, file
  `alembic/versions/20260923210000_an_assessment_is_of_one_system_version.py`, `down_revision =
  '3b91d0e7a52c'`.
  1. `ALTER TABLE control_objectives.project ADD COLUMN system_id uuid`.
  2. Backfill: `system_id` = the project's highest-numbered `core.system.pid`.
     `control_objectives_rw` cannot read `qualification`, so `qualification_id` cannot be joined.
     On live this gives MCAS's v1, which is the version its card describes.
  3. `RAISE` if any row stays NULL, or two rows get the same `system_id`. Assessments are never
     deleted.
  4. `SET NOT NULL`; `UNIQUE (system_id)` named `uq_project_system_id`; FK
     `fk_project_system_id_core_system` to `core.system(pid) ON DELETE CASCADE`.
  5. Drop `system_name` and `qualification_id` (and the `qualification_id` index).

  `db/tables.py` declares an external `core_system` table (like `core_project`) and
  `Project.system_id`. `tests/conftest.py` `CORE_PROJECT_DDL` adds `core.system (pid uuid PK,
  project_id uuid REFERENCES core.project ON DELETE CASCADE, number int NOT NULL)`.
- **Interfaces**:
  - New qualification route file `src/app/p/[project]/api/system-versions/[systemPid]/ontology.jsonld/route.ts`,
    `GET`:
    - `fetchAccess(project, callerToken)` must give a role, else 404;
    - `prisma.qualification.findUnique({where: {systemId}})` must belong to that project, else
      404;
    - it delivers the same bytes as `/api/qualifications/{id}/ontology.jsonld`
      (`knowledgeGraphStore.deliver`); 502 when the builder is down.
  - control-objectives:
    - new env `QUALIFICATION_URL` (compose: `http://qualification-web:3000/qualification`) and
      `PLATFORM_URL` (`http://platform:8000`);
    - new client module `src/aisc_control_objectives/upstream.py` with
      `latest_version(project, token)` and `card_jsonld(project, system_pid, token)`, over
      `httpx`, forwarding the incoming `Authorization` header.
  - `POST /p/{project}/projects` (form "Start assessment", no file):
    - resolve the latest version;
    - if an assessment with that `system_id` exists, 303 to it;
    - else fetch the JSON-LD, `projects.create(project, name, jsonld, raw, system_id)`, and 303
      to it.
    - Errors: 409 "No AI card for the latest version yet" when there is no version, or the route
      404s; 502 when qualification or the platform is down. Nothing is stored in either case.
  - The upload field leaves the page. `POST /api/projects` (JSON upload) and
    `POST /api/projects/{id}/card` are removed.
  - The assessment page shows "Assessment of vN"; when vN is not the latest it shows "read-only:
    vM is the latest", and its map and severity forms are replaced by that notice.
  - `POST .../map` and `POST .../severity` on a non-latest assessment return 409.
- **Rules**
  - S7.1 When "Start assessment" is clicked twice on v1, then one assessment A1 exists, and the
    second click opens A1.
  - S7.2 When v2 exists and "Start" is clicked, then A2 is created with v2's `system_id`. A1 is
    unchanged and read-only (map and severity: 409).
  - S7.3 When a non-member calls the qualification route or any `/p/{project}/...` of
    control-objectives, then 404.
  - S7.4 The risks stored for A2 equal, by text and position, the `qualification_risk` rows of
    v2's card.
  - S7.5 `graph.jsonld` of A2 equals byte-for-byte what the qualification route returned. Its
    `digest` is `sha256` of those bytes.
  - S7.6 When the version is deleted (by the project cascade), then its assessment goes with it.
  - S7.7 A new objectives CSV changes `objectives_digest` for new assessments only. `DEFAULT (user
    to confirm)`
- **Out of scope**: carry-forward (WP16); per-project databases for control-objectives.

## WP8 (R) One-click install, same UX for tests and controls

- **Data**: none. It writes `engine.plugin` (existing `POST /api/v1/plugins`) or
  `controls.checklist` (existing controls install).
- **Interfaces**
  - Catalogue `frontend/src/components/catalogue/ToolDetailModal.tsx`: test and control entries
    render the same `<a>`-styled button "Install into a project…". For tests,
    `InstallPluginButton` gets that label and style.
  - `crossSite/connect.ts` `dispatchInstall(targetEnv, entries, project?)` opens
    `${targetEnv}/receiver?project=<pid>&uri=<web+aiscplugin URI>`. `project` is sent only when
    it matches the PID regex from `controlsInstall.ts`, and `targetEnv` only when it is an
    absolute http(s) URL. Without a handshake it falls back to the custom protocol.
  - Controls: `controlsInstallUrl` as built (`/install?slug&project`).
  - Webapp `src/pluginCatalogue/PluginInstallContext.tsx`: before `replaceState` strips the URL,
    it stores `project` through `currentPlatformProject()` (sessionStorage `aisc_platform_project`).
  - Webapp `src/components/PluginInstallDialog.tsx`: it loads `GET /api/v1/projects?
    platform_project_id=<pid>`.
    - Exactly one result is preselected. With none, it calls `POST
      /api/v1/projects/for-platform/<pid>` and preselects the result.
    - It then reads `GET /api/v1/projects/{enginePid}`. If `plugins[]` has the same `package_name`
      and `version`, it shows "Already installed in <name>" and the primary button becomes "Open
      plugins".
  - Neither file is one of Sean's 2026-09-23 files (checked: last Sean commit 0fcc0f1, 2026-09-01).
- **Rules**
  - S8.1 When the catalogue was opened from project P and the user clicks install on a test, then
    one new tab opens on the webapp with P's workspace preselected. One "Install" click gives an
    `engine.plugin` row for P's engine project with `catalogue_slug = <slug>`.
  - S8.2 When the same test is installed again, then no second row is made (existing reuse in
    `create_plugins`), and the dialog said "Already installed" before the click.
  - S8.3 When the same flow is used for a control, then `project_<P>.controls.checklist` gets one
    row with `catalogueId = <slug>`. A second install says "already installed" (as built).
  - S8.4 When the fragment carries a non-http(s) `targetEnv` or a non-uuid `project`, then neither
    is used.
  - S8.5 A test install still needs platform `admin` (`routers/plugin.py:173`); a non-admin sees
    the engine's 403 as "Installing a test takes the admin role". `DEFAULT (user to confirm)`
    (WP18)
- **Out of scope**: changing the admin rule (WP18); a service worker.

## WP9 (R) Test stamp

- **Data**: none new. It uses `engine.evaluation.system_id` (frozen column) and its FK to
  `core.system` (restored by 0023).
- **Interfaces**
  - New file `aisc_backend/repositories/system_version_repository.py` with
    `async def latest_system_pid(platform_project_id: uuid.UUID | None) -> uuid.UUID | None`.
    - It returns None when the argument is None, when the vendor is not Postgres, or when
      `to_regclass('core.system')` is null.
    - Otherwise it runs `SELECT pid FROM core.system WHERE project_id = %s ORDER BY number DESC
      LIMIT 1`, through `sync_to_async`, on `connection.cursor()`.
    - On `DatabaseError` it logs a warning and returns None.
  - `routers/evaluation.py`: one import line, and line 103 becomes `evaluation =
    Evaluation(status=EvaluationStatus.Pending, project=project, system_id=await
    latest_system_pid(project.platform_project_id))`. Line 103 is authored by 894cbffd, not Sean.
- **Rules**
  - S9.1 `git diff e34fca3 -- aisc_backend/routers/evaluation.py` shows exactly two changed lines
    (the import and line 103).
  - S9.2 When an evaluation starts while v2 is the latest, then `system_id = v2.pid`. When v3 is
    saved afterwards, then that evaluation still has v2.
  - S9.3 When the project has no version, or the engine runs on sqlite, then the evaluation starts
    with `system_id = NULL`.
  - S9.4 G1 and G5 still pass after WP9.
- **Out of scope**: the fallback `core.evaluation_stamp` table (only if the user rejects the
  one-line edit).

## WP10 (R) Control stamp

- **Data**: new controls Prisma migration
  `apps/controls/prisma/migrations/20260923210000_answers_carry_the_system_version/migration.sql`,
  applied per project DB by `scripts/migrate-projects.mjs` and on first open by
  `src/lib/projectDb.ts`:
  - `ALTER TABLE controls.submission_answer ADD COLUMN system_version_pid uuid, ADD COLUMN
    system_version_number integer, ADD COLUMN answered_at timestamptz(3)`. All nullable, no FK
    (another database).
  - `schema.prisma` `SubmissionAnswer` gains `systemVersionPid String? @map("system_version_pid")
    @db.Uuid`, `systemVersionNumber Int? @map("system_version_number")` and `answeredAt DateTime?
    @map("answered_at") @db.Timestamptz(3)`.
- **Interfaces**
  - New `src/lib/systemVersion.ts` `latestVersion(pid, token)` calls `GET
    ${PLATFORM_URL}/projects/{pid}/system-versions/latest` (3 s timeout) and returns `{pid,
    number} | null`. On error it returns null and logs a warning.
  - `saveDraft` in `src/app/p/[project]/submissions/[id]/actions.ts` still deletes and recreates
    the rows. For each new row:
    - if the old row for the same `questionId` has an equal `answer` and `score`, its three stamp
      fields are copied;
    - otherwise the row gets `answeredAt = now` and the latest version (or NULLs).
  - `reopenForAmendment` copies the three fields with each answer.
  - The submission page shows "answered under vN" per answer, "not stamped" when NULL, and in its
    header the distinct versions the answers carry.
- **Rules**
  - S10.1 When question A is answered while v1 is the latest, then v2 is saved, then question B is
    answered and the draft saved, then A carries v1 and B carries v2.
  - S10.2 When the platform is stopped, then the save succeeds and the new or changed answers have
    NULL stamps.
  - S10.3 When a draft is saved again with no change, then no stamp or `answered_at` changes.
  - S10.4 When a project DB made before WP10 is opened, then it gains the columns (migrate on
    open), and its old answers show "not stamped".
  - S10.5 Amending a closed submission keeps each copied answer's original stamp.
- **Out of scope**: a cross-database FK; re-stamping old answers.

## WP11 (R) Dashboard: visualise and comment

- **Data**
  - Template `platform/project-template/0002_dashboard.sql` (run as `platform_rw`, the database
    owner): `GRANT CONNECT ON DATABASE <current> TO dashboard_ro; GRANT USAGE ON SCHEMA controls TO
    dashboard_ro;`.
  - Controls Prisma migration `20260923210100_dashboard_reads_controls` (run as `controls_rw`, the
    table owner): `GRANT SELECT ON ALL TABLES IN SCHEMA controls TO dashboard_ro; ALTER DEFAULT
    PRIVILEGES FOR ROLE controls_rw IN SCHEMA controls GRANT SELECT ON TABLES TO dashboard_ro;`.
    See D5.
  - Superset metadata (the `superset` DB). No new aisc_ext tables: `aisc_comment` and
    `aisc_review_request` stay as they are.
- **Interfaces**
  - 11a: the bridge `aisc_ext/projects.py` has `register_project(pid, slug, name)` and
    `unregister_project(pid)`. The first is idempotent and creates, for project P (hex = pid
    without dashes):
    - on the existing "AISC Results" connection, virtual dataset `engine_results_<hex>`. It
      selects `m.pid, m.score, m.unit, m.time, m.dimensions, met.name AS metric, e.pid AS
      evaluation_pid, e.created_at AS evaluated_at, s.pid AS system_version_pid, s.number AS
      system_version` from `engine.measurement m`, joined to `observation`, `evaluation e`,
      `project p` and `metric met`, `LEFT JOIN core.system s ON s.pid = e.system_id`,
      `WHERE p.platform_project_id = '<pid>'`;
    - connection `AISC Controls <slug>`:
      `postgresql+psycopg2://dashboard_ro:<pw>@postgres:5432/project_<hex>`, with dataset
      `controls_answers_<hex>`. It selects `c.title, q.text, a.answer, a.score,
      a.system_version_number, a.answered_at, s.label, s.version AS submission_version` from
      `controls.submission_answer a`, joined to `submission s`, `checklist_question q` and
      `checklist c`;
    - role `AiscProject_<hex>`, with `datasource_access` on both datasets and `database_access` on
      the controls connection;
    - dashboard slug `aisc-<hex>`, with `roles = [AiscProject_<hex>]` (feature flag
      `DASHBOARD_RBAC: True`). It has a line chart of score by `system_version` and a table of
      answers by `system_version_number`.
  - Bridge HTTP: `POST /api/v1/aisc_project/<pid>` and `DELETE /api/v1/aisc_project/<pid>`
    (FAB `BaseApi`, `resource_name = "aisc_project"`). They are authenticated by the header
    `X-AISC-Bridge-Token` compared in constant time with env `DASHBOARD_BRIDGE_TOKEN`; 401
    otherwise.
  - The platform `add_project` (after `projectdb.provision`) and `remove_project` (before
    `projectdb.drop`) call it with env `DASHBOARD_BRIDGE_URL`, 5 s timeout. A failure is logged,
    never fatal, and retried by `provision_all` on the next `pool()`.
  - 11b login: `KeycloakSecurityManager.auth_user_oauth` adds, to the realm-mapped roles,
    `AiscProject_<hex>` for every `core.project_member` row of the subject (read over the
    `dashboard_ro` connection). A Keycloak `admin` maps to Superset `Admin` (as `_PRIORITY`).
  - 11c: commit W4, the review page `/aisc/review` (`aisc_ext/review/`, `scripts/verify_review.py`,
    `tests/test_review.py`, the `comments/api.py`, `comments/views.py` and `superset_config.py`
    hunks).
- **Rules**
  - S11.1 When a seeded throwaway project has an evaluation stamped v1 and an answer stamped v2,
    then `engine_results_<hex>` returns rows with `system_version = 1`, and
    `controls_answers_<hex>` returns rows with `system_version_number = 2`.
  - S11.2 When a member of P opens `aisc-<hex>`, then it renders and they can post a comment on a
    chart (`POST /api/v1/aisc_comment/`).
  - S11.3 When a signed-in non-member opens `aisc-<hex>`, or queries either dataset through the
    chart API, then 403 or 404 and no rows.
  - S11.4 `engine_results_<hex>` never returns a row whose `platform_project_id` differs from P.
  - S11.5 When the project is deleted, then its datasets, connection, role and dashboard are gone
    after the bridge call.
  - S11.6 Without a bridge token, `POST /api/v1/aisc_project/<pid>` returns 401.
  - S11.7 Unit tests: 74+ pass; `scripts/verify_review.py` checks pass.
- **Out of scope**: the final report; SQL Lab for viewers; `DASHBOARD_BRIDGE_TOKEN` rotation.
  Per-project roles replace plan 5's module-role membership. `DEFAULT (user to confirm)`

## WP12 (R) Pipeline chain test

- **Interfaces**:
  - `scripts/test-pipeline-chain.sh` uses one throwaway Postgres with every migration from WP4 plus
    control-objectives Alembic and one project database with the controls migrations. It then runs,
    in order, the chain-tagged tests of each module against it, sharing ids through
    `$SCRATCH/chain.json`:
    1. platform: project and v1;
    2. qualification: card v1 with 2 `card_component` rows;
    3. control-objectives: assessment on v1, with the qualification HTTP stubbed by the stored
       JSON-LD;
    4. engine: plugin row with `catalogue_slug`, and an evaluation stamped v1;
    5. controls: checklist with `catalogueId`;
    6. platform: v2;
    7. controls: an answer stamped v2 (platform stubbed by v2);
    8. `scripts/pipeline_chain/test_dashboard_queries.py`, which runs the two WP11 dataset SQL
       statements.
  - `--break <link>` is one of `qualification_fk`, `co_fk`, `engine_stamp`, `controls_stamp`,
    `card_component`. It drops that FK or skips that write, and expects the run to fail.
- **Rules**
  - S12.1 The full chain passes, and step 8 returns v1 for the test result and v2 for the answer.
  - S12.2 Each `--break` value makes the run fail at the step that consumes the link.
  - S12.3 No container remains afterwards (S0.1).
- **Out of scope**: browser automation; LLM calls (the filler is stubbed).

## WP13 (R) Webapp undo

- **Data**: none.
- **Code**: revert e36fed4. `SystemVersionBanner.tsx` and its test are deleted, and
  `AISystemSettings.tsx` returns to its 429f62c content (Sean's version). The optional read-only
  "description: vN (latest)" is dropped, because it would need an edit to Sean's
  `AISystemSettings.tsx` (see D4).
- **Rules**
  - S13.1 `grep -ri frozen src` in apps/webapp prints nothing.
  - S13.2 `git diff 429f62c -- src/components/AISystemSettings.tsx` is empty.
  - S13.3 The vitest and tsc baselines hold.
- **Out of scope**: any new webapp feature.

## Nice to have (brief)

- **WP14 (N)** ReviewRequestApi: CSRF on POST/PUT/DELETE, and the add/edit forms submit the
  fields the model has. First a test that pins each bug, then the fix.
- **WP15 (N)**
  - Add a "superseded by pipeline-2026-09-23/02" header to plans 2-6 and the roadmap; rewrite the
    spec to section 2 of 02.
  - `scripts/verify-rbac.sh` uses `/system-versions` instead of `/systems`. The 3 empty
    `project_*` DBs are left as they are. `DEFAULT (user to confirm)`
- **WP16 (N)** Carry-forward: when vN+1's assessment starts, risks with equal text and VAIR terms
  copy their rating and mapping, marked "carried from vN". `DEFAULT (user to confirm)`
- **WP17 (N)** A pre-commit hook refuses staged lines that match the secret patterns of
  `scripts/secrets.sh`.
- **WP18 (N)** A test install takes project editor instead of admin. It needs a user decision and
  touches `routers/plugin.py`.

## Deviations from 02

- **D1 `core.system` is not the platform's to alter.** The live DB shows `core.system` (and
  `core.project`) owned by `aisc-postgres-user`, and 0002's own comment says dropping core.system
  "takes the superuser". `platform_rw` holds ALL privileges but not ownership, so 02's 0003 (ADD
  COLUMN, DROP INDEX) would fail.
  - Fix: one idempotent superuser line in `init/project-databases.sql` (`ALTER TABLE core.system
    OWNER TO platform_rw`). `postgres-setup` runs that file on every start, and `platform` waits
    for it (`depends_on: service_completed_successfully`).
  - 0003 guards on ownership (S2.8). Runbook step 4 of 02 needs `postgres-setup` (or that psql
    line) run first.
- **D2 0023 must restore names explicitly.** The e34fca3 names come from the `aisc_backend_*` era
  (0020), carried across 0021's renames. 0023 therefore renames on Postgres to the reference names
  (WP1). The live DB's names may still differ, if the live DB was migrated through Sean's
  pre-squash chain. Section 6 step 5's comparison will show that, and it is then a fix-up RunSQL,
  not a schema change.
- **D3 `routers/evaluation.py` and `models/evaluation.py` are Sean's files of 2026-09-23** (commits
  1c769a8 and 66f9f1a). The stamp is limited to one import plus line 103 (blame 894cbffd), pinned by
  S9.1. If the user reads RULES.md as "no line in Sean's files", the 02 fallback
  (`core.evaluation_stamp`) applies.
- **D4 `AISystemSettings.tsx` is Sean's file of 2026-09-23.** WP13's optional "vN (latest)" is
  dropped.
- **D5 Grants on per-project controls tables.** The tables are owned by `controls_rw` (created by
  Prisma), so the template (run as `platform_rw`) cannot grant SELECT on them. The template grants
  CONNECT and schema USAGE; a controls migration grants SELECT.
- **D6 No FK-safe path for stamps to post-0002 versions.**
  - If an engine evaluation or a card points at an `ai_system_version` pid that is not in
    `core.system`, the order matters. 0023 nulls such evaluation stamps (WP1 step 8), and the
    qualification migration refuses (WP3 step 1).
  - Live has none (1 version, same pid; 0 evaluations), so every order is safe today (S4.3).
  - Safest runbook order: `postgres-setup`, platform 0003, then engine and qualification.
- **D7 The controls save rewrites every answer.** `saveDraft` does deleteMany plus createMany, so
  "stamp when answered" needs the carry rule S10.3, or every save would restamp every answer.
- **D8 Receiver URL.** 02 wrote `/receiver?package&version&slug&project`. The catalogue and
  `parseInstallUris` already carry package, version and slug in `?uri=`, so only `project=` is
  added.
- **D9 control-objectives backfill.** `control_objectives_rw` cannot read the `qualification`
  schema, so `system_id` is backfilled from the project's latest `core.system` row, not through
  `qualification_id`.
- **D10 Route placement.** Qualification's existing download routes are `/api/qualifications/[id]/*`.
  The new route lives under `/p/[project]/api/...` as 02 says, which also puts it behind
  `middleware.ts` (`matcher: ["/p/:path*"]`), plus its own check (S7.3).
- **D11 Test Postgres major version.** `postgres:14-alpine`, matching live, rather than RULES.md's
  example `postgres:16`, so that `pg_dump` output is comparable with section 6 step 5.

## Orchestrator amendments (binding, override the sections above)

- **A1 (resolves D3): no line in Sean's files changes.** RULES.md freezes Sean's code of 2026-09-23, so
  `routers/evaluation.py` and `models/evaluation.py` are not edited. The test stamp instead sets the
  existing `evaluation.system_id` from new, non-Sean code: a Django `pre_save` signal on `Evaluation`, in a
  new module (e.g. `aisc_backend/signals/system_stamp.py`) registered from a file Sean did not touch today.
  When `system_id` is null on create, it gets the project's latest system version. The engine schema
  is unchanged. If that proves impossible, use 02's fallback `core.evaluation_stamp`. S9.1 is reinterpreted
  accordingly: tests assert the behaviour (a new evaluation carries the latest version) and that Sean's
  files are byte-identical to `e34fca3`.
- **A2 (D1):** the ownership line in `init/project-databases.sql` is accepted, but it only takes effect on
  the next start of the live stack. Nothing in this run executes it against the live DB.
