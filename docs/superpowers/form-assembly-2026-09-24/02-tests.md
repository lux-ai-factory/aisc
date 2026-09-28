# Form assembly: tests (stage 2)

Date: 2026-09-25. App: `apps/qualification`, branch `feat/unified-modules` (not switched).
Input: `01-spec.md` (R1 to R42). Output: the executable contract below. No implementation code,
no migration, no docker, nothing committed.

All paths below are relative to `apps/qualification`.

---

## 1. Files

### New test files

| File | Layer |
|---|---|
| `test/unit/annexDefaultForm.test.ts` | vitest |
| `test/unit/annexPoints.test.ts` | vitest |
| `test/unit/FormService.test.ts` | vitest, fake repository |
| `test/unit/formActions.test.ts` | vitest, module mocks |
| `test/unit/formDraft.test.ts` | vitest |
| `test/unit/builderState.test.ts` | vitest |
| `test/unit/formLibrary.test.ts` | vitest |
| `test/unit/formChooser.test.ts` | vitest |
| `test/unit/FormChooser.test.tsx` | vitest, jsdom |
| `test/unit/FormBuilder.test.tsx` | vitest, jsdom |
| `test/unit/FormImportClient.test.ts` | vitest, fake fetch |
| `test/unit/FormImport.test.tsx` | vitest, jsdom |
| `test/unit/QualifyFormBlocks.test.tsx` | vitest, jsdom |
| `test/unit/QualificationService.forms.test.ts` | vitest, fakes |
| `test/unit/formsNoModel.test.ts` | vitest, source scan |
| `test/db/forms.db.test.ts` | vitest, DB-gated |
| `services/ontology/tests/test_annex_points.py` | pytest |
| `services/ontology/tests/test_form_answers.py` | pytest |
| `services/ontology/tests/test_absent_blocks.py` | pytest |
| `services/ontology/tests/test_coverage.py` | pytest |
| `services/prefill/tests/test_form_import.py` | pytest |
| `services/prefill/tests/test_custom_form_prefill.py` | pytest |
| `services/system_card_renderer/tests/test_form_coverage.py` | pytest |

### New test support (pure fixtures, no implementation)

- `test/support/forms.ts`: literal builders for `ResolvedQuestion` / `ResolvedFormVersion`
  (`customQuestion`, `seededQuestion`, `formVersion`, `defaultVersionLiteral`,
  `policyOnlyVersion`, `ALL_BLOCKS`) and `loadSrc(path)`, the run-time loader
  `prefillOnEditPage.test.ts` already uses, so an extended file does not fail at collection.
- `test/support/fakeFormStore.ts`: the in-memory `FormRepository` (`FakeFormStore`, `idCounter`).
  Its header documents the repository methods FormService may call (section 3).

The .docx fixtures are built inside `test_form_import.py` with python-docx, as the spec (R26) and
the existing prefill tests do, so no binary fixture is committed.

### Existing test files extended (appended only; no existing line changed or removed)

`test/unit/QualificationFormParser.test.ts`, `AnsweredForm.test.tsx`, `VerticalCard.test.tsx`,
`QualificationExporter.test.ts`, `aiCardExport.test.ts`, `PrefillClient.test.ts`,
`prefillChoice.test.ts`; `services/ontology/tests/test_app.py`, `services/agents/tests/test_workflow.py`,
`services/prefill/tests/test_app.py`, `services/prefill/tests/test_fields.py`.

`git diff --stat` on the app shows 889 insertions and 0 deletions.

Not touched, and still passing unmodified as section 9.8 requires: `test_example_mcas.py`,
`test_ontology_only_card.py`, `oneSystemEntryPoints.test.ts`, `prefillOnEditPage.test.ts`,
`keyQuestions.test.ts`, `projectAccess.test.ts`, `cardSubmission.test.ts`, `formPrefill.test.tsx`
(and `formUpload.test.tsx`, which the spec does not list).

---

## 2. Requirement to test map

Every test title (TS) or name (Python) carries its R-id, so `grep -rn "R17 "` or `grep -rn "_r17_"`
finds all of them. The main tests per requirement:

| R | Test file :: tests |
|---|---|
| R1 | `annexDefaultForm.test.ts` :: "R1 FORM_BLOCKS is the 9 block ids...", "R1 is the default form's version 1...", "R1 has the 14 questions in KEY_QUESTIONS order...", "R1 returns a fresh value each call...", "R1 seeds the form row...", "R1 seeds version 1 with all 9 blocks...", "R1 seeds one form_question per...", "R1 seeds one form_version_question per entry..." ; `forms.db.test.ts` :: "R1 annex-iv-default-v1's rows ... field by field", "R1 the default form and its version are seeded..." |
| R2 | `annexPoints.test.ts` :: 6 tests (ids, citations, shape, ANNEX_POINTS, isAnnexPoint, annexCitation) ; `test_annex_points.py` :: `test_r2_*` (repo layout, equals JSON, citation equals `_annex_citation`, unknown id, container candidate, env override, missing file names every place, Dockerfile COPY) |
| R3 | `FormService.test.ts` :: "R3 lists the listed forms, the default first...", "R3 gives each form its latest version number and question count", "R3 never lists a use-once form", "R3 a builtin form that is not the default...", "R3 is the same library for every project..." |
| R4 | `formActions.test.ts` :: 4 x "R4 ..." (non-admin refused and setDefault not called, null access refused, admin sets it, unlisted/unknown) ; `FormService.test.ts` :: "R4 moves the default in one repository call...", "R4 refuses an unlisted form...", "R4 refuses an unknown form" ; `forms.db.test.ts` :: "R4 a second is_default row fails on form_one_default", "R4 an unlisted form cannot be the default" ; `annexDefaultForm.test.ts` :: "R4 R5 R6 names the constraints and triggers" |
| R5 | `FormService.test.ts` :: "R5 a new form's own questions are f-<form id>:q1, q2", "R5 the next own question ... max + 1 ... never reused", "R5 two forms' questions with the same visible text keep different keys" ; `forms.db.test.ts` :: "R5 the same (qualification, toolId, questionId) twice fails..." |
| R6 | `forms.db.test.ts` :: 7 x "R6 ..." (form_version and form_version_question UPDATE/DELETE, identity fixed, name/origin/listed fixed, builtin second version, duplicate number, checks) ; `FormService.test.ts` :: "R6 rewording a question saves the next version...", "R6 a save that changes nothing makes no version...", "R6 a save that lost a race...", "R6 a card's version resolves to that version's wording" ; `formDraft.test.ts` :: 8 x "R6 ..." (`sameContent`) ; `formActions.test.ts` :: "R6 the service's refusal reaches the person", 3 x "R6 ... answers 404" (edit page) ; `AnsweredForm.test.tsx` :: "R6 shows that version's questions and wording" ; `annexDefaultForm.test.ts` :: "R6 creates the triggers after the seed" |
| R7 | `annexDefaultForm.test.ts` :: 2 x "R7 ..." (`resolveFormVersionId`), "R7 updates and deletes no existing row" ; `FormService.test.ts` :: "R7 resolve(null) is the default version, without asking the repository", "R7 the seeded default version resolves to...", "R7 an unknown version id resolves to null" ; `AnsweredForm.test.tsx` :: "R7 the default version renders the same output as no form at all" ; `test_form_answers.py` :: `test_r7_*` (digest equality) ; `test_example_mcas.py` (existing, unchanged) ; `forms.db.test.ts` :: "R7 run on a database holding a non-latest card, no row ... changes" |
| R8 | `formChooser.test.ts` :: 6 x "R8 ..." (`preselect`) ; `FormChooser.test.tsx` :: 8 x "R8 ..." (radio group, default tag, links, Continue, same as vN, Same form as vN, not found) + 2 edit-page source checks ; `QualificationService.forms.test.ts` :: 3 x `startingPoint().fromFormVersionId` ; `prefillOnEditPage.test.ts` (existing, unchanged) |
| R9 | `QualifyFormBlocks.test.tsx` :: 20 tests (identity required, blocks absent, one test per block, question order and names, where applicable, headings by groupLabel or owner, hidden formVersionId, mixed headings, default version unchanged, no form prop = default, carry-over of answers) |
| R10 | `QualificationFormParser.test.ts` :: "R10 a form with no blocks and no questions still needs the three identity fields", "R10 the identity alone is a complete submission of an empty form" ; `annexDefaultForm.test.ts` :: "R10 the identity block is the three fields..." |
| R11 | `QualificationFormParser.test.ts` :: 9 x "R11 ..." ; `QualificationService.forms.test.ts` :: "R15 R11 a form without the description block..." |
| R12 | `QualificationFormParser.test.ts` :: 9 x "R12 ..." |
| R13 | `QualificationFormParser.test.ts` :: 2 x "R13 ..." |
| R14 | `QualificationFormParser.test.ts` :: 5 x "R14 ..." (missing count, optional blank, foreign keys ignored, mixed version, default version equals today) |
| R15 | `QualificationService.forms.test.ts` :: 6 x "R15 ..." |
| R16 | `formLibrary.test.ts` :: 5 x "R16 ..." (`filterLibrary`) ; `builderState.test.ts` :: 3 x "R16 ..." ; `FormBuilder.test.tsx` :: 4 x "R16 ..." ; `FormService.test.ts` :: "R16 one group per listed form..." (`libraryGroups`) |
| R17 | `builderState.test.ts` :: 2 x "R17 ..." ; `FormBuilder.test.tsx` :: 2 x "R17 ..." (apply, confirm "Replace the 2 questions in your form?") |
| R18 | `builderState.test.ts` :: 3 x "R18 ..." ; `FormBuilder.test.tsx` :: 4 x "R18 ..." (aria labels, disabled ends, focus kept, draggable) |
| R19 | `builderState.test.ts` :: 3 x "R19 ..." + "R6 R19 editing a form opens its own questions as its own" ; `FormBuilder.test.tsx` :: 3 x "R19 ..." |
| R20 | `builderState.test.ts` :: 2 x "R20 ..." ; `FormBuilder.test.tsx` :: "R20 a picked row names its owner form and edits into a copy" ; `FormService.test.ts` :: "R20 editing another form's question makes a copy owned by the form being saved" |
| R21 | `FormBuilder.test.tsx` :: "R21 the identity is always included, and every block has its own checkbox" ; `builderState.test.ts` :: "R21 toggling a block..." |
| R22 | `formDraft.test.ts` :: 23 x "R22 ..." (every exact message, bounds, A7) ; `FormService.test.ts` :: 10 x "R22 ..." ; `formActions.test.ts` :: 8 x "R22 ..." ; `FormBuilder.test.tsx` :: 5 x "R22 ..." ; `builderState.test.ts` :: "R22 the name travels in the draft" |
| R23 | `formLibrary.test.ts` :: 5 x "R23 ..." (`overlapHints`, `overlapLabel`) ; `FormBuilder.test.tsx` :: "R23 two questions on the same Annex point each show the overlap chip" |
| R24 | `test_form_import.py::TestCsv` :: 30 `test_r24_*` cases |
| R25 | `test_form_import.py::TestMarkdown` :: 7 `test_r25_*` |
| R26 | `test_form_import.py::TestWord` :: 3 `test_r26_*` |
| R27 | `test_form_import.py::TestLimits` :: 14 `test_r27_*` ; `prefill/tests/test_app.py::TestFormImportEndpoint` :: 9 `test_r27_*` (200 shape, warnings, 422 x3, 413, found 0, no model) |
| R28 | `FormImportClient.test.ts` :: 6 x "R28 ..." ; `FormImport.test.tsx` :: 7 x "R28 ..." ; `builderState.test.ts` :: "R28 an imported file opens as own questions..." |
| R29 | `QualifyFormBlocks.test.tsx` :: "R29 a free-text citation uses the Annex chip..." ; `AnsweredForm.test.tsx` :: "R29 ..." ; `VerticalCard.test.tsx` :: inside "R36 one Additional documentation section..." ; `FormBuilder.test.tsx` :: "R29 a question with no citation has no chip" |
| R30 | `QualificationExporter.test.ts` :: 5 x "R30 ..." |
| R31 | `test_form_answers.py` :: 8 `test_r31_*` |
| R32 | `agents/tests/test_workflow.py` :: 4 `test_r32_*` |
| R33 | `test_absent_blocks.py` :: 9 `test_r33_*` ; `ontology/tests/test_app.py` :: `test_r33_description_use_case_and_users_are_optional_now` |
| R34 | `test_coverage.py` :: 10 `test_r34_*` ; `ontology/tests/test_app.py` :: `test_r34_a_request_without_a_form_gets_no_coverage_keys` |
| R35 | `test_coverage.py` :: 3 `test_r35_*` |
| R36 | `VerticalCard.test.tsx` :: 4 x "R36 ..." ; `AnsweredForm.test.tsx` :: 4 x "R36 ..." ; `test_form_coverage.py` :: 8 `test_r36_*` ; `test_ontology_only_card.py` (existing, unchanged) |
| R37 | `aiCardExport.test.ts` :: 2 x "R37 ..." |
| R38 | `prefill/tests/test_app.py::TestPrefillWithAForm` :: 2 `test_r38_*` ; `prefill/tests/test_fields.py` :: `test_r38_the_default_questions_propose_what_the_annex_headings_do` ; `PrefillClient.test.ts` :: "R38 without a form it sends exactly what it sends today" ; existing prefill tests unchanged |
| R39 | `test_custom_form_prefill.py` :: 23 `test_r39_*` ; `prefill/tests/test_app.py` :: `test_r39_r40_a_custom_question_is_proposed_by_its_own_wording` |
| R40 | `prefill/tests/test_app.py` :: `test_r40_*` (6 cases) ; `PrefillClient.test.ts` :: "R40 sends the form's fields and questions as JSON" ; `prefillChoice.test.ts` :: 5 x "R40 ..." |
| R41 | `formsNoModel.test.ts` :: 3 x "R41 ..." ; `test_form_import.py::test_r41_*` and `test_coverage.py::test_r41_*` (AST import scans) ; `test_custom_form_prefill.py::test_r41_no_model_is_involved` |
| R42 | `formActions.test.ts` :: 3 x "R42 ..." ; `projectAccess.test.ts` (existing, unchanged) |

---

## 3. Interface names chosen where the spec is silent

The implementer should follow these; each is also stated in the header comment of the test file
that fixes it.

**Domain modules (`src/domain/forms/`)**
- `blocks.ts`: `FORM_BLOCKS`, `IDENTITY_FIELDS` (as spec).
- `legacy.ts`: `annexDefaultVersion()` returns a fresh object each call; question ids `annex-iv-<id>`,
  `ownerFormId = "annex-iv-default"`.
- `formDraft.ts`: `parseFormDraft(input, context?)`, where `context.takenNames?: string[]` are the other
  listed forms' names; the "A form called <name> already exists." check runs only when given.
  On success `value.name` is trimmed. `sameContent(draft, version)`: blocks compared as sets, the name is
  not content, a pick matches by id, an own question matches by id plus text/citation/required/annexPoint,
  an own question without id or a copy is always a change.
- `builderState.ts`: state `{ formId, name, description, blocks, questions, origin }`; rows
  `{kind:"pick", questionId, source}`, `{kind:"own", questionId?, text, citation, required, annexPoint}`,
  `{kind:"copy", fromQuestionId, text, citation, required, annexPoint, source}`. Actions: `tick {question}`,
  `untick {questionId}`, `startFrom {form}`, `move {from, to}` (out of range is a no-op),
  `addOwn {values}`, `edit {index, values}` (a pick becomes a copy, an own keeps its id, a copy stays a
  copy of the same source), `remove {index}`, `toggleBlock {block}`, `setName {name}`.
  `initialBuilderState({ name?, blocks?, questions?, origin?, startFrom?, edit? })`: `edit` opens the
  form's own questions as `own` with their ids and the rest as picks, sets `formId` and `name`.
  Exported helpers `isTicked(state, questionId)` and `toDraft(state)` (blocks in FORM_BLOCKS order,
  no display fields).
- `library.ts`: groups are `{ formId, formName, questions: ResolvedQuestion[] }`; `overlapHints` returns
  a plain object `questionId -> AnnexPointId`; `overlapLabel(point)` returns `"≈ overlaps <citation>"`.
- `chooser.ts`: `preselect(options: {formId, versionIds}[], {fromFormVersionId, fromFormListed,
  defaultFormId})` returns `{param: "form" | "formVersion", id}`. Options carry all version ids of each
  listed form, because the spec's input has no form id for the previous card's version.

**FormService (`src/server/services/FormService.ts`)**
- `new FormService(repository, { newId? })`. `newId` mints form, version and question ids (default: any
  lowercase unique id valid in `^[a-z0-9-]+$`); a form's scope is `f-<form id>`.
- Repository methods it may call (documented in `test/support/fakeFormStore.ts`): `listForms`,
  `findForm`, `findVersion` (with `form` and `questions[].question.ownerForm`, position order),
  `versionsOf` (number ascending, same shape), `findQuestion` (with `ownerForm`), `questionsOwnedBy`,
  `insertVersion(plan)` (one transaction; plan `{form?, version, newQuestions, snapshots}`; a taken
  `(formId, number)` throws an error with `code: "P2002"`), `setDefault(formId)`.
- `resolve(id | null)`: `null` returns `annexDefaultVersion()` without touching the repository (this
  keeps `cardSubmission.test.ts`, which builds QualificationService without a forms dependency, green);
  an unknown id returns `null`.
- `library()` rows: `{ formId, name, description, origin, builtin, isDefault, versionId, version,
  questionCount }`. `libraryGroups()` (new, for the builder's left column). `latestVersion(formId)`
  returns `ResolvedFormVersion | null`.
- `saveDraft(draft, { formId?, listed, origin? })` returns `{ok:true, formId, versionId, number,
  created}` or `{ok:false, error}`; stores blocks in FORM_BLOCKS order; `origin` defaults to `builder`;
  name collisions are checked for new listed forms only.
- `setDefault(project, formId)` returns `{ok:true}` or `{ok:false, error:"That form cannot be the default."}`.

**Server actions and pages**
- `saveForm(project, draftJson, formId?, origin?)`, `useFormOnce(project, draftJson, origin?)`,
  `setDefaultForm(project, formId)`; module singletons `formService` and `callerAccess`. `useFormOnce`
  sets the name to "Custom questions" before validating. A draft that is not JSON returns `{error}`.
- `forms/[formId]/edit/page.tsx` calls `formService.latestVersion(formId)` and `notFound()` for null,
  builtin or unlisted.
- `FormImportClient(baseUrl = PREFILL_URL, fetchImpl = fetch)`; a non-OK response without a detail
  gives an error naming the status.

**Components**
- `FormChooser` props: `project`, `options` (`{formId, name, versionNumber, questionCount, isDefault,
  versionIds}`), `preselected`, `previous` (`{cardVersionNumber, formVersionId, listed}` or null),
  `error`. The group is a fieldset with legend "Which form?" (or an explicit radiogroup); Continue calls
  `router.push("/p/<project>/system/edit?<param>=<id>")`.
- `FormBuilder` props: `project`, `library`, `forms` (Start from), `initial` (initialBuilderState's
  argument). Columns are `<section aria-label="Question library">` and `<section aria-label="Your form">`.
  Name input labelled "Form name"; search labelled "Search questions"; "Start from" select plus "Apply";
  the editor has a textarea (`required`, `maxLength=2000`), the citation input (`maxLength=200`, the
  spec's placeholder), a "Required" checkbox, the "Answers Annex IV point" select and a "Save question"
  button. Saving calls `saveForm(project, JSON.stringify(draft), formId?, origin?)`.
- `FormImport` props: `project`, `library`, `forms`; calls `readFormFile(formData)` with the file under
  `"file"`; preview rows have a text input, citation input, "Required" checkbox and "Remove" button;
  warnings render as `li`.
- `QualifyForm`: `form?: ResolvedFormVersion`, defaulting to the default version; the old `keyQuestions`
  prop is still accepted and ignored (two existing mounts pass it).
- `AnsweredForm`: `form?: ResolvedFormVersion`, defaulting to the default version.

**Other TS**
- `QualificationFormParser.parse(formData, form?)`: `form` defaults to the default version.
  `ParsedQualification` gains `formVersionId`. A missing identity field throws the same message as a
  blank one.
- `QualificationService(repo, parser, platform, forms)`, with `forms.resolve(id|null)` returning null
  for unknown. `startingPoint()` adds `fromFormVersionId`.
- `toExport(q, form?)`: without a form it is exactly today's export.
- `src/lib/prefillChoice.ts`: `prefillableFor(form)`, `prefillFormSpec(form)` (returns `{fields,
  questions}`; fields = identity + included block ids + question fields), and
  `currentAnswers(formData, prefillable?)`.

**Python**
- `airo_min/annex_points.py`: `ANNEX_POINTS` (the JSON's `points` list), `annex_citation(id)` (raises
  `KeyError` or `ValueError` for other ids), `candidate_paths()`, `load_annex_points()`, module-level
  `_PACKAGE` and `_APP_ROOT` as in `pickers.py`.
- `airo_min/coverage.py`: `coverage(form, answers)`. `build_view(graph, form=None, answers=None)`;
  `app.py` passes the request's `form` and `answers`. Additional documentation entries take the
  question's citation from the form, not the answer's.
- `prefill/form_import.py`: `parse_form_file(raw, filename)` returns an object with `.format`,
  `.questions` (items with `.text`, `.citation`, `.required`) and `.warnings`; refusals raise
  `DocumentUnreadable` (or a subclass). "line <L>" for CSV is the 1-based line in the file, header
  included. "Removed N duplicate question(s)." is plural-aware, like the heading warning.
- `prefill/fields.py`: `proposals_for_questions(text, questions)`.
- The migration's seed must be literal `INSERT INTO ... (cols) VALUES (...)` rows; the unit test parses
  them.

---

## 4. Commands

```bash
cd apps/qualification

# vitest (unit + component; DB tests skip without the env)
npm test

# DB-gated (needs docker; starts a throwaway Postgres on a random port, refuses 5432; NOT run here)
test/db/throwaway-db.sh
```

The four Python services have no venv of their own except prefill. I used throwaway venvs in the
session scratchpad (`uv venv` + `uv pip install -r requirements.txt pytest httpx`, plus `rdflib==7.6.0`
for agents). Two environment quirks: some `__pycache__` folders are root-owned, stale builds from
`/w` in the container (so `PYTHONPYCACHEPREFIX` points elsewhere), and `services/agents/application.log`
is root-owned (so agents runs from another working directory).

```bash
P=<a scratch dir>
cd services/ontology && PYTHONPYCACHEPREFIX=$P/pyc <venv>/bin/python -m pytest -p no:cacheprovider
cd services/prefill  && PYTHONPYCACHEPREFIX=$P/pyc .venv/bin/python -m pytest -p no:cacheprovider
cd services/system_card_renderer && PYTHONPYCACHEPREFIX=$P/pyc <venv>/bin/python -m pytest -p no:cacheprovider
cd $P/agents-cwd && PYTHONPYCACHEPREFIX=$P/pyc <venv>/bin/python -m pytest -p no:cacheprovider \
   -c <app>/services/agents/pytest.ini --rootdir <app>/services/agents <app>/services/agents/tests
```

New Python tests that need a missing module import it per test (a fixture, or a `try/except
ImportError` stand-in that re-raises), so a missing module fails those tests and never aborts the
rest of the suite at collection.

---

## 5. Red run (2026-09-25)

### Before any change (baseline)

| Suite | Result |
|---|---|
| vitest | 51 files, 421 passed, 20 skipped (DB) |
| ontology | 182 passed, **3 failed**: `test_build::test_a_full_qualification_exercises_all_nineteen_properties`, `test_example_mcas::test_it_exercises_all_nineteen_properties`, `test_roundtrip::test_the_rebuilt_graph_keeps_every_airo_relation`. Their expected property set includes `hasModel`, `hasTrainingData`, `hasTestingData`, `hasValidationData`, which the example has no engine components for. Not related to this feature. |
| agents | 146 passed (with rdflib installed; from another working directory) |
| prefill | 73 passed |
| renderer | 9 passed |

### After (tests written, no implementation)

| Suite | Pre-existing | New |
|---|---|---|
| vitest | 421 passed, 20 skipped: unchanged | 92 failed, 10 passed, 14 skipped (DB). Also 11 new files fail at import on the missing module (about 158 declared tests: annexDefaultForm 14, annexPoints 6, FormService 30, builderState 17, formLibrary 10, formChooser 6, formDraft 31, FormImportClient 6, FormChooser 10, FormBuilder 21, FormImport 7) |
| ontology | 182 passed, the same 3 failing as before | 27 failed, 7 errors (the `ap` fixture's ImportError), 8 passed |
| agents | 146 passed | 2 failed, 2 passed |
| prefill | 73 passed | 98 failed, 2 passed |
| renderer | 9 passed | 7 failed, 1 passed |

Every failure was checked for its reason: a missing module, function, endpoint or export
("Cannot find package '@/domain/forms/...'", "No module named 'airo_min.coverage'", 404 on
`/forms/import`, "prefillableFor is not a function"), or today's behaviour where the spec asks for new
behaviour (the parser still asks for the description, `toExport` sorts by question id, `build_graph`
writes `qual:description ""` and the Purpose and AIUser nodes, the untagged answer is in the Turtle,
the PDF still prints empty Overview rows, `answer_for` still matches `q12a` by suffix). None fails on
a typo or on a broken import inside a test.

**New tests that pass already, by design.** They pin behaviour that must not change, or scan code
that does not exist yet:
- vitest (10): `PrefillClient` "R38 without a form it sends exactly what it sends today";
  `QualificationExporter` "R30 a block the form leaves out exports as stored", "R30 still JSON";
  `QualificationService.forms` "R15 a description is passed on as it was"; `VerticalCard` "R36 a view
  without coverage..."; `aiCardExport` both R37 tests (the view is already passed through verbatim);
  `formActions` "R42 a viewer may open ... but not save" (the existing `decide`); `formsNoModel`
  2 scans (vacuous until the files exist; the file-existence test beside them is red).
- ontology (8): `test_r7_*` x2 (digest equality holds today), `test_r31_a_seeded_answer_with_its_tag...`,
  `test_r31_an_answer_without_the_annex_point_key...`, `test_r33_no_deployers...` x2,
  `test_r34_no_form_means_no_coverage_keys_in_the_view`, `test_app::test_r34_a_request_without_a_form...`.
- agents (2): `test_r32_no_tagged_answer...`, `test_r32_without_any_annex_point_key...`.
- prefill (2): both R38 tests (today's `/prefill` ignores the two new fields).
- renderer (1): `test_r36_no_coverage_means_no_summary_line_and_the_card_as_before`.

The DB-gated file skips (14 tests) without `QUALIFICATION_TEST_DATABASE_URL` and
`QUALIFICATION_TEST_ADMIN_URL`, refuses ports 5432 and 5433, and was not run (it needs docker). Its
R7 test reverts this migration inside a transaction, digests the five history tables, reapplies the
migration and compares the digests, then rolls back.

---

## 6. Spec gaps and contradictions found

1. **Parser second argument.** Section 5.2 makes `parse(formData, form)` required and section 9.8 says
   the existing parser cases pass `annexDefaultVersion()`. But `prefillOnEditPage.test.ts`, which
   section 9.8 says must pass unmodified, calls `new QualificationFormParser().parse(form)` with one
   argument. Resolved as: `form` defaults to the default version, the existing parser cases stay as
   they are, and one new R14 test compares both calls explicitly.
2. **QualifyForm prop.** R9 says `form` replaces `keyQuestions`, but `formPrefill.test.tsx` and
   `formUpload.test.tsx` (the second one is not in section 9 at all) mount it with `keyQuestions`.
   Resolved as: `form` is optional with the default version, and `keyQuestions` is tolerated. The same
   reasoning makes the `forms` dependency of QualificationService default to FormService, with
   `resolve(null)` answered in memory, so `cardSubmission.test.ts` stays green unmodified.
3. **R34 MCAS "14 of 14".** `services/ontology/examples/mcas.qualification.json` has 13 answers (no 1(f);
   `test_example_mcas.py` asserts 13), so under A16 the committed JSON gives "13 of 14". `mcas.ts`
   answers 1(f). The tests cover both: the committed JSON gives 13, and the JSON plus the 1(f) answer
   gives 14. Needs a decision if 14 was meant for the committed JSON.
4. **R38 against R39 for merged points.** R39 ends an answer at the next Annex heading, first match
   wins, which would give only the 1(d) text when a document has both 1(d) and 1(e). Legacy
   `annex_sections` joins both, and R38 requires the default form to equal legacy. The tests follow
   R38: Annex-heading matches of a tagged question join, as `annex_sections` does.
5. **Name uniqueness in `parseFormDraft(input)`.** A pure one-argument function cannot know the other
   forms' names. Added the optional `context.takenNames`; `saveDraft` enforces it too.
6. **R17 wording.** "`{kind:"pick"}` for questions S does not own and `{kind:"pick"}` for those it does"
   repeats the same kind twice. Tested as: every question is a pick.
7. **Previous card's form in `preselect`.** The spec's input lacks the form id of the previous card's
   version. Options carry `versionIds` to bridge that.
8. **Origin for import saves.** The spec's `saveForm(project, draftJson, formId?)` has no way to say
   `import`. Added an optional fourth argument (and a third one on `useFormOnce`).
9. **Renderer "no classification".** `SystemCard.classification` is required; the policy-only payload
   sends empty lists. If "no classification" means the key is absent, the model needs a default.
10. **Not covered by any test:** the header line "Form: <name> v<N>" (section 7, no R-id), the library
    page `/forms` table (section 7) and `?example=mcas` skipping the chooser at run time (only a source
    check), the Dockerfile edit is checked as text only.
