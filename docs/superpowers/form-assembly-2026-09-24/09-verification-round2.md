# Form assembly: independent verification, round 2 (stage 9)

Date: 2026-09-25. Verifier: independent; wrote none of the code or tests, ran and read everything below.
Code: `apps/qualification`, branch `feat/unified-modules`, HEAD `8f0ab50` at the start and at the end (did not
move during this run), round 1 and round 2 work uncommitted. Inputs: `06-spec-addendum.md`, `07-tests-round2.md`,
`08-plan-round2.md`, `04-progress.md` (round 2 sections), `05-verification.md`.

This run modified no repository file except this one. Probe scripts and logs are in
`$P/v2/` (`P=/tmp/claude-1001/-home-listuser/572e79f5-831d-4f75-909f-47cb45306c7a/scratchpad`). `npm run build`
rewrote the generated, untracked `.next/`. The only databases used were the throwaway ones: two started by
`test/db/throwaway-db.sh`, and one started by a verifier probe (`$P/v2/probe-mig/run.sh`, same pattern, random
port, refuses 5432 and 5433, removed on exit). Ports 5432 and 5433 were never touched. No `aisc-t-qual-*`
container is left. Other sessions' containers (`aisc-t-renderer-*`, `aisc-t-orders-*`) were left alone.

---

## 1. Counts vs the plan

The plan (section 6) was written before `8f0ab50`, which added tests. Each difference is accounted for below, test
file by test file.

| Suite | Plan expected | Measured now | Difference explained |
|---|---|---|---|
| vitest | 78 files (74 passed, 4 skipped); 914 tests: 876 passed, 38 skipped | 81 files (77 passed, 4 skipped); 950 tests: 912 passed, 38 skipped, **0 failed** | +3 files, +36 tests: `agentToken` 10, `writeAccess` 16, `serviceTokens` 10 (8 from 8f0ab50, 2 from round 2 fix 2) |
| `tsc --noEmit` | 1 error (formLibrary:137) before the cast | **0 errors** | the authorised cast |
| `prisma validate` (dummy URL) | valid | **valid** | |
| `npm run build` | exit 0, export route listed | **exit 0**, `/p/[project]/forms/[formId]/export` listed, only the known font lint warning | |
| ontology | 240 passed, 3 failed | **261 passed, 3 failed** (the three pre-existing ones of 03-plan 6.4) | +21 = `test_service_token.py` (8f0ab50) |
| prefill | 283 passed | **298 passed** | +15 = `test_service_token.py` (8f0ab50) |
| renderer | 35 passed | **50 passed** | +15 = `test_service_token.py` (8f0ab50) |
| agents | 152 passed | **168 passed** | +16 = `test_service_token.py` 13 + `test_clients.py` 3 (8f0ab50) |
| DB (throwaway) | 3 files, 37 passed | **3 files, 37 passed**, no container left | |

Logs: `$P/v2/{vitest.log,vitest.json,tsc.log,build.log,db.log,onto.log,prefill.log,rend.log,agents.log}`.

## 2. Test integrity

Method: I fingerprinted every file under `test/` and `services/*/tests/` at the start and at the end (identical: no
test moved during this run). I compared them with (a) the round 2 red-run fingerprint
`$P/r2-impl-tests.before-cast.sha` (127 files), (b) the round 1 end state in `$P/r2-before/tests.tar`, and (c) HEAD.

- **Against the red run**, six files differ. Three are 8f0ab50's (`services/agents/tests/test_clients.py`,
  `services/ontology/tests/conftest.py`, `test/unit/onlyLatestCardChanges.test.ts`): committed there and clean in the
  working tree. The other three are the documented edits. I proved each one by reversing the documented edit on the
  current file and checking that the sha256 then equals the red-run hash exactly:
  - `test/unit/formLibrary.test.ts`: only `acmeGroup([newer])` became `acmeGroup([newer as never])` (the authorised
    cast, a type-only change).
  - `test/unit/FormService.test.ts`: only the R61 R64 test changed. It adds `const gv2 = store.inserted.at(-1)!.version.id;`
    and uses `fromVersionId: gv2` in place of `"gg-v2"`, and its assertions are unchanged. The sibling R62 test
    reads the id the same way. This is a real fix: the fake store mints `n<k>` ids for saved versions, so `"gg-v2"`
    never existed.
  - `test/unit/formsNoModel.test.ts`: only the R73 env test changed. Its title and filter went from
    `PREFILL_URL`/`PLATFORM_URL` to an `ALLOWED` list that adds `QUALIFICATION_WEB_TO_PREFILL_TOKEN`, with a
    comment citing the amendment. The scan regex, the file list and the other R73/R41 tests are untouched. This
    matches the R73 amendment in 06.
- **`serviceTokens.test.ts` (8f0ab50's test)**: the working-tree diff against HEAD only adds lines. It adds two
  tests (the import and export clients send `X-AISC-Service-Token`, and export keeps its JSON content type) and
  two owners in "each env name is read by its own client only". That test checks equality in both directions over
  the union of all owner files, so adding the two clients makes it **stricter**. They must now read the prefill
  token and must not read any other edge's token. Nothing was loosened.
- **Against round 1 (tarball)**, every changed or removed line in the 19 changed files matches 07 section 3 row by
  row. The removed tests are the R3 "builtin not default", five R4/F6 `setDefault` tests, four `setDefaultForm`
  tests, three R4 DB tests, the R22 pick and "Custom questions" tests (replaced by R60 and R68), and the `is_default`
  column in the R1 DB select. The renamed and flipped tests are R8 to R46 and the precedence flip R8 to R71. The
  rest are additive shape changes (`fromVersionId`, `versionId`, `ownerFormId`, `annexPoint`, `optionalBlank`) and the
  R72 counts. I found no other removal or weakening. No test file is gone.

**Result: pass.** The only test edits beyond 07 are the three authorised or documented ones above, plus the
additive `serviceTokens.test.ts` extension.

## 3. Conformance (R43 to R73)

Every R-id has green tests (vitest 0 failed). Below is what I checked by reading and by probing, beyond the tests.

**Default form fixed (R43 to R46).**
- The code: `FormService.listed()` computes `isDefault: form.id === DEFAULT_FORM_ID`. There is no `setDefault` in
  the service, repository, actions or UI. `actions.ts` exports only `saveForm` and `useFormOnce`.
  `SetDefaultButton.tsx` is gone. The risk-3 grep and a wider grep over `src`, `prisma/schema.prisma`, `scripts`
  and `platform` find no writer of a default. The Prisma seed (`scripts/seed_mcas.mjs`) writes no form or default
  rows. `preselect` falls back to the constant.
- The migration probe (`$P/v2/probe-mig/run.sh`): I applied migrations up to 090000 only, added a listed and an
  unlisted form, and **moved the old default to the listed form** (`acme.is_default = true`, the builtin false).
  Then I applied 120000 with `prisma migrate deploy`. It applied cleanly. The column, `form_one_default` and
  `form_default_is_listed` are gone, `form_builtin_is_the_default` exists, and no row changed.
  `_prisma_migrations` records both.
- As `qualification_rw`, each of these writes fails:
  - a second builtin row
  - unlisting the default
  - changing its origin
  - promoting a builder form to builtin
  - renaming the default's id
  - deleting it
  - updating a v1 snapshot
  - adding a v2 to the builtin

  With no default flag left, a leftover "moved" default in an old DB loses its effect harmlessly.
- The R7 revert and re-apply DB test passes.

**No project scope (R47, R48).** The schema's four form models and both migrations have no project column.
FormService and FormRepository take no project argument. The library page calls `library()` with no arguments;
the project appears only in link prefixes and redirects.

**Export and import (R50 to R59).**
- `form_export.py` matches R50 to R52 byte for byte (the tests pin the examples).
- Adversarial probe (`$P/v2/probe-io/roundtrip_fuzz.py`): 4000 random forms built from an alphabet of `\`, `|`,
  `\|`, `\\`, `'`, `''`, `= + - @`, quotes, commas, newlines, tabs, CRLF, `#`, `[x]`, `<!--`, `-->`, NBSP, ZWSP,
  BOM, NUL, U+2028, non-ASCII and more, with random names, citations, required flags and points.
  - **Markdown: 4000 of 4000 round-trip.**
  - **CSV: 97 failures, all of one class** (finding G1): a cell that starts with exactly two `'` followed by a
    formula character.
  - Across 3000 more CSV exports, no parsed text or citation cell starts with `= + - @`, tab or CR. The formula
    guard holds, and `collapse` removes leading tab and CR.
- `.docx` zip-bomb probe (`$P/v2/probe-io/zipbomb.py`, over HTTP with the service token). Both `/prefill` and
  `/forms/import` answer:
  - 200 for a normal file;
  - 422 with the exact R70 message for a 51 MiB zero member (88 KB zipped);
  - 422 with the same message for sixty 1 MiB members.

  A crafted zip whose central directory declares 2 KB but whose stream inflates to 200 MB passes the declared-size
  check, as designed. `zipfile` then stops at the declared size ("Bad CRC-32"), and the endpoint answers 422 in
  0.2 s. The declared-size bound is sound.
- The export route has no access logic of its own. `src/middleware.ts` (unchanged, matcher `/p/:path*`) lets GET
  through for members, viewers included, and refuses strangers. The route exports only a form version's
  questions (text, citation, required, point) through `exportable`. It exports no card, answer or project data.
  Unlisted use-once forms can be exported by id, as R57 says. Their ids are random UUIDs and appear only on the
  card and edit pages of the project that used them.
- The route validates `format` case-sensitively and `version` with `^[1-9]\d*$`. It returns bytes through
  `TextEncoder` (BOM kept), the ASCII filename, and `no-store`.
- `FormImportClient` and `FormImport.tsx` map the point through `isAnnexPoint`, and the preview has the
  "Answers Annex IV point" select.

**F3 pinned picks (R60 to R64).** `pinnedSnapshots` loads each pick's `fromVersionId` once. A missing version or row
is "Question n no longer exists." The planner copies the five fields verbatim, and `sameContent` gets the map.
`sourceUpdates` matches the owner group by `ownerFormId`, compares the five fields and skips own rows, copy rows,
missing owners and dropped questions. The builder shows the chip, the paragraph and the button, and `takeLatest`
repins. One nit: the button's aria-label adds a `.trimEnd()` that the spec does not have (G2).

**F4 (R65, R66).** `coverage.py` counts a point as optional left blank only when it is uncovered, asked, and never
required. It uses the exact summary format with the singular "optional". `optionalBlank` is in the view, the
renderer model and the TS type. Legacy cards export with the default version, so they show the line and
`FormLine`.

**F7 (R67 to R69).** `useOnceFormName` matches R67. `saveDraft` names use-once forms against every form's name.
`useFormOnce` reads `platformClient.latestVersion(project)` (async, so `.catch` covers failures) and falls back to
the project. `toExport` adds `ownerFormId`. The ontology `/build` model declares `form: dict[str, Any]`, so the key
reaches `coverage()`. The code groups by id and falls back to the name.

**R71.** `pickFormParams` treats empty strings as absent and returns example, then formVersion, then form, then
none. The edit page uses it, and an unknown `?formVersion` never falls back to `?form`.

**R49.** `SiteHeader` adds "Forms" after "Versions", inside the `project &&` fragment.

**R72 (MCAS).**
- The JSON diff is exactly one inserted 5-line object (1f after 1de).
- I regenerated both graphs from the JSON in `$P`. Each is 413 triples and isomorphic to the committed
  `mcas.ttl` and `mcas.jsonld`.
- The committed export with the default form gives "Annex IV coverage: 14 of 14 points.".
- The README says 14 answers and 413 triples. The old 13-answer JSON gives 409.

**Prefill token.** `FormImportClient` and `FormExportClient` take
`QUALIFICATION_WEB_TO_PREFILL_TOKEN` as a third constructor argument and send `serviceTokenHeaders(...)`, the same
way `PrefillClient` does. The 8f0ab50 scan "every caller of a sidecar sends that sidecar's token" passes.

**No LLM in Next.js.** No file under `src` reads an LLM URL or token, or imports an LLM SDK. The forms files import
no `FillerClient`. `form_export.py` imports only the standard library. The only model path is the pre-existing
`FillerClient` to the agents service, outside the forms feature.

## 4. Round 1 regression spot-check

| Guarantee | Still holds | Evidence |
|---|---|---|
| Identity block locked | yes | `FORM_BLOCKS` starts at `description` (no identity field); the R10 to R15 tests pass |
| Versions append-only | yes | the migration probe: an update of a v1 snapshot fails on `form_version_question_is_append_only`, and a v2 of the builtin fails on `form_builtin_is_fixed`; the DB suite passes |
| Legacy graph digest | yes | probe `$P/v2/probe-io/digest.py`: the default-form export **with `ownerFormId`** builds a graph whose digest equals the legacy export's (413 = 413 triples); the only graph change in the repo is the intended MCAS example (409 to 413) |
| PDF escaping and url_fetcher (F1) | yes | `template_engine.py:18` `autoescape=True`; `renderer.py:20,58` `restricted_url_fetcher`; the 9 `test_pdf_safety.py` tests pass |
| CSV field limit (F2) | yes | `form_import.py:142` `csv.field_size_limit(...)` |

## 5. Findings

| Id | Severity | R | File:line | Problem | Failure scenario | Suggested fix | Cat. |
|---|---|---|---|---|---|---|---|
| G1 | low | R50, R53, R54, B9 | `services/prefill/prefill/form_export.py:55-59` (`_guard`), `services/prefill/prefill/form_import.py:81` (`_unguarded`) | The CSV guard is not injective. The exporter guards `'=x` (writes `''=x`) but leaves `''=x` as it is. The importer strips one `'` from anything shaped `'` + `'` + formula, so `''=x` comes back as `'=x`. This follows R50's literal rule. R54's case list does not include two leading quotes, so no test catches it. | A form with a question or citation starting `''=`, `''+`, `''-` or `''@` (for example a quoted formula in a spreadsheet how-to) exports, and its re-import differs by one quote. The fuzz probe hit this in 97 of 4000 random forms, and in no other class. | Guard any cell matching `^'*[=+\-@]` with one extra `'`, and strip one `'` on import when the cell matches `^'+[=+\-@]`. That is an exact inverse, and every R50 example output stays the same. Add `''=x` and `'''=x` to the R54 case 3 texts. Needs a one-line R50/R53 amendment. | B |
| G2 | nit | R64 | `src/app/p/[project]/forms/FormBuilder.tsx:268` | The aria-label is `"Use the new wording of " + text.slice(0, 40).trimEnd()`. The spec says "the first 40 characters". The only test uses a text whose 40th character is not a space. | When the 40th character is a space, the label is one character shorter than the spec's. The accessible name is arguably better. | Either drop `.trimEnd()` or amend R64 to say "trimmed". | C |

No finding of medium severity or above. The default is fixed, forms carry no project, the export route cannot
reach anything beyond a form version's questions, and the zip cap holds on both endpoints.

## 6. Still open for the product owner

- **Deployment: `apps/qualification/Dockerfile:47` `CMD npx prisma db push --accept-data-loss && npx next start`.**
  It is latent in the current stack. `docker-compose.development.yml:312-316` runs `qualification-migrate`
  (`prisma migrate deploy`), and the web service overrides the CMD (`:345`). No other compose file
  (`docker-compose.yml`, `.staging`, `.demo.nbg`) defines qualification.
  - Anyone who runs the image with its default CMD gets a DB synced from `schema.prisma`: no 090000 seed (so no
    `annex-iv-default` row, and the chooser falls back to the first listed form), no 120000 CHECK, and no
    triggers.
  - Against an already migrated DB, `db push --accept-data-loss` may drop the hand-written partial indexes
    (`form_listed_name_key`, which is the listed-name uniqueness).
  - Decide: make the image CMD `prisma migrate deploy`, or keep the override as the only supported path and
    document it.
- B-items worth an explicit yes:
  - **B1**: export depends on the prefill service. Without `PREFILL_URL` it answers 503, and with the wrong or a
    missing token, 401 from prefill, which the route turns into a 502.
  - **B3**: a round trip restores all 9 blocks, and name, description and identities are not carried.
  - **B6**: no DB index on use-once names.
  - **B8**: `?formVersion` silently wins over `?form`.
  - **B9**: the importer strips one `'`. Hand-written `'=` loses its quote, and G1 is the double-quote edge.
  - **B10**: no export button inside the builder.
  - B2, B4, B5 and B7 read as settled defaults.
- Visible change to confirm (was F4, now R66): every legacy card shows the coverage line (for example "10 of 14
  points (4 optional left blank)") and "Form: Annex IV default v1 · CSV · Markdown".
- R73 amendment: `QUALIFICATION_WEB_TO_PREFILL_TOKEN` is allowed in the forms code (already recorded in 06). The
  verifier agrees it is a service-to-service token, not a model credential.
- Unchanged from round 1: the three pre-existing ontology failures (03-plan 6.4) are still red, by design.

## 7. Verdict

**Ready.** Every suite is green at the expected counts once the 8f0ab50 additions are accounted for, and test
integrity is proven. R43 to R73 are met, and the round 1 guarantees hold. G1 (low) and G2 (nit) are not blocking.
G1 needs a one-line spec decision, after which the fix is mechanical. The Dockerfile `db push` CMD is a
deployment decision outside this feature's code.
