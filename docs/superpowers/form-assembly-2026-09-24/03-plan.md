# Form assembly: implementation plan (stage 3)

Date: 2026-09-25. Inputs: `01-spec.md` (R1 to R42), `02-tests.md` (the test map), the tests themselves,
and the code of `apps/qualification` on branch `feat/unified-modules`.

The tests are the contract. Where the spec and the tests disagree, this plan follows the tests and
says so (section 2). All paths below are relative to `apps/qualification` unless they start with `/`.

Two repositories are involved: `apps/qualification` is its own git repository (a submodule of
`/home/listuser/aisc-install`, same branch name). The code and tests live in the app repository; this
plan and the spec live in the parent repository. Nothing in this plan commits to either.

---

## 0. Before starting (task 0: baseline and tools)

1. Confirm the branch without switching: `git -C apps/qualification branch --show-current` prints
   `feat/unified-modules`. If it does not, stop and ask.
2. Record the red baseline. Expected today (2026-09-25):
   - `npx vitest run`: 67 files (21 failed, 42 passed, 4 skipped), 557 collected tests
     (92 failed, 431 passed, 34 skipped), plus 11 new files that fail at import.
   - ontology: 30 failed, 190 passed, 7 errors (3 of the failures are pre-existing and unrelated, see 6.4).
   - prefill: 98 failed, 75 passed. renderer: 7 failed, 10 passed. agents: 2 failed, 148 passed.
   - `npx tsc --noEmit`: 0 errors outside `test/` (the test files have errors for the missing modules).
3. Python environments. Make throwaway venvs in your own scratchpad `$P` (never inside the repo):
   ```bash
   P=<your scratchpad>
   uv venv $P/venv-ontology  && uv pip install --python $P/venv-ontology  -r services/ontology/requirements.txt pytest httpx
   uv venv $P/venv-renderer  && uv pip install --python $P/venv-renderer  -r services/system_card_renderer/requirements.txt pytest httpx
   uv venv $P/venv-agents    && uv pip install --python $P/venv-agents    -r services/agents/requirements.txt pytest httpx rdflib==7.6.0
   ```
   Prefill already has `services/prefill/.venv`: use it as it is, and do not install into it.
   Two quirks: some `__pycache__` folders are root-owned, so always set `PYTHONPYCACHEPREFIX=$P/pyc`
   and pass `-p no:cacheprovider`; `services/agents/application.log` is root-owned, so run the agents
   suite from `$P/agents-cwd`. The exact commands are in section 6.

Short names used below:
```bash
VT="npx vitest run"                                   # from apps/qualification
ONTO="(cd services/ontology && PYTHONPYCACHEPREFIX=$P/pyc $P/venv-ontology/bin/python -m pytest -p no:cacheprovider"
PREF="(cd services/prefill && PYTHONPYCACHEPREFIX=$P/pyc .venv/bin/python -m pytest -p no:cacheprovider"
REND="(cd services/system_card_renderer && PYTHONPYCACHEPREFIX=$P/pyc $P/venv-renderer/bin/python -m pytest -p no:cacheprovider"
```
(Close each `(` with `)` after the test paths; the full lines are in section 6.)

---

## 1. Task list (ordered by dependency)

Every task ends with a command whose output proves it. "Green" means every test the command selects
passes; for a file that other tasks also cover, the task names the describe blocks that must pass.

### Task 1. Shared data, the in-memory default form, the migration and the Prisma schema (R1, R2 TS, R4, R5, R6, R7 shape)

Files to create:
- `src/data/annexPoints.json`: exactly the JSON in spec section 2 (the `_comment` key and the 14
  `points`, nothing else).
- `src/domain/forms/annexPoints.ts`:
  - `export const ANNEX_POINTS: { id: AnnexPointId; citation: string }[]` = the JSON's `points`
    (import the JSON; the test compares with `toEqual`).
  - `export type AnnexPointId = "1a" | "1b" | "1c" | "1de" | "1f" | "1gh" | "2a" | ... | "2h"`.
  - `export function isAnnexPoint(s: unknown): s is AnnexPointId` (exact, case-sensitive).
  - `export function annexCitation(id: AnnexPointId): string`.
- `src/domain/forms/blocks.ts`: `FORM_BLOCKS` (the 9 ids in spec section 3 order, `as const`),
  `type FormBlock`, `IDENTITY_FIELDS = ["systemName", "systemVersion", "company"] as const`,
  and a helper `inBlockOrder(blocks: readonly string[]): FormBlock[]` (filter of FORM_BLOCKS) that
  later tasks reuse.
- `src/domain/forms/types.ts`: `ResolvedQuestion`, `ResolvedFormVersion` exactly as spec 5.1.
  Also export the `FormDraft` question union here or in `formDraft.ts` (task 2).
- `src/domain/forms/legacy.ts`: `DEFAULT_FORM_ID = "annex-iv-default"`,
  `DEFAULT_VERSION_ID = "annex-iv-default-v1"`, `resolveFormVersionId(id: string | null): string`,
  `annexDefaultVersion(): ResolvedFormVersion` built from `KEY_QUESTIONS` on every call (a fresh
  object and fresh arrays each time): `questionId = "annex-iv-" + id`, `scope = group`, `localId = id`,
  `key`, `field = keyQuestionField(q)`, `text`, `citation`, `required = !optional`,
  `annexPoint = id`, `groupLabel`, `ownerFormId = DEFAULT_FORM_ID`, `ownerFormName = "Annex IV default"`,
  `ownerBuiltin = true`; the version is listed, builtin, number 1, `blocks = [...FORM_BLOCKS]`.
  Pure: it may import only `@/data/keyQuestions` and `./blocks` (it is used in the browser).
- `prisma/migrations/20260925090000_forms_are_data/migration.sql` (section 3 below has the SQL).

Files to modify:
- `prisma/schema.prisma`: add the four models of spec 4.1 verbatim, plus on `Qualification`
  `formVersionId String? @map("form_version_id")`, the `formVersion` relation and
  `@@index([formVersionId], map: "qualification_form_version_id_idx")`; on `QualificationAnswer`
  replace `@@unique([qualificationId, questionId])` with
  `@@unique([qualificationId, toolId, questionId], map: "qualification_answer_qualification_id_tool_id_question_id_key")`.
  Nothing in `src` or `scripts` uses the old compound key (checked), so no caller changes.
- Then run `npx prisma generate` (writes only `node_modules/.prisma`; it touches no database). The
  typecheck and the DB tests need the regenerated client.

Proof:
```bash
$VT test/unit/annexPoints.test.ts test/unit/annexDefaultForm.test.ts      # 6 + 14 green
npx prisma validate
```

### Task 2. Pure domain modules (R6 sameContent, R8, R16 to R23)

- `src/domain/forms/formDraft.ts`:
  - `export type FormDraft` (spec 5.1). `parseFormDraft(input: unknown, context?: { takenNames?: string[] })`
    returns `{ ok: true; value: FormDraft } | { ok: false; error: string }`. Never throws.
  - Use zod for the shape (a discriminated union on `kind`, non-strict objects, so an extra key such as
    `text` on a pick is stripped and not refused), then plain checks for the messages, in this order:
    name trimmed; blank gives "Give the form a name."; over 120 gives "A form name is at most 120
    characters."; when `takenNames` is given and one equals the name ignoring case, "A form called
    <name> already exists."; description over 500 is refused (any message); each block that is not in
    FORM_BLOCKS gives "<id> is not a part of the form." (so `systemName` is refused too); duplicate
    blocks are refused (any message); more than 200 questions gives "A form has at most 200 questions.";
    then per question at 1-based position n: own or copy with blank text "Question n has no text.",
    text over 2000 "Question n is longer than 2000 characters.", citation over 200 "The citation of
    question n is longer than 200 characters.", an `annexPoint` that is not null and not
    `isAnnexPoint` "Question n names an Annex IV point that does not exist.", a `questionId`
    (pick or own) or a `fromQuestionId` (copy) already seen in the same set "Question n is already in
    the form.". Anything that fails the zod shape gives one generic message.
  - The returned value has the name, text and citation trimmed.
  - `sameContent(draft, version)`: blocks compared as sets; name ignored; same length; per position a
    pick matches when `questionId` equals the version question's `questionId`; an own with
    `questionId` matches when the id and text, citation, required and annexPoint all equal; an own
    without id or any copy is always a change.
- `src/domain/forms/builderState.ts`: state `{ formId: string | null, name, description, blocks,
  questions, origin: "builder" | "import" }`, rows as in `02-tests.md` section 3. Give each row an
  internal `rowKey` (a counter string) for React keys and focus; `toDraft` strips it and `source`.
  - `builderReducer(state, action)` is pure and never mutates (spread copies). Actions: `tick`
    (append a pick with `source`, no-op when `isTicked`), `untick` (remove pick or own rows with that
    id), `startFrom` (questions become picks of the form's questions in order, blocks become the
    form's), `move {from,to}` (out of range is a no-op), `addOwn {values}`, `edit {index, values}`
    (pick becomes copy with `fromQuestionId`; own keeps its `questionId`; copy stays a copy of the same
    source), `remove {index}`, `toggleBlock {block}`, `setName {name}`.
  - `initialBuilderState(opts = {})`: defaults `formId: null`, `name: ""`, `description: ""`,
    `blocks: [...FORM_BLOCKS]` (ASSUMED: a new form starts with every block, like the default form and
    like an import, A10), `questions: []`, `origin: "builder"`. `startFrom` applies the startFrom
    action; `edit` sets `formId`, `name = formName`, `blocks`, and rows: own (with id, text, citation,
    required, annexPoint) for questions whose `ownerFormId === form.formId`, picks otherwise.
  - `isTicked(state, questionId)`: a pick or own row with that `questionId`.
  - `toDraft(state)`: `{ name, description, blocks: inBlockOrder(state.blocks), questions }` where a
    pick is `{kind, questionId}`, an own is `{kind, questionId?, text, citation, required, annexPoint}`
    (omit `questionId` when absent), a copy is `{kind, fromQuestionId, text, citation, required,
    annexPoint}`.
- `src/domain/forms/library.ts`:
  - `type LibraryGroup = { formId: string; formName: string; questions: ResolvedQuestion[] }`.
  - `filterLibrary(groups, query)`: normalise both sides: lowercase, every character that is not a
    letter, a digit or `§` becomes a space, whitespace collapsed and trimmed. A query that normalises to
    `""` returns `groups` unchanged. A question matches when the normalised query is a substring of its
    normalised text or citation; groups with no match are omitted; order kept. (See conflict 2.10: the
    spec's plain rule fails the `"?"` test.)
  - `overlapHints(selected, candidates)`: plain object. For every Q in selected plus candidates with a
    non-null `annexPoint` p, map `Q.questionId -> p` when at least one selected question with another
    id has p.
  - `overlapLabel(point) = "≈ overlaps " + annexCitation(point)`.
- `src/domain/forms/chooser.ts`: `preselect(options, { fromFormVersionId, fromFormListed, defaultFormId })`:
  when `fromFormVersionId` is in some option's `versionIds`, `{param: "form", id: thatFormId}`; else
  when it is non-null and `fromFormListed` is false, `{param: "formVersion", id: fromFormVersionId}`;
  else the default form when it is an option; else the first option.

Proof: `$VT test/unit/formDraft.test.ts test/unit/builderState.test.ts test/unit/formLibrary.test.ts test/unit/formChooser.test.ts`
(31 + 17 + 10 + 6 green).

### Task 3. Python: the Annex points loader (R2 Python)

- Create `services/ontology/airo_min/annex_points.py`, shaped like `airo_min/pickers.py`:
  `_PACKAGE`, `_APP_ROOT = app_root_for(_PACKAGE)` (import `app_root_for` from `.pickers` or copy it),
  `candidate_paths()` reading `ANNEX_POINTS_PATH`, then `_APP_ROOT / "src/data/annexPoints.json"`,
  then `_PACKAGE / "annex_points.json"`. It must read the module globals at call time (the test
  monkeypatches `_PACKAGE` and `_APP_ROOT`). `load_annex_points()` returns the `points` list or raises
  `FileNotFoundError("annexPoints.json not found; looked in: " + every path)`. Module level
  `ANNEX_POINTS = load_annex_points()`, a private id-to-citation dict, and `annex_citation(id)` that
  raises `KeyError` for any other id. Standard library only.
- `services/ontology/Dockerfile`: add exactly one line after the existing vocabulary COPY:
  `COPY src/data/annexPoints.json ./airo_min/annex_points.json`. Do not build the image.

Proof: `$ONTO tests/test_annex_points.py)` (8 green).

### Task 4. Python: the graph and the view (R7, R31, R33, R34, R35)

`services/ontology/airo_min/build.py`:
- Read every metadata field with `.get(key, "")` (direct callers pass dicts without them).
- `qual:description` only when the description is non-empty; Purpose node and `hasPurpose` only when
  `targetUseCase` is non-empty; AIUser node and `hasAIUser` only when `targetUsers` is non-empty.
  Deployers unchanged. The provider is always there (company is identity).
- `_add_risk`: `stakeholder = next(iter(...), None)`; link `hasImpactOnStakeholder` only when found.
- Answers loop:
  - no `annexPoint` key: exactly today's code (`_annex_citation(answer)`);
  - `annexPoint` key with value None: skip the answer completely (A17);
  - `annexPoint` = p: `qual:citation = annex_citation(p)` (from `airo_min.annex_points`, never the
    free-text citation), `qual:questionId`, `qual:text` as today; and only when `toolId` is not
    `annex-1`/`annex-2`, add `QUAL.annexPoint = Literal(p)` and, when `citation` is non-empty,
    `QUAL.sourceCitation = Literal(citation)`. An unknown p raises `ValueError` (the app returns 422).
- Keep `_annex_citation` exactly as it is (test_annex_points compares against it).

Create `services/ontology/airo_min/coverage.py` (imports: standard library and `airo_min` only):
- `coverage(form, answers)`: answered = the set of `"toolId:questionId"` whose answer is non-blank
  after strip; only keys that are questions of `form` count. `annex.points` in ANNEX_POINTS order with
  `covered` true when some answered form question has that `annexPoint`; `covered` count; `total` 14.
  `forms`: one entry per owner that is not builtin (`ownerBuiltin` false), grouped by `ownerForm`
  name, in the order of that owner's first question in the form; `total` = its questions in this
  version, `answered` = those answered. `summary` = `"Annex IV coverage: <c> of 14 points"` +
  `"; <name>: <a> of <t> answered"` per entry + `"."`.
- `additional_documentation(form, answers)`: one section per owner form (builtin included), in first
  appearance order, `{"form": ownerForm, "entries": [...]}` listing answered questions whose
  `annexPoint` is None, in version order, each `{"key", "question": q.text, "citation": q.citation
  (the form's, see conflict 2.11), "answer"}`; sections with no entries dropped.

`services/ontology/airo_min/view.py`: `build_view(g, form=None, answers=None)`; when `form` is None the
result is exactly today's (no new keys); otherwise add `"form": {"name", "version"}`,
`"coverage": coverage(form, answers or [])`, `"additionalDocumentation": additional_documentation(...)`.

`services/ontology/app.py`: in `Qualification`, `description: str = ""`, `targetUseCase: str = ""`,
`targetUsers: str = ""`, and `form: dict[str, Any] | None = None` (pydantic ignores undeclared keys,
so without this line the form is silently dropped). In `build`, pass
`form=qualification.get("form")` and `answers=qualification["answers"]` to `build_view` only when the
form is not None.

Proof:
```bash
$ONTO tests/test_form_answers.py tests/test_absent_blocks.py tests/test_coverage.py tests/test_app.py tests/test_example_mcas.py tests/test_build.py)
```
All new tests green; `test_example_mcas.py::test_the_committed_turtle_matches_what_the_builder_produces`
still green; the only failures allowed are the 3 pre-existing ones in 6.4.

### Task 5. Python: the filler reads tags (R32)

`services/agents/fill/workflow.py` `answer_for`: when any answer has the `annexPoint` key, the point is
`wanted.lower().replace("-", "")` (so `Annex IV(2)(a)` gives `2a`) and the result is the non-empty
`answer` of every answer with `annexPoint == point`, in export order, joined by `"\n\n"` (empty string
when none). Otherwise today's suffix rule, unchanged.

Proof: run the agents suite (section 6) filtered with `-k r32`: 4 green; then the full suite: 150 passed.

### Task 6. Python: the PDF renderer (R36 PDF)

- `services/system_card_renderer/models.py`: `CoveragePoint {id, citation, covered}`,
  `CoverageAnnex {covered, total, points: List[CoveragePoint] = []}`,
  `CoverageForm {name, answered, total}`, `Coverage {annex, forms: List[CoverageForm] = [], summary}`,
  `AdditionalEntry {key, question, citation = "", answer}`, `AdditionalSection {form, entries = []}`;
  `Ontology` gains `coverage: Optional[Coverage] = None` and
  `additionalDocumentation: List[AdditionalSection] = Field(default_factory=list)`. `classification`
  stays required (the tests send it; conflict 2.15).
- `templates/system_card.html.j2`: in the Overview `dl.kv`, wrap each of the three rows in
  `{% if card.description %}` (and `target_use_case`, `target_users`); directly after
  `<h2>Ontology</h2>`, `{% if card.ontology.coverage %}<p class="coverage">{{ card.ontology.coverage.summary }}</p>{% endif %}`;
  after the risk chains, one section per `additionalDocumentation` entry: an `h3`
  "Additional documentation: {{ s.form }}" and each entry's question, citation (only when non-empty,
  in a `span.cite`) and answer. Leave everything else as it is.

Proof: `$REND)` (17 passed, including the unchanged `test_ontology_only_card.py`).

### Task 7. Python: form import (R24 to R27, R41)

Create `services/prefill/prefill/form_import.py` (imports: standard library, `docx`, `prefill` only):
- `@dataclass ImportedQuestion(text, citation, required)`, `@dataclass FormImport(format, questions, warnings)`.
- `parse_form_file(raw, filename)`: empty raw raises `DocumentUnreadable("the file is empty")`; the
  extension (lowercased, after the last dot) must be `csv`, `md`, `markdown` or `docx`, else
  `DocumentUnreadable(f"{ext or 'this file'} is not a form format this reads: csv, docx, md")`.
  Text formats decode with `prefill.documents._decode`, then strip a leading BOM (`﻿`).
- Collection yields `(text, citation, required, where)` candidates, where `where` is the 1-based line
  (CSV: the physical line in the file, header included, use `csv.reader(...).line_num`; Markdown: the
  line; .docx: the paragraph number).
- CSV (R24): delimiter `;` when the first line has `;` and no `,`, else `,`. Header when the first
  cell, stripped and lowercased, is one of `question, questions, text, question text`; header columns
  mapped by name (question / citation `citation, reference, source, clause` / required `required,
  mandatory`). No header: columns 1, 2, 3. Required true for `yes, y, true, 1, required` after strip
  and lowercase. Rows with a blank question are skipped silently.
- Markdown (R25): skip fenced blocks (between lines starting with three backticks), horizontal rules
  (`---`, `***`, and similar), HTML comments; lines starting with `#` are headings, counted. Table rows
  (`|` at both ends) are split into cells and read with the CSV header rules (the header is decided by
  the table's first row; separator rows of `-`, `:`, `|` and spaces are skipped). Every other non-blank
  line: strip a leading list marker (`-`, `*`, `+`, `1.`, `1)`) and surrounding `**`/`__` (repeat
  until stable), then the citation rule: a trailing `[...]` not immediately followed by `(` is the
  citation and is cut from the text.
- .docx (R26): open with `docx.Document(io.BytesIO(raw))` inside `try`, raising `DocumentUnreadable` on
  any error; paragraphs whose `style.name` starts with `Heading` or equals `Title` or `Subtitle` are
  skipped and counted; empty paragraphs skipped; others read with the bracket rule; tables after the
  paragraphs, row by row, with the CSV header rules.
- Limits (R27), applied to the candidates in order: collapse whitespace and trim text and citation;
  text over 2000 skipped with "Question on line <L> is longer than 2000 characters and was skipped.";
  citation over 200 cut with "The citation on line <L> was shortened to 200 characters."; duplicates
  by lowercased collapsed text keep the first. Warnings order: "Skipped N heading." / "Skipped N
  headings." first when N > 0, then the per-line warnings, then "Removed N duplicate question." /
  "... questions." when N > 0. More than 200 questions after that raises `DocumentUnreadable("This
  file has more than 200 questions; split it into smaller forms.")`.

`services/prefill/app.py`: `POST /forms/import` with `file: UploadFile = File(...)`: read; over
`MAX_BYTES` (read the module global at call time, the test monkeypatches it) gives 413;
`DocumentUnreadable` gives 422 with `str(exc)`; 200 body exactly
`{"format", "found": len(questions), "questions": [{"text", "citation", "required"}], "warnings"}`.

Proof: `$PREF tests/test_form_import.py)` all green, and
`$PREF tests/test_app.py -k TestFormImportEndpoint)` 9 green. The rest of `test_app.py` goes green in
task 8.

### Task 8. Python: prefill for a custom form (R38, R39, R40 Python)

`services/prefill/prefill/fields.py`, add (keep every existing function unchanged):
- `norm(s)`: NFKC, lowercase, then repeatedly strip leading `#`s, list markers (`-`, `*`, `•`),
  numbering (`^\d+(\.\d+)*[.)]?\s+`) and surrounding `**`/`__` until stable; remove whitespace around
  `§`; collapse whitespace; strip trailing `?`, `:`, `.` and spaces.
- `annex_sections_by_point(text)`: the same walk as `annex_sections` (same heading regex, same risk
  heading reset, same joining of both letters of a merged point), keyed by the point id (the suffix of
  the `ANNEX_FIELDS` field after the last `:`, e.g. `1de`), also returning the line index of each
  point's first heading.
- `proposals_for_questions(text, questions) -> dict[field, str]`:
  1. Naming matches. A line names Q when `norm(line)` equals `norm(Q.text)`, or `norm(Q.citation)`
     (only when that is at least 3 characters and, as a guard for R38, is not one of the 14 Annex IV
     citations: those are matched through step 2), or `norm(citation) + " " + norm(text)`; or when the
     line is `Label: value` (split at the first `:`) and `norm(Label)` names Q, in which case a
     non-blank `value` is the answer's first line. The answer runs to the next line that names any
     question, is an Annex heading (`_ANNEX_HEADING`), a markdown heading (`^#{1,6}\s`) or the risks
     heading (`RISKS_HEADING`); non-blank lines joined and cleaned with `_clean`. Two questions with the
     same normalised text both take it. A match whose answer is empty does not claim the field.
  2. Annex matches: a question with `annexPoint` p takes `annex_sections_by_point(text)[p]`.
  3. Per field, the candidate whose first line comes first in the document wins; on a tie the Annex
     match wins. Fields with nothing are absent.
- `services/prefill/app.py` `/prefill`: two new optional form fields `fields: str | None = Form(None)`
  and `questions: str | None = Form(None)`, each parsed with `_form_json(name, value, list, ...)` when
  given (422 "fields: ..." / "questions: ..."). When both are absent, the code path is exactly today's.
  Otherwise: proposals = `metadata_from_text(text)` plus
  (`proposals_for_questions(text, questions)` when `questions` is given, else `annex_sections(text)`),
  then kept only for names in `fields` when `fields` is given. Risks: when `fields` is given and has no
  `"risks"`, return `risks: None`, `risksKept: False`, `risksProposed: 0` without reading them.
- `services/prefill/README.md`: document `POST /forms/import` and the two new `/prefill` fields.

Proof: `$PREF)` 173 passed (every existing prefill test unchanged).

### Task 9. TS: the parser takes the form (R10 to R14)

`src/server/forms/QualificationFormParser.ts`:
- `parse(formData, form: ResolvedFormVersion = annexDefaultVersion())`; `ParsedQualification` gains
  `formVersionId: string`; `intendedDeployers: string | null`.
- Read every text field as a trimmed string (`this.trimmed`, so a missing field reads as `""`, which
  gives the same message as a blank one). Identity always: "System name is required", "Version is
  required", "Company is required". Each of `description`, `targetUseCase`, `targetUsers`,
  `intendedDeployers` keeps its current message when its block is in `form.blocks`; otherwise it is
  `""` (`intendedDeployers`: `null`) whatever was posted. Keep today's check order (identity and text
  fields, then target systems and sectors, then market forms and localities, then questions, then
  risks), because existing tests depend on which message comes first.
- Each picker is read and validated only when its block is included; otherwise `[]`.
- Questions: missing = required questions of `form` whose `q.field` is missing or blank; the message
  is unchanged. Answers: iterate `formData.entries()` as today (order preserved), keep a `q:` field only
  when it is the `field` of a question in `form` (a map `field -> question`), and emit
  `{ toolId: q.scope, questionId: q.localId, answer: trimmed }`.
- Risks parsed only when `"risks"` is in `form.blocks`, else `[]`.
- Update `CreateQualificationInput` in `QualificationRepository.ts`: `intendedDeployers: string | null`
  and `formVersionId: string`.

Proof: `$VT test/unit/QualificationFormParser.test.ts test/unit/prefillOnEditPage.test.ts test/unit/cardSubmission.test.ts`
(all green; the old cases pass unmodified with one argument).

### Task 10. FormRepository and FormService (R3 to R7, R16, R20, R22)

`src/server/repositories/FormRepository.ts`: class `FormRepository(db: PrismaClient = prisma)`
implementing exactly the methods documented in `test/support/fakeFormStore.ts`:
- `listForms()` `findMany`; `findForm(id)` `findUnique`;
- `findVersion(id)` / `versionsOf(formId)` with
  `include: { form: true, questions: { orderBy: { position: "asc" }, include: { question: { include: { ownerForm: true } } } } }`
  (`versionsOf` ordered by `number` ascending);
- `findQuestion(id)` with `include: { ownerForm: true }`; `questionsOwnedBy(formId)`;
- `insertVersion(plan)` in one `prisma.$transaction(async (tx) => ...)`: the form (when given), then
  `formQuestion.createMany(newQuestions)`, then the version, then
  `formVersionQuestion.createMany(snapshots with formVersionId)`; let Prisma's P2002 propagate;
- `setDefault(formId)` in one transaction: `updateMany({ where: { isDefault: true }, data: { isDefault: false } })`
  then `update({ where: { id: formId }, data: { isDefault: true } })`.
No work in the constructor (tests mock `@/lib/prisma` with partial objects).

`src/server/services/FormService.ts`: `class FormService(repository = new FormRepository(), { newId = () => randomUUID() } = {})`
and `export const formService = new FormService()`.
- private `toResolved(row)` maps a repository version row to `ResolvedFormVersion` (builtin =
  `origin === "builtin"`; `ownerFormName = question.ownerForm.name`; `ownerBuiltin` likewise;
  `blocks` via `inBlockOrder`; `key`/`field` from scope and local id).
- `resolve(id)`: null returns `annexDefaultVersion()` with no repository call; else `findVersion`
  then `toResolved`, or null.
- `latestVersion(formId)`: last of `versionsOf`, resolved, or null.
- `library()` (no parameters): listed forms, each with its latest version; sort default first, then
  builtin, then name by `toLowerCase()`; rows `{formId, name, description, origin, builtin, isDefault,
  versionId, version, questionCount}`.
- `libraryGroups()`: in library order, `{formId, formName, questions}` with the latest version's
  questions whose `ownerFormId` is that form.
- `chooserOptions()`: library rows plus `versionIds` (all version ids of the form, ascending). Used by
  the edit page only; not tested.
- `setDefault(project, formId)`: unknown or unlisted form gives
  `{ok: false, error: "That form cannot be the default."}` without calling `repository.setDefault`;
  else one `repository.setDefault(formId)` and `{ok: true}`.
- `saveDraft(draft, { formId, listed, origin = "builder" })`:
  1. Existing form (`formId` given): `findForm`; refuse when missing, builtin or unlisted (any clear
     message). Validate with `parseFormDraft({...draft, name: form.name})`. Load `versionsOf`; resolve
     the latest; when `sameContent(value, latest)` return `{ok: true, formId, versionId: latest.id,
     number: latest.number, created: false}` with no insert.
  2. New form: `parseFormDraft(draft, listed ? { takenNames: listed form names } : undefined)`;
     `formId = newId()`; `plan.form = {id, name, description, origin, listed}`.
  3. `maxN` = the largest `n` of local ids `q<n>` over `questionsOwnedBy(formId)` (0 for a new form).
  4. Per question at 1-based n: pick: `findQuestion`, missing gives "Question n no longer exists.";
     the snapshot (text, citation, required, annexPoint, groupLabel) is the most recent
     `form_version_question` of that question among `versionsOf(ownerFormId)` taken from the newest
     version down (missing gives the same "no longer exists"). Own with id: `findQuestion`; when its
     `ownerFormId` is not this form, "Question n belongs to another form: edit makes a copy."; the
     snapshot is the draft's values, `groupLabel: null`. Own without id: a new identity
     `{id: newId(), ownerFormId: formId, scope: "f-" + formId, localId: "q" + (++maxN), copiedFromId: null}`.
     Copy: the source must exist; a new identity like an own one with `copiedFromId = fromQuestionId`;
     snapshot from the draft's values.
  5. `insertVersion({form?, version: {id: newId(), formId, number: latest + 1 (1 for new), blocks:
     inBlockOrder(value.blocks)}, newQuestions, snapshots})`. On an error with `code === "P2002"`
     return `{ok: false, error: "This form was saved by someone else meanwhile. Reload it and save
     again."}` for an existing form, and "A form called <name> already exists." for a new one (the
     name index raced); rethrow anything else.
  6. Return `{ok: true, formId, versionId, number, created: true}`.

Proof: `$VT test/unit/FormService.test.ts` (30 green).

### Task 11. QualificationService stores the version (R15, R8 starting point)

- `src/server/services/QualificationService.ts`: fourth constructor parameter
  `forms: { resolve(id: string | null): Promise<ResolvedFormVersion | null> } = formService`.
  `createFromForm`: `const raw = formData.get("formVersionId")`; id = non-blank string or null;
  `form = await this.forms.resolve(id)`; null throws
  `FormValidationError("The form this was filled with no longer exists. Reload the page.")` before the
  platform is asked. `parsed = this.parser.parse(formData, form)`. `createVersion` receives the same
  four keys as today with `description: parsed.description === "" ? null : parsed.description` (no
  extra key: `cardVersionsInCoreSystem.test.ts` compares the exact object). `repo.create({...parsed,
  formVersionId: form.versionId, projectId, systemId})` (set it from `form`, not from `parsed`).
- `startingPoint()` also returns `fromFormVersionId: from ? resolveFormVersionId(from.formVersionId ?? null) : null`.
- `src/domain/cardVersions.ts`: `CardContent` gains `formVersionId?: string | null` (optional so the
  existing card fixtures still type-check); `cardAsFormStart` unchanged.
- `QualificationRepository.cardSummary`: add `formVersionId` to the select.

Proof: `$VT test/unit/QualificationService.forms.test.ts test/unit/cardSubmission.test.ts test/unit/cardVersionsInCoreSystem.test.ts`.

### Task 12. Export, ontology service, view types (R30, R37)

- `src/server/services/QualificationExporter.ts`: `toExport(q, form?)`. Without `form`, byte-for-byte
  today's result. With `form`: answers whose key is a question of the version come first in version
  position order, each `{toolId, questionId, answer, citation, annexPoint}` from the snapshot; answers
  not in the version come last, sorted by `"toolId:questionId"`, in the **legacy shape**
  `{toolId, questionId, answer}` with no `citation` and no `annexPoint` key (guard for R7, see risk 4.1);
  add `form: {name: form.formName, version: form.versionNumber, questions: [{key, text, citation,
  required, annexPoint, ownerForm: ownerFormName, ownerBuiltin}]}`. Extend the `QualificationExport`
  type with the optional keys.
- `src/server/services/OntologyService.ts`: fourth constructor parameter
  `forms: { resolve(id: string | null): Promise<ResolvedFormVersion | null> } = formService`; in
  `build` and `patchNode`, `const form = await this.forms.resolve(q.formVersionId ?? null)` and
  `toExport(q, form ?? undefined)`.
- `src/app/api/qualifications/[id]/extracted/route.ts` GET: same resolution, `toExport(q, form ?? undefined)`.
- `src/domain/OntologyView.ts`: types `Coverage`, `AdditionalSection`, and optional `form`, `coverage`,
  `additionalDocumentation` on `OntologyView`. `aiCardExport` needs no change (the R37 tests already
  pass; keep them passing).

Proof: `$VT test/unit/QualificationExporter.test.ts test/unit/aiCardExport.test.ts test/unit/engineComponents.test.ts test/unit/systemVersionOntologyRoute.test.ts`.

### Task 13. Prefill and import clients (R28 client, R38, R40 TS)

- `src/server/services/PrefillClient.ts`: `read(file, mode, current, currentRisks, formSpec?)`; only
  when `formSpec` is given, `body.set("fields", JSON.stringify(formSpec.fields))` and
  `body.set("questions", JSON.stringify(formSpec.questions))`.
- `src/lib/prefillChoice.ts`: keep `METADATA_FIELDS`, `PREFILLABLE` and every existing export as they
  are. Add `prefillableFor(form)` = identity + included blocks among the four metadata text fields +
  every question `field`; `prefillFormSpec(form)` = `{fields: [...identity, ...form.blocks,
  ...question fields] (with "risks" present exactly when the block is), questions: [{field, text,
  citation, annexPoint}]}`; `currentAnswers(form, prefillable = PREFILLABLE)`. Pure: import
  `FORM_BLOCKS`/types only, never FormService.
- `src/server/services/FormImportClient.ts`: `class FormImportClient(baseUrl = process.env.PREFILL_URL ?? "", fetchImpl = fetch)`,
  `read(file)`: no base URL gives `{ok: false, error: "Importing forms is not available on this install."}`
  with no fetch; POST `serviceUrl(base, "/forms/import")` with a FormData holding `file`; a thrown
  fetch gives "The form reader could not be reached."; a non-OK response gives its JSON `detail`, or
  `"The form file could not be read (<status>)."` when there is none; OK gives `{ok: true, format,
  found, questions, warnings}`. Never throws. `export const formImportClient = new FormImportClient()`.

Proof: `$VT test/unit/PrefillClient.test.ts test/unit/prefillChoice.test.ts test/unit/prefillOnEditPage.test.ts test/unit/FormImportClient.test.ts`.

### Task 14. Server actions (R4, R6, R22, R42)

- `src/app/p/[project]/forms/actions.ts`. The very first characters of the file must be `"use server";`
  (the test's regex anchors at the start of the file: no comment above it). Imports `formService` from
  `@/server/services/FormService`, `callerAccess` from `@/server/access/qualificationAccess`,
  `parseFormDraft`, `redirect` and `revalidatePath`.
  - `saveForm(project, draftJson, formId?, origin?)`: `JSON.parse` in try (failure returns
    `{error: "The form could not be read."}`); `parseFormDraft(input)` failure returns `{error}`;
    `formService.saveDraft(value, {formId, listed: true, origin: origin ?? "builder"})`; `!ok` returns
    `{error}`; else `redirect("/p/" + project + "/system/edit?form=" + formId)` (outside any try).
  - `useFormOnce(project, draftJson, origin?)`: same, with the name set to "Custom questions" before
    validating, `listed: false`, redirect to `?formVersion=<versionId>`.
  - `setDefaultForm(project, formId)`: `const access = await callerAccess(project)`; unless
    `access?.admin === true` return `{error: "Only an administrator can change the default form."}`
    without touching the service; `!ok` returns `{error}`; else `revalidatePath("/p/" + project + "/forms")`
    and return `{}`.
- `src/app/p/[project]/forms/import/actions.ts`: `"use server";` first; `readFormFile(formData)`: the
  `file` entry must be a non-empty `File` (else `{ok: false, error: "Choose a file first."}`); returns
  `formImportClient.read(file)`. Stores nothing.

Proof: `$VT test/unit/formActions.test.ts -t "setDefaultForm|saveForm|useFormOnce|viewer"` green
(the file-existence and edit-page tests go green in tasks 17 and 19).

### Task 15. The qualification form renders the version (R9, R29, R40 hook)

- `src/app/p/[project]/qualify/new/QualifyForm.tsx`: props gain `form?: ResolvedFormVersion`; keep
  `keyQuestions?: KeyQuestion[]` in the type but ignore it (two unchanged tests pass it). `const v =
  form ?? annexDefaultVersion()` (memoise). Render:
  - the identity inputs always (required), description / targetUseCase / targetUsers /
    intendedDeployers and the four pickers only when their block is in `v.blocks` (the pickers'
    hidden inputs disappear with them);
  - the "Technical documentation" section only when there are questions; questions in order, a
    `h3.qf-group` whenever `groupLabel ?? ownerFormName` differs from the previous question's, the
    `span.qf-citation` only for a non-empty citation, "where applicable" when not required,
    `required={q.required}`, `name`/`id`/`htmlFor` = `q.field`, `defaultValue={initial?.answers[q.field] ?? ""}`;
  - `RiskRows` only when `"risks"` is included;
  - `<input type="hidden" name="formVersionId" value={v.versionId} />` inside the form.
  For the default version the markup must stay as today (same names, order, headings, chips).
- `useDocumentPrefill(initialRisks, form?)`: `currentAnswers(data, prefillableFor(form))`; the reader
  adds `fields` and `questions` (from `prefillFormSpec(form)`) to the action's FormData **only when the
  form is not the default version** (guard, risk 4.4); `prefill-actions.ts` `readDocument` parses them
  when present (a parse failure returns its usual error) and passes `{fields, questions}` as the fifth
  argument of `prefillClient.read`.

Proof: `$VT test/unit/QualifyFormBlocks.test.tsx test/unit/formPrefill.test.tsx test/unit/formUpload.test.tsx test/unit/DocumentUpload.test.tsx test/unit/prefillOnEditPage.test.ts` (20 new green, the rest unchanged).

### Task 16. The card reads its version (R6, R7, R29, R36)

- `src/app/p/[project]/qualify/[id]/AnsweredForm.tsx`: `form?: ResolvedFormVersion` defaulting to
  `annexDefaultVersion()`. Identity rows always; other metadata and pickers only when included; groups
  by change of `groupLabel ?? ownerFormName` (keep `h2.qf-group` and the " optional" note as today);
  the citation chip in `Row` only when non-empty; "left blank" for unanswered; the risk section only
  when `risks` is included. The default version must produce byte-identical `innerHTML` to today's.
- `src/app/p/[project]/qualify/[id]/VerticalCard.tsx`: when `view.coverage`, a first element
  `<p className="qf-coverage">{summary}</p>`; the "About the system" heading and table only when
  `view.rows.length > 0`; the "Risks" heading only when `view.chains.length > 0`; after the chains,
  per `additionalDocumentation` section an `h3.qf-group` "Additional documentation: <form>" and each
  entry's question, a `span.qf-citation` only for a non-empty citation, and the answer.
- `src/app/p/[project]/qualify/[id]/page.tsx`: `const form = (await formService.resolve(q.formVersionId ?? null)) ?? annexDefaultVersion()`
  and pass it to `AnsweredForm`. Optionally show "Form: <name> v<N>" under the header.

Proof: `$VT test/unit/AnsweredForm.test.tsx test/unit/VerticalCard.test.tsx test/unit/aiCardExport.test.ts`.

### Task 17. The chooser and the edit page (R8)

- `src/app/p/[project]/system/edit/FormChooser.tsx` ("use client"): props as `02-tests.md` section 3.
  A `<fieldset>` with `<legend>Which form?</legend>`; when `previous && !previous.listed`, a first radio
  "Same form as v<cardVersionNumber>" with value `formVersion:<id>`; then one radio per option inside a
  wrapping `<label>`: name, "v<N>", "<Q> questions", a "default" tag when `isDefault`, and "same as
  v<cardVersionNumber>" when `previous?.listed` and `versionIds` includes `previous.formVersionId`.
  Checked state from `preselected` (controlled `useState`). `error` renders as its own text node. Links
  (next/link) "+ New form" to `/p/<project>/forms/new` and "Import form" to `/p/<project>/forms/import`.
  A `type="button"` "Continue" calls `router.push("/p/" + project + "/system/edit?" + param + "=" + id)`.
- `src/app/p/[project]/system/edit/page.tsx`: `searchParams` gains `form` and `formVersion`.
  - `?example=mcas`: as today, with `form = annexDefaultVersion()`, no chooser.
  - `?form=<id>`: `formService.latestVersion(id)`; `?formVersion=<id>`: `formService.resolve(id)`.
    When one of them is named and resolves to null, fall through to the chooser with
    `error = "That form was not found."`.
  - A resolved version: as today (`startingPoint` for `initial`), plus a line "Form: <name> v<N>", and
    `<QualifyForm form={version} ... />`.
  - Otherwise the chooser: `start = startingPoint()` (catch to null), `options = chooserOptions()`,
    `fromFormListed` from `resolve(start.fromFormVersionId)?.listed`, `defaultFormId` from the option
    with `isDefault`, `preselected = preselect(...)`, `previous = start.fromFormVersionId ?
    {cardVersionNumber: start.next.fromVersionNumber, formVersionId, listed} : null`, and render
    `<FormChooser .../>`. The source must contain `<FormChooser`, `<QualifyForm`, `formVersion`,
    `example` and the literal "That form was not found.".

Proof: `$VT test/unit/FormChooser.test.tsx test/unit/formChooser.test.ts test/unit/prefillOnEditPage.test.ts`.

### Task 18. The builder (R16 to R23, R29)

`src/app/p/[project]/forms/FormBuilder.tsx` ("use client"): props `project`, `library: LibraryGroup[]`,
`forms: ResolvedFormVersion[]`, `initial`. `useReducer(builderReducer, initial, initialBuilderState)`;
local UI state only for the search text, the open editor, the pending focus and the error.
- `<section aria-label="Question library">`: an input labelled "Search questions"; a select labelled
  "Start from" (options by `formId`) and an "Apply" button (when the right column has N > 0 rows,
  `window.confirm("Replace the N questions in your form?")` first); one group per
  `filterLibrary(library, search)` group with an `h3` holding only the form name, then per question a
  `label` wrapping a checkbox (`checked = isTicked`), the text, a `span.qf-citation` only for a
  non-empty citation, and the overlap chip when hinted. No other checkbox in this section.
- `<section aria-label="Your form">`: for a new form an input labelled "Form name"; for an edit the
  name as text (no input). "Always included: System name, Version, Company (provider)" as one text
  run. One checkbox per `FORM_BLOCKS` block whose accessible name is exactly `METADATA_FIELDS[id].label`
  or `RISK_BLOCK.title` (no citation chip inside that label). Rows (`draggable`, with `onDragStart` /
  `onDrop` dispatching `move`): position, text, citation chip only when non-empty, the owner form name
  for picks and copies, the overlap chip ("≈ overlaps ..." as its own element, once per row), a
  "Required"/"Optional" tag as text, buttons "Move up"/"Move down" with
  `aria-label={"Move " + text.slice(0, 40).trimEnd() + " up"}` (and `" down"`), disabled at the ends;
  after a move, focus the same button of the moved row (refs keyed by `rowKey`, focused in an effect);
  "Edit" and "Remove". Do not render a `textarea` for the form description here: the tests read the
  first `textarea` of this section as the question editor.
- "+ New question" opens the editor (one at a time): a `textarea` (`required`, `maxLength={2000}`), a
  citation input (`maxLength={200}`, placeholder "e.g. Acme AI Policy §4.2"), a checkbox labelled
  exactly "Required" (default checked), a select labelled "Answers Annex IV point" with "None" (value
  `""`) plus the 14 citations, and "Save question" (dispatches `addOwn`, or `edit` for an existing row,
  prefilled from the row, a pick keeping its source's annexPoint).
- Overlap: `overlapHints(rows as {questionId: rowId, annexPoint}, all library questions)` where a row
  without a question id uses its `rowKey`.
- Footer: `div.error` above it when set; "Save form" (new) or "Save as v<initial.edit.versionNumber + 1>"
  (edit), calling `saveForm(project, JSON.stringify(toDraft(state)), state.formId ?? undefined, state.origin)`;
  "Use once" calling `useFormOnce(project, json, state.origin)`. A returned `{error}` is shown.

Proof: `$VT test/unit/FormBuilder.test.tsx` (21 green).

### Task 19. Import UI and the remaining pages (R6 404, R17 from, R28, R42)

- `src/app/p/[project]/forms/import/FormImport.tsx` ("use client"): props `project`, `library`,
  `forms`. A file input `accept=".csv,.md,.markdown,.docx"`; on change, a FormData with `file`, then
  `readFormFile(fd)`. Failure: show the error text; stay on the upload. Success: "Found N questions in
  <filename>" as one text node, the warnings as `li`, one row per question (text input, citation input,
  checkbox labelled "Required", a "Remove" button), and "Continue with M questions" (M = rows left,
  disabled at 0). Confirm replaces the preview with `<FormBuilder>` given `initial = {name: file name
  without its last extension, origin: "import", blocks: [...FORM_BLOCKS], questions: rows as own
  {text, citation, required, annexPoint: null}}`.
- Pages (server components, each awaits `params`):
  - `src/app/p/[project]/forms/page.tsx`: the library table (name, "default" tag, "v<N>",
    "<Q> questions", origin), "Start from" (`/forms/new?from=<id>`), "Edit" (not builtin), and "Set as
    default" only when `(await callerAccess(project))?.admin`. The button is a small client component
    `src/app/p/[project]/forms/SetDefaultButton.tsx` calling `setDefaultForm` and `router.refresh()`
    (a server component cannot hold the click handler; this file is not in the spec's list, it is
    needed and stays under `forms/`, where R41's scan covers it).
  - `src/app/p/[project]/forms/new/page.tsx`: `library = await formService.libraryGroups()`, `forms`
    = the listed forms' latest versions (from `library()` rows then `resolve(versionId)`),
    `initial = from ? { startFrom: forms.find(f => f.formId === from) } : {}`.
  - `src/app/p/[project]/forms/[formId]/edit/page.tsx`: first `const v = await formService.latestVersion(formId)`;
    `if (!v || v.builtin || !v.listed) notFound();` before anything else; then the same `library`
    and `forms` as the new page (use only `library`, `libraryGroups`, `latestVersion`, `resolve`: the
    test's mock has only those), and `<FormBuilder initial={{ edit: v }} />`.
  - `src/app/p/[project]/forms/import/page.tsx`: `<FormImport project library forms />`.

Proof: `$VT test/unit/FormImport.test.tsx test/unit/formActions.test.ts test/unit/formsNoModel.test.ts` (7 + 17 + 3 green).

### Task 20. Docs (no test)

- `README.md` (app): one sentence after the "14 questions" line saying forms are data: the 14 are the
  seeded "Annex IV default" form, and an install can build or import other forms under `/p/<project>/forms`.
- `services/prefill/README.md` (done in task 8).
- Nothing else. No new markdown files.

---

## 2. Spec and test conflicts, and how this plan resolves them (tests win)

1. Parser: spec 5.2 makes the second argument required; `prefillOnEditPage.test.ts` calls
   `parse(form)`. It defaults to the default version.
2. `QualifyForm`: `form` optional, `keyQuestions` tolerated and ignored (two unchanged tests pass it).
3. `QualificationService`: the fourth `forms` dependency defaults to `formService`, and `resolve(null)`
   is answered in memory, so `cardSubmission.test.ts` and `cardVersionsInCoreSystem.test.ts` (three
   arguments) stay green.
4. R34 "14 of 14" for MCAS: the committed JSON has 13 answers (no 1(f)), so it gives 13; with the
   extra 1(f) answer, 14. No special case in the code. Open for the product owner if 14 was meant.
5. R38 against R39 on merged points: an Annex-heading match joins both letters, as `annex_sections`
   does.
6. `parseFormDraft(input, context?)`: `takenNames` added; `saveDraft` passes it for new listed forms.
7. R17: every "Start from" question is a pick.
8. `preselect` options carry `versionIds`.
9. `saveForm` fourth argument `origin`, `useFormOnce` third.
10. New, found here: `filterLibrary(groups, "?")` must return question 1a, whose text and citation hold
    no `?`. The spec's rule (substring of the lowercased, whitespace-collapsed text) cannot do that.
    Resolved: punctuation other than `§` normalises to spaces on both sides, and a query that is empty
    after that is the empty query. Every other search test gives the same result under this rule.
11. R35 entries take the citation from the form's question, not the answer (the test's expected
    `"Acme AI policy §3"` differs from the answer's `"Acme AI Policy §3"`).
12. Spec 5.2 `toExport(q, form)` required; the existing exporter tests call `toExport(q)`. Optional,
    and without it the export is exactly today's.
13. `AnsweredForm` `form` optional with the default version.
14. R10 refuses `"   "` for the identity; today's zod accepts it. The parser now trims every text field
    (a behaviour change: whitespace-only values are refused and stored values lose surrounding spaces).
15. Renderer "no classification": the tests send empty lists, so `classification` stays required.
16. Stray stored answers (keys not in the version): the spec is silent on their shape; this plan keeps
    them in the legacy shape so the graph of historic cards does not change (risk 4.1).
17. `OntologyService` forms dependency: spec says `resolve` returns a version; FormService returns null
    for an unknown id. OntologyService falls back to `toExport(q)` on null.
18. `02-tests.md` gap 10 (no test for the "Form: <name> v<N>" line, the `/forms` table, `?example=mcas`
    at run time, the Dockerfile at build time): implemented as specified, checked by reading only.

---

## 3. Migration details

File: `prisma/migrations/20260925090000_forms_are_data/migration.sql`. Rules for the whole file:
- Every name fully qualified with `qualification.` (the R7 DB test runs it through `psql` as the
  superuser after `SET search_path TO qualification`, and Prisma runs it as `qualification_rw`, owner of
  the tables it creates, so no GRANT is needed: `init/platform-db.sql` sets default privileges).
- No `BEGIN`/`COMMIT`, no `CONCURRENTLY` (the R7 DB test wraps it in a transaction).
- Every function is `CREATE OR REPLACE FUNCTION`; exactly five triggers, named as below, one function
  each. The R7 DB test reverts the migration by dropping the functions of those five triggers, the four
  tables, the new column and the new index, then runs this file again: anything else it creates would
  make the second run fail.
- No `UPDATE ... SET`, `DELETE FROM` or `TRUNCATE` of `qualification`, `qualification_answer`,
  `qualification_risk`, `knowledge_graph` or `card_component` anywhere, comments included (the unit
  test strips `--` comments but a word in a string would still count). The comment header may mention
  `annex-iv-default-v1`; the trigger for `form_builtin_is_fixed` must come after the seed.

```sql
-- Forms are data: the 14 Annex IV questions become the seeded form "Annex IV default".
-- Nothing below changes a row of qualification, qualification_answer, qualification_risk,
-- knowledge_graph or card_component. Nothing here touches knowledge_graph or qualification_risk.

-- 1. the four tables
CREATE TABLE qualification.form (
  id          text PRIMARY KEY,
  name        text NOT NULL,
  description text NOT NULL DEFAULT '',
  origin      text NOT NULL,
  listed      boolean NOT NULL DEFAULT true,
  is_default  boolean NOT NULL DEFAULT false,
  created_at  timestamptz(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT form_origin_check CHECK (origin IN ('builtin', 'builder', 'import')),
  CONSTRAINT form_default_is_listed CHECK (NOT is_default OR listed),
  CONSTRAINT form_name_length CHECK (length(btrim(name)) BETWEEN 1 AND 120)
);
CREATE UNIQUE INDEX form_one_default ON qualification.form ((true)) WHERE is_default;
CREATE UNIQUE INDEX form_listed_name_key ON qualification.form (lower(name)) WHERE listed;

CREATE TABLE qualification.form_version (
  id         text PRIMARY KEY,
  form_id    text NOT NULL,
  number     integer NOT NULL,
  blocks     text[] NOT NULL,
  created_at timestamptz(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT form_version_form_id_fkey FOREIGN KEY (form_id)
    REFERENCES qualification.form (id) ON DELETE RESTRICT,
  CONSTRAINT form_version_number_check CHECK (number >= 1),
  CONSTRAINT form_version_blocks_check CHECK (blocks <@ ARRAY['description','targetUseCase',
    'targetUsers','intendedDeployers','targetSystemTags','sectorTags','marketFormTags',
    'localityTags','risks']::text[])
);
CREATE UNIQUE INDEX form_version_form_id_number_key ON qualification.form_version (form_id, number);

CREATE TABLE qualification.form_question (
  id             text PRIMARY KEY,
  owner_form_id  text NOT NULL,
  scope          text NOT NULL,
  local_id       text NOT NULL,
  copied_from_id text NULL,
  created_at     timestamptz(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT form_question_owner_form_id_fkey FOREIGN KEY (owner_form_id)
    REFERENCES qualification.form (id) ON DELETE RESTRICT,
  CONSTRAINT form_question_copied_from_id_fkey FOREIGN KEY (copied_from_id)
    REFERENCES qualification.form_question (id) ON DELETE RESTRICT,
  CONSTRAINT form_question_scope_check CHECK (scope ~ '^[a-z0-9-]+$'),
  CONSTRAINT form_question_local_id_check CHECK (local_id ~ '^[a-z0-9]+$')
);
CREATE UNIQUE INDEX form_question_scope_local_id_key ON qualification.form_question (scope, local_id);

CREATE TABLE qualification.form_version_question (
  form_version_id text NOT NULL,
  question_id     text NOT NULL,
  position        integer NOT NULL,
  text            text NOT NULL,
  citation        text NOT NULL DEFAULT '',
  required        boolean NOT NULL,
  annex_point     text NULL,
  group_label     text NULL,
  CONSTRAINT form_version_question_pkey PRIMARY KEY (form_version_id, question_id),
  CONSTRAINT form_version_question_form_version_id_fkey FOREIGN KEY (form_version_id)
    REFERENCES qualification.form_version (id) ON DELETE RESTRICT,
  CONSTRAINT form_version_question_question_id_fkey FOREIGN KEY (question_id)
    REFERENCES qualification.form_question (id) ON DELETE RESTRICT,
  CONSTRAINT form_version_question_position_check CHECK (position >= 0),
  CONSTRAINT form_version_question_text_check CHECK (length(btrim(text)) BETWEEN 1 AND 2000),
  CONSTRAINT form_version_question_citation_check CHECK (length(citation) <= 200),
  CONSTRAINT form_version_question_annex_point_check CHECK (annex_point IS NULL OR annex_point IN
    ('1a','1b','1c','1de','1f','1gh','2a','2b','2c','2d','2e','2f','2g','2h'))
);
CREATE UNIQUE INDEX form_version_question_form_version_id_position_key
  ON qualification.form_version_question (form_version_id, position);

-- 2. the seed: literal VALUES rows (test/unit/annexDefaultForm.test.ts parses them)
INSERT INTO qualification.form (id, name, description, origin, listed, is_default) VALUES
  ('annex-iv-default', 'Annex IV default', 'EU AI Act Annex IV points 1 and 2, as 14 questions.',
   'builtin', true, true);
INSERT INTO qualification.form_version (id, form_id, number, blocks) VALUES
  ('annex-iv-default-v1', 'annex-iv-default', 1, ARRAY['description','targetUseCase','targetUsers',
   'intendedDeployers','targetSystemTags','sectorTags','marketFormTags','localityTags','risks']::text[]);
INSERT INTO qualification.form_question (id, owner_form_id, scope, local_id) VALUES
  ('annex-iv-1a', 'annex-iv-default', 'annex-1', '1a'),
  -- ... one row per KEY_QUESTIONS entry, 14 in all
  ('annex-iv-2h', 'annex-iv-default', 'annex-2', '2h');
INSERT INTO qualification.form_version_question
  (form_version_id, question_id, position, text, citation, required, annex_point, group_label) VALUES
  ('annex-iv-default-v1', 'annex-iv-1a', 0, '<KEY_QUESTIONS[0].text, quotes doubled>',
   'Annex IV(1)(a)', true, '1a', 'About the system'),
  -- ... positions 0 to 13 in KEY_QUESTIONS order; required = NOT optional (1b, 1f, 2d, 2f are false)
  ('annex-iv-default-v1', 'annex-iv-2h', 13, '<...>', 'Annex IV(2)(h)', true, '2h', 'How the system was built');
```
Generate the 28 seed rows from `src/data/keyQuestions.ts` with a throwaway script in your scratchpad
(never committed, never in the repo), doubling every `'`. Paste the output; the two R1 migration tests
and the DB R1 test prove it field by field. The texts contain `;` and `,`: that is fine inside string
literals for Prisma, psql and the test's parser.

```sql
-- 3. the card records its form version; NULL means annex-iv-default-v1 (no backfill)
ALTER TABLE qualification.qualification
  ADD COLUMN form_version_id text NULL
  CONSTRAINT qualification_form_version_id_fkey REFERENCES qualification.form_version (id) ON DELETE RESTRICT;
CREATE INDEX qualification_form_version_id_idx ON qualification.qualification (form_version_id);

-- 4. answers are keyed by (scope, local id) within a card
DROP INDEX qualification."QualificationAnswer_qualificationId_questionId_key";
CREATE UNIQUE INDEX qualification_answer_qualification_id_tool_id_question_id_key
  ON qualification.qualification_answer ("qualificationId", "toolId", "questionId");

-- 5. immutability, created after the seed
CREATE OR REPLACE FUNCTION qualification.form_version_is_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'form version % is immutable: save a new version instead', OLD.id;
END $$;
CREATE TRIGGER form_version_is_append_only BEFORE UPDATE OR DELETE ON qualification.form_version
  FOR EACH ROW EXECUTE FUNCTION qualification.form_version_is_append_only();

CREATE OR REPLACE FUNCTION qualification.form_version_question_is_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'form version % is immutable: save a new version instead', OLD.form_version_id;
END $$;
CREATE TRIGGER form_version_question_is_append_only
  BEFORE UPDATE OR DELETE ON qualification.form_version_question
  FOR EACH ROW EXECUTE FUNCTION qualification.form_version_question_is_append_only();

CREATE OR REPLACE FUNCTION qualification.form_question_identity_is_fixed() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'form question % cannot be deleted: versions refer to it', OLD.id;
  END IF;
  IF NEW.scope IS DISTINCT FROM OLD.scope OR NEW.local_id IS DISTINCT FROM OLD.local_id
     OR NEW.owner_form_id IS DISTINCT FROM OLD.owner_form_id
     OR NEW.copied_from_id IS DISTINCT FROM OLD.copied_from_id THEN
    RAISE EXCEPTION 'form question % keeps its identity: scope, local id, owner and source are fixed', OLD.id;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER form_question_identity_is_fixed BEFORE UPDATE OR DELETE ON qualification.form_question
  FOR EACH ROW EXECUTE FUNCTION qualification.form_question_identity_is_fixed();

CREATE OR REPLACE FUNCTION qualification.form_name_is_fixed() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.name IS DISTINCT FROM OLD.name OR NEW.origin IS DISTINCT FROM OLD.origin
     OR NEW.listed IS DISTINCT FROM OLD.listed THEN
    RAISE EXCEPTION 'form % keeps its name, origin and listing: only its description and default flag change', OLD.id;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER form_name_is_fixed BEFORE UPDATE ON qualification.form
  FOR EACH ROW EXECUTE FUNCTION qualification.form_name_is_fixed();

CREATE OR REPLACE FUNCTION qualification.form_builtin_is_fixed() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM qualification.form f WHERE f.id = NEW.form_id AND f.origin = 'builtin')
     AND EXISTS (SELECT 1 FROM qualification.form_version v WHERE v.form_id = NEW.form_id) THEN
    RAISE EXCEPTION 'form % is builtin: it has one version, made by a migration', NEW.form_id;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER form_builtin_is_fixed BEFORE INSERT ON qualification.form_version
  FOR EACH ROW EXECUTE FUNCTION qualification.form_builtin_is_fixed();
```

How it coexists with the existing triggers:
- `qualification_only_latest_changes` (BEFORE UPDATE on `qualification`) does not fire on
  `ALTER TABLE ... ADD COLUMN`, and the app writes `form_version_id` only on INSERT (a new card), so it
  never meets that trigger. The DB test that sets `formVersionId` updates the latest card, which the
  trigger allows.
- `qualification_answer_only_latest_changes` (BEFORE INSERT OR UPDATE on answers) is untouched;
  swapping a unique index does not fire row triggers.
- Project and version deletion still cascade to cards: the new FK points from `qualification` to
  `form_version`, so RESTRICT only stops deleting a used version, never deleting a card.
- Nothing here touches `knowledge_graph`, `qualification_risk` or `card_component` (frozen, spec 1.3).
- The Prisma models and this SQL differ in details Prisma does not model (checks, partial indexes,
  triggers). That drift is accepted, as for the earlier hand-written migrations. Never run
  `prisma migrate dev`, `db push` or `migrate reset`.

---

## 4. Risks and traps, and how each is guarded

1. **Graph digest of existing cards (R7).** OntologyService now passes the default version for legacy
   cards, so their export gains `citation`, `annexPoint` and `form`. Guards: seeded answers get no new
   triple (the extra properties are only for scopes other than `annex-1`/`annex-2`); their
   `qual:citation` is `annex_citation(id)`, which R2 proves equal to the legacy value; stray stored
   answers (retired ids such as `data:data-source` may exist on the live DB) keep the legacy export
   shape, so they stay in the graph as today; answer order does not matter to the digest. Proof:
   `test_form_answers.py::test_r7_*`, the unchanged `test_example_mcas.py`, and the stored
   `knowledge_graph` rows are rewritten only when the digest changes (`KnowledgeGraphStore.save`).
2. **Visible change on old cards.** Every legacy card now shows the coverage line (for MCAS as stored,
   "Annex IV coverage: 13 of 14 points.") in the card, the JSON export and the PDF. That is the spec's
   intent (R34, R37); `ai-card.json` only gains keys. Mention it in the final report.
3. **The ontology service's required fields.** `description`, `targetUseCase`, `targetUsers` default
   to `""`; `build_graph` reads with `.get`. `form` must be declared on the pydantic model or pydantic
   drops it without error: `test_coverage.py::test_r35_a_policy_only_card_through_the_service` fails if
   it is missing.
4. **Prefill of the default form (R38).** `proposals_for_questions` matches `annex_sections` on the
   tested documents only. Guards: the hook sends no `fields`/`questions` for the default version, so the
   server runs today's path exactly; Annex citations never name a question on their own (a line like
   `Annex IV(1)(a): ...` would otherwise propose where the legacy reader does not).
5. **Parser order and exact platform arguments.** Keep today's validation order (the old parser tests
   depend on which message comes first) and pass `createVersion` exactly its four keys.
6. **`"use server"` must be the first characters** of both action files (test regex anchored at the
   start of the file).
7. **Builder markup traps.** Block checkbox names must equal the labels exactly (no chip inside the
   label); one "Required" checkbox in the right column; no other `textarea` in the right column; the
   overlap chip exactly once per row; `aria-label`s built from `text.slice(0, 40)`.
8. **The edit page test mock** has only `saveDraft`, `setDefault`, `library`, `libraryGroups`,
   `latestVersion`, `resolve`: the page calls `notFound()` before anything else and uses only those.
9. **Unit tests import services that import Prisma.** `FormRepository` and `FormService` do nothing in
   their constructors; `resolve(null)` never touches the repository (the three-argument
   `QualificationService` tests post no `formVersionId`).
10. **Stale Prisma client.** Run `npx prisma generate` after the schema change, or the typecheck fails
    and the DB tests fail on `formVersionId`.
11. **Migration re-run in the R7 DB test.** Fully qualified names, `CREATE OR REPLACE FUNCTION`, exactly
    the five named triggers, no transaction statements (section 3).
12. **Python environment.** Root-owned `__pycache__` and `application.log`: always
    `PYTHONPYCACHEPREFIX=$P/pyc`, `-p no:cacheprovider`, agents from `$P/agents-cwd`. Never `sudo`,
    never `chown`/`rm` those files.
13. **The chooser changes a flow.** "Edit the AI system" (`/system/edit` with no parameter) now shows
    the chooser first; `?example=mcas` still skips it. Intended (R8); mention it in the final report.
14. **Concurrent session.** Another session may be committing to this branch. Touch only the files this
    plan names; before each proof run, `git -C apps/qualification status --short` and leave any file you
    did not create or edit alone.

---

## 5. Things the implementer must NOT do

- No `prisma migrate deploy|dev|reset`, `db push` or any SQL against a running database. Ports 5432 and
  5433 are the live stack and off limits. The only database allowed is the throwaway one that
  `test/db/throwaway-db.sh` starts on a random port and removes.
- No docker use other than that script. No `docker compose`, no image builds, no edits to compose
  files. The only Dockerfile edit is the one `COPY` line in `services/ontology/Dockerfile`.
- No commits, no pushes, no branch switches, in either repository.
- Never `git add -A`, `git add .`, `git stash`, `git checkout .`, `git checkout -- <path>`,
  `git restore`, `git reset` or `git clean`: another session may be working on this branch, and these
  touch its files.
- Do not weaken, skip, delete or edit any test, fixture or test-support file (`test/**`,
  `services/*/tests/**`). If a test looks wrong, stop and report it with the reason.
- Do not change the frozen things: `src/data/keyQuestions.ts`, `src/data/prefillFields.json`,
  `src/data/airo_vocab.json`, `airo.ttl`/`vair.ttl`, `src/middleware.ts`, `scripts/*.mjs`, and the
  `knowledge_graph`, `qualification_risk`, `card_component` tables.
- Do not fix the three pre-existing ontology failures (6.4); they are unrelated.
- No new dependency (no drag-and-drop library, A6), no model call (R41), no new markdown files other
  than what section 1 lists.
- No em dashes in any prose you write (user rule).

---

## 6. Full verification

Run from `apps/qualification`, with `P` your scratchpad.

### 6.1 TypeScript
```bash
npx vitest run
npx tsc --noEmit
npx prisma validate
```
Expected: Test Files 63 passed, 4 skipped (67). Tests: 0 failed, about 681 passed (431 today plus the
92 red plus the 158 declared in the 11 files that fail at import today), 34 skipped (20 existing DB
tests and 14 new ones, skipped without the DB variables). `tsc`: 0 errors anywhere, tests included.

### 6.2 Python
```bash
(cd services/ontology && PYTHONPYCACHEPREFIX=$P/pyc $P/venv-ontology/bin/python -m pytest -p no:cacheprovider)
(cd services/prefill && PYTHONPYCACHEPREFIX=$P/pyc .venv/bin/python -m pytest -p no:cacheprovider)
(cd services/system_card_renderer && PYTHONPYCACHEPREFIX=$P/pyc $P/venv-renderer/bin/python -m pytest -p no:cacheprovider)
mkdir -p $P/agents-cwd && (cd $P/agents-cwd && PYTHONPYCACHEPREFIX=$P/pyc $P/venv-agents/bin/python -m pytest -p no:cacheprovider \
  -c "$OLDPWD/services/agents/pytest.ini" --rootdir "$OLDPWD/services/agents" "$OLDPWD/services/agents/tests")
```
(If `$OLDPWD` is not what you expect, use the absolute app path
`/home/listuser/aisc-install/apps/qualification`.)

Expected: ontology 224 passed, 3 failed (6.4); prefill 173 passed; renderer 17 passed; agents 150 passed.

### 6.3 DB-gated tests (throwaway database only)
```bash
npx prisma generate
test/db/throwaway-db.sh
```
The script starts `postgres:14-alpine` on a random localhost port (it refuses 5432, and
`forms.db.test.ts` refuses 5432 and 5433), applies `init/*.sql`, the platform migrations and every
Prisma migration including the new one, runs `npx vitest run test/db` and removes the container.
Expected: 3 files, 34 passed (20 existing, 14 new), 0 failed. If docker is not available, say so in
the report and do not try another way to reach a database.

### 6.4 Known, unrelated failures (leave them)
`services/ontology`: `test_build.py::test_a_full_qualification_exercises_all_nineteen_properties`,
`test_example_mcas.py::test_it_exercises_all_nineteen_properties`,
`test_roundtrip.py::test_the_rebuilt_graph_keeps_every_airo_relation` (they expect engine-component
properties the example does not have). They failed before any of this work.

### 6.5 Final checks by reading
- `git -C apps/qualification status --short` lists only files this plan names (plus none deleted).
- `git -C apps/qualification diff --stat -- test services/*/tests` is unchanged from the start (the
  test writer's 889 insertions, 0 deletions).
- The migration has no `UPDATE ... SET`/`DELETE FROM`/`TRUNCATE` of the five history tables.
