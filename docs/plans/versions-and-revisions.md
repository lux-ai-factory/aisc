# Versions and revisions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a person correct the description of the same AI system (a *revision*) without creating a new system *version*, so all evidence stays attached and reports show "Version 1, revision 2" with an Amendments block.

**Architecture:** The system version stays one `project.system` row (`pid`); it gains `card_revision`. The qualification card allows several rows per `system_id`, numbered by `revision`; only the latest revision of the latest version may change. Controls' existing amend action gains a reason and a requester. The report pins a card revision in its snapshot and reads the highest revision not above it.

**Tech Stack:** Python 3 + FastAPI + psycopg (platform, report-generator, report-composer; pytest). Next.js + Prisma + vitest (qualification, controls). PostgreSQL per-project databases.

**Spec:** `docs/specs/versions-and-revisions.md`

## Global Constraints

- Work only in a separate clone `~/aisc-revisions` (with submodules) of the user's working branch. Never edit, build or run tests from `~/aisc`: the live stack aisc-063319 mounts `platform/project-template`, `platform/migrations`, `adapters`, `shared`, `local_plugins` from it.
- Tests run on throwaway databases only (`PLATFORM_TEST_DATABASE_URL`, each module's test DB). Never `docker compose` under the name `aisc-063319`.
- Commits stay local in `~/aisc-revisions`; no push without the user's yes, listing every repo and ref first.
- Saving "the system changed" behaves exactly as today; existing tests pass unchanged.
- Only the latest version can be revised. No sign-off step. Display: "Version N, revision R" when R > 1, otherwise "Version N".
- A correction requires both *Reason* and *Requested by* (trimmed, non-empty).
- Names, comments and tests say what things do: no plan codes, dates or task numbers in code.
- User-facing text: no em dashes.
- `df -h /` before any image build.

## Review Focus

1. **Correction posted from a stale page** after someone saved a new version: must be refused with a plain message, not create revision 2 of an old version. (Task 1 `test_revise_refuses_a_version_that_is_not_the_latest`, Task 4 `refuses a correction of a card that is no longer the latest`.)
2. **Two corrections at once** on the same version: must give revisions 2 and 3, never two revision 2s. (Task 1 `test_two_revisions_at_once_get_consecutive_numbers`.)
3. **Platform revised, card insert then failed**: `project.system.card_revision` is ahead of the cards; reports must still render the highest existing revision not above the pin. (Task 7 `test_card_reader_takes_highest_revision_not_above_pin`.)
4. **Old snapshots with no `card_revision`** must render exactly as before (revision 1). (Task 7 `test_snapshot_without_card_revision_reads_revision_one`.)
5. **In-place edits of an earlier revision** (Refine with AI, ontology corrections, components) must be refused by the database. (Task 2 `earlier revision of the latest version cannot change`.)

---

### Task 0: Separate checkout

- [ ] **Step 1:** `git clone --recurse-submodules --branch pilot https://github.com/lux-ai-factory/aisc.git ~/aisc-revisions` (origin `pilot` = dc39126 = local `hardening` in `~/aisc`, checked 2026-11-11). Check out each submodule at the commit `~/aisc` records (`git -C ~/aisc submodule status`), on branch `pilot` where it exists.
- [ ] **Step 2:** Copy `docs/specs/versions-and-revisions.md` and this plan into the clone.
- [ ] **Step 3:** Run each module's existing test suite once (platform, qualification, controls, report-generator, report-composer) and record the baseline pass/fail counts in `docs/plans/versions-and-revisions-baseline.txt`. Pre-existing failures are not this work's to fix.

### Task 1: Platform: revise a version

**Files:**
- Create: `platform/project-template/0032_card_revision.sql`
- Modify: `platform/platform_service/db.py` (`_STORED`, new `revise_version`)
- Modify: `platform/platform_service/routes/projects.py` (new PATCH route, `SystemRevisionIn`)
- Modify: `apps/report-composer/report_composer/db.py` (`_SYSTEM` includes `card_revision`)
- Test: `platform/tests/test_project_system.py`, `platform/tests/test_api_system_versions.py`

**Interfaces:**
- Produces: `PATCH /projects/{project}/system-versions/{pid}` body `{name, version, provider, description, reason, requested_by}` → 200 version dict incl. `card_revision: int`; 404 unknown project/pid; 409 not the latest; 422 empty reason/requested_by. Role: editor.
- Produces: `db.revise_version(project, pid, name, version, provider, description, reason, requested_by, subject) -> dict | None` (None = no such project; raises `db.NotLatest`, `db.NoSuchVersion`).
- Produces: every version dict (`list_versions`, `latest_version`, `create_version`) includes `card_revision`.

- [ ] **Step 1: Write failing tests** in `test_project_system.py`:
  - `test_new_version_has_card_revision_one`: `create_version(...)["card_revision"] == 1`.
  - `test_revise_updates_the_latest_version_in_place`: after create v1 then `revise_version(..., provider="Eindhoven Engine", reason="provider name", requested_by="Eindhoven Engine")`: same `pid`, `number == 1`, `card_revision == 2`, `provider == "Eindhoven Engine"`; `list_versions` has 1 row.
  - `test_revise_refuses_a_version_that_is_not_the_latest`: v1, v2, revise v1 → raises `db.NotLatest`; v1 unchanged.
  - `test_two_revisions_at_once_get_consecutive_numbers`: two threads revise v1 → `{2, 3}`.
  - `test_revise_emits_card_version_revised`: outbox row action `card_version.revised`, `item_id == pid`, details contain `number`, `card_revision`, `reason`, `requested_by`.
  And in `test_api_system_versions.py`: `test_patch_revises_for_editor` (200), `test_patch_refused_for_viewer` (403/404 as the other routes do), `test_patch_unknown_pid_404`, `test_patch_not_latest_409`, `test_patch_empty_reason_422`, `test_patch_empty_requested_by_422`.
- [ ] **Step 2:** Run `cd platform && PLATFORM_TEST_DATABASE_URL=<throwaway> pytest tests/test_project_system.py tests/test_api_system_versions.py -v` → new tests FAIL.
- [ ] **Step 3:** `0032_card_revision.sql`: `ALTER TABLE project.system ADD COLUMN IF NOT EXISTS card_revision integer NOT NULL DEFAULT 1 CHECK (card_revision > 0);` (the existing `system_only_latest_changes` trigger already refuses updates to non-latest rows; map its exception to `NotLatest`). Implement `revise_version` under the same advisory lock as `create_version` with `card_revision = card_revision + 1`, emitting `card_version.revised` in the same transaction. Add the route with `reason`/`requested_by` validated non-empty after `strip()`. Add `card_revision` to `_STORED` and to the composer's `_SYSTEM`.
- [ ] **Step 4:** Run the two files → PASS; run the whole platform suite → baseline count unchanged plus the new tests.
- [ ] **Step 5:** Commit `platform: a version's description can be revised in place`.

### Task 2: Qualification database: several revisions per version

**Files:**
- Create: `apps/qualification/prisma/migrations/20261111000000_card_revisions/migration.sql`
- Modify: `apps/qualification/prisma/schema.prisma` (`Qualification`)
- Test: `apps/qualification/test/db/cardRevisions.db.test.ts`

**Interfaces:**
- Produces: columns `revision Int @default(1)`, `amendsId String? @map("amends_id")`, `amendReason String? @map("amend_reason")`, `amendRequestedBy String? @map("amend_requested_by")`; `@@unique([systemId, revision])` replacing `systemId @unique`.
- Produces: SQL `qualification.card_is_current(card_id text) RETURNS boolean`: true when the card's version is the latest (`card_is_latest(system_id)`) and its `revision` is the highest for that `system_id`.

- [ ] **Step 1: Write failing DB tests** (pattern of `test/db/cardVersions.db.test.ts`):
  - `two cards of the same version with revisions 1 and 2 are allowed`.
  - `the same revision twice for one version is refused` (unique violation).
  - `revision 2 without reason, requested-by or amends is refused` (CHECK: revision = 1 ⇔ all three NULL).
  - `earlier revision of the latest version cannot change`: UPDATE of revision 1's `description`, INSERT of an answer / qualification_component / card_component on revision 1 → each raises.
  - `latest revision of the latest version still changes in place` (UPDATE succeeds).
  - `existing cards read as revision 1 after the migration`.
- [ ] **Step 2:** `cd apps/qualification && npx vitest run test/db/cardRevisions.db.test.ts` against the test DB → FAIL.
- [ ] **Step 3:** Migration: add the four columns + CHECK `(revision = 1 AND amends_id IS NULL AND amend_reason IS NULL AND amend_requested_by IS NULL) OR (revision > 1 AND amends_id IS NOT NULL AND amend_reason <> '' AND amend_requested_by <> '')`; FK `amends_id → qualification(id)`; `DROP INDEX qualification.qualification_system_id_key`; `CREATE UNIQUE INDEX qualification_system_id_revision_key ON qualification.qualification (system_id, revision)`; create `card_is_current`; `CREATE OR REPLACE` the four trigger functions from `20260925000000_project_database` (lines 128-160) and `20260929000000_system_components` (line 24) to call `card_is_current(<card id>)` instead of `card_is_latest(<system id>)`. Update `schema.prisma`; `npx prisma generate`.
- [ ] **Step 4:** Run the new test and the whole `test/db` folder → PASS (baseline unchanged).
- [ ] **Step 5:** Commit `qualification: a version's card can have several revisions`.

### Task 3: Qualification: "the card of a version" means its latest revision

**Files:**
- Modify: `apps/qualification/src/domain/cardVersions.ts` (`CardRef`, `cardIdByVersion`)
- Modify: `apps/qualification/src/server/repositories/QualificationRepository.ts` (`cardRefs`, `findBySystem`, new `revisionsOf`)
- Test: `apps/qualification/test/unit/cardVersions.test.ts`

**Interfaces:**
- Produces: `CardRef = { id: string; systemId: string; revision: number }`; `cardIdByVersion` maps each `systemId` to the id of its highest revision.
- Produces: `QualificationRepository.revisionsOf(systemId: string): Promise<{ id: string; revision: number; amendReason: string | null; amendRequestedBy: string | null; createdAt: Date }[]>` (highest first).
- Produces: `findBySystem(systemId)` returns the highest revision.

- [ ] **Step 1: Failing tests** in `cardVersions.test.ts`: `nextCard starts from the highest revision of the newest version` (cards `{a, v1, 1}`, `{b, v1, 2}` → `fromCardId === "b"`); `a version with one revision behaves as before`.
- [ ] **Step 2:** `npx vitest run test/unit/cardVersions.test.ts` → FAIL.
- [ ] **Step 3:** Implement; `findBySystem` uses `findFirst({ where: { systemId }, orderBy: { revision: "desc" } })`.
- [ ] **Step 4:** Run the unit suite → PASS.
- [ ] **Step 5:** Commit `qualification: a version's card is its latest revision`.

### Task 4: Qualification service: save a correction

**Files:**
- Modify: `apps/qualification/src/server/services/PlatformClient.ts` (`CardVersion.cardRevision`, new `reviseVersion`)
- Modify: `apps/qualification/src/server/services/QualificationService.ts` (extract the shared preparation of `createFromForm`; new `reviseFromForm`)
- Test: `apps/qualification/test/unit/QualificationService.revisions.test.ts`

**Interfaces:**
- Consumes: Task 1 PATCH route; Task 2 columns; Task 3 `nextCard`.
- Produces: `PlatformClient.reviseVersion(project: string, pid: string, identity: SystemIdentity, amend: Amendment): Promise<CardVersion>`; `type Amendment = { reason: string; requestedBy: string }`; `CardVersion` gains `cardRevision: number` (from `card_revision`).
- Produces: `QualificationService.reviseFromForm(project: string, formData: FormData, amend: Amendment, record?: (tx: Tx, card: CreatedCard & { revision: number; amendsId: string }) => Promise<unknown>): Promise<{ id: string }>`.

- [ ] **Step 1: Failing tests** (platform client faked as in `QualificationService.forms.test.ts`):
  - `a correction keeps the version and makes the next revision`: start card on latest v1 rev 1 → `reviseVersion` called with v1's pid; new card `systemId === v1.pid`, `revision === 2`, `amendsId === <rev 1 id>`, reason/requested-by stored; `createVersion` never called.
  - `a correction copies risks and components from the form like a save`.
  - `refuses a correction without a reason or a requester` → `FormValidationError` "Say why the description is corrected and who asked for it."; platform not called.
  - `refuses a correction of a card that is no longer the latest`: platform answers 409 → `FormValidationError` "A newer version was saved since this page was opened. Reload it before correcting the description."; nothing stored.
  - `the card revision stored is the one the platform returned`.
- [ ] **Step 2:** `npx vitest run test/unit/QualificationService.revisions.test.ts` → FAIL.
- [ ] **Step 3:** Move the shared steps of `createFromForm` (form resolution, parse, component keys, ledger-safety check, engine links, review carry) into one private method used by both; `reviseFromForm` then calls `reviseVersion` instead of `createVersion` and creates the card with `revision`, `amendsId`, `amendReason`, `amendRequestedBy`.
- [ ] **Step 4:** Run the whole unit suite → PASS, `QualificationService.forms.test.ts` unchanged.
- [ ] **Step 5:** Commit `qualification: a card save can correct the description of the same version`.

### Task 5: Qualification UI: ask, record, show

**Files:**
- Modify: `apps/qualification/src/app/p/[project]/qualify/new/actions.ts`
- Modify: `apps/qualification/src/app/p/[project]/qualify/new/QualifyForm.tsx`, `src/app/p/[project]/system/edit/page.tsx`
- Modify: `src/app/p/[project]/system/page.tsx`, `src/app/p/[project]/qualifications/page.tsx`
- Test: `apps/qualification/test/unit/qualifyActions.revisions.test.ts`

**Interfaces:**
- Consumes: Task 4 `reviseFromForm`, Task 3 `revisionsOf`.
- Produces: form fields `change` (`"system"` | `"correction"`), `amendReason`, `amendRequestedBy`. Ledger action `qualification.amended`, details `{ revision, amends, reason, requested_by, risks, components }`, content = card input.

- [ ] **Step 1: Failing tests:** `no choice is refused` ("Choose whether the system changed or you are correcting its description."); `"system" calls createFromForm and emits qualification.created as today`; `"correction" calls reviseFromForm and emits qualification.amended with reason and requested_by`; `the edit page offers the correction only when editing the latest card` (render test, as `isolationActionsAndPages.test.ts` does pages).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. In the form: a radio pair with nothing preselected, labels "The system changed (new version)" and "Correcting the description of Version N (revision N.R+1)"; *Reason* and *Requested by* inputs shown when correction is chosen. System page heading "Version N, revision R" when R > 1; version history lists each version's revisions with reason, requested by, author and date.
- [ ] **Step 4:** Run the unit suite → PASS; `npx tsc --noEmit` clean; `npm run build` succeeds.
- [ ] **Step 5:** Commit `qualification: ask whether a save changes the system or corrects its description`.

### Task 6: Controls: amend with a reason

**Files:**
- Create: `apps/controls/prisma/migrations/20261111000000_amendment_reason/migration.sql`
- Modify: `apps/controls/prisma/schema.prisma` (`Submission`)
- Modify: `apps/controls/src/app/p/[project]/submissions/[id]/actions.ts` (`reopenForAmendment`) and the page/button that calls it
- Test: `apps/controls/test/unit/amendment.test.ts`

**Interfaces:**
- Produces: `Submission.amendReason String? @map("amend_reason")`, `amendRequestedBy String? @map("amend_requested_by")`.
- Produces: `reopenForAmendment(project: string, submissionId: string, amend: { reason: string; requestedBy: string }): Promise<void>`; event `controls.submission.reopened` details gain `reason`, `requested_by`.

- [ ] **Step 1: Failing tests:** `amending stores reason and requester on the new draft`; `amending without a reason or requester is refused` ("Say why the answers are amended and who asked for it."), nothing created; `the reopened event carries reason and requested_by`; `the closed submission is unchanged`.
- [ ] **Step 2:** `cd apps/controls && npx vitest run test/unit/amendment.test.ts` → FAIL.
- [ ] **Step 3:** Migration adds the two nullable columns; validate before the transaction; store on the created draft; the Amend button opens a small form with the two fields.
- [ ] **Step 4:** Unit suite → PASS; `npx tsc --noEmit`; `npm run build`.
- [ ] **Step 5:** Commit `controls: an amendment says why and who asked for it`.

### Task 7: Report generator: pinned revision, cover, Amendments block

**Files:**
- Modify: `apps/report-generator/report_renderer/snapshot.py` (`card_revision` property)
- Modify: `apps/report-generator/report_renderer/data/qualification.py` (every card query), `report_renderer/context.py` (`ctx.card_revision`)
- Modify: `apps/report-generator/report_renderer/blocks/cover.py`
- Create: `apps/report-generator/report_renderer/blocks/amendments.py`; register it where the other blocks are (`registry.py`)
- Modify: `apps/report-generator/report_renderer/data/controls.py` (new `amendments`)
- Test: `apps/report-generator/tests/test_card_revisions.py`, `tests/test_block_amendments.py`, `tests/test_block_cover.py`

**Interfaces:**
- Consumes: Task 2 columns, Task 6 columns.
- Produces: snapshot key `card_revision: integer >= 1`, optional, absent = 1.
- Produces: `qualification.card(project_id, system_id, *, sources, revision: int)` and the same `revision` keyword on `components`, `knowledge_graph`, `risks`; `qualification.amendments(project_id, system_id, *, sources, revision) -> list[dict]` (`revision, reason, requested_by, created_at`); `controls.amendments(project_id, system_id, *, sources) -> list[dict]` (`checklist, version, reason, requested_by, created_at`).
- Produces: block type `"amendments"`.

- [ ] **Step 1: Failing tests:**
  - `test_snapshot_without_card_revision_reads_revision_one`; `test_snapshot_card_revision_must_be_positive`.
  - `test_card_reader_takes_highest_revision_not_above_pin`: revisions 1 and 2 exist, pin 3 → revision 2; pin 1 → revision 1 (description text differs and is asserted).
  - `test_risks_follow_the_pinned_revision` (Risk 5 vulnerability text of rev 1 vs rev 2).
  - `test_cover_shows_revision_when_above_one` ("Version 1, revision 2"); `test_cover_unchanged_for_revision_one` (golden test stays green).
  - `test_amendments_block_lists_card_and_checklist_amendments` (rows: date, what, reason, requested by); `test_amendments_block_omitted_when_none`; `test_amendments_up_to_pinned_revision_only`.
- [ ] **Step 2:** `cd apps/report-generator && pytest tests/test_card_revisions.py tests/test_block_amendments.py tests/test_block_cover.py -v` → FAIL.
- [ ] **Step 3:** Card queries select `... WHERE q.system_id = %(s)s AND q.revision = (SELECT max(revision) FROM qualification.qualification WHERE system_id = %(s)s AND revision <= %(r)s)`. Amendments block follows `changes_since.py`'s structure; no ledger lookup in the renderer beyond what `report_ro` can already read (if the ledger entry id is not readable, the column is left out).
- [ ] **Step 4:** Whole report-generator suite → baseline unchanged plus new tests; golden tests unchanged.
- [ ] **Step 5:** Commit `report: a report pins a card revision and lists amendments`.

### Task 8: Report composer: pin at generation, block in built-in layouts

**Files:**
- Modify: `apps/report-composer/report_composer/reports.py` (`snapshot_of`)
- Modify: `apps/report-composer/report_composer/builtin_layouts.py`
- Test: `apps/report-composer/tests/test_card_revision_pin.py`

**Interfaces:**
- Consumes: Task 1 `card_revision` on `project.system`; Task 7 snapshot key and block type.

- [ ] **Step 1: Failing tests:** `snapshot pins the version's current card revision` (`project.system.card_revision = 2` → snapshot `card_revision == 2`); `a stored report regenerates with its own pinned revision after a later correction`; `built-in layouts end with an amendments block in the appendix`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement; built-in layout change via a project migration as `0003_numbering_on.sql` did, so existing projects get it.
- [ ] **Step 4:** Whole composer suite → PASS (baseline unchanged).
- [ ] **Step 5:** Commit `report composer: reports pin the card revision`.

### Task 9: End-to-end on a throwaway stack

- [ ] **Step 1:** `df -h /`; start a stack from `~/aisc-revisions` under its own name and ports (see `~/aisc-second-instance.md`).
- [ ] **Step 2:** Create a project with a card like Mijke's v1 (provider "Eindhoven University of Technology (TU/e, Eindhoven Engine)...", description with "learning Dutch", Risk 5 vulnerability "Mijke's instructions do not fix the answer language..."), one evaluation, one closed checklist submission; generate a report (R1).
- [ ] **Step 3:** Save a correction (provider "Eindhoven Engine", description without "learning Dutch", Risk 5 "The locally hosted model does not always follow Mijke's instruction to reply in the language of the person's message"), amend the submission, start a second evaluation.
- [ ] **Step 4:** Check spec section 10 items 1-8: same `pid` on both evaluations; `project.system` has 1 row with `card_revision = 2`; ledger has `qualification.amended`, `card_version.revised`, `controls.submission.reopened` with reason; new report (R2) `pdftotext` shows "Version 1, revision 2", an Amendments block, and none of "TU/e", "learning Dutch", "do not fix the answer language"; regenerating R1 reproduces its text (diff of `pdftotext` outputs, ignoring the generation timestamp).
- [ ] **Step 5:** Stop and remove the throwaway stack. Report results to the user; deploying to aisc-063319 waits for a gap between test runs and the user's yes.
