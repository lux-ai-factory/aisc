# Stage 5: coding plan

Inputs: RULES.md, 03-specs.md (amendments A1 and A2 are binding), 04-tests.md and the committed
"Tests first" files, and the code (read only). Stage 6 follows this plan literally, group by
group, in this order. Every group ends with a checkpoint: the group's tests pass and
`scripts/guard-frozen.sh` passes (from group A on). If a checkpoint is red, stop and fix inside the
group; do not start the next group.

Facts checked while writing this plan (read only, throwaway containers only):

- The guard's reference dump was built (`GUARD_OUT=<scratch> scripts/guard-frozen.sh --only G1,G2`).
  G2 passes today; G1 differs by 70 lines, all from 0022 (listed in step A2). The exact reference
  names are copied into step A2.
- The backend sqlite suite today: 36 failures, 4 errors, 12 skipped. The errors that are not ours:
  `tests.integration.test_integration` (ImportError: `DataShapeStatus` is not in
  `aisc_backend.models`), and 3 SynchronousOnlyOperation errors in Sean's
  `test_project_config_router`. The failures that are not ours: 3 Keycloak integration tests.
- `prisma migrate deploy` (Prisma 5.22) exits 0 when an already applied migration file was edited
  (checked on a throwaway postgres:14-alpine with a scratch copy of `prisma/`). Step C5 relies on it.

## 0. Rules for stage 6

- Branch `feat/unified-modules` in every repo. Local commits only. NEVER push.
- Never `docker compose up/down/build/restart` against compose project `aisc`; never migrate or
  write the live DB (host port 5432, container `postgres`). `docker compose ... config` on the
  scratch copies made by `scripts/tests/test_compose.py` is read only and allowed.
- Do not edit `shared/plugin-manager`.
- Other sessions' uncommitted files stay unstaged and unmodified unless a step says otherwise:
  - apps/qualification: `next.config.ts`, `src/app/p/[project]/qualify/new/QualifyForm.tsx`
    (modified), and every untracked prefill file (`services/prefill/**` except
    `tests/test_no_term_literal.py`, `DocumentUpload.tsx`, `prefill-actions.ts`,
    `prefillFields.json`, `prefillChoice.ts`, `prefillFlow.ts`, `PrefillClient.ts`, their tests);
  - apps/results-dashboard: `aisc_ext/comments/api.py`, `aisc_ext/comments/views.py`,
    `superset_config.py` (modified), `aisc_ext/review/`, `scripts/verify_review.py`,
    `tests/test_review.py` (untracked);
  - top level: the prefill hunks of `docker-compose.development.yml`, `scripts/verify.sh`,
    `docs/superpowers/plans/*`, `docs/superpowers/specs/`, and the `apps/*` submodule pointers.

  When a step edits one of these files, stage only its own hunks with `git add -p`.
- Stage by explicit path (`git add <file>`), never `git add -A` or `git commit -a`.
- Prose in docs and commit messages: no em dashes.

### DO-NOT-EDIT

Computed with `git log --author=seanblevins --name-only`, keeping the commits whose author date is
2026-09-23 (`--since=2026-09-23` on committer date returns nothing, because Sean's commits were
merged later).

apps/backend (must end byte-identical to `e34fca3`; the only allowed change is
`git checkout e34fca3 -- <file>` in step A1):

- `aisc_backend/models/ai_system.py`, `models/common.py`, `models/evaluation.py`,
  `models/plugin.py`, `models/project_config.py`, `models/project.py`
- `aisc_backend/repositories/evaluation_repository.py`, `project_config_repository.py`,
  `project_repository.py`, `stats_repository.py`
- `aisc_backend/routers/component.py`, `evaluation.py`, `internal.py`, `plugin.py`,
  `project_config.py`, `project.py`
- `aisc_backend/schemas/ai_system.py`, `schemas/plugin.py`, `schemas/project_config.py`
- `aisc_backend/services/datashape_validation.py`, `project_config_keys.py`,
  `project_config_matching.py`
- `aisc_backend/tests/routers/test_evaluation_inputs_template.py`,
  `test_project_config_router.py`, `test_project_evaluations_serialization.py`
- `config/settings.py`, `env.development`, `pyproject.toml`
- (Sean's squashed migrations `0014_..._squashed.py` to `0022_aicomponent_unified_json_value_and_resource.py`
  do not exist in this tree; the merged `0020`/`0021` and every migration `0001` to `0022` are also
  not to be edited.)
- Also frozen by RULES.md: every file under `aisc_backend/models/` (G5), and the `Dockerfile`
  beyond dfe4120.

apps/webapp (must stay byte-identical to `429f62c`; the only allowed change is
`git checkout 429f62c -- src/components/AISystemSettings.tsx` in step A4):

- `src/api/api.tsx`, `src/components/AISystemSettings.tsx`,
  `src/components/plugin/PluginConfigForm.tsx`, `src/components/plugin/PluginEvaluationForm.tsx`,
  `src/components/plugin/PluginEvaluationForm.test.tsx`, `src/models/models.tsx`,
  `src/pages/PluginsConfig.tsx`, `src/pages/PluginStartEvaluation.tsx`,
  `src/pages/PluginStartEvaluation.test.tsx`, `src/pages/Settings.tsx`

apps/eval (no commit after `e5b1b0a`): `aisc_eval/celery_tasks.py`, `aisc_eval/plugin_runtime.py`,
`tests/test_project_settings_runtime.py`, and in practice the whole repo.

shared/plugin-interface (no commit after `97eddea`): `PLUGIN_DEVELOPER_GUIDE.md`,
`src/aisc_plugin_interface/__init__.py`, `base_evaluation_plugin.py`,
`decorators/evaluation_input.py`, `input_providers/__init__.py`,
`input_providers/json_input_provider.py`, `model_listing.py`, `models/component_value.py`,
`models/evaluation_input.py`, `models/llm.py`, `models/project_config_definition.py`,
`models/resource.py`, `openai_client.py`, and in practice the whole repo.

shared/plugin-manager: the whole repo (`git status` must stay clean).

AIRO (frozen):

- `apps/qualification/services/ontology/airo/airo.ttl`, `.../airo/vair.ttl`,
  `apps/qualification/src/data/airo_vocab.json` (G3 hashes);
- `model QualificationRisk` and `model KnowledgeGraph` in `apps/qualification/prisma/schema.prisma`;
- tables `qualification.knowledge_graph` and `qualification.qualification_risk`: no migration adds
  a column, index, trigger or FK to them (G2).

### Throwaway Postgres recipe (T)

Every DB command below that says "on T" first runs this, in the same shell (it is 04's block; the
container is removed on exit, and port 5432 is refused):

```
NAME=aisc-t-$(openssl rand -hex 4); PW=$(openssl rand -hex 12)
PORT=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')
[ "$PORT" != 5432 ] || exit 1
trap "docker rm -f $NAME >/dev/null 2>&1" EXIT
docker run --rm -d --name $NAME -p 127.0.0.1:$PORT:5432 -e POSTGRES_USER=aisc-postgres-user \
  -e POSTGRES_PASSWORD=$PW -e POSTGRES_DB=platform postgres:14-alpine >/dev/null
until docker exec $NAME pg_isready -U aisc-postgres-user -d platform >/dev/null 2>&1; do sleep 0.5; done; sleep 1
docker exec -i $NAME psql -q -U aisc-postgres-user -d platform -v ON_ERROR_STOP=1 < /home/listuser/aisc-install/init/platform-db.sql
docker exec -i $NAME psql -q -U aisc-postgres-user -d platform -v ON_ERROR_STOP=1 < /home/listuser/aisc-install/init/project-databases.sql
```

Keep it in a scratch file (for example `$SCRATCH/tpg.sh`, sourced), never in a repo. The host has
no psql or pg_dump; helpers run them with `docker exec`.

### Suite commands (reused below)

| id | repo dir | command |
|---|---|---|
| BE-sqlite | apps/backend | `PYTHONPATH=/home/listuser/aisc-install/shared/plugin-interface/src DB_ENGINE=django.db.backends.sqlite3 DB_NAME=$SCRATCH/t.db .venv/bin/python manage.py test aisc_backend` |
| BE-pg | apps/backend, on T | `PYTHONPATH=/home/listuser/aisc-install/shared/plugin-interface/src DB_ENGINE=django.db.backends.postgresql DB_NAME=platform DB_USER=aisc-postgres-user DB_PASSWORD=$PW DB_HOST=127.0.0.1 DB_PORT=$PORT .venv/bin/python manage.py test --noinput aisc_backend` |
| PLAT | platform, on T | `PLATFORM_TEST_DATABASE_URL=postgresql://platform_rw:platform_rw@127.0.0.1:$PORT/platform PLATFORM_TEST_SUPERUSER_URL=postgresql://aisc-postgres-user:$PW@127.0.0.1:$PORT/platform uv run --extra dev pytest -q -p no:cacheprovider` |
| Q-unit | apps/qualification | `npx vitest run && npx tsc --noEmit` |
| Q-db | apps/qualification | `test/db/throwaway-db.sh` (makes and removes its own container) |
| Q-py | apps/qualification | `docker run --rm -v $PWD:/w -e PYTHONDONTWRITEBYTECODE=1 -e PREFILL_FIELDS_PATH=/w/src/data/prefillFields.json -w /w/services/<ontology\|prefill\|agents> python:3.12-slim sh -c "pip install -q -r requirements.txt pytest && python -m pytest -q -p no:cacheprovider"` |
| CO | apps/control-objectives, on T | `CONTROL_OBJECTIVES_TEST_DATABASE_URL=postgresql+psycopg://aisc-postgres-user:$PW@127.0.0.1:$PORT/control_objectives_test uv run --extra dev pytest -q` |
| CTL | apps/controls, on T | `CONTROLS_TEST_PG_CONTAINER=$NAME PROJECT_DATABASE_URL="postgresql://controls_rw:controls_rw@127.0.0.1:$PORT/{database}?schema=controls&connection_limit=2" npx vitest run test/unit test/integration/answer-stamps.test.ts test/integration/dashboard-grants.test.ts test/integration/install-once-throwaway.test.ts` (ONLY these paths: see finding F1) |
| CAT | apps/catalogue/frontend | `npx vitest run` |
| WEB | apps/webapp | `npx vitest run && npx tsc -b --noEmit` |
| DASH | apps/results-dashboard, on T | `AISC_DASHBOARD_TEST_PG_CONTAINER=$NAME PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider --ignore=tests/test_sso_login.py` |
| TOP | repo root | `uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests scripts/pipeline_chain` (about 4 min, own containers) |
| GUARD | repo root | `scripts/guard-frozen.sh` (reads committed HEAD trees; `GUARD_SOURCE=worktree` before a commit) |

## Findings carried from 04, and new ones (read before group A)

- **F1 Live-DB hazard in controls (04 finding 1).** `install.test.ts`,
  `submission-lifecycle.test.ts`, `project-scope.test.ts`, `action-access.test.ts` and
  `project-database.test.ts` run `docker exec postgres psql` (CREATE/DROP DATABASE on the LIVE
  container) whenever `PROJECT_DATABASE_URL` is set. Never run plain `npx vitest run` in
  apps/controls with that variable set. Use command CTL only. 03 section 0's controls command is
  wrong on this point; 04's is right. Porting those five files to `throwawayDb.ts` is out of scope
  for this run.
- **F2 Column-name mismatch (04 finding 2).** 03 11a writes `WHERE p.platform_project_id = '<pid>'`.
  The engine column is `engine.project.project_id` (Django attribute `platform_project_id`,
  `db_column="project_id"`). The tests are right and 03 is wrong: use `p.project_id` in the
  dashboard SQL (step J3). No test fix.
- **F3 PYTHONPATH (04 finding 3).** Every backend command needs
  `PYTHONPATH=/home/listuser/aisc-install/shared/plugin-interface/src` (stale
  aisc-plugin-interface 0.2.6 in `.venv`). Do not run `uv sync` (it rewrites the venv; not needed).
- **F4 Reverse operations (04 finding 4).** 0023 must be reversible: every `RunPython` gets
  `migrations.RunPython.noop` as reverse (S1.2 migrates 0023 back to 0022).
- **F5 Tests that already error (04 finding 5).** Backend baseline: 3 SynchronousOnlyOperation
  errors in Sean's `test_project_config_router` (file identical to e34fca3, frozen), 3 Keycloak
  integration failures, 1 ImportError in `tests/integration/test_integration`. They stay red
  (see "Cannot go green"). The check is: the failing set never grows.
- **F6 Guard allowed set under A1 (04 finding 6).** The guard allows, in apps/backend: 0022 (kept),
  `0023_*`, `repositories/system_version_repository.py`, `signals/*`, `apps.py`, and
  `aisc_backend/tests/*`. Nothing else under `aisc_backend/` or `config/` may differ from e34fca3.
  So the WP9 code goes in exactly `aisc_backend/signals/` and
  `aisc_backend/repositories/system_version_repository.py`, registered from `aisc_backend/apps.py`.
- **F7 Stamp in sync and async (04 finding 7).** The pre_save signal runs inside `save()`; the
  async route calls `asave()`, which runs `save()` in a worker thread, so a sync DB helper works in
  both. The async `latest_system_pid` wraps the same helper with `sync_to_async`.
- **F8 Old tests to rewrite (04 finding 8).** Listed per step (C4, D6, G5, I2). Rule for every
  rewrite: delete only the cases whose subject is a removed behaviour (freeze, drafts, upload
  routes, old labels); change only how the fixture is made in the others; keep their assertions.
- **F9 Names pinned by tests (04 finding 9).** Used as is below.
- **F10 Environment variables (04 finding 10).** `PLATFORM_TEST_SUPERUSER_URL`,
  `QUALIFICATION_TEST_*`, `CONTROLS_TEST_PG_CONTAINER`, `AISC_DASHBOARD_TEST_PG_CONTAINER`,
  `CHAIN_*`. All point at a throwaway container.
- **F11 New: platform 0003 breaks qualification migration `20260923180000` on a fresh DB.**
  `20260923180000_one_ai_card_per_system_version` adds an unconditional FK to
  `core.ai_system_version`. On any fresh database where platform 0003 runs first (a new install,
  `test/db/throwaway-db.sh`, the guard's G1 candidate, the WP12 chain setup), that table is gone,
  so `prisma migrate deploy` fails at that migration and never reaches the WP3 migration. Decision
  (stage 5, flag to the user): make the FK statement of that file conditional (step C5). 03 WP3
  says "the bcc7093 migration file stays": it stays, with one statement guarded. Prisma 5.22
  deploy accepts the edited applied file (checked). The alternative, running every test harness
  with 0003 after Prisma, would leave fresh installs broken.
- **F12 New: `card_is_latest` must be PL/pgSQL.** In the orders Q-before-P (WP4), the qualification
  migration runs before `core.system.number` exists. A `LANGUAGE sql` function body is checked at
  CREATE time and would fail; a `LANGUAGE plpgsql` body is not.
- **F13 New: DB error inside the stamp.** On the live DB before platform 0003, `core.system` exists
  without `number`. The stamp's query must run inside `transaction.atomic()` (a savepoint), so a
  `DatabaseError` rolls back only the savepoint and the evaluation still saves with NULL.
- **F14 New: WP12 chain hazards.** (a) platform `tests/conftest.py` deletes every project whose
  slug starts `pytest-` at session end, so the chain project must use another prefix (`chain-`);
  (b) control-objectives `tests/conftest.py::repository` DROPs and re-CREATEs the database named
  in its URL, which in the chain is `platform`: the chain test must not use that fixture;
  (c) `manage.py test` creates a test database unless no test in the suite declares databases, so
  the engine chain test must be a plain `unittest.TestCase` (see K3).

## Cannot go green in this run (do not chase)

| test / rule | why |
|---|---|
| backend `tests/integration/test_keycloak_integration.py` (3 tests) | need a live Keycloak |
| backend `tests/integration/test_integration` (ImportError) | pre-existing, `DataShapeStatus` gone since Sean's merge; fixing needs a models change (frozen) |
| backend `tests/routers/test_project_config_router.py` (3 SynchronousOnlyOperation errors) | Sean's file, byte-identical to e34fca3, frozen |
| S1.5 "full suite green" | follows from the three rows above; check that the failing set does not grow |
| results-dashboard `tests/test_sso_login.py` | needs Keycloak and a browser; always `--ignore`d |
| S3.2, S3.6 "answers stay in the form"; S3.3 UI; S6.2/S6.3 banner and panel text; Link/Unlink; S10 UI labels | UI in a browser (manual list in 04) |
| S6.5 fill with an LLM; WP6a service actually starting | need the deployed agents service and an LLM key; starting containers is forbidden |
| S8.1 end to end, S8.2 row count | real tab and backend write on the stack |
| S11.2, S11.3, S11.5 end to end | need a live Superset |
| S11.7 `scripts/verify_review.py`, `tests/test_review.py` | the other session's uncommitted W4 work (group L) |
| catalogue `npx tsc --noEmit` | 81 pre-existing errors, none from our files |
| controls integration files of F1 | would touch the live server |

## Tests that contradict 03, and who is right

| test | contradiction | right | test fix |
|---|---|---|---|
| `scripts/pipeline_chain/test_dashboard_queries.py`, `apps/results-dashboard/tests/test_project_datasets_db.py` | use `p.project_id`, 03 says `p.platform_project_id` | tests (real column) | none |
| `services/ontology/tests/test_schema.py::test_exactly_the_figure_3_subset_with_the_collapse` (19 classes, 19 properties), `::test_every_parent_edge_is_declared_in_airo` (6 edges) | WP6 adds `AIModel`, `Data`, and the four sub-properties | 03 WP6 | set 21, 23 and 8 (step F4); faithful, the other checks against airo.ttl stay |
| `platform/tests/test_api_membership.py` (4 tests on `/projects/{slug}/systems`) | WP2 removes that route | 03 WP2 | point them at `/system-versions` (step C4) |
| `platform/tests/test_ai_system.py`, `test_api_ai_system.py` | pin the removed freeze model | 03 WP2 | delete (step C3) |
| backend `tests/routers/test_ai_system_versions.py`, `tests/test_system_versions.py` | pin 0022's code | 03 WP1 | deleted by the revert (step A1) |
| qualification `test/unit/cardSubmission.test.ts`, `PlatformClient.test.ts`, `cardVersions.test.ts`, `seedMcas.test.ts` | pin the freeze model | 03 WP3 | rewrite per F8 (step D6) |
| control-objectives `tests/test_projects.py`, `tests/test_repository.py`, `tests/test_project_access.py::test_an_editor_gets_past_the_door` | upload a card | 03 WP7 | rewrite per F8 (step G5) |
| catalogue `ToolDetailModal.test.tsx` "offers the enable once the index has a version" | looks for "Enable plugin" | 03 WP8 (S8.1) | new label (step I2) |
| webapp `SystemVersionBanner.test.tsx` | the banner goes | 03 WP13 | delete (step A4) |
| 03 S9.1 "two changed lines" vs A1 "no line in Sean's files" | | A1 (binding) | tests already follow A1 |
| 03 section 0 controls command `npx vitest run` | writes to the live server (F1) | 04 | use CTL |

---

## Group 0: preflight (no commit)

0.1 Check branches and cleanliness:

```
cd /home/listuser/aisc-install
for r in . apps/backend apps/webapp apps/eval shared/plugin-interface shared/plugin-manager apps/qualification \
         apps/control-objectives apps/controls apps/catalogue apps/results-dashboard; do
  printf '%-28s %s\n' "$r" "$(git -C $r branch --show-current)"; done
git -C shared/plugin-manager status --porcelain   # must print nothing
```

Every repo must be on `feat/unified-modules`, except that apps/eval, shared/plugin-interface and
shared/plugin-manager are only checked for "no new commits / clean". Stop and ask the user if not.

0.2 Record baselines into `$SCRATCH/baseline/` (BE-sqlite, Q-unit, CO on T, CTL on T, CAT, WEB,
DASH on T, PLAT on T). They are the "does not grow" references.

---

## Group A: engine undo (WP1) and webapp undo (WP13)

Both are reverts; after this group the whole guard (G1 to G5) passes, and it must keep passing at
every later checkpoint.

### A1. apps/backend: revert e144bc9 and a38dbb4, keep 0022 and dfe4120

```
cd /home/listuser/aisc-install/apps/backend
git checkout e34fca3 -- aisc_backend/admin.py aisc_backend/auth/membership.py \
  aisc_backend/models/ai_system.py aisc_backend/models/evaluation.py aisc_backend/models/project.py \
  aisc_backend/repositories/project_repository.py aisc_backend/repositories/stats_repository.py \
  aisc_backend/routers/component.py aisc_backend/routers/evaluation.py aisc_backend/routers/internal.py \
  aisc_backend/routers/project.py aisc_backend/schemas/ai_system.py \
  aisc_backend/tests/routers/test_evaluation_inputs_template.py \
  aisc_backend/tests/routers/test_project_evaluations_serialization.py \
  aisc_backend/tests/routers/test_project_membership.py
git rm -q aisc_backend/services/platform_client.py aisc_backend/services/platform_versions.py \
  aisc_backend/services/system_versions.py aisc_backend/tests/routers/test_ai_system_versions.py \
  aisc_backend/tests/test_system_versions.py
```

`aisc_backend/migrations/0022_parts_belong_to_a_version_of_the_one_system.py` and `Dockerfile` are
not touched. Check: `git diff --stat e34fca3 -- aisc_backend config` lists only the 0022 file and
the four new test files of 2e718cd.

### A2. apps/backend: new migration 0023

Create `aisc_backend/migrations/0023_one_system_per_project_again.py`:

- `dependencies = [("aisc_backend", "0022_parts_belong_to_a_version_of_the_one_system")]`.
- Module docstring: why (the engine is back to e34fca3; the platform's card versions live in
  core.system; names are restored to the e34fca3 dump because Postgres keeps names across the
  0021 renames).
- Helper `def _pg(schema_editor): return schema_editor.connection.vendor == "postgresql"`.
- Operations, in this order:

1. `RunPython(drop_version_links, migrations.RunPython.noop)`; on Postgres only:
   ```sql
   ALTER TABLE ai_component DROP CONSTRAINT IF EXISTS ai_component_system_version_id_fkey;
   ALTER TABLE evaluation DROP CONSTRAINT IF EXISTS evaluation_system_version_id_fkey;
   ```
2. `CreateModel(name="AISystem", fields=[...], options={"db_table": "ai_system"})` with the field
   list copied from 0020 in the same order (column order must match the dump):
   `id BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")`,
   `pid UUIDField(default=uuid.uuid4, editable=False)`, `name CharField(max_length=255)`,
   `description CharField(max_length=255)`, `created_at DateTimeField(auto_now_add=True)`,
   `project OneToOneField(on_delete=CASCADE, related_name="aisystem", to="aisc_backend.project")`.
3. `AddField("aicomponent", "system", ForeignKey(null=True, on_delete=CASCADE, related_name="components", to="aisc_backend.aisystem"))`.
4. `RunPython(parts_back_on_the_system, migrations.RunPython.noop)`:
   ```python
   def parts_back_on_the_system(apps, schema_editor):
       db = schema_editor.connection.alias
       Project = apps.get_model("aisc_backend", "Project")
       AISystem = apps.get_model("aisc_backend", "AISystem")
       AIComponent = apps.get_model("aisc_backend", "AIComponent")
       for project in Project.objects.using(db).all():
           system = AISystem.objects.using(db).create(
               project=project, name=f"{project.name} system", description="")
           AIComponent.objects.using(db).filter(project=project).update(system=system)
   ```
   (one system per engine project, named as e34fca3's `get_or_create_aisystem` names it; pids of
   parts are untouched.)
5. `AlterField("aicomponent", "system", ForeignKey(on_delete=CASCADE, related_name="components", to="aisc_backend.aisystem"))` (NOT NULL).
6. `RemoveField("aicomponent", "project")`, `RemoveField("aicomponent", "system_version_id")`,
   `RemoveField("aicomponent", "lineage")`, `DeleteModel("SystemVersionParts")`.
7. `RunPython(restore_reference_names, migrations.RunPython.noop)`; on Postgres only, one DO block
   that looks every name up in the catalog and renames it to the e34fca3 reference name (taken
   from the reference dump, which is authoritative):

   | object | reference name |
   |---|---|
   | PK of `ai_system` (`contype='p'`) | `aisc_backend_aisystem_pkey` |
   | UNIQUE of `ai_system` (`contype='u'`) | `aisc_backend_aisystem_project_id_key` |
   | FK of `ai_system` (`contype='f'`) | `aisc_backend_aisystem_project_id_381e09a9_fk_project_id` |
   | FK of `ai_component` with `confrelid='ai_system'::regclass` | `aisc_backend_aicompo_system_id_0909bda5_fk_aisc_back` |
   | non-PK index of `ai_component` on `system_id` only | `aisc_backend_aicomponent_system_id_0909bda5` |
   | identity sequence `pg_get_serial_sequence('ai_system','id')` | `aisc_backend_aisystem_id_seq` |

   ```sql
   DO $$
   DECLARE n text;
   BEGIN
     SELECT conname INTO n FROM pg_constraint WHERE conrelid = 'ai_system'::regclass AND contype = 'p';
     IF n <> 'aisc_backend_aisystem_pkey' THEN
       EXECUTE format('ALTER TABLE ai_system RENAME CONSTRAINT %I TO aisc_backend_aisystem_pkey', n); END IF;
     -- same for contype 'u' and 'f' on ai_system, and the ai_component FK into ai_system
     SELECT i.relname INTO n FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid
      WHERE x.indrelid = 'ai_component'::regclass AND NOT x.indisprimary
        AND x.indkey::text = (SELECT attnum::text FROM pg_attribute
                               WHERE attrelid = 'ai_component'::regclass AND attname = 'system_id');
     IF n <> 'aisc_backend_aicomponent_system_id_0909bda5' THEN
       EXECUTE format('ALTER INDEX %I RENAME TO aisc_backend_aicomponent_system_id_0909bda5', n); END IF;
     n := pg_get_serial_sequence('ai_system', 'id');
     IF n IS NOT NULL AND n NOT LIKE '%aisc_backend_aisystem_id_seq' THEN
       EXECUTE format('ALTER SEQUENCE %s RENAME TO aisc_backend_aisystem_id_seq', n); END IF;
   END $$;
   ```
   (Renaming a PK or UNIQUE constraint also renames its index.)
8. `RunPython(link_evaluation_to_core_system, migrations.RunPython.noop)`; on Postgres only:
   ```sql
   DO $$
   BEGIN
     IF to_regclass('core.system') IS NOT NULL THEN
       UPDATE evaluation SET system_id = NULL
        WHERE system_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM core.system s WHERE s.pid = evaluation.system_id);
       IF NOT EXISTS (SELECT 1 FROM pg_constraint
                       WHERE conrelid = 'evaluation'::regclass
                         AND conname = 'aisc_backend_evaluation_system_id_fkey') THEN
         ALTER TABLE evaluation ADD CONSTRAINT aisc_backend_evaluation_system_id_fkey
           FOREIGN KEY (system_id) REFERENCES core.system (pid) ON DELETE SET NULL;
       END IF;
     END IF;
   END $$;
   ```
   (Not DEFERRABLE, exactly as 0015 made it.)

Reverse: every RunPython reverse is `RunPython.noop`; the schema operations reverse themselves.
Going back to 0022 is only done on empty tables (S1.2's test).

The 70-line G1 diff this step must remove (from the guard run): `ai_component.project_id`,
`system_version_id`, `lineage` and their indexes and FKs; missing `ai_system` table, sequence,
PK, UNIQUE, FK and ACL; `system_version_parts` and its objects; missing
`aisc_backend_evaluation_system_id_fkey`; extra `evaluation_system_version_id_fkey`.

### A3. Checkpoint A (backend)

Commands: BE-sqlite, then BE-pg on T.

Turns green:
- `aisc_backend/tests/test_one_system_per_project.py`: every test
  (`ModelStateIsE34fca3.*`, `Migration0023Exists.*`, `OneSystemPerProject.test_s1_6_second_system_for_a_project_is_refused`,
  `AISystemRouteIsE34fca3.*`, `EvaluationTaskWithoutThePlatform.*`);
- `aisc_backend/tests/test_migration_0023_data.py::Migration0023MovesPartsBackOntoTheSystem.test_s1_2_every_part_keeps_its_pid_and_joins_its_project_s_one_system` (sqlite and Postgres);
- `aisc_backend/tests/test_frozen_sean_files.py`: every test.

Expected still red after A: the F5 set (7), and in `test_evaluation_system_stamp.py` the WP9 tests
(group B).

Commit (apps/backend): `One AI system per project again, as at Sean's merge` with a body: reverts
e144bc9 and a38dbb4 except migration 0022; 0023 moves every part back onto its project's one
AISystem, restores the e34fca3 names and the evaluation's key into core.system; the engine no
longer asks the platform for versions.

### A4. apps/webapp: revert e36fed4 (WP13)

```
cd /home/listuser/aisc-install/apps/webapp
git checkout 429f62c -- src/components/AISystemSettings.tsx
git rm -q src/components/SystemVersionBanner.tsx src/components/SystemVersionBanner.test.tsx
```

Turns green: `src/wp13Undo.test.ts::S13.1 no file under src mentions "frozen"`,
`::S13.2 AISystemSettings.tsx is byte-identical to Sean's 429f62c`, `::S13.2 SystemVersionBanner is gone`.
Command: WEB (the 7 dialog tests of `PluginInstallDialog.wp8.test.tsx` stay red until group I;
tsc 0 errors).

Commit (apps/webapp): `The AI system settings are Sean's again; no version banner`.

### A5. Checkpoint A (guard)

```
cd /home/listuser/aisc-install && scripts/guard-frozen.sh      # expect G1..G5 PASS, "GUARD PASS"
uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests/test_guard_frozen.py \
  -k "s0_ or s1_1 or s1_4 or s1_6 or g2 or g3 or g4 or s9_1"
```

Turns green: `scripts/tests/test_guard_frozen.py::test_s1_1_engine_schema_equals_e34fca3`,
`::test_s1_4_backend_part_of_g4_and_g5`, `::test_s1_6_one_ai_system_per_engine_project`,
`::test_g4_webapp_seans_files_identical_to_429f62c`,
`::test_s9_1_seans_evaluation_files_are_byte_identical_to_e34fca3[aisc_backend/routers/evaluation.py]`,
`[aisc_backend/models/evaluation.py]`. The S0.x, G2, G3 and G4-eval tests stay green.

---

## Group B: the test stamp (WP9, amendment A1)

### B1. apps/backend: `aisc_backend/repositories/system_version_repository.py` (new)

```python
"""The latest saved AI card version of a platform project (core.system), for the test stamp."""
import logging, uuid
from asgiref.sync import sync_to_async
from django.db import DatabaseError, connection, transaction

logger = logging.getLogger(__name__)
LATEST = "SELECT pid FROM core.system WHERE project_id = %s ORDER BY number DESC LIMIT 1"

def latest_system_pid_sync(platform_project_id: uuid.UUID | None) -> uuid.UUID | None:
    if platform_project_id is None or connection.vendor != "postgresql":
        return None
    try:
        with transaction.atomic():               # a savepoint: an error spoils nothing (F13)
            with connection.cursor() as cursor:
                cursor.execute("SELECT to_regclass('core.system') IS NOT NULL")
                if not cursor.fetchone()[0]:
                    return None
                cursor.execute(LATEST, [str(platform_project_id)])
                row = cursor.fetchone()
    except DatabaseError:
        logger.warning("could not read the latest system version of %s", platform_project_id, exc_info=True)
        return None
    return uuid.UUID(str(row[0])) if row else None

async def latest_system_pid(platform_project_id: uuid.UUID | None) -> uuid.UUID | None:
    return await sync_to_async(latest_system_pid_sync)(platform_project_id)
```

### B2. apps/backend: `aisc_backend/signals/__init__.py` (empty docstring) and `aisc_backend/signals/system_stamp.py` (new)

```python
from django.db.models.signals import pre_save
from django.dispatch import receiver
from aisc_backend.models.evaluation import Evaluation
from aisc_backend.repositories.system_version_repository import latest_system_pid_sync

@receiver(pre_save, sender=Evaluation, dispatch_uid="aisc_evaluation_system_stamp")
def stamp_the_latest_system_version(sender, instance, raw=False, **kwargs):
    """A new evaluation records the card version that is the latest when it starts; it is never restamped."""
    if raw or not instance._state.adding or instance.system_id is not None or instance.project_id is None:
        return
    instance.system_id = latest_system_pid_sync(instance.project.platform_project_id)
```

### B3. apps/backend: `aisc_backend/apps.py`

Add to `AiscBackendConfig`:

```python
    def ready(self):
        from aisc_backend.signals import system_stamp  # noqa: F401  (the test stamp, WP9)
```

`config/settings.py` lists `'aisc_backend'`; Django picks the single AppConfig subclass, so no
settings change (settings.py is Sean's).

### B4. Checkpoint B

Commands: BE-sqlite, BE-pg on T, GUARD.

Turns green, `aisc_backend/tests/test_evaluation_system_stamp.py`:
`LatestSystemPid.test_s9_latest_system_pid_is_an_async_function`, `test_s9_3_none_for_no_platform_project`,
`test_s9_3_none_on_sqlite` (sqlite), `test_s9_3_none_when_core_system_is_absent` (pg),
`test_s9_2_highest_number_wins` (pg), `test_s9_3_none_when_the_project_has_no_version` (pg);
`EvaluationCarriesTheLatestVersion.test_s9_2_new_evaluation_gets_the_latest_version_and_keeps_it` (pg),
`test_s9_2_started_through_the_route` (pg), `test_s9_3_route_without_a_version_starts_with_null`;
kept green: `test_s9_2_an_explicit_system_id_is_kept`, `test_s9_3_no_version_gives_null`,
`test_s9_3_sqlite_gives_null`. Also `scripts/tests/test_guard_frozen.py::test_s9_4_g1_and_g5_after_the_stamp`
(run TOP `-k s9_4` after the commit).

Commit (apps/backend): `A test records the AI card version that was the latest when it started`
(body: a pre_save signal outside Sean's files, per amendment A1; NULL when the project has no
version, on sqlite, or when core.system cannot be read).

---

## Group C: platform card versions in core.system (WP2), and the fresh-DB order fix (F11)

### C1. `init/project-databases.sql` (top level): append

```
-- core.system is the platform's to migrate (platform migration 0003 adds its version number and
-- the only-latest rule). It was made by the superuser in init/platform-db.sql; this runs as the
-- superuser on every start of postgres-setup, and again changes nothing.
\connect platform
ALTER TABLE core.system OWNER TO platform_rw;
```

(A2: this takes effect on the live stack only at its next start. Nothing in this run executes it
against the live DB.)

### C2. `platform/migrations/0003_card_versions_in_core_system.sql` (new, runs as platform_rw)

Header comment: what and why (one saved AI card version per row, numbered per project; only the
latest may change; core.ai_system* go). Then, in order:

```sql
-- 1. the superuser must have handed core.system over (init/project-databases.sql)
DO $$
BEGIN
  IF (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'core.system'::regclass) <> current_user THEN
    RAISE EXCEPTION 'core.system must be owned by platform_rw: run init/project-databases.sql as the superuser';
  END IF;
END $$;

-- 2. versions 0002 made that core.system does not have yet (plpgsql plans lazily, so the
--    branch may name a table that is absent)
DO $$
BEGIN
  IF to_regclass('core.ai_system_version') IS NOT NULL THEN
    INSERT INTO core.system (pid, project_id, name, version, provider, description, created_at)
    SELECT v.pid, a.project_id, v.name, v.release, v.provider, v.description, v.created_at
      FROM core.ai_system_version v JOIN core.ai_system a ON a.pid = v.ai_system_id
     WHERE NOT EXISTS (SELECT 1 FROM core.system s WHERE s.pid = v.pid);
  END IF;
END $$;

-- 3.
ALTER TABLE core.system ADD COLUMN IF NOT EXISTS number integer;
ALTER TABLE core.system ADD COLUMN IF NOT EXISTS created_by text;

-- 4.
UPDATE core.system s SET number = n.rn
  FROM (SELECT pid, row_number() OVER (PARTITION BY project_id ORDER BY created_at, pid) AS rn
          FROM core.system) n
 WHERE s.pid = n.pid AND s.number IS NULL;
ALTER TABLE core.system ALTER COLUMN number SET NOT NULL;
ALTER TABLE core.system ADD CONSTRAINT system_number_positive CHECK (number > 0);

-- 5.
DROP INDEX IF EXISTS core.system_identity_idx;
ALTER TABLE core.system DROP CONSTRAINT IF EXISTS system_project_id_name_version_key;
ALTER TABLE core.system ADD CONSTRAINT system_project_number_key UNIQUE (project_id, number);

-- 6.
DROP TABLE IF EXISTS core.ai_system_version CASCADE;
DROP TABLE IF EXISTS core.ai_system CASCADE;
DROP FUNCTION IF EXISTS core.ai_system_version_is_frozen();

-- 7.
CREATE FUNCTION core.system_only_latest_changes() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.number <> OLD.number OR NEW.project_id <> OLD.project_id
     OR OLD.number < (SELECT max(number) FROM core.system WHERE project_id = OLD.project_id) THEN
    RAISE EXCEPTION 'system version % of project % is not the latest and cannot change',
      OLD.number, OLD.project_id;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER system_only_latest_changes BEFORE UPDATE ON core.system
  FOR EACH ROW EXECUTE FUNCTION core.system_only_latest_changes();

-- 8.
COMMENT ON TABLE core.system IS
  'One saved AI card version of the project''s one AI system; number 1, 2, ... per project.';
```

No reverse file (the platform runner has none); the file is the whole change. Grants on
core.system are untouched and survive (S2.6 grants test).

### C3. platform code: revert b723c73, e126a3f, 72edfbf, and add the version routes

```
cd /home/listuser/aisc-install
git checkout b723c73^ -- platform/platform_service/app.py platform/platform_service/db.py
git rm -q platform/platform_service/ai_system.py platform/tests/test_ai_system.py platform/tests/test_api_ai_system.py
```

`platform/migrations/0002_one_ai_system_per_project.sql` stays. Then edit:

`platform/platform_service/db.py`, in the "systems" section: remove `list_systems` and
`register_system`; keep `get_system` and add `number, created_by` to its select. Add:

```python
_VERSION = ("s.pid, s.project_id, s.number, s.name, s.version, s.provider, s.description,"
            " s.created_at, s.created_by")

def create_version(project: str, name: str, version: str | None, provider: str | None,
                   description: str | None, subject: str | None) -> dict | None:
    """The project's next card version, numbered max+1 under a per-project advisory lock."""
    with pool().connection() as conn, conn.transaction():
        pid = _project_pid(conn, project)
        if pid is None:
            return None
        conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (str(pid),))
        return conn.execute(
            "insert into core.system (project_id, number, name, version, provider, description, created_by)"
            " values (%s, (select coalesce(max(number), 0) + 1 from core.system where project_id = %s),"
            " %s, %s, %s, %s, %s)"
            f" returning pid, project_id, number, name, version, provider, description, created_at, created_by",
            (pid, pid, name, version, provider, description, subject)).fetchone()

def list_versions(project: str) -> list[dict] | None:   # highest number first; None: no such project
def latest_version(project: str) -> dict | None | bool:  # see below
```

`latest_version` must tell "no project" from "no version": return `(found_project: bool, row | None)`
or raise a small `NoSuchProject`; pick one and use it in app.py. Both select `_VERSION` from
`core.system s join core.project p on p.pid = s.project_id` filtered by pid or slug
(`looks_like_pid`), ordered by `s.number desc` (`limit 1` for latest).

`platform/platform_service/app.py`: remove the routes `GET /projects/{slug}/systems` and
`POST /projects/{slug}/systems`; keep `GET /systems/{pid}` (now with `number`, `created_by`); add:

- `POST /projects/{project}/system-versions` (status 201): `role_or_404(project, caller, "editor")`,
  then `name, version = system_key(body.name, body.version)` (422 through the existing
  `InvalidSystem` handler), then `db.create_version(project, name, version, body.provider,
  body.description, caller.subject)`; None is 404. Body model: the existing `SystemIn`.
- `GET /projects/{project}/system-versions` (viewer): the list, or 404.
- `GET /projects/{project}/system-versions/latest` (viewer): the row, or `None` (200 `null`); 404
  for no such project. Return annotation `dict | None`.

Order inside each handler: `role_or_404` first (a stranger gets 404 before anything else), then
the lookup. `POST /projects` creates no system row (already so after the checkout).

### C4. platform tests: `platform/tests/test_api_membership.py`

In `test_a_viewer_may_not_name_a_system_and_an_editor_may`, `test_a_viewer_can_read_the_systems`,
`test_a_stranger_cannot_read_the_systems`, `test_a_stranger_cannot_read_a_system_by_its_own_id`:
replace the path `/projects/{slug}/systems` with `/projects/{slug}/system-versions`; nothing else
changes (the membership rules they pin are S2.2's).

### C5. apps/qualification: make `20260923180000_one_ai_card_per_system_version/migration.sql` tolerant (F11)

Replace only its two FK statements with:

```sql
ALTER TABLE qualification DROP CONSTRAINT IF EXISTS "Qualification_system_id_fkey";
-- On a database where the platform already dropped core.ai_system_version (its 0003), there is
-- nothing to point at here: 20260923210000 points the key at core.system.
DO $$
BEGIN
  IF to_regclass('core.ai_system_version') IS NOT NULL THEN
    ALTER TABLE qualification
      ADD CONSTRAINT "qualification_system_id_fkey"
      FOREIGN KEY (system_id) REFERENCES core.ai_system_version (pid) ON DELETE CASCADE;
  END IF;
END $$;
```

Everything else in the file stays byte for byte. Commit it in apps/qualification now (message:
`The one-card-per-version migration also runs where the platform already moved on`).

### C6. `docker-compose.development.yml` (top level)

Remove from service `aisc-backend` the two comment lines and `PLATFORM_URL: http://platform:8000`
(lines 65 to 67, from c0f460e). Stage with `git add -p` (the file has other people's prefill hunks).

### C7. Checkpoint C

Commands: PLAT on T; TOP `-k "wp2 or s6a_compose_config"` (after the top-level commit); GUARD.

Turns green:
- `platform/tests/test_card_versions_migration.py`: every test
  (`test_d1_project_databases_sql_gives_core_system_to_platform_rw`,
  `test_d1_running_the_platform_part_twice_makes_platform_rw_the_owner`, `test_s2_6_*` (4),
  `test_s2_7_on_the_live_shape_every_pid_is_kept_and_mcas_is_number_1`,
  `test_s2_8_without_ownership_0003_fails_with_the_guard_message_and_is_not_recorded`,
  `test_s2_4_the_trigger_refuses_changes_to_an_older_version_and_to_number_or_project`);
- `platform/tests/test_api_system_versions.py`: every test (`test_s2_1_*` (5), `test_s2_2_*` (3),
  `test_s2_3_*`, `test_s2_4_*`, `test_s2_5_*`, `test_s2_9_*` (2),
  `test_wp2_the_old_system_routes_are_gone[*]` (5), `test_wp2_the_old_version_routes_are_gone`);
- `platform/tests/test_compose_engine_env.py::test_wp2_aisc_backend_has_no_platform_url`;
- `scripts/tests/test_compose.py::test_wp2_aisc_backend_has_no_platform_url`;
- the four rewritten `test_api_membership.py` tests; the rest of PLAT stays at its baseline.

Still red: `platform/tests/test_dashboard_bridge.py` (group J).

Commits:
- top level: `Card versions are rows of core.system, numbered per project` (files:
  `init/project-databases.sql`, `platform/migrations/0003_card_versions_in_core_system.sql`,
  `platform/platform_service/app.py`, `platform/platform_service/db.py`, deleted
  `platform/platform_service/ai_system.py`, `platform/tests/test_ai_system.py`,
  `platform/tests/test_api_ai_system.py`, `platform/tests/test_api_membership.py`);
- top level: `The engine no longer needs the platform's address` (the compose hunk).

---

## Group D: qualification undo, and "save = next version" (WP3)

### D1. Prisma migration `prisma/migrations/20260923210000_card_versions_point_at_core_system/migration.sql` (new)

```sql
-- 1. cards are never deleted: refuse when one points outside core.system
DO $$
DECLARE missing text;
BEGIN
  SELECT string_agg(DISTINCT q.system_id::text, ', ') INTO missing
    FROM qualification q
   WHERE NOT EXISTS (SELECT 1 FROM core.system s WHERE s.pid = q.system_id);
  IF missing IS NOT NULL THEN
    RAISE EXCEPTION 'cards point at system versions missing from core.system: %', missing;
  END IF;
END $$;

-- 2.
ALTER TABLE qualification DROP CONSTRAINT IF EXISTS qualification_system_id_fkey;
ALTER TABLE qualification DROP CONSTRAINT IF EXISTS "Qualification_system_id_fkey";
ALTER TABLE qualification ADD CONSTRAINT qualification_system_id_fkey
  FOREIGN KEY (system_id) REFERENCES core.system (pid) ON DELETE CASCADE;

-- 3. PL/pgSQL on purpose (F12): core.system.number may not exist yet when this runs
CREATE FUNCTION qualification.card_is_latest(version_pid uuid) RETURNS boolean
LANGUAGE plpgsql STABLE AS $$
BEGIN
  RETURN EXISTS (
    SELECT 1 FROM core.system s
     WHERE s.pid = version_pid
       AND s.number = (SELECT max(o.number) FROM core.system o WHERE o.project_id = s.project_id));
END $$;

-- 4.
CREATE FUNCTION qualification.qualification_only_latest_changes() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT qualification.card_is_latest(OLD.system_id) THEN
    RAISE EXCEPTION 'AI card % is of a version that is not the latest: it is kept as it was', OLD.id;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER qualification_only_latest_changes BEFORE UPDATE ON qualification.qualification
  FOR EACH ROW EXECUTE FUNCTION qualification.qualification_only_latest_changes();

-- 5. answers: INSERT or UPDATE only (no DELETE trigger, so the project cascade is never blocked)
CREATE FUNCTION qualification.answer_only_latest_changes() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT qualification.card_is_latest(
       (SELECT q.system_id FROM qualification.qualification q WHERE q.id = NEW."qualificationId")) THEN
    RAISE EXCEPTION 'AI card % is of a version that is not the latest: it is kept as it was', NEW."qualificationId";
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER qualification_answer_only_latest_changes
  BEFORE INSERT OR UPDATE ON qualification.qualification_answer
  FOR EACH ROW EXECUTE FUNCTION qualification.answer_only_latest_changes();

-- 6. card_component (WP6 fills it)
CREATE TABLE qualification.card_component (
  id               text PRIMARY KEY,
  qualification_id text NOT NULL REFERENCES qualification.qualification (id) ON DELETE CASCADE,
  component_pid    uuid NOT NULL,
  airo_property    text NOT NULL CHECK (airo_property IN
                     ('hasModel','hasTrainingData','hasTestingData','hasValidationData','hasComponent')),
  name             text NOT NULL,
  component_type   text NOT NULL,
  object_name      text NOT NULL DEFAULT '',
  linked_at        timestamptz(3) NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX card_component_qualification_id_component_pid_key
  ON qualification.card_component (qualification_id, component_pid);
CREATE INDEX card_component_component_pid_idx ON qualification.card_component (component_pid);
CREATE FUNCTION qualification.component_only_latest_changes() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT qualification.card_is_latest(
       (SELECT q.system_id FROM qualification.qualification q WHERE q.id = NEW.qualification_id)) THEN
    RAISE EXCEPTION 'AI card % is of a version that is not the latest: it is kept as it was', NEW.qualification_id;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER card_component_only_latest_changes
  BEFORE INSERT OR UPDATE ON qualification.card_component
  FOR EACH ROW EXECUTE FUNCTION qualification.component_only_latest_changes();
```

Index names follow Prisma's convention, so `prisma migrate diff` stays clean. No reverse (Prisma
has none). Nothing touches `knowledge_graph` or `qualification_risk` (G2).

### D2. `prisma/schema.prisma`

Add (and `components CardComponent[]` on `Qualification`; update the comment on `systemId` to say
it is a `core.system` row, a card version). `QualificationRisk` and `KnowledgeGraph` unchanged.

```prisma
model CardComponent {
  id              String        @id @default(cuid())
  qualificationId String        @map("qualification_id")
  componentPid    String        @map("component_pid") @db.Uuid
  airoProperty    String        @map("airo_property")
  name            String
  componentType   String        @map("component_type")
  objectName      String        @default("") @map("object_name")
  linkedAt        DateTime      @default(now()) @map("linked_at") @db.Timestamptz(3)
  qualification   Qualification @relation(fields: [qualificationId], references: [id], onDelete: Cascade)

  @@unique([qualificationId, componentPid])
  @@index([componentPid])
  @@map("card_component")
}
```

Then `npx prisma generate` (generated client only, not committed).

### D3. `src/server/services/PlatformClient.ts`

Keep `call()` and the constructor. Remove `aiSystem`, `versionForNewCard`, `freeze`,
`PlatformAISystem`, `frozen_at`. New types and methods:

```ts
export type CardVersion = { pid: string; project_id: string; number: number; name: string;
  version: string | null; provider: string | null; description: string | null;
  created_at: string; created_by: string | null };
latestVersion(project: string): Promise<CardVersion | null>   // GET  /projects/{p}/system-versions/latest
listVersions(project: string): Promise<CardVersion[]>          // GET  /projects/{p}/system-versions
createVersion(project: string, identity: SystemIdentity): Promise<CardVersion>
                                                               // POST /projects/{p}/system-versions, body {name, version, provider, description}
```

`call` must send `method` explicitly (the test reads `init.method === "GET"`). The unreachable
message keeps "the platform did not answer".

### D4. `src/domain/cardVersions.ts`

Rows are `{pid, number}` (type `VersionRef = { pid: string; number: number }`); the word "frozen"
must not appear anywhere in the file (a test greps it).
- `nextCard(versions, cards)`: `versionNumber = (max number ?? 0) + 1`, always; `fromCardId` and
  `fromVersionNumber` from the highest-numbered version that has a card.
- `cardStanding(versions, cards, systemId)`: `current` is true only when `systemId` is the latest
  version's pid; `currentCardId` is the latest version's card id or null; `versionNumber` as now.
- `cardAsFormStart` unchanged.

### D5. Services, actions and pages

- `src/server/services/QualificationService.ts`: delete `CardExistsError`. `createFromForm`:
  parse; `createVersion(project, {name: systemName, version: systemVersion, provider: company,
  description})`; `repo.create({...parsed, projectId: version.project_id, systemId: version.pid})`.
  `startingPoint`, `currentCardId`, `standing`, `versionNumbers` use `listVersions` (and
  `project_id` of the rows; with no versions, resolve cards by the project the page already has).
- New `src/server/services/cardLatest.ts`:
  ```ts
  export const NOT_LATEST = "403: this AI card is of an older version and is kept as it was; only the latest version changes.";
  export class NotLatestError extends Error { constructor() { super(NOT_LATEST); this.name = "NotLatestError"; } }
  export async function isLatestCard(projectId: string, systemId: string): Promise<boolean>   // platformClient.latestVersion(projectId)?.pid === systemId
  export async function assertLatestCard(projectId: string, systemId: string): Promise<void> // throws NotLatestError
  ```
  It imports `platformClient` from `@/server/services/PlatformClient` (the tests mock that module).
- `src/server/services/OntologyService.ts`: in `patchNode` and `resetPatch`, right after the card is
  read and before any build or write, `await assertLatestCard(projectId, q.systemId)`. `build` is
  not guarded (reading an old card must keep working; it writes only `knowledge_graph`).
- `src/app/api/qualifications/[id]/extracted/route.ts` PUT: after `cardSummary`, return
  `NextResponse.json({ error: NOT_LATEST }, { status: 403 })` when `!(await isLatestCard(project,
  exists.systemId))`, before parsing or writing (check that `cardSummary` selects `systemId`; add it
  if not). The `fill` route (`api/qualifications/[id]/fill/route.ts`) gets the same 403.
- `src/app/p/[project]/qualify/new/actions.ts`: remove the `CardExistsError` import and branch. An
  error whose message matches `/did not answer/i` returns exactly
  `{ error: "The platform did not answer; nothing was saved" }`; other `could not name this
  system|PLATFORM_URL` errors return `err.message`. Do not touch `QualifyForm.tsx` (other session).
- `scripts/seed_mcas.mjs`: `systemForProject(project, options)` makes one
  `POST ${platform}/projects/{project}/system-versions` with body
  `{name: QUALIFICATION.systemName, version: QUALIFICATION.systemVersion, provider: QUALIFICATION.company, description: QUALIFICATION.description}`
  and returns `{projectId: v.project_id, systemId: v.pid}`. Delete `freezeForCard` and its call in
  `seedMcas`. `seedMcas` still names the version only when it is about to write the card.
- Pages (705a288's screens kept; manual checks in 04):
  - `src/app/p/[project]/system/page.tsx`: no version: "No AI card yet" and a link "Edit the AI
    system" (`/p/{project}/system/edit`); latest version without a card: "v{N} has no card yet"
    and the same link; otherwise the latest card (link or redirect to `/p/{project}/qualify/{id}`;
    group F adds the drift banner here, so render a page, not a redirect).
  - `src/app/p/[project]/system/edit/page.tsx`: prefill from `startingPoint`; Save makes the next
    version (unchanged flow through `submitQualification`).
  - `src/app/p/[project]/qualifications/page.tsx` ("Versions"): `v{number}`, `created_by`,
    `created_at`, highest first, from `listVersions`.
  - `src/app/p/[project]/qualify/[id]/page.tsx`: when `standing.current` is false, show
    "v{N}, kept as it was" with a link to the latest card, and render no edit, fill, patch or
    component controls.

### D6. Rewrite the old freeze-model tests (F8)

`test/unit/cardSubmission.test.ts`, `test/unit/PlatformClient.test.ts`,
`test/unit/cardVersions.test.ts`, `test/unit/seedMcas.test.ts`: delete the cases about `aiSystem`,
`versionForNewCard`, `freeze`, `freezeForCard`, `frozen_at`, drafts and `CardExistsError`; in the
remaining cases change fakes to the new method names and row shape; keep their assertions. Do
not weaken the new files of 4440c4e.

### D7. Checkpoint D

Commands: Q-unit; Q-db; GUARD.

Turns green:
- `test/unit/cardVersionsInCoreSystem.test.ts`: every test (S3.1 x7 incl. the 2 already green,
  S3.2, S3.3, S3.6 x3);
- `test/unit/onlyLatestCardChanges.test.ts`: every test (S3.3 x3; S3.4 x2 stay green);
- `test/unit/seedMcasVersions.test.ts`: every test;
- `test/db/cardVersions.db.test.ts`: every test (catalog block: S3.7 FK, S3.1 unique index, S3.3
  function and triggers, S3.7 no DELETE trigger, WP3 step 6 columns, S3.3 refusal; behaviour block:
  S3.3 x4, S3.3/S3.4, WP3 step 6 CHECK, S3.7 cascade).

Q-unit stays at 385 passed plus the new ones, except the engineComponents (group F) and
systemVersionOntologyRoute (group G) files; tsc clean.

Commit (apps/qualification): `Saving the AI card makes the next card version, and only the latest changes`
(files: the new migration, `prisma/schema.prisma`, `PlatformClient.ts`, `cardVersions.ts`,
`QualificationService.ts`, `cardLatest.ts`, `OntologyService.ts`, the extracted and fill routes,
`qualify/new/actions.ts`, the four pages, `scripts/seed_mcas.mjs`, the four rewritten tests).
Never stage `QualifyForm.tsx`, `next.config.ts` or the prefill files.

---

## Group E: migration-order check (WP4, no code)

### E1. Checkpoint E

Everything it needs is in groups A, C, D. Commit first (the guard reads HEAD), then:

```
cd /home/listuser/aisc-install
scripts/guard-frozen.sh --orders          # expect S4.1 PASS, S4.2 PASS, S4.3 PASS, S4.4 PASS
uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests/test_guard_frozen.py -k s4_
```

Turns green: `scripts/tests/test_guard_frozen.py::test_s4_1_every_order_gives_the_reference_engine_schema`,
`::test_s4_2_core_and_qualification_schema_identical_across_orders`,
`::test_s4_3_mcas_card_and_version_survive_every_order`,
`::test_s4_4_unowned_core_system_fails_only_at_0003_then_recovers`.

If S4.2 differs between orders, diff `$GUARD_OUT/core-qual.order-*.sql`; the usual cause is an
object made only in one order (fix it in the migration that makes it, idempotently). No commit
unless a fix was needed (then in the repo of the migration fixed).

---

## Group F: card agent deployed, components linked by AIRO (WP6)

### F1. 6a compose (top level, file edit only)

`docker-compose.development.yml`, after `qualification-llm`:

```yaml
  # The card agent: drafts the prose-fed nodes of an AI card (techniques, components) through the
  # LLM sidecar, and publishes the draft to qualification-web.
  qualification-agents:
    build: apps/qualification/services/agents
    image: aisc-qualification-agents:latest
    pull_policy: never
    container_name: qualification-agents
    environment:
      LLM_SERVICE_URL: http://qualification-llm:4000
      BAF_LLM_BASE_URL: http://qualification-llm:4000
      ONTOLOGY_SERVICE_URL: http://qualification-ontology:8011
      APP_URL: http://qualification-web:3000/qualification
    restart: unless-stopped
    networks:
      - backend
```

(`LLM_SERVICE_URL` is what 03 and the test name; `fill/llm.py` reads `BAF_LLM_BASE_URL`, so both
are set: a taste call, named here.) In `qualification-web.environment` add
`AGENT_SERVICE_URL: http://qualification-agents:8012` (the port in `services/agents/Dockerfile`).
Stage with `git add -p`.

Turns green: `scripts/tests/test_compose.py::test_s6a_qualification_agents_service`,
`::test_s6a_qualification_web_reaches_the_agents`; `::test_s6a_compose_config_is_valid` stays green.
Command: TOP `-k s6a`.

Commit (top level): `The card agent runs beside qualification, and qualification can reach it`.

### F2. 6b apps/qualification TypeScript

- New `src/domain/cardComponents.ts`:
  `type AiroProperty = "hasModel" | "hasTrainingData" | "hasTestingData" | "hasValidationData" | "hasComponent"`;
  `defaultProperty(type)` (`model`, `llm` to `hasModel`; `dataset` to `hasTestingData`; anything
  else `hasComponent`); `propertyOptions(type)` (`dataset`: `["hasTestingData", "hasTrainingData",
  "hasValidationData"]`; `model`/`llm`: `["hasModel"]`; else `["hasComponent"]`);
  `componentDrift(linked, engine)` returns `{removed, added, changed}`: `removed` are linked rows
  whose `componentPid` is not an engine pid; `added` are engine components not linked; `changed`
  are engine components with a linked row of the same pid whose `componentType` differs from
  `component_type` or `objectName` differs from `data`. Pure: never mutates its inputs.
- New `src/server/services/EngineClient.ts`:
  `new EngineClient(baseUrl = process.env.AISC_BACKEND_URL ?? "", fetchImpl = fetch, callerToken = callerToken)`;
  `components(platformProjectPid)`: GET
  `${base}/api/v1/projects?platform_project_id=${encodeURIComponent(pid)}` with
  `headers.Authorization = "Bearer <token>"`; an empty list returns `[]` without a second call;
  else GET `${base}/api/v1/projects/${first.pid}/aisystem` (same headers) and return its
  `components`. A thrown fetch rejects with `new Error("The engine did not answer")`; a non-2xx
  rejects with "The engine answered <status>". No `method:` other than GET anywhere in the file.
- `src/server/repositories/QualificationRepository.ts`: `find` and `list` include
  `components: { orderBy: { linkedAt: "asc" } }`; `QualificationWithAnswers` gains
  `components: CardComponent[]`; new `linkComponent(qualificationId, {componentPid, airoProperty,
  name, componentType, objectName})` (upsert on `qualificationId_componentPid`) and
  `unlinkComponent(qualificationId, componentPid)` (deleteMany).
- `src/server/services/QualificationExporter.ts`: `QualificationExport.engineComponents:
  {pid, name, componentType, objectName, property}[]`, filled from `q.components ?? []`
  (`pid: componentPid, property: airoProperty`).
- New `src/app/p/[project]/qualify/[id]/component-actions.ts` ("use server"):
  `linkComponent(projectId, qualificationId, componentPid, airoProperty)` and
  `unlinkComponent(projectId, qualificationId, componentPid)`: read the card through the project,
  `assertLatestCard`, check `airoProperty` is in `propertyOptions(type)`, snapshot `name`,
  `component_type`, `data` from `EngineClient.components`, write, `revalidatePath`. Errors return
  `{ok:false, error}`.
- New `src/app/p/[project]/qualify/[id]/ComponentsPanel.tsx`, shown on the latest card's page
  only: the engine components with a property select pre-set by `defaultProperty`, "Link" /
  "Unlink", the filler's free-text components listed as "suggestions" (never auto-linked), and
  "The engine did not answer" when `components()` rejects (the card still renders).
- 6c: `src/app/p/[project]/system/page.tsx` computes `componentDrift(latestCard.components,
  engineComponents)`; any drift shows a banner listing removed, added and changed, with a link
  "Start the next version" to `/p/{project}/system/edit`; engine down: no banner, no claim.

### F3. 6b ontology service (Python, apps/qualification/services/ontology)

- `airo_min/schema.py`: `CLASSES` gains `"AIModel": "AIComponent"` and `"Data": "AIComponent"`;
  `PROPERTIES` gains `"hasModel": ((), "AIModel")`, `"hasTrainingData": ((), "Data")`,
  `"hasTestingData": ((), "Data")`, `"hasValidationData": ((), "Data")` (airo.ttl declares no
  domain for them). airo.ttl is not touched (G3).
- `airo_min/build.py`, in `build_graph` after the prose-derived loop:
  ```python
  COMPONENT_RANGE = {"hasModel": "AIModel", "hasTrainingData": "Data", "hasTestingData": "Data",
                     "hasValidationData": "Data", "hasComponent": "AIComponent"}
  for entry in qualification.get("engineComponents") or []:
      prop = entry["property"]
      node = add_individual(g, URIRef("urn:aisc:component:" + entry["pid"]),
                            COMPONENT_RANGE[prop], entry.get("name"))
      g.add((node, QUAL.objectName, Literal(entry.get("objectName", ""))))
      link(g, system, prop, node)
  ```
  An unknown property raises (KeyError is fine; a ValueError with the property name is nicer).
- Check that `app.py` passes the whole qualification dict to `build_graph` (so `engineComponents`
  arrives) and that `validate.py` accepts `qual:objectName`; adjust only if a test says so.

### F4. Test fix (faithful, see the contradiction table)

`services/ontology/tests/test_schema.py`: `len(CLASSES) == 21`, `len(PROPERTIES) == 23`,
`len(SUBCLASS_EDGES) == 8`, and update the docstring/comment that says "19". VAIR has no term
under `airo:AIModel` or `airo:Data` (checked), so `test_vair_terms.py` counts do not move; if any
other count test moves, stop and report it rather than editing it.

### F5. Checkpoint F

Commands: Q-unit; Q-py for `ontology` (and `agents` to keep
`tests/test_service.py::test_a_failed_run_says_so_rather_than_vanishing` green); GUARD (G3 runs
`tests/test_vendored.py`).

Turns green:
- `test/unit/engineComponents.test.ts`: every test (S6.6 x3, S6.3, S6.1 x3, S6.2 x5);
- `services/ontology/tests/test_engine_components.py`: `test_s6_1_linked_components_are_airo_edges_from_the_system`,
  `test_s6_1_each_component_node_is_typed_by_the_property_range`,
  `test_s6_1_each_component_node_carries_its_name_and_object_name`,
  `test_s6_1_the_jsonld_parses_back_to_the_same_triples`,
  `test_s6_1_other_component_types_map_to_their_range`,
  `test_s6_1_schema_has_the_component_sub_properties[hasModel-AIModel|hasTrainingData-Data|hasTestingData-Data|hasValidationData-Data]`;
  `test_s6_1_without_engine_components_the_graph_is_unchanged` stays green;
- `services/ontology/tests/test_schema.py`: all green with the new counts.

Commits (apps/qualification): `A card links the engine's components through AIRO, and shows drift`
(TS files) and `The AIRO graph carries the engine components a card links` (ontology Python and
the test_schema counts).

---

## Group G: control objectives from the latest version's card (WP7)

### G1. apps/qualification: route `src/app/p/[project]/api/system-versions/[systemPid]/ontology.jsonld/route.ts` (new)

```ts
export async function GET(_req: Request, { params }: { params: Promise<{ project: string; systemPid: string }> }) {
  const { project, systemPid } = await params;
  const access = await fetchAccess(project, await callerToken(), { platformUrl: process.env.PLATFORM_URL ?? "" });
  if (!access?.role) return new NextResponse("Not found", { status: 404 });
  const card = await prisma.qualification.findUnique({ where: { systemId: systemPid },
    select: { id: true, projectId: true, systemId: true, systemName: true, systemVersion: true } });
  if (!card || card.projectId !== project) return new NextResponse("Not found", { status: 404 });
  try {
    const { document } = await knowledgeGraphStore.deliver(card.id, "jsonld",
      () => ontologyService.build(card.projectId, card.id));
    return new NextResponse(document, { headers: {
      "Content-Type": "application/ld+json; charset=utf-8", "Cache-Control": "no-store" } });
  } catch (err) {
    return new NextResponse(`Could not produce the knowledge graph: ${err instanceof Error ? err.message : "unavailable"}`, { status: 502 });
  }
}
```

`{project}` is the platform pid (control-objectives sends `latest.project_id`). Turns green:
`test/unit/systemVersionOntologyRoute.test.ts`: every test (S7.3 x5, S7.5). Command: Q-unit.
Commit (apps/qualification): `Control objectives can read the AI card of one version`.

### G2. apps/control-objectives: Alembic revision `alembic/versions/20260923210000_an_assessment_is_of_one_system_version.py` (new)

`revision = '4d2a9c1e7b60'`, `down_revision = '3b91d0e7a52c'`.

```python
def upgrade() -> None:
    op.execute("ALTER TABLE project ADD COLUMN system_id uuid")
    op.execute("""
        UPDATE project p SET system_id = (
          SELECT s.pid FROM core.system s WHERE s.project_id = p.project_id
           ORDER BY s.number DESC LIMIT 1)""")
    op.execute("""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM project WHERE system_id IS NULL) THEN
            RAISE EXCEPTION 'an assessment has no system version to belong to; assessments are never deleted';
          END IF;
          IF EXISTS (SELECT 1 FROM project GROUP BY system_id HAVING count(*) > 1) THEN
            RAISE EXCEPTION 'two assessments would belong to one system version; keep one first';
          END IF;
        END $$;""")
    op.execute("ALTER TABLE project ALTER COLUMN system_id SET NOT NULL")
    op.create_unique_constraint("uq_project_system_id", "project", ["system_id"])
    op.create_foreign_key("fk_project_system_id_core_system", "project", "system",
                          ["system_id"], ["pid"], referent_schema="core", ondelete="CASCADE")
    op.execute("DROP INDEX IF EXISTS ix_project_qualification_id")
    op.drop_column("project", "qualification_id")
    op.drop_column("project", "system_name")

def downgrade() -> None:
    op.add_column("project", sa.Column("system_name", sa.Text(), nullable=False, server_default=""))
    op.add_column("project", sa.Column("qualification_id", sa.Text(), nullable=False, server_default=""))
    op.create_index("ix_project_qualification_id", "project", ["qualification_id"])
    op.drop_constraint("fk_project_system_id_core_system", "project", type_="foreignkey")
    op.drop_constraint("uq_project_system_id", "project", type_="unique")
    op.drop_column("project", "system_id")
```

(The search_path of `alembic/env.py` is `control_objectives, core`. The whole upgrade is one
transaction, so a RAISE leaves the table as it was: the S7 data tests check that.)

### G3. apps/control-objectives code

- `src/aisc_control_objectives/db/tables.py`: external `core_system = Table("system", Base.metadata,
  Column("pid", UUID(as_uuid=False), primary_key=True), schema="core", info={"external": True})`;
  `Project.system_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("core.system.pid",
  ondelete="CASCADE"), nullable=False, unique=True)`; remove the `system_name` and
  `qualification_id` columns.
- `db/repository.py`: `ProjectRecord` gains `system_id`, `version_number`, `latest_number`;
  `system_name` and `qualification_id` stay on the record but come from the stored ontology.
  `create(project, name, ontology, jsonld, *, system_id)`; new `find_by_system(system_id) ->
  ProjectRecord | None`; `_to_record` reads the numbers with
  `SELECT s.number, (SELECT max(o.number) FROM core.system o WHERE o.project_id = s.project_id)
  FROM core.system s WHERE s.pid = :sid`; new `is_latest(record) -> bool`
  (`version_number == latest_number`).
- `projects.py`: `Projects.create(project, name, jsonld, raw, system_id)`; drop `replace_card`.
- New `src/aisc_control_objectives/upstream.py` (httpx; move `httpx>=0.27` from the dev extra to
  `dependencies` in `pyproject.toml` and run `uv lock --offline`; httpx is already in `uv.lock`):
  ```python
  class UpstreamDown(Exception): ...
  def latest_version(project: str, authorization: str | None) -> dict | None
      # GET {PLATFORM_URL}/projects/{project}/system-versions/latest, Authorization forwarded
      # verbatim; 200 -> the JSON (None for null); anything else or a transport error -> UpstreamDown
  def card_jsonld(project: str, system_pid: str, authorization: str | None) -> str | None
      # GET {QUALIFICATION_URL}/p/{project}/api/system-versions/{system_pid}/ontology.jsonld;
      # 404 -> None; 200 -> response.content.decode("utf-8") (the served bytes); else UpstreamDown
  ```
  Both read the env at call time; unset env is `UpstreamDown`.
- `api/app.py`:
  - `POST /p/{project}/projects` (form, no file): `auth = request.headers.get("authorization")`;
    `latest = upstream.latest_version(project, auth)` (UpstreamDown: 502 plain text); None: 409
    "No AI card for the latest version yet"; `existing = repository.find_by_system(latest["pid"])`:
    303 to it; `jsonld = upstream.card_jsonld(latest["project_id"], latest["pid"], auth)`
    (UpstreamDown: 502; None: 409 same text); `raw = json.loads(jsonld)` (not a card: 502);
    `view = projects.create(project, name, jsonld, raw, latest["pid"])`; on IntegrityError
    (a concurrent start) 303 to `find_by_system`; else 303 to the new one. Nothing is stored on
    any error path.
  - `POST .../{project_id}/map` and `.../severity`, and their JSON twins under `/api/projects/`:
    409 "read-only: v{latest} is the latest" when `not repository.is_latest(record)`.
  - Remove `POST /api/projects` and `POST /api/projects/{project_id}/card` (and `CARD_WANTED` if
    unused).
- `rendering.py` and the templates: the projects page has a "Start assessment" form (a submit
  button and the name field, no `type="file"`); the assessment page shows "Assessment of v{N}";
  when not latest, "read-only: v{M} is the latest" replaces the map and severity forms (no
  `/projects/{id}/map` or `/severity` in the page).

### G4. Compose (top level, file edit only)

`control-objectives` service environment: `QUALIFICATION_URL: http://qualification-web:3000/qualification`
and `PLATFORM_URL: http://platform:8000` (if not already there). Stage with `git add -p`. Manual
check only (no test).

### G5. Rewrite the old upload tests (F8)

`tests/test_projects.py`, `tests/test_repository.py`,
`tests/test_project_access.py::test_an_editor_gets_past_the_door`: make assessments with
`repository.create(..., system_id=system_version(platform_project, n))` or
`Projects.create(..., system_id)` (one version per assessment: `system_id` is unique), and delete
the cases whose subject is the removed upload routes (`POST /api/projects`, `/card`, "not JSON",
"not an AI card", replace-card). Keep the listing, rating, mapping and access assertions.

### G6. Checkpoint G

Commands: CO on T; Q-unit; GUARD.

Turns green:
- `tests/test_assessment_of_a_version.py`: every test (S7.1, S7.2 x3, S7.4, S7.5, S7.6 x2, S7.7,
  the 409 x2, 502 x2, Authorization, start button, routes removed, upstream x3; S7.3 stays green);
- `tests/test_migration_assessment_of_a_version.py`: every test
  (`test_s7_data_backfills_the_latest_version_and_drops_the_old_link`,
  `test_s7_data_refuses_an_assessment_with_no_version`,
  `test_s7_data_refuses_two_assessments_on_one_version`,
  `test_s7_6_after_the_migration_deleting_the_version_deletes_the_assessment`,
  `test_the_revision_follows_the_live_head`);
- the 220 existing tests, less the deleted upload cases, stay green.

Commits: apps/control-objectives `An assessment is of the latest saved AI card version, read from qualification`;
top level (compose hunk) `Control objectives knows where qualification and the platform are`.

---

## Group H: answers carry the system version (WP10) and the dashboard reads controls (WP11 grant)

### H1. apps/controls migrations (new)

`prisma/migrations/20260923210000_answers_carry_the_system_version/migration.sql`:

```sql
ALTER TABLE "submission_answer"
  ADD COLUMN "system_version_pid" UUID,
  ADD COLUMN "system_version_number" INTEGER,
  ADD COLUMN "answered_at" TIMESTAMPTZ(3);
```

`prisma/migrations/20260923210100_dashboard_reads_controls/migration.sql`:

```sql
GRANT SELECT ON ALL TABLES IN SCHEMA controls TO dashboard_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE controls_rw IN SCHEMA controls GRANT SELECT ON TABLES TO dashboard_ro;
```

`prisma/schema.prisma` `SubmissionAnswer` gains
`systemVersionPid String? @map("system_version_pid") @db.Uuid`,
`systemVersionNumber Int? @map("system_version_number")`,
`answeredAt DateTime? @map("answered_at") @db.Timestamptz(3)`. Run `npx prisma generate`.
`prismaFor` already migrates a project DB on first open (`migrate deploy`), which gives S10.4.

### H2. `src/lib/systemVersion.ts` (new)

```ts
export async function latestVersion(pid: string, token: string | null): Promise<{ pid: string; number: number } | null> {
  const base = (process.env.PLATFORM_URL ?? "").replace(/\/+$/, "");
  if (!base) return null;
  try {
    const res = await fetch(`${base}/projects/${encodeURIComponent(pid)}/system-versions/latest`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {}, cache: "no-store",
      signal: AbortSignal.timeout(3000) });
    if (!res.ok) { console.warn(`platform answered ${res.status} for the latest version of ${pid}`); return null; }
    const body = await res.json();
    return body ? { pid: body.pid, number: body.number } : null;
  } catch (err) {
    console.warn(`platform did not answer for the latest version of ${pid}`, err);
    return null;
  }
}
```

### H3. `src/app/p/[project]/submissions/[id]/actions.ts`

- `saveDraft`: before the transaction, read the old rows
  (`prisma.submissionAnswer.findMany({ where: { submissionId } })`) by `questionId`. For each new
  row: if an old row has the same `answer` and `score`, copy its `systemVersionPid`,
  `systemVersionNumber` and `answeredAt`; otherwise set `answeredAt: new Date()` and the latest
  version (`latestVersion(project, await callerToken())`, asked once, and only when at least one
  row is new or changed), or NULLs. Keep deleteMany plus createMany in one `$transaction`.
- `reopenForAmendment`: copy the three fields with each answer.
- Submission page (`src/app/p/[project]/submissions/[id]/page.tsx` or its view component): per
  answer "answered under v{N}" or "not stamped"; in the header the distinct versions (manual).

### H4. Checkpoint H

Command: CTL on T (only those paths, F1); GUARD.

Turns green:
- `test/unit/systemVersion.test.ts`: every test (S10.1 x2, null, S10.2 x3);
- `test/integration/answer-stamps.test.ts`: every test (migration there, three columns, S10.1 x2,
  S10.2, S10.3, S10.4, S10.5);
- `test/integration/dashboard-grants.test.ts`: every test (migration there, SELECT and nothing
  more, default privileges);
- `test/integration/install-once-throwaway.test.ts::S8.3` stays green.

Commits (apps/controls): `Each answer carries the AI card version it was answered under` and
`The dashboard may read this project's controls, and only read them`.

---

## Group I: one-click install, same UX for tests and controls (WP8)

### I1. apps/catalogue/frontend

- `src/crossSite/connect.ts`: `dispatchInstall(targetEnv: string | null, entries: InstallEntry[], project?: string | null)`.
  Use `targetEnv` only when `/^https?:\/\//i.test(targetEnv)` (so `javascript:` and `//host` fall
  back to `window.open(uri)`); add `project=<encodeURIComponent(pid)>&` before `uri=` only when it
  matches the PID regex of `controlsInstall.ts` (export that regex from one place and import it).
  URL shape: `${targetEnv}/receiver?project=<pid>&uri=<encoded enable URI>`, or
  `${targetEnv}/receiver?uri=...` without a project.
- `src/crossSite/InstallPluginButton.tsx`: props gain `project?: string | null` and
  `style?: React.CSSProperties`; default label "Install into a project…"; pass `project` to
  `dispatchInstall`; the anchor uses the given style.
- `src/components/catalogue/ToolDetailModal.tsx`: render `<InstallPluginButton ... project={handshake?.project}
  style={styles.actionBtn(false)} />` so the test and control anchors carry the same style
  attribute and the same label.

### I2. Test fix

`src/components/catalogue/ToolDetailModal.test.tsx` "offers the enable once the index has a
version": look for the link named /install into a project/i instead of "Enable plugin".

### I3. apps/webapp

- `src/pluginCatalogue/PluginInstallContext.tsx`: at module load, before `replaceState` strips the
  URL, read `project` from `window.location.search`; when it matches the PID regex, store it with
  the existing `currentPlatformProject` helper of `src/platform/currentProject.ts`
  (sessionStorage `aisc_platform_project`).
- `src/components/PluginInstallDialog.tsx`: after `GET /api/v1/projects?platform_project_id=<pid>`:
  one result is preselected; none: `POST /api/v1/projects/for-platform/<pid>` and preselect its
  result. Then `GET /api/v1/projects/{enginePid}`; if `plugins[]` has the same `package_name` and
  `version`, show "Already installed in <name>" and the primary button becomes "Open plugins"
  (navigates to the plugins page). An install answered 403 shows the toast "Installing a test
  takes the admin role". Use `fetch` with the existing `API_URL` and auth helper of the dialog;
  do not edit `src/api/api.tsx` (Sean's).

### I4. Checkpoint I

Commands: CAT; WEB; GUARD (G4 webapp must stay PASS).

Turns green:
- `frontend/src/crossSite/wp8OneClickInstall.test.tsx`: every test (S8.4 x5, S8.1 x4);
- `frontend/src/components/catalogue/ToolDetailModal.test.tsx`: all, with the label fix;
- `src/components/PluginInstallDialog.wp8.test.tsx`: every test (S8.1 x4, S8.2 x2, S8.5, and the
  PluginInstallContext S8.1);
- WEB: 0 failures, tsc 0 errors (S13.3).

Commits: apps/catalogue `Tests and controls install with the same button, into the project the catalogue came from`;
apps/webapp `The install dialog opens on the catalogue's project and says when a test is already there`.

---

## Group J: dashboard, visualise and comment (WP11)

### J1. Platform template `platform/project-template/0002_dashboard.sql` (new, runs as platform_rw)

```sql
-- The dashboard reads this project's answers as dashboard_ro: it may connect and look into the
-- controls schema. The SELECT on the tables is granted by controls' own migration, because
-- controls_rw owns them (D5).
DO $grant$
BEGIN
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO dashboard_ro', current_database());
END
$grant$;
GRANT USAGE ON SCHEMA controls TO dashboard_ro;
```

### J2. Platform bridge calls

- New `platform/platform_service/dashboard_bridge.py`: `register(pid, slug, name) -> bool` and
  `unregister(pid) -> bool`. URL `${DASHBOARD_BRIDGE_URL}/api/v1/aisc_project/<pid>`, methods
  POST (JSON body `{slug, name}`) and DELETE, header `X-AISC-Bridge-Token: $DASHBOARD_BRIDGE_TOKEN`,
  `urllib.request.urlopen(..., timeout=5)`. No `DASHBOARD_BRIDGE_URL`: return True, do nothing.
  Any exception: `logger.warning(...)`, return False. Never raises.
- `platform/platform_service/app.py`: `add_project` calls `dashboard_bridge.register(...)` after
  `projectdb.provision` succeeded; on False, `db.remember_unregistered(pid)`. `remove_project`
  calls `dashboard_bridge.unregister(found["pid"])` before `projectdb.drop(...)` (call
  `projectdb.drop` through the module, as now, so the test's monkeypatch sees the order).
- `platform/platform_service/db.py`: a module set `_unregistered: set[str]`, `remember_unregistered`,
  and in `provision_all`: on its first run after start (or `reset()`), register every project it
  provisions (select `pid, slug, name`); on later runs, retry `_unregistered`. `_setup_pending`
  is also true when `_unregistered` is non-empty and `RETRY_SECONDS` passed. `reset()` clears it.
- Compose (top level, file edit, `git add -p`): `platform` gets
  `DASHBOARD_BRIDGE_URL: http://dashboard:8088` (service `dashboard` of
  `docker-compose.development.yml`; 8088 is Superset's default port, check the service's command
  or healthcheck before using it) and
  `DASHBOARD_BRIDGE_TOKEN: ${DASHBOARD_BRIDGE_TOKEN:-}`; the dashboard gets the same token
  variable. Never write a real token into a file; do not read env.secrets.

Turns green (PLAT on T): `platform/tests/test_dashboard_bridge.py`: every test
(`test_wp11_the_dashboard_may_connect_to_a_project_database_and_use_its_controls_schema`,
`test_wp11_the_dashboard_still_writes_nothing_in_a_project_database`,
`test_s11_5_making_a_project_registers_it_with_the_dashboard_bridge`,
`test_s11_5_deleting_a_project_unregisters_it_before_its_database_is_dropped`,
`test_s11_5_a_bridge_that_hangs_is_given_up_on_after_about_5_seconds`,
`test_s11_5_a_failed_registration_is_retried_by_provision_all`; the "down" test stays green).

Commit (top level): `A project's dashboard is made with the project and removed before its database`.

### J3. apps/results-dashboard

- New `aisc_ext/projects.py` (no Superset import at module level):
  - `_PID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")`;
    `_pid(value)` normalises `str(value).lower()` and raises `ValueError` unless it matches;
    `_hex(pid)`.
  - `project_role_name(pid) -> f"AiscProject_{hex}"` (accepts `uuid.UUID`).
  - `engine_results_sql(pid)`: exactly the SQL of `scripts/pipeline_chain/test_dashboard_queries.py`
    `ENGINE_RESULTS_SQL` (with `WHERE p.project_id = '<pid>'`, F2), pid validated first.
  - `controls_answers_sql()`: exactly `CONTROLS_ANSWERS_SQL` of the same file.
  - `MEMBER_PROJECTS_SQL = "SELECT project_id FROM core.project_member WHERE subject = %(subject)s"`
    (no trailing semicolon: the DB test appends one).
  - `register_project(pid, slug, name, *, store, controls_password)`: upserts, each spec tagged
    `"aisc_project": pid`: database `"AISC Controls <slug>"` with
    `sqlalchemy_uri = f"postgresql+psycopg2://dashboard_ro:{controls_password}@postgres:5432/project_{hex}"`
    and `allow_dml: False`; datasets `engine_results_<hex>` (`database: "AISC Results"`, `sql`) and
    `controls_answers_<hex>` (`database: "AISC Controls <slug>"`, `sql`); role
    `AiscProject_<hex>` with `permissions = [("datasource_access", "engine_results_<hex>"),
    ("datasource_access", "controls_answers_<hex>"), ("database_access", "AISC Controls <slug>")]`;
    dashboard `aisc-<hex>` with `roles = [AiscProject_<hex>]` and `charts = [{"kind": "line",
    "dataset": "engine_results_<hex>", "by": "system_version", "metric": "score"}, {"kind": "table",
    "dataset": "controls_answers_<hex>", "by": "system_version_number"}]`. Idempotent (upsert by key).
  - `unregister_project(pid, *, store)`: for every kind, delete each key whose spec has
    `aisc_project == pid`; unknown pid is a no-op.
  - `authorize_bridge(headers, env) -> int | None`: `expected = env.get("DASHBOARD_BRIDGE_TOKEN") or ""`;
    `given = headers.get("X-AISC-Bridge-Token") or ""`; 401 when `expected` is empty or
    `not hmac.compare_digest(given, expected)` (call it as `hmac.compare_digest`, the test patches
    the module attribute); else None.
  - `SupersetStore` (runtime only, imports Superset inside its methods): upsert/delete/items over
    `Database`, `SqlaTable`, FAB roles and `Dashboard`.
- New `aisc_ext/project_bridge_api.py`: `class ProjectBridgeApi(BaseApi)` with
  `resource_name = "aisc_project"` (this exact text), `POST /<pid>` and `DELETE /<pid>` that call
  `authorize_bridge(request.headers, os.environ)` then `register_project` / `unregister_project`
  with `SupersetStore()` and `controls_password=os.environ.get("DASHBOARD_RO_PASSWORD", "dashboard_ro")`;
  exempt from CSRF (token-authenticated, not cookie).
- `aisc_ext/security.py`: `roles_for_login(realm_roles, member_project_pids) -> list[str]`:
  `map_keycloak_roles(realm_roles)` followed by `project_role_name(p)` for each pid, without
  duplicates, in order (import `project_role_name` from `aisc_ext.projects`).
- `aisc_ext/sso.py`: `auth_user_oauth` reads the subject's projects with `MEMBER_PROJECTS_SQL` over
  the `dashboard_ro` results connection and uses `roles_for_login` instead of
  `map_keycloak_roles`.
- `superset_config.py` (has W4's uncommitted hunks: stage only yours with `git add -p`):
  `"DASHBOARD_RBAC": True` in `FEATURE_FLAGS`; in `FLASK_APP_MUTATOR`, `add_api(ProjectBridgeApi)`
  next to `CommentApi`.

Turns green (DASH on T): `tests/test_projects.py`: every test; `tests/test_project_bridge.py`:
every test; `tests/test_project_datasets_db.py`: every test (needs groups C and H, and J1 for the
CONNECT test). The 74-test baseline stays (it includes W4's untracked `test_review.py`).

Commit (apps/results-dashboard): `One dashboard per project, readable only by its members, with the version on every row`
(files: `aisc_ext/projects.py`, `aisc_ext/project_bridge_api.py`, `aisc_ext/security.py`,
`aisc_ext/sso.py`, and only your hunks of `superset_config.py`).

### J4. Checkpoint J

Commands: PLAT on T; DASH on T; TOP `-k "test_dashboard_queries or s11_4"` (runs
`scripts/pipeline_chain/test_dashboard_queries.py` standalone); GUARD.

Turns green: `scripts/pipeline_chain/test_dashboard_queries.py::test_s12_1_engine_results_carry_the_version_of_the_evaluation`,
`::test_s12_1_controls_answers_carry_the_version_they_were_answered_under`,
`::test_s11_4_engine_results_never_return_another_projects_rows`.

---

## Group K: pipeline chain test (WP12)

The driver `scripts/test-pipeline-chain.sh` exists; what is missing are the per-module tests it
selects by name (`chain_step<N>`). Each skips itself unless `CHAIN_JSON` is set, reads the ids of
earlier steps from `$CHAIN_JSON` and writes its own keys back (read, update, write the whole
object). Each asserts the link it consumes, so a `--break` fails at the consuming step.

K1. platform: `platform/tests/test_chain.py`, `pytestmark = [pytest.mark.chain, pytest.mark.skipif(no CHAIN_JSON)]`;
register the `chain` marker in `platform/pyproject.toml` `[tool.pytest.ini_options] markers`.
`test_chain_step1_project_and_v1`: through the API (`client`, `as_user`) create a project whose
slug starts `chain-` (never `pytest-`, F14a), then `POST .../system-versions`; write `project_pid`,
`v1_pid`. `test_chain_step6_v2`: `POST .../system-versions` again; assert number 2; write `v2_pid`.

K2. qualification: `test/chain/chain.test.ts` (included by the vitest config, skipped without
`CHAIN_JSON`), `it("chain_step2 card v1 with 2 card_component rows")`: with Prisma on
`DATABASE_URL`, create the card for `v1_pid` and two `card_component` rows (a model and a dataset);
assert `qualification_system_id_fkey` exists and points at `core.system` (consumes
`qualification_fk`); write `card_v1_id`.

K3. engine: `aisc_backend/tests/test_chain.py`, `@tag("chain")` on a plain `unittest.TestCase`
(not Django's TestCase: then `manage.py test` makes no test database and the ORM uses the
throwaway `platform` DB, F14c), skipped without `CHAIN_JSON`. `test_chain_step4_plugin_and_stamped_evaluation`:
get or create the engine project for `project_pid`, a `Plugin` with `catalogue_slug`, an
`Evaluation` created through the ORM (so the WP9 signal stamps it), one `Observation` and one
`Measurement`; assert `system_id == v1_pid`; write `plugin_id`, `evaluation_pid`.

K4. control-objectives: `tests/test_chain.py` with the `chain` marker (register it in
`pyproject.toml`), skipped without `CHAIN_JSON`. It must NOT use the `repository` fixture (F14b):
build `ProjectRepository(os.environ["CONTROL_OBJECTIVES_TEST_DATABASE_URL"])` directly.
`test_chain_step3_assessment_on_v1`: stub the platform and qualification with a local HTTP server
(as in `test_assessment_of_a_version.py`), serving a JSON-LD built from the card's two
`card_component` rows (read with `CHAIN_SU_DSN`); assert there are 2 rows (consumes
`card_component`) and that `fk_project_system_id_core_system` exists (consumes `co_fk`); start the
assessment; assert its `system_id == v1_pid`; write `assessment_v1_id`.

K5. controls: `test/chain/chain.test.ts`, skipped without `CHAIN_JSON`, using
`PROJECT_DATABASE_URL` and `CHAIN_*` only (never `docker exec postgres`). `chain_step5`: install a
checklist with `catalogueId` into `project_db`; write `checklist_id`. `chain_step7`: stub the
platform's `/system-versions/latest` with `v2`, save an answer through `saveDraft`, assert its
stamp is v2; write `submission_id`.

K6. Checkpoint K

```
cd /home/listuser/aisc-install
scripts/test-pipeline-chain.sh                                   # CHAIN PASS
for l in qualification_fk co_fk engine_stamp controls_stamp card_component; do
  scripts/test-pipeline-chain.sh --break $l; done                # each: BREAK <l> OK
uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests/test_pipeline_chain.py
```

Turns green: `scripts/tests/test_pipeline_chain.py::test_s12_1_the_full_chain_passes`,
`::test_s12_2_each_break_fails_at_the_step_that_consumes_it[qualification_fk|co_fk|engine_stamp|controls_stamp|card_component]`;
`::test_s12_3_no_container_remains` and `::test_s12_unknown_link_is_refused` stay green. Then
BE-sqlite, PLAT, Q-unit, CO, CTL must still pass (the chain tests skip there).

Commits, one per repo: `The pipeline chain step of <module>`.

---

## Group L: other sessions' work (needs the user, do not do by default)

- WP5: the prefill files (W3) are untracked in apps/qualification, plus hunks in
  `next.config.ts`, `QualifyForm.tsx`, the top-level compose (`qualification-prefill`,
  `PREFILL_URL`) and `scripts/verify.sh`. S5.1 to S5.5 already pass with them in the tree.
  Committing another session's work is the user's call: ask, then commit exactly those files as
  one commit per repo (`The form can start from a document`).
- WP11 11c: W4 (`aisc_ext/review/`, `scripts/verify_review.py`, `tests/test_review.py`, and the
  hunks of `comments/api.py`, `comments/views.py`, `superset_config.py`). Same rule.
- Top-level submodule pointers (`apps/*`) and `scripts/verify-rbac.sh`'s `/systems` call (WP15):
  not in this run; ask.

---

## Integration check (after all groups)

Run everything, each DB suite on its own fresh T (the ids are the suite commands of section 0):

```
cd /home/listuser/aisc-install
scripts/guard-frozen.sh                                  # GUARD PASS (G1..G5)
scripts/guard-frozen.sh --orders                         # S4.1..S4.4 PASS
uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests scripts/pipeline_chain
scripts/test-pipeline-chain.sh                           # CHAIN PASS
(cd platform && PLAT)                                    # on T
(cd apps/backend && BE-sqlite); (cd apps/backend && BE-pg)          # BE-pg on T
(cd apps/qualification && Q-unit && Q-db); Q-py for ontology, prefill, agents
(cd apps/control-objectives && CO)                       # on T
(cd apps/controls && CTL)                                # on T, only those paths
(cd apps/catalogue/frontend && CAT); (cd apps/catalogue/backend && uv run pytest -q -p no:cacheprovider)
(cd apps/webapp && WEB)
(cd apps/results-dashboard && DASH)                      # on T
docker ps -a --filter name=aisc-t- -q                    # prints nothing
git -C shared/plugin-manager status --porcelain          # prints nothing
```

Expected remaining failures, and nothing else:

| suite | expected red | reason |
|---|---|---|
| BE-sqlite / BE-pg | `tests.integration.test_integration` (1 ImportError); `test_keycloak_integration` (3 failures); `test_project_config_router` (3 SynchronousOnlyOperation errors, Sean's file) | F5, frozen or needs Keycloak |
| catalogue `npx tsc --noEmit` (not part of CAT) | 81 pre-existing errors | not ours |
| everything in "Cannot go green" | manual checks listed in 04 | browser, Keycloak, Superset, LLM, live stack |

Skipped by design: the DB-gated qualification file without Q-db; BE Postgres-only tests on
sqlite and sqlite-only ones on Postgres; the dashboard DB tests without
`AISC_DASHBOARD_TEST_PG_CONTAINER`; the chain tests outside the chain; the controls integration
files of F1 (not run at all).

Report to the user: the list of local commits per repo (none pushed), the decision F11 (the
guarded edit of `20260923180000`), the taste calls named in step F1 of group F (`BAF_LLM_BASE_URL`) and J2
(the bridge URL), the group L questions, and the manual checks of 04.

## Orchestrator amendments (binding)

- **B1 (step C5): do not edit an already-applied migration first.** The live qualification DB has
  `20260923180000` applied, and an edited file changes its checksum. First try the alternative: platform 0003
  does NOT drop `core.ai_system_version` (it leaves the unused table and its data for a later cleanup
  migration, applied together with the live runbook), so the old qualification FK stays valid on
  a fresh install. Only if that breaks a spec'd test, fall back to the plan's C5, and record the reason
  in 06-report.md under "Needs the user".
- **B2: group L (committing other sessions' prefill and review-page work) is skipped.** Leave those files
  uncommitted and untouched.
- **B3: progress.** After each group's checkpoint, append a line to 06-report.md (group, commits, tests
  green or red, guard result) so an interruption loses nothing.
