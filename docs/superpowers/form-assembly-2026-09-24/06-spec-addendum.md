# Form assembly: specification addendum (stage 6)

Date: 2026-09-25. App: `apps/qualification`, branch `feat/unified-modules` (not switched).
Status: specification only. It changes a feature that is implemented but uncommitted (see `04-progress.md`,
fix round 1, and `05-verification.md`). No test, code or migration exists yet for anything below.

Readers: the agents who will write tests, a plan and code from this file plus `01-spec.md`. Where the two
conflict, **this file wins**. Requirement ids continue from `01-spec.md`: R43 to R73. New assumptions are
B1, B2, ... (section 7). Section 5 lists every item of `01-spec.md` this file supersedes.

Paths are relative to `apps/qualification` unless absolute. "The default form" is the seeded form
`annex-iv-default`; "the default version" is `annex-iv-default-v1`. DB-gated tests (`test/db/`) run only
through `test/db/throwaway-db.sh`, as today; every other test named here needs no network, model, database,
docker or running service.

---

## 1. Product owner decisions and where they land

| # | Decision | Requirements |
|---|---|---|
| 1 | The default form is always the seeded Annex IV form, for every project; nobody can change it. "Set as default" goes. | R43 to R46 |
| 2 | Forms are never project-scoped: one install-wide library. | R47, R48 |
| 3 | Any form can be exported (CSV, Markdown) and imported back to an equal form. | R50 to R59 |
| 4a | F3: a picked question stays pinned to the wording it was picked with; "Source updated" offers the new wording. | R60 to R64 |
| 4b | F4: legacy cards keep the coverage line and the "Form:" line; coverage names optional points left blank. | R65, R66 |
| 4c | F7: use-once forms get a unique name; coverage groups by form id. | R67 to R69 |
| 4d | F8: cap the uncompressed size of .docx files. | R70 |
| 4e | `?formVersion` wins over `?form`. | R71 |
| 4f | "Forms" link in the site header. | R49 |
| 4g | MCAS covers 14 of 14. | R72 |
| 5 | Q1, Q2 and touched ASSUMED items resolved. | section 5, R73 |

What the code has today, verified by reading (not assumed):

- `Form` has **no** project, owner or organisation column (`prisma/schema.prisma`, migration
  `20260925090000_forms_are_data`). The only project-shaped thing in the forms code is the unused
  `_project` parameter of `FormService.setDefault` and the `project` argument of the server actions (used
  for access and redirects). So decision 2 removes no column; it removes that parameter and pins the rule
  with tests.
- The default mechanism is: column `form.is_default`, partial unique index `form_one_default`, check
  `form_default_is_listed`, the `form_name_is_fixed` trigger message ("only its description and default
  flag change"), `FormRepository.setDefault`, `FormService.setDefault` (with the F6 P2002 mapping), the
  action `setDefaultForm`, `forms/SetDefaultButton.tsx`, the library page's admin check, and the edit
  page's `options.find((o) => o.isDefault)`.
- `src/data/examples/mcas.ts` (line 41) and `scripts/seed_mcas.mjs` (line 127, "1f") **already** answer
  1(f), with the same text. Only `services/ontology/examples/mcas.qualification.json` (13 answers) and the
  graph files built from it (`mcas.ttl`, `mcas.jsonld`, 409 triples each today) lack it.
- The edit page today lets `?form` win over `?formVersion` (`system/edit/page.tsx` lines 29 to 31), and
  `test/unit/editSystemPage.test.tsx` pins that order.

---

## 2. Where the new logic lives

| Logic | Where | Why |
|---|---|---|
| Writing CSV and Markdown form files | Python, new `services/prefill/prefill/form_export.py`, endpoint `POST /forms/export` on the prefill service | The reader (`form_import.py`) is already there. Writer and reader in one module family means the round-trip property (R54) is one pytest in one process, with no cross-language drift, and the product owner reads Python. The TS side only relays bytes. |
| Importer extensions (Annex column, escapes) | Python, `services/prefill/prefill/form_import.py` | Same file as today. |
| The 14 point ids in the prefill service | Python, `ANNEX_POINT_IDS` in `services/prefill/prefill/fields.py`, derived from `ANNEX_FIELDS` (already loaded from `src/data/prefillFields.json`) with `_point_of`, in first-appearance order | No new data file, no image change (spec section 2 of 01 already chose this). |
| .docx expansion cap | Python, one helper in `services/prefill/prefill/documents.py`, used by both `.docx` readers | One rule for `/prefill` and `/forms/import`. |
| Coverage wording (optional left blank), grouping by form id | Python, `services/ontology/airo_min/coverage.py` | Already computed there, once, for card, JSON and PDF. |
| Use-once name, "source updated" detection, pinned picks, chooser preselection, `?form`/`?formVersion` resolution | TS, small pure modules under `src/domain/forms/` | They run before a Prisma write or on every builder click; each is a pure function. |
| Export route | TS, thin route handler; `FormExportClient` (fetch injected, never throws) | Reads the version from the DB and relays the service's answer. |

If the prefill service is not configured, export is unavailable (R56, R57), exactly as import already is.
**ASSUMED (B1):** that shared dependency is acceptable; a pure-TS writer is the fallback if the product owner
wants export to work without the prefill service (only R50 to R57 would move).

---

## 3. Data model and migration changes

### 3.1 Migration choice

`prisma/migrations/20260925090000_forms_are_data/migration.sql` is **not edited**. A new forward migration
`prisma/migrations/20260925120000_the_default_form_is_fixed/migration.sql` removes the default flag.

Why, although the product owner states 090000 has never reached a live database: "never applied anywhere"
cannot be proved. It has been applied to throwaway Postgres instances by `test/db/throwaway-db.sh`
(including `KEEP=1` runs), other sessions keep their own containers, and Prisma stores a checksum per applied
migration in `_prisma_migrations`, so any database that ran the old text would report the edited file as
modified. The 090000 text is also pinned by `test/unit/annexDefaultForm.test.ts` and reverted and re-run by
the R7 DB test; leaving it intact keeps both meaningful. The cost is one small file.

### 3.2 `20260925120000_the_default_form_is_fixed/migration.sql` (exact statements, in this order)

Rules as for 090000 (plan 03 section 3): every name schema-qualified, no `BEGIN`/`COMMIT`, no
`CONCURRENTLY`, no `IF EXISTS` (a database in an unexpected shape fails loudly and rolls back), no `UPDATE`,
`DELETE` or `TRUNCATE` of any table.

```sql
-- The default form is always the seeded "Annex IV default" (id annex-iv-default), for every
-- project. Nobody changes it, so the default flag and everything that served it go.
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

No trigger is added or dropped, so the R7 DB test's revert of 090000 (drop the five trigger functions, the
four tables, the column, the index; re-run 090000) still works: the new constraint lives on `form` and goes
with the table.

### 3.3 `prisma/schema.prisma`

- `model Form`: remove `isDefault` (and its comment). Add above the model:
  `/// The default form is always id "annex-iv-default" (DEFAULT_FORM_ID in src/domain/forms/legacy.ts). There is no default flag.`
- Nothing else changes. `npx prisma validate` (dummy `DATABASE_URL`, as in 04-progress task 1) stays valid.

### 3.4 Shapes that change (TS and Python)

| Shape | Change |
|---|---|
| `LibraryRow.isDefault` (FormService) | Kept, but computed: `formId === DEFAULT_FORM_ID`. Never read from the database. |
| `LibraryGroup` (`src/domain/forms/library.ts`) | Gains `versionId: string`: the owner form's latest version id, the version its questions are shown (and picked) from. |
| `DraftQuestion` pick | `{ kind: "pick"; questionId: string; fromVersionId: string }` (both required). |
| `BuilderRow` pick | Gains `fromVersionId: string`; `source` is the pinned snapshot (the wording shown). |
| `FormService` constructor | `new FormService(repository, { newId, now = () => new Date() })`. |
| `FormService` methods | `setDefault` removed. `saveDraft(draft, { formId?, listed, origin?, systemName? })`: `systemName` is used only when `listed === false` (R67, R68). New `exportable(formId, versionNumber?)` (R57). No method takes a project. |
| `preselect` (`src/domain/forms/chooser.ts`) | `preselect(options, { fromFormVersionId, fromFormListed })`; the default is the constant `DEFAULT_FORM_ID`. |
| Export payload `form.questions[]` (`QualificationExporter.toExport`) | Gains `ownerFormId: string`. |
| `coverage()` output | `annex` gains `optionalBlank: int`; `annex.points[]` shape unchanged (`{id, citation, covered}`). |
| Renderer `CoverageAnnex` (`services/system_card_renderer/models.py`) and TS `Coverage` (`src/domain/OntologyView.ts`) | Gain `optionalBlank` (Python `int = 0`, TS `optionalBlank?: number`). |
| `/forms/import` response `questions[]` and TS `ImportedQuestion` | Gain `annexPoint: string \| null` (TS: `AnnexPointId \| null`). |
| New `POST /forms/export` | R55. |

---

## 4. Requirements

### A. The default form is fixed

**R43. The default form is a constant, the same for every project.**
- Given listed forms "Annex IV default" (builtin), "Zeta checklist" and "Acme AI policy", when
  `FormService.library()` runs with the fake repository, then the rows are, in order: "Annex IV default"
  (`isDefault: true`), "Acme AI policy", "Zeta checklist" (both `isDefault: false`, case-insensitive name
  order). No row's `isDefault` comes from the repository: the fake store has no default field at all.
- Given `chooserOptions()`, then exactly one option has `isDefault: true`, and its `formId` is
  `"annex-iv-default"`.
- Given the chooser, then the "default" tag (`span.qf-tag` " default") is on "Annex IV default" and on no
  other option.
- Tests: `test/unit/FormService.test.ts` (vitest, fake repository), `test/unit/FormChooser.test.tsx`
  (jsdom). `test/support/fakeFormStore.ts` loses its default field and its `setDefault` method.

**R44. Nothing can change the default.**
- Given the source of `src/app/p/[project]/forms/actions.ts`, then it exports exactly `saveForm` and
  `useFormOnce` (no `setDefaultForm`).
- Given `src/app/p/[project]/forms/SetDefaultButton.tsx`, then the file does not exist.
- Given `FormService` and `FormRepository`, then neither has a `setDefault` method (a test calls
  `"setDefault" in FormService.prototype` and the same for `FormRepository.prototype`: both false).
- Given every file under `src/` and `prisma/schema.prisma`, then none contains `setDefault`,
  `is_default`, `Set as default` or `Only an administrator can change the default form.` (source scan;
  the computed `LibraryRow.isDefault` is allowed and not scanned for), and `prisma/schema.prisma` has no
  `isDefault` field.
- Given the library page rendered for an administrator (`callerAccess` mocked to `{admin: true}`), then no
  button or link reads "Set as default".
- Tests: `test/unit/formsDefaultIsFixed.test.ts` (vitest, source scan and prototype checks, new),
  `test/unit/FormsPage.test.tsx` (vitest, jsdom, server component called with mocked `formService` and
  `callerAccess`, new).

**R45. The forward migration.**
- Given `prisma/migrations/20260925120000_the_default_form_is_fixed/migration.sql` read as text (with `--`
  comments stripped), then it contains the statements of section 3.2, and contains no `UPDATE`, `DELETE`,
  `TRUNCATE`, `BEGIN`, `COMMIT`, `CONCURRENTLY` or `IF EXISTS`.
- Given `prisma/migrations/20260925090000_forms_are_data/migration.sql`, then its bytes are unchanged
  (the existing text tests in `annexDefaultForm.test.ts` keep passing unmodified).
- Given a migrated throwaway DB, then: `qualification.form` has no column `is_default`
  (`information_schema.columns`); no index `form_one_default` exists; inserting a form row with
  `origin = 'builtin'` and id `other` fails on `form_builtin_is_the_default`; updating
  `annex-iv-default` to `listed = false` fails (on the trigger `form_name_is_fixed`, whose message now reads
  "... only its description changes"); updating its `description` succeeds (then roll back).
- Given the R7 DB test, then it still passes (the forward migration does not stop 090000 from being
  reverted and re-applied inside its transaction).
- Tests: `test/unit/annexDefaultForm.test.ts` (vitest, extended: text of the new file),
  `test/db/forms.db.test.ts` (DB-gated, extended; the R4 and R4 F6 DB tests are removed, section 5.3).

**R46. The chooser preselects the Annex IV default for a first card; the previous card's form after that.**
- A14 is kept; it does not conflict with decision 1.
- Given a project with no card, when `preselect(options, {fromFormVersionId: null, fromFormListed: false})`
  runs, then it returns `{param: "form", id: "annex-iv-default"}`, whatever the order of `options`.
- Given the latest card was filled with a version of a listed form F, then it returns
  `{param: "form", id: F}` (unchanged). Given an unlisted version U, then `{param: "formVersion", id: U}`
  (unchanged). Given a legacy card (`formVersionId` NULL, so `fromFormVersionId` is `annex-iv-default-v1`),
  then `{param: "form", id: "annex-iv-default"}`.
- Given options that do not contain `annex-iv-default` (a database without the seed) and no previous card,
  then it returns the first option; given no options, `null` (unchanged).
- Given the edit page with no parameters and a first card, then the chooser receives
  `preselected = {param: "form", id: "annex-iv-default"}`.
- Tests: `test/unit/formChooser.test.ts` (vitest, updated to the new signature), `test/unit/editSystemPage.test.tsx`
  (vitest, updated).

### B. One install-wide library

**R47. No form is scoped to a project.**
- Given `prisma/schema.prisma`, then the models `Form`, `FormVersion`, `FormQuestion` and
  `FormVersionQuestion` have no field whose name contains `project` (case-insensitive), and neither
  migration file creates a column whose name contains `project` on the four form tables.
- Given `src/server/services/FormService.ts` and `src/server/repositories/FormRepository.ts`, then no
  public method has a parameter named `project` or `projectId` (source scan over their method signatures),
  and neither file contains `projectId` or `project_id`.
- Given a form saved while working in project A (`saveForm("a", ...)`), when project B's chooser options,
  library and builder groups are read, then they contain it; and `resolve(<its version id>)` returns it with
  no project argument.
- Tests: `test/unit/formsDefaultIsFixed.test.ts` (source scans; same new file as R44),
  `test/unit/FormService.test.ts` (fake repository), `test/unit/formActions.test.ts` (save in "a", read the
  service the way project "b"'s pages do).

**R48. The forms pages stay under `/p/[project]/forms`; the project is navigation context only.**
- The routes of 01-spec 5.3 stay where they are, so every existing link keeps working and
  `src/middleware.ts` (unchanged) keeps being the access door: GET for any member of the project in the URL,
  POST only with `may_write`. Moving them out of `/p/` would need a new access rule; not done.
- Given the library page for project "a" and for project "b" with the same mocked `formService`, then both
  render the same rows in the same order; the only differences are the `/p/a/...` and `/p/b/...` prefixes of
  the links.
- Given the library page, then its intro paragraph contains exactly the sentence
  "Every project on this install sees the same forms." and the sentence
  "A new AI card starts with the Annex IV default."
- Given `saveForm` or `useFormOnce` called with project "b", then the redirect goes to
  `/p/b/system/edit?...` (unchanged behaviour, now pinned).
- Tests: `test/unit/FormsPage.test.tsx`, `test/unit/formActions.test.ts`.

**R49. A "Forms" link in the site header.**
- Given `SiteHeader` rendered with `project="demo"`, then the nav holds, in this order, "← Back",
  "AI system", "Versions", "Forms", "Methodology", and "Forms" links to `/p/demo/forms`.
- Given `SiteHeader` without a project, then there is no "Forms" link (the forms pages need a project for
  their access door and their links).
- Tests: `test/unit/SiteHeader.test.tsx` (vitest, jsdom, new; `launcherUrl` reads its env as today, set in
  the test).

### C. Export and import

**R50. CSV export format (exact).**
- Function `export_form(form: dict, fmt: str) -> ExportedFile` in `services/prefill/prefill/form_export.py`,
  pure; `ExportedFile` is a dataclass `(filename: str, content_type: str, content: str)`. `form` is
  `{"name": str, "version": int, "questions": [{"text", "citation", "required", "annexPoint"}]}`.
- `collapse(s)` = `" ".join(s.split())`, applied to name, text and citation before writing.
- For `fmt == "csv"`, `content` is:
  1. the character U+FEFF (byte order mark, so spreadsheet programs read UTF-8), then
  2. the header row `question,citation,required,annex_point`, then
  3. one row per question in position order: text, citation, `yes` or `no`, the point id (`1a`, `1de`, ...)
     or empty,
  written with Python's `csv.writer` default dialect (`excel`: comma, `"` quoting only where needed, `"`
  doubled inside a quoted field, `\r\n` after every row including the last).
- Formula guard: a text or citation cell whose first character is `=`, `+`, `-` or `@`, or whose first
  character is `'` and second is one of those four, is written with one extra `'` in front.
- Amended 2026-09-25 (G1, product owner: the round trip must be exact): the guard applies to any cell matching `^'*[=+\-@]` (any run of `'`, then a formula character), because guarding only zero or one `'` let `''=x` come back as `'=x`; every example above is unchanged.
- Example: questions ("Who signs off a model release?", "Acme AI Policy §4.2", required, null) and
  ("=Is SUM(A1) ok, or not?", "", optional, "2a") give exactly
  `﻿question,citation,required,annex_point\r\nWho signs off a model release?,Acme AI Policy §4.2,yes,\r\n"'=Is SUM(A1) ok, or not?",,no,2a\r\n`.
- `content_type` is `text/csv; charset=utf-8`.
- Tests: `services/prefill/tests/test_form_export.py` (pytest, prefill, new).

**R51. Markdown export format (exact).**
- For `fmt == "md"`, `content` is these lines joined with `\n`, ending with one `\n`:
  1. `# <collapsed name> (v<version>)`
  2. empty line
  3. `<!-- Exported from the AI System Qualification form library. Import this file to make a new form with these questions. -->`
  4. empty line
  5. `| Question | Citation | Required | Annex IV point |`
  6. `|---|---|---|---|`
  7. one row per question: `"| " + " | ".join(cells) + " |"` with cells = text, citation, `yes`/`no`, point
     id or empty, each escaped: `\` becomes `\\`, then `|` becomes `\|`.
- No formula guard in Markdown.
- Example: form "Acme AI policy" v3 with ("Who signs off | approves?", "", required, "2a") gives exactly
  `# Acme AI policy (v3)\n\n<!-- Exported ... -->\n\n| Question | Citation | Required | Annex IV point |\n|---|---|---|---|\n| Who signs off \| approves? |  | yes | 2a |\n`.
- `content_type` is `text/markdown; charset=utf-8`.
- Tests: `services/prefill/tests/test_form_export.py`.

**R52. File name.**
- `filename = f"{slug(name)}-v{version}.{ext}"`, `ext` `csv` or `md`. `slug`: Unicode NFKD, drop combining
  marks, lowercase, every run of characters outside `[a-z0-9]` becomes one `-`, strip `-` at both ends, cut
  to 60 characters, strip trailing `-` again; an empty result is `form`.
- Examples: ("Annex IV default", 1, csv) gives `annex-iv-default-v1.csv`; ("Acme AI policy §4", 3, md) gives
  `acme-ai-policy-4-v3.md`; ("Ärzte-Fragen", 1, csv) gives `arzte-fragen-v1.csv`; ("§§", 2, md) gives
  `form-v2.md`; ("Custom questions: MCAS, 2026-09-25", 1, csv) gives
  `custom-questions-mcas-2026-09-25-v1.csv`.
- The filename is always ASCII, so the TS route puts it in `Content-Disposition` without encoding.
- Tests: `services/prefill/tests/test_form_export.py`.

**R53. The importer reads what the exporter writes.**
Changes to `services/prefill/prefill/form_import.py`; every existing R24 to R27 rule and test stays as is
unless named here.
- Annex column: header names (lowercased, trimmed) `annex_point`, `annex point`, `annex iv point`, `annex`
  name the Annex column, in CSV headers, Markdown table headers and .docx table headers. Without a header row
  there is no Annex column (the existing "extra columns are ignored" rule stays).
- Annex value: trimmed and lowercased; empty is `None`; one of the 14 ids in `ANNEX_POINT_IDS` is that id;
  anything else is `None` plus the warning
  `The Annex IV point on line <L> ("<trimmed value>") is not one of the 14 and was left blank.`
  Checked only for questions that are kept (after the length and duplicate rules), in line order with the
  other per-line warnings. Paragraph and list-line questions (no table) have `annexPoint = None`.
- CSV formula guard, the inverse of R50: in CSV only, a question or citation cell whose first character is
  `'` and second one of `=`, `+`, `-`, `@` loses that first `'`. Markdown and .docx cells are not touched.
- Amended 2026-09-25 (G1, product owner: the round trip must be exact): the importer strips exactly one `'` from any cell matching `^'+[=+\-@]`, the exact inverse of the amended R50 guard, so `''=x`, `'''+y` and the like round-trip unchanged.
- Markdown table cells: a table line is split into cells on `|` characters that are not escaped; reading
  left to right, `\\` is a literal `\`, `\|` is a literal `|`, and any other `\` is kept as it is. The
  leading and trailing `|` of the line are removed first, as today.
- `required`: `no` stays false (already true today: every value outside the true set is false).
- `ImportedQuestion` gains `annex_point: str | None`; `POST /forms/import` returns each question as
  `{"text", "citation", "required", "annexPoint"}`.
- `ANNEX_POINT_IDS` in `prefill/fields.py` equals, in order, the ids of `src/data/annexPoints.json`.
- Tests: `services/prefill/tests/test_form_import.py` (extended), `services/prefill/tests/test_app.py`
  (extended: the response key), `services/prefill/tests/test_fields.py` (extended: `ANNEX_POINT_IDS`
  against the repo JSON, read from `../../src/data/annexPoints.json` relative to `services/prefill`).

**R54. Export then import round-trips to an equal form.**
- Definition. Two question lists are **equal** when they have the same length and, position by position,
  `collapse(text)`, `collapse(citation)`, `required` and `annexPoint` are equal (exact string and value
  equality). Not compared, and not carried by the file: the form's name, description, blocks, question
  identities (scope, local id, owner, copies), `groupLabel`, and version history. An import always makes a
  new form whose questions are its own (01-spec R28), with all 9 blocks (A10) and the name prefilled from
  the file name (so a round trip of "Annex IV default" v1 is prefilled `annex-iv-default-v1`, which cannot
  clash with the original's name).
- Precondition: the form's question texts are pairwise distinct after lowercasing and `collapse`. When they
  are not, the importer's duplicate rule (R27) keeps the first and warns "Removed N duplicate question(s).",
  and the lists are not equal; export does not refuse such a form.
- Given each of these forms, when `parse_form_file(export_form(f, fmt).content.encode("utf-8"), export_form(f, fmt).filename)`
  runs for `fmt` in `csv` and `md`, then the imported questions equal `f`'s questions, and the only warning
  is, for `md`, "Skipped 1 heading." (for `csv`: none):
  1. the 14 Annex IV default questions, from the committed fixture
     `services/prefill/tests/fixtures/annex_iv_default_form.json`;
  2. a form of 200 questions, one of them 2000 characters long with a 200-character citation;
  3. texts and citations holding `,`, `"`, `;`, `|`, `\`, `\|`, `[x]` at the end, `§`, non-ASCII letters,
     a leading `=`, `+`, `-`, `@`, a leading `'=`, internal newlines and double spaces (compared after
     `collapse`);
  4. empty citations, every required/optional mix, and every one of the 14 points plus `null`;
  5. a form with zero questions (CSV: header only; Markdown: header and separator only; both import to
     `found: 0`).
- Given `services/prefill/tests/fixtures/annex_iv_default_form.json`, then its `questions` equal
  `annexDefaultVersion().questions` mapped to `{text, citation, required, annexPoint}` in order, and its
  `name` is "Annex IV default" and `version` 1 (so the Python fixture cannot drift from `KEY_QUESTIONS`).
- Tests: `services/prefill/tests/test_form_export.py` (pytest, the round trip),
  `test/unit/annexDefaultExportFixture.test.ts` (vitest, the fixture agrees with the TS default, new).

**R55. `POST /forms/export` on the prefill service.**
```
POST /forms/export   application/json
  {"format": "csv" | "md",
   "form": {"name": str, "version": int >= 1,
            "questions": [{"text": str, "citation": str, "required": bool, "annexPoint": str | null}]}}
-> 200 {"filename": str, "contentType": str, "content": str}
-> 422 {"detail": ...}
```
- 422 with detail exactly `format must be csv or md` for any other format; `question <n> names an Annex IV
  point that does not exist` (1-based) for an `annexPoint` outside `ANNEX_POINT_IDS`;
  `a form has at most 200 questions` for more than 200; the pydantic default detail for a missing or
  mistyped field.
- Stores nothing, reads no file, calls no model.
- Tests: `services/prefill/tests/test_app.py` (extended, `TestFormExportEndpoint`).

**R56. `FormExportClient` never throws.**
- New `src/server/services/FormExportClient.ts`: `FormExportClient(baseUrl = process.env.PREFILL_URL ?? "", fetchImpl = fetch)`,
  `write(form: ResolvedFormVersion, format: "csv" | "md"): Promise<{ok: true; filename; contentType; content} | {ok: false; status: 502 | 503; error}>`.
  It sends `{format, form: {name: formName, version: versionNumber, questions: [{text, citation, required, annexPoint}]}}`
  in position order.
- `PREFILL_URL` unset: `{ok: false, status: 503, error: "Exporting forms is not available on this install."}`
  and fetch is not called. Fetch throws: `{ok: false, status: 502, error: "The form writer could not be reached."}`.
  Any non-200, or a 200 whose body is not JSON with the three string keys:
  `{ok: false, status: 502, error: "The form could not be exported."}`.
- Tests: `test/unit/FormExportClient.test.ts` (vitest, fake fetch, new).

**R57. The export route.**
- New route handler `src/app/p/[project]/forms/[formId]/export/route.ts`, GET only:
  `/p/<project>/forms/<formId>/export?format=csv|md[&version=<n>]`.
- `FormService.exportable(formId, versionNumber?)`: the form's version with that number, or its latest when
  the number is absent; `null` when the form or the number does not exist. Works for every form: builtin,
  listed, and unlisted (use-once).
- `format` missing or not `csv`/`md`: 400, body `format must be csv or md`. `version` present but not a
  positive integer, or naming no version of the form, or an unknown `formId`: 404, body `Not found`.
  `FormExportClient` failure: its `status` and `error` as the body.
- 200: body = UTF-8 bytes of `content` exactly (including the BOM for CSV), headers
  `Content-Type: <contentType>`, `Content-Disposition: attachment; filename="<filename>"`,
  `Cache-Control: no-store`.
- Access: the route is under `/p/:project`, so `src/middleware.ts` (unchanged) allows GET to any member of
  that project, viewers included, and refuses strangers. Forms are install-wide, so a member of any project
  can export any form.
- Tests: `test/unit/formExportRoute.test.ts` (vitest, mocked `formService` and `FormExportClient`, new).

**R58. Where the export buttons are.**
- Library page (`/p/<project>/forms`): each row's actions become, in order: "Start from", "Edit" (not for
  the builtin form), "Export CSV", "Export Markdown". The two export links point at the row's latest
  version: `/p/<project>/forms/<encodeURIComponent(formId)>/export?format=csv&version=<N>` (and `md`), with
  the `download` attribute. The builtin "Annex IV default" row has both.
- A new thin component `src/app/p/[project]/FormLine.tsx`, props `{project, formId, formName, versionNumber}`,
  renders `<p className="qf-row-form">Form: <name> v<N> · <a>CSV</a> · <a>Markdown</a></p>`; the links
  have `aria-label` `Export <name> v<N> as CSV` / `Export <name> v<N> as Markdown` and the hrefs above for
  that exact version. The card page (`qualify/[id]/page.tsx`) and the edit page (`system/edit/page.tsx`)
  render it in place of their current "Form:" paragraph, so a card filled with a use-once form, or a legacy
  card (Annex IV default v1), can export the very version it was filled with.
- Tests: `test/unit/FormsPage.test.tsx`, `test/unit/FormLine.test.tsx` (vitest, jsdom, new).

**R59. An imported file's Annex tags reach the builder.**
- `FormImportClient` maps each question's `annexPoint` through `isAnnexPoint` (anything else becomes
  `null`).
- The import preview (01-spec R28) gains, per row, a select labelled "Answers Annex IV point" with "None"
  plus the 14 points by citation (the R19 options), preselected from the file; the chosen value travels
  into the builder's `{kind: "own"}` row.
- Given the CSV of R50's example imported and confirmed, then the builder's rows are own rows with
  `annexPoint` `null` and `"2a"`, `required` true and false.
- Tests: `test/unit/FormImportClient.test.ts` (extended), `test/unit/FormImport.test.tsx` (extended).

### D. F3: picked questions are pinned

**R60. A pick names the version its wording comes from.**
- `DraftQuestion` pick is `{kind: "pick", questionId, fromVersionId}`; `parseFormDraft` refuses a pick
  without a string `fromVersionId` with "The form could not be read." (the zod shape error).
- `FormService.saveDraft`: for a pick, load version `fromVersionId`; when it does not exist, or holds no
  snapshot of `questionId`, refuse with "Question <n> no longer exists."; otherwise copy that snapshot
  (text, citation, required, annexPoint, groupLabel) verbatim. The version may belong to any form (the
  owner's version the question was picked from, or the saved form's own latest version when it already
  carries the question). 01-spec R22's "most recent wording in its owner form" rule is removed, and
  `FormService.latestSnapshot` with it.
- Given form G v1 with q1 "A", F picks q1 from G v1 and is saved; G is saved as v2 with q1 "B"; then F's
  latest version still says "A".
- Tests: `test/unit/formDraft.test.ts`, `test/unit/FormService.test.ts` (both updated).

**R61. `sameContent` compares pinned wording.**
- A draft pick equals the version's question at the same position when `questionId` is equal **and** the
  snapshot at `fromVersionId` equals the version's snapshot in text, citation, required, annexPoint and
  groupLabel (exact equality). `sameContent(draft, version, snapshots)` gets a third argument,
  `snapshots: Map<string, snapshot>` keyed `${fromVersionId}:${questionId}`, filled by `saveDraft` before the
  comparison (the function stays pure).
- Given F edited and saved with no change, then no new version (`created: false`), even when the owner has
  a newer wording (this is the F3 scenario: the pin holds).
- Given F edited with one pick switched to the owner's newer version (R64), then a new version is created
  with the new wording.
- Tests: `test/unit/formDraft.test.ts`, `test/unit/FormService.test.ts`.

**R62. Where each pick is pinned.**
- Ticking a question in the left column pins it to its group's `versionId` (the owner's latest version).
- "Start from S" pins every question to S's latest version id (so a question S had itself pinned to an older
  wording keeps that wording).
- Opening `/forms/<F>/edit` pins every pick row to F's latest version id.
- `toDraft` emits `fromVersionId` for every pick.
- Tests: `test/unit/builderState.test.ts` (updated), `test/unit/FormService.test.ts` (`libraryGroups`
  carries `versionId`).

**R63. "Source updated" is detected by a pure function.**
- `sourceUpdates(rows: BuilderRow[], library: LibraryGroup[]): Record<number, {question: ResolvedQuestion; versionId: string}>`
  in `src/domain/forms/library.ts`, keyed by row index. A pick row is listed when the library has a group
  with `formId` equal to the pinned question's `ownerFormId` whose `questions` contain the same
  `questionId` with a snapshot different (text, citation, required, annexPoint, groupLabel) from the pinned
  one; the value is that question and the group's `versionId`.
- Not listed: own and copy rows; picks whose owner is not in the library (unlisted owners never get a
  second version; the builtin never changes); picks whose owner dropped the question from its latest
  version; picks whose wording is the same.
- Tests: `test/unit/formLibrary.test.ts` (extended).

**R64. The builder shows it and offers the new wording.**
- A listed pick row shows a chip `span.qf-tag` with text exactly "Source updated", a paragraph
  `p.qf-new-wording` "New wording: <new text>", and a button "Use new wording" with `aria-label`
  `Use the new wording of <first 40 characters of the pinned text>`.
- Pressing it dispatches `{type: "takeLatest", index, question, versionId}`: the row's `source` becomes
  `question` and `fromVersionId` becomes `versionId`; the chip, paragraph and button disappear. On any row
  that is not a pick the action returns the state unchanged.
- Saving an existing form after taking a new wording makes its next version (R61), so cards filled with
  earlier versions keep the old wording (R6).
- Tests: `test/unit/builderState.test.ts`, `test/unit/FormBuilder.test.tsx` (extended).

### E. F4: coverage on every card

**R65. Coverage counts optional points left blank (exact strings).**
- In `coverage(form, answers)`: a point `p` is **optional left blank** when it is not covered, the version
  has at least one question with `annexPoint == p`, and none of those questions is `required`.
  `annex.optionalBlank` is the number of such points.
- `summary` = `"Annex IV coverage: <c> of 14 points"`, then `" (<b> optional left blank)"` only when
  `b > 0`, then for each `forms` entry `"; <name>: <a> of <t> answered"`, then `"."`. The word "optional"
  never takes a plural.
- Exact cases:
  - default form, all 14 answered: `Annex IV coverage: 14 of 14 points.`
  - default form, the four optional points (1b, 1f, 2d, 2f) blank: `Annex IV coverage: 10 of 14 points (4 optional left blank).`
  - default form, only 1f blank: `Annex IV coverage: 13 of 14 points (1 optional left blank).`
  - policy-only form, 18 answered, 3 tagged (1a, 2a, 2g, all answered), 11 points never asked:
    `Annex IV coverage: 3 of 14 points; Acme AI policy: 18 of 18 answered.` (points not asked are not
    mentioned)
  - the same form with the optional question tagged 2g left blank:
    `Annex IV coverage: 2 of 14 points (1 optional left blank); Acme AI policy: 17 of 18 answered.`
  - a form with no questions: `Annex IV coverage: 0 of 14 points.`
  - a legacy card whose required tagged question is blank (possible only for rows stored before a rule
    change): that point is neither covered nor counted as optional left blank.
- `optionalBlank` travels through `build_view` unchanged into the card, `ai-card.json` and the PDF model.
- Tests: `services/ontology/tests/test_coverage.py` (extended and updated, section 5.3),
  `services/system_card_renderer/tests/test_form_coverage.py` (extended: a payload with `optionalBlank`
  validates; one without it defaults to 0).

**R66. Legacy cards keep the coverage line and the "Form:" line.**
- 01-spec section 9.1's "card view ... identical to today's" is replaced by: a legacy card
  (`form_version_id IS NULL`) is exported with the default version (as implemented in
  `OntologyService.exportOf`), so its card, `ai-card.json` and PDF show the coverage summary of R65, and the
  card page shows the `FormLine` "Form: Annex IV default v1". Its answered form, graph and graph digest stay
  identical (01-spec R7 unchanged).
- Given a legacy card with 1b, 1f, 2d, 2f blank, then `VerticalCard` shows
  `Annex IV coverage: 10 of 14 points (4 optional left blank).` as `p.qf-coverage`.
- Tests: `test/unit/VerticalCard.test.tsx` (extended), `test/unit/FormLine.test.tsx`,
  `services/ontology/tests/test_coverage.py`.

### F. F7: use-once forms have unique names; coverage groups by id

**R67. The use-once name.**
- Pure `useOnceFormName(systemName: string, today: Date, taken: string[]): string` in
  `src/domain/forms/useOnceName.ts`:
  1. `s` = `systemName` with whitespace collapsed and trimmed; empty becomes `unnamed system`; cut to 80
     characters, then trimmed at the end.
  2. `d` = `today` as `YYYY-MM-DD` in UTC.
  3. `base` = `Custom questions: <s>, <d>`.
  4. If no entry of `taken` equals `base` case-insensitively (after trim), return `base`; otherwise return
     `<base> (<n>)` for the smallest integer `n >= 2` not taken the same way.
- Examples: ("MCAS", 2026-09-25T23:30Z, []) gives `Custom questions: MCAS, 2026-09-25`; the same with
  `taken = ["custom questions: mcas, 2026-09-25"]` gives `Custom questions: MCAS, 2026-09-25 (2)`; with
  that and `(2)` taken, `(3)`. The longest result (80-character name, `(999)`) is 116 characters, inside the
  120 limit.
- Tests: `test/unit/useOnceName.test.ts` (vitest, new).

**R68. `useFormOnce` names the form with it.**
- `useFormOnce(project, draftJson, origin?)` reads the system name as the `name` of
  `platformClient.latestVersion(project)`; when that is null or the call throws, it uses the `project`
  argument. It passes it as `saveDraft(draft, {listed: false, origin, systemName})`.
- `saveDraft` with `listed: false` ignores the draft's name and uses
  `useOnceFormName(systemName, now(), <names of every form, listed or not>)`.
- The old unlisted forms named plain "Custom questions" stay as they are (names are fixed, A12).
- Two use-once saves racing in the same instant may get the same name: no database index prevents it
  (**ASSUMED (B6)**). Nothing depends on the name being unique: coverage groups by id (R69).
- Tests: `test/unit/FormService.test.ts` (updated: two saves get `...` and `... (2)`; the old test "may
  repeat that name" is replaced), `test/unit/formActions.test.ts` (updated: platform mocked; platform
  failure falls back to the project).

**R69. Coverage and "Additional documentation" group by owner form id.**
- `toExport` adds `ownerFormId` to every `form.questions[]` entry.
- In `coverage.py`, `_owners_in_order` groups by `ownerFormId` when the question has that key, and by
  `ownerForm` (the name) when it does not (payloads built by older callers and existing tests). Each
  `forms` entry and each `additionalDocumentation` section still shows the owner's name; the shapes are
  unchanged.
- Given two different owner ids that share the name "Custom questions", then `forms` has two entries and
  `additionalDocumentation` two sections, each with its own questions.
- Tests: `services/ontology/tests/test_coverage.py` (extended), `test/unit/QualificationExporter.test.ts`
  (extended).

### G. F8: .docx expansion cap

**R70. A .docx may expand to at most 50 MiB.**
- New `check_docx_expansion(raw: bytes) -> None` in `services/prefill/prefill/documents.py`, called by
  `documents._from_docx` and `form_import._from_docx` before `docx.Document`.
- The limit is `PREFILL_MAX_UNZIPPED_BYTES`, read from the environment at call time, default `52428800`
  (50 MiB).
- The check opens the bytes with `zipfile.ZipFile`; a `zipfile.BadZipFile` becomes
  `DocumentUnreadable("this .docx could not be read: <exception text>")` (the existing message pattern). It
  sums `ZipInfo.file_size` over `infolist()`; when the sum is greater than the limit it raises
  `DocumentUnreadable("this .docx expands to more than <limit> bytes when unpacked; remove embedded media or split it")`,
  with `<limit>` the configured limit in bytes (default text: `... more than 52428800 bytes ...`), the same
  wording style as the existing 413 detail "the file is larger than <n> bytes". (The declared sizes are a sound bound: Python's
  `zipfile` stops reading a member at its declared size.)
- Both endpoints turn it into 422 with that detail (`/forms/import` and `/prefill` already map
  `DocumentUnreadable` to 422).
- Given a .docx built in the test whose members declare 51 MiB in total (a highly compressible member of
  zeros), then both readers raise the message and `docx.Document` is never called; given a normal .docx, no
  change; given `PREFILL_MAX_UNZIPPED_BYTES=1000` in the environment, a small .docx is refused with
  "... more than 1000 bytes when unpacked; ...".
- Tests: `services/prefill/tests/test_documents.py` (existing, extended), `services/prefill/tests/test_form_import.py`,
  `services/prefill/tests/test_app.py` (422 on both endpoints).

### H. Form parameters

**R71. `?formVersion` wins over `?form`.**
- Pure `pickFormParams({example, form, formVersion})` in `src/domain/forms/chooser.ts` returns which lookup
  the edit page does; the page then shows the chooser with the error when the lookup finds nothing. Empty
  strings count as absent.

| `?example` | `?formVersion` | `?form` | Result |
|---|---|---|---|
| known | any | any | the default version, no chooser (unchanged) |
| absent or unknown | known | any (absent, known, unknown, or another form) | that version; `?form` is ignored, no message |
| absent or unknown | unknown | any | the chooser with "That form was not found." and the usual preselection (R46); no fallback to `?form` |
| absent or unknown | absent | known | that form's latest version |
| absent or unknown | absent | unknown | the chooser with "That form was not found." and the usual preselection |
| absent or unknown | absent | absent | the chooser, no message |

- Tests: `test/unit/formChooser.test.ts` (`pickFormParams`, every row), `test/unit/editSystemPage.test.tsx`
  (updated: the precedence test flips; one test per row).

### I. MCAS covers 14 of 14

**R72. The worked example answers 1(f) everywhere.**
- `src/data/examples/mcas.ts` and `scripts/seed_mcas.mjs` already answer 1(f): no change.
- `services/ontology/examples/mcas.qualification.json`: insert
  `{"toolId": "annex-1", "questionId": "1f", "answer": <the exact 1(f) text of mcas.ts>}` right after the
  `1de` answer (so the list follows `KEY_QUESTIONS` order). Nothing else in the file changes.
- Regenerate `services/ontology/examples/mcas.ttl` and `mcas.jsonld` from the new JSON with the documented
  CLI (from `services/ontology`):
  `python -m airo_min.build examples/mcas.qualification.json --extracted examples/mcas.extracted.json --format turtle --out examples/mcas.ttl`
  and the same with `--format json-ld --out examples/mcas.jsonld`. The graph grows from 409 to 413 triples
  (measured on 2026-09-25 with the current builder); the view's node count stays 59.
- `services/ontology/README.md` examples table: "13 Annex IV answers" becomes "14 Annex IV answers" and
  "295 triples" (already stale) becomes "413 triples".
- New agreement check: the set of `toolId:questionId` keys and the 1(f) text in the JSON equal those of
  `MCAS` in `mcas.ts` (its `q:` answer fields) and of `ANSWERS` in `scripts/seed_mcas.mjs`.
- Then the committed MCAS export with the default form gives `Annex IV coverage: 14 of 14 points.`
- Existing tests that pin the old example and must be updated deliberately, with these new values:

| Test | Now | After |
|---|---|---|
| `services/ontology/tests/test_example_mcas.py::test_the_export_fills_every_new_form_element` | `len(answers) == 13` | `== 14` (comment: every sub-item answered) |
| `services/ontology/tests/test_example_mcas.py::test_each_answer_is_labelled_with_its_annex_iv_citation` | `len(citations) == 13` | `== 14`, and asserts `"Annex IV(1)(f)"` is present |
| `services/ontology/tests/test_example_mcas.py::test_the_committed_turtle_matches_what_the_builder_produces` and `test_the_committed_jsonld_is_the_same_graph` | pass against 409-triple files | unchanged code; pass only once the two files are regenerated |
| `services/ontology/tests/test_roundtrip.py::test_the_rebuilt_graph_keeps_the_annex_iv_answers` | `13` texts, `9697` characters | `14`, `9996` (9697 + 299, the 1(f) text's length) |
| `services/ontology/tests/test_coverage.py::test_r34_a16_the_committed_mcas_export_skips_1f_so_it_covers_13` | the committed JSON, 13 of 14 | build the 1(f)-less case explicitly (remove the 1f answer from a copy) and expect `Annex IV coverage: 13 of 14 points (1 optional left blank).`; rename to `..._without_1f_covers_13_with_one_optional_blank` |
| `services/ontology/tests/test_coverage.py::test_r34_with_a_form_the_view_carries_form_and_coverage` | `13 of 14 points.` | `Annex IV coverage: 14 of 14 points.` |
| `services/ontology/tests/test_coverage.py::test_r34_the_mcas_example_as_the_form_has_it_covers_all_14` | appends a 1f answer | uses the committed JSON as it is (no append); still 14 of 14 |

- No test pins a literal MCAS graph digest (checked: `test_form_answers.py` and `test_graph.py` compare
  digests with each other only), so no digest constant changes. Stored `knowledge_graph` rows of seeded
  MCAS cards are built from the database, whose seed already has 1(f): nothing changes there.
- Tests: `test/unit/mcasExampleAgrees.test.ts` (vitest, new: reads the JSON and `scripts/seed_mcas.mjs`'s
  exported `MCAS_SEED` or its `ANSWERS` through the module, and `MCAS` from `mcas.ts`), the updated
  ontology tests above.

### J. Access and no model

**R73. The new parts call no model and follow the project door.**
- `test/unit/formsNoModel.test.ts` (extended) scans also `FormExportClient.ts`,
  `forms/[formId]/export/route.ts`, `FormLine.tsx`, `src/domain/forms/useOnceName.ts`: none imports
  `FillerClient` or `services/llm`, and the only env names read are `PREFILL_URL` and `PLATFORM_URL`.
- Amended 2026-09-25 (product owner): `QUALIFICATION_WEB_TO_PREFILL_TOKEN` is also allowed, because R73's intent is no model credentials in the forms code and that is a service-to-service token (8f0ab50: prefill refuses a caller without it), not a model credential.
- `services/prefill/tests/test_form_export.py::test_r73_*`: `form_export.py` imports only the standard
  library and `prefill` modules (AST scan, like `test_form_import.py::test_r41_*`).
- Access is 01-spec R42 minus its `setDefaultForm` bullet: GET (library, builder pages, export) for any
  project member; POST (save, use once, import confirm) with `may_write`. There is no admin-only action left.
- Tests: `test/unit/formsNoModel.test.ts`, `services/prefill/tests/test_form_export.py`,
  `test/unit/formActions.test.ts` (the R42 tests stay; the R4 ones go).

---

## 5. Superseded items of `01-spec.md` (and the test and plan notes that go with them)

### 5.1 Requirements and sections

| Item | Status | By |
|---|---|---|
| 3 Vocabulary, "Builtin form ... Read-only" | kept; add "and always the default" | R43 |
| 4.1 `Form.isDefault` | removed | 3.3 |
| 4.2 `form_one_default`, `CHECK (NOT is_default OR listed)`, `form_name_is_fixed` "Only `is_default` and `description` may change" | removed / replaced; only `description` may change | 3.2 |
| 4.3 step 2 seed `is_default=true` | stays in 090000 (unedited), undone by 120000 | 3.1, 3.2 |
| 5.1 `FormService.chooserOptions(project)`, `setDefault(project, formId)` | `chooserOptions()` with no argument; `setDefault` removed | 3.4, R44, R47 |
| 5.1 `FormImportClient` result questions | gain `annexPoint` | R59 |
| 5.3 route table: `/forms` "Set as default" (admins only); `setDefaultForm` row; `useFormOnce` name `"Custom questions"`; `?form` / `?formVersion` rows | removed; name from R67; precedence R71 | R44, R67, R71 |
| 5.3 `POST /forms/import` response | gains `annexPoint` | R53 |
| R3 "the default first, then builtin, then the rest" | Annex IV default first, then by name (the only builtin is the default) | R43 |
| R4 entirely | removed | R44 |
| R6 third bullet "identical snapshots" | now enforced for picks through the pinned version | R61 |
| R8 first two bullets (org default "Acme AI policy" checked) | default is always Annex IV; `preselect` signature | R46 |
| R8 fourth bullet (`?form=<unknown>` or `?formVersion=<unknown>`) | detailed by the table | R71 |
| R16 groups | gain `versionId`; pick pins it | R62 |
| R17 "every question as pick" | picks pinned to S's latest version | R62 |
| R22 "Use once" named "Custom questions" | unique name | R67, R68 |
| R22 "A `pick` takes its snapshot ... from the most recent ... row in its owner form's versions; the draft's own wording for a pick is ignored" | a pick takes the snapshot of its `fromVersionId` | R60 |
| R24, R25, R26 header rules | add the Annex column; CSV `'` guard; Markdown `\|` escape | R53 |
| R27 | adds the Annex warning; .docx expansion cap | R53, R70 |
| R28 preview | adds the Annex select | R59 |
| R34 `summary` format and the MCAS example | optional-left-blank clause; MCAS JSON now has 1(f) | R65, R72 |
| R34 / R35 grouping "one entry per owner form" (by name in the code) | by owner id | R69 |
| R36 "Form: <name> v<N>" (section 7 line) | rendered by `FormLine` with export links | R58 |
| R42 second bullet (`setDefaultForm` requires admin) | removed | R73 |
| 7 UI summary, Library: "default" tag, "Set as default" | tag kept on Annex IV default; action removed; export links added | R43, R44, R58 |
| 8 Error table rows "Non-admin sets default", "Default set to unlisted/unknown" | removed; new rows: export errors (R56, R57), .docx expansion (R70) | |
| 9.1 "Their answered form, card view, graph digest and downloads are identical to today's" | answered form, graph and digest identical; card view, JSON and PDF gain the coverage line and the Form line | R66 |
| 9.8 "must keep passing unmodified: `test_example_mcas.py`" | updated deliberately (two counts), plus regenerated artefacts | R72 |
| 11 Out of scope "Exporting a form to a file" | now in scope (CSV, Markdown) | R50 to R58 |
| 11 Out of scope "Several organisations per install, or per-project private forms" | stays out of scope, now as a decision, not an assumption | R47 |

### 5.2 ASSUMED items and open questions

| Item | Status |
|---|---|
| A1 organisation = the install | **confirmed** by decision 2 |
| A4 only a platform admin changes the default | **void**: nobody changes it |
| A12 names fixed at creation | kept; the reason now also covers R68 (old "Custom questions" rows keep their name) |
| A14 previous card's form preselected, default for a first card | **confirmed**; the default is always Annex IV (R46) |
| A16 coverage counts only non-blank answers, denominator 14 | kept; the summary now says how many blanks were optional (R65) |
| A18 use-once forms named "Custom questions" | **replaced** by R67 |
| A9, A10 | kept; A10 is why round-trip equality excludes blocks (R54, B3) |
| Q1 may a project editor set the default | **closed**: nobody sets it |
| Q2 limit form visibility across projects | **closed: no**. Forms are install-wide by decision; an ownership column is not added |
| 02-tests gap 3 / plan conflict 4 (MCAS 13 vs 14) | **closed** by R72 |
| 05-verification F3, F4, F7, F8 | **closed** by R60 to R64, R65 to R66, R67 to R69, R70 |
| 05-verification section 6 "no navigation link to /p/<project>/forms" | **closed** by R49 |
| 04-progress F5 note "the test pins the implemented order (`form`)" | **reversed** by R71 |

### 5.3 Existing tests to change deliberately (not weakened: each is replaced by a test of the new rule)

- `test/unit/FormService.test.ts`: the three R4 `setDefault` tests and the two R4 F6 tests (removed; R44);
  R3 ordering tests that set a default in the fake store (now the constant, R43); R22 "a use-once form is
  unlisted, named Custom questions, and may repeat that name" (replaced, R68); R22 pick tests that expect
  the owner's latest wording (replaced by the pinned rule, R60, R61); every pick without `fromVersionId`.
- `test/unit/formActions.test.ts`: the four R4 `setDefaultForm` tests (removed); "R22 saves an unlisted form
  named Custom questions" (updated, R68).
- `test/unit/formDraft.test.ts`, `test/unit/builderState.test.ts`, `test/unit/FormBuilder.test.tsx`: picks
  and library groups gain `fromVersionId` / `versionId` (R60, R62).
- `test/unit/formChooser.test.ts`, `test/unit/FormChooser.test.tsx`, `test/unit/editSystemPage.test.tsx`,
  `test/unit/FormImport.test.tsx`: `defaultFormId` / stored `isDefault` fixtures replaced by the constant;
  `editSystemPage.test.tsx`'s precedence test flips (R71).
- `test/support/fakeFormStore.ts`: default field and `setDefault` removed; `findVersion` used for pinned
  picks.
- `test/db/forms.db.test.ts`: "R4 a second is_default row fails on form_one_default", "R4 an unlisted form
  cannot be the default" and "R4 F6 two administrators moving the default at once" (removed; replaced by the
  R45 DB tests).
- Ontology tests of R72's table.

---

## 6. Out of scope

- Exporting to .docx or PDF; importing PDF, .txt or .xlsx (A9 stands).
- Carrying a form's name, description, blocks, question identities, group labels or version history in an
  exported file; "import as a new version of an existing form"; importing a file as picks of the original
  questions.
- Exporting several forms in one file, or a whole library.
- Renaming, archiving or deleting forms (including the old "Custom questions" rows).
- A database uniqueness index on use-once names (B6).
- Per-project or per-organisation form visibility (decision 2).
- A configurable default form, per project or per install (decision 1).
- Moving the forms pages out of `/p/[project]/` (R48).
- Mentioning Annex points a custom form never asks in the coverage summary (B4).
- Notifying authors when a source form changes, outside the builder (R64 is shown only when the form is
  opened in the builder).

---

## 7. New assumptions

- **ASSUMED (B1)** Export goes through the prefill service (Python), like import; an install without
  `PREFILL_URL` cannot export (503 message, R56). Reversal: move R50 to R52 into a pure TS module and drop
  R55 and R56.
- **ASSUMED (B2)** The CSV and Markdown Annex column holds point ids (`1a`, `1de`), and the importer accepts
  only ids; a citation such as "Annex IV(2)(a)" in that column is warned about and left blank (R53).
- **ASSUMED (B3)** "Equal" after a round trip is question-level (text and citation after whitespace
  collapse, required, Annex point, order). Blocks, name, description and identities are not carried; an
  import starts with all 9 blocks (A10), so a form that had excluded blocks comes back with them included.
- **ASSUMED (B4)** Coverage names only optional points left blank; points a custom form never asks get no
  note ("3 of 14 points", not "3 of 14 points (11 not asked)"), and per-form counts ("18 of 18 answered")
  get no optional note.
- **ASSUMED (B5)** The use-once name's system name is the latest card version's name from the platform,
  or the project id from the URL when there is no version yet or the platform fails; the date is today in
  UTC.
- **ASSUMED (B6)** Use-once name uniqueness is enforced by the application (R67), not the database; two
  saves racing in the same instant may share a name, which is harmless because nothing groups by name.
- **ASSUMED (B7)** The .docx expansion limit is 50 MiB (`PREFILL_MAX_UNZIPPED_BYTES`), five times the 10 MB
  upload cap, and applies to `/prefill` as well as `/forms/import` (one shared check).
- **ASSUMED (B8)** When `?formVersion` and `?form` disagree, the version is used silently (the page's "Form:"
  line shows which one); an unknown `?formVersion` never falls back to `?form`.
- **ASSUMED (B9)** A CSV cell starting with `=`, `+`, `-` or `@` is written with a leading `'` (spreadsheet
  formula injection guard, the shared library takes text from any writer), and the importer removes it, so
  the guard is invisible after a round trip. A hand-written CSV question that really starts with `'=` loses
  the `'` on import.
- **ASSUMED (B10)** Export links are shown on the library rows and on the "Form:" line of the edit and card
  pages; there is no export button inside the builder.

---

## 8. Multi-form select and the wide builder (2026-09-25, round 3)

Product owner requests: (1) the builder pages use more of the page width; (2) "Start from" (one dropdown
and Apply) becomes a multi-select of forms. Requirements continue from R73. The gaps were filled by the
decisions marked ASSUMED (C1 to C8) at the end of this section; the owner may overrule them in flight.
Out of scope, unchanged: DB, API, server actions and their contracts, Python, the save payload
(`toDraft`), overlap hints, "Source updated" (R63, R64), blocks, the question editor, save actions.

### K. The builder is wide

**R74. The builder pages use the wide layout.**
- Given `/forms/new` or `/forms/<F>/edit`, then the page is
  `<main className="qualify-page qualify-page--wide qf-forms-page">`, the same `qualify-page--wide` class the
  compiled card page uses (widePage.test.ts). The three width rules that test pins are unchanged.
- Given `/forms/import`, then the upload and preview steps stay `qualify-page qualify-page--form qf-forms-page`
  (1080px); when "Continue with N questions" mounts the builder, the same `main` becomes
  `qualify-page qualify-page--wide qf-forms-page`. (`FormImport` renders the `main`; the page passes it the
  header, crumb included.)
- The library page `/forms` stays `qualify-page--form` (1080px).
- CSS: in the design-pass block, above 960px, `.qualify-page--wide .qf-builder` widens the form column
  (`minmax(0, 1fr) minmax(380px, 560px)`). At 960px and below the single-column rule still wins.
- Tests: `test/unit/formsLayout.test.tsx` (P1 updated, P3 new), `test/unit/widePage.test.ts` (new case).

### L. Multi-form select

**R75. The library column starts with a multi-select of forms.**
- Given the builder, then the library column's toolbar holds a `fieldset.qf-builder-forms` with legend
  "Select forms" and one checkbox per form of `forms` (every library form, library order), each inside a
  `label.qf-builder-formchip` that reads `<form name>`, then `v<N> · <count> questions` (`1 question` for one).
  The "Start from" select and its Apply button are gone.
- Given no form selected, then the column shows `p.qf-builder-prompt` "Select one or more forms to see their
  questions." and lists no question.
- Given forms selected, then the column shows one group per selected form, headed by its name, in the order
  the forms were selected, each listing that form's questions (its latest version, in position order,
  including the questions it picked from other forms) with checkbox, text and citation chip as in R16.
- Given a search query, then it filters within the selected forms only (R16's `filterLibrary` rule); with no
  form selected the prompt shows whatever the query.
- Tests: `test/unit/FormBuilder.test.tsx`, `test/unit/formsLayout.test.tsx` (B4 replaced).

**R76. Selecting a form ticks all its questions.**
- Given form S not selected, when it is selected (`{type: "selectForm", form: S}`), then S is appended to
  `state.selected`, and every question of S that is not already ticked (R16's `isTicked`: a pick or own row
  with that question id) is appended to "Your form" as a pick, in S's order, after the rows already there,
  pinned to S's latest version id (R62's "Start from" rule) and marked as coming from S (`viaFormId`).
- Given a question already ticked (through another form, a tick, or the edit page), then it is not added a
  second time and its existing row is not moved.
- Selecting changes neither the blocks nor the name. Selecting a form already selected changes nothing.
- Given S = Acme (q1, q2, q3) selected after Annex IV default (1a, 2a), then "Your form" reads 1a, 2a, q1,
  q2, q3 and the library shows the Annex IV group, then the Acme group.
- Tests: `test/unit/builderState.test.ts`, `test/unit/FormBuilder.test.tsx`.

**R77. Unselecting a form takes back what it added.**
- Given S selected, when it is unselected (`{type: "deselectForm", formId}`), then S leaves `state.selected`
  and its group leaves the column, and every pick row with `viaFormId` S is removed. Rows that stay: own
  questions, copies (a pick edited in the builder, R20, even one that came from S), and picks that came from
  another form or from a tick in another group. Unselecting a form not selected changes nothing.
- Tests: `test/unit/builderState.test.ts`, `test/unit/FormBuilder.test.tsx`.

**R78. Ticking inside a selected form.**
- Unticking a question removes its row (R16) and leaves its form selected.
- Ticking a question in S's group (`{type: "tick", question, versionId, form: S}`) adds a pick marked as
  coming from S, pinned to S's version, placed right after the last row that came from S and stands earlier
  in S's order; when none does, right before the first row from S that stands later; when S has no row, at
  the end. A tick with no `form` appends, as before.
- Given S = q1, q2, q3 selected and q2 unticked, when q2 is ticked again, then the order is q1, q2, q3.
- Tests: `test/unit/builderState.test.ts`, `test/unit/FormBuilder.test.tsx`.

**R79. Where the builder opens.**
- `/forms/new?from=<S>` (the library row's "Start from" link): S is preselected, all its questions ticked
  (R76), and the blocks are S's blocks (kept from R17). An unknown id opens the empty builder, as before.
- `/forms/<F>/edit`: nothing is ticked beyond F's current questions, which open as in R6/R62 (own rows and
  picks pinned to F's latest version). The owner forms of F's picks (`ownerFormId`, first appearance order,
  never F itself) are `state.selected`, and each such pick is marked as coming from its owner, so
  unselecting that owner removes it (R77). Only owners present in `forms` show as groups or chips.
- An import opens with no form selected and its questions as own rows.
- Tests: `test/unit/builderState.test.ts`, `test/unit/FormBuilder.test.tsx`.

**R80. The pure state keeps the selection; React stays thin.**
- `BuilderState` gains `selected: string[]`; a pick row gains optional `viaFormId`. `toDraft` output is
  unchanged (neither travels). The reducer never mutates its input.
- The right column's empty hint reads "No questions yet. Select a form in the library, or write your own."
- Tests: `test/unit/builderState.test.ts`.

### Superseded by section 8

| Item | Status | By |
|---|---|---|
| 01-spec R16 first bullet "one group per listed form ... each listing the questions that form owns" and A15 "lists each question once, under the form that owns it" | groups only for selected forms, each with all its questions; a question may show under two selected forms (ticked in both) | R75 |
| 01-spec R17 entirely (selector, Apply, replace, confirmation "Replace the N questions in your form?") | removed; selecting appends and never asks | R75, R76 |
| 01-spec R17 second bullet (`?from=<S>` opens started from S) | kept, as a preselection | R79 |
| 06 R62 second bullet "Start from S pins every question to S's latest version id" | now said of selecting S | R76 |
| 06 section 5.1 row "R17 every question as pick" | as above | R76 |
| 10-ui-plan 4.1/4.2 "one page width for the whole forms area" and the builder's `qualify-page--form` shells | builder pages go wide | R74 |
| 10-ui-plan 4.3/4.4 "Start from" toolbar (`.qf-builder-startfrom`, `.qf-builder-apply`) | replaced by `.qf-builder-forms` chips | R75 |

### New assumptions (section 8)

- **ASSUMED (C1)** With no form selected the library column shows only the prompt; search filters within the
  selected forms.
- **ASSUMED (C2)** Unselecting a form removes the untouched picks that came from it; own questions and edited
  copies stay.
- **ASSUMED (C3)** Unticking keeps the form selected; re-ticking puts the question back at its place among
  that form's rows, else at the end.
- **ASSUMED (C4)** A question already ticked is never added twice. A copy (edited pick) does not count as
  ticked, as in R20, so selecting its source form again adds the original next to the copy.
- **ASSUMED (C5)** A selected form's group lists all its questions, picked ones included (what "Start from"
  used to apply), pinned to that form's version; the owner-only `library` groups still drive "Source
  updated" and the overlap candidates.
- **ASSUMED (C6)** Selecting a form does not change the blocks; the `?from=` link still sets them from S, as
  R17 did.
- **ASSUMED (C7)** On the edit page the selected forms are the owners of F's picks.
- **ASSUMED (C8)** The chip list is every form of `forms` in library order, including the builtin default
  and, on the edit page, F itself.
