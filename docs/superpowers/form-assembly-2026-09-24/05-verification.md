# Form assembly: independent verification (stage 5)

Date: 2026-09-25. Verifier: independent agent, did not write spec, tests or code.
Code: `apps/qualification`, branch `feat/unified-modules`, HEAD `c324885` plus uncommitted working tree
(41 modified, 35 untracked paths). Nothing was modified, committed, staged, stashed or reset. The only
file written is this one.

HEAD check: the app repo stayed at `c324885` and the parent repo at `d884c52` from start to end of this
run. The parent working tree also shows `M homepage/project.html`, which no plan task names (probably
another session's; not reviewed).

## 1. Real counts vs the plan (section 6)

| Suite | Command (from `apps/qualification`) | Result | Plan expects | Match |
|---|---|---|---|---|
| vitest | `npx vitest run` | 67 files (63 passed, 4 skipped); 715 tests: 681 passed, 34 skipped, 0 failed | 63 + 4 skipped; about 681 passed, 34 skipped | yes |
| tsc | `npx tsc --noEmit` | exit 0, 0 lines of output | 0 errors | yes |
| prisma validate | dummy `DATABASE_URL` on port 1 (never connects) | "The schema ... is valid" | valid | yes |
| build | `npm run build` | exit 0, 21 routes incl. 4 `/forms` pages; 1 pre-existing font lint warning (`layout.tsx`) | (not in plan) | ok |
| ontology | venv-ontology, pytest | 224 passed, 3 failed | 224 passed, 3 failed | yes |
| prefill | `services/prefill/.venv` | 173 passed | 173 | yes |
| renderer | venv-system_card_renderer | 17 passed | 17 | yes |
| agents | venv-agents from `$P/agents-cwd` | 150 passed | 150 | yes |
| DB | `test/db/throwaway-db.sh` | 3 files, 33 tests: 30 passed, 3 failed | 34 passed | no (see 4) |

- The 3 ontology failures are pre-existing: I exported HEAD's `services/ontology` + `src/data` with
  `git archive` into the scratchpad and ran the three files there: the same 3 fail at HEAD.
- The plan's "34 DB tests" is a miscount: the files hold 33 (13 + 14 + 6).
- Docker: two DB runs through the script (one with `KEEP=1`, removed afterwards with `docker rm -f` of my
  own container). No `aisc-t-qual-*` container is left. Two `aisc-t-composer/renderer-*` containers that
  existed before I started belong to another session and were not touched. No connection to 5432/5433.

## 2. Test integrity

- `git diff --numstat` against HEAD over `test/` and `services/*/tests/*`: 11 modified files, 889
  insertions, **0 deletions**. No test file deleted (`git ls-files -d` empty). No vitest config, setup or
  existing support file changed. So no pre-existing test was weakened or removed.
- The existing tests the spec says must stay unmodified (`test_example_mcas.py`,
  `test_ontology_only_card.py`, `oneSystemEntryPoints`, `prefillOnEditPage`, `keyQuestions`,
  `projectAccess`) are unmodified and pass (except the 1 pre-existing mcas failure above).
- Spot-checked new tests (`formActions`, `QualificationService.forms`, `annexDefaultForm`,
  `QualifyFormBlocks`, `QualificationExporter` extension, `test_form_answers.py`,
  `test_form_coverage.py`, `forms.db.test.ts`): they assert concrete values, exact messages and
  "not called" spies, and would fail without the feature. No tautologies found. Mocks are at the right
  seam (service and access for actions; fake repository for FormService).
- Behaviour covered only by source-text tests:
  - the edit page's branching (`?form`, `?formVersion`, `?example`, unknown id message) is checked only by
    regex over `system/edit/page.tsx` (finding F5);
  - R41 (no model) and R42 (pages under `/p/[project]`) are source scans, acceptable for what they claim;
  - migration constraint/trigger names and "no UPDATE/DELETE" are text checks in `annexDefaultForm.test.ts`,
    but each is also exercised on a real Postgres by `forms.db.test.ts` (R4 and R7 manually, see 4).
- `test_form_answers.py` simulates the new TS export in Python (`as_new_export`); the TS side is pinned
  separately by `QualificationExporter.test.ts`. There is no single test feeding real TS output into the
  Python graph build, but both halves assert the same shape, so the digest claim holds.

## 3. Spec conformance review (by area)

Checked against the code, not only the tests.

- **R1, R2 seed and points**: the migration seed equals `annexDefaultVersion()` field by field on a real DB
  (R1 DB test passes). Python loader matches, Dockerfile gains exactly the one COPY line; no other image
  imports `airo_min`, so no image misses `annex_points.json`.
- **R3, R4 library and default**: library order and filtering correct. `setDefaultForm` checks
  `callerAccess(project).admin === true` server side before calling the service (A4); null access is
  refused. The library page hides "Set as default" for non-admins. The DB index `form_one_default` fires by
  name (confirmed with psql on the throwaway DB). Concurrency gap: F6.
- **R5 keys**: scope `f-<formId>` with `q<n>`, n = max over every question the form owns + 1, never
  reused. `formId` is a UUID (spec says cuid): matches the scope regex, harmless.
- **R6 immutability**: all five triggers exist and pass their DB tests; builtin edit page 404s; P2002 on
  save maps to the concurrency message (or the name message for a new form). Deviation: F3.
- **Coexistence with the "only the latest card changes" triggers**: the new triggers sit only on the four
  new tables. The migration adds a nullable column with no default (DDL, no row rewrite, fires no UPDATE
  trigger) and swaps an index; it never updates or deletes a history row. `formVersionId` is written only
  on INSERT of a new card, which the existing triggers allow. The new FK is RESTRICT towards
  `form_version`, and forms are never deleted, so the project-delete cascade into `qualification` is not
  blocked.
- **R7 legacy cards and live-DB safety** (read-only reasoning, no connection): `form_version_id IS NULL`
  resolves in memory to the default version. The dropped index name
  `"QualificationAnswer_qualificationId_questionId_key"` is the one created in `20260430105826` and never
  renamed (the table rename in `20260922110000` keeps index names), so it exists on any DB migrated by
  Prisma. The new unique key is weaker than the old one, so creating it cannot fail on existing rows.
  Without `IF EXISTS`, a DB whose index was named differently fails loudly and rolls back (Postgres runs a
  multi-statement script in one implicit transaction): a safe failure mode. The R7 history-digest test
  passes on a clean throwaway DB. Graph digest of existing cards: default answers keep `qual:citation` and
  `qual:questionId`; `annex_citation(id)` equals `_annex_citation` for all 14 ids; `graph_digest` is
  canonical and order-independent, so the new position ordering cannot change it. Committed `mcas.ttl` test
  still passes. Stored answers outside the version export in the legacy shape. `scripts/*.mjs` and
  seeds unchanged and keep producing NULL (default) cards.
- **R8, R9 chooser and form**: behaviour matches; see F5 for test depth.
- **R10 to R15 parser and save, identity locked**: identity (`systemName`, `systemVersion`, `company`) is
  required by the server-side parser for every version, including `blocks = []`; blocks outside
  `FORM_BLOCKS` are refused by `parseFormDraft` and by the DB CHECK, so no form can list or drop an identity
  field; the ontology service still requires the three identity fields in pydantic; `QualifyForm`,
  `AnsweredForm` and the builder ("Always included") always show them. The form definition is loaded server
  side from the posted id; unknown id is refused before the platform call; `""` description goes to the
  platform as `null`.
- **R16 to R23 builder**: reducer, overlap hints and draft validation behave as specified; overlap is
  tag-based only.
- **R24 to R28 import**: rules and messages match; `.docx` errors become 422; size limit 413 before
  parsing; Next server-action body limit is 11 MB, above the 10 MB prefill cap. Gaps: F2 (CSV field limit),
  F8 (zip expansion, pre-existing).
- **R29 to R37 graph, coverage, card, PDF**: tagged answers add `qual:annexPoint`/`qual:sourceCitation`
  only for non-seeded scopes; untagged answers are absent from the graph; unknown point gives 422;
  `hasAIUser` absence no longer raises. Coverage and additional documentation are computed once in Python
  and passed through unchanged to the card, `ai-card.json` and the PDF payload. Security gap in the PDF:
  F1. Behaviour change for legacy cards: F4.
- **R38 to R40 prefill**: without `fields`/`questions` the old path runs unchanged; the TS side sends them
  only for non-default versions.
- **R41 no model**: no new TS module imports `FillerClient` or the LLM service; the only env read is
  `PREFILL_URL`. `form_import.py` imports only stdlib, `docx`, `prefill.documents`; `coverage.py` only its
  package. No LLM call anywhere in the feature.
- **R42 access**: every new page and action is under `/p/[project]`, so the unchanged middleware refuses
  POST without `may_write`. Server actions take `project` as a client argument (same pattern as the
  existing `submitQualification`); since forms are install-wide (A1) and `admin` is a realm role, that
  opens nothing new. Redirect targets are always `/p/...` (no open redirect).

## 4. Findings

Severity: blocker / major / minor / nit. Category: A mechanical fix, B needs product owner, C unsure.

| id | sev | R-id | file:line | what is wrong | failure scenario | suggested fix | cat |
|---|---|---|---|---|---|---|---|
| F1 | major (security) | R29, R36 | `services/system_card_renderer/template_engine.py:15` (template `templates/system_card.html.j2:143-147`) | `select_autoescape(["html","xml"])` returns False for `*.html.j2` (verified in the venv), so the PDF template prints every value raw into WeasyPrint HTML. Pre-existing for answers, but the feature adds form names, question text and citations that come from an install-wide library (any writer of any project, or an imported file). | A writer in project A saves a form whose citation is `<a rel="attachment" href="file:///...">x</a>` (verified: the raw tag reaches the HTML). A user in project B fills that form; its PDF embeds a file from the renderer container (WeasyPrint's default fetcher reads `file://` and `http://`), or makes the renderer fetch internal URLs. | `autoescape=True` (or add `"j2"` to the extensions) and pass WeasyPrint a `url_fetcher` that refuses everything except the template directory. Rerun renderer tests. | A |
| F2 | minor | R27 | `services/prefill/prefill/form_import.py:108` | `csv.reader` keeps its default 131072-char field limit and `_csv.Error` is not caught. | A CSV with one cell over 128 KB (well under 10 MB) makes `POST /forms/import` answer 500 instead of the spec's "longer than 2000 characters and was skipped" warning (verified: `Error field larger than field limit (131072)`). | `csv.field_size_limit(MAX_BYTES)` in `_from_csv`, or catch `csv.Error` and raise `DocumentUnreadable` (422). Add a test. | A |
| F3 | minor | R6, R22 | `src/domain/forms/formDraft.ts:159` | `sameContent` compares a pick only by question id, while R6 says "identical snapshots" and R22 says a pick takes the owner's most recent wording. | Form F picks G's q1; G later rewords q1 in G v2. The author opens F and saves with no change: no new version, so F keeps the old wording indefinitely until some other change is made. | Either compare a pick against the owner's latest snapshot (new version when it differs), or confirm that picks are frozen at pick time and amend the spec. | B |
| F4 | minor | R34, R36, spec 9.1 | `src/server/services/OntologyService.ts:39` (`exportOf`), `qualify/[id]/page.tsx` | Legacy cards resolve to the default version and are exported with a `form`, so every legacy card now shows a coverage line and "Form: Annex IV default v1". Spec 9.1 says their card view stays identical. The implementer flagged this. | A legacy card that left the 4 "where applicable" questions blank now reads "Annex IV coverage: 10 of 14 points." to reviewers, which can read as a deficiency (A16). | Product owner decides: keep, or send no `form` for `formVersionId IS NULL` cards. | B |
| F5 | minor | R8 | `test/unit/FormChooser.test.tsx:119-133` vs `src/app/p/[project]/system/edit/page.tsx:24-76` | The page's branching (which param wins, unknown id message plus preselection, `?example` skipping the chooser) is only checked by regex over the source. | A regression such as `?formVersion` being ignored when `?form` is also present, or the error not reaching the chooser, would pass the suite. | Render test of `EditSystemPage` with mocked `formService`/`qualificationService`, as already done for `forms/[formId]/edit`. | A |
| F6 | minor | R4 | `src/server/repositories/FormRepository.ts:103-107`, `src/app/p/[project]/forms/actions.ts:77` | Two admins setting different defaults at the same time: under READ COMMITTED the second transaction's `updateMany` does not see the first's new default, so its `update` hits `form_one_default`. The error is not caught. | Rare, but the second admin gets a 500 page instead of a message. The invariant itself holds (the DB refuses). | Catch the unique violation in `setDefault` and return "That form cannot be the default." or a retry message; or lock with `SELECT ... FOR UPDATE` first. | A |
| F7 | nit | R34, R35 | `services/ontology/airo_min/coverage.py:32-38` | Owner forms are grouped by name, not id. Listed names are unique only among listed forms, and every use-once form is named "Custom questions". | A use-once form that picks questions from a listed form also named "Custom questions" shows one merged coverage line and one merged "Additional documentation" section. | Carry an owner id in the export and group by it, or reserve the name "Custom questions" for unlisted forms. | C |
| F8 | nit | R27 | `services/prefill/prefill/form_import.py:195` (and pre-existing `prefill/documents.py`) | The 10 MB cap applies to the compressed .docx; python-docx expands XML in memory without limit. | A crafted high-compression .docx can use a lot of prefill memory (pre-existing for `/prefill` too). | Check the zip's total uncompressed size before `docx.Document` (e.g. `zipfile` infolist sum below a cap). | B |

Counts: 0 blocker, 1 major, 5 minor, 2 nit. By category: A 4 (F1, F2, F5, F6), B 3 (F3, F4, F8),
C 1 (F7).

## 5. The three known DB failures (judged independently)

1. **`forms.db.test.ts` R4 "a second is_default row fails on form_one_default": the test is wrong, not the
   code.** On the throwaway DB, psql gives `ERROR: duplicate key value violates unique constraint
   "form_one_default"`. Through `prisma.$executeRawUnsafe` the error text is only
   ``Raw query failed. Code: `23505`. Message: `Key ((true))=(t) already exists.` `` and never names the
   index, so `/form_one_default/` cannot match. Fix (A, test side): assert code `23505` (or
   `/23505|already exists/`) and check the index name through `QUALIFICATION_TEST_PSQL`, as the R7 test does.
2. **`forms.db.test.ts` R7 "no row of the five history tables changes": the test is wrong (order
   dependent), not the code.** The failure is `could not create unique index
   "QualificationAnswer_qualificationId_questionId_key" ... (cmug..., q1) is duplicated`: the test's revert
   step recreates the old `(qualificationId, questionId)` index, and the earlier R5 test in the same file
   has committed `q1` under both `f-ff` and `f-gg`. Run alone on a clean throwaway DB (`KEEP=1`, then
   `-t "R7 run on a database"`), it passes: the migration leaves the five tables' digests unchanged. Fix
   (A, test side): inside the R7 transaction delete R5's `f-*` answers (or all non-`annex-*` answers)
   before recreating the old index, or give R5 distinct question ids. The underlying fact (the migration is
   not reversible once scoped duplicates exist) is expected: there are no down migrations.
3. **`cardVersions.db.test.ts` S3.3: pre-existing and the test is stale, unrelated to forms.** The file is
   unchanged against HEAD. The test inserts a card with a random `project_id`; migration
   `20260924120000_a_card_is_of_a_version_of_its_project` (commit `e0be925`, already in HEAD) added
   `Qualification_project_id_fkey`, which fires before the check the test waits for. Fix (A, test side):
   insert a `core.project` row for that id first (as `forms.db.test.ts` does), or also drop the project FK in
   the test's transaction.

With these three test fixes the DB suite would be expected at 33 passed.

## 6. ASSUMED items and open questions still needing the product owner

From the spec (section 12), none confirmed yet:

- A1 organisation = the install; the library is visible to every project on it.
- A2 the 2026-09-23 freeze on `knowledge_graph` / `qualification_risk` still holds.
- A3 no FK from answers to `form_question`; the parser keeps integrity.
- A4 only a platform admin changes the default; any project editor creates forms.
- A5 an included metadata field stays required.
- A6 reorder by buttons plus native drag, no library.
- A7 a form may have zero questions.
- A8 imported questions are optional unless the file says so.
- A9 import accepts csv, md, docx only (no PDF).
- A10 an imported form starts with all 9 blocks.
- A11 versions are append-only from creation.
- A12 form names are fixed at creation.
- A13 the builtin form is read-only in the app.
- A14 the chooser preselects the previous card's form, the default only for a first card.
- A15 the library lists each question under its owner only; use-once forms' questions are not offered.
- A16 coverage counts only non-blank answers; denominator always 14.
- A17 untagged answers are not in the graph; tagged custom answers get `qual:annexPoint` /
  `qual:sourceCitation`.
- A18 use-once forms are named "Custom questions" and listed nowhere.
- Q1 should a project editor be able to set the default?
- Q2 should form visibility across projects be limited before a multi-customer install?

Raised by implementation or this verification:

- F3 and F4 above (pick freshness; coverage line on legacy cards).
- F8 (zip expansion limit for .docx, pre-existing).
- "Edit the AI system" now always opens "Which form?" first (`?example=mcas` still skips it), and there is
  no navigation link to `/p/<project>/forms` (reached only via the chooser or by URL). Confirm that is
  wanted.
- Messages the tests do not fix, chosen by the implementers: "That form cannot be changed." (save over a
  builtin, unlisted or missing form), "<id> is in the form twice.", "A form description is at most 500
  characters.", "The form could not be read.".
- F1's fix changes how existing answers render in the PDF (escaped instead of raw HTML); expected to be
  invisible for normal text, but worth a note to the owner since it touches a pre-existing surface.

## 7. Verdict

**Ready after A fixes.** All suites match the plan's final counts except the DB suite, whose 3 failures
are test defects (2 in the new file, 1 pre-existing), not code defects. No blocker. Before merge, fix F1
(PDF HTML injection, widened by the shared library) and F2, F5 and F6, plus the three DB test fixes; F3,
F4 and F8 need a product owner decision but do not block correctness of the stored data or history.
