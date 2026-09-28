# Form assembly: implementation plan, round 2 (stage 8)

Date: 2026-09-25. Inputs: `06-spec-addendum.md` (R43 to R73, B1 to B10), `07-tests-round2.md` (test map,
interface names, gaps), the round 2 tests themselves, and for context `01-spec.md`, `03-plan.md`,
`04-progress.md`, `05-verification.md`. Code: `apps/qualification`, branch `feat/unified-modules`, with the
uncommitted round 1 code and the round 2 tests in the working tree.

The tests are the contract. Where the addendum and the tests disagree, this plan follows the tests (section 2).
This plan contains no code. The SQL in section 3 is given verbatim because the addendum fixes it.

Short names used everywhere below:

```bash
A=/home/listuser/aisc-install/apps/qualification
P=/tmp/claude-1001/-home-listuser/572e79f5-831d-4f75-909f-47cb45306c7a/scratchpad   # holds the venvs; use this exact path
VT="cd $A && npx vitest run"
PREF="cd $A/services/prefill && PYTHONPYCACHEPREFIX=$P/pyc .venv/bin/python -m pytest -p no:cacheprovider"   # pytest.ini already has -q: never add -q
ONTO="cd $A/services/ontology && PYTHONPYCACHEPREFIX=$P/pyc $P/venv-ontology/bin/python -m pytest -p no:cacheprovider -q"
REND="cd $A/services/system_card_renderer && PYTHONPYCACHEPREFIX=$P/pyc $P/venv-system_card_renderer/bin/python -m pytest -p no:cacheprovider -q"
AGENTS="cd $P/agents-cwd && PYTHONPYCACHEPREFIX=$P/pyc $P/venv-agents/bin/python -m pytest -p no:cacheprovider -q -c $A/services/agents/pytest.ini --rootdir $A/services/agents $A/services/agents/tests"
```

Run each as `bash -c "$VT <files>"` or paste the expanded line. `$P/r2-run-all.sh <tag>` runs the five non-DB
suites and prints one summary line each (logs in `$P/r2-logs/`).

vitest filters by substring, case-insensitively: `test/unit/formChooser.test.ts` also selects
`test/unit/FormChooser.test.tsx`. That is expected, not a regression.

---

## 1. Task list (ordered by dependency)

Every task ends with commands whose output proves it. "Green" means every test the command selects passes.
Per-file totals (from the 2026-09-25 red run, re-measured by the planner the same day) are given so a partial
pass is visible.

### Task 0. Fresh baseline and the e9d0693 check (no code)

1. `git -C $A branch --show-current` prints `feat/unified-modules`. If not, stop and ask.
2. `git -C $A log --oneline -3` and note HEAD. It was `e9d0693` when this plan was written. If HEAD moved, run
   `git -C $A show --stat HEAD` for each new commit and check its paths against section 5 (file list). Any
   overlap with a file this plan edits: stop and report before editing that file.
3. Test-file fingerprint, so the end of the run can prove no test changed (many test files are untracked, so
   `git diff` cannot):
   `cd $A && find test services/*/tests -type f -not -path '*/__pycache__/*' -print0 | sort -z | xargs -0 sha256sum > $P/r2-impl-tests.sha`
4. Baseline: `bash $P/r2-run-all.sh r2impl-before`. Expected (measured by the planner on 2026-09-25 against
   HEAD `e9d0693` plus the working tree, identical to `07-tests-round2.md` section 6 "After"):

| Suite | Expected |
|---|---|
| vitest | Test Files 22 failed, 52 passed, 4 skipped (78); Tests 164 failed, 712 passed, 38 skipped (914) |
| ontology | 24 failed, 219 passed |
| prefill | 99 failed, 184 passed (about 30 s: every failing test re-raises an ImportError) |
| renderer | 2 failed, 33 passed |
| agents | 152 passed |
| `cd $A && npx tsc --noEmit` | 44 errors, all in `test/unit/` (FormService 16, formDraft 14, formChooser 12, formLibrary 1, QualificationExporter 1) |

   A different number means the tree moved: diff `$P/r2-logs/r2impl-before-*.log` against
   `$P/r2-logs/planner-*.log` (the planner's run) before going on.
5. e9d0693 interaction, checked by the planner and to be re-confirmed by reading only:
   - The commit touched `services/agents/{agent.py,service.py,tests/test_project_llm.py}`,
     `src/app/api/qualifications/[id]/extracted/route.ts`, `src/app/p/[project]/qualify/new/actions.ts`,
     `src/server/services/FillerClient.ts`, deleted `test/unit/FillerTrigger.test.ts` and the S3.8 block of
     `test/unit/cardVersionsInCoreSystem.test.ts`, and added `test/unit/fillerReadsItsProject.test.ts`.
   - Only `extracted/route.ts` is also round 1 work: the working tree adds `formService.resolve(...)` and
     `toExport(q, form ?? undefined)` on top of the commit's `projectId: project`
     (`git -C $A diff -- 'src/app/api/qualifications/[id]/extracted/route.ts'`). Round 2 does not edit this
     file. R69 changes what `toExport` puts in `form.questions[]` (adds `ownerFormId`), which the route only
     spreads; `fillerReadsItsProject.test.ts` mocks both `toExport` and `formService`, so it is unaffected.
   - Round 2 edits none of the other files of the commit. `QualificationService.createFromForm` still returns
     `{id, projectId}`; the commit's action only reads `id`. Nothing to do.
   - The round 2 red run (`$P/r2-logs/before-vitest.log`, 09:23) already postdates the commit (09:03), which is
     why the counts above reproduce exactly.
6. `docker ps -a --format '{{.Names}}' | grep aisc-t-qual-` must be empty before the DB task (task 14). Leave
   any other session's containers alone.

Proof: the table in step 4 reproduced; the fingerprint file exists.

### Task 1. Prefill: the 14 point ids and the .docx expansion cap (R53 ids, R70)

Files:
- `services/prefill/prefill/fields.py`: add `ANNEX_POINT_IDS: tuple[str, ...]`, built once at import from
  `ANNEX_FIELDS.values()` through the existing `_point_of`, deduplicated, first appearance order. (Planner
  check: this gives `1a 1b 1c 1de 1f 1gh 2a ... 2h`, the order of `src/data/annexPoints.json`.) No other change.
- `services/prefill/prefill/documents.py`: add
  `check_docx_expansion(raw: bytes) -> None` and a module constant `DEFAULT_MAX_UNZIPPED_BYTES = 52428800`.
  - The limit is read at call time: `PREFILL_MAX_UNZIPPED_BYTES` from `os.environ`, as an int; a missing,
    non-integer or non-positive value means the default (a choice the tests leave open; say it in the
    docstring).
  - `zipfile.ZipFile(io.BytesIO(raw))`; `zipfile.BadZipFile` (and any other exception opening it) becomes
    `DocumentUnreadable(f"this .docx could not be read: {exc}")`.
  - Sum of `ZipInfo.file_size` over `infolist()`; strictly greater than the limit raises
    `DocumentUnreadable(f"this .docx expands to more than {limit} bytes when unpacked; remove embedded media or split it")`.
    Exactly the limit passes. Returns `None`.
  - Call it as the first statement of `documents._from_docx`, before `docx.Document`.
- `services/prefill/prefill/form_import.py`: call `check_docx_expansion(raw)` as the first statement of
  `_from_docx`, before the `import docx` / `docx.Document` call. Keep calling `docx.Document` through the
  module attribute (`docx.Document(...)`), because the tests monkeypatch `docx.Document` to prove the order.

Proof:
```bash
$PREF tests/test_fields.py tests/test_documents.py                       # 18 + 15, all green
$PREF tests/test_form_import.py -k TestDocxExpansion                     # 4 green
```

### Task 2. Prefill: the importer reads what the exporter writes (R53, the Python half of R59)

File: `services/prefill/prefill/form_import.py` only. Every existing R24 to R27 rule stays.

- `ImportedQuestion` gains a fourth dataclass field `annex_point: str | None = None` (after `required`).
- `Candidate` becomes `(text, citation, required, annex_raw, line)`, with `annex_raw: str | None`: `None` for a
  paragraph, list line or table without an Annex column; the raw cell text otherwise. Update the three
  producers (`_table_rows`, the Markdown line path, the .docx paragraph path) and `_limited`.
- Header rules in `_table_rows`: add `_ANNEX_HEADERS = {"annex_point", "annex point", "annex iv point", "annex"}`
  matched like the other names (the header cells are already stripped and lowercased). Only a header row gives
  an Annex column; the no-header branch keeps `q_col, c_col, r_col = 0, 1, 2` and has no Annex column.
- CSV formula guard, CSV only: `_table_rows` takes a keyword `unguard: bool = False`; `_from_csv` passes `True`.
  When set, the question cell and the citation cell each lose their first character when that character is `'`
  and the rest of the cell is something the exporter would have guarded: the rest starts with one of `= + - @`,
  or the rest starts with `'` followed by one of `= + - @`. This is the exact inverse of R50's guard (section 2,
  conflict 1): `'=x` gives `=x`, `''=x` gives `'=x`, `'quoted'` and `'plain` stay. Apply it to the raw cell,
  before `_collapse`. Markdown tables and .docx tables call `_table_rows` without it.
- Markdown table cells: replace `line[1:-1].split("|")` with a small splitter `_md_cells(inner: str) -> list[str]`
  that walks left to right: `\\` appends one `\`, `\|` appends one `|`, any other `\` is kept as is, a bare `|`
  ends the cell. The leading and trailing `|` of the line are removed first, as today; the table-line test
  (`startswith("|") and endswith("|")`) and the separator regex stay as they are. Cells are then stripped, as
  today.
- `_limited`: per kept candidate, in the existing order (collapse, skip empty, length rule with its warning,
  duplicate rule, citation cut with its warning), then the Annex value: `None` stays `None`; otherwise
  `v = annex_raw.strip()`; empty is `None`; `v.lower()` in `ANNEX_POINT_IDS` (import it from `prefill.fields`)
  is that id; anything else is `None` plus the warning
  `f'The Annex IV point on line {line} ("{v}") is not one of the 14 and was left blank.'` appended at that point,
  so it sits in line order with the other per-line warnings. Skipped and duplicate rows are never checked.
- `services/prefill/app.py` `/forms/import`: each question becomes
  `{"text", "citation", "required", "annexPoint": q.annex_point}`.
- The module docstring gains two lines: the Annex column, the CSV guard and the Markdown escapes.

Proof:
```bash
$PREF tests/test_form_import.py                                          # 89 green
$PREF tests/test_app.py -k "TestFormImportEndpoint or TestFormImportAnnexPoint or test_r27"
```

### Task 3. Prefill: the exporter (R50, R51, R52, R54, the Python half of R73)

New file `services/prefill/prefill/form_export.py`. Imports: standard library only (`csv`, `io`, `re`,
`unicodedata`, `dataclasses`), plus `from __future__ import annotations` if wanted. No `prefill` import is
needed. A `test_r73_*` AST scan enforces this.

- `@dataclass class ExportedFile: filename: str; content_type: str; content: str` (fields in that order).
- `collapse(s: str) -> str` = `" ".join(s.split())`.
- `slug(name: str) -> str`: NFKD, drop `unicodedata.combining` characters, lowercase, every run of characters
  outside `[a-z0-9]` becomes one `-`, strip `-` at both ends, cut to 60, strip trailing `-` again, empty is
  `"form"`.
- `_guard(cell)`: when the first character is one of `= + - @`, or the first is `'` and the second is one of
  those four, prefix one `'`. Applied after `collapse`, to text and citation only.
- `_md_escape(cell)`: `\` becomes `\\` first, then `|` becomes `\|`.
- `export_form(form: dict, fmt: str) -> ExportedFile`, pure:
  - `fmt == "csv"`: `csv.writer(io.StringIO())` with the default dialect; header row
    `question, citation, required, annex_point`; one row per question in list order:
    `_guard(collapse(text))`, `_guard(collapse(citation))`, `"yes"`/`"no"`, the point id or `""`. Content is
    `"﻿" + buffer.getvalue()`. `content_type = "text/csv; charset=utf-8"`.
  - `fmt == "md"`: lines `# <collapse(name)> (v<version>)`, `""`, the exact R51 HTML comment, `""`, the header
    `| Question | Citation | Required | Annex IV point |`, `|---|---|---|---|`, then per question
    `"| " + " | ".join(escaped cells) + " |"` with cells collapse(text), collapse(citation), yes/no, point or
    empty. Joined with `\n`, plus one final `\n`. `content_type = "text/markdown; charset=utf-8"`.
  - `filename = f"{slug(form['name'])}-v{form['version']}.{fmt}"`.
  - Any other `fmt` raises `ValueError("format must be csv or md")` (the endpoint checks first; this keeps the
    function total).

A reference the test writer used for the achievability check exists at `$P/r2ref/form_export.py` (and
`form_import.py`, `documents.py`). It is scratch, not authoritative: write the repository code from this plan
and the tests.

Proof:
```bash
$PREF tests/test_form_export.py                                          # 45 green (incl. the 10 round trips)
```

### Task 4. Prefill: POST /forms/export and the 422s (R55, R70 on both endpoints)

File: `services/prefill/app.py`.
- Pydantic v2 models (pydantic 2.10.3 in the venv): `ExportQuestion(text: str, citation: str, required: bool, annexPoint: Optional[str])`
  (all four required, no defaults: a missing `annexPoint` is pydantic's 422), `ExportForm(name: str,
  version: int = Field(ge=1), questions: list[ExportQuestion])`, `ExportRequest(format: str, form: ExportForm)`.
  `format` must be a plain `str`, not a `Literal`, so that `"pdf"` reaches the handler's own message. Lax mode
  already refuses `text: 1` (int is not coerced to str in v2) and `version: "three"`.
- `@app.post("/forms/export")`, in this order: `format` not exactly `"csv"` or `"md"` (case-sensitive, `""`
  included) gives `HTTPException(422, "format must be csv or md")`; more than 200 questions gives
  `HTTPException(422, "a form has at most 200 questions")`; the first question (1-based n) whose `annexPoint`
  is not `None` and not in `ANNEX_POINT_IDS` gives `HTTPException(422, f"question {n} names an Annex IV point that does not exist")`.
  Then `export_form(req.form.model_dump(), req.format)` and return
  `{"filename": out.filename, "contentType": out.content_type, "content": out.content}`. Reads no file, writes
  nothing, calls no model.
- `/prefill` and `/forms/import` already turn `DocumentUnreadable` into 422 with `str(exc)`: nothing to add for
  R70 beyond task 1.

Proof:
```bash
$PREF tests/test_app.py                                                  # 56 green
$PREF                                                                    # prefill: 283 passed, 0 failed
```

### Task 5. The MCAS example answers 1(f) (R72)

Files (data and docs only, no code):
- `services/ontology/examples/mcas.qualification.json`: insert one object right after the `1de` answer,
  `{"toolId": "annex-1", "questionId": "1f", "answer": <text>}`, where `<text>` is exactly the value of
  `"q:annex-1:1f"` in `src/data/examples/mcas.ts` (line 41; 299 characters). Nothing else changes. Planner
  check: re-serialising the file with Python's `json.dumps(data, indent=2, ensure_ascii=False) + "\n"` changes
  only the inserted lines, so either a hand edit with the same two-space layout or that re-serialisation is
  fine. Verify with `git -C $A diff --stat -- services/ontology/examples/mcas.qualification.json` (5 lines added).
- Regenerate both graph files, from `services/ontology`, with the venv:
  ```bash
  cd $A/services/ontology && PYTHONPYCACHEPREFIX=$P/pyc $P/venv-ontology/bin/python -m airo_min.build examples/mcas.qualification.json --extracted examples/mcas.extracted.json --format turtle --out examples/mcas.ttl
  cd $A/services/ontology && PYTHONPYCACHEPREFIX=$P/pyc $P/venv-ontology/bin/python -m airo_min.build examples/mcas.qualification.json --extracted examples/mcas.extracted.json --format json-ld --out examples/mcas.jsonld
  ```
  Each prints `413 triples -> ...`. The Turtle diff also reorders blank nodes (rdflib's serialisation is not
  stable): expected, the tests compare graphs, not text.
- `services/ontology/README.md` examples table: "13 Annex IV answers" becomes "14 Annex IV answers", "295
  triples" becomes "413 triples". Nothing else.
- Unchanged on purpose: `src/data/examples/mcas.ts`, `scripts/seed_mcas.mjs` (both already answer 1f).

Proof:
```bash
$ONTO tests/test_example_mcas.py tests/test_roundtrip.py    # only failures: the 2 pre-existing ones of 03-plan 6.4
bash -c "$VT test/unit/mcasExampleAgrees.test.ts"          # 5 green
```
Planner dry run (in a scratch copy): with this data change alone the whole ontology suite had 16 failures, all
of them either the 3 pre-existing ones or `test_coverage.py` tests that need task 6. No other MCAS-based test
(`test_view`, `test_app` rows 10, `test_graph` digests) moved.

### Task 6. Coverage names optional points left blank and groups by owner id (R65, R66 Python side, R69 Python side)

Files:
- `services/ontology/airo_min/coverage.py`:
  - `_owners_in_order(questions) -> list[tuple[key, name]]`: the group key is `("id", q["ownerFormId"])` when
    the question has an `ownerFormId` key, else `("name", q["ownerForm"])`; order of each group's first question;
    the name shown is the first question's `ownerForm`. A private `_owner_key(q)` gives the same key, and both
    `coverage` and `additional_documentation` filter "mine" by key, not by name.
  - Optional left blank: `optional_blank` = the number of points p (in `ANNEX_POINTS`) that are not covered,
    that some question of the version has `annexPoint == p`, and none of those questions is `required`.
  - `annex` gains `"optionalBlank": optional_blank`; `points` keep `{id, citation, covered}`.
  - `summary`: `f"Annex IV coverage: {covered} of 14 points"`, then `f" ({b} optional left blank)"` only when
    `b > 0`, then the per-form parts as today, then `"."`. "optional" never takes a plural.
  - The module docstring's `form` shape gains `ownerFormId` (optional).
- `services/ontology/airo_min/view.py`, `app.py`: no change (`build_view` passes `coverage()` through).
- `services/system_card_renderer/models.py`: `CoverageAnnex.optionalBlank: int = 0`. The template already
  prints `coverage.summary`; no template change.

Proof:
```bash
$ONTO tests/test_coverage.py                               # 27 green
$ONTO                                                      # ontology: 240 passed, 3 failed (the 3 of 03-plan 6.4)
$REND                                                      # renderer: 35 passed
```

### Task 7. The forward migration and the Prisma schema (R45 text half, the schema parts of R44 and R47)

Files:
- New `prisma/migrations/20260925120000_the_default_form_is_fixed/migration.sql`, exactly section 3.1.
- `prisma/migrations/20260925090000_forms_are_data/migration.sql`: **not touched** (its sha256
  `cbea212d...147557` is pinned; planner re-checked it matches today).
- `prisma/schema.prisma`, `model Form`: delete the `isDefault ... @map("is_default")` line and any comment that
  mentions the default flag; put this exact line directly above `model Form {`:
  `/// The default form is always id "annex-iv-default" (DEFAULT_FORM_ID in src/domain/forms/legacy.ts). There is no default flag.`
  The file must then contain neither `is_default` nor an `isDefault` field anywhere. Nothing else changes.
- Then `cd $A && npx prisma generate` (writes only `node_modules/.prisma`). Mandatory: without it the Prisma
  client still selects `is_default`, and every DB test that reads `qualification.form` through Prisma fails on
  the migrated throwaway DB.

Proof:
```bash
bash -c "$VT test/unit/annexDefaultForm.test.ts"           # 21 green
cd $A && DATABASE_URL="postgresql://x:x@127.0.0.1:1/x?schema=qualification" npx prisma validate   # valid; never connects
bash -c "$VT test/unit/formsDefaultIsFixed.test.ts -t 'R47 model|R47 neither migration|schema.prisma has no isDefault'"
```

### Task 8. Pure domain modules (R46, R60 draft, R61, R62, R63, R64 reducer, R67, R71)

All under `src/domain/forms/`, all pure (no Prisma, no env, no fetch).

- New `useOnceName.ts`: `export function useOnceFormName(systemName: string, today: Date, taken: string[]): string`.
  `s` = whitespace collapsed and trimmed, empty is `unnamed system`, `slice(0, 80)` then `trimEnd()`; `d` =
  `today.toISOString().slice(0, 10)` (UTC); `base = "Custom questions: " + s + ", " + d`; compare
  case-insensitively after trim against a `Set` built from `taken` (never mutate `taken`); return `base` or
  `base + " (" + n + ")"` for the smallest free `n >= 2`. Export `USE_ONCE_PREFIX = "Custom questions"` only if
  used elsewhere; no other export needed.
- `chooser.ts`:
  - `preselect(options, from: { fromFormVersionId: string | null; fromFormListed: boolean })`: the fallback is
    `options.find((o) => o.formId === DEFAULT_FORM_ID) ?? options[0]` (import `DEFAULT_FORM_ID` from
    `./legacy`). A leftover `defaultFormId` key on `from` is simply never read.
  - New `export type FormLookup = { lookup: "example" } | { lookup: "formVersion"; id: string } | { lookup: "form"; id: string } | { lookup: "none" }`
    and `export function pickFormParams(p: { example?: string; form?: string; formVersion?: string }): FormLookup`:
    empty strings count as absent; `findExample(example)` (from `@/data/examples`, case-insensitive already)
    known gives `example`; else a `formVersion` gives `formVersion`; else a `form` gives `form`; else `none`.
    Importing `@/data/examples` here is fine: `FormChooser.tsx` imports only the `ChooserPick` type from this
    module, so nothing reaches the client bundle.
  - Update the header comment (no "install default").
- `formDraft.ts`:
  - The zod pick shape becomes `{ kind: "pick", questionId: z.string(), fromVersionId: z.string().min(1) }`
    (non-strict, so an extra `text` is still stripped). `DraftQuestion`'s pick type gains `fromVersionId: string`.
    A missing, numeric or null `fromVersionId` fails the shape: "The form could not be read.".
  - The duplicate rule keeps keying picks by `questionId` only (the same question from two versions is still
    "Question n is already in the form.").
  - `export type PinnedSnapshot = { text: string; citation: string; required: boolean; annexPoint: string | null; groupLabel: string | null }`.
    `annexPoint` is `string | null`, not `AnnexPointId | null`: the R61 tests build `Map`s whose values carry a
    plain `"2a"` string, and `Map` is checked covariantly by tsc.
  - `sameContent(draft, version, snapshots: ReadonlyMap<string, PinnedSnapshot>)`: a pick matches position i
    when `questionId` equals the version question's and `snapshots.get(`${fromVersionId}:${questionId}`)` exists
    and equals the version question in all five fields (exact equality). Missing entry: a change. Everything
    else as today. Pure: never writes to the map.
- `library.ts`:
  - `LibraryGroup` gains `versionId: string`.
  - `filterLibrary` becomes generic, `filterLibrary<G extends { questions: ResolvedQuestion[] }>(groups: G[], query: string): G[]`,
    same behaviour. Reason: `formLibrary.test.ts`'s older `groups` fixture has no `versionId`, and a
    `LibraryGroup[]` parameter would make tsc refuse it.
  - New `export function sourceUpdates(rows: BuilderRow[], library: LibraryGroup[]): Record<number, { question: ResolvedQuestion; versionId: string }>`
    (import `BuilderRow` as a type from `./builderState`): for each pick row at index i, the group with
    `formId === row.source.ownerFormId`, its question with the same `questionId`, listed when any of text,
    citation, required, annexPoint, groupLabel differs from `row.source`. Own and copy rows, missing groups
    (unlisted owner, gone), questions the owner dropped and identical wording are not listed. Pure.
- `builderState.ts`:
  - Pick row: `{ rowKey; kind: "pick"; questionId; fromVersionId: string; source: ResolvedQuestion }`
    (`BuilderRowInput` follows).
  - Actions: `{ type: "tick"; question: ResolvedQuestion; versionId: string }` pins to `versionId`; `startFrom`
    pins every row to `form.versionId`; `initialBuilderState({ edit })` pins every pick row to
    `edit.versionId`; new `{ type: "takeLatest"; index: number; question: ResolvedQuestion; versionId: string }`
    replaces that pick row's `source` and `fromVersionId` (new row object, new array), and returns the very
    same state object (`===`) for an own row, a copy row or an index out of range.
  - `toDraft` pick: `{ kind: "pick", questionId, fromVersionId }`.

Proof:
```bash
bash -c "$VT test/unit/useOnceName.test.ts test/unit/formChooser.test.ts test/unit/formDraft.test.ts test/unit/formLibrary.test.ts test/unit/builderState.test.ts"
# 9 + 28 (+ FormChooser.test.tsx 11, selected by substring) + 44 + 22 + 24, all green
```

### Task 9. FormRepository and FormService (R43, R44 prototypes, R47, R57 exportable, R60, R61, R62, R68)

Files:
- `src/server/repositories/FormRepository.ts`: delete `setDefault` (and its comment). Nothing else. No method
  may take a parameter named `project`, `projectId` or `_project`, and the file must not contain `projectId` or
  `project_id` (R47 scan, comments included for the second check).
- `src/server/services/FormService.ts`:
  - Constructor `(repository = new FormRepository(), { newId = () => randomUUID(), now = () => new Date() }: { newId?: () => string; now?: () => Date } = {})`;
    keep `now` as a private field.
  - Delete `setDefault` (with its `_project` parameter and the F6 message) and `latestSnapshot`.
  - `listed()`: `isDefault: form.id === DEFAULT_FORM_ID` (import from `@/domain/forms/legacy`), never read from
    the row; the sort puts the default first, then the rest by `name.toLowerCase()` (a builtin rank may stay: the
    new CHECK makes the default the only builtin).
  - `libraryGroups()` adds `versionId: latest.versionId`.
  - New `async exportable(formId: string, versionNumber?: number): Promise<ResolvedFormVersion | null>`:
    `versionsOf(formId)`; with a number, the version with that `number`, else the last; `toResolved`, or `null`
    when there is none. Works for listed, unlisted and builtin forms (the builtin resolves equal to
    `annexDefaultVersion()`, as R7 already proves for `resolve`).
  - `saveDraft(draft, opts: { formId?: string; listed: boolean; origin?: "builder" | "import"; systemName?: string })`:
    1. Existing form: as today (refusals, name fixed at creation, `parseFormDraft`).
    2. New use-once form (`listed === false`): name =
       `useOnceFormName(opts.systemName ?? "", this.now(), (await this.repository.listForms()).map((f) => f.name))`
       (every form, listed or not); validate `parseFormDraft({ ...draft, name })` without `takenNames`.
       `systemName` is ignored when `listed` is true.
    3. New listed form: as today (`takenNames` of listed forms).
    4. Pinned snapshots, before `sameContent` and before any planning: for each pick at 1-based n, load
       `findVersion(fromVersionId)` (memoise per version id within this save), find the row whose `questionId`
       matches; a missing version or row returns `{ok: false, error: "Question <n> no longer exists."}` with no
       insert. Keep them in a `Map` keyed `${fromVersionId}:${questionId}` of the five fields.
    5. Existing form: `sameContent(value, latest, snapshots)`; equal returns `created: false` as today.
    6. Planning: a pick pushes its pinned snapshot verbatim (text, citation, required, annexPoint, groupLabel)
       at its position; no `findQuestion` for picks any more. Own and copy rows as today. Insert and P2002
       mapping as today.
  - No public method has a project parameter; the class comment keeps "one library, the same for every
    project".

Proof:
```bash
bash -c "$VT test/unit/FormService.test.ts"                # 48 green
bash -c "$VT test/unit/formsDefaultIsFixed.test.ts -t 'setDefault method|R47 src'"   # prototype and R47 scans green
bash -c "$VT test/unit/formActions.test.ts -t 'R47 a form saved while in project a'" # real service on the fake store
```

### Task 10. Export shape and view type (R69 TS side, R66 type)

Files:
- `src/server/services/QualificationExporter.ts`: each `form.questions[]` entry gains
  `ownerFormId: q.ownerFormId`; the `QualificationExport` type gains `ownerFormId: string` in that entry.
  Nothing else (without a form, the export is still byte for byte the legacy one).
- `src/domain/OntologyView.ts`: `Coverage.annex` gains `optionalBlank?: number` (written exactly like that; a
  test greps `optionalBlank\?:\s*number`).
- `VerticalCard.tsx`: no change (it prints `summary`).

Proof:
```bash
bash -c "$VT test/unit/QualificationExporter.test.ts test/unit/VerticalCard.test.tsx test/unit/fillerReadsItsProject.test.ts"   # 12 + 7 + 4 green
```

### Task 11. FormExportClient and the export route (R56, R57, R73 scans of both)

Files:
- New `src/server/services/FormExportClient.ts`:
  - `export class FormExportClient { constructor(baseUrl: string = process.env.PREFILL_URL ?? "", fetchImpl: typeof fetch = fetch) }`
    (a default parameter, so `new FormExportClient(undefined, f)` reads the env).
  - `async write(form: ResolvedFormVersion, format: "csv" | "md"): Promise<{ ok: true; filename: string; contentType: string; content: string } | { ok: false; status: 502 | 503; error: string }>`,
    never throws: empty base URL gives 503 "Exporting forms is not available on this install." with no fetch;
    `POST serviceUrl(base, "/forms/export")` (from `@/server/services/http`, as FormImportClient does) with
    `headers: { "Content-Type": "application/json" }` and body
    `JSON.stringify({ format, form: { name: form.formName, version: form.versionNumber, questions: form.questions.map(({ text, citation, required, annexPoint }) => ({ text, citation, required, annexPoint })) } })`;
    a thrown fetch gives 502 "The form writer could not be reached."; `!res.ok`, a body that is not JSON, or a
    body without the three string keys gives 502 "The form could not be exported."; success returns exactly
    `{ ok: true, filename, contentType, content }` (no extra keys).
  - `export const formExportClient = new FormExportClient();`
  - Reads no env other than `PREFILL_URL`; imports no FillerClient or llm module.
- New `src/app/p/[project]/forms/[formId]/export/route.ts`, `GET` only:
  `export async function GET(request: Request, { params }: { params: Promise<{ project: string; formId: string }> })`.
  1. `format = new URL(request.url).searchParams.get("format")`; not exactly `csv` or `md` (case-sensitive)
     gives 400, body `format must be csv or md`, `Content-Type: text/plain; charset=utf-8`.
  2. `version`: when the parameter is present, it must match `^[1-9]\d*$`, else 404 `Not found` without asking
     the service; absent means the latest.
  3. `formService.exportable(formId, n)` (`n` undefined when absent; `formId` comes decoded from `params`);
     `null` gives 404 `Not found`.
  4. `formExportClient.write(v, format)`; failure gives its `status` and `error` as a text body.
  5. 200: `new Response(new TextEncoder().encode(content), { headers: { "Content-Type": contentType, "Content-Disposition": `attachment; filename="${filename}"`, "Cache-Control": "no-store" } })`.
  Reads no env. No POST/PUT/PATCH/DELETE exports. Access is the unchanged middleware (`matcher: ["/p/:path*"]`,
  GET allowed for any member, viewers included).

Proof:
```bash
bash -c "$VT test/unit/FormExportClient.test.ts test/unit/formExportRoute.test.ts"   # 9 + 18 green
```

### Task 12. Actions, the library page, FormLine, the card and edit pages, the header (R44, R46, R48, R49, R58, R66, R71, R73)

12a. Actions and the library page (R44, R48, R58, R73):
- `src/app/p/[project]/forms/actions.ts` (the first characters stay `"use server";`): delete `setDefaultForm`
  and the `callerAccess` import; the file must not contain `.admin`. `useFormOnce(project, draftJson, origin?)`:
  after `JSON.parse`, validate with the name replaced by a placeholder (for example `"Custom questions"`,
  because `parseFormDraft` refuses a blank name and the service ignores it); then
  `const latest = await platformClient.latestVersion(project).catch(() => null)` (import `platformClient`
  from `@/server/services/PlatformClient`), `systemName = latest?.name ?? project`, and
  `formService.saveDraft(value, { listed: false, origin: origin ?? "builder", systemName })`. `saveForm`
  unchanged. Exactly two exported functions, no other `export`.
- Delete `src/app/p/[project]/forms/SetDefaultButton.tsx` (an untracked round 1 file; `rm` that one path).
- `src/app/p/[project]/forms/page.tsx`: drop `callerAccess`, the `admin` flag and the button. The header's first
  `<p>` holds, as plain text, "Every project on this install sees the same forms." and "A new AI card starts
  with the Annex IV default." (plus the existing text and the "+ New form" / "Import form" links). Each row's
  last cell, in order: "Start from", "Edit" (not for the builtin), "Export CSV", "Export Markdown". The two
  export links are plain `<a download>` (not `next/link`: Next 15.0.3's Link intercepts the click even with
  `download`), href
  `${basePath}/p/${project}/forms/${encodeURIComponent(r.formId)}/export?format=csv&version=${r.version}` (and
  `md`), with `const basePath = process.env.NEXT_BASE_PATH || ""` as the card page already does (the stack
  serves the app under `/qualification`). The file's top comment loses "Only an administrator changes the
  default." `formService.library()` is called with no arguments.

12b. FormLine and the two pages (R58, R66, R71, R46):
- New `src/app/p/[project]/FormLine.tsx` (a server-safe component, no `"use client"`, no hooks). Props
  `{ project: string; formId: string; formName: string; versionNumber: number; basePath?: string }`,
  `basePath` defaulting to `""`. It must not read `process.env` (R73 scan): the pages pass `basePath`.
  Renders `<p className="qf-row-form">Form: {formName} v{versionNumber} · <a ...>CSV</a> · <a ...>Markdown</a></p>`
  so that `textContent` is exactly `Form: <name> v<N> · CSV · Markdown`; each `<a>` has `download`,
  `aria-label={`Export ${formName} v${versionNumber} as CSV`}` (and `as Markdown`), and href
  `${basePath}/p/${project}/forms/${encodeURIComponent(formId)}/export?format=csv&version=${versionNumber}`.
- `src/app/p/[project]/qualify/[id]/page.tsx`: keep the line
  `const form = (await formService.resolve(q.formVersionId ?? null)) ?? annexDefaultVersion();` exactly as it
  is (a test greps it); replace the "Form: {form.formName} v{form.versionNumber}" paragraph with
  `<FormLine project={project} formId={form.formId} formName={form.formName} versionNumber={form.versionNumber} basePath={basePath} />`
  on one tag, props in that order, no `>` inside the attribute list (the test regex is
  `<FormLine[^>]*formId=\{[^}]*\.formId\}[^>]*versionNumber=\{[^}]*\.versionNumber\}`). The file must no longer
  contain `Form: {`.
- `src/app/p/[project]/system/edit/page.tsx`: use `pickFormParams({ example, form, formVersion })`:
  `example` gives `annexDefaultVersion()` and `worked = findExample(example)`; `formVersion` gives
  `formService.resolve(id)`; `form` gives `formService.latestVersion(id)`; a named lookup that finds nothing sets
  `error = "That form was not found."`; `none` sets no error. `preselect(options, { fromFormVersionId: from, fromFormListed })`
  with no `defaultFormId`; the source must contain neither `defaultFormId` nor `find((o) => o.isDefault)`.
  Replace the "Form:" paragraph with `<FormLine project={project} formId={version.formId} formName={version.formName} versionNumber={version.versionNumber} basePath={basePath} />`
  (`basePath` from `process.env.NEXT_BASE_PATH || ""`); no `Form: {` left. Keep the strings the round 1 source
  tests need (`<FormChooser`, `<QualifyForm`, `formVersion`, `example`, "That form was not found.").

12c. The header (R49):
- `src/components/SiteHeader.tsx`: inside the `project &&` fragment, after "Versions", add
  `<Link href={`/p/${project}/forms`}>Forms</Link>`. Without a project nothing changes.

Proof:
```bash
bash -c "$VT test/unit/formActions.test.ts test/unit/FormsPage.test.tsx test/unit/FormLine.test.tsx test/unit/editSystemPage.test.tsx test/unit/SiteHeader.test.tsx test/unit/formsDefaultIsFixed.test.ts test/unit/formsNoModel.test.ts"
# 23 + 5 + 6 + 24 + 2 + 17 + 6, all green
```

### Task 13. The builder and the import UI (R59, R64)

Files:
- `src/app/p/[project]/forms/FormBuilder.tsx`:
  - A left-column tick dispatches `{ type: "tick", question, versionId: group.versionId }`.
  - `const updates = sourceUpdates(state.questions, library)` (memoised). For a listed pick row: a chip
    `<span className="qf-tag">Source updated</span>` (exact text), `<p className="qf-new-wording">New wording: {question.text}</p>`,
    and a `type="button"` "Use new wording" with
    `aria-label={"Use the new wording of " + row.source.text.slice(0, 40).trimEnd()}`, dispatching
    `{ type: "takeLatest", index, question, versionId }`. Nothing of it on other rows.
  - Saving is unchanged (`toDraft` now carries `fromVersionId`).
- `src/server/services/FormImportClient.ts`: `ImportedQuestion` gains `annexPoint: AnnexPointId | null`; each
  question is mapped to exactly `{ text, citation, required, annexPoint: isAnnexPoint(q.annexPoint) ? q.annexPoint : null }`.
- `src/app/p/[project]/forms/import/FormImport.tsx`: preview rows keep `annexPoint` from the file; each row
  gets its own `<label>` "Answers Annex IV point" with a `<select>` (option `""` "None", then the 14
  `ANNEX_POINTS` by citation, value = id), preselected from the row; a change updates the row; "Continue" passes
  `annexPoint` into the builder's own rows instead of `null`. Reuse the option list the builder's editor
  already renders if it is exported; otherwise map `ANNEX_POINTS` the same way.

Proof:
```bash
bash -c "$VT test/unit/FormBuilder.test.tsx test/unit/FormImport.test.tsx test/unit/FormImportClient.test.ts"   # 26 + 10 + 7 green
bash -c "$VT"                                                                                               # 0 failed
```

### Task 14. DB-gated tests on a throwaway Postgres (R45 DB half, R1 and R7 still green)

```bash
cd $A && npx prisma generate            # again, if task 7's run was before any later schema touch
cd $A && test/db/throwaway-db.sh        # random port, refuses 5432; removes its container on exit
docker ps -a --format '{{.Names}}' | grep aisc-t-qual- || echo "none left"
```
Expected: 3 files, 37 tests, 37 passed (`cardVersionOfItsProject` 6, `cardVersions` 13, `forms` 18). If docker
is unavailable, say so and stop: no other way to a database.

### Task 15. Docs (no test)

- `services/prefill/README.md`: document `POST /forms/export` (request, response, the three 422 messages),
  the `annexPoint` key of `/forms/import`, and `PREFILL_MAX_UNZIPPED_BYTES` (default 52428800). No new markdown
  file.

### Task 16. Full verification

Section 6.

---

## 2. Conflicts found, and how this plan resolves them (tests win)

1. **The CSV `'` guard inverse (07 gap 1).** R53's literal wording does not strip `''=x`; R54 and B9 need it
   stripped once. Implemented as the exact inverse of the exporter: strip one leading `'` only when the rest is
   a cell the exporter would have guarded (task 2).
2. **R73 against the deployment's basePath.** R73 forbids `FormLine.tsx` any env read but `PREFILL_URL` and
   `PLATFORM_URL`; the stack sets `NEXT_BASE_PATH: /qualification` (`docker-compose.development.yml:306`), raw
   `<a>` hrefs do not get it, and Next 15.0.3's `Link` ignores `download` (it client-navigates). Resolved with an
   optional `basePath` prop on FormLine (default `""`, so the tests' exact hrefs hold), filled by the two pages
   from `NEXT_BASE_PATH`; the library page reads `NEXT_BASE_PATH` itself (not in R73's list; R41's scan allows it).
3. **A type error in a test that no source change can fix.** `test/unit/formLibrary.test.ts:137`:
   `acmeGroup([newer])`, where the test-local `acmeGroup` infers `AnnexPointId | null` from its default and
   `newer` carries a plain `"2a"` string. After the implementation, `npx tsc --noEmit` is expected to report
   exactly this one error (TS2322). `next build` is unaffected (Next's type check skips `*.test.*` files,
   `node_modules/next/dist/lib/typescript/runTypeCheck.js`). Do not edit the test and do not widen
   `AnnexPointId`: report it to the test writer (a one-word cast in the test fixes it).
4. **`LibraryGroup.versionId` against the old `formLibrary` fixture.** Made `filterLibrary` generic (task 8)
   so the old fixture without `versionId` still type-checks.
5. **R61 map values against `AnnexPointId`.** `PinnedSnapshot.annexPoint` is `string | null` (task 8).
6. **R72 "seed_mcas.mjs unchanged" against "read through its exports" (07 gap 4).** The test runs `seedMcas`
   with a fake prisma; the script stays unchanged.
7. **R45 "no BEGIN" against the plpgsql body (07 gap 2).** The test checks outside `$$ ... $$`; the section 3.2
   text is used verbatim.
8. **The task framing said e9d0693 came after the round 2 tests.** The red run in `07` (09:23) postdates the
   commit (09:03) and reproduces exactly today, so the round 2 tests were already run against it. No
   interaction found (task 0, step 5).
9. **Deployment path outside this plan (report only, do not fix).** The app image's `CMD` is
   `npx prisma db push --accept-data-loss && npx next start` (`apps/qualification/Dockerfile`). A database reached
   through the image is synced from `schema.prisma`, not migrated: neither 090000 (seed, triggers, checks,
   partial indexes) nor 120000 runs there, and `db push` may drop the hand-written partial indexes. This was
   already true for round 1. It is for the product owner, and the Dockerfile is off limits here.

---

## 3. Migration

### 3.1 `prisma/migrations/20260925120000_the_default_form_is_fixed/migration.sql` (verbatim)

```sql
-- The default form is always the seeded "Annex IV default" (id annex-iv-default), for every
-- project. Nobody changes it, so the default flag and everything that served it go.
-- Addendum 06, section 3.2. No row of any table is changed here.
DROP INDEX qualification.form_one_default;
ALTER TABLE qualification.form DROP CONSTRAINT form_default_is_listed;
ALTER TABLE qualification.form DROP COLUMN is_default;

-- The only builtin form is the default one, and it is always listed.
ALTER TABLE qualification.form ADD CONSTRAINT form_builtin_is_the_default
  CHECK (origin <> 'builtin' OR (id = 'annex-iv-default' AND listed));

-- Same rule as before, without the default flag in its message.
CREATE OR REPLACE FUNCTION qualification.form_name_is_fixed() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.name IS DISTINCT FROM OLD.name OR NEW.origin IS DISTINCT FROM OLD.origin
     OR NEW.listed IS DISTINCT FROM OLD.listed THEN
    RAISE EXCEPTION 'form % keeps its name, origin and listing: only its description changes', OLD.id;
  END IF;
  RETURN NEW;
END $$;
```

Rules the unit test enforces (with `--` comments stripped): the nine statement fragments of 3.2 in that order
(whitespace-collapsed), no `UPDATE`, `DELETE`, `TRUNCATE` anywhere, no `BEGIN`/`COMMIT`/`CONCURRENTLY`/
`IF EXISTS` outside the `$$` body, no `CREATE TRIGGER`/`DROP TRIGGER`. Keep the comments free of `$$`.

### 3.2 How it coexists with 090000 and the existing triggers

- **Order.** `prisma migrate deploy` applies 090000 then 120000 on a fresh database; on one where 090000 is
  applied, only 120000. 090000's bytes and checksum are untouched, so `_prisma_migrations` never reports it as
  modified.
- **Atomicity.** Prisma sends the file as one multi-statement script; Postgres runs it in one implicit
  transaction, so a database in an unexpected shape (another index name, an extra builtin row) fails at the
  first statement and changes nothing. That is why there is no `IF EXISTS`.
- **The new CHECK is validated on existing rows** when added: the only builtin row is `annex-iv-default`,
  listed, so it passes; a database holding another builtin row fails loudly.
- **`form_name_is_fixed`.** `CREATE OR REPLACE FUNCTION` swaps the body only; the trigger created by 090000
  (`BEFORE UPDATE ON qualification.form`) keeps pointing at it. No trigger is created or dropped, so the set of
  five trigger names the R7 DB test reverts is unchanged.
- **The other four triggers** (`form_version_is_append_only`, `form_version_question_is_append_only`,
  `form_question_identity_is_fixed`, `form_builtin_is_fixed`) and the card triggers
  (`qualification_only_latest_changes`, `qualification_answer_only_latest_changes`) are untouched. DDL fires no
  row trigger; the file changes no row of `qualification`, `qualification_answer`, `qualification_risk`,
  `knowledge_graph` or `card_component`.
- **The R7 DB test.** It drops the five trigger functions `CASCADE`, the four tables `CASCADE` (which removes
  `form_builtin_is_the_default` with `form`), the column and the answer key, then re-runs 090000's text inside a
  rolled-back transaction. That re-run recreates `is_default` and `form_one_default` only inside the
  transaction; the rollback returns the database to its post-120000 state. It keeps passing unmodified.
- **Ownership.** On the throwaway DB, Prisma runs both files as `qualification_rw`, which owns the `form` table
  and the function it created, so `DROP INDEX`, `ALTER TABLE` and `CREATE OR REPLACE FUNCTION` are allowed. A
  database where 090000 was run by another role would refuse 120000 for `qualification_rw` (loud, rolled back).
- **Prisma drift.** The schema no longer has `isDefault`; the CHECK and trigger remain unmodelled, as before.
  Never `prisma migrate dev`, `db push` or `migrate reset`.

---

## 4. Risks and how each is guarded

1. **MCAS graph 409 to 413 triples, and every pinned count.** Pins that move, all already updated by the test
   writer: `test_example_mcas.py` (14 answers, 14 citations incl. "Annex IV(1)(f)", 413 triples, 59 view nodes,
   1f right after 1de), `test_roundtrip.py` (14 texts, 9996 characters = 9697 + 299), `test_coverage.py` (three
   R34 MCAS tests plus `test_r72_*`), `mcasExampleAgrees.test.ts` (keys, 1f text, order, README "14 Annex IV
   answers" and "413 triples"). The committed-graph tests pass only after both files are regenerated from the
   edited JSON. No test pins a literal graph digest (`test_graph.py` and `test_form_answers.py` compare digests
   with each other), so no digest constant changes; the stored `knowledge_graph` rows of seeded MCAS cards come
   from the database, whose seed already answers 1f. The planner's scratch run confirmed nothing else in the
   ontology suite moves. The three pre-existing failures stay (03-plan 6.4); do not fix them.
2. **Export/import round trip.** The ten `TestRoundTrip` cases are the property. Traps: collapse before the
   guard on export, unguard before collapse on import; the guard only in CSV; `\` escaped before `|` on export
   and a left-to-right tokenizer on import (a two-pass `replace` breaks `\\|`); the BOM is already stripped by
   the importer; the Markdown title counts as exactly one heading (hence "Skipped 1 heading."), and the HTML
   comment is one line (already skipped); table cells never go through the bracket-citation or list-marker
   rules (so `Ends with a box [x]` and `-dash first?` survive); the Annex check runs after the duplicate rule;
   empty forms give header only. The route checks bytes (`arrayBuffer`), so build the body with `TextEncoder`,
   never `Response.text()` semantics.
3. **Removing set-default leaves no dead code or routes.** Deleted: `FormRepository.setDefault`,
   `FormService.setDefault` (and the F6 message), `FormService.latestSnapshot`, `setDefaultForm`, the
   `callerAccess` import in the actions and in the library page, `SetDefaultButton.tsx`, the admin branch of
   the library page, `defaultFormId` in `chooser.ts` and the edit page, `isDefault` in `schema.prisma`, stale
   comments. Kept on purpose: `LibraryRow.isDefault` (computed), the FormChooser `isDefault` prop and tag. Check
   at the end: `grep -rn "setDefault\|is_default\|Set as default\|Only an administrator\|defaultFormId\|latestSnapshot\|org default" $A/src $A/prisma/schema.prisma`
   prints nothing (the test's four needles plus four of this plan's). No route is lost: set-default was a
   server action, not a route; `next build` lists the same routes plus `/p/[project]/forms/[formId]/export`.
4. **`?formVersion` precedence.** The flip is deliberate (R71, B8). Nothing in the app builds a URL with both
   (`FormChooser` pushes one parameter; `saveForm` redirects with `?form`, `useFormOnce` with
   `?formVersion`). An unknown `?formVersion` never falls back to `?form`. Empty strings are absent everywhere
   (the page must not call `resolve("")`).
5. **Stale Prisma client** after the schema edit: `npx prisma generate` in task 7 and before task 14.
6. **basePath.** See conflict 2. Keep `NEXT_BASE_PATH` unset in the shell that runs vitest (the tests expect
   bare `/p/...` hrefs).
7. **tsc expectation changes.** Round 1 ended at 0 errors; round 2 ends at exactly 1, in a test file
   (conflict 3). Any other error, in `src/` or in a test, is the implementer's to fix in `src/` (widen a
   source type, make a helper generic), never in the test.
8. **The use-once name race (B6).** Two saves in the same instant may share a name; no index prevents it and
   nothing groups by name any more (R69). Do not add an index.
9. **Legacy cards change visibly (R66).** Every legacy card shows the coverage line with the optional note and
   the "Form: Annex IV default v1 · CSV · Markdown" line. Intended; mention it in the final report.
10. **A concurrent session commits on this branch.** Before each proof run, `git -C $A status --short`; touch
    only the files of section 5; if a file you need changed under you, stop and report.
11. **Prefill run time.** The failing prefill suite takes about 30 s (ImportError re-raised per test); once
    `form_export.py` exists it drops to a few seconds. Not a hang.

---

## 5. Files this plan creates, edits or deletes (nothing else)

Created: `prisma/migrations/20260925120000_the_default_form_is_fixed/migration.sql`,
`services/prefill/prefill/form_export.py`, `src/domain/forms/useOnceName.ts`,
`src/server/services/FormExportClient.ts`, `src/app/p/[project]/forms/[formId]/export/route.ts`,
`src/app/p/[project]/FormLine.tsx`.

Edited: `prisma/schema.prisma`; `services/prefill/prefill/{fields.py,documents.py,form_import.py}`,
`services/prefill/app.py`, `services/prefill/README.md`; `services/ontology/airo_min/coverage.py`,
`services/ontology/examples/{mcas.qualification.json,mcas.ttl,mcas.jsonld}`, `services/ontology/README.md`;
`services/system_card_renderer/models.py`; `src/domain/forms/{chooser.ts,formDraft.ts,library.ts,builderState.ts}`;
`src/domain/OntologyView.ts`; `src/server/repositories/FormRepository.ts`;
`src/server/services/{FormService.ts,QualificationExporter.ts,FormImportClient.ts}`;
`src/app/p/[project]/forms/{actions.ts,page.tsx,FormBuilder.tsx,import/FormImport.tsx}`;
`src/app/p/[project]/qualify/[id]/page.tsx`; `src/app/p/[project]/system/edit/page.tsx`;
`src/components/SiteHeader.tsx`.

Deleted: `src/app/p/[project]/forms/SetDefaultButton.tsx`.

Generated, not tracked: `node_modules/.prisma` (by `prisma generate`), `.next/` (by an optional build).

---

## 6. Full verification (expected counts)

Run from a clean shell with `A` and `P` set as at the top.

### 6.1 TypeScript
```bash
cd $A && npx vitest run
cd $A && npx tsc --noEmit
cd $A && DATABASE_URL="postgresql://x:x@127.0.0.1:1/x?schema=qualification" npx prisma validate
```
Expected: Test Files 74 passed, 4 skipped (78); Tests 876 passed, 38 skipped (914), 0 failed (the 38 are the 37
DB tests plus one pre-existing skip). `tsc`: exactly one error,
`test/unit/formLibrary.test.ts(137,...): error TS2322` (conflict 3), nothing in `src/`. Prisma: valid.

Optional, only when `pgrep -af "next (dev|start)"` shows no server using `$A`: `cd $A && npm run build`,
expected exit 0 with the routes of round 1 plus `/p/[project]/forms/[formId]/export` (the pre-existing font
lint warning only).

### 6.2 Python
```bash
bash -c "$ONTO"      # 240 passed, 3 failed (test_build ...nineteen_properties, test_example_mcas ...nineteen_properties, test_roundtrip ...every_airo_relation)
bash -c "$PREF"      # 283 passed
bash -c "$REND"      # 35 passed
bash -c "$AGENTS"    # 152 passed (untouched; proves e9d0693's side still holds)
```
or `bash $P/r2-run-all.sh r2impl-after` for the five summary lines.

### 6.3 DB (throwaway only)
Task 14: 3 files, 37 passed; no `aisc-t-qual-*` container left.

### 6.4 By reading
- Test integrity: `cd $A && sha256sum -c --quiet $P/r2-impl-tests.sha` prints nothing (every test, fixture and
  support file byte-identical to task 0). If a line appears, find out whether the other session changed it
  (`git log -1 -- <file>`) before reporting.
- `git -C $A status --short` lists only section 5's files beyond what task 0 saw; `git -C $A log --oneline -1`
  unchanged, or only the other session's commits.
- The grep of risk 3 prints nothing.
- `git -C $A diff --stat -- prisma/migrations/20260925090000_forms_are_data` is empty and the sha256 test passes.
- R-id closure: every id R43 to R73 has at least one green test in `07-tests-round2.md` section 2's map; list
  any that does not in the report.

### 6.5 R-ids closed per task

| Task | R-ids |
|---|---|
| 1 | R53 (ids), R70 |
| 2 | R53, R59 (service) |
| 3 | R50, R51, R52, R54, R73 (Python) |
| 4 | R55, R70 (endpoints) |
| 5 | R72 |
| 6 | R65, R66 (Python), R69 (Python) |
| 7 | R45 (text), R44 and R47 (schema) |
| 8 | R46, R60 (draft), R61, R62, R63, R64 (reducer), R67, R71 (function) |
| 9 | R43, R44 (prototypes), R47, R57 (exportable), R60, R61, R62, R68 |
| 10 | R66 (type), R69 (TS) |
| 11 | R56, R57, R73 (TS new parts) |
| 12 | R44, R46 (page), R48, R49, R58, R66, R68 (action), R71 (page), R73 |
| 13 | R59, R64 |
| 14 | R45 (DB) |

---

## 7. Must not do

- No `prisma migrate deploy|dev|reset`, no `prisma db push`, no SQL or psql against any running database.
  Ports 5432 and 5433 are the live stack and off limits. The only database allowed is the one
  `test/db/throwaway-db.sh` starts on a random port and removes; DB tests run only through that script.
- No docker use other than that script: no `docker compose`, no image builds or pulls of app images, no
  container restarts, no edits to any Dockerfile or compose file (report the `db push` CMD, do not change it).
- No commits, pushes, branch switches, `git stash`, `git reset`, `git checkout` (any form), `git restore`,
  `git clean`, `git add -A` or `git add .`, in either repository: another session commits on this branch.
- Never edit, weaken, skip, rename or delete a test, fixture or test-support file (`test/**`,
  `services/*/tests/**`, including `test/support/fakeFormStore.ts` and the committed JSON fixture). If a test
  looks wrong, stop and report it with the reason (conflict 3 is already known: report, do not touch).
- Do not edit `prisma/migrations/20260925090000_forms_are_data/migration.sql`.
- Do not touch the files of e9d0693 (`services/agents/**`, `src/server/services/FillerClient.ts`,
  `src/app/p/[project]/qualify/new/actions.ts`, `src/app/api/qualifications/[id]/extracted/route.ts`), nor the
  frozen ones: `src/data/keyQuestions.ts`, `src/data/prefillFields.json`, `src/data/annexPoints.json`,
  `src/data/examples/mcas.ts`, `src/middleware.ts`, `scripts/*.mjs`, `airo.ttl`/`vair.ttl`.
- Do not fix the three pre-existing ontology failures.
- No new dependency, no model or LLM call, no new markdown file (only the two README edits listed).
- Never `sudo`, `chown` or delete the root-owned `__pycache__` folders or `services/agents/application.log`;
  always `PYTHONPYCACHEPREFIX=$P/pyc` and `-p no:cacheprovider`; agents run from `$P/agents-cwd`.
- No em dashes in any prose written (user rule).
