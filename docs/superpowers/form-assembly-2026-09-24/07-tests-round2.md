# Form assembly: tests, round 2 (stage 7)

Date: 2026-09-25. App: `apps/qualification`, branch `feat/unified-modules` (not switched, nothing committed,
staged or stashed). Input: `06-spec-addendum.md` (R43 to R73, section 5, B1 to B10). Output: the executable
contract below. The tests are the only change: no implementation code and no migration were written, and no
file under `src/`, `prisma/`, `scripts/` or any service's code changed. The one committed fixture is
`services/prefill/tests/fixtures/annex_iv_default_form.json`.

Paths are relative to `apps/qualification`.

---

## 1. Files

### New test files

| File | Layer | R |
|---|---|---|
| `test/unit/formsDefaultIsFixed.test.ts` | vitest, source scans and prototype checks | R44, R47 |
| `test/unit/FormsPage.test.tsx` | vitest, jsdom, server component with mocked `formService` and `callerAccess` | R44, R48, R58 |
| `test/unit/SiteHeader.test.tsx` | vitest, jsdom | R49 |
| `test/unit/FormExportClient.test.ts` | vitest, fake fetch | R56 |
| `test/unit/formExportRoute.test.ts` | vitest, mocked `formService` and `formExportClient` | R57 |
| `test/unit/FormLine.test.tsx` | vitest, jsdom, and source checks of the two pages | R58, R66 |
| `test/unit/useOnceName.test.ts` | vitest | R67 |
| `test/unit/annexDefaultExportFixture.test.ts` | vitest | R54 |
| `test/unit/mcasExampleAgrees.test.ts` | vitest | R72 |
| `services/prefill/tests/test_form_export.py` | pytest, prefill | R50, R51, R52, R54, R73 |

New fixture: `services/prefill/tests/fixtures/annex_iv_default_form.json` (the 14 default questions as
`{text, citation, required, annexPoint}`, name "Annex IV default", version 1). It was generated from
`src/data/keyQuestions.ts`, and `annexDefaultExportFixture.test.ts` keeps it equal to `annexDefaultVersion()`.

Files that do not exist yet are loaded at run time (`import(resolve(path))`, as
`systemVersionOntologyRoute.test.ts` does). A missing module therefore fails only the tests that need it,
never a whole file at collection. The Python tests use the round 1 pattern: a `try/except ImportError`
stand-in that re-raises.

### Existing test files changed

Extended only (tests appended, nothing existing touched): `test/unit/FormImport.test.tsx`,
`FormImportClient.test.ts`, `formLibrary.test.ts` (plus one added `import * as library` line),
`formsNoModel.test.ts`, `annexDefaultForm.test.ts`, `VerticalCard.test.tsx` (plus one `readFileSync` import),
`services/prefill/tests/test_form_import.py`, `test_documents.py`, `test_fields.py`,
`services/system_card_renderer/tests/test_form_coverage.py`.

Changed on purpose and extended (section 3 lists every changed line): `test/support/fakeFormStore.ts`,
`test/unit/FormService.test.ts`, `formActions.test.ts`, `formDraft.test.ts`, `builderState.test.ts`,
`FormBuilder.test.tsx`, `formChooser.test.ts`, `FormChooser.test.tsx`, `editSystemPage.test.tsx`,
`QualificationExporter.test.ts`, `test/db/forms.db.test.ts`, `services/prefill/tests/test_app.py`,
`services/ontology/tests/test_coverage.py`, `test_example_mcas.py`, `test_roundtrip.py`.

---

## 2. Requirement to test map

Every test title (TS) or name (Python) carries its R-id, so `grep -rn "R57 "` or `grep -rn "_r57_"` finds
them all.

| R | Test file :: tests |
|---|---|
| R43 | `FormService.test.ts` :: "R43 the fake store has no default field...", "R43 the library is Annex IV default (the default), then the rest by name...", "R43 exactly one chooser option is the default...", "R43 a store without the seeded form has no default row" ; `FormChooser.test.tsx` :: "R8 R43 tags the Annex IV default...", "R43 the default tag ... on no other option" |
| R44 | `formsDefaultIsFixed.test.ts` :: 9 x "R44 ..." (actions export exactly saveForm and useFormOnce, no SetDefaultButton.tsx, no setDefault on either prototype, 4 source-scan needles, no isDefault in the schema) ; `FormsPage.test.tsx` :: "R44 an administrator sees no Set as default..." |
| R45 | `annexDefaultForm.test.ts` :: 7 x "R45 ..." (the file exists, statements of 3.2 in order, no UPDATE/DELETE/TRUNCATE/BEGIN/COMMIT/CONCURRENTLY/IF EXISTS outside the function body, no trigger added or dropped, the 090000 sha256 is unchanged, no `isDefault`/`is_default` in the schema, the schema's doc comment) ; `test/db/forms.db.test.ts` :: 6 x "R45 ..." (no column, no index, the second builtin fails on `form_builtin_is_the_default`, unlisting the default fails with the new trigger message, the description update succeeds and is rolled back, the migration is recorded) ; the R7 DB test (unchanged) |
| R46 | `formChooser.test.ts` :: 7 x "R46 ..." (first card, whatever the order, legacy and listed, unlisted, unseeded and empty options, a stale `defaultFormId` ignored) ; `editSystemPage.test.tsx` :: "R8 R46 no form named...", "R46 the page preselects annex-iv-default by the constant...", "R46 the page source no longer derives a default" |
| R47 | `formsDefaultIsFixed.test.ts` :: 9 x "R47 ..." (4 models, the two migrations, method parameters and `projectId`/`project_id` in FormService and FormRepository) ; `FormService.test.ts` :: 2 x "R47 ..." ; `formActions.test.ts` :: 2 x "R47 ..." (the service is never told the project; save in "a", then read chooser, library, builder groups and resolve as project "b"'s pages do) |
| R48 | `FormsPage.test.tsx` :: "R48 the intro says...", "R48 projects a and b see the same rows..." ; `formActions.test.ts` :: "R48 saveForm and useFormOnce called with project b redirect inside /p/b/" |
| R49 | `SiteHeader.test.tsx` :: 2 x "R49 ..." |
| R50 | `test_form_export.py::TestCsv` :: 9 `test_r50_*` (the exact example, dataclass shape, zero questions, quoting, guard x4, `'`+guard x4, no guard otherwise, collapse, order) |
| R51 | `test_form_export.py::TestMarkdown` :: 5 `test_r51_*` (the exact example, `\` before `|`, no guard, zero questions, collapse) |
| R52 | `test_form_export.py::TestFileName` :: 5 examples + 3 `test_r52_*` (cut then strip, cut to 60, ASCII) |
| R53 | `test_form_import.py::TestAnnexColumn` :: 17 `test_r53_*` ; `::TestCsvFormulaGuard` :: 8 ; `::TestMarkdownEscapes` :: 4 ; `test_app.py::TestFormImportAnnexPoint` :: 1 ; `test_app.py::test_r27_a_csv_comes_back_as_questions` (updated) ; `test_fields.py` :: `test_r53_annex_point_ids_equal_the_repo_json_in_order` |
| R54 | `test_form_export.py::TestRoundTrip` :: 10 round trips (5 forms x csv, md) + 5 more `test_r54_*` ; `annexDefaultExportFixture.test.ts` :: 2 x "R54 ..." |
| R55 | `test_app.py::TestFormExportEndpoint` :: 18 `test_r55_*` (csv, md, no questions, 4 other formats, unknown point, 201 and 200 questions, 7 pydantic 422 cases, stores nothing) |
| R56 | `FormExportClient.test.ts` :: 9 x "R56 ..." |
| R57 | `formExportRoute.test.ts` :: 17 x "R57 ..." ; `FormService.test.ts` :: 4 x "R57 ..." (`exportable`) ; `formActions.test.ts` :: "R73 the export route is a GET under /p/[project]/..." |
| R58 | `FormsPage.test.tsx` :: 2 x "R58 ..." ; `FormLine.test.tsx` :: 4 x "R58 ..." |
| R59 | `FormImportClient.test.ts` :: 1 x "R59 ..." ; `FormImport.test.tsx` :: 3 x "R59 ..." |
| R60 | `formDraft.test.ts` :: 5 x "R60 ..." ; `FormService.test.ts` :: 8 x "R60 ..." |
| R61 | `formDraft.test.ts` :: 9 x "R61 ..." ; `FormService.test.ts` :: "R61 F opened and saved with no change...", "R61 R64 F with its pick switched..." ; `FormBuilder.test.tsx` :: "R64 R61 saving after taking it..." |
| R62 | `builderState.test.ts` :: 4 x "R62 ..." ; `FormService.test.ts` :: "R62 each library group carries its form's latest version id..." |
| R63 | `formLibrary.test.ts` :: 12 x "R63 ..." |
| R64 | `builderState.test.ts` :: 3 x "R64 ..." ; `FormBuilder.test.tsx` :: 5 x "R64 ..." |
| R65 | `test_coverage.py` :: 10 `test_r65_*` ; `test_form_coverage.py` (renderer) :: 2 `test_r65_*` ; `VerticalCard.test.tsx` :: "R66 the TS Coverage type carries optionalBlank" |
| R66 | `test_coverage.py::test_r65_r66_default_form_with_the_four_optional_points_blank` ; `VerticalCard.test.tsx` :: 2 x "R66 ..." ; `FormLine.test.tsx` :: 2 x "R66 ..." |
| R67 | `useOnceName.test.ts` :: 9 x "R67 ..." |
| R68 | `FormService.test.ts` :: 4 x "R68 ..." ; `formActions.test.ts` :: 4 x "R68 ..." |
| R69 | `test_coverage.py` :: 3 `test_r69_*` ; `QualificationExporter.test.ts` :: "R69 two owners that share the name..." and the updated R30 exact form |
| R70 | `test_documents.py` :: 6 `test_r70_*` ; `test_form_import.py::TestDocxExpansion` :: 4 ; `test_app.py::TestDocxExpansionEndpoints` :: 2 |
| R71 | `formChooser.test.ts` :: 17 x "R71 ..." (`pickFormParams`, every row, empty strings) ; `editSystemPage.test.tsx` :: "R71 ?formVersion wins over ?form" (flipped) + 10 x "R71 row N ..." |
| R72 | `mcasExampleAgrees.test.ts` :: 5 x "R72 ..." ; `test_example_mcas.py` :: 2 updated counts + 2 `test_r72_*` (413 triples and 59 nodes, 1f after 1de) ; `test_roundtrip.py` (updated) ; `test_coverage.py` :: 3 updated + `test_r72_the_committed_mcas_export_covers_14_of_14` |
| R73 | `formsNoModel.test.ts` :: 3 x "R73 ..." ; `test_form_export.py::test_r73_*` ; `formActions.test.ts` :: 3 x "R73 ..." (actions export exactly two, the export route under the door, no `.admin` read) ; the R42 tests stay |

---

## 3. Existing tests changed on purpose

Each change replaces superseded behaviour with a test of the new rule. Nothing else was weakened or deleted.
Rows marked **gap** are tests that section 5.3 does not name, but that the addendum's new shapes break
(section 7).

| File :: test | Before | After | Reason |
|---|---|---|---|
| `test/support/fakeFormStore.ts` | `FormRow.isDefault`, `seedDefault(isDefault = true)`, `addForm({isDefault})`, `setDefault()` | all four removed; header documents that there is no default flag | 5.3, R43 ("the fake store has no default field at all"), R44 |
| `FormService.test.ts` :: header | `new FormService(repo, {newId?})`, `setDefault(...)` | `{newId?, now?}`, `saveDraft(..., systemName?)`, `exportable`, groups with `versionId` | 3.4 |
| `FormService.test.ts` :: "R3 a builtin form that is not the default still comes before the rest" | set `isDefault` in the fake store | **removed**; replaced by the four R43 tests | 5.3 (R3 ordering tests that set a default) |
| `FormService.test.ts` :: describe "setting the org default (R4)" (5 tests: move, unlisted, F6 race, F6 other failure, unknown) | `setDefault` behaviour | **removed** | 5.3, R44 |
| `FormService.test.ts` :: "R5 two forms' questions with the same visible text..." | picks `{kind, questionId}` | picks gain `fromVersionId: "ff-v1"` / `"gg-v1"` | 5.3 (every pick without fromVersionId) |
| `FormService.test.ts` :: "R22 a pick takes the owner's most recent wording, not what the draft says" | pick without version; expected the owner's latest (gg v2) | renamed "R60 a pick takes the wording of the version it was picked from..."; pick pinned to `gg-v2`, same expected snapshot | 5.3, R60 |
| `FormService.test.ts` :: "R22 a pick of a question its owner dropped takes the last version that had it" | the owner's-history lookup | replaced by "R60 a pick pinned to an older version keeps that version's wording..." and "R60 a pick of a question its owner dropped, pinned to a version that had it..." | 5.3, R60 (`latestSnapshot` removed) |
| `FormService.test.ts` :: "R22 a pick of the seeded questions keeps their group label" | pick without version | `fromVersionId: "annex-iv-default-v1"` | 5.3 |
| `FormService.test.ts` :: "R22 refuses a pick of a question that does not exist" | pick without version | `fromVersionId: "gg-v2"`, same refusal | 5.3 |
| `FormService.test.ts` :: "R22 a use-once form is unlisted, named Custom questions, and may repeat that name" | two saves both "Custom questions" | replaced by "R68 two use-once forms of one system on one day get unique names..." (`... 2026-09-25` and `... (2)`) | 5.3, R68 |
| `FormService.test.ts` :: "R3 gives each form its latest version number and question count" | unchanged | unchanged, but now red: it expects `isDefault: true` for Annex IV while the fake store has no default field | the sanctioned fake-store change; the service must compute `isDefault` (3.4) |
| `formActions.test.ts` :: header, hoisted mocks | `setDefault` mock, `admin` fixture | removed; `platformClient.latestVersion` mocked (module `@/server/services/PlatformClient`) | 5.3, R68 |
| `formActions.test.ts` :: describe "setDefaultForm (R4, A4)" (4 tests) | `setDefaultForm` behaviour | **removed** | 5.3, R44 |
| `formActions.test.ts` :: "R22 saves an unlisted form named Custom questions and opens that version" | `draft.name === "Custom questions"` | "R68 saves an unlisted form named after the system...": `latestVersion("mcas")` called, `opts` has `systemName: "MCAS"`, same redirect; describe renamed "useFormOnce (R22, R68)" | 5.3, R68 |
| `formDraft.test.ts` :: "R22 takes all three kinds", "R22 the same question picked twice" | picks without version | picks gain `fromVersionId` | 5.3, R60 |
| `formDraft.test.ts` :: the 8 `sameContent` tests (R6) | `sameContent(draft, version)`; pick without version | `sameContent(draft, version, snapshots)`; pick `fromVersionId: "gg-v1"`, with a map holding that snapshot | 5.3, R61 |
| `builderState.test.ts` :: R16 x2, R17 "replaces...", "R6 R19 editing a form opens...", "R20 editing a picked question..." | `tick {question}`; drafts `{kind: "pick", questionId}` | `tick {question, versionId}`; drafts gain `fromVersionId`; Start from fixture gets `versionId: "mix-v2"` | 5.3, R62 |
| `builderState.test.ts` :: the other tick calls (R16 ticked twice, R18, R19 remove, R20 copy) | `tick {question}` | `tick {question, versionId}` (expectations unchanged) | R62 |
| `FormBuilder.test.tsx` :: `library` fixture, "R22 Save form sends the draft", "R22 Use once sends the draft" | groups without `versionId`; picks without version | groups gain `versionId`; saved picks `fromVersionId: "acme-v1"` | 5.3, R62 |
| `formChooser.test.ts` :: header and the 6 `preselect` calls | third argument had `defaultFormId` | `defaultFormId` removed | 5.3, R46 |
| `formChooser.test.ts` :: "R8 a project's first card starts on the org default", "R8 a previous form that is no longer offered falls back to the org default" | expected `acme` (the configured default) | renamed R46; expect `annex-iv-default` | R46 |
| `FormChooser.test.tsx` :: `options` fixture, "R8 tags the org default and checks the preselected form" | `isDefault` on acme; tag on acme | `isDefault` on Annex IV; "R8 R43 tags the Annex IV default and checks the preselected form" | 5.3, R43 |
| `editSystemPage.test.tsx` :: `OPTIONS` and the expected `chooser.options` | `isDefault` on acme | `isDefault` on Annex IV | 5.3 |
| `editSystemPage.test.tsx` :: "R8 no form named...", the unknown-id `it.each` (2), "R8 the starting card failing..." | preselected `acme` | preselected `annex-iv-default` ("R8 R46 no form named ...") | R46 |
| `editSystemPage.test.tsx` :: "R8 ?form wins over ?formVersion when both are given" | `acme-v2`, `resolve` not called | flipped: "R71 ?formVersion wins over ?form": `u1-v1`, `latestVersion` not called | 5.3, R71 |
| `test/db/forms.db.test.ts` :: describe "exactly one org default (R4)" (3 tests) | `form_one_default`, the F6 race, the unlisted default | **removed**; replaced by the six R45 DB tests | 5.3, R45 |
| `test/db/forms.db.test.ts` :: "R1 the default form and its version are seeded with every block" | `SELECT name, origin, listed, is_default` expecting `is_default: true` | selects `name, origin, listed` only | **gap**: the column is dropped by 120000, so the old query would error |
| `QualificationExporter.test.ts` :: "R30 the export names the form, its version and its questions in order" | exact `form.questions` without `ownerFormId` | each entry gains `ownerFormId` | **gap**: R69 adds the key to the exact shape |
| `services/prefill/tests/test_app.py` :: `test_r27_a_csv_comes_back_as_questions` | exact questions `{text, citation, required}` | each gains `"annexPoint": None` | **gap**: R53 adds the key |
| `services/ontology/tests/test_coverage.py` :: `test_r34_the_shape` | `set(annex) == {covered, total, points}` | adds `optionalBlank` | **gap**: R65 adds the key |
| `test_coverage.py` :: `test_r34_a16_the_committed_mcas_export_skips_1f_so_it_covers_13` | the committed JSON, `13 of 14 points.` | renamed `test_r34_a16_the_mcas_export_without_1f_covers_13_with_one_optional_blank`; removes 1f from a copy; `13 of 14 points (1 optional left blank).` | R72 table |
| `test_coverage.py` :: `test_r34_with_a_form_the_view_carries_form_and_coverage` | `13 of 14 points.` | `Annex IV coverage: 14 of 14 points.` | R72 table |
| `test_coverage.py` :: `test_r34_the_mcas_example_as_the_form_has_it_covers_all_14` | appended a 1f answer | the committed JSON as it is | R72 table |
| `test_example_mcas.py` :: `test_the_export_fills_every_new_form_element` | `len(answers) == 13` | `== 14` | R72 table |
| `test_example_mcas.py` :: `test_each_answer_is_labelled_with_its_annex_iv_citation` | `len(citations) == 13` | asserts `"Annex IV(1)(f)"`, `== 14` | R72 table |
| `test_roundtrip.py` :: `test_the_rebuilt_graph_keeps_the_annex_iv_answers` | 13 texts, 9697 characters | 14, 9996 | R72 table |
| `test_example_mcas.py` :: the two committed-graph tests | unchanged | unchanged; they pass only once `mcas.ttl` and `mcas.jsonld` are regenerated | R72 table |

`FormImport.test.tsx` is in 5.3's list but had no `defaultFormId` or stored `isDefault` fixture, so nothing
in it changed; the R59 tests were appended. The `setDefaultForm: vi.fn()` keys left in the action mocks of
`FormBuilder.test.tsx` and `FormImport.test.tsx` are harmless and were not touched.

---

## 4. Interface names chosen where the addendum is silent

Each is also stated in the header comment of the test file that fixes it.

**TS**
- `FormService` constructor option `now?: () => Date` (3.4); `exportable(formId, versionNumber?)` returns the
  same `ResolvedFormVersion` shape as `resolve`, or `null`.
- `saveDraft(draft, {listed: false, systemName})` takes the use-once name's taken list from
  `repository.listForms()` (every form, listed or not).
- Builder actions: `{type: "tick", question, versionId}` (the group's versionId) and
  `{type: "takeLatest", index, question, versionId}`. `takeLatest` on an own row, a copy row or an index past
  the end returns the very same state object (`toBe`). A pick row has `fromVersionId` next to `source`.
- `sameContent(draft, version, snapshots)`: `snapshots` is a `Map` keyed `${fromVersionId}:${questionId}`
  whose values are `{text, citation, required, annexPoint, groupLabel}`.
- `sourceUpdates(rows, library)` is exported from `src/domain/forms/library.ts`; its result keys are row
  indexes. A group holding the same question id counts only when it is the owner's group (`formId ===
  source.ownerFormId`).
- `pickFormParams({example, form, formVersion})` in `src/domain/forms/chooser.ts` returns one of
  `{lookup: "example"}`, `{lookup: "formVersion", id}`, `{lookup: "form", id}`, `{lookup: "none"}`. An
  example counts as "known" when `findExample()` knows it (case-insensitive, as today). Empty strings count as
  absent.
- `preselect` ignores a leftover `defaultFormId` key when an old caller still passes one.
- Export route singletons: `formService` and `formExportClient` (named like `formImportClient`) in
  `src/server/services/FormExportClient.ts`. `format` is case-sensitive (`CSV` gets 400). A `version` that
  is present but not a positive integer (`0`, `-1`, `1.5`, `abc`, `3x`) gets 404. The body is checked as
  bytes (`arrayBuffer`), because `Response.text()` would strip the BOM.
- `FormExportClient.write` sends `Content-Type: application/json` and posts to `serviceUrl(base,
  "/forms/export")`, the same way FormImportClient builds its URL.
- `FormLine`'s text content is exactly `Form: <name> v<N> · CSV · Markdown`. The card and edit pages must
  render `<FormLine ...>` and no longer contain `Form: {`.
- Library page: the intro is the `header p`; row links are, in order, "Start from", "Edit", "Export CSV",
  "Export Markdown" (text content); `formService.library()` is called with no arguments.
- `SiteHeader`: nav link texts in order; the header reads `LAUNCHER_URL`, which the test sets.
- `useFormOnce` reads the system name from `platformClient.latestVersion(project)` (module
  `@/server/services/PlatformClient`). A null answer or a throw falls back to the `project` argument. A blank
  draft name is not refused.
- R47 parameter scan: `_project` counts as a project parameter, since the addendum removes it.
- R72: the seed's answers are read through the module by running `seedMcas(fakePrisma, {platform})` and
  capturing `data.answers.create`, so `scripts/seed_mcas.mjs` needs no change.

**Python**
- `ImportedQuestion.annex_point: str | None` (a dataclass field); the reader keeps `.text`, `.citation`,
  `.required`.
- `check_docx_expansion` is asserted to return `None` for a normal file. Exactly the limit is accepted; the
  limit minus one is refused.
- A .docx bomb is built in the test: a python-docx file plus a 51 MiB member of zeros (about 50 KB zipped).
  `docx.Document` is monkeypatched to fail, which proves the check runs first.
- `/forms/export`: an empty `format` (`""`) gets the exact 422 message; `version: 0` and a mistyped version
  get pydantic's list detail.
- Round-trip comparison: the importer's `(text, citation, required, annex_point)` against the form's
  `(collapse(text), collapse(citation), required, annexPoint)`.

---

## 5. Commands

```bash
cd apps/qualification
P=/tmp/claude-1001/-home-listuser/572e79f5-831d-4f75-909f-47cb45306c7a/scratchpad

npx vitest run                                    # unit + component; DB files skip without the env
test/db/throwaway-db.sh                           # DB-gated, throwaway Postgres on a random port, removed after

(cd services/ontology && PYTHONPYCACHEPREFIX=$P/pyc $P/venv-ontology/bin/python -m pytest -p no:cacheprovider -q)
(cd services/prefill  && PYTHONPYCACHEPREFIX=$P/pyc .venv/bin/python -m pytest -p no:cacheprovider)   # pytest.ini has -q
(cd services/system_card_renderer && PYTHONPYCACHEPREFIX=$P/pyc $P/venv-system_card_renderer/bin/python -m pytest -p no:cacheprovider -q)
(cd $P/agents-cwd && PYTHONPYCACHEPREFIX=$P/pyc $P/venv-agents/bin/python -m pytest -p no:cacheprovider -q \
   -c $PWD/services/agents/pytest.ini --rootdir $PWD/services/agents $PWD/services/agents/tests)
```

`$P/r2-run-all.sh <tag>` runs the five non-DB suites and writes logs to `$P/r2-logs/`.

R72 needs the graph files regenerated after the JSON edit (from `services/ontology`, as the addendum says):
`python -m airo_min.build examples/mcas.qualification.json --extracted examples/mcas.extracted.json --format turtle --out examples/mcas.ttl`
and the same with `--format json-ld --out examples/mcas.jsonld`.

---

## 6. Red run (2026-09-25)

### Before any change (baseline, this session)

| Suite | Result |
|---|---|
| vitest | 69 files (65 passed, 4 skipped); 728 tests: 693 passed, 35 skipped |
| ontology | 224 passed, 3 failed (the pre-existing three of plan 6.4: `test_build::...nineteen_properties`, `test_example_mcas::test_it_exercises_all_nineteen_properties`, `test_roundtrip::...every_airo_relation`) |
| prefill | 176 passed |
| renderer | 33 passed |
| agents | 152 passed |
| DB | 34 tests, 34 passed (04-progress, fix round 1; not re-run before the change) |

### After (tests written, no implementation)

| Suite | Totals | New tests with an R43..R73 id | Pre-existing tests |
|---|---|---|---|
| vitest | 78 files (22 failed, 52 passed, 4 skipped); 914 tests: 164 failed, 712 passed, 38 skipped | 208: 155 failed, 47 passed, 6 skipped (the R45 DB tests) | 9 changed tests red for the new rule (section 3); every other baseline-passing test still passes |
| ontology | 24 failed, 219 passed | 16: 14 failed, 2 passed | the same 3 pre-existing failures; the 7 changed R72/R65 tests red |
| prefill | 99 failed, 184 passed | 107: 98 failed, 9 passed | `test_r27_a_csv_comes_back_as_questions` red (annexPoint key); all 176 others pass |
| renderer | 2 failed, 33 passed | 2: 2 failed | all 33 pass |
| agents | 152 passed | none | unchanged |
| DB (`test/db/throwaway-db.sh`) | 3 files, 37 tests: 5 failed, 32 passed | 6 R45: 5 failed, 1 passed | 31 (34 minus the 3 removed R4 tests) pass; container `aisc-t-qual-*` removed, none left |

The comparison with the baseline was done test by test, not by counts. The baseline suite was run in a
scratch copy of the app holding the pre-change test files (JSON and junit reports in `$P/r2-logs/`, copy since
removed). Every baseline-passing test is either still passing, or listed in section 3 as removed, renamed or
changed. That scratch copy is not a git repository, so there `secrets.test.ts` failed twice and two renderer
test ids differ by path; in the real repository they pass unchanged.

**Why the new tests fail.** Every failure is a missing module, function, key or behaviour:
"Cannot find module .../FormExportClient.ts" (and the same for the route, FormLine and useOnceName);
`svc.exportable is not a function`; `sourceUpdates` and `pickFormParams` undefined; `No module named
'prefill.form_export'`; 404 on `/forms/export`; `check_docx_expansion` and `ANNEX_POINT_IDS` missing;
`isDefault` undefined; picks still taking the owner's latest wording; `setDefaultForm` still exported;
SetDefaultButton still rendered; the old `form_name_is_fixed` message and the `is_default` column in the DB;
the MCAS JSON with 13 answers. None fails on a typo or a broken import inside a test.

**Achievability check (scratch only).** The prefill tests were also run against a throwaway reference in
`$P/r2ref/` (`form_export.py`, the importer extensions, `check_docx_expansion`), loaded over the real
modules by a pytest plugin (`-p r2ref_plugin`); nothing in the repository was touched. Result: 194 passed,
and 1 failed, the R73 check that `prefill/form_export.py` exists in the repository. The R72 figures were
measured on a scratch copy of the JSON with the 1(f) answer inserted: 1(f) is 299 characters, the graph has
413 triples and the view 59 nodes, which confirms 9996, 413 and 59.

**New tests that pass already, by design.** They pin behaviour that must not change, or scan code that is
already clean:
- vitest (47): all R71 edit-page rows that do not combine both parameters (rows 1, 2 with `?form` absent, 3
  with `?form` absent, 4, 5, 6); `preselect` cases where Annex IV is the first option; the R47 schema,
  repository and "no project argument" checks; the R48 redirects and same-rows-for-a-and-b; R49 "no project,
  no Forms link"; the R54 fixture check (the fixture was generated to agree); the 090000 hash; the FormChooser
  tag tests (the component renders the flag it is given: the constant is enforced by R43 in FormService and
  by R46 on the edit page); R60 "F3" and R61 "no change, no version" (versions are immutable today; the
  failing R61 test is the one that switches versions); `sameContent` cases where the pinned snapshot is equal;
  R66 VerticalCard (it prints the Python summary as it is); the R73 scans (vacuous until the files exist; the
  existence test beside them is red); `takeLatest never mutates`; R68 "listed keeps the draft's name" and
  "origin still travels".
- ontology (2): the points keep their shape; grouping by name without `ownerFormId`.
- prefill (9): `no` is not required; `'` before anything else stays; Markdown and .docx cells untouched by
  the guard; other backslashes kept; a normal .docx still reads; a bad zip keeps its message; the awkward
  texts are distinct; the fixture holds the 14 points.
- DB (1): the default form's description can change.

The prefill failing run takes about 28 s, because pytest formats the re-raised ImportError for every failing
test. The same tests take about 1 s against the reference.

---

## 7. Addendum gaps and contradictions found

1. **R53 against R50 and R54, the `'=` guard.** R50 writes a cell starting `'=` as `''=`. R53's inverse,
   read literally ("first character `'` and second one of `=`, `+`, `-`, `@` loses that first `'`"), does not
   strip `''=`, because its second character is `'`. The R54 round trip of "a leading `'=`" (case 3) and B9
   ("the guard is invisible after a round trip") would then fail. The tests take the importer to be the exact
   inverse of the exporter: `''=x` imports as `'=x` (`test_r53_only_one_quote_is_removed`, and the round
   trip). A reference that follows the literal R53 text fails those two tests.
2. **R45 "contains no BEGIN" against section 3.2.** The exact function body in 3.2 has plpgsql's own
   `BEGIN ... END $$`. The test checks for `BEGIN`/`COMMIT` outside the dollar-quoted body, and for data
   changes everywhere.
3. **5.3 misses four tests that the new shapes break:** `test_app.py::test_r27_a_csv_comes_back_as_questions`
   (R53 `annexPoint`), `test_coverage.py::test_r34_the_shape` (R65 `optionalBlank`),
   `QualificationExporter.test.ts` "R30 the export names the form..." (R69 `ownerFormId`), and the DB test
   "R1 the default form and its version are seeded with every block" (it selected `is_default`, which 120000
   drops). Each was changed minimally (section 3, rows marked gap).
4. **R72 "no change" to `scripts/seed_mcas.mjs` against "reads MCAS_SEED or its ANSWERS through the
   module".** `MCAS_SEED` has no answers and `ANSWERS` is not exported. The test runs `seedMcas()` with a
   fake prisma instead, so the script stays unchanged.
5. **R53 warning value.** "`<trimmed value>`" does not say whether the value is lowercased too. The tests use
   values where it makes no difference (`3a`, `9z`, `7q`, `annex iv(2)(a)` given in lower case).
6. **R57 case of `format`.** "not `csv`/`md`" was taken as case-sensitive (`?format=CSV` is 400). The same
   goes for the endpoint (`"CSV"` gets 422).
7. **R58 and R66 on the pages** are source checks (`<FormLine` present, `Form: {` gone): the card page is a
   server component with many services, and the edit-page test cannot mock a module that does not exist yet.
   The FormLine component itself is rendered and checked.
8. **R47 `_project`.** The addendum says the unused `_project` parameter of `setDefault` goes. The scan
   counts `_project` as a project parameter.
9. **R43 in the chooser component.** The component only renders `isDefault` as given; the tests for it pass
   today. The constant is pinned where it is decided: FormService (R43) and the edit page (R46, with flags
   stripped and the order reversed).
