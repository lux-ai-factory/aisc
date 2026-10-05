# Two-level forms: the tests (stage 2, test author)

Date: 2026-09-25. Inputs: `00-brief.md`, `01-spec.md` (T1 to T63, D1 to D30, section 8). App:
`apps/qualification`, branch `feat/unified-modules`, uncommitted working tree. Tests and fixtures only: no file
under `src/`, `prisma/` or `services/*/` (outside `tests/`) was touched, nothing was committed, no container is
left behind.

The tests are the contract. Where the spec is silent, the names the tests use are listed in section 5; use them.

Short names below: `A=apps/qualification`, `P=` the session scratchpad
(`/tmp/claude-1001/-home-listuser/572e79f5-831d-4f75-909f-47cb45306c7a/scratchpad`).

---

## 1. Files

### 1.1 Created (35)

Support and fixtures:
- `test/support/fakeQuestionnaireStore.ts`: in-memory `QuestionSetRepository` + `QuestionnaireRepository`; its header
  is the repository contract (section 5.3). Mirrors the DB rules (P2002 for taken numbers and names, P2003 for an item
  naming no set item, the trigger messages for builtin/retired versions and for a question of another set).
- `test/support/mcasCard.ts`: the MCAS example as a stored card (`mcasCard()`), fixed ids and dates.
- `test/fixtures/mcas-export-before.json`: `toExport(mcasCard(), annexDefaultVersion())` from the code BEFORE the
  change, `JSON.stringify(x, null, 2)` (T10). Written by the test author from the unchanged code (the spec's "plan's
  first task" is therefore done): do not regenerate it.
- `test/fixtures/Dockerfile.before`: a byte copy of the Dockerfile before the change (T59).

vitest (unit/component, `test/unit/`): `twoLevelSchema`, `twoLevelMigration`, `questionSetDraft`, `setEditorState`,
`questionnaireDraft`, `moveCard`, `references`, `callerName`, `annexIdentity`, `QuestionSetService`,
`QuestionnaireService`, `questionSetActions`, `questionnaireActions`, `questionSetExportRoute`,
`questionnaireExportRoute`, `formsRedirects`, `QuestionnaireFileClient`, `dockerfile` (all `.test.ts`);
`QuestionSetEditor`, `QuestionSetsPage`, `QuestionSetPage`, `QuestionSetImport`, `RetireButton`,
`QuestionnaireBuilder`, `QuestionnairesPage`, `QuestionnaireImport`, `questionnaireEditPage`, `QualifyFormMove`
(all `.test.tsx`).

DB: `test/db/twoLevelForms.db.test.ts` (70 tests).

Python: `services/ontology/tests/test_owner_set_keys.py` (11), `services/prefill/tests/test_questionnaire_file.py`
(84 collected).

### 1.2 Deleted (9), each replaced as spec 8.2 says

`test/unit/FormService.test.ts`, `formDraft.test.ts`, `formActions.test.ts`, `formExportRoute.test.ts`,
`FormImport.test.tsx`, `FormBuilder.test.tsx`, `FormsPage.test.tsx`, `test/db/forms.db.test.ts`,
`test/support/fakeFormStore.ts`. Where each case lives on: section 4.1.

### 1.3 Changed (22)

`test/support/forms.ts`; `test/unit/annexDefaultForm.test.ts`, `builderState.test.ts`, `formLibrary.test.ts`,
`formChooser.test.ts`, `FormChooser.test.tsx`, `editSystemPage.test.tsx`, `FormLine.test.tsx`,
`formsLayout.test.tsx`, `widePage.test.ts`, `SiteHeader.test.tsx`, `formsNoModel.test.ts`,
`formsDefaultIsFixed.test.ts`, `QualificationService.forms.test.ts`, `QualificationExporter.test.ts`,
`FormExportClient.test.ts`, `QualifyFormBlocks.test.tsx`, `AnsweredForm.test.tsx`, `PrefillClient.test.ts`,
`prefillChoice.test.ts`, `VerticalCard.test.tsx`; `services/prefill/tests/test_app.py` (appended only). Before and
after: section 4.2.

Checked and left unchanged (they build versions through `test/support/forms.ts` but read no renamed field):
`cardSubmission.test.ts`, `formPrefill.test.tsx`, `QualificationFormParser.test.ts`, `serviceTokens.test.ts`.
Every file of 8.3's "Unchanged" list is byte-identical.

---

## 2. T-id to tests

Every test name starts with (or, in Python, contains `t<n>_`) its T-id. `grep -rn '"T27 '` finds a requirement.

| T | Layer | File(s) |
|---|---|---|
| T1 | unit | `twoLevelSchema.test.ts` (7 models field by field with `@map`/`@@map`/keys; no Form models; `questionnaireVersionId`; no `project`; no default flag; every map name at most 63 bytes; `npx prisma validate`) |
| T2 | unit | `twoLevelMigration.test.ts` (file exists; no BEGIN/COMMIT/CONCURRENTLY/IF EXISTS/CASCADE; no UPDATE/DELETE FROM/TRUNCATE statement, DO blocks included; no EXCEPTION clause; schema-qualified names; order of 4.2; drops; messages; the ten triggers after the last DROP; 090000/120000 sha256 pinned) |
| T3 | unit, DB | `annexDefaultForm.test.ts`; `twoLevelForms.db.test.ts` (resolve with the real repositories deep-equals the twins; builtin rows; 14 wording rows; 14 items; old tables and functions gone; ten triggers) |
| T4 to T7 | DB | `twoLevelForms.db.test.ts` (every message of 3.2, the CHECKs, FK/PK names, one-way retire, name keys, delete refused, answer index, card FK `confdeltype = 'r'`, renamed index) |
| T8 | DB | `twoLevelForms.db.test.ts` (the spec's fixture; every row of the seven tables; the NOTICE; lists before/after) |
| T9 | DB | `twoLevelForms.db.test.ts` (history digests; write log and row addresses; P1 tampered builtin; second builtin; D29 600-char description; the live state; C5 and C8 count aborts) |
| T10 | unit | `annexIdentity.test.ts` |
| T11 | pytest (ontology) | `test_owner_set_keys.py` |
| T12, T13 | unit | `questionSetDraft.test.ts` |
| T14, T15, T19, T45 | unit | `QuestionSetService.test.ts`; T15's 404: `QuestionSetEditor.test.tsx`, `questionSetActions.test.ts` |
| T16 | unit | `setEditorState.test.ts` |
| T17 | component | `QuestionSetEditor.test.tsx`, `formsLayout.test.tsx` (B6 T17) |
| T18 | unit | `questionSetActions.test.ts` |
| T20 | component | `QuestionSetsPage.test.tsx` |
| T21 | component | `QuestionSetPage.test.tsx` |
| T22, T23 | unit | `questionnaireDraft.test.ts` |
| T24, T25, T35, T46 | unit | `QuestionnaireService.test.ts`; T35 also `questionnaireActions.test.ts`, `QuestionnairesPage.test.tsx` |
| T26 | unit | `formLibrary.test.ts` |
| T27 to T31, T33 | unit, component | `builderState.test.ts`, `QuestionnaireBuilder.test.tsx`; T30 `questionnaireActions.test.ts`, `formsDefaultIsFixed.test.ts`; T31 `questionnaireEditPage.test.tsx`, `questionnaireActions.test.ts` (404s) |
| T32 | component, unit | `formsLayout.test.tsx`, `widePage.test.ts`, `QuestionnaireBuilder.test.tsx`, `QuestionnaireImport.test.tsx`, `questionnaireEditPage.test.tsx`, `QuestionnairesPage.test.tsx` |
| T34 | component | `QuestionnairesPage.test.tsx`, `formsLayout.test.tsx` (L) |
| T36, T38 | component | `FormChooser.test.tsx`, `editSystemPage.test.tsx` |
| T37, T39 | unit, component | `formChooser.test.ts`, `editSystemPage.test.tsx` |
| T40 | unit, component | `QualificationService.forms.test.ts`, `QualifyFormMove.test.tsx`, `QualifyFormBlocks.test.tsx`, `AnsweredForm.test.tsx` |
| T41 | unit, component | `moveCard.test.ts`, `QualifyFormMove.test.tsx`, `editSystemPage.test.tsx`, `QualificationService.forms.test.ts` |
| T42 | unit, component | `FormLine.test.tsx`, `moveCard.test.ts` (`newerVersion`), `formsLayout.test.tsx` (F1) |
| T43 | unit, pytest | `QualificationExporter.test.ts`, `annexIdentity.test.ts`, `test_owner_set_keys.py` (`test_coverage.py` untouched and green) |
| T44 | component | `VerticalCard.test.tsx` |
| T47 | unit | `questionSetExportRoute.test.ts`, `FormExportClient.test.ts` |
| T48 | unit | `questionnaireExportRoute.test.ts` |
| T49 | component, unit | `QuestionSetImport.test.tsx`, `QuestionSetService.test.ts`, `questionSetActions.test.ts` |
| T50 to T52 | pytest (prefill) | `test_questionnaire_file.py`, `test_app.py::TestQuestionnaireEndpoints` |
| T53 | unit, component | `references.test.ts`, `QuestionnaireService.test.ts`, `QuestionnaireImport.test.tsx`, `questionnaireActions.test.ts` |
| T54 | unit, component | `QuestionnaireService.test.ts`, `QuestionnaireImport.test.tsx`, `QuestionnaireFileClient.test.ts`, `questionnaireActions.test.ts` |
| T55 | unit | `callerName.test.ts`, `questionSetActions.test.ts`, `questionnaireActions.test.ts`, both service tests |
| T56 | component | `RetireButton.test.tsx`, `QuestionSetsPage.test.tsx` |
| T57 | unit, component | both service tests, `questionnaireEditPage.test.tsx` |
| T58 | unit | `PrefillClient.test.ts`, `prefillChoice.test.ts` |
| T59 | unit | `dockerfile.test.ts` |
| T60 | component | `SiteHeader.test.tsx` |
| T61 | unit, pytest | `formsNoModel.test.ts`, `test_questionnaire_file.py` (AST scan) |
| T62 | unit | `formsRedirects.test.ts` |
| T63 | unit, component | `formsDefaultIsFixed.test.ts`, both service tests, `QuestionSetsPage.test.tsx`, `QuestionnairesPage.test.tsx`, both action tests |

---

## 3. The migration tests (DB), how they work

All in `test/db/twoLevelForms.db.test.ts`, run only by `test/db/throwaway-db.sh` (which applies every migration,
the new one included). Every psql script runs as the throwaway DB's superuser inside `BEGIN ... ROLLBACK`.

- **Back to the state of live** (`revertToLive()`): drop the seven new tables and the ten trigger functions, drop
  `qualification.questionnaire_version_id`, restore the old answer index (after deleting rows only the new key
  allows, as the old R7 test did), then run the texts of 20260925090000 and 20260925120000. The five history tables
  are locked first (ACCESS EXCLUSIVE) so concurrent DB test files wait instead of deadlocking.
- **Live** ("T9 live" tests): builtin form only, one card with `form_version_id` NULL, 14 answers (non-ASCII text),
  a risk, its knowledge graph and `systemCardJson`. Snapshot, run the migration, snapshot. Asserted: the card's
  answers (with their `ctid`), the graph (digest, md5 of Turtle and JSON-LD, counts, `built_at`), the card JSON and
  the whole card row minus the renamed column are byte-identical; the version stays NULL; the new rows are exactly the
  builtin level (1, 1, 14, 14, 1, 1, 14) carrying the old rows' values column for column, `created_by = 'system'`.
- **T8 split fixture**: exactly the spec's table (`acme`, `mix`, `once`, `odd`, created 2026-09-01 to -04), cards c1
  (mix v1, then not the latest) and c2 (NULL, 14 answers). Form version ids are `fv-acme-1`, ..., so they cannot be
  confused with set version ids (`acme-v1`, ...). Every row of the seven new tables is asserted, including
  `created_by = 'unknown'` and every `created_at`.
- **No card row is written**: a test-only AFTER INSERT/UPDATE/DELETE and AFTER TRUNCATE log trigger on the five history
  tables, and every history row's `ctid` compared before and after (an UPDATE moves a row, even a no-op one). So the
  latest-card triggers cannot have fired, and c1 was not touched.
- **Aborts**: P1 (one of the 14 builtin rows deleted; a second builtin form); D29 (a 600-character description, CHECK
  name matched, old tables intact after `ROLLBACK TO SAVEPOINT`); C5 and C8 count checks: a test-only event trigger
  arms a row trigger on `questionnaire_version_item` as soon as the migration creates it, which swallows one item (C5
  must fail: `expected 14, found 13`, or the zero-missing part `expected 0, found 1`) or writes one stray history row
  (C8 must fail with found = expected + 1).

**Harness validated.** To make sure the contract is runnable, the DB tests were run against a scratch reference
migration written from spec 4.2 (kept only in `$P/tlf/ref/migration.sql`, never in the repo, not the implementation):
every DB test passed except the two T3 tests that need the new TS modules. Two mutations of it (pinning the lowest
matching set version instead of the highest; a no-op `UPDATE ... SET answer = answer` of the latest card's answers)
were each caught (T8 pins; T9 write log and `ctid`s; the digests alone would have missed the no-op update). T1 and T2
likewise pass against a reference schema and that migration.

Note for the implementer: the other two DB files use the generated Prisma client (`app.qualification.create`), so
after the schema change `prisma generate` must have run, or they fail with "The column
`qualification.form_version_id` does not exist". `twoLevelForms.db.test.ts` uses raw SQL for every card write.

---

## 4. Changed and deleted tests (before, after, reason)

Counts are `it`/`test` cases as vitest runs them (it.each rows counted).

### 4.1 Deleted (spec 8.2)

| File | Before | Where its cases live now | Removed on purpose |
|---|---|---|---|
| `FormService.test.ts` | 48 | R3, R16 -> `QuestionSetService` T45 and `QuestionnaireService` T46; R5 -> T14, T15 (`s-<set>:q<n>`); R6 -> T15, T24, T25; R7 -> T25; R43 -> T46; R47 -> T63; R57 -> T25; R60 to R62 -> T24, T25, T46; R68 -> T24 | R20 copy; R22 "own question belongs to another form" (T15 "belongs to another question set" replaces it); R60 "no latestSnapshot" |
| `formDraft.test.ts` | 37 | name, description, block, 200-limit, shape and duplicate cases -> `questionSetDraft`, `questionnaireDraft` with the new messages | pick/own/copy kinds; snapshot `sameContent` |
| `formActions.test.ts` | 23 | R22/R6 saves -> `saveQuestionnaire`/`saveQuestionSet`; R42 door -> both action files; R6 edit 404s -> T31 (and T15 for sets); R68 naming -> `useQuestionnaireOnce`; R48, R47 -> both; R73 exports and no `.admin` -> `questionnaireActions` | R47 "real FormService through FakeFormStore" (FormService deleted; T63 covers install-wide) |
| `formExportRoute.test.ts` | 18 (7 `it`, with `it.each`) | every R57 case -> `questionSetExportRoute` (same statuses and messages); use-once case -> "retired set exports" and the questionnaire route's unlisted/retired cases; `/forms/<id>/export` -> `formsRedirects` | none |
| `FormImport.test.tsx` | 10 | all -> `QuestionSetImport.test.tsx`; R28 "mounts the builder" -> "mounts the set editor" (8.2) | none |
| `FormBuilder.test.tsx` | 33 | R16, R18, R21, R22 (labels `Save questionnaire`), R23, R75 to R80 -> `QuestionnaireBuilder`; R19 editor cases -> `QuestionSetEditor`; R64 -> T29 | R20 copy; R77's "own question and copy stay" (06 C2 void) |
| `FormsPage.test.tsx` | 5 | R44 no `Set as default`, R48 intro -> T34; R48 two projects -> T63; R58 actions -> T34 (questionnaires) and T20 (sets, CSV/Markdown) | none |
| `test/db/forms.db.test.ts` | 18 | R1 seed -> T3; R5 answer index -> T7; R6 triggers -> T4; R45 builtin rules -> T5; R7 no history -> T9, its "revert 090000" recipe -> `revertToLive()` | the old form-table checks (tables dropped) |
| `test/support/fakeFormStore.ts` | support | `test/support/fakeQuestionnaireStore.ts` | |

### 4.2 Changed (spec 8.3; minimal)

| File | Before | After | What changed | Row |
|---|---|---|---|---|
| `test/support/forms.ts` | support | support | builders keep their names and return the new fields (`setId`, `setName`, `setVersionId`, `setVersionNumber`, `setBuiltin`; `questionnaireId`, `questionnaireName`, `description`, `retired`); added `setQuestion` (scope `s-`), `setVersion`, `questionnaireVersion`, `annexSetLiteral`, `ANNEX_DESCRIPTION` | 8.3 support |
| `annexDefaultForm.test.ts` | 21 | 24 | `annexDefaultVersion()` field names (T3); constants of 3.4; `DEFAULT_FORM_ID` gone; `annexSetVersion`; `resolveQuestionnaireVersionId`; the two "schema has no default flag" tests dropped (now T1). The 090000/120000 byte pins unchanged | 8.3 |
| `builderState.test.ts` | 43 | 38 | rewritten on sets: R16, R18, R21, R76 to R79 kept (`selectSet`, `viaSetId`, `setVersionId`, `rows`, `toQuestionnaireDraft`); own/copy/import-as-own/`fromVersionId` cases removed; R64 `takeLatest` -> `acceptUpdate`; new T27 to T33 | 8.3 |
| `formLibrary.test.ts` | 18 | 21 | `filterLibrary`/`overlapHints` byte-unchanged; the 8 `sourceUpdates` tests -> 11 `updatesAvailable` | 8.3 |
| `formChooser.test.ts` | 12 (34 run) | 15 | `preselect` signature; R8 "older version starts on the form's latest" flipped to "that exact version" (D11); `pickFormParams` -> `pickQuestionnaireParams` with the aliases | 8.3 |
| `FormChooser.test.tsx` | 11 | 15 | texts `Which questionnaire?`, `+ New questionnaire`, `Import questionnaire`, `That questionnaire was not found.` (in `div.error`), `Same questionnaire as v<N> (<name> v<k>)`; hrefs `?questionnaire=`; new T38 cases (update available, D10 retired, encoding) | 8.3 |
| `editSystemPage.test.tsx` | 24 | 32 | `questionnaireService` mock; `fromQuestionnaireVersionId`; param names and aliases (T39 four-way precedence); A14 per T37 (exact version); new T41 cases | 8.3 |
| `FormLine.test.tsx` | 6 | 9 | `Questionnaire: <name> v<N>`, JSON link, `/questionnaires/` hrefs, legacy line; `newer` prop; card page source checks `questionnaireVersionId`, `newerVersion(` | 8.3 |
| `formsLayout.test.tsx` | 20 | 22 | paths to `questionnaires/*`, `question-sets/*`; L tests on the questionnaires page (6 cells, links and buttons, new header links); B tests on `QuestionnaireBuilder` (`Your questionnaire`, `Select question sets`); B6 split (builder has no editor; the editor-panel asserts, unchanged, moved to the set editor); B7 no `Edit`; B8 `Update available`/`Accept the update of`; P3 set import stays `--form`, new P3b questionnaire import turns `--wide`; C1/F1 props follow T36/T42 (F1: 3 separators for the new JSON link; C1 keeps its exact count of 2 tags); B2, B4, P4 CSS pins unchanged | 8.3 |
| `widePage.test.ts` | 5 | 5 | only the last test's paths | 8.3 |
| `SiteHeader.test.tsx` | 2 | 2 | `Forms` -> `Question sets`, `Questionnaires` | 8.3 |
| `formsNoModel.test.ts` | 6 | 8 | the file list of T61 (missing files fail); env-name test; deleted modules gone; R73's allowed names gain `NEXT_BASE_PATH` (T61 allows it; the old export route becomes a redirect reading it). Scan logic unchanged | 8.3 |
| `formsDefaultIsFixed.test.ts` | 17 | 25 | T30 export list; the seven models; public-method and `projectId` scans on the four new classes; new migration's tables have no project column; `setDefault` scans unchanged | 8.3 |
| `QualificationService.forms.test.ts` | 9 | 12 | posted/stored `questionnaireVersionId`, `formVersionId` alias (+ new name wins), new message, `fromQuestionnaireVersionId`; T41 move case | 8.3 |
| `QualificationExporter.test.ts` | 12 | 13 | `ownerSet`/`ownerSetId`; exact key order | 8.3 |
| `FormExportClient.test.ts` | 9 | 9 | `write({name, version, questions})` | 8.3 |
| `QualifyFormBlocks.test.tsx` | 20 | 20 | hidden input `questionnaireVersionId`; `setName` for `ownerFormName`; nothing else | 8.3 type change |
| `AnsweredForm.test.tsx` | 18 | 19 | one T40 case added; the R36 heading case unchanged | 8.3 type change |
| `PrefillClient.test.ts` | 9 | 10 | one T58 case added | 8.3, T58 |
| `prefillChoice.test.ts` | 13 | 16 | three T58 cases added | 8.3, T58 |
| `VerticalCard.test.tsx` | 7 | 8 | one T44 case added | T44 |
| `services/prefill/tests/test_app.py` | 56 | 81 | class `TestQuestionnaireEndpoints` appended (25); nothing above it changed | T50, T51 |

---

## 5. Interface names chosen where the spec is silent

### 5.1 Domain (`src/domain/forms/`)
- `setEditorState.ts`: `QuestionValues = {text, citation, required, annexPoint}`; actions `add {values}`,
  `edit {index, values}`, `move {from, to}`, `remove {index}`, `setName {name}`, `setDescription {description}`,
  `toggleAlsoQuestionnaire`. `initialSetEditorState({})` is exactly `{setId: null, name: "", description: "", rows: [],
  origin: "builder", alsoQuestionnaire: false, nextRow: 0}`; `{edit: ResolvedSetVersion}`; `{rows, name, origin:
  "import"}`. Edit/remove of an index that is not there returns the same state. `toSetDraft` omits `questionId` for new
  rows.
- `builderState.ts`: `BuilderState` keys exactly `questionnaireId, name, description, blocks, rows, origin, selected,
  nextRow`; a pick row's keys exactly `rowKey, kind, questionId, setVersionId, source` (+ `viaSetId` only when from a
  set). Actions `tick {question, setVersionId, group?}`, `untick {questionId}`, `selectSet {group}`, `deselectSet
  {setId}`, `move`, `remove`, `toggleBlock`, `setName`, `acceptUpdate {index, question, setVersionId}`,
  `acceptAllUpdates {updates}` (the `updatesAvailable` output; removed entries ignored). Unknown actions (`addOwn`,
  `edit`, `copy`) return the same state object. `BuilderInit = {name?, description?, blocks?, origin?, picks?:
  Array<{question, setVersionId, viaSetId?}>, startFrom?, edit?}`.
- `chooser.ts`: `QuestionnaireLookup = {lookup: "example"} | {lookup: "version", id} | {lookup: "latest", id} |
  {lookup: "none"}`.
- `moveCard.ts`: `newerVersion(card, latest | null): {versionId, versionNumber} | null` (null for another
  questionnaire too); `moveNotice` appends each count sentence only when its count is above 0.
- `references.ts`: `ReferenceItem = {setId, setName, setVersion, scope, localId}`, `FoundSetVersion = {setId, number,
  name, versionId, keys: string[]}`, `missingReferences(items, found)`.
- `annexDefaultVersion().description` is `EU AI Act Annex IV points 1 and 2, as 14 questions.` (the form's, so it
  deep-equals the migrated row).

### 5.2 Services
- `QuestionSetService`: `list({retired})` rows `{setId, name, description, origin, builtin, versionId, version,
  questionCount, savedBy, savedAt, retiredAt}`; `saveDraft(draft, {setId?, origin?, createdBy, alsoQuestionnaire?})`
  -> `{ok, setId, versionId, number, created, questionnaireId?}`; `retire(setId)` -> `{ok: true} | {ok: false, error}`
  with `Annex IV cannot be retired.` / `That question set cannot be retired.` (the action passes them through). A
  name-only change of an existing set is no change.
- `QuestionnaireService`: library rows add `savedBy, savedAt, retiredAt, updates`; `saveDraft(draft,
  {questionnaireId?, listed, origin?, createdBy, systemName?})`; an existing questionnaire's draft name is ignored;
  taken names are listed, non-retired ones (the DB index); `retire(id)` messages `The Annex IV default cannot be
  retired.` / `That questionnaire cannot be retired.`; `resolveReferences(items)` -> `{ok: true, picks} | {ok: false,
  missing}`; `importSelfContained(file, {setName, questionnaireName, createdBy})` -> `{ok, setId, questionnaireId,
  versionId}`.
- Both take `(repository, {newId, now})`; the repositories take a `PrismaClient` in the constructor (the DB test builds
  `new QuestionnaireRepository(app)` and `new QuestionSetRepository(app)`).
- `QuestionnaireFileClient(baseUrl, fetchImpl, serviceToken)`: `write(file, bundle)`, `read(file)`; failures `{ok:
  false, status, error}` (a 4xx keeps the service's status and `detail`); singleton `questionnaireFileClient`. Types
  `QuestionnaireFileInput`, `QuestionnaireFile` exported there.

### 5.3 Repository contract
The header of `test/support/fakeQuestionnaireStore.ts`: `listSets`, `findSet`, `findSetVersion`, `setVersionsOf`,
`findQuestion`, `questionsOf`, `insertSetVersion(plan)` (one transaction, optionally with a questionnaire version),
`retireSet(id, at)`; `listQuestionnaires`, `findQuestionnaire`, `findQuestionnaireVersion`,
`questionnaireVersionsOf`, `insertQuestionnaireVersion(plan)`, `retireQuestionnaire(id, at)`. Row shapes are the
Prisma models; version reads include their items (a questionnaire item includes `setItem` with `question` and
`setVersion.set`). The fake's retire methods ignore an unknown id: the services check first.

### 5.4 Pages, actions, components
- Pages are default async `({params, searchParams})`. Set edit page reads `questionSetService.latest(setId)`; set page
  `history(setId)` + `atNumber(setId, n?)`; questionnaire edit and `?from` read `questionnaireService.latestVersion`;
  the set export route `atNumber`, the questionnaire route `exportable`. The questionnaire export route checks format,
  then bundle, then version. The old export route's `Location` may be relative or absolute (path and query compared).
- `readQuestionnaireFile(formData)` -> `{ok: true, bundle: "references", open: {name, blocks, origin: "import",
  picks}} | {ok: true, bundle: "self-contained", file, fileName} | {ok: false, error, missing?}`.
- `QuestionSetEditor {project, initial, latestNumber?}`; `saveQuestionSet(project, json, setId | undefined, {origin,
  alsoQuestionnaire})` with opts always given. `QuestionSetImport {project, header?}` and `QuestionnaireImport
  {project, groups, header?}` render the page's `<main>`. `QuestionnaireBuilder {project, groups, initial}`; its
  left column is `section[aria-label="Question library"]`; save calls `saveQuestionnaire(project, json, id |
  undefined, origin)`, `useQuestionnaireOnce(project, json, origin)`.
- `FormChooser` options `{questionnaireId, name, versionNumber, questionCount, isDefault, versionId, versionIds}`,
  `previous: {cardVersionNumber, versionId, name, versionNumber} | null`, radio values `questionnaire:<id>` /
  `questionnaireVersion:<id>`. `FormLine {project, questionnaireId, questionnaireName, versionNumber, basePath?,
  newer?}` (tests also pass `form`). `QualifyForm` gets `previous` and `cardNumber` only when the chosen version
  differs from the previous card's; `p.qf-moving`/`p.qf-wording-changed` render inside it.
- Lists: set `Made by` shows `Built in`/`Imported` (builder label free); retired questionnaires show only `Export`
  and `Export self-contained`; toggle links `Show retired questionnaires` / `Show current questionnaires`.

### 5.5 Python
`QuestionnaireFileError`'s detail is `str(error)`; `read_questionnaire` output carries `bundle`; "missing wording" on
export means the key is absent (a null `annexPoint`/`groupLabel` is present).

---

## 6. Commands

```bash
A=/home/listuser/aisc-install/apps/qualification
P=/tmp/claude-1001/-home-listuser/572e79f5-831d-4f75-909f-47cb45306c7a/scratchpad
cd $A && npx vitest run
cd $A && npx tsc --noEmit
cd $A && DATABASE_URL="postgresql://x:x@127.0.0.1:1/x?schema=qualification" npx prisma validate
cd $A/services/ontology && PYTHONPYCACHEPREFIX=$P/pyc $P/venv-ontology/bin/python -m pytest -p no:cacheprovider -q
cd $A/services/prefill && PYTHONPYCACHEPREFIX=$P/pyc .venv/bin/python -m pytest -p no:cacheprovider
cd $A/services/system_card_renderer && PYTHONPYCACHEPREFIX=$P/pyc $P/venv-system_card_renderer/bin/python -m pytest -p no:cacheprovider -q
cd $P/agents-cwd && PYTHONPYCACHEPREFIX=$P/pyc $P/venv-agents/bin/python -m pytest -p no:cacheprovider -q -c $A/services/agents/pytest.ini --rootdir $A/services/agents $A/services/agents/tests
cd $A && test/db/throwaway-db.sh
```

The venvs were created fresh this session (`uv venv` + `uv pip install -r requirements.txt pytest httpx`, plus
`rdflib==7.6.0` for agents). `bash $P/tlf/run-all.sh <tag>` runs the five non-DB suites (logs in `$P/tlf/logs/`).
Test-file fingerprint before any change: `$P/tlf/before-tests.sha`; originals in `$P/tlf/before-tests/tests.tar`.

---

## 7. Red run (2026-09-25)

| Suite | Before (baseline, unchanged tree) | After (tests written) |
|---|---|---|
| vitest | Files 78 passed, 4 skipped (82); Tests 959 passed, 38 skipped (997) | Files 46 failed, 53 passed, 4 skipped (103); Tests 672 failed, 629 passed, 90 skipped (1391) |
| tsc | 0 errors | 60 errors, all in `test/` (missing new types and fields), 0 in `src/` |
| ontology | 3 failed, 261 passed | 12 failed, 263 passed |
| prefill | 311 passed | 109 failed, 311 passed |
| renderer | 50 passed | 50 passed |
| agents | 168 passed | 168 passed |
| DB (`throwaway-db.sh`) | 3 files, 37 passed | 3 files (1 failed, 2 passed); 89 tests: 68 failed, 21 passed |

Why the new tests fail (every one checked by class):
- vitest: "Cannot find module" for each new module, page, route or component (loaded per test through `loadSrc` or a
  dynamic import, so one missing module fails only its tests); missing files (`existsSync`, ENOENT) for the migration
  and new sources; assertions on renamed fields, new texts and new exports (old components still say `Which form?`,
  `Form:`, read `ownerFormName`, post `formVersionId`); the old `/forms` pages still render instead of redirecting.
  vitest's skipped count is the DB tests (89) plus one pre-existing skip.
- ontology: 9 new fail (`KeyError: 'ownerForm'`, `_owner_key` not preferring `ownerSetId`); the 3 pre-existing failures
  (`nineteen_properties` x2, `every_airo_relation`) are unchanged.
- prefill: 84 `ImportError: No module named 'prefill.questionnaire_file'`, 25 `404` (endpoints missing).
- DB: the migration file and the seven tables do not exist.

Passing on purpose (guards that must stay green): the unchanged cases inside edited files, T5 "no default column",
T7 "same answer key twice fails", T1 `prisma validate` and "no default flag", T2's pins of 090000/120000, T10's fixture
guard and "answers, metadata, risks equal", T58 x4, T44, the T41 no-move cases, T42 "without newer", T36 Continue
and encoding, T39 `?example` wins, the old-key fallbacks in `test_owner_set_keys.py`, the door checks, "every other
Dockerfile line unchanged".

Untouched tests: every test file whose bytes are unchanged (compared with `$P/tlf/before-tests.sha`) passes; the 56
old tests of `test_app.py` pass; renderer and agents unchanged.

---

## 8. Spec gaps and contradictions

Contradictions (the tests take a side):
1. **Index name too long.** 3.1/3.3 name `questionnaire_version_item_questionnaire_version_id_position_key`: 64 bytes.
   Prisma refuses it (`prisma validate` fails, which 3.3 requires to pass) and Postgres would cut it to 63. T1 pins
   only a `questionnaire_version_item_*` name of at most 63 bytes, the same in the schema and the migration's
   `CREATE UNIQUE INDEX`. The implementer picks the name.
2. **`ON COMMIT DROP` vs "no COMMIT".** 4.1 forbids COMMIT, 4.2 step 1 requires `ON COMMIT DROP`: T2 exempts it.
3. **Turtle not byte-stable.** T11 asks for equal Turtle, but two builds of the same input differ in blank-node labels:
   the test compares `graph_digest` and rdflib isomorphism.
4. **File client failures.** 5.3 says QuestionnaireFileClient has FormImportClient's contract, which has no `status`;
   the export route must relay one (T48 as T47): tests use `{ok: false, status, error}`.
5. **T61 vs 06 R73.** T61 allows `NEXT_BASE_PATH`; R73's allowed list in `formsNoModel.test.ts` gains it.

Gaps (a choice was made, see section 5): droppedAnswers and non-`q:` fields (T41); whether a zero count drops its
sentence (T41); `Accept all updates` payload and `Remove from questionnaire` aria label (T29); `?retired=1` for
questionnaires and the "Made by" labels (T20, T34); T34's tag from `groups()` vs T46's `updates` (tests fit both);
names taken for a listed save, and which name error wins in T54; T51 output without `version`, blank `setId`, block
order; T32 "the import page" now that there are two; T38 "latest" read as "no option's `versionId` is P"; the same
question pinned to two set versions in one questionnaire draft is refused (T22); spec 8.3 omits
`QualificationFormParser.test.ts` and `serviceTokens.test.ts` (no edit needed) and formsLayout C1/F1 prop changes.

Not tested, worth a decision:
- A custom **listed** form named `Annex IV` (any case) that owns questions would make a second active set named `Annex
  IV` and abort the migration on `question_set_active_name_key`. Live has none; D29 ("data breaking a new CHECK
  aborts") would cover it, but the migration's message would be a bare unique violation.
- DB tests other than `twoLevelForms.db.test.ts` need a regenerated Prisma client (section 3).
