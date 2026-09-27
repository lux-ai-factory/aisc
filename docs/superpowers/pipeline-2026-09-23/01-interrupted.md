# Stage 1: what was interrupted on 2026-09-23

Times are local (CEST, UTC+2). Transcript timestamps are UTC and have been converted.
The usage limit hit at 18:34 local (16:34Z) in session 5d02402e.

Sources used:
- `~/.claude/projects/-home-listuser/5d02402e-...jsonl`. Called "S-versions": the Superset review page, Sean's merge, and the versioned AI system. It was cut by the limit.
- `~/.claude/projects/-home-listuser/048dc13b-...jsonl`. Called "S-prefill": qualification document prefill and the MCAS terms. It was idle after 16:52; its last user message was at 16:46.
- `~/.claude/projects/-home-listuser-macchine-obbedienti/7b89fcaf-347d-4e59-85fc-07be705028ff.jsonl`. Called "S-projdb": one database per project. It is about AISC even though it was started from the macchine-obbedienti folder. It was idle from 17:11, waiting on four user questions. It was not in the brief, but it is the "other session" that S-versions refers to.
- `c95f3e80`: one message ("start aisc mock demo", 17:11). It does not bear on this work, so it is excluded.
- `cda66d96`: an Anthropic key exposure scan (15:58). It is not part of the build, so it is excluded.
- git in every repo, the live DB (read only), the docs, and the memory notes.

## 1. Decisions the user made

| Time (local) | Session | Quote | Status |
|---|---|---|---|
| 14:09 | S-projdb | "one click from catalogue -> write in the controls database -> controls app read from the database" | In force (built, plan 1) |
| 14:14 | S-projdb | "each project should be fully isolated from the others so everything from step 1 qualification to step 6 visualise is fully related to a project and nothing else" | In force as a goal. See the conflicts section: RULES.md now freezes the engine's table placement. |
| 14:19 / 14:20 | S-projdb | "we should have one database per project" / "The only thing that connects them is the homepage, end of the story" | Built for controls only. Plans 2-5 are written but not run. RULES.md FROZEN #1 says engine tables stay where they are, which contradicts plan 4. |
| 14:34 | S-projdb | "the catalogue will be hosted online, so unified. The catalogue is one but you need to say which project you want to install into" | In force (built) |
| 14:39 | S-projdb | "keycloak shared, -> only admin can delete a project and make the admin type the name to delete it -> subagent driven" | In force (built, b30692e) |
| ~16:20 | S-projdb | Approved dropping the shared `controls` schema (17 example checklists, 0 answers) | Done (6a245dc) |
| 16:17 | S-versions | "I want to merge Sean into mine -> giving priority to his changes" | Done (e34fca3 etc.). Now FROZEN in RULES.md. |
| 17:03 | S-versions | "now I want only one system available and one ai card. If the system is edited you create a new version" | **SUPERSEDED** at 18:25-18:32 by "only the card is versioned" |
| (~17:05) | S-versions | "freeze on use" (the latest version is a draft until an evaluation or card uses it), per the memory note | **SUPERSEDED**: no freeze, no copying |
| 17:48 | S-versions | "I still see the old mechanism, where you can create new qualifications instead of editing and versioning one system only" | In force: the qualification screens for "edit the one system" are kept |
| 17:52 | S-versions | "I wanted to use my branch for the merge!!" | In force: work lands on `feat/unified-modules`, not on side branches |
| 18:25 | S-versions | "a project has one system as per sean changes -> ai card is the description of a system and there can be multiple versions of it -> controls objectives are tied to the description of the system -> tests and control are tied to the system itself (only one)" | In force (RULES.md "Decided model") |
| 18:30 | S-versions | "...what if we have a sync mechanism such as the controls and the tests are tied always to the latest version? In the end this has no operational consequences" | Refined at 18:32 into stamping |
| 18:32 | S-versions | "ok so I completely agree with the auditor part. We need to tie each assessment to the system version" | In force: each assessment records the latest card version when it happens (RULES.md) |
| 18:34 | S-versions | "first check what the other claude session was doing to sync the plan in one" | **Interrupted** by the limit. Not started. |
| 13:28 / 13:55 | S-prefill | "I want the risks to be part of the file upload mechanism" / "NO TERM should never appear... Wipe everything out" | Risks: built (uncommitted). "No term": fixed for MCAS only, by a data fix. The general fix (option A or B) was never chosen. |
| 16:46 | S-prefill | "provide for now labels for the ontology" | Done as a live DB data fix on the MCAS qualification (curated terms restored; 0 "no term" nodes) |

## 2. Work streams in flight

### W1. Versioned AI system: freeze-on-use build, then the model corrected (S-versions). Interrupted.
- **Goal now:** apply the corrected model. One unversioned system, only the card versioned, assessments stamp the version, card components link to engine parts via AIRO. The deployed freeze and copy-on-write build is to be undone.
- **Done:** the freeze build is committed on `feat/unified-modules` in four repos (see section 3). It was rebuilt and deployed at about 18:00 and migrated the live DB.
- **Backup:** `~/aisc-install-backup-before-ai-system-versions-20260923.dump`, taken before the deploy.
- **Env change:** S-versions also added `MODEL_LISTING_SSL_VERIFY=False` to `env.runtime`, which is untracked.
- **Uncommitted:** `docs/superpowers/specs/2026-09-23-one-system-versioned-description.md` (123 lines, written 18:33). Its open questions:
  1. Order: rework in the shared DB first, or fold into plans 2-4.
  2. Controls: stamp when a control is answered, or when the checklist is submitted.
  3. Carry control-objective ratings forward to the next version, or start empty.
  4. Does a re-uploaded file count as drift?
- **Next step at cutoff:** reconcile the spec with S-projdb's plans 2-4 ("sync the plan in one").
- **Also pending from S-versions:** a control-objectives redesign to read the card from the DB instead of an upload. It offered options 1/2/3 at 18:22, and no answer was recorded.

### W2. One database per project (S-projdb). Paused, waiting on user answers.
- **Plan 1 (controls + catalogue install):** committed as `docs/superpowers/plans/2026-09-23-project-databases-1-controls.md` in b425374, together with the roadmap. All 11 tasks are done and reviewed, and all 16 final-review findings are fixed. `verify.sh`: 17 ok.
- **Top-level commits:** 065b57f, aac6c47, 366fdc8, e389fa7, 001fa05, d79204d, b624bc5, b30692e, 6a245dc, c8a2637, 1d94aaa.
- **apps/controls commits:** 240712a, 99e2951, 8c06186, c2e68c1, c85be7b, 29be392, 3e76d2b, 35600dc, 2013dec.
- **apps/catalogue commits:** d88da1d, 8dd2fb5, b5da8d8.
- **Plans 2-5, uncommitted:** `plans/2026-09-23-project-databases-{2-qualification,3-control-objectives,4-engine,5-dashboard}.md`.
  - Plan 2 (qualification, 10 tasks) moves `core.system` to `project.system` in each project DB.
  - Plan 3 (control-objectives, 9 tasks) keeps the card upload and several assessments.
  - Plan 4 (engine, 9 tasks) moves every engine table into the project DB, with a Django alias per project DB, an `X-AISC-Project` header and HMAC run tickets.
  - Plan 5 (dashboard, 10 tasks) gives each project its own Superset connection, a bridge and project roles.
- **Plan 6 (retire shared schemas):** only in the roadmap. No plan file exists.
- **Next step:** four questions to the user from 17:10, unanswered:
  1. Is the prefill work in qualification someone else's?
  2. Should the engine plan build on Sean's merge?
  3. Should the dashboard role be a member of every module role, or should each module grant it?
  4. Fix `verify-rbac.sh` and drop 3 empty `project_*` test DBs?
- **Stale gate:** plan 4 gate 2 (`list_openai_models` missing) is now resolved. `shared/plugin-interface` is checked out at 97eddea, which has it.

### W3. Qualification document prefill (S-prefill). Uncommitted.
- **Goal:** uploading a document fills the form: 21 fields plus the risk rows (not tags), with a "fill only the empty ones / replace my answers" choice.
- **Uncommitted in `apps/qualification`:**
  - Modified: `next.config.ts` (11 MB body limit) and `src/app/p/[project]/qualify/new/QualifyForm.tsx` (wiring).
  - New app code: `services/prefill/` (the Python FastAPI reader and its tests), `src/app/p/[project]/qualify/new/DocumentUpload.tsx`, `prefill-actions.ts`, `src/data/prefillFields.json`, `src/lib/prefillChoice.ts`, `src/lib/prefillFlow.ts`, `src/server/services/PrefillClient.ts`.
  - New tests: `test/unit/{DocumentUpload,PrefillClient,formUpload,nextConfig,prefillChoice,prefillFields,prefillFlow}.test.*`.
  - Tests at 13:35: 69 Python, 353 vitest, tsc clean.
- **Uncommitted at top level:**
  - `docker-compose.development.yml` adds the `qualification-prefill` service and `PREFILL_URL: http://qualification-prefill:8012` on qualification-web.
  - `scripts/verify.sh` adds a "qualification prefill" test line.
- **Running:** the live qualification image was built from the files on disk, so it already contains this work.
- **Next step:** commit it. At 13:27 the session asked "Should I make them?" and got no answer.
- **Open items in this stream:**
  - Tags are not read from documents. The save error "Pick at least one market form" (16:40) was not reproduced; the session asked the user for the "N selected" count and got no answer.
  - The "NO TERM" general fix needs option A (a classification section in the document) or option B (build the filler on an LLM, e.g. OpenAI or local ollama). Neither was chosen.
  - The filler agent is not deployed in `aisc-install`.
  - The session offered a pre-commit secret hook and got no answer.
- **Data change (not code):** the MCAS qualification in the live DB (`cmue7pq23000mpv7zew2fghpg`, created 16:42) got curated ontology terms at 16:52. Backups: `~/Downloads/mcas-qualification-backup-2026-09-23{,-b}.json`.

### W4. Superset review page (S-versions, 15:31-15:52). Uncommitted.
- **Goal:** Keycloak users comment beside a dashboard without modifying Superset.
- **Uncommitted in `apps/results-dashboard`:**
  - Modified: `aisc_ext/comments/api.py` (CSRF check, dashboard access check, chart and reply rules), `aisc_ext/comments/views.py` (the list page becomes read-only) and `superset_config.py` (registers the review page).
  - New: `aisc_ext/review/` (`service.py`, `views.py`, templates), `scripts/verify_review.py` and `tests/test_review.py`.
  - Results: 74 unit tests, 31/31 live checks, 23/23 browser checks.
- **Next step:** commit. Items the session left for the user:
  - Viewers can't open any dashboard without dataset access.
  - Keycloak admin maps to a Superset viewer.
  - ReviewRequestApi still has the CSRF and add/edit-form bugs.
- **Top-level:** `apps/results-dashboard` shows as `m`, which here means uncommitted changes inside the submodule.

### W5. Sean merge. Done, now frozen.
- backend e34fca3, webapp 429f62c, eval e5b1b0a, plugin-interface 97eddea.
- Top level: b435917 points at them, and a2852c3 and a34515b are Sean's cherry-picked commits.
- Leftover side branches: `feat/ai-system-versions` (top, backend, qualification, webapp) and `merge/sean-aisystem` (top, backend, webapp, eval, plugin-interface). Both are fully contained in `feat/unified-modules`. S-versions offered to delete them, with no answer.
- backend dfe4120 fixes the Dockerfile so it builds with `../../shared`. It is not versioning-related and is needed for the image to build.

## 3. Code to undo (the freeze and versioning build)

Per RULES.md, the engine can only get a new migration that reverts `0022` and restores the e34fca3 schema.

**Top-level `aisc` (platform core):**
- b723c73 "One AI system per project, in versions that stay as they were used":
  - `platform/migrations/0002_one_ai_system_per_project.sql` creates `core.ai_system` (one per project) and `core.ai_system_version` (number, release, frozen_at, frozen_reason, a trigger that refuses updates to frozen rows, and a one-draft partial index). It carries over the `core.system` rows under the same pids.
  - Also `platform/platform_service/ai_system.py` (new), `app.py` (+74: `GET /projects/{slug}/ai-system`, the draft and freeze endpoints), `db.py` (+161/-31), and tests `platform/tests/test_ai_system.py` and `test_api_ai_system.py`.
- e126a3f: 0002 marks carried-over versions frozen.
- 72edfbf: `db.py` makes an edit answer with its project, plus a test.
- c0f460e: `docker-compose.development.yml` adds `PLATFORM_URL: http://platform:8000` on the backend for drafts and freeze. It also bumps the backend, qualification and webapp pointers.
- 59a085a and ad6262f: pointer bumps only.
- **Live DB state:** migration 0002 is applied; `core.ai_system` has 1 row; `core.ai_system_version` has 1 row (number 1, frozen, "ai card (carried over from core.system)"). `core.system` still exists with 1 row.

**apps/backend (engine):**
- e144bc9 "The parts of the AI system belong to a version of the platform's one".
  - Adds migration `0022_parts_belong_to_a_version_of_the_one_system.py`, which:
    - creates `SystemVersionParts` (the table `engine.system_version_parts`);
    - adds `ai_component.project` (FK to engine.project), `system_version_id` and `lineage`;
    - removes `ai_component.system`;
    - deletes the `AISystem` model, dropping the `engine.ai_system` table;
    - adds SQL foreign keys from `ai_component.system_version_id` and `evaluation.system_id` to `core.ai_system_version`, replacing evaluation's old key to `core.system`.
  - Also changes `admin.py`, `auth/membership.py`, `models/{ai_system,evaluation,project}.py`, `repositories/{project,stats}_repository.py`, `routers/{component,evaluation,internal,project}.py` and `schemas/ai_system.py`.
  - Adds `services/platform_client.py`, `services/platform_versions.py` and `services/system_versions.py`.
  - Tests: new `tests/routers/test_ai_system_versions.py` and `tests/test_system_versions.py`; edits to `test_evaluation_inputs_template.py`, `test_project_evaluations_serialization.py` and `test_project_membership.py`.
- a38dbb4: 0022 edit (the version link does not block deleting the project).
- **Keep dfe4120** (Dockerfile). It is not part of versioning.
- **Live DB state:** 0022 is applied; `engine.ai_system` is absent; `engine.system_version_parts` is present. There are 0 components and 0 evaluations.

**apps/qualification:**
- bcc7093 "One AI card per version":
  - `prisma/migrations/20260923180000_one_ai_card_per_system_version/migration.sql` repoints the FK `qualification.system_id` to `core.ai_system_version` (ON DELETE CASCADE) and adds the UNIQUE index `qualification_system_id_key`. It is applied live.
  - Also `prisma/schema.prisma`, `scripts/seed_mcas.mjs`, `QualificationsList.tsx`, `qualifications/page.tsx`, `qualify/new/{actions.ts,page.tsx}`, `src/domain/cardVersions.ts` (new), `QualificationRepository.ts`, `PlatformClient.ts` (calls the draft and freeze endpoints) and `QualificationService.ts`.
  - Tests: `PlatformClient`, `QualificationsList`, `cardSubmission` (new), `cardVersions` (new), `seedMcas`.
- 705a288 "One AI system to edit": the screens `system/page.tsx`, `system/edit/page.tsx`, `/qualify/new` redirects, `SiteHeader`, and `test/unit/oneSystemEntryPoints.test.ts`. The spec says to KEEP these screens; only the freeze and draft calls go.
- e112001: an apostrophe fix in `p/[project]/page.tsx`. Keep it.

**apps/webapp:**
- e36fed4: `src/components/SystemVersionBanner.tsx` and its test (new), plus `AISystemSettings.tsx`, which shows the version and warns when it is frozen. The "frozen, next edit makes a new version" wording follows the undone model.

**Memory note:** `project_aisc_ai_system_versions.md` says "not rebuilt". That is stale: it was rebuilt and migrated live at about 18:00.

## 4. Current data placement and install flows

The live Postgres is container `postgres` (compose `aisc`). Databases: `platform`, `keycloak`, `superset`, and `project_<hex>` for 4 projects: MCAS `project_01399e17...` plus 3 empty test leftovers. There are also old `aisc`, `controls`, `qualification`, `control_objectives` and `control_objectives_test` databases with `public` tables, not in use as far as I could tell.

| Module | Where | Project identified by | System identified by |
|---|---|---|---|
| platform core | `platform.core`: project, project_member, system, ai_system, ai_system_version, schema_migration | `core.project.pid` (+slug) | `core.ai_system_version.pid` (via ai_system.project_id); legacy `core.system` still present |
| engine (backend/eval) | `platform.engine.*` (unprefixed Django tables) | `engine.project.project_id` = core pid; child rows FK `engine.project.id` | `evaluation.system_id` and `ai_component.system_version_id` -> `core.ai_system_version`; `engine.ai_system` table dropped by 0022 |
| qualification | `platform.qualification`: qualification, qualification_answer, qualification_risk, knowledge_graph (frozen) | `qualification.project_id` -> core.project | `qualification.system_id` UNIQUE -> core.ai_system_version; also text copies `systemName`, `systemVersion` |
| control-objectives | `platform.control_objectives`: project, risk, graph, mapped_objective, mapping_run | its own `project` row, `project_id` -> core.project | no link: `system_name` and `qualification_id` copied from an uploaded card file (`ai-card.json` / `ontology.jsonld`) |
| controls | `project_<hex>.controls`: source, checklist, checklist_question, submission, submission_answer (+`provision.template_migration`); shared schema dropped | the database itself (no project column) | none |
| catalogue | `platform.catalogue`: tool, tool_metadata, tag, metric, control_question... | knows no projects | n/a |
| dashboard | `superset` DB (metadata); reads `platform` via `dashboard_ro`; comments tables created by `aisc_ext` | none per project yet | n/a |

**Installing a test (plugin):**
1. The catalogue (:8102) sends `web+aiscplugin://enable?package=&version=&slug=` to the webapp `/receiver` (`apps/webapp/src/pluginCatalogue/installUri.ts`).
2. `PluginInstallDialog` POSTs `${API_URL}/plugins` with project_uuid, package, version and catalogue_slug.
3. The backend's `routers/plugin.py:173` (`require_role("admin")`) calls `plugin_loader.load_package` from the devpi index and writes `engine.plugin` rows per project, recording `catalogue_slug`.

**Installing a control (checklist):**
1. The catalogue's "Install into a project..." sends the user to the opening platform's controls `/install?slug=`.
2. That page lists the projects the user may edit, and `chooseProject` redirects to `/p/{pid}/install`.
3. `installFromCatalogue` does the rest:
   - `writableProject(pid)` checks the platform's `GET /authz/projects/{pid}`;
   - `fetchCataloguePackage(slug)` fetches the control from the catalogue (d88da1d);
   - `installChecklist` writes into `project_<hex>.controls`. It is idempotent.

## 5. Conflicts between streams

1. **RULES.md vs S-projdb plans 4 and 5, and the spec.**
   - RULES.md FROZEN #1 says engine "Table names and placement stay as they are now (unprefixed, and the current schema); do not rename or move them".
   - Plan 4 moves every engine table into each project DB. Plan 5 assumes `engine.*` inside project DBs. The spec (section "Data, per module") puts everything, the engine included, in the project DB.
2. **Plans 2-4 were written 16:53-17:11, before the 18:25-18:32 model.**
   - Plan 2 keeps "a project may name several systems" and the platform-written systems.
   - Plan 3 keeps the card upload, several assessments per project, and the `system_name` and `qualification_id` copies.
   - Plan 4 makes `evaluation.system_id` an FK to `project.system`, not a version stamp.
   - The spec lists the needed edits but was never reconciled. That was the interrupted step.
3. **Spec vs RULES.md on the engine stamp.**
   - The spec adds `engine.evaluation.system_version_id` as a stamp. RULES.md freezes the Evaluation model and says to add links on the non-frozen side.
   - Today the live `evaluation.system_id` points at `core.ai_system_version` only because of 0022. Reverting to e34fca3 restores the key to `core.system`.
4. **Spec vs RULES.md on what is kept.**
   - The spec keeps "the membership checks on Sean's routes; the unprefixed table names". Those come from the e34fca3 merge, so they survive the revert.
   - The spec also says `core.ai_system` / `core.ai_system_version` "move into the project database". RULES.md only allows the platform core to change.
5. **The freeze build and W3 prefill both edit qualification's `qualify/new` area.**
   - 705a288 redirects `/qualify/new` to `/system/edit`.
   - The uncommitted prefill work edits `qualify/new/QualifyForm.tsx` and adds files in that folder. The edit page reuses the form (unverified).
6. **A shared file across streams.** The top-level `docker-compose.development.yml` holds both W1's committed `PLATFORM_URL` line (to remove with the undo) and W3's uncommitted prefill service.
7. **Plan 3 vs S-versions' offered option 1.** Plan 3 says control-objectives "does not read the AI system". S-versions proposed that it read the latest card version.

## 6. Open questions (unanswered at cutoff)

1. **Spec, from S-versions:** order of work; whether controls are stamped per answer or per submission; carry-forward of objectives to the next version; whether a re-upload counts as drift.
2. **S-projdb (17:10):**
   1. Is the prefill work owned by another session? It is S-prefill's.
   2. Should the engine plan build on Sean's merge? RULES.md now implies yes.
   3. Which dashboard role model?
   4. Fix `verify-rbac.sh` and drop the 3 empty `project_*` databases?
   - Plan 3's own questions: one assessment per project? Should objective CSV updates reach existing projects? Should it point at `project.system`?
   - Plan 4's questions: run tickets versus a worker service account; removing Django admin and allauth; immudb.
3. **Per-project databases:** do they still apply to qualification, control-objectives, engine and dashboard, given the RULES.md placement freeze? Controls is already per project.
4. **What undoing the platform core becomes:**
   - Is `core.ai_system_version` kept as the card-version table, stripped of freeze and draft?
   - Or is it replaced by `core.system` or by a qualification-owned table?
   - Is `core.system` dropped? That needs the superuser.
5. **The live migrations:** the platform's 0002, the engine's 0022 and qualification's card migration are applied, but RULES.md forbids migrating the live DB. How does the reverted schema reach the running stack?
6. **S-prefill:** commit the prefill work? Option A or B for "no term"? Should the upload fill tags? Add the pre-commit secret hook?
7. **W4:** commit the review page? Fix ReviewRequestApi? Viewer dataset access and admin role mapping?
8. **Leftovers:** delete the side branches `feat/ai-system-versions` and `merge/sean-aisystem`?
