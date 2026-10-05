# Stage 2: work plan

Inputs: RULES.md, 01-interrupted.md, the spec `specs/2026-09-23-one-system-versioned-description.md`,
plans 1-5 and the roadmap, and the code (read only). This file says WHAT to do and in what order.
It is not a spec and holds no code. Every `DEFAULT (user to confirm)` is reversible and is listed
again in PROGRESS.md for the user.

## 1. Decisions this plan makes

1. **Placement.** The engine stays where it is: `platform` DB, schema `engine`, unprefixed tables,
   e34fca3 schema. Qualification, control-objectives and the card versions also stay in the
   `platform` DB. Only controls stays in `project_<hex>` (already built, plan 1).
   Reason: the frozen engine has `evaluation.system_id -> core.system(pid)`, so the version table
   has to live in `platform`. Anything that points at it (qualification, control-objectives) keeps
   a real foreign key only if it stays in the same database.
   `DEFAULT (user to confirm)`: "one database per project" now applies to controls only.
   Everything else is isolated by `project_id` plus the membership checks that are already there.
2. **The one system** is the engine's `engine.ai_system`: Sean's model, one-to-one with
   `engine.project`, not versioned, with its components in `engine.ai_component`. It comes back
   with the undo.
3. **A system version is a `core.system` row.** One row per saved AI card: v1, v2, and so on.
   `core.system` gains a card `number`. Its "same name and version is the same row" identity
   index goes, because two card versions may carry the same product name and version.
   `core.ai_system` and `core.ai_system_version` are dropped.
   Reason: the frozen engine column `evaluation.system_id` already references `core.system(pid)`,
   and it is documented as "the system this evaluation ran against". It becomes the test stamp,
   with no engine schema change. Before bcc7093, qualification also pointed at `core.system`.
4. **The undo is forward only.** It uses new migrations (engine `0023`, platform `0003`, and a new
   qualification Prisma migration). Applied migration files stay in place, because the live DB
   has recorded them. Each new migration is idempotent and works in any order relative to the
   others (see WP1-WP3).
5. **Links to frozen rows are made on the non-frozen side.** The one exception is the engine
   stamp. It uses the existing frozen column `evaluation.system_id` and is set by one line in
   `create_evaluation_task` (routers/evaluation.py:103). That line is not Sean's: git blame shows
   894cbffd.

## 2. Target data: what each step writes and reads

All tables are in the `platform` DB unless marked `[project_<hex>]`.

| Step | Writes | Reads | Links (owning side -> target) |
|---|---|---|---|
| 0 project | `core.project`, `core.project_member` (platform) | | |
| 1 qualification + card agent | `qualification.qualification` (the card, one per version), `qualification_answer`, `qualification_risk` (frozen), `knowledge_graph` (frozen table), new `qualification.card_component`; the platform writes `core.system` (version header) on the card's behalf | `engine.ai_system` / `engine.ai_component` via the engine API | `qualification.system_id -> core.system(pid)` UNIQUE, ON DELETE CASCADE; `core.system.project_id -> core.project`; `card_component.qualification_id -> qualification.id` CASCADE; `card_component.component_pid` = `engine.ai_component.pid` (uuid, no FK: the engine is frozen and in another schema's ownership) plus a snapshot (name, type, object name) and the AIRO property |
| 2 control objectives | `control_objectives.project` (one assessment per version), `graph` (snapshot of that version's JSON-LD), `risk`, `mapped_objective`, `mapping_run` | the card of the latest version from qualification over HTTP (new route by system version) | new `control_objectives.project.system_id -> core.system(pid)` UNIQUE, ON DELETE CASCADE; existing `project_id -> core.project` |
| 3 install | tests: `engine.plugin` rows per project with `catalogue_slug` (engine, unchanged). Controls: `controls.source` / `checklist` (`catalogueId`) / `checklist_question` `[project_<hex>]` | `catalogue.tool`, `tool_metadata`, `control_question`, devpi | `engine.plugin -> engine.project`; checklist: the DB is the project |
| 4a execute tests | `engine.evaluation` (+ `system_id` stamp), `evaluation_plugin`, `evaluation_input`, `observation`, `measurement`, `artifact` | `core.system` (latest number for the project; SELECT is already granted) | `engine.evaluation.system_id -> core.system(pid)` ON DELETE SET NULL (restored 0015 key) |
| 4b answer controls | `controls.submission`, `submission_answer` + new `system_version_pid`, `system_version_number`, `answered_at` `[project_<hex>]` | platform `GET /projects/{pid}/system-versions/latest` | uuid stamp, no FK (it crosses databases) |
| 5 dashboard | Superset metadata and the `aisc_ext` comment/review tables (`superset` DB) | `engine.*` joined to `core.system` over the existing connection; `controls.*` over a per-project connection | comments -> Superset dashboard/chart ids (unchanged) |

Rules held by the data:
- One system: `engine.ai_system.project` is one-to-one with `engine.project` (e34fca3).
- One card per version: UNIQUE `qualification.system_id`. Version numbers are gapless per
  project: UNIQUE `(core.system.project_id, number)`. Only the platform writes `core.system`.
- Old versions are read-only: a platform trigger refuses UPDATE on `core.system` except for the
  latest number, and a qualification trigger refuses UPDATE on a card whose version is not the
  project's latest. Both are in non-frozen schemas.
- "Latest" is `max(number)` for the project. Live screens show it. Stamps never block a write:
  if the platform cannot be reached, the stamp is NULL and a warning is logged.

## 3. Work streams from 01: fate of each

| Stream | Fate | Reason |
|---|---|---|
| W1 freeze/versioning build | **Discard** the freeze, drafts, copy-on-write and SystemVersionParts (WP1-WP3, WP13). **Keep** 705a288 (the one-system screens) and e112001. **Fold** the spec's model into this plan | Superseded by the 18:25-18:32 model; RULES.md orders the engine undo |
| W1 spec (uncommitted) | **Fold in**: its terms and rules 1-7 are kept; its "Data, per module" and "Fit with plans" sections are replaced by section 2 here | It assumed per-project DBs for everything |
| W2 plan 1 (controls + catalogue install) | **Keep** as built | It matches RULES.md; controls is not frozen |
| W2 plans 2, 4, 5, 6, roadmap | **Drop** plans 2, 4 and 6. **Mine** plan 5 for WP11b (template grant, bridge, per-project role). Mark all of them superseded (WP15) | Plan 4 moves frozen engine tables; plan 2 moves `core.system` away from the engine's FK |
| W2 plan 3 (control-objectives) | **Drop** the move to per-project DBs. **Reuse** its "authz inside the helper" lesson for the new routes in WP7 | Same placement reason; its upload model is superseded |
| W3 prefill | **Finish and commit** (WP5) | The user asked for it; it is already in the running image |
| W4 review page | **Finish and commit** (WP11c); fix the ReviewRequestApi bugs (WP14, nice to have) | Step 5 "comment" |
| W5 Sean merge, dfe4120 | **Keep**, frozen | RULES.md |
| Side branches `feat/ai-system-versions`, `merge/sean-aisystem` | **Keep**, untouched | Deleting needs the user; they are fully contained in `feat/unified-modules` |
| `MODEL_LISTING_SSL_VERIFY` in untracked `env.runtime` | **Keep** | It comes from Sean's a2852c3 |

## 4. Open questions from 01, with defaults

Every row is `DEFAULT (user to confirm)`.

| # | Question (source) | Default |
|---|---|---|
| 1 | Order of work (spec q1) | Undo first in the shared DB, then build forward. No second rework, since plans 2-4 are dropped. `DEFAULT (user to confirm)` |
| 2 | Control stamp (spec q2) | Per answer, when it is saved (RULES.md "when answered"). A submission lists the versions its answers carry. `DEFAULT (user to confirm)` |
| 3 | Carry-forward (spec q3) | A new version's assessment starts empty. Copying unchanged risks' ratings and mappings (same text and VAIR terms), marked "carried from vN", is WP16 (N). `DEFAULT (user to confirm)` |
| 4 | Drift (spec q4) | A re-upload counts (the object name differs from the card's snapshot), as do an added or removed component and a changed type. Shown, never auto-fixed. `DEFAULT (user to confirm)` |
| 5 | Prefill owner (S-projdb q1) | S-prefill; this run finishes it (WP5). `DEFAULT (user to confirm)` |
| 6 | Engine plan on Sean's merge (S-projdb q2) | Yes; no engine work beyond the undo and the stamp line. `DEFAULT (user to confirm)` |
| 7 | Dashboard role model (S-projdb q3) | Each project template grants `dashboard_ro` read on its own schemas (plan 5's approach); no membership in module roles. `DEFAULT (user to confirm)` |
| 8 | `verify-rbac.sh`, 3 empty `project_*` DBs (S-projdb q4) | Fix the script (WP15). Do not drop the DBs in this run (no live writes); dropping is a later user action. `DEFAULT (user to confirm)` |
| 9 | Plan 3's questions | One assessment per version, several per project over time. A new CSV applies to new assessments only (`objectives_digest` records which). Points at `core.system`. `DEFAULT (user to confirm)` |
| 10 | Plan 4's questions (run tickets, Django admin/allauth, immudb) | Not applicable: plan 4 is dropped. `DEFAULT (user to confirm)` |
| 11 | Per-project DBs for other modules (01 q3) | No, see decision 1. `DEFAULT (user to confirm)` |
| 12 | What `core` becomes (01 q4) | `core.system` is kept and becomes the version table (`number` added); `core.ai_system` and `core.ai_system_version` are dropped. `DEFAULT (user to confirm)` |
| 13 | Live migrations (01 q5) | The section 6 runbook, applied later with the user. `DEFAULT (user to confirm)` |
| 14 | Prefill (01 q6) | Commit it. "No term": option B, through the existing ontology filler, which limits terms to the class; the prefill leaves term fields empty rather than writing "no term". The upload does not fill tags. The secret hook is WP17 (N). `DEFAULT (user to confirm)` |
| 15 | W4 (01 q7) | Commit the review page; fix ReviewRequestApi (WP14). Members read their project's datasets; a Keycloak admin maps to Superset Admin. `DEFAULT (user to confirm)` |
| 16 | Side branches (01 q8) | Keep. `DEFAULT (user to confirm)` |
| 17 | New: a test install needs platform `admin` (`routers/plugin.py:173`), a control install needs project editor | Keep the engine rule, and the catalogue says so; aligning them is WP18 (N). `DEFAULT (user to confirm)` |

## 5. Work packages

Every package is TDD against throwaway Postgres (a `docker run --rm` container under a unique
name, with `PLATFORM_TEST_DATABASE_URL` and each module's equivalent set). Commits stay local on
`feat/unified-modules`, with explicit paths staged. No compose, no live writes.
R = required for the goal, N = nice to have.

**WP0 (R) Test bed and reference schema.** Touches: a new top-level `scripts/` file. Deps: none.
- Goal: start a throwaway Postgres, apply `init/platform-db.sql`, run the engine migrations at
  e34fca3, and dump `pg_dump -s -n engine` as the reference (constraint and index names
  included). Record the baselines of the backend, platform, qualification, control-objectives,
  controls, catalogue and webapp suites.
- Accept: prints the reference dump path and the baseline pass counts; leaves no container.

**WP1 (R) Engine undo.** Touches: apps/backend. Deps: WP0.
- Revert e144bc9 and a38dbb4 in code (models, admin, membership, repositories, routers, schemas,
  services/platform_*, system_versions, their tests). Keep dfe4120 and the 0022 file.
- Add `0023`, restoring e34fca3 exactly:
  - recreate `ai_system` (one per `engine.project`) and re-add `ai_component.system`, filled
    from its project's ai_system;
  - drop `ai_component.project`, `system_version_id`, `lineage` and `system_version_parts`;
  - drop the two FKs into `core.ai_system_version` if they exist;
  - re-add `aisc_backend_evaluation_system_id_fkey -> core.system(pid) ON DELETE SET NULL` when
    `core.system` exists (as 0015 does).
- Accept: the engine schema after `0001..0023` diffs empty against the WP0 reference, whether
  platform 0003 ran before or after. `makemigrations --check` is clean. The backend baseline
  passes, Sean's tests included. `git diff e34fca3 -- aisc_backend/models` is empty.

**WP2 (R) Platform core: card versions in `core.system`.** Touches: platform/, compose. Deps: WP0.
- Revert b723c73, e126a3f and 72edfbf in code and tests. Keep the 0002 file.
- Add `0003`:
  - drop `core.ai_system_version` and `core.ai_system` if they exist (FKs into them first);
  - add `number int NOT NULL` (existing rows numbered by `created_at` per project) and
    `created_by`;
  - replace `system_identity_idx` with UNIQUE `(project_id, number)`;
  - add the trigger that allows UPDATE on the latest row only.
- Endpoints, caller must be an editor: `POST /projects/{slug}/system-versions`, then
  `GET /projects/{slug}/system-versions` and `GET /projects/{pid}/system-versions/latest`.
  Remove the draft and freeze endpoints; the old `register_system` becomes the version create.
- Remove the backend's `PLATFORM_URL` (compose line 67, from c0f460e) with `git add -p`.
- Accept:
  - Two POSTs give v1 and v2; a viewer gets 403, a stranger 404.
  - Updating v1 is refused by the DB, updating v2 is allowed, and deleting the project cascades.
  - 0003 is a no-op on a fresh DB and converts a DB holding 0002's rows, keeping the pids.

**WP3 (R) Qualification undo, and "save = next version".** Touches: apps/qualification. Deps: WP2.
- Revert bcc7093 in code: PlatformClient draft/freeze, cardVersions, the repository and service
  changes, their tests. Keep its migration file.
- A new Prisma migration repoints `qualification.system_id` to `core.system(pid)` ON DELETE
  CASCADE (UNIQUE kept), adds the read-only trigger for non-latest cards, and creates
  `card_component`.
- Saving the card calls `POST system-versions`, then writes the new card row, pre-filled from the
  previous one. The "Versions" list shows vN and who made it; old versions open read-only.
  705a288's screens stay.
- The filler and reviewer patches edit the latest card in place; only a form save makes a
  version. `DEFAULT (user to confirm)`
- Accept: two saves give 2 cards on v1 and v2. Editing v1 is refused (UI 403, DB trigger).
  `seed_mcas` produces v1. The vitest and tsc baselines hold, and the prefill files are untouched
  until WP5.

**WP4 (R) Migration-order check for WP1-WP3.** Touches: the WP0 script. Deps: WP1-WP3.
- Goal: on a throwaway DB in the live shape (0002/0022/card migration applied; 1 version,
  0 components, 0 evaluations), run engine 0023, the qualification migration and platform 0003
  in all 6 orders.
- Accept: every order ends in the same schema (the engine matches the reference; core and
  qualification are as designed), and the MCAS qualification keeps its `system_id`.

**WP5 (R) Finish the document prefill (W3).** Touches: apps/qualification, compose,
`scripts/verify.sh`. Deps: WP3 (same folder).
- Prove the prefill works from `/system/edit`, since 705a288 redirects `/qualify/new` there.
- Add a test for "Pick at least one market form" with an uploaded document and no tags: a clear
  message, and no answers lost.
- The prefill writes no "no term". Commit the W3 files, and the compose and verify.sh hunks, with
  `git add -p`.
- Accept: 69+ Python and 353+ vitest tests pass and tsc is clean. An upload on the edit page fills
  the 21 fields and the risk rows, with the "empty only / replace" choice.

**WP6 (R) Card agent deployed, and components linked by AIRO.** Touches: apps/qualification (app
and ontology service), compose. Deps: WP1, WP3.
- 6a: add a `qualification-agents` service (the ontology filler, `services/agents`) and
  `AGENT_SERVICE_URL` on qualification-web to the compose file. File edit only.
- 6b: the card lists the engine components (via the engine API, with the caller's token) and
  stores `card_component` rows:
  - `hasModel` for a model or LLM;
  - `hasTrainingData`, `hasTestingData` or `hasValidationData` for a dataset;
  - `hasComponent` otherwise.
  The graph builder emits them as AIRO triples on `urn:aisc:component:<pid>`. The filler's
  free-text components become suggestions to match.
- 6c: a drift banner compares the latest card's snapshot with the engine components and offers
  "start the next version".
- Accept:
  - A card with 2 engine components exports JSON-LD with the two AIRO properties and their pids.
  - Deleting, adding or re-uploading a component shows drift and never edits the card.
  - The filler, when reachable, fills `techniques`.
  - The compose config validates (`docker compose config` on a copy, never `up`).

**WP7 (R) Control objectives from the latest version's card.** Touches: apps/control-objectives,
apps/qualification (one route). Deps: WP3, WP6b.
- The assessment row gets `system_id -> core.system` UNIQUE; the `system_name` and
  `qualification_id` copies are dropped (Alembic).
- "Start assessment" takes the project's latest version and fetches its JSON-LD with the caller's
  token from a new qualification route, `/p/{pid}/api/system-versions/{system_pid}/ontology.jsonld`
  (authz inside the handler).
- The bytes are stored as the `graph` snapshot, and the existing risk parsing runs unchanged.
  Upload leaves the UI; older versions' assessments are read-only history.
- Accept: v1 gives assessment A1, and a second start on v1 opens A1. After v2, start gives A2 and
  A1 is read-only. A stranger gets 404 from both apps. The risks equal the card's
  `qualification_risk` rows.

**WP8 (R) One-click install, same UX for tests and controls.** Touches: the apps/catalogue
frontend, apps/webapp receiver and dialog (not Sean's files; checked before editing). Deps: none.
- Test and control entries show the same "Install into a project..." button. Both go to the
  opening platform over https with the slug and the handshake's project:
  - tests to webapp `/receiver?package&version&slug&project`, the custom protocol kept as a
    fallback;
  - controls to controls `/install?slug&project`, as built.
- Both targets preselect that project in the chooser; one confirm installs, and a second install
  says "already installed".
- Accept (vitest, plus a browser check on mocks or a throwaway stack): from the catalogue opened
  by project P, one click and one confirm give an `engine.plugin` row for P with
  `catalogue_slug`, or a `project_<P>.controls.checklist` with `catalogueId`. Both are idempotent.

**WP9 (R) Test stamp.** Touches: apps/backend (one repository function, one line). Deps: WP1, WP2.
- `create_evaluation_task` sets `system_id` to the project's latest `core.system` pid, read by
  `project.platform_project_id`; NULL means no version yet.
- Accept: an evaluation started after v2 has v2's pid, and saving v3 afterwards leaves it on v2.
  With no version the evaluation still starts. The engine schema diff is still empty.

**WP10 (R) Control stamp.** Touches: apps/controls, `platform/project-template` if needed.
Deps: WP2.
- Add `system_version_pid`, `system_version_number` and `answered_at` to
  `controls.submission_answer` through the controls template migration path (provision).
- Every answer save sets them from the platform's `latest`. If the platform is down they stay
  NULL and the save still succeeds. The submission page shows "answered under vN" per answer.
- Accept: answers saved before and after v2 carry v1 and v2. A stopped platform does not block a
  save. Existing project DBs get the columns on first open.

**WP11 (R) Dashboard: visualise and comment.** Touches: apps/results-dashboard, platform/, the
template, compose. Deps: WP9, WP10.
- 11a: on the existing connection, datasets join `engine.measurement -> evaluation -> core.system`
  (version number), filtered by project, with one default dashboard per project.
- 11b: a per-project connection for `controls`, taken from plan 5:
  - template file `000N_dashboard.sql` grants `dashboard_ro` read on `controls`;
  - the bridge (`aisc_ext`) registers the connection and a role per project;
  - the platform calls the bridge on create and delete;
  - a chart shows answers by version.
- 11c: commit W4 (the review page). Members get dataset read; a Keycloak admin maps to Superset
  Admin.
- Accept: for a seeded throwaway project the dashboard shows test results and control answers,
  each with vN. A member comments on a chart; a non-member gets 403/404 on that project's
  dashboard and connection. 74+ unit tests and the review checks pass.

**WP12 (R) Pipeline chain test.** Deps: WP1-WP11.
- One cross-module integration test on throwaway DBs: project, card v1 with components, CO
  assessment on v1, plugin and checklist installed, evaluation stamped v1, card v2, an answer
  stamped v2, and dashboard queries that return both with their versions.
- Accept: it passes, and it fails if any link in section 2 is removed.

**WP13 (R) Webapp undo.** Touches: apps/webapp (not Sean's files). Deps: WP2.
- Revert e36fed4: SystemVersionBanner, and the frozen wording in AISystemSettings. Optionally
  show "description: vN (latest)", read-only.
- Accept: the vitest/tsc baseline holds, and `grep -ri frozen src` is empty.

**WP14 (N) ReviewRequestApi fixes** (CSRF, the add/edit forms). Accept: the tests that pin the
bugs pass.

**WP15 (N) Docs and scripts hygiene.** Plans 2-6 and the roadmap get a "superseded by
pipeline-2026-09-23/02" header. The spec is rewritten to match section 2. `verify-rbac.sh` is
fixed. The memory note `project_aisc_ai_system_versions.md` is corrected (stage 6).
Accept: `scripts/verify.sh` is green, on a throwaway stack or in dry run.

**WP16 (N) Carry-forward** of unchanged risks. Accept: v2 with one changed risk carries the others, marked.
**WP17 (N) Pre-commit secret hook.** Accept: a commit containing a fake key is refused.

**WP18 (N) Align the install permission** (test install = project editor). Needs a user decision,
and it touches engine code.

**Order.** WP0; then WP1 and WP2 in parallel; WP3; WP4; WP13 and WP5; WP6; WP7. Alongside WP3-WP7:
WP8 at any time, WP9 after WP1 and WP2, WP10 after WP2. Then WP11, WP12, and the N packages last.

## 6. Applying the undo to the live DB later (not in this run)

Run with the user present, after WP4 is green:
1. Take a fresh `pg_dump -Fc` of `platform` and of the MCAS `project_<hex>`.
   The 18:00 backup `~/aisc-install-backup-before-ai-system-versions-20260923.dump` is the
   fallback.
2. Stop the writers: aisc-backend, the eval worker, qualification-web and control-objectives.
3. Rebuild those images from `feat/unified-modules`.
4. Run engine `migrate` (0023), `qualification-migrate`, a platform restart (0003) and
   control-objectives Alembic, in that order. Any order is safe, per WP4.
5. Compare `pg_dump -s -n engine` with the WP0 reference, and check the MCAS card and
   `core.system` number 1 are intact.
6. Start the stack and run `scripts/verify.sh`.
Rollback: restore the dump from step 1.

## 7. Risks

- **0023 fidelity.** Django-generated constraint and index names must match e34fca3. If they do
  not, 0023 needs RunSQL renames. WP1's diff gate catches this.
- **Migration order on a fresh install.** Engine 0022 still runs and may add FKs into tables
  that platform 0003 drops. Every drop uses IF EXISTS and 0023 is idempotent. WP4 tests all
  orders, but a new compose `depends_on` could still race.
- **The stamp is code in a frozen module.** One line in `create_evaluation_task`. If the user
  reads RULES.md as "no engine code", the fallback is a non-frozen `core.evaluation_stamp` table
  written by the platform when the SPA starts a run. That fallback is weaker, because runs
  started by other means are missed.
- **Isolation drops for 4 modules versus the 14:19 decision.** Row-level `project_id` plus
  membership checks replace database isolation. The Superset shared connection can show engine
  rows across projects to any dashboard user unless the per-project filter and roles (WP11) hold.
- **Cross-database stamps** (controls) have no FK. A deleted version leaves dangling uuids, so
  the number is stored as well.
- **In-place edits of the latest card** by the filler and reviewer after an assessment was
  stamped weaken the auditor's guarantee. This is flagged as a DEFAULT.
- **The LLM key** for the filler (Mistral or Anthropic through qualification-llm) may be missing,
  and WP6a then yields empty techniques. The filler degrades by design.
- **Shared files across packages**: the compose file, verify.sh and `qualify/new`. Stage with
  `git add -p` and give each package its own hunks.
- **Live image drift.** The running images contain the freeze build and the prefill until the
  section 6 run. Nobody should use the "frozen" flows before then.
