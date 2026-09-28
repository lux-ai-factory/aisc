# Form assembly: implementation progress (stage 4)

Implementer 1 covers plan tasks 0 to 10. Implementer 2 continues from task 11 using this log and
`03-plan.md`. Paths are relative to `apps/qualification` unless absolute.

## Environment (read this first)

- Branch `feat/unified-modules`, checked, not switched. Nothing committed, nothing staged.
- Scratchpad `P=/tmp/claude-1001/-home-listuser/572e79f5-831d-4f75-909f-47cb45306c7a/scratchpad`.
- The venvs already existed there from the test writer; reused, not recreated:
  - ontology: `$P/venv-ontology`
  - renderer: `$P/venv-system_card_renderer` (the plan calls it `venv-renderer`; same thing, other name)
  - agents: `$P/venv-agents` (has rdflib 7.6.0)
  - prefill: `services/prefill/.venv` (as it is)
- `services/prefill/pytest.ini` already sets `addopts = -q`: do not add `-q` again, or pytest drops the
  summary line (`-qq`).
- Always `PYTHONPYCACHEPREFIX=$P/pyc` and `-p no:cacheprovider`; agents runs from `$P/agents-cwd`.

## Task 0: baseline

Commands: the section 6 commands of the plan.

| Suite | Result |
|---|---|
| vitest | 67 files (21 failed, 42 passed, 4 skipped); 557 tests (92 failed, 431 passed, 34 skipped) |
| tsc | 0 errors outside `test/` |
| ontology | 30 failed, 190 passed, 7 errors |
| prefill | 98 failed, 75 passed |
| renderer | 7 failed, 10 passed |
| agents | 2 failed, 148 passed |

Matches the plan's expected baseline.

## Task 1: shared data, default form, migration, Prisma schema (done)

Files created:
- `src/data/annexPoints.json` (spec section 2, verbatim)
- `src/domain/forms/annexPoints.ts` (`ANNEX_POINTS`, `AnnexPointId`, `isAnnexPoint`, `annexCitation`, which throws on an unknown id)
- `src/domain/forms/blocks.ts` (`FORM_BLOCKS`, `FormBlock`, `IDENTITY_FIELDS`, plus `isFormBlock(s)` and `inBlockOrder(blocks)`)
- `src/domain/forms/types.ts` (`ResolvedQuestion`, `ResolvedFormVersion`)
- `src/domain/forms/legacy.ts` (`DEFAULT_FORM_ID`, `DEFAULT_VERSION_ID`, `resolveFormVersionId`, `annexDefaultVersion`)
- `prisma/migrations/20260925090000_forms_are_data/migration.sql` (plan section 3; the 28 seed rows were
  generated from `keyQuestions.ts` by `$P/gen_seed.py`, a scratchpad script, not in the repo)

Files modified:
- `prisma/schema.prisma` (the four models verbatim from spec 4.1; `Qualification.formVersionId` + relation + index;
  the answer unique key now `(qualificationId, toolId, questionId)` with the snake_case map name)
- `npx prisma generate` run (touches only `node_modules/.prisma`).

Commands:
- `npx vitest run test/unit/annexPoints.test.ts test/unit/annexDefaultForm.test.ts`: 2 files, 20 passed.
- `DATABASE_URL="postgresql://x:x@127.0.0.1:1/x?schema=qualification" npx prisma validate`: valid.

Deviation: `prisma validate` refuses to run without `DATABASE_URL` in the environment; a dummy URL on
port 1 is passed only so it parses the schema (validate never connects).

## Task 2: pure domain modules (done)

Files created: `src/domain/forms/formDraft.ts`, `builderState.ts`, `library.ts`, `chooser.ts`.

Command: `npx vitest run test/unit/formDraft.test.ts test/unit/builderState.test.ts test/unit/formLibrary.test.ts test/unit/formChooser.test.ts`
Result: 64 passed (31 + 17 + 10 + 6). Note: vitest filters by substring, case-insensitively, so
`formChooser.test.ts` also selects `test/unit/FormChooser.test.tsx` (task 17), which fails at import until
`src/app/p/[project]/system/edit/FormChooser.tsx` exists. Expected, not a regression.

Notes for later tasks:
- `formDraft.ts` exports `FormDraft`, `DraftQuestion`, `parseFormDraft(input, {takenNames?})`, `sameContent`, and the
  limits `MAX_NAME`/`MAX_DESCRIPTION`/`MAX_QUESTIONS`/`MAX_TEXT`/`MAX_CITATION`. The zod shape error is the generic
  "The form could not be read." Messages not fixed by the tests: description "A form description is at most 500
  characters.", duplicate block "<id> is in the form twice."
- `builderState.ts`: the counter for `rowKey` lives in the state (`nextRow`), not in a module variable, so the
  reducer is pure (safe under React StrictMode double calls). Rows are `BuilderRow` (`rowKey` + pick/own/copy);
  `initialBuilderState` accepts rows without `rowKey` (`BuilderRowInput`). Exports `QuestionValues`,
  `BuilderAction`, `BuilderInit`. `toDraft` strips `rowKey` and `source`.
- `library.ts` exports `LibraryGroup`, `filterLibrary`, `overlapHints`, `overlapLabel`.
- `chooser.ts` exports `preselect` (returns `null` only when there is no option at all) and `ChooserPick`.
- `npx tsc --noEmit`: 0 errors in `src/`.

## Task 3: Python Annex points loader (done)

Files: created `services/ontology/airo_min/annex_points.py` (imports `app_root_for` from `.pickers`);
`services/ontology/Dockerfile` gained exactly the one line
`COPY src/data/annexPoints.json ./airo_min/annex_points.json` after the vocabulary COPY. No image built.
`annex_citation(id)` raises `KeyError` for any other id.

Command: `(cd services/ontology && PYTHONPYCACHEPREFIX=$P/pyc $P/venv-ontology/bin/python -m pytest -p no:cacheprovider tests/test_annex_points.py)`
Result: 8 passed.

## Task 4: Python graph and view (done)

Files:
- `services/ontology/airo_min/build.py`: imports `annex_citation` from `.annex_points`; `_SEEDED_SCOPES =
  {"annex-1","annex-2"}`; identity and metadata read with `.get(key, "")`; `qual:description`, the Purpose node
  and the AIUser node only when their text is non-empty; `_add_risk` takes `next(iter(...), None)` and links
  `hasImpactOnStakeholder` only when found; the answers loop follows plan task 4 exactly (no key: legacy; None:
  skipped; a point: `qual:citation = annex_citation(p)`, plus `qual:annexPoint` and `qual:sourceCitation` only for
  scopes other than the seeded ones; an unknown point raises `ValueError`, so the service answers 422).
  `_annex_citation` unchanged.
- `services/ontology/airo_min/coverage.py` (new): `coverage(form, answers)`, `additional_documentation(form, answers)`.
- `services/ontology/airo_min/view.py`: `build_view(g, form=None, answers=None)`; the three keys are added only
  when `form` is not None.
- `services/ontology/app.py`: `description`/`targetUseCase`/`targetUsers` default to `""`; `form: dict | None = None`
  declared on `Qualification`; `build` passes `form` and `answers` only when a form was sent.

Commands:
- plan task 4 selection (`test_form_answers test_absent_blocks test_coverage test_app test_example_mcas test_build`):
  88 passed, 2 failed (the pre-existing `test_example_mcas::test_it_exercises_all_nineteen_properties` and
  `test_build::test_a_full_qualification_exercises_all_nineteen_properties`, plan 6.4).
- full ontology suite: 224 passed, 3 failed (exactly the three of plan 6.4). Matches the plan's final expectation.

## Task 5: the filler reads tags (done)

File: `services/agents/fill/workflow.py` `answer_for`: when any answer has the `annexPoint` key, the point is
`wanted.lower().replace("-", "")` and the result is every non-empty tagged answer for that point, in export
order, joined by a blank line; otherwise the suffix rule, unchanged.

Commands (from `$P/agents-cwd`, plan section 6.2 line): `-k r32` 4 passed; full suite 150 passed.

## Task 6: PDF renderer (done)

Files: `services/system_card_renderer/models.py` (`CoveragePoint`, `CoverageAnnex`, `CoverageForm`, `Coverage`,
`AdditionalEntry`, `AdditionalSection`; `Ontology.coverage` optional, `Ontology.additionalDocumentation` default
`[]`; `classification` still required); `templates/system_card.html.j2` (the three Overview rows each behind an
`{% if %}`; `<p class="coverage">` right after `<h2>Ontology</h2>`; after the risk chains one
`h3 "Additional documentation: <form>"` + a `dl.kv` of question (with `span.cite` only for a non-empty citation)
and answer per section). Nothing else changed.

Command: `(cd services/system_card_renderer && PYTHONPYCACHEPREFIX=$P/pyc $P/venv-system_card_renderer/bin/python -m pytest -p no:cacheprovider)`
Result: 17 passed.

## Task 7: form import (done)

Files: created `services/prefill/prefill/form_import.py` (`ImportedQuestion`, `FormImport`, `parse_form_file`;
imports only the standard library, `docx` and `prefill.documents`); `services/prefill/app.py` gained
`POST /forms/import` (413 over `MAX_BYTES` read at call time, 422 with `str(exc)` on `DocumentUnreadable`,
200 body exactly `{format, found, questions, warnings}`).
Choices the tests leave open: a duplicate is detected before the citation is cut (a dropped duplicate gets no
"shortened" warning); a multi-line HTML comment is skipped until `-->`; .docx table rows are numbered after the
last paragraph number.

Commands: `$PREF tests/test_form_import.py)` 53 passed; `$PREF tests/test_app.py -k TestFormImportEndpoint)` 9 passed.

## Task 8: prefill for a custom form (done)

Files:
- `services/prefill/prefill/fields.py`: added `norm`, `annex_sections_by_point` (point id -> (answer, first
  heading line)), `_ANNEX_CITATIONS` (the default citations never name a question on their own, R38 guard),
  `proposals_for_questions(text, questions)`. Every existing function unchanged.
- `services/prefill/app.py` `/prefill`: optional `fields` and `questions` form fields, each parsed with
  `_form_json(..., list, ...)` (422 "fields: ..." / "questions: ..."; a question item without a string
  `field` is also 422 "questions: ..."). Both absent: exactly today's path (`proposals_from_text`). Otherwise
  `metadata_from_text` + (`proposals_for_questions` or `annex_sections`), filtered to `fields`; no `"risks"` in
  `fields` gives `risks: None`, `risksKept: False`, `risksProposed: 0` without reading risks.
- `services/prefill/README.md`: documents the two new `/prefill` fields and `POST /forms/import`.

Command: `(cd services/prefill && PYTHONPYCACHEPREFIX=$P/pyc .venv/bin/python -m pytest -p no:cacheprovider)`
Result: 173 passed (every existing prefill test unchanged).

## Task 9: the parser takes the form (done)

Files:
- `src/server/forms/QualificationFormParser.ts`: `parse(formData, form = annexDefaultVersion())`; zod removed from
  this file (plain checks keep the same messages and the same order: identity, then description, targetUseCase,
  targetUsers, intendedDeployers, then target systems and sectors, then market forms and localities, then
  questions, then risks). Every text field read through `this.trimmed` (missing reads as ""). `ParsedQualification`
  is now an explicit type with `intendedDeployers: string | null` and `formVersionId: string` (= `form.versionId`).
  Answers keep only `q:` fields that are a question `field` of the version, emitted as
  `{toolId: q.scope, questionId: q.localId, answer}`. Risks parsed only when `"risks"` is a block.
  The `KEY_QUESTIONS`/`keyQuestionIdSet` imports are gone from the parser (the functions stay in keyQuestions.ts).
- `src/server/repositories/QualificationRepository.ts`: `CreateQualificationInput.intendedDeployers: string | null`,
  `formVersionId: string`.

Command: `npx vitest run test/unit/QualificationFormParser.test.ts test/unit/prefillOnEditPage.test.ts test/unit/cardSubmission.test.ts`
Result: 3 files, 54 passed. `npx tsc --noEmit`: 0 errors in `src/`.

Note for task 11: `QualificationService.createFromForm` today spreads `parsed` into `repo.create`, so it already
type-checks (and stores `formVersionId` from the parser's default version). Task 11 must still set
`formVersionId: form.versionId` from the resolved form, as the plan says.

## Task 10: FormRepository and FormService (done)

Files created:
- `src/server/repositories/FormRepository.ts`: `FormRepository(db = prisma)` with exactly the methods of
  `test/support/fakeFormStore.ts` (`listForms`, `findForm`, `findVersion`, `versionsOf`, `findQuestion`,
  `questionsOwnedBy`, `insertVersion` in one `$transaction`, `setDefault` in one `$transaction`). Exports the types
  `FormVersionRow` (the include of plan task 10), `FormQuestionWithOwner`, `VersionInsert`. No work in the
  constructor; no module singleton (FormService makes its own).
- `src/server/services/FormService.ts`: `FormService(repository = new FormRepository(), { newId = randomUUID })`,
  `export const formService`. Methods `resolve`, `latestVersion`, `library()` (no parameters), `libraryGroups()`,
  `chooserOptions()` (library rows + `versionIds`, ascending; untested, for the edit page), `setDefault(project,
  formId)`, `saveDraft(draft, {formId?, listed, origin?})`, all as plan task 10. Exports types `LibraryRow`,
  `ChooserOption`, `SaveResult`.
  Message not fixed by the tests: saving over a missing, builtin or unlisted form gives "That form cannot be
  changed."

Command: `npx vitest run test/unit/FormService.test.ts`: 30 passed. `npx tsc --noEmit`: 0 errors in `src/`.

## After task 10: all five suites (2026-09-25)

| Suite | Result |
|---|---|
| vitest | 67 files (13 failed, 50 passed, 4 skipped); 671 tests (64 failed, 573 passed, 34 skipped) |
| tsc | 22 errors, all in `test/` (imports of modules that tasks 13 to 19 create); 0 in `src/` |
| prisma validate | valid (with the dummy `DATABASE_URL`, see task 1) |
| ontology | 224 passed, 3 failed (exactly the three pre-existing ones of plan 6.4) |
| prefill | 173 passed |
| renderer | 17 passed |
| agents | 150 passed |

The Python suites are at their final expected counts (plan 6.2). Every remaining vitest failure belongs to a
task from 11 on:
- `QualificationService.forms.test.ts` (8): task 11
- `QualificationExporter.test.ts` (3), and the export/ontology route side: task 12
- `PrefillClient.test.ts` (1), `prefillChoice.test.ts` (5), `FormImportClient.test.ts` (import): task 13
- `formActions.test.ts` (17): tasks 14, 17, 19
- `QualifyFormBlocks.test.tsx` (20): task 15
- `AnsweredForm.test.tsx` (6), `VerticalCard.test.tsx` (3): task 16
- `FormChooser.test.tsx` (import): task 17
- `FormBuilder.test.tsx` (import): task 18
- `FormImport.test.tsx` (import), `formsNoModel.test.ts` (1): task 19

`git -C apps/qualification diff --stat -- test services/*/tests`: 11 files, 889 insertions, 0 deletions (unchanged).
`git status` lists only the files named in tasks 1 to 10 above (plus the untouched new test files).

## DB-gated tests (plan 6.3), run on a throwaway Postgres

`test/db/throwaway-db.sh` (random free port, refuses 5432, container `aisc-t-qual-<random>`, removed afterwards;
checked with `docker ps -a` after every run: no container left). `npx prisma generate` had been run in task 1.

Result: 3 files, 33 tests (not 34 as the plan says: `cardVersions.db.test.ts` has 13, `forms.db.test.ts` 14, the
third file the rest), 30 passed, 3 failed:

1. `test/db/cardVersions.db.test.ts::S3.3 the migration file refuses cards pointing at versions missing from
   core.system`: a pre-existing test of the earlier migration `20260923180000`; it inserts a card with a random
   `project_id` and now trips `Qualification_project_id_fkey` (added by `20260924120000`) before its own check.
   Unrelated to forms; not touched.
2. `test/db/forms.db.test.ts::R4 a second is_default row fails on form_one_default`: **test looks wrong.** The
   index does fire (psql on the same DB: `ERROR: duplicate key value violates unique constraint
   "form_one_default"`), but the test runs the SQL through `prisma.$executeRawUnsafe`, whose error text for
   23505 is only `Code: 23505. Message: Key ((true))=(t) already exists.` and never carries the index name, so
   `/form_one_default/` cannot match. Suggested fix for the test writer: also accept `/23505|already exists/`, or
   check the name through psql (as the R7 test does). Not worked around in the migration (it would take a sixth
   trigger, which plan section 3 forbids, or an index expression chosen only to print its name).
3. `test/db/forms.db.test.ts::R7 run on a database holding a non-latest card, no row of the five history tables
   changes`: **test looks wrong (order dependent).** To revert the migration it recreates the old unique index
   on `(qualificationId, questionId)`, but the earlier R5 test in the same file has already committed a card with
   `q1` under both `f-ff` and `f-gg`, so the revert fails with `could not create unique index ...
   is duplicated` before the migration is ever re-run. Run first on a clean throwaway DB
   (`KEEP=1 test/db/throwaway-db.sh`, then `npx vitest run test/db/forms.db.test.ts -t "R7 run on a database"`,
   then `docker rm -f`), it passes: the migration itself leaves history unchanged. Suggested fix: run the revert
   and re-apply on data the test creates itself, or delete the R5 rows (or use distinct question ids) before
   recreating the old index.

Every other new DB test passes: R1 seed field by field, R6 triggers and checks, R5 the new answer key, R4
unlisted default refused, R6 the card's FK is RESTRICT.

## Tests believed wrong (summary)

- `test/db/forms.db.test.ts::R4 a second is_default row fails on form_one_default` (Prisma's raw error hides the
  index name; the constraint itself works).
- `test/db/forms.db.test.ts::R7 run on a database holding a non-latest card, ...` (depends on the R5 test not having
  run first; passes alone).
No unit or Python test was found wrong.

## Handover to implementer 2 (task 11 on)

- Start with task 11. `formService` (`src/server/services/FormService.ts`) and `resolveFormVersionId`
  (`src/domain/forms/legacy.ts`) exist; `FormService.chooserOptions()` exists for task 17.
- Parser: `parse(formData, form)` returns `formVersionId`; set `formVersionId: form.versionId` explicitly in
  `repo.create` anyway (plan task 11).
- `prefillChoice.ts` (task 13) can import `FORM_BLOCKS`/`IDENTITY_FIELDS` from `@/domain/forms/blocks` and types
  from `@/domain/forms/types`.
- The builder (task 18) should use `BuilderRow.rowKey` for React keys and focus; the counter lives in the state.
- Before each proof run, `git status --short` and leave any file you did not create or edit alone.

---

# Implementer 2: tasks 11 to 20 (2026-09-25)

Same environment as above (scratchpad venvs, `PYTHONPYCACHEPREFIX`, agents from `$P/agents-cwd`). Nothing
committed, staged, stashed or reset. No test, fixture or test-support file touched.

## Task 11: QualificationService stores the version (done)

Files: `src/server/services/QualificationService.ts` (fourth constructor parameter `forms: FormResolver =
formService`; `createFromForm` resolves the posted `formVersionId` (blank or missing is null), refuses an
unknown one with `FormValidationError("The form this was filled with no longer exists. Reload the page.")`
before the platform is asked, parses with that version, passes `description: "" -> null` to `createVersion`
(same four keys), and stores `formVersionId: form.versionId`; `startingPoint` also returns
`fromFormVersionId`); `src/domain/cardVersions.ts` (`CardContent.formVersionId?: string | null`);
`QualificationRepository.cardSummary` selects `formVersionId`; `src/domain/forms/types.ts` gained
`FormResolver` (shared by QualificationService and OntologyService).

Command: `npx vitest run test/unit/QualificationService.forms.test.ts test/unit/cardSubmission.test.ts test/unit/cardVersionsInCoreSystem.test.ts`: 3 files, 27 passed.

## Task 12: export, ontology service, view types (done)

Files: `QualificationExporter.ts` (`toExport(q, form?)`; without a form byte-for-byte as before; with one,
the version's answers first in version order with `citation` and `annexPoint`, stray answers last by
`toolId:questionId` in the legacy shape, plus `form: {name, version, questions}`); `OntologyService.ts`
(fourth parameter `forms`, `build` and `patchNode` export through `exportOf`, which resolves
`q.formVersionId ?? null` and falls back to no form on null); `api/qualifications/[id]/extracted/route.ts`
GET the same; `src/domain/OntologyView.ts` (`Coverage`, `AdditionalSection`, optional `form`, `coverage`,
`additionalDocumentation`).

Command: `npx vitest run test/unit/QualificationExporter.test.ts test/unit/aiCardExport.test.ts test/unit/engineComponents.test.ts test/unit/systemVersionOntologyRoute.test.ts`: 4 files, all passed (48 with task 11's file).

## Task 13: prefill and import clients (done)

Files: `PrefillClient.ts` (`read(..., formSpec?)`; `fields`/`questions` set only when given);
`src/lib/prefillChoice.ts` (`prefillableFor`, `prefillFormSpec`, type `PrefillFormSpec`, and
`currentAnswers(form, prefillable = PREFILLABLE)`; every existing export unchanged; imports only
`@/domain/forms/blocks` and types); new `src/server/services/FormImportClient.ts` (never throws; also
guards an OK response whose body is not JSON).

Command: `npx vitest run test/unit/PrefillClient.test.ts test/unit/prefillChoice.test.ts test/unit/prefillOnEditPage.test.ts test/unit/FormImportClient.test.ts`: 4 files, 35 passed.

## Task 14: server actions (done)

Files: `src/app/p/[project]/forms/actions.ts` (`saveForm`, `useFormOnce`, `setDefaultForm`, `"use server";`
first) and `src/app/p/[project]/forms/import/actions.ts` (`readFormFile`). Untestable choice: a draft that is
not JSON gives "The form could not be read." (the same text as formDraft's shape error).

Command: `npx vitest run test/unit/formActions.test.ts -t "setDefaultForm|saveForm|useFormOnce|viewer"`: 13 passed
(and `-t "server actions"` 1 passed).

## Task 15: the qualification form renders the version (done)

Files: `qualify/new/QualifyForm.tsx` (`form?` prop, `keyQuestions?` kept and ignored; identity always;
the four text fields and four pickers only when their block is included; the documentation section only
when there are questions, headings on a change of `groupLabel ?? ownerFormName`, chip only for a non-empty
citation; `RiskRows` only with the risk block; hidden `formVersionId`); `useDocumentPrefill.ts`
(`useDocumentPrefill(initialRisks, form?)`; `currentAnswers` against `prefillableFor(form)`; `fields` and
`questions` added to the action's FormData only when the form is not `annex-iv-default-v1`);
`prefill-actions.ts` (parses them when present, passes `{fields, questions}` as the fifth argument).

Command: `npx vitest run test/unit/QualifyFormBlocks.test.tsx test/unit/formPrefill.test.tsx test/unit/formUpload.test.tsx test/unit/DocumentUpload.test.tsx test/unit/prefillOnEditPage.test.ts`: 5 files, 56 passed.

## Task 16: the card reads its version (done)

Files: `qualify/[id]/AnsweredForm.tsx` (`form` defaults to `annexDefaultVersion()`; blocks, groups, chips and
the risk section follow the version; byte-identical for the default version, test R7 proves it);
`VerticalCard.tsx` (coverage line first; About heading and table only with rows; Risks heading only with
chains; one "Additional documentation: <form>" section per entry after the chains); `qualify/[id]/page.tsx`
(resolves the card's version, falls back to the default, passes it on, shows "Form: <name> v<N>" under the
header).

Command: `npx vitest run test/unit/AnsweredForm.test.tsx test/unit/VerticalCard.test.tsx test/unit/aiCardExport.test.ts`: 3 files, 33 passed.

## Task 17: the chooser and the edit page (done)

Files: new `system/edit/FormChooser.tsx`; `system/edit/page.tsx` (`?example=` is the default version with no
chooser; `?form=` latest version; `?formVersion=` that version; a named form that resolves to null falls
through to the chooser with "That form was not found."; the chooser gets `chooserOptions()` mapped to its
props, `preselect(...)` and `previous`). "Form: <name> v<N>" shown above the form.

Command: `npx vitest run test/unit/FormChooser.test.tsx test/unit/formChooser.test.ts test/unit/prefillOnEditPage.test.ts`: 3 files, 23 passed.

## Task 18: the builder (done)

File: new `src/app/p/[project]/forms/FormBuilder.tsx`. All state through `builderReducer`; local state only
for search, "Start from" selection, the open editor, focus after a move, the save's error and pending flag.
Overlap hints use the row's question id, or its `rowKey` for a new own row or a copy. Focus after a move goes
to the same button of the moved row (the other one when that is now disabled at an end). The server action
`useFormOnce` is imported as `saveFormForOnce` so React's hook lint rule does not mistake it for a hook.

Command: `npx vitest run test/unit/FormBuilder.test.tsx`: 21 passed.

## Task 19: import UI and the remaining pages (done)

Files (all new, under `src/app/p/[project]/forms/`): `import/FormImport.tsx`, `SetDefaultButton.tsx`,
`page.tsx`, `new/page.tsx`, `[formId]/edit/page.tsx` (`notFound()` before anything else), `import/page.tsx`.
Deviation: one small extra module `forms/libraryData.ts` (`builderData()`: `library()` rows, `libraryGroups()`
and each row's `resolve(versionId)`), shared by the three builder pages so they do not repeat it. It uses only
the methods the edit page test mocks, and sits under `forms/`, so R41's scan covers it. The library page hides
"Set as default" on the form that already is the default.

Command: `npx vitest run test/unit/FormImport.test.tsx test/unit/formActions.test.ts test/unit/formsNoModel.test.ts`: 3 files, 28 passed
(7 + 18 + 3; `formActions.test.ts` holds 18 tests, the plan said 17).

## Task 20: docs (done)

`README.md` (app): one sentence after the "14 questions" item: forms are data, the 14 are the seeded
"Annex IV default" form, other forms are built or imported under `/p/<project>/forms`.
`services/prefill/README.md` was done in task 8. No new markdown file.

## Final verification (plan section 6)

| Suite | Result | Plan expects |
|---|---|---|
| vitest | 67 files (63 passed, 4 skipped); 715 tests (681 passed, 34 skipped, 0 failed) | 63 + 4 skipped; about 681 passed, 34 skipped |
| `npx tsc --noEmit` | 0 errors (tests included) | 0 |
| `prisma validate` | valid (dummy `DATABASE_URL`, see task 1) | valid |
| `npx next build` | compiled, lint and types OK, 21 routes incl. the 4 `/forms` pages; no DB or network needed (one pre-existing font lint warning in `layout.tsx`) | (not in plan) |
| ontology | 224 passed, 3 failed (the three of 6.4) | same |
| prefill | 173 passed | 173 |
| renderer | 17 passed | 17 |
| agents | 150 passed | 150 |
| DB (`test/db/throwaway-db.sh`) | 3 files, 33 tests: 30 passed, 3 failed (the same three recorded above: S3.3 pre-existing, R4 and R7 tests believed wrong) | 34 passed |

`docker ps -a` after the DB run: no `aisc-t-qual-*` container left.
`git diff --stat -- test services/*/tests`: 11 files, 889 insertions, 0 deletions (unchanged).
`git status` lists only files named by the plan, plus `forms/libraryData.ts` (see task 19) and the untouched
test files. The build wrote only `.next/` (git-ignored; it held only a cache, no running server uses it).

Behaviour changes to mention to the user (plan risks 4.2 and 4.13): "Edit the AI system" now opens
"Which form?" first (`?example=mcas` still skips it); every card, legacy ones included, shows the coverage
line; the card page and the edit page show "Form: <name> v<N>". There is no link to `/p/<project>/forms`
from the existing navigation; it is reached through the chooser's "+ New form" / "Import form" or by URL.

No further test found wrong beyond the two DB tests already recorded.

---

# Fix round 1 (2026-09-25): verification findings F1, F2, F5, F6 and the three DB tests

Scope: category A of `05-verification.md`. F3, F4, F7, F8 not touched (product owner). Each fix test
first: the new test was run and seen failing for the stated reason before the code changed. Nothing
committed, staged, stashed or reset; HEAD still `c324885`.

## F1 PDF: escaping and a restricted url_fetcher (fixed)

- Test added: `services/system_card_renderer/tests/test_pdf_safety.py` (16 tests). Hostile citation
  (`<a rel="attachment" href="file:///etc/passwd">`), answer (`<img src="http://169.254.169.254/...">`),
  form name, question and description must come out escaped; the template's own markup (stylesheet link,
  `span.cite`, `h3`) and plain text render unchanged. `restricted_url_fetcher(templates)` must refuse
  `file:///etc/passwd`, `file://localhost/...`, a path escaping the folder (resolved and `..`), http(s) to
  any host incl. localhost and the metadata IP, ftp; it must serve `styles.css` byte for byte and a
  `data:` URI. End to end: a template asking for forbidden URLs still renders a PDF, and the only fetch
  that reaches the underlying fetcher is its own `styles.css`.
- Seen failing: against a no-op stub fetcher, 12 failed (raw markup in the HTML; "DID NOT RAISE").
- Fix: `template_engine.py` `autoescape=True` (`select_autoescape(["html","xml"])` did not match
  `*.html.j2`); `renderer.py` new `restricted_url_fetcher(allowed_dir)` (data: URIs, and file URLs whose
  resolved path is a file under the templates folder; everything else raises `ValueError`), passed as
  `url_fetcher` to `HTML(...)`. The template has no intentionally-HTML value (no `|safe`; `&mdash;` and
  the title's dash are template text), so nothing needed marking safe. A real PDF of the ONTOLOGY_ONLY card renders
  with no WeasyPrint warning (the stylesheet still loads).
- Result: renderer 33 passed (17 + 16).

## F2 CSV cell over 128 KB (fixed)

- Tests added: `tests/test_form_import.py::TestLimits` `test_r27_a_csv_cell_over_the_csv_module_limit_is_skipped_not_an_error`
  (200 000-char question: skipped with "Question on line 3 is longer than 2000 characters and was
  skipped.", the rows around it kept) and `test_r27_a_huge_quoted_citation_is_cut_not_an_error`;
  `tests/test_app.py::TestFormImportEndpoint::test_r27_a_csv_cell_over_128_kb_is_a_warning_not_a_500`.
- Seen failing: 3 failed with `_csv.Error: field larger than field limit (131072)`.
- Fix: `services/prefill/prefill/form_import.py` lifts `csv.field_size_limit` once at import
  (`2**31 - 1`); the file is already in memory and bounded by the upload cap, so the module's own limit
  protected nothing. No other csv user in the prefill service.
- Result: prefill 176 passed (173 + 3).

## F5 edit page branching, run not read (fixed: tests only)

- Test added: `test/unit/editSystemPage.test.tsx` (12 tests). Calls `EditSystemPage` with mocked
  `formService` / `qualificationService` and marker `QualifyForm` / `FormChooser`, and reads their props
  from the returned tree: no param gives the chooser with the default preselected and `error: null`,
  options mapped; `?form` fills the latest version; `?formVersion` that version; `?example=mcas` the
  default version with no chooser and no `startingPoint` call; precedence `example` > `form` >
  `formVersion`; an unknown `?example` is ignored; unknown `?form` / `?formVersion` give the chooser with
  "That form was not found." and the usual preselection; A14 previous listed form and previous use-once
  version; a failing `startingPoint` still shows the chooser.
- The page's behaviour was already correct, so the tests passed at once. To prove they catch
  regressions, three temporary mutations of the page were run and reverted (`cmp` identical afterwards):
  `formVersion` winning over `form` (1 failed), the error not passed to the chooser (2 failed),
  `?formVersion` ignored (1 failed). No production code changed; no extraction was needed.
- Note: the spec does not say which of `?form` and `?formVersion` wins when both are given; the test
  pins the implemented order (`form`).

## F6 concurrent set-default (fixed)

- Tests added: `test/unit/FormService.test.ts` "R4 F6 another administrator moving the default at the
  same time is a message, not an error" (repository throws P2002) and "R4 F6 any other failure of the move
  is not hidden" (P1001 still throws); `test/db/forms.db.test.ts` "R4 F6 two administrators moving the
  default at once": a real race on the throwaway DB (first transaction held open after both writes, second
  `FormService(new FormRepository(other client)).setDefault` waits on its row lock, then the first
  commits); asserts the message and that exactly the first form is the default; restores
  `annex-iv-default` as default afterwards.
- Seen failing: unit, the raw error propagated; DB, `PrismaClientKnownRequestError ... Unique constraint
  failed on the fields: (`(true)`)` from `FormRepository.setDefault` (P2002, the 500 of the finding).
- Fix: `src/server/services/FormService.ts` `setDefault` catches P2002 from the repository and returns
  `{ ok: false, error: "Another administrator changed the default form meanwhile. Reload the page and try
  again." }` (same pattern as the raced save in `saveDraft`); `setDefaultForm` already turns it into
  `{ error }` and `SetDefaultButton` shows it. DB invariant unchanged (`form_one_default` still refuses).

## DB tests judged wrong (fixed, intent kept)

- `forms.db.test.ts` R4 "a second is_default row fails on form_one_default": now asserts the Prisma
  rejection carries ``Code: `23505` `` and runs the same UPDATE through `QUALIFICATION_TEST_PSQL`
  (`BEGIN; ...; ROLLBACK;`), expecting `duplicate key value violates unique constraint
  "form_one_default"`; also checks the row is still not the default. Stricter than before, not looser.
- `forms.db.test.ts` R7: inside its rolled-back transaction, after dropping the new answer key and before
  recreating the old `(qualificationId, questionId)` index, it deletes answer rows only the new key allows
  (same questionId under two scopes, as R5 commits). Verified order independent: passes on a DB where R5
  had already committed its rows in two earlier runs.
- `cardVersions.db.test.ts` S3.3 (pre-existing): inserts a real `core.project` row for the card and also
  drops `qualification_system_id_project_id_fkey` (added later, by `20260924120000`, which would refuse
  the dangling card first), like the test already drops `qualification_system_id_fkey`. Still asserts the
  migration's own message and the dangling id.
- Iterated on one `KEEP=1` throwaway container (`aisc-t-qual-7f4d91cf`, mine), removed with
  `docker rm -f`; the final run used the script normally. Other sessions' `aisc-t-verify-*` containers
  were not touched. No connection to 5432/5433.

## Final counts (fix round 1)

| Suite | Result |
|---|---|
| vitest | 68 files (64 passed, 4 skipped); 730 tests: 695 passed, 35 skipped, 0 failed (+12 page, +2 FormService; +1 skipped is the F6 DB test) |
| `npx tsc --noEmit` | exit 0 |
| `npm run build` | exit 0, 21 routes; only the pre-existing font lint warning |
| ontology | 224 passed, 3 failed (the three pre-existing ones of plan 6.4) |
| prefill | 176 passed |
| renderer | 33 passed |
| agents | 150 passed |
| DB (`test/db/throwaway-db.sh`) | 3 files, 34 tests, 34 passed |

`docker ps -a` afterwards: no `aisc-t-qual-*` container left.

---

# Round 2, implementer 1: tasks 0 to 8 of `08-plan-round2.md` (2026-09-25)

Same environment as above (`A`, `P`, `$PREF`, `$ONTO`, `$REND`, `$AGENTS`, `$VT` exactly as defined at the top of
`08-plan-round2.md`). Nothing committed, staged, stashed, reset or checked out. No test, fixture or test-support
file touched (the `formLibrary.test.ts:137` cast is left for implementer 2). No docker, no DB used in these tasks.

## Task 0: baseline (done)

- Branch `feat/unified-modules`, HEAD `e9d0693` (unchanged, so no new commit to check against section 5).
- Test fingerprint: `$P/r2-impl-tests.sha` (127 files). `git status --short` saved to `$P/r2-impl-status-before.txt`.
- `bash $P/r2-run-all.sh r2impl-before`: exactly the plan's table (vitest 22 failed / 52 passed / 4 skipped files,
  164 failed / 712 passed / 38 skipped tests; ontology 24 failed, 219 passed; prefill 99 failed, 184 passed;
  renderer 2 failed, 33 passed; agents 152 passed). `npx tsc --noEmit`: 44 errors.
- e9d0693 check: nothing to do (no round 2 file of tasks 0 to 8 is in that commit).

## Task 1: point ids and the .docx expansion cap (done)

Files: `services/prefill/prefill/fields.py` (`ANNEX_POINT_IDS`, right after `_point_of`);
`services/prefill/prefill/documents.py` (`DEFAULT_MAX_UNZIPPED_BYTES`, `_max_unzipped_bytes()`,
`check_docx_expansion(raw)`, called first in `_from_docx`); `services/prefill/prefill/form_import.py`
(`check_docx_expansion(raw)` first in `_from_docx`, `docx.Document` still through the module attribute).
Choice the tests leave open (in the docstring): a missing, non-integer or non-positive env value means the default.
The zip is opened in a `with` block; any exception opening or listing it is the "could not be read" message.

Commands: `$PREF tests/test_fields.py tests/test_documents.py` 33 passed; `$PREF tests/test_form_import.py -k TestDocxExpansion` 4 passed.

## Task 2: the importer reads what the exporter writes (done)

Files: `services/prefill/prefill/form_import.py` (`ImportedQuestion.annex_point`, 5-tuple `Candidate`,
`_ANNEX_HEADERS`, `_unguarded` + `_table_rows(..., unguard=)` used only by `_from_csv`, `_md_cells` tokenizer,
the Annex check in `_limited` after the citation cut, module docstring lines); `services/prefill/app.py`
(`/forms/import` returns `annexPoint`).
Deviation (cosmetic): the module docstring and `_md_cells`'s docstring are raw strings (`r"""`) because they
contain `\|` and `\\`; otherwise Python emits a SyntaxWarning.

Commands: `$PREF tests/test_form_import.py` 89 passed; `$PREF tests/test_app.py -k "TestFormImportEndpoint or TestFormImportAnnexPoint or test_r27"` 11 passed, 0 failed.

## Task 3: the exporter (done)

File created: `services/prefill/prefill/form_export.py` (standard library only: `csv`, `io`, `re`, `unicodedata`,
`dataclasses`). Exports `ExportedFile`, `collapse`, `slug`, `export_form`, plus the constants `FORMATS` and
`MD_COMMENT`. Written from the plan, the scratch reference in `$P/r2ref/` was not copied.

Command: `$PREF tests/test_form_export.py` 45 passed (10 round trips included).

## Task 4: POST /forms/export (done)

File: `services/prefill/app.py` (pydantic `ExportQuestion`, `ExportForm`, `ExportRequest`; `format: str`;
the three 422 checks in the plan's order; the 200 limit is `form_import.MAX_QUESTIONS`, which is 200).

Commands: `$PREF tests/test_app.py` 56 passed; `$PREF` 283 passed, 0 failed (the 1 warning is pre-existing).

## Task 5: MCAS answers 1(f) (done)

Files: `services/ontology/examples/mcas.qualification.json` (the 1f object inserted after 1de, text read from
line 41 of `src/data/examples/mcas.ts` by a script, 299 characters; re-serialised with
`json.dumps(indent=2, ensure_ascii=False) + "\n"` after checking that reproduces the old file byte for byte;
`git diff --stat`: 5 insertions); `mcas.ttl` and `mcas.jsonld` regenerated with the plan's two commands (each
printed `413 triples -> ...`); `services/ontology/README.md` (13 -> 14 Annex IV answers, 295 -> 413 triples).

Commands: `$ONTO tests/test_example_mcas.py tests/test_roundtrip.py` 19 passed, 2 failed (the pre-existing
`test_it_exercises_all_nineteen_properties` and `test_the_rebuilt_graph_keeps_every_airo_relation`);
`$VT test/unit/mcasExampleAgrees.test.ts` 5 passed.

## Task 6: coverage names optional points left blank, groups by owner id (done)

Files: `services/ontology/airo_min/coverage.py` (`_owner_key`, `_owners_in_order` now returns `(key, name)`
pairs, `optional_blank`, `annex.optionalBlank`, the summary note, docstring gains `ownerFormId`);
`services/system_card_renderer/models.py` (`CoverageAnnex.optionalBlank: int = 0`).

Commands: `$ONTO tests/test_coverage.py` 27 passed; `$ONTO` 240 passed, 3 failed (the three of 03-plan 6.4);
`$REND` 35 passed.

## Task 7: forward migration and Prisma schema (done)

Files: new `prisma/migrations/20260925120000_the_default_form_is_fixed/migration.sql` (section 3.1 verbatim);
`prisma/schema.prisma` (the `isDefault` line and its comment deleted, the R44 `///` line added directly above
`model Form {`, below the existing doc line). `npx prisma generate` run (writes only `node_modules/.prisma`).
090000 untouched (sha256 still `cbea212d...147557`).

Commands: `$VT test/unit/annexDefaultForm.test.ts` 21 passed; `prisma validate` (dummy URL) valid;
`$VT test/unit/formsDefaultIsFixed.test.ts -t 'R47 model|R47 neither migration|schema.prisma has no isDefault'`
6 passed, 11 skipped.

## Task 8: pure domain modules (done)

Files: new `src/domain/forms/useOnceName.ts` (`useOnceFormName` only; no `USE_ONCE_PREFIX` export, nothing uses
it); `chooser.ts` (`preselect` without `defaultFormId`, fallback `DEFAULT_FORM_ID`; `FormLookup`,
`pickFormParams`; header comment updated); `formDraft.ts` (pick `fromVersionId: z.string().min(1)`,
`PinnedSnapshot`, `sameContent(draft, version, snapshots)` comparing all five fields); `library.ts`
(`LibraryGroup.versionId`, generic `filterLibrary`, `sourceUpdates`); `builderState.ts` (pick rows carry
`fromVersionId`; `tick` takes `versionId`; `startFrom` and `edit` pin to the form's `versionId`; `takeLatest`;
`toDraft` emits `fromVersionId`).

Command: `$VT test/unit/useOnceName.test.ts test/unit/formChooser.test.ts test/unit/formDraft.test.ts test/unit/formLibrary.test.ts test/unit/builderState.test.ts`:
6 files, 138 passed (9 + 28 + 11 FormChooser.test.tsx + 44 + 22 + 24).

## State after task 8 (handover to implementer 2, task 9 on)

| Suite | Result |
|---|---|
| vitest | Test Files 15 failed, 59 passed, 4 skipped (78); Tests 89 failed, 787 passed, 38 skipped (914) |
| ontology | 240 passed, 3 failed (final: the three pre-existing) |
| prefill | 283 passed (final) |
| renderer | 35 passed (final) |
| agents | 152 passed (final) |
| `npx tsc --noEmit` | 25 errors: 17 in tests (FormService.test.ts 15, formLibrary.test.ts 1 = the known conflict 3, QualificationExporter.test.ts 1), 8 in `src/` |

Logs: `$P/r2-logs/r2impl-after8-*.log`; tsc list: `$P/r2impl-tsc-after8.txt`.

The 89 failing vitest tests, all in files of tasks 9 to 13: FormService (18), formExportRoute (18),
FormExportClient (9), formsDefaultIsFixed (7), editSystemPage (6), formActions (6), FormBuilder (6), FormLine (6),
FormsPage (4), FormImport (3), QualificationExporter (2), FormImportClient (1), formsNoModel (1), SiteHeader (1),
VerticalCard (1).

The 8 `src/` tsc errors are exactly what tasks 9, 12 and 13 remove, caused by the task 7 and 8 changes:
- `FormRepository.ts` lines 105-106: `isDefault` in `setDefault` (task 9 deletes `setDefault`).
- `FormService.ts:78` `libraryGroups()` lacks `versionId`; `:142` `sameContent` now needs the snapshots map;
  `:264` reads `isDefault` from the row (task 9).
- `system/edit/page.tsx:48` passes `defaultFormId` to `preselect` (task 12b).
- `forms/FormBuilder.tsx:181` dispatches `tick` without `versionId` (task 13).

Integrity at the end of task 8: `sha256sum -c --quiet $P/r2-impl-tests.sha` prints nothing (no test changed);
`git status --short` compared with task 0 adds only `services/ontology/README.md`,
`services/ontology/examples/{mcas.jsonld,mcas.qualification.json,mcas.ttl}`, `services/prefill/prefill/documents.py`,
`prisma/migrations/20260925120000_the_default_form_is_fixed/`, `services/prefill/prefill/form_export.py` (the other
edited files were already modified or inside untracked folders). HEAD still `e9d0693`.
`services/prefill/README.md` (task 15) is not yet edited. No test found wrong.

# Round 2, implementer 2: tasks 9 to 16 of `08-plan-round2.md` (2026-09-25)

Same environment (`A`, `P`, `$VT`, `$PREF`, `$ONTO`, `$REND`, `$AGENTS` as in `08-plan-round2.md`). Nothing
committed, staged, stashed, reset or checked out. No server or container started or restarted; the only docker
use was `test/db/throwaway-db.sh`. The Dockerfile was not touched. One test file was edited, the authorised cast
(task 16 below).

## Task 9: FormRepository and FormService (done, 1 test believed wrong)

Files: `src/server/repositories/FormRepository.ts` (`setDefault` and its comment deleted; the header comment
no longer mentions moving the default); `src/server/services/FormService.ts` (constructor
`{ newId, now }`; `setDefault` and `latestSnapshot` deleted; `listed()` computes
`isDefault: form.id === DEFAULT_FORM_ID`, and the sort is the default first, then by name; `libraryGroups()`
adds `versionId`; new `exportable(formId, versionNumber?)`; `saveDraft(..., { systemName? })`: a use-once form
is named by `useOnceFormName` against every form's name; a private `pinnedSnapshots(value)` loads each pick's
`findVersion(fromVersionId)` once per id, refuses a missing version or row with "Question <n> no longer
exists." before any planning, and feeds both `sameContent` and the planner, which copies the pinned five
fields verbatim).

Commands: `$VT test/unit/FormService.test.ts` 47 passed, 1 failed (below); the `setDefault method|R47 src`
scans 5 passed; `formActions -t 'R47 a form saved while in project a'` 1 passed.

**Test believed wrong:** `FormService.test.ts` "R61 R64 F with its pick switched to G's newer version makes
the next version, with the new wording". It saves G's v2 through the service (`reworded("B")`), whose version
id comes from `newId` (`idCounter("n")`, so `n1`), then picks from `fromVersionId: "gg-v2"`. That id exists only
for versions the fake store seeds (`<formId>-v<n>`), so the pick is correctly refused with "Question 1 no
longer exists.". The sibling R62 test reads the id from `store.inserted.at(-1)!.version.id`, which is the right
way. Fix in the test: use `store.inserted.at(-1)!.version.id` in place of `"gg-v2"`. Not changed. (Minting
version ids as `<formId>-v<n>` would also make it pass, but that changes the id scheme the header describes
and the plan keeps, so I did not do it.)

## Task 10: export shape and view type (done)

Files: `src/server/services/QualificationExporter.ts` (`ownerFormId` in the type and in each
`form.questions[]` entry, after `ownerForm`); `src/domain/OntologyView.ts` (`optionalBlank?: number`).
Command: `$VT test/unit/QualificationExporter.test.ts test/unit/VerticalCard.test.tsx test/unit/fillerReadsItsProject.test.ts` 23 passed (12 + 7 + 4).

## Task 11: FormExportClient and the export route (done)

Files created: `src/server/services/FormExportClient.ts`, `src/app/p/[project]/forms/[formId]/export/route.ts`
(GET only; every error body is `text/plain; charset=utf-8`; the 200 body is `TextEncoder` bytes).
Command: `$VT test/unit/FormExportClient.test.ts test/unit/formExportRoute.test.ts` 27 passed (9 + 18).

## Task 12: actions, library page, FormLine, card and edit pages, header (done)

Files: `forms/actions.ts` (`setDefaultForm`, `callerAccess` and `revalidatePath` imports gone; `useFormOnce`
validates with the placeholder name, then `platformClient.latestVersion(project).catch(() => null)`,
`systemName = latest?.name ?? project`); `forms/SetDefaultButton.tsx` deleted; `forms/page.tsx` (no access
call; the two R48 sentences; "Export CSV" and "Export Markdown" as `<a download>` with `NEXT_BASE_PATH`);
new `src/app/p/[project]/FormLine.tsx` (`basePath` prop, reads no env); `qualify/[id]/page.tsx` and
`system/edit/page.tsx` render `<FormLine ... basePath={basePath} />`; the edit page uses `pickFormParams` and
`preselect` without `defaultFormId`; `src/components/SiteHeader.tsx` gains "Forms" after "Versions".
Command: the plan's seven files, 83 passed (23 + 5 + 6 + 24 + 2 + 17 + 6).

## Task 13: builder and import UI (done)

Files: `forms/FormBuilder.tsx` (tick carries `group.versionId`; `sourceUpdates` memoised; "Source updated"
chip, "New wording: ..." paragraph and the "Use new wording" button dispatching `takeLatest`);
`FormImportClient.ts` (`annexPoint: AnnexPointId | null`, mapped through `isAnnexPoint`);
`forms/import/FormImport.tsx` (per-row `<label htmlFor>` "Answers Annex IV point" + `<select>`, None then the
14 `ANNEX_POINTS`; Continue passes the row's `annexPoint`). The preview normalises a missing `annexPoint` to
`null` because the round 1 R28 fixture has no such key.
Command: `$VT test/unit/FormBuilder.test.tsx test/unit/FormImport.test.tsx test/unit/FormImportClient.test.ts` 43 passed (26 + 10 + 7).

## Task 14: DB on a throwaway Postgres (done)

`npx prisma generate`, then `test/db/throwaway-db.sh`: 3 files, 37 passed. Afterwards `docker ps -a | grep
aisc-t-qual-` shows nothing. Log: `$P/r2-logs/r2impl2-db.log`.

## Task 15: docs (done)

`services/prefill/README.md`: `annexPoint` in the `/forms/import` response and the rules that give it (Annex
column, CSV unguard, Markdown escapes); `POST /forms/export` (request, 200 response, the three 422 messages,
file shapes, filename); the .docx expansion cap `PREFILL_MAX_UNZIPPED_BYTES` (default 52428800). No em dashes.

## Task 16: full verification

A concurrent session committed `8f0ab50` ("API auth: ... every sidecar takes a token per caller") at 10:19,
during this run. It staged only its own hunks: the round 1 and round 2 work is still uncommitted. It adds tests,
so the counts are above the plan's.

| Check | Plan expected | Result |
|---|---|---|
| vitest | 74 passed, 4 skipped files; 876 passed, 38 skipped, 0 failed (914) | Files 2 failed, 75 passed, 4 skipped (81); Tests 2 failed, 908 passed, 38 skipped (948) |
| tsc | exactly 1 error (formLibrary:137) before the cast | 0 errors after the cast |
| prisma validate (dummy URL) | valid | valid |
| next build | exit 0, routes + `/p/[project]/forms/[formId]/export` | exit 0, the export route listed, only the font lint warning |
| ontology | 240 passed, 3 failed | 261 passed, 3 failed (the three pre-existing ones; +21 are 8f0ab50's) |
| prefill | 283 passed | 298 passed |
| renderer | 35 passed | 50 passed |
| agents | 152 passed | 168 passed |
| DB | 37 passed, no container left | 37 passed, none left |

The two vitest failures:
1. `FormService.test.ts` R61 R64 (the test believed wrong, task 9).
2. `serviceTokens.test.ts` "holds for every source file that reads a sidecar's URL" (8f0ab50's test) flags
   `FormExportClient.ts` and `FormImportClient.ts` for reading `PREFILL_URL` without sending
   `QUALIFICATION_WEB_TO_PREFILL_TOKEN` through `serviceTokenHeaders`. That is also a real runtime gap: prefill
   now refuses every path but /health without the token, so import and export will be 401 in the stack. For
   `FormExportClient.ts` it **conflicts with R73** (`formsNoModel.test.ts`: the new parts read no env other than
   `PREFILL_URL` and `PLATFORM_URL`). Needs a decision: amend R73 to allow the prefill token, or read the token
   in a shared helper. Not changed here: it is the other session's feature, in flight, and one of the two tests
   has to give.

Deviation: the build's lint (`react-hooks/rules-of-hooks`) refused `useOnceFormName(...)` inside the
`FormService` class because of its `use` prefix. `FormService.ts` now imports it as
`useOnceFormName as oneUseFormName`, the same trick `FormBuilder.tsx` uses for `useFormOnce`. The exported name
is unchanged, since the tests import it.

The authorised cast: `test/unit/formLibrary.test.ts:137` `acmeGroup([newer])` became
`acmeGroup([newer as never])` (type only, same assertion). `$P/r2-impl-tests.sha` has that one line updated;
the pre-cast baseline is kept as `$P/r2-impl-tests.before-cast.sha`.

By reading:
- `sha256sum -c --quiet $P/r2-impl-tests.sha` shows 3 mismatches: `services/agents/tests/test_clients.py`,
  `services/ontology/tests/conftest.py`, `test/unit/onlyLatestCardChanges.test.ts`. `git log -1` shows all three
  changed in 8f0ab50 (the other session), and none of them is dirty. No test changed by this implementer except
  the cast.
- The risk 3 grep (`setDefault|is_default|Set as default|Only an administrator|defaultFormId|latestSnapshot|org default`
  over `src` and `schema.prisma`) prints nothing.
- `git diff --stat -- prisma/migrations/20260925090000_forms_are_data` is empty; its sha256 is still `cbea212d...147557`.
- Files touched in tasks 9 to 15 are all in section 5 of the plan (plus the authorised test cast). Status
  snapshot: `$P/r2impl2-status-final.txt`.
- R-id closure: every id from R43 to R73 has green tests. R61 and R64 are covered by their other tests
  (formDraft, builderState, FormBuilder, the R61 "no change" FormService test); only the one wrong test is red.

Intended visible change (risk 9): every legacy card now shows the coverage note for optional points left blank,
and the line "Form: Annex IV default v1 · CSV · Markdown".
Still for the product owner (conflict 9): the image's `CMD` runs `prisma db push`, not the migrations.

Logs: `$P/r2-logs/r2impl2-after-*.log`, `$P/r2-logs/r2impl2-final-vitest.log`, `$P/r2-logs/r2impl2-build.log`.

# Round 2 fix (2026-09-25)

Nothing committed, staged, stashed, reset or checked out. No server, migration or docker change; the only
docker use was `test/db/throwaway-db.sh`.

## Fix 1: the R61 R64 test's id lookup

`test/unit/FormService.test.ts`, "R61 R64 F with its pick switched to G's newer version...": the pick now reads
G's v2 id from `store.inserted.at(-1)!.version.id` (as the R62 test does) in place of `"gg-v2"`. The assertions
are unchanged and `FormService.ts` is untouched. `$VT test/unit/FormService.test.ts`: 48 passed.

## Fix 2: the form clients send the prefill token

Red first: `serviceTokens.test.ts` "holds for every source file that reads a sidecar's URL" flagged
`FormExportClient.ts` and `FormImportClient.ts`. Tests added in `serviceTokens.test.ts` (qualification-prefill):
POST /forms/import and POST /forms/export each carry `X-AISC-Service-Token` when
`QUALIFICATION_WEB_TO_PREFILL_TOKEN` is set (export also keeps `Content-Type: application/json`); the two
form clients join `PrefillClient.ts` as owners of that env name in "each env name is read by its own client
only". 4 red before the change.

Change: both clients follow `PrefillClient` exactly: a third constructor argument
`serviceToken = process.env.QUALIFICATION_WEB_TO_PREFILL_TOKEN ?? ""` and `serviceTokenHeaders(this.serviceToken)`
from `http.ts` in the request headers (export spreads it beside its content type).

R73: `formsNoModel.test.ts` then flagged `FormExportClient.ts: QUALIFICATION_WEB_TO_PREFILL_TOKEN`. Per the
product owner, its allowlist now also holds `QUALIFICATION_WEB_TO_PREFILL_TOKEN` (a service-to-service token,
not a model credential); the amendment is one line under R73 in `06-spec-addendum.md`. After: the four files
(serviceTokens, formsNoModel, FormExportClient, FormImportClient) 32 passed.

Prefill side (checked, no change): `/prefill`, `/forms/import` and `/forms/export` are all routes of the one
`app`, behind the single `ServiceTokens` middleware, with no route-level token check. An ad-hoc probe (no test
edited): /forms/export 401 without and with a wrong token, 200 with the right one; /forms/import 401, 401, and
past the door (422 on a JSON body) with the right one.

## Verification

| Check | Result |
|---|---|
| vitest | Files 77 passed, 4 skipped (81); Tests 912 passed, 38 skipped, 0 failed (950) |
| tsc | 0 errors |
| next build | exit 0, `/p/[project]/forms/[formId]/export` listed, only the font lint warning |
| ontology | 261 passed, 3 failed (the same three pre-existing ones) |
| prefill | 298 passed |
| renderer | 50 passed |
| agents | 168 passed |
| DB (throwaway) | 3 files, 37 passed, no `aisc-t-qual-` container left |

Logs: `$P/r2-logs/r2fix-*.log`.

## G1 fix (2026-09-25)

Finding G1 (09-verification-round2.md): the CSV formula guard was not injective, so `''=x` exported unguarded and re-imported as `'=x`. Product owner: the round trip must be exact.

- `prefill/form_export.py` `_guard`: one extra `'` before any cell matching `^'*[=+\-@]`.
- `prefill/form_import.py` `_unguarded`: strips exactly one `'` from a cell matching `^'+[=+\-@]`.
- Every R50 example output unchanged; no existing test edited.
- Tests first (`tests/test_form_export.py`, class `TestG1ExactCsvGuard`, 13 tests): export of `''=x`, `'''+y`, `'-z`, `@w`, `=a`; exact CSV round trip of each; import strips exactly one `'`; a seeded property test (exhaustive 0 to 5 quotes times each formula character, plus 400 random quote/formula/text heads) proving export then import is identity and no exported cell starts with `= + - @`. 6 failed before the fix, 13 pass after.
- R50 and R53 in 06-spec-addendum.md each gain one "Amended 2026-09-25 (G1 ...)" line.

| Check | Result |
|---|---|
| prefill | 311 passed (298 + 13 new) |
| vitest | Files 77 passed, 4 skipped (81); Tests 912 passed, 38 skipped, 0 failed (950) |

## Design pass (2026-09-25)

Implements 10-ui-plan.md, tasks 1 to 11 and the checks of 12. Markup and CSS only: no behaviour, props, server action, data, route or Python change. No existing test edited. Task 0 (header check in the running app) and the visual screenshot pass of task 12 were not done here: they need the running stack, which this pass did not rebuild, restart or deploy.

Tests first: `test/unit/formsLayout.test.tsx`, 18 tests (L1-L5, B1-B8, I1, C1, F1, P1, P2). All 18 were run and seen failing before any markup changed. B3 as first written passed on the old markup, so it was tightened (label has exactly the checkbox and a `.qf-builder-pick-body`, citation inside `.qf-builder-chips`) and seen failing before task 5.

| # | Task | Files | Tests | Result |
|---|---|---|---|---|
| 1 | Test file, shared mocks, CSS `rule()` helper | `test/unit/formsLayout.test.tsx` (new) | none | runs |
| 2 | Page shells: `qualify-page--form qf-forms-page`, "← Forms" crumb | `forms/page.tsx`, `forms/new/page.tsx`, `forms/[formId]/edit/page.tsx`, `forms/import/page.tsx` | P1, P2 | red then green; widePage, formActions green |
| 3 | Library: header buttons, `qf-forms-table`, default tag, description, Made by map, actions wrapper, section 3.3 CSS, `.qf-forms-page` added to the `.qf-tag` and `.qf-citation` selector lists | `forms/page.tsx`, `globals.css` | L1-L5 | red then green; FormsPage 5/5 |
| 4 | Builder frame: `qualify-form` root, grid, sticky right column, 960px breakpoint, `qf-select`, Start from toolbar | `forms/FormBuilder.tsx`, `globals.css` | B1, B2, B4 | red then green; FormBuilder 26/26 |
| 5 | Library rows: pick grid, body span, chip line, clamp, overlap chip | same | B3 | red then green |
| 6 | Identity chips (visually hidden commas), block chips, "Blocks" / "Questions (N)" heads, empty hint | same | B5 | red then green; R21 green |
| 7 | Picked rows: position square, body, chips, text tools, "Source updated" box | same | B7, B8 | red then green; R18, R64 green |
| 8 | Editor inset panel with heading, citation/point pair, small buttons (Cancel, Save question); footer (Use once, Save form) | same | B6 | red then green; FormImport 10/10 |
| 9 | Import: drop box, `h2` found line, warnings box, `ol.qf-import-rows` rows, section 5.3 CSS | `forms/import/FormImport.tsx`, `globals.css` | I1 | red then green; FormImport 10/10 |
| 10 | Chooser: `.qf-chooser-tags` wrapper, `qf-tag--default`, section 6.3 CSS | `system/edit/FormChooser.tsx`, `globals.css` | C1 | red then green; FormChooser + formChooser 39/39 |
| 11 | FormLine: `qf-row-form-name`, `qf-row-form-sep` spans, section 7.3 CSS | `FormLine.tsx`, `globals.css` | F1 | red then green; FormLine, VerticalCard green |

Small departures from the plan's CSS text, all needed for the plan's intent to take effect:
- `.qualify-header .qf-crumb { margin: 0 0 8px }` added: `.qualify-header p` (more specific than `.qf-crumb`) would otherwise give the crumb the intro's 32px gap.
- Specificity: `.qf-tag--default` is written `.qualify-form .qf-tag--default, .qf-forms-page .qf-tag--default`, `.qf-tag--notice` as `.qualify-form .qf-tag--notice`, and the editor head as `.qualify-form .qf-builder-editor .qf-group`, `.qf-import-found` as `.qualify-form .qf-import-found`, `.qf-builder > .qf-section` as `.qualify-form.qf-builder > .qf-section`, plus `.qualify-form .qf-builder-form { padding-bottom: 0 }`. Written as in the plan, each loses to an existing `.qualify-form .qf-*` rule.
- "Use new wording" carries `btn ghost qf-builder-small` (the plan's "small modifier"), not `qf-builder-tool`, so it stays a ghost button. `qf-builder-small` has no rule of its own; `.qf-builder-update .btn` and `.qf-builder-editor-actions .btn` size it.
- `.qf-import-point` is a flex column with a 4px gap (the plan put `margin-bottom: 4px` on the label); `.qf-import-row .qf-builder-check` gets a 10px bottom margin so it lines up with the inputs.

All new CSS sits in one block at the end of `globals.css` headed `/* ── Form assembly: library, builder, import, chooser, form line ───────── */`. The three width rules widePage pins are untouched.

| Check | Result |
|---|---|
| vitest | Files 78 passed, 4 skipped (82); Tests 930 passed, 38 skipped, 0 failed (968) = 912 + 18 new |
| tsc | 0 errors |
| next lint | exit 0, only the existing custom-font warning |
| next build | exit 0 (writes only the git-ignored `.next`) |

Still open: task 0 and the visual pass (1440px and 800px) on the running app after a redeploy, which needs the owner's yes.

## Multi-form select (2026-09-25)

Implements addendum 06 section 8 (R74 to R80, assumptions C1 to C8): the builder pages are wide, and
"Start from" (one dropdown and Apply) is a multi-select of forms. No DB, API, server action, save payload or
Python change; no git write.

Spec first (06 section 8), then tests, seen failing, then code.

| Area | Files | Change |
|---|---|---|
| Pure state | `src/domain/forms/builderState.ts` | `BuilderState.selected: string[]`; a pick row may carry `viaFormId`. New actions `selectForm {form}` (ticks every not-yet-ticked question, in the form's order, appended, pinned to its version) and `deselectForm {formId}` (removes that form's untouched picks). `tick` takes an optional `form`: the question goes back at its place among that form's rows, else at the end. `startFrom` action removed; `initialBuilderState({startFrom})` preselects S and takes its blocks; `{edit}` selects the owners of F's picks. `toDraft` unchanged. |
| Builder | `src/app/p/[project]/forms/FormBuilder.tsx` | `fieldset.qf-builder-forms` "Select forms", one `label.qf-builder-formchip` per form (name, `vN · K questions`); groups only for the selected forms, in selection order, from `forms` (all their questions); `p.qf-builder-prompt` when none; empty-form hint reworded. The Start from select, Apply and `window.confirm` are gone. |
| Page shells | `forms/new/page.tsx`, `forms/[formId]/edit/page.tsx` | `qualify-page qualify-page--wide qf-forms-page` |
| Import | `forms/import/page.tsx`, `forms/import/FormImport.tsx` | FormImport renders the `main` (the page passes its header): `--form` for upload and preview, `--wide` once the builder mounts. Prettier reformatted FormImport.tsx as a whole (layout only). |
| CSS | `src/app/globals.css` | Removed the dead `.qf-builder-startfrom` / `.qf-builder-apply` rules; appended to the design-pass block: form chips (the `.qf-builder-block` look, tokens only), prompt, group spacing, and `@media (min-width: 961px) { .qualify-page--wide .qf-builder { grid-template-columns: minmax(0, 1fr) minmax(380px, 560px) } }`. The three widePage width rules are untouched. |

Existing tests changed deliberately (each for the old Start-from or width rule only):

| Test | Before | After | Why |
|---|---|---|---|
| builderState "R17 replaces the right column ..." | `startFrom` replaced the rows and set S's blocks | renamed "R76 selecting a form appends ..."; `selectForm` keeps the existing row, appends S's picks, blocks unchanged | R17 superseded by R76 |
| builderState "R62 Start from S pins ..." | action `startFrom` | action `selectForm`, renamed "R62 R76 selecting S pins ..." | same pin rule, new action |
| builderState header comment | listed `startFrom` | notes section 8 interface | doc only |
| FormBuilder "R16 one group per listed form ..." | groups on open; counted every checkbox in the column | `browse()` (select both forms, untick all) first; counts only question checkboxes (`.qf-builder-groups`) | groups show only for selected forms (R75); the form chips are checkboxes too |
| FormBuilder R29, R16 search, R16 ticking, `three()` (R18, R19), R20, R23, R22 Save form, R22 Use once | `mount()` then tick | `browse()` then tick; search counts use `questionBoxes()` | same reason; assertions unchanged |
| FormBuilder `three()` | ticks q1, q3, q2 gave that order | same ticks plus one "Move How are incidents reported? down" | a tick inside Acme's group lands in Acme's order (R78); the move restores the order the R18 expectations were written for, and they are unchanged |
| FormBuilder describe "Start from (R17)" (2 tests: Apply fills; confirm before replacing) | dropdown, Apply, "Replace the 2 questions ..." | removed, replaced by the 9 "selecting forms (R75 to R80)" tests | R17 superseded; selecting never replaces or asks |
| formsLayout B3 | every checkbox in the library column | selects both forms, then every checkbox in `.qf-builder-groups` (asserts 5) | form chips are not question rows |
| formsLayout B4 | Start from select and Apply in `.qf-builder-startfrom` | `fieldset.qf-builder-forms` in the toolbar, chip labels with name and meta spans, prompt, chip CSS guard | R75 |
| formsLayout B7 | ticked one question, `getByRole` Edit/Remove | selects Acme (3 rows), `getAllByRole` | selecting ticks all of a form's questions |
| formsLayout P1 | every forms page `--form`, never `--wide` | library `--form`, never `--wide`; new and edit `--wide`, never `--form` | R74 |

New tests: builderState 19 (R76 x7, R77 x4, R78 x5, R79 x3), FormBuilder 9 (R75 x3, R76, R77, R78, R79 x2,
R80), formsLayout 2 (P3 import step width, P4 wide-grid CSS guard), widePage 1 (builder pages take
`qualify-page--wide`, library stays 1080px). Every new test was run and seen failing before the code, for the
expected reason ("Select forms" group missing, `selected` undefined, old hint text, pages still `--form`, CSS
rule absent). Three of the new builderState guards ("selecting a form already selected", "unselecting a form
not selected", "never mutate") passed vacuously before the code (the unknown action returned `undefined`);
they bite now.

| Check | Result |
|---|---|
| vitest | Files 78 passed, 4 skipped (82); Tests 959 passed, 38 skipped, 0 failed (997) = 930 + 29 net |
| tsc | 0 errors |
| next lint | exit 0, only the existing custom-font warning |
| next build | exit 0 |

Not done: a visual pass on the running app (needs a redeploy, which needs the owner's yes).
