# Two-level forms: implementation progress (stage 4)

Half A (implementer A): plan tasks 0 to 12. Half B continues from task 13 with this log and `03-plan.md`.
Short names as in the plan (`A`, `P`, `VT`, `PREF`, `ONTO`, `REND`, `AGENTS`, `DUMMY`).

## Task 0. Baseline (done)

- Branch `feat/unified-modules`, HEAD `8f0ab50` (unchanged since the plan).
- `$P/tlf/impl-status-before.txt` (134 lines), `$P/tlf/impl-tests.sha` (166 files),
  `$P/tlf/impl-untracked-src.tar` (32 entries) written.
- Applied migrations hash to `cbea212d...7557` and `b8338d12...dc4c` (as pinned).
- `bash $P/tlf/run-all.sh impl-before`: vitest Files 46 failed, 53 passed, 4 skipped (103); Tests 672 failed,
  629 passed, 90 skipped (1391). ontology 12 failed, 263 passed. prefill 109 failed, 311 passed. renderer 50
  passed. agents 168 passed. tsc 60 errors, 0 outside `test/`. Exactly the plan's table.
- Venvs present. No `aisc-t-qual-*` container. DB baseline (optional) skipped.

## Task 1. Schema, migration, generate (done)

- `prisma/schema.prisma`: the four Form models removed, the seven models of spec 3.3 added; the questionnaire
  item position key is `questionnaire_version_item_version_id_position_key` (plan section 3 conflict 1);
  `Qualification.questionnaireVersionId` / `questionnaireVersion` / its index replace the form ones.
- New `prisma/migrations/20260925150000_two_level_forms/migration.sql`, written from spec 4.2 and plan section 2
  (not copied from the scratch reference): capture `tlf_counts`; P1; the seven tables with the DDL of 3.1 (index
  name above); builtin level; pass A (jsonb list compare, `tlf_assigned`); pass B (pin = highest matching set
  version, fallback set version with NOTICE, Annex IV mismatch raises); C1 to C7 (count and zero-missing parts);
  the four card-column statements; four DROP TABLE and five DROP FUNCTION; the ten functions and triggers; C8.
- `npx prisma generate` run (rewrites `node_modules/.prisma`, shared with the other session; the live stack is
  image-based and unaffected).
- Proof: `twoLevelSchema` + `twoLevelMigration` 24 passed; `prisma validate` valid; the two applied migrations
  keep their hashes. Early DB checkpoint `test/db/throwaway-db.sh`: 89 tests, 87 passed, 2 failed (exactly the
  two T3 resolve tests that need tasks 5, 8, 9). No `aisc-t-qual-*` container left.

## Task 2. Dockerfile and DEPLOY.md (done)

- `Dockerfile`: last line only, now `CMD ["sh", "-c", "npx prisma migrate deploy && npx next start -p 3000"]`.
- `DEPLOY.md`: line 63 reworded as the plan says; two new paragraphs (pg_dump backup before
  20260925150000_two_level_forms; baselining a `db push` database with `prisma migrate resolve --applied`).
  No em dash added.
- Proof: `dockerfile.test.ts` 6 passed.

## Task 3. Ontology coverage (done)

- `services/ontology/airo_min/coverage.py`: new `_owner_name(q)` = `ownerSet`, else `ownerForm`; `_owner_key`
  prefers `ownerSetId`, then `ownerFormId`, then the name; docstring states both key styles. No other
  `q["ownerForm"]` read remains. Output keys and summaries unchanged.
- Proof: `test_owner_set_keys.py` + `test_coverage.py` 38 passed; whole suite 272 passed, 3 failed (the three
  pre-existing `nineteen_properties` x2 and `every_airo_relation`).

## Task 4. Prefill questionnaire file (done)

- New `services/prefill/prefill/questionnaire_file.py` (stdlib + `prefill.*` only): `QuestionnaireFileError`,
  `write_questionnaire`, `read_questionnaire`, constants (`MAX_ITEMS = 200`, `SCOPE`, `LOCAL_ID`, `BLOCKS`).
  `write_questionnaire` also checks bundle, 200 limit and missing wording (in that order) and raises
  `QuestionnaireFileError`, so the endpoint only maps it to 422.
- `services/prefill/app.py`: appended `QuestionnaireItem` / `QuestionnaireIn` / `QuestionnaireExportRequest`
  models (wording optional; absent key = missing wording, a null text/citation/required also counts as
  missing), `POST /questionnaires/export`, `POST /questionnaires/import` (413 over `MAX_BYTES`). One import
  line added at the top; nothing else above changed.
- `services/prefill/README.md`: both endpoints documented.
- Decisions where the spec is silent: `read_questionnaire` returns `version` as given or `None` when absent;
  missing `blocks` / `items` read as `[]`; a blank `groupLabel` string is refused with the groupLabel message
  (the DB check would refuse it).
- Proof: `test_questionnaire_file.py` 84 passed; `test_app.py` 81 passed; prefill suite 420 passed.

## Task 5. Types and builtin twins (done)

- `src/domain/forms/types.ts` replaced by spec 5.1 (`ResolvedQuestion` with set fields,
  `ResolvedQuestionnaireVersion`, `ResolvedSetVersion`, `VersionStamp`, `QuestionnaireResolver`).
  `ResolvedFormVersion` / `FormResolver` gone (no aliases).
- `src/domain/forms/legacy.ts`: `ANNEX_SET_ID`, `ANNEX_SET_VERSION_ID`, `ANNEX_SET_NAME`,
  `DEFAULT_QUESTIONNAIRE_ID`, `DEFAULT_VERSION_ID`, `DEFAULT_QUESTIONNAIRE_NAME`, `ANNEX_DESCRIPTION`,
  `resolveQuestionnaireVersionId`, `annexDefaultVersion()`, `annexSetVersion()`. `DEFAULT_FORM_ID` and
  `resolveFormVersionId` gone.
- Proof: `annexDefaultForm` + `annexDefaultExportFixture` + `keyQuestions` 41 passed (24 + 2 + 15).

## Task 6. Pure domain modules (done)

- New `src/domain/forms/questionSetDraft.ts` (`SetDraft`, `SetDraftQuestion`, `parseSetDraft`, `sameSetContent`;
  description is trimmed as the test wants), `setEditorState.ts` (`QuestionValues`, `SetRow`, `SetEditorState`,
  `SetEditorAction`, `SetEditorInit`, `initialSetEditorState`, `setEditorReducer`, `toSetDraft`; row keys `r<n>`),
  `questionnaireDraft.ts` (`QuestionnaireDraft`, `QuestionnaireDraftItem`, `parseQuestionnaireDraft`,
  `sameQuestionnaireContent`), `moveCard.ts` (`rewordedSince`, `droppedAnswers`, `moveNotice`, `newerVersion`),
  `references.ts` (`ReferenceItem`, `FoundSetVersion`, `missingReferences`).
- `library.ts`: `LibraryGroup` and `sourceUpdates` gone; `SetGroup = {setId, setName, versionId, versionNumber,
  retired, questions}`, `SetUpdate = {kind: "reworded", question, versionId, versionNumber} | {kind: "removed",
  setName, versionNumber}`, `updatesAvailable(rows, groups)`. `filterLibrary`, `overlapHints`, `overlapLabel`
  unchanged.
- `builderState.ts` rewritten: picks only (`BuilderRow`, `BuilderState`, `BuilderAction`, `BuilderPick`,
  `BuilderInit`, `initialBuilderState`, `isTicked`, `builderReducer`, `toQuestionnaireDraft`). `edit`,
  `startFrom` and `picks` open with every pick's `viaSetId = question.setId` and those sets selected in first
  appearance order. `toDraft` is gone (the old `FormBuilder.tsx` still imports it: half B).
- `chooser.ts`, `formDraft.ts`, `useOnceName.ts`, `annexPoints.ts`, `blocks.ts` untouched.
- Proof: questionSetDraft 26, setEditorState 12, questionnaireDraft 22, formLibrary 25, builderState 38,
  moveCard 18, references 7, useOnceName 9: 157 passed.

## Task 7. callerName (done)

- New `src/server/access/callerName.ts`: `identityFromToken` (base64url payload, alphabet checked, first non-blank
  of preferred_username / email / sub, trimmed, cut to 200) and `callerName()`.
- Proof: `callerName.test.ts` 10 passed.

## Task 8. Repositories and QuestionSetService (done)

- New `src/server/repositories/QuestionSetRepository.ts`: `QuestionSetRepository(db = prisma)` with `listSets`,
  `findSet`, `findSetVersion`, `setVersionsOf`, `findQuestion`, `questionsOf`, `insertSetVersion(plan)` (one
  interactive `$transaction`, optionally with the questionnaire plan), `retireSet`; exported types
  `SetVersionInsert`, `QuestionnaireVersionInsert`, `SetVersionRow`, the include `SET_VERSION_INCLUDE`, and the
  helper `writeQuestionnaireVersion(tx, plan)`.
  Deviation: it also has `listQuestionnaires()` (read only). `saveDraft(..., {alsoQuestionnaire})` must refuse a
  name a listed questionnaire has with the questionnaire message, and the fake store's P2002 cannot tell the set
  name index from the questionnaire one, so the service checks first. `QuestionnaireRepository` has the same method.
- New `src/server/repositories/QuestionnaireRepository.ts`: `extends QuestionSetRepository`; adds
  `listQuestionnaires`, `findQuestionnaire`, `findQuestionnaireVersion`, `questionnaireVersionsOf`,
  `insertQuestionnaireVersion`, `retireQuestionnaire`; `QUESTIONNAIRE_VERSION_INCLUDE`, `QuestionnaireVersionRow`.
- New `src/server/services/QuestionSetService.ts`: `QuestionSetService(repository, {newId, now})` with `list`,
  `groups`, `resolveSetVersion`, `latest`, `atNumber`, `history`, `saveDraft`, `retire`; singleton
  `questionSetService`. Also exported helpers other server code may reuse: `toResolvedQuestion`,
  `toResolvedSetVersion`, `stampOf`, `libraryOrder`, `uniqueConflict`, types `SetListRow`, `SaveSetOptions`,
  `SaveSetResult`. Ids (set, version, question, questionnaire) all come from `newId()`; scope `s-<setId>`,
  local ids `q<n>` with n = 1 + max over every question the set owns. For an existing set the draft's name and
  description are replaced by the set's before parsing (D21), so a blank draft name is not an error there.
- Proof: `QuestionSetService.test.ts` 36 passed.

## Task 9. QuestionnaireService (done)

- New `src/server/services/QuestionnaireService.ts`: `QuestionnaireService(repository, {newId, now})` with
  `resolve` (null is `annexDefaultVersion()`, no repository call), `latestVersion`, `exportable`, `library`,
  `chooserOptions` (library row + `versionIds`), `history`, `saveDraft`, `retire`, `resolveReferences`,
  `importSelfContained`; singleton `questionnaireService`. Types `QuestionnaireLibraryRow`,
  `QuestionnaireChooserOption`, `SaveQuestionnaireOptions`, `SaveQuestionnaireResult`, `SelfContainedFile`,
  `ResolvedReferences`. It builds its set groups (for `updates`) through an internal `QuestionSetService` on the
  same repository. `importSelfContained` checks the set name (T12) then the questionnaire name (T22) before one
  `insertSetVersion` with `plan.questionnaire`; the set and questionnaire descriptions are the file's.
  `retire` refuses unlisted ("That questionnaire cannot be retired.").
- Proof: `QuestionnaireService.test.ts` 40 passed; `formsDefaultIsFixed.test.ts` 24 passed, 1 failed (the
  expected `R44 T30 the questionnaire actions export exactly ...`, task 15).

## Task 10. Server-side consumers (done)

- `src/server/services/QualificationExporter.ts`: type `ResolvedQuestionnaireVersion`; per question exactly
  `{key, text, citation, required, annexPoint, ownerSet, ownerSetId, ownerBuiltin}` (from `setName`, `setId`,
  `setBuiltin`); `form.name` = `questionnaireName`.
- `src/server/services/OntologyService.ts`: `forms: QuestionnaireResolver = questionnaireService`; resolves
  `q.questionnaireVersionId ?? null`.
- `src/server/services/QualificationService.ts`: `forms: QuestionnaireResolver = questionnaireService`; reads the
  posted `questionnaireVersionId`, else `formVersionId` (D20), else null (helper `postedId`); unknown id throws
  `FormValidationError("The questionnaire this was filled with no longer exists. Reload the page.")` before the
  platform is called; the parser's `formVersionId` is stripped and `repo.create` gets `questionnaireVersionId`;
  `startingPoint()` returns `fromQuestionnaireVersionId`.
- `src/server/forms/QualificationFormParser.ts`: parameter type only; output field stays `formVersionId`.
- `src/server/repositories/QualificationRepository.ts`, `src/domain/cardVersions.ts`: `formVersionId` ->
  `questionnaireVersionId`.
- `src/app/api/qualifications/[id]/extracted/route.ts`: only the import and the resolve line (now
  `questionnaireService.resolve(q.questionnaireVersionId ?? null)`).
- `src/lib/prefillChoice.ts`, `src/app/p/[project]/qualify/new/useDocumentPrefill.ts`: type rename only (the
  spec already carries the resolved, pinned wording). `PrefillClient.ts` untouched.
- `test/fixtures/mcas-export-before.json` not touched.
- Proof: QualificationExporter 13, annexIdentity 4, QualificationService.forms 12, PrefillClient 10,
  prefillChoice 16, QualificationFormParser 45, fillerReadsItsProject 4, agentToken 10, writeAccess 16,
  aiCardExport 10, cardSubmission 2: 142 passed. (Plan section 3 conflict 4 resolved as foreseen: the three
  committed tests that mock `FormService` pass with the real `QuestionnaireService` loaded.)

## Task 11. File clients (done)

- `src/server/services/FormExportClient.ts`: `write(list: QuestionList, format)` with exported
  `QuestionList = {name, version, questions: {text, citation, required, annexPoint}[]}`; body, messages, token
  and URL unchanged.
- New `src/server/services/QuestionnaireFileClient.ts`: `QuestionnaireFileClient(baseUrl, fetchImpl,
  serviceToken)`, `write(file, bundle)` -> `{ok: true, filename, contentType, content} | {ok: false, status,
  error}`, `read(file)` -> `{ok: true, file} | {ok: false, status, error}`; 503 / 502 messages of the plan; a 4xx
  with a string `detail` keeps status and detail, anything else is 502. Types `QuestionnaireBundle`,
  `QuestionnaireFileItem`, `QuestionnaireFileInput`, `QuestionnaireFile`, `QuestionnaireWriteResult`,
  `QuestionnaireReadResult`; singleton `questionnaireFileClient`.
- Proof: FormExportClient 9, QuestionnaireFileClient 14, serviceTokens 10, FormImportClient 7: 40 passed.

## Task 12. DB proof (done)

- `npx prisma generate` (second run), then `test/db/throwaway-db.sh`: Test Files 3 passed (3), Tests 89 passed
  (89). `docker ps -a | grep aisc-t-qual-`: none. No other container touched.

## Split checkpoint (half A's last act), 2026-09-25

- HEAD `8f0ab50`, unchanged all through (no commit by the other session meanwhile).
- `bash $P/tlf/run-all.sh split`: vitest Test Files 26 failed, 73 passed, 4 skipped (103); Tests 366 failed,
  935 passed, 90 skipped (1391). ontology 272 passed, 3 failed (pre-existing). prefill 420 passed. renderer 50
  passed. agents 168 passed. Logs: `$P/tlf/logs/split-*.log`.
- Per file: every half A file of tasks 1 to 11 green at the plan's counts. The 26 failing files are exactly the
  plan's "still red at the split" table with exactly its failed counts, except `editSystemPage.test.tsx`: 29/32
  failed (plan 30/32), one more passing. That is the +1 against the plan's "about 934 passed, 367 failed".
- tsc (`$P/tlf/logs/split-tsc.log`): 78 errors, in `src/app/p/[project]/forms/FormBuilder.tsx` (32),
  `forms/import/FormImport.tsx` (3), `forms/libraryData.ts` (2), `forms/new/page.tsx` (1),
  `qualify/[id]/AnsweredForm.tsx` (6), `qualify/[id]/page.tsx` (1), `qualify/new/QualifyForm.tsx` (3),
  `system/edit/page.tsx` (2), `src/domain/forms/chooser.ts` (1), `src/domain/forms/formDraft.ts` (1),
  `src/server/repositories/FormRepository.ts` (14), `src/server/services/FormService.ts` (7), all half B's (to
  rewrite or delete), plus `test/unit/builderState.test.ts` (5, see below). Zero in any file half A created or
  edited.
- DB: 89 passed (task 12).
- `sha256sum -c --quiet $P/tlf/impl-tests.sha`: no output (every test, fixture and support file byte-identical).
- `git status --short` differs from `$P/tlf/impl-status-before.txt` only by `DEPLOY.md`, `Dockerfile` (M) and the
  new untracked half A files (the new files under `src/domain/forms/` are inside an already untracked directory).
  `git diff --stat -- Dockerfile`: one line. No em dash in any file half A wrote or edited.

## Test observations (recorded, not edited)

- `test/unit/builderState.test.ts` lines 68, 115, 389, 450, 494: `error TS7006: Parameter 'r' implicitly has an
  'any' type`. The file's helper `b()` returns `{ ...m, act }` where `m` is `loadSrc(...)`'s `any`, so the spread
  (and so `act` and every `s`) is `any`; no source change can type it. All 38 tests pass at run time. It was
  among the 60 baseline tsc errors (13 there, 5 left). Plan section 6.1 expects tsc 0 errors at the end: these 5
  will remain unless the test is changed, which is not ours to do. Half B: report, do not edit.

## For half B (handover)

- Start with the plan's section 1.3 checkpoint; compare HEAD with `8f0ab50`.
- Venvs kept for you: `$P/venv-ontology`, `$P/venv-system_card_renderer`, `$P/venv-agents`, `$P/agents-cwd`
  (prefill uses its own `.venv`). Backups: `$P/tlf/impl-untracked-src.tar` (task 16 needs it),
  `$P/tlf/impl-tests.sha`, `$P/tlf/impl-status-before.txt`.
- Not deleted (task 16 does): `src/domain/forms/formDraft.ts`, `src/server/services/FormService.ts`,
  `src/server/repositories/FormRepository.ts`, the old `/forms` UI, `FormImportClient.ts` stays.
- Interfaces ready to import: see tasks 5 to 11 above. Names half B will need most:
  `questionSetService` (`list`, `groups`, `history`, `atNumber`, `latest`, `saveDraft(draft, {setId?, origin?,
  createdBy, alsoQuestionnaire?})`, `retire`), `questionnaireService` (`resolve`, `latestVersion`, `exportable`,
  `library`, `chooserOptions`, `history`, `saveDraft(draft, {questionnaireId?, listed, origin?, createdBy,
  systemName?})`, `retire`, `resolveReferences`, `importSelfContained(file, {setName, questionnaireName,
  createdBy})`), `callerName()`, `formExportClient.write({name, version, questions}, format)`,
  `questionnaireFileClient.write/read`, `initialSetEditorState` / `setEditorReducer` / `toSetDraft`,
  `initialBuilderState` / `builderReducer` / `toQuestionnaireDraft` / `isTicked`, `updatesAvailable`,
  `SetGroup`, `moveNotice` / `rewordedSince` / `newerVersion`, `missingReferences`.
- The old builder imported `toDraft`, `LibraryGroup`, `sourceUpdates`, `ResolvedFormVersion`, `FormResolver`,
  `DEFAULT_FORM_ID`, `resolveFormVersionId`: all gone on purpose (tests assert it), no aliases.
- `prisma generate` rewrote `node_modules/.prisma` (twice); the live stack is image-based and unaffected. Nothing
  was migrated, rebuilt, restarted or deployed; no commit.

---

# Half B (implementer B): plan tasks 13 to 19

## Start checkpoint (plan 1.3, half B's first act)

- Branch `feat/unified-modules`, HEAD `8f0ab50` (unchanged; no new commit all through half B). `git status` matched
  half A's handover. Venvs present. `npx prisma generate` run (third run, plan 4.3 item 3).
- `run-all.sh b-start`: vitest Files 27 failed, 72 passed, 4 skipped; Tests 367 failed, 934 passed, 90 skipped. The
  extra failing file against half A's split was `formUpload.test.tsx`, a 5 s timeout under full-run load: alone it
  passes 6/6 (and in every later full run). Python suites as half A. Fingerprint clean.

## Task 13. RetireButton and the header (done)

- New `src/app/p/[project]/RetireButton.tsx`; `src/components/SiteHeader.tsx`: `Forms` replaced by `Question sets`
  and `Questionnaires`.
- Proof: RetireButton 6, SiteHeader 2 passed.

## Task 14. Question sets (done)

- New under `src/app/p/[project]/question-sets/`: `actions.ts`, `import/actions.ts` (`readQuestionSetFile`, the old
  `readFormFile` body), `[setId]/export/route.ts`, `page.tsx`, `[setId]/page.tsx`, `new/page.tsx`,
  `[setId]/edit/page.tsx`, `QuestionSetEditor.tsx` (the old builder's editor panel and row markup), `import/page.tsx`,
  `import/QuestionSetImport.tsx` (`mv` of `forms/import/FormImport.tsx`, then edited: mounts the set editor, stays
  `--form`). The "Also make a questionnaire with all its questions" box shows only for a new set of origin import.
  Annex point chips on set rows use the `qf-overlap` chip class (so `span.qf-citation` stays the citation only).
- Proof: questionSetActions 23, questionSetExportRoute 21, QuestionSetsPage 11, QuestionSetPage 12,
  QuestionSetEditor 16, QuestionSetImport 13: 96 passed.

## Task 15. Questionnaires (done)

- New under `src/app/p/[project]/questionnaires/`: `actions.ts` (exactly the three actions), `libraryData.ts` (`mv` of
  `forms/libraryData.ts`, rewritten), `QuestionnaireBuilder.tsx` (`mv` of `forms/FormBuilder.tsx`, rewritten: set
  chips for non-retired groups, picks only, update box, `Accept all updates`, `p.qf-builder-author`),
  `new/page.tsx`, `[questionnaireId]/edit/page.tsx` (`p.qf-saved-by` from `history`), `page.tsx` (the
  `update available` tag reads the library row's `updates`, which the service computes from the set groups),
  `[questionnaireId]/export/route.ts`, `import/page.tsx`, `import/actions.ts`, `import/QuestionnaireImport.tsx`.
- Proof: questionnaireActions 33, questionnaireExportRoute 30, formsDefaultIsFixed 25, QuestionnaireBuilder 43,
  questionnaireEditPage 7, QuestionnairesPage 12, QuestionnaireImport 10: 160 passed.

## Task 16. Old /forms: redirects, old code removed (done)

- Backups checked first: `$P/tlf/impl-untracked-src.tar` and `~/aisc-backups/qualification-worktree-before-two-level-1701.tar.gz`
  both hold every deleted file.
- `forms/page.tsx`, `forms/new/page.tsx`, `forms/[formId]/edit/page.tsx`, `forms/import/page.tsx` are
  `permanentRedirect` only; `forms/[formId]/export/route.ts` a 308 with `NEXT_BASE_PATH` + path + the query as it came.
- Deleted (plain `rm`, one path each): `forms/actions.ts`, `forms/import/actions.ts`, `src/domain/forms/formDraft.ts`,
  `src/server/services/FormService.ts`, `src/server/repositories/FormRepository.ts`. The three other old files had
  already moved (`mv`) in tasks 14 and 15, nothing was left behind.
- Proof: formsRedirects 13, formsNoModel 8 passed.
- The grep of plan task 16 step 5 prints 4 lines, all `FormImportResult`, the type of `FormImportClient.ts`, which the
  plan keeps (formsNoModel requires the file). The pattern `FormImport[^C]` matches `FormImportR...`: a false
  positive of the pattern, not dead code. The keeper grep lists exactly the deliberate keepers
  (`QualificationService.ts` lines 48, 52, 57, 58; `QualificationFormParser.ts` lines 66, 195).

## Task 17. Chooser, edit page, card (done)

- `src/domain/forms/chooser.ts`: `preselect(options, {fromVersionId})`, `QuestionnaireLookup`,
  `pickQuestionnaireParams`; `pickFormParams` gone. `system/edit/FormChooser.tsx`, `system/edit/page.tsx`,
  `qualify/new/QualifyForm.tsx` (`previous`, `cardNumber`, `p.qf-moving`, `p.qf-wording-changed`, hidden
  `questionnaireVersionId`, heading `groupLabel ?? setName`), `qualify/[id]/AnsweredForm.tsx` (type and heading),
  `FormLine.tsx` (new props, `form` accepted and unused), `qualify/[id]/page.tsx` (`questionnaireService.resolve`,
  `newerVersion` for the current card only).
- Proof: formChooser + FormChooser + editSystemPage 81; QualifyFormMove 10, QualifyFormBlocks 20, AnsweredForm 19,
  FormLine 9, VerticalCard 8; guards formPrefill 10, formUpload 6, prefillOnEditPage 7, cardSubmission 2.

## Task 18. Layout (done)

- `src/app/globals.css`: one block appended at the end (after the pinned media queries) for `qf-set-versions`,
  `qf-moving`, `qf-questionnaire-update`, `qf-wording-changed`, `qf-import-missing`, `qf-saved-by`,
  `qf-builder-author`, `qf-forms-toggle`, `qf-builder-questions-head`, `qf-retire`, and `qf-tag--notice` inside
  `.qf-forms-table` (the existing rule is scoped to `.qualify-form`). No existing rule changed.
- Proof: formsLayout 22, widePage 5; full vitest 0 failed.

## The authorised test edit (builderState.test.ts)

- Type annotations only, lines 68, 115, 389, 450, 494: `.map((r) =>` became `.map((r: BuilderState["rows"][number]) =>`
  (`BuilderState` was already imported as a type). No assertion or runtime change; 38 passed before and after.
  Diff: `$P/tlf/builderState-annotations.diff`; original: `$P/tlf/builderState.test.ts.orig`.
- Fingerprint baseline `$P/tlf/impl-tests.sha`: only that line changed, from
  `d108d87b63b439005329d0b55d044511792ac19c1d5cc9a45b87d69fb0e65ebb` to
  `5a05a540ebb23369a9b43642d74cc06d36fd7f44715d06beb9f71d93d4d65521` (previous baseline kept as
  `$P/tlf/impl-tests.sha.before-annotations`).

## Deviation: one half A file touched

- `npm run build` failed its lint step: `QuestionnaireService.ts` line 233 called `useOnceFormName`, a plain function
  whose name trips `react-hooks/rules-of-hooks`. The fix is the one the old `FormService.ts` used: import it as
  `useOnceFormName as oneUseFormName` (with the same one-line comment) and call that. Behaviour identical;
  QuestionnaireService 40 and formsDefaultIsFixed 25 still pass.

## Task 19. Full verification (done), 2026-09-25

- `npx prisma generate` (fourth run). vitest: Test Files 99 passed, 4 skipped (103); Tests 1301 passed, 90 skipped
  (1391); 0 failed. tsc: 0 errors. `prisma validate` (dummy URL): valid.
- `npm run build`: exit 0; routes include `/p/[project]/question-sets*` (6) and `/p/[project]/questionnaires*` (5),
  and the five `/forms*` routes (redirects). The three running `next start` processes are inside docker containers,
  none from `$A`; the build wrote only the git-ignored `.next`.
- ontology 272 passed, 3 failed (the three pre-existing); prefill 420 passed; renderer 50 passed; agents 168 passed.
- DB via `test/db/throwaway-db.sh`: Test Files 3 passed (3), Tests 89 passed (89); no `aisc-t-qual-*` container
  before or after; no other container touched.
- Fingerprint check prints nothing; the two applied migrations still hash `cbea212d...` and `b8338d12...`.
- No em dash in any file half B wrote or edited (the one hit, `qualify/[id]/page.tsx` line 27, is a pre-existing
  comment). `git diff --stat -- Dockerfile`: one line. `git status` differs from the start only by the files of plan
  section 5 (and the moves/deletes above). HEAD unchanged; nothing committed, migrated, rebuilt, restarted or deployed.
  `prisma generate` rewrote `node_modules/.prisma` (shared; the live stack is image-based).
- Open decision (plan section 3 item 9, not taken): a custom listed form named "Annex IV" in any case that owns
  questions would abort the migration on `question_set_active_name_key` with a bare unique-violation message. Live
  has none.
- Tests believed wrong: none. Only note: plan task 16's grep pattern over-matches `FormImportResult` (above).

## Fix round (05-verification H4, H8, H12), 2026-09-25

Each finding test first: the new tests were run and failed for the stated reason before any code changed.

- H4 (fixed). `QuestionnaireService.importSelfContained` now re-checks every file item before anything else:
  a non-object item gets T51's `item <n> has no setId`; a `groupLabel` that is not null/absent and not a
  string of trimmed length at least 1 and length at most 120 gets T51's `item <n>: groupLabel must be text
  of at most 120 characters or null`. Nothing is written. Before the fix: the fake stored the bad label, a
  null item threw a TypeError, and on the real DB each case threw `PrismaClientUnknownRequestError` (the
  CHECK) or `PrismaClientValidationError` (a number). The other DB-constrained fields (text, citation,
  required, annexPoint, names, description, blocks, item count) were already checked by `parseSetDraft`
  and `parseQuestionnaireDraft`; identities are generated.
- H8 (fixed). `forms/[formId]/export/route.ts` encodes `project` with `encodeURIComponent` (formId already
  was). Before: `/p/a b/...` in `Location`. Not touched (outside the finding): the four `/forms*` redirect
  pages also interpolate `project` unencoded into `permanentRedirect`.
- H12 (fixed). New `retireRace(err)` in `QuestionSetService.ts` reads the trigger text from the error:
  `is retired: it gets no new version` (a save meeting a committed retire) maps to `That question set
  cannot be changed.` / `That questionnaire cannot be changed.`; `it can only be retired, once` (a second
  retire) maps to `That question set cannot be retired.` / `That questionnaire cannot be retired.` Any
  other error still throws. Before: the raw trigger error (500), proven on the real triggers too.
- Tests added (new files only, no existing test edited): `test/unit/twoLevelFormsFixRound.test.ts` (16:
  H4 9, H8 2, H12 5) and `test/db/twoLevelFormsFixRound.db.test.ts` (8: H4 4, H12 4,
  real Postgres, race made with a stale-read repository).
- Files changed: `src/server/services/QuestionnaireService.ts`, `src/server/services/QuestionSetService.ts`,
  `src/app/p/[project]/forms/[formId]/export/route.ts`. Migration untouched.
- Proof: vitest Test Files 100 passed, 5 skipped (105); Tests 1317 passed, 98 skipped (1415); 0 failed.
  tsc 0 errors. `npm run build` exit 0. DB via `test/db/throwaway-db.sh`: Test Files 4 passed, Tests 97
  passed (89 before plus 8); no `aisc-t-qual-*` container before or after. Nothing committed.
