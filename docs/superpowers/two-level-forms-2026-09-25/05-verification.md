# Two-level forms: independent verification (stage 5)

Date: 2026-09-25. Verifier: a separate agent that wrote none of this work. Every number below was run or read by the
verifier; nothing is copied from `04-progress.md`.

Code: `apps/qualification`, branch `feat/unified-modules`, HEAD `8f0ab50` at the start and at the end (no new commit by
the other session during verification). `git status --short` was identical before and after. The verifier changed no
repository file: a sha256 of every file outside `node_modules` and `.next`, taken first and checked last, differs only
in `tsconfig.tsbuildinfo` (git-ignored, rewritten by `tsc`/`next build`). This file is the only file written.

Scratch location: `$V=/tmp/claude-1001/-home-listuser/572e79f5-831d-4f75-909f-47cb45306c7a/scratchpad/ver`
(probe scripts, logs, snapshots). The three throwaway venvs, the probe container and the extracted backup copies were
deleted at the end. No `aisc-t-qual-*` or `ver-tlf-*` container is left; no other container was touched; ports 5432
and 5433 were never used.

---

## 1. Counts against the plan (03-plan section 6)

| Check | Command (from `apps/qualification` unless noted) | Result | Plan |
|---|---|---|---|
| vitest | `npx vitest run` | Test Files 99 passed, 4 skipped (103); Tests 1301 passed, 90 skipped (1391); exit 0 | same |
| tsc | `npx tsc --noEmit` | 0 errors, exit 0 | 0 |
| prisma | `DATABASE_URL=postgresql://x:x@127.0.0.1:1/x?schema=qualification npx prisma validate` | valid | valid |
| build | `npm run build` (no `next` process had `$A` as cwd) | exit 0; routes `/p/[project]/question-sets` (6), `/p/[project]/questionnaires` (5), the 5 `/forms*` (redirects) | same |
| ontology | fresh venv, `pytest -p no:cacheprovider -q` | 272 passed, 3 failed: `test_build.py::...all_nineteen_properties`, `test_example_mcas.py::...all_nineteen_properties`, `test_roundtrip.py::...every_airo_relation` | same 3, pre-existing |
| prefill | own `.venv` | 420 passed | 420 |
| renderer | fresh venv | 50 passed | 50 |
| agents | fresh venv, run from a scratch cwd with `-c .../pytest.ini --rootdir` | 168 passed | 168 |
| DB | `test/db/throwaway-db.sh` | Test Files 3 passed (3); Tests 89 passed (89); no `aisc-t-qual-*` before or after | same |

Applied migrations: `20260925090000_forms_are_data` sha256 `cbea212d...7557`, `20260925120000_the_default_form_is_fixed`
sha256 `b8338d12...dc4c`, unchanged (these are also the checksums Prisma recorded in the probe database).

## 2. Test integrity

Reference points: `~/aisc-backups/qualification-worktree-before-two-level-1701.tar.gz` (17:01, after the test author,
before any implementation: it already contains the new test files) and `$P/tlf/before-tests/tests.tar` (15:36, before
the test author).

- Backup (red run) vs now: 166 test, fixture and support files in both; none added, none removed; exactly one changed:
  `test/unit/builderState.test.ts`, lines 68, 115, 389, 450, 494, each `.map((r) =>` became
  `.map((r: BuilderState["rows"][number]) =>`. Type annotation only, no assertion or runtime change. This is the one
  authorised edit. **Integrity: pass.**
- Pre-author vs red run (what the test author changed), against spec section 8:
  - Deleted: `FormService.test.ts`, `formDraft.test.ts`, `formActions.test.ts`, `FormsPage.test.tsx`,
    `formExportRoute.test.ts`, `FormImport.test.tsx`, `FormBuilder.test.tsx`, `test/support/fakeFormStore.ts`,
    `test/db/forms.db.test.ts`. Exactly the nine of 8.2.
  - Changed: the files of 8.3 (support `forms.ts`, `annexDefaultForm`, `builderState`, `formLibrary`, `formChooser`,
    `FormChooser`, `editSystemPage`, `FormLine`, `formsLayout`, `widePage`, `SiteHeader`, `formsNoModel`,
    `formsDefaultIsFixed`, `QualificationService.forms`, `QualificationExporter`, `FormExportClient`, `AnsweredForm`,
    `QualifyFormBlocks`, `PrefillClient`, `prefillChoice`, `VerticalCard`), plus `services/prefill/tests/test_app.py`,
    which T50/T51 name as extended: its diff is additions only (0 lines removed). The lightly changed component files
    only rename `formVersionId`/`ownerFormName` per T40.
  - 35 new files, each with real assertions (for example `QuestionnaireService.test.ts` 40 tests / 110 `expect`,
    `twoLevelForms.db.test.ts` 70 / 176); none uses `.skip`, `.only`, `.todo` or `expect(true)`. Spot read: the T24 tests
    assert the fake store's call log is exactly `["insertQuestionnaireVersion"]` and that a forged `text` in a draft
    item resolves to the pinned set wording.

## 3. The migration (`prisma/migrations/20260925150000_two_level_forms/migration.sql`, 639 lines)

### 3.1 Line-by-line reading against spec 4.x

Every step of spec 4.2 is present, in order: capture `tlf_counts` (11-20); P1 (23-44, ids only, as plan 2.2); the
seven tables with the 3.1 DDL verbatim except the 50-byte item index name (47-175); the builtin level as seven
`INSERT ... SELECT` from the old rows (178-206); pass A with the jsonb list compare and `tlf_assigned` (210-265);
pass B with "highest matching set version", the Annex IV abort and the fallback plus NOTICE (269-354); C1 to C7 with
both the count and the zero-missing parts (357-460); the four card-column statements (463-467); four `DROP TABLE` and
five `DROP FUNCTION`, no CASCADE (470-478); the ten functions and triggers after the last drop, messages exactly 3.2
(481-603); C8 (606-639). No `BEGIN`/`COMMIT`/`CASCADE`/`IF EXISTS`/`CONCURRENTLY`, no row `UPDATE`/`DELETE`, no
`EXCEPTION` clause. `SELECT ... INTO pin` without `STRICT` correctly yields NULL on no match.

### 3.2 Probe on a database at live's state

Own script, own container (`postgres:14-alpine`, the live image), random port:

```bash
$V/probe/start.sh                              # init/platform-db.sql, init/project-databases.sql, platform migrations
cd $V/probe/base && prisma migrate deploy      # a copy of prisma/ holding migrations up to 20260925120000 only
psql < $V/probe/live_seed.sql                  # gen_live.py: 1 project, 1 core.system, 1 card with form_version_id NULL,
                                               # 14 answers (3 KB each, newline, quote, non-ASCII), 1 risk, the real
                                               # mcas.ttl/mcas.jsonld as the knowledge graph, 18 KB card JSON, 1 component
$V/probe/snap.sh platform before               # pg_dump --data-only of the 5 history tables and core, schema dump,
                                               # per-row md5 + ctid + xmin
cd $V/probe/full && prisma migrate deploy      # the repository's migrations dir, byte-identical copy
$V/probe/snap.sh platform after; diff ...
```

State before: 1 form, 1 version, 14 questions, 14 version rows, 1 card NULL, 14 answers (live's facts). Results:

- `prisma migrate deploy`: exit 0 in 1.4 s, "All migrations have been successfully applied".
- Every history row identical including `ctid` and `xmin`: no UPDATE of any card, answer, risk, graph or component
  row, not even a no-op one.
- `pg_dump` data of `qualification_answer` (43,938 bytes), `qualification_risk`, `knowledge_graph` (102,964 bytes),
  `card_component` and all of `core`: byte-identical. `qualification`: identical except the COPY header's column name
  `form_version_id` -> `questionnaire_version_id`. Card JSON md5 unchanged; the card's version stays NULL.
- Wording: `(version, position, key, md5(text), citation, required, annex_point, group_label)` for every old row equals
  the same list from `questionnaire_version_item` joined to `question_set_version_item` after.
- 10 new triggers present; the three card triggers still present; 8 FKs, all `ON DELETE RESTRICT`; the answer unique
  index untouched; new tables owned by `qualification_rw`; `dashboard_ro` got SELECT through default privileges.
- Triggers effective (each in a rolled-back transaction as `qualification_rw`): UPDATE/DELETE of versions and items
  refused with the 3.2 messages; question identity and delete refused; second builtin version refused; retire or
  second builtin refused by the CHECKs; unlisting and renaming refused; delete of a questionnaire row refused; cross-set
  set item refused; questionnaire item not a set item refused by `questionnaire_version_item_set_item_fkey`; a card
  pointed at an unknown version refused by `qualification_questionnaire_version_id_fkey`; description change and
  pointing the card at `annex-iv-default-v1` allowed.
- Idempotence: a second `prisma migrate deploy` prints "No pending migrations to apply." Running the SQL file again by
  hand fails at its first statement (`relation "qualification.form" does not exist`) and leaves schema and rows
  identical.

### 3.3 Adversarial fixture (`gen_rich.py`, 54 forms, 165 versions, 212 questions, 4,838 version rows, 3 cards)

Custom forms with several versions (acme v1..v4, a reword, a removal, an addition, v3 = v2 with other blocks);
cross-form picks (mix v1 pins the old wording, mix v2 the new); a use-once form with an own question and a pick; two
forms picking the same hand-edited wording; a pick differing only in `group_label`; a question owned by a form with no
version and picked elsewhere; a form with no version; a form with an empty v1; unlisted forms named "Annex IV" and
twice "acme ai POLICY" (allowed before); a form with 150 questions x 30 versions plus 14 Annex picks; 40 small forms;
text with newline, quotes, backslash, trailing space, non-ASCII; cards on mix v1 (not latest), NULL, acme v4 (latest).

`prisma migrate deploy`: exit 0 in 2.1 s. History rows identical (ctid, xmin); all 4,838 wording rows identical before
and after; questionnaire versions keep id, number, blocks, created_at. Pins exactly as spec 4.2 says: acme v3 shares
`acme-v2`; mix v1 -> `acme-v1`; once's pick -> `acme-v2` (highest with that wording); the two hand-edited picks share
one fallback `acme-v4`; the label-only difference makes `acme-v5`; the versionless owner gets `ghost-v1` with the one
question at position 0; the unlisted "Annex IV" and duplicate-name sets are created retired, so no name clash; the 40
small forms make 80 set versions (v3 reuses v2). App code (`QuestionnaireService`/`QuestionSetService` with the real
repository, scratch vitest config outside the repo) reads the migrated library, resolves every version, `resolve(null)`
and `resolve("annex-iv-default-v1")` equal `annexDefaultVersion()`, a migrated questionnaire and a migrated set take a
new version (new question keyed `s-acme:q4`, labels carried), retiring works and the builtin refuses.

### 3.4 Aborts and atomicity (through `prisma migrate deploy`, each on a copy of the live-state DB)

| Fixture | Error | After |
|---|---|---|
| f1 listed custom form "annex iv" owning a question | 23505 `question_set_active_name_key` | rows and schema identical, old tables present, no new table |
| f2 custom row with `group_label = ''` | 23514 `question_set_version_item_group_label_check` | same |
| f3 a pick of Annex IV 1a with other wording | P0001 `form version fv-x-1 pins wording of annex-iv-1a that no version of Annex IV has` | same |
| f4 description of 600 characters | 23514 `questionnaire_description_length` | same |

After a failure `_prisma_migrations` holds the row unfinished; the next `migrate deploy` stops with P3009;
`prisma migrate resolve --rolled-back 20260925150000_two_level_forms` clears it and the next deploy fails again the
same way on the same data. The migration is one transaction under Prisma.

### 3.5 The checks fire (mutation test)

Copies of the migration in `$V/probe/mut/`, each with one sabotage, run inside `BEGIN ... ROLLBACK` as
`qualification_rw` on the adversarial fixture. The unmodified control completes.

| Sabotage | Raised |
|---|---|
| a stray set | C1 expected 48, found 49 |
| a stray question | C2 expected 212, found 213 |
| builtin scope altered | C2 expected 0, found 14 |
| questionnaire description altered | C3 expected 0, found 53 |
| blocks altered | C4 expected 0, found 164 |
| item positions shifted | C5 expected 0, found 4824 |
| a cross-set wording row | C6 expected 0, found 1 |
| default items repointed to a copy `annex-iv-v2` | C7 expected 0, found 14 |
| a history row written | C8 expected 1, found 2 |

## 4. Conformance (T1 to T63, brief decisions 1 to 10)

Read in code, beyond the green tests:

- **Separation (dec. 1, 9; T24, T28).** The builder reducer has only tick/untick/selectSet/deselectSet/move/remove/
  toggleBlock/setName/acceptUpdate/acceptAllUpdates; no "+ New question", Edit or copy in `QuestionnaireBuilder.tsx`.
  Server side, `QuestionnaireService.saveDraft` writes only through `insertQuestionnaireVersion` (questionnaire,
  version, items), checks every item is an existing set item and never reads wording from the draft. The only
  questionnaire-side path that writes a set is the self-contained import (spec T54).
- **Pinning and update available (dec. 2; T25, T26, T29).** `updatesAvailable` compares the five wording fields with
  the pinned source, same wording is no update, retired groups count.
- **Cards never change (dec. 3; T40, T41, T42).** `createFromForm` resolves the posted version server side and always
  creates; the migration proved no card row is written. The card page offers "Move to vM" only for the current card.
- **Retire (dec. 5; D9).** One-way in services and triggers; a POST, so `may_write` in the current project through
  `src/middleware.ts`; builtin rows refused in services and by the CHECKs.
- **created_by (dec. 6; D4).** `callerName()` reads the same token header the middleware sends to the platform for
  this request; claims `preferred_username`, `email`, `sub`; "unknown" otherwise.
- **Export/import (dec. 7; T47 to T54).** References by default, `bundle=self-contained` json only; reference import
  resolves by ids only and lists missing items without storing; the builder save re-validates everything.
- **Redirects (T62), default fixed (T30, T34), coverage by set id with old keys still read (T43), prefill uses pinned
  wording (T58), Dockerfile last line (T59, one line changed, fixture compare), DEPLOY.md note (backup, baseline),
  header links (T60), no model (T61).** All as specified.
- **Security of the routes.** Both export routes are GETs any member may call (install-wide library by design); ids are
  DB lookups; filenames come from the prefill `slug` (ASCII, dashes); `no-store`; CSV formula guard applies to the
  questionnaire CSV too. Both prefill endpoints sit behind the `ServiceTokens` middleware, and
  `QuestionnaireFileClient` sends `X-AISC-Service-Token` (tested). Import is a POST (writers only), 10 MB cap in prefill.

## 5. Regression of rounds 1 and 2

All present and green: identity block always included and locked (`QuestionnaireBuilder.test.tsx`, and the DB blocks
CHECK has no identity block); PDF escaping and the `url_fetcher` allow list (`test_pdf_safety.py`, in the 50);
CSV formula guard round trip (`test_form_export.py` R50, `test_form_import.py` R53); service token on every sidecar
client (`serviceTokens.test.ts`, `QuestionnaireFileClient.test.ts`); docx expansion cap (`test_documents.py` R70).

## 6. Findings

No blocker, no major.

| Id | Severity | T-id | File:line | Problem | Failure scenario | Suggested fix | Cat. |
|---|---|---|---|---|---|---|---|
| H1 | minor | T8, D7 | `prisma/migrations/20260925150000_two_level_forms/migration.sql:314-345` | A fallback set version made for hand-edited pinned wording becomes the set's latest version. | Probe: odd's "Hand edited?" became `acme-v4`/`acme-v5`; afterwards the owner's own questionnaire and every other one pinned to acme show "update available: Acme AI policy v5 words it: Hand edited?". Live has no custom form, so unreachable there. The NOTICE is also invisible under `prisma migrate deploy`. | Product decision: keep (spec D7), or abort on unmatched custom wording like Annex IV. | B |
| H2 | minor | T8, plan 3 item 9 | `migration.sql:227`, index at 62 | A listed custom form named "Annex IV" (any case) owning questions aborts with a bare unique violation. | Probe f1: 23505 on `question_set_active_name_key`, rolled back cleanly. Live has none. | Keep, or add a precondition with a clear message. | B |
| H3 | minor | deploy | `/home/listuser/aisc-install/docker-compose.development.yml:320` | `until npx prisma migrate deploy; do echo waiting for postgres ...` retries forever. | A failed migration shows as "waiting for postgres" forever (P3009 from the second try); `qualification-web` and `report-grants` never start. Outside this change's allowed scope (no compose edits). | Run the migration as a one-off during this deploy (checklist step 6); later, make the loop retry only on connection errors. | B |
| H4 | minor | T54 | `src/server/services/QuestionnaireService.ts:347`; `src/app/p/[project]/questionnaires/import/actions.ts:54-73` | The self-contained file comes back from the browser; `groupLabel` is not re-validated in TS (text, citation, required, annexPoint and blocks are). | A tampered POST with `groupLabel: ""`, 500 characters or a number gives an unhandled Prisma or CHECK error (500). The DB CHECK keeps the data correct. | Validate `groupLabel` in `importSelfContained`: string, trimmed 1..120, else null (or the T51 message). | A |
| H5 | nit | T52, T54, D18 | `QuestionnaireService.ts:311-324` | A zero-item questionnaire exported self-contained cannot be imported: "A question set needs at least one question." | Round trip of an empty questionnaire fails, though T52 writes and reads it. | Decide: refuse at export, or allow import of zero items without making a set. | B |
| H6 | nit | T52, T54 | `services/prefill/prefill/questionnaire_file.py:136,153` | Self-contained import collapses whitespace in question text. | A question text with a line break does not round-trip exactly (the spec accepts "compared after collapse"). | None, or keep newlines on read. | C |
| H7 | nit | T34, T20 | `QuestionnaireService.ts:407`, `QuestionSetService.ts:156,180` | A listed questionnaire or set with no version (possible only from hand-made old data, which the migration keeps) is silently skipped yet still holds its name. | "A questionnaire called Ghost already exists" with no Ghost listed. Live has none. | Show them, or refuse them in the migration precondition. | B |
| H8 | nit | T62 | `src/app/p/[project]/forms/[formId]/export/route.ts:16` | `project` goes into `Location` unencoded (formId is encoded). | Harmless (the middleware answers 404 for an unknown project first; header validation refuses CR/LF). | `encodeURIComponent(project)`. | A |
| H9 | nit | perf | `QuestionnaireService.ts:398-437`, `QuestionSetService.ts:148-192` | Every list, chooser and builder page loads every version of every questionnaire and set with all items, one query each. | Fine at live's size (1 set, 1 questionnaire); grows with history. | Load latest versions only when the library grows. | B |
| H10 | nit | T35, T39 | `src/app/p/[project]/system/edit/page.tsx:42` | `?questionnaire=<id>` opens the latest version of a retired or unlisted questionnaire too. | A kept link fills a retired questionnaire; allowed by "still resolvable", not by the chooser. | Decide whether retired should also refuse `?questionnaire=`. | C |
| H11 | nit | T49, D22 | `QuestionSetService.ts:240,267` | The server honours `alsoQuestionnaire` for origin `builder` too; the UI offers it only on import. | Only via a hand-made POST by a writer; result is a valid questionnaire. | Ignore it unless origin is import, or accept as is. | C |
| H12 | nit | T15, T24, T35 | `QuestionSetService.ts:376`, `QuestionnaireService.ts:226`, repositories `retire*` | A retire racing a save (or a double retire) surfaces as an unhandled trigger error. | Two writers at the same second: one gets a 500 instead of a message; the data stays correct. | Map P0001 "is retired" / "can only be retired, once" to the existing messages. | A |

A (mechanical): H4, H8, H12. B (product owner): H1, H2, H3, H5, H7, H9. C (unsure): H6, H10, H11.

## 7. Deploy readiness for live

Verdict: **ready to deploy.** The A fixes are robustness only and can follow; none touches the migration or live's
data. The migration was proven on a synthetic live-state copy, so the dry run on a copy of the real data (step 3) is
the one step that remains before the irreversible run.

Stack facts: the running stack is compose project `aisc` from `~/aisc-install` (always `-p aisc`);
`qualification-migrate` runs `prisma migrate deploy` as `qualification_rw` (the owner of the form tables and
functions, as the migration needs), and `qualification-web` overrides the image command, so the Dockerfile change does
not affect live.

1. **Freeze the code.** Decide the commit (the working tree is uncommitted, and another session commits on this
   branch). Note HEAD. The image is built from the working tree as it is then.
2. **Read-only checks on live** (psql as a read-only role): `_prisma_migrations` has 090000 and 120000 finished with
   checksums `cbea212d...7557` and `b8338d12...dc4c`, and no unfinished row; `form` 1 (builtin), `form_version` 1,
   `form_question` 14, `form_version_question` 14; `SELECT count(*) FROM qualification.form WHERE origin <> 'builtin'`
   is 0; `qualification` 1 row, `qualification_answer` 14. Any difference: stop.
3. **Backup and dry run.** `docker exec postgres pg_dump -U <superuser> -d platform -Fc > ~/aisc-backups/platform-before-two-level-forms-$(date +%F-%H%M).dump`
   (the whole database: the qualification tables have FKs into `core`), and the DEPLOY.md
   `pg_dump --schema=qualification` plain dump. Check `pg_restore -l` lists both schemas. Restore the `-Fc` dump into a
   throwaway `postgres:14-alpine` on a random port (create the roles first with `init/platform-db.sql`), run
   `prisma migrate deploy` from the frozen tree against it, and compare the card, answers and graph rows (md5, as
   `$V/probe/snap.sh` does). Exit 0 and identical rows: go on. Remove the throwaway container.
4. **Keep the way back.** `docker tag $(docker inspect qualification-web --format '{{.Image}}') aisc-qualification-web:pre-two-level`
   and the same for `qualification-migrate`.
5. **Stop the writer.** `docker compose -p aisc -f docker-compose.development.yml stop qualification-web` (the old code
   expects the form tables, and the rename takes an ACCESS EXCLUSIVE lock on `qualification.qualification`).
6. **Build and migrate once, watching the exit code.**
   `docker compose -p aisc -f docker-compose.development.yml build qualification-migrate qualification-web`, then
   `docker compose -p aisc -f docker-compose.development.yml run --rm --no-deps qualification-migrate npx prisma migrate deploy`.
   Expect "Applying migration `20260925150000_two_level_forms`" and exit 0. Do not use the service's own loop for this
   run (H3).
7. **Read-only post-checks.** `question_set` 1, `question_set_version` 1, `question` 14, `question_set_version_item` 14,
   `questionnaire` 1, `questionnaire_version` 1, `questionnaire_version_item` 14; `qualification` 1 with
   `questionnaire_version_id` NULL; `qualification_answer` 14; `to_regclass('qualification.form')` NULL; the
   `_prisma_migrations` row for 20260925150000 finished.
8. **Start and smoke.** `docker compose -p aisc -f docker-compose.development.yml up -d qualification-web` (the migrate
   service reruns and prints "No pending migrations"). Open `/qualification/p/<project>/questionnaires` and
   `/question-sets`; the card page shows "Questionnaire: Annex IV default v1"; download its JSON, CSV and PDF; `/forms`
   redirects to `/questionnaires`.

Rollback:

- **The migration fails in step 6:** the database is unchanged (one transaction, proven in 3.4). Run
  `prisma migrate resolve --rolled-back 20260925150000_two_level_forms` (same one-off `run`), start the old image
  (`aisc-qualification-web:pre-two-level`), and read the error before trying again.
- **Undo after success:** stop `qualification-web`; restore the qualification schema from the step 3 dump
  (`pg_restore --clean --if-exists -n qualification -d platform <dump>` as the superuser; this also restores
  `_prisma_migrations` without the new row); start the tagged pre-two-level images. Any card saved after the deploy is
  lost this way: export it first.
