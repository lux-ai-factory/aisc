# Two-level forms: implementation plan (stage 3)

Date: 2026-09-25. Inputs: `00-brief.md` (process rules), `01-spec.md` (T1 to T63, D1 to D30), `02-tests.md`
(test map, interface names, contradictions), the tests themselves, the scratch reference migration
`$P/tlf/ref/migration.sql` (read for insight only), and for the way the last pipeline sequenced its work
`../form-assembly-2026-09-24/03-plan.md` and `08-plan-round2.md`. Code: `apps/qualification`, branch
`feat/unified-modules`, HEAD `8f0ab50` when this plan was written, uncommitted working tree.

**The tests are the contract.** Where the spec and the tests disagree, this plan follows the tests (section 3).
This plan has no code. Names, messages and statement heads that a test matches by regex are quoted exactly,
because they are load-bearing; everything else is described.

Two implementers run this plan one after the other and do not talk to each other or to the planner:

- **Half A** (tasks 0 to 12): the database, Python, the pure domain modules, the repositories and services, the
  server-side consumers and the HTTP clients. Nothing under `src/app/p/[project]/` except one hook and one API
  route.
- **Half B** (tasks 13 to 19): every page, route, server action and React component under
  `src/app/p/[project]/`, the chooser module, the removal of the old form code, and the full verification.

The split point is after task 12 (section 1.3). Half B starts by re-running task 0's checks and the split
checkpoint, so it trusts nothing it has not seen.

Short names used everywhere below (use these exact paths):

```bash
A=/home/listuser/aisc-install/apps/qualification
P=/tmp/claude-1001/-home-listuser/572e79f5-831d-4f75-909f-47cb45306c7a/scratchpad
VT="cd $A && npx vitest run"
PREF="cd $A/services/prefill && PYTHONPYCACHEPREFIX=$P/pyc .venv/bin/python -m pytest -p no:cacheprovider"   # its pytest.ini already has -q: never add -q
ONTO="cd $A/services/ontology && PYTHONPYCACHEPREFIX=$P/pyc $P/venv-ontology/bin/python -m pytest -p no:cacheprovider -q"
REND="cd $A/services/system_card_renderer && PYTHONPYCACHEPREFIX=$P/pyc $P/venv-system_card_renderer/bin/python -m pytest -p no:cacheprovider -q"
AGENTS="cd $P/agents-cwd && PYTHONPYCACHEPREFIX=$P/pyc $P/venv-agents/bin/python -m pytest -p no:cacheprovider -q -c $A/services/agents/pytest.ini --rootdir $A/services/agents $A/services/agents/tests"
DUMMY='DATABASE_URL=postgresql://x:x@127.0.0.1:1/x?schema=qualification'
```

Run each as `bash -c "$VT <files>"`. `bash $P/tlf/run-all.sh <tag>` runs the five non-DB suites and prints one
summary line each (logs in `$P/tlf/logs/<tag>-*.log`).

vitest filters by substring, case-insensitively: `test/unit/formChooser.test.ts` also selects
`test/unit/FormChooser.test.tsx`. That is expected. Every other file path in this plan selects only itself.

Every implementer, before starting, prints the user's three-line contract (GOAL, SCOPE, DONE WHEN) and appends it
to `~/.claude/prompt-log/$(date +%Y-%m).md`, as `~/.claude/CLAUDE.md` asks.

---

## 1. Tasks

"Green" means every test the command selects passes. Counts are per file, `it`/`test` cases as vitest runs them
(`it.each` rows counted), from the planner's reading of the red run of 2026-09-25 (`$P/tlf/logs/after-vitest.json`).

### Task 0. Fresh baseline (no code)

1. `git -C $A branch --show-current` prints `feat/unified-modules`. If not, stop and ask.
2. `git -C $A log --oneline -3`: HEAD was `8f0ab50` when this plan was written. If HEAD moved, run
   `git -C $A show --stat <sha>` for each new commit and compare its paths with section 5 (files). Any overlap
   with a file this plan edits, creates or deletes: stop and report before touching that file.
3. `git -C $A status --short > $P/tlf/impl-status-before.txt` (the other session's work in progress is visible
   here; this plan touches only section 5's files).
4. Fingerprint of every test file (many are untracked, so `git diff` cannot prove they did not change):
   `cd $A && find test services/*/tests -type f -not -path '*/__pycache__/*' -not -path '*/.pytest_cache/*' -print0 | sort -z | xargs -0 sha256sum > $P/tlf/impl-tests.sha`
   Also the sha256 of the two applied migrations, which must never change:
   `sha256sum $A/prisma/migrations/20260925090000_forms_are_data/migration.sql $A/prisma/migrations/20260925120000_the_default_form_is_fixed/migration.sql`
   must print `cbea212d7cd330c13c667918bad2b57572a2ceb871c327da423a3bb687147557` and
   `b8338d12f1c9f3c92022798556e1d0ef7a5b1f25b60b6e7b141feac2ca8dfb4c`.
5. Backup of the untracked source this plan moves or deletes (untracked files have no git history: a delete
   is final):
   `cd $A && tar -cf $P/tlf/impl-untracked-src.tar 'src/app/p/[project]/forms' src/domain/forms src/server/services/FormService.ts src/server/repositories/FormRepository.ts src/server/services/FormExportClient.ts src/server/services/FormImportClient.ts 'src/app/p/[project]/FormLine.tsx' 'src/app/p/[project]/system/edit/FormChooser.tsx'`
   (half B checks it exists before task 16).
6. Baseline: `bash $P/tlf/run-all.sh impl-before`, then `cd $A && npx tsc --noEmit > $P/tlf/logs/impl-before-tsc.log 2>&1; grep -c "error TS" $P/tlf/logs/impl-before-tsc.log`.
   Expected (the test author's red run, `02-tests.md` section 7, re-read by the planner from the logs):

| Suite | Expected |
|---|---|
| vitest | Test Files 46 failed, 53 passed, 4 skipped (103); Tests 672 failed, 629 passed, 90 skipped (1391) |
| tsc | 60 errors, every one in `test/`, none in `src/` |
| ontology | 12 failed, 263 passed (the 9 new ones of `test_owner_set_keys.py` plus the 3 pre-existing: `test_build.py::...all_nineteen_properties`, `test_example_mcas.py::...all_nineteen_properties`, `test_roundtrip.py::...every_airo_relation`) |
| prefill | 109 failed, 311 passed |
| renderer | 50 passed |
| agents | 168 passed |

   A different number means the tree moved since the tests were written: diff `$P/tlf/logs/impl-before-*.log`
   with `$P/tlf/logs/after-*.log` before going on.
7. DB baseline (optional, 30 s): `docker ps -a --format '{{.Names}}' | grep aisc-t-qual- || echo none` prints
   `none`; then `cd $A && test/db/throwaway-db.sh` is expected to give 3 files, 89 tests, 68 failed, 21 passed.
   Leave every other container alone (for example `connectors-test-*` belongs to another session).
8. Check the venvs exist: `ls $P/venv-ontology/bin/python $P/venv-system_card_renderer/bin/python $P/venv-agents/bin/python $A/services/prefill/.venv/bin/python $P/agents-cwd`. If one is missing, recreate it as
   `02-tests.md` section 6 says (`uv venv` plus `uv pip install -r requirements.txt pytest httpx`, and
   `rdflib==7.6.0` for agents), inside `$P`, never in the repository.

Proof: the table reproduced; `$P/tlf/impl-tests.sha` and `$P/tlf/impl-untracked-src.tar` exist.

### Task 1. The Prisma schema, the forward migration, `prisma generate` (T1, T2; T3 to T9 proven in task 12)

Files:
- `prisma/schema.prisma`: remove `model Form`, `FormVersion`, `FormQuestion`, `FormVersionQuestion`; add the
  seven models of spec 3.3 exactly (field names, types, `@map`, `@@map`, relations, `@@id`/`@@unique`/`@@index`
  with their `map:` names). One change to spec 3.3: the `@@unique([questionnaireVersionId, position])` of
  `QuestionnaireVersionItem` uses `map: "questionnaire_version_item_version_id_position_key"` (50 bytes; section 3,
  conflict 1). In `model Qualification`, replace `formVersionId`/`formVersion` and the `formVersionId` index by
  the three lines of spec 3.3 (without the trailing `// replaces ...` comment). Rules the tests check: no model
  body of the seven contains the word `project` (outside `///` lines), the file contains neither `isDefault` nor
  `is_default` anywhere (comments included), every `map:` name of the seven models is at most 63 bytes, both
  `retiredAt` and `createdAt` are `@db.Timestamptz(3)`, and no extra field is added to any of the seven models
  (the test compares the field set exactly).
- New `prisma/migrations/20260925150000_two_level_forms/migration.sql`: the design of section 2.
- Do not touch `prisma/migrations/20260925090000_forms_are_data/` or `20260925120000_the_default_form_is_fixed/`
  (sha256 pinned twice) or `migration_lock.toml`.

Then, at once: `cd $A && npx prisma generate` (writes only `node_modules/.prisma`; the live `qualification-web`
container runs from its own image and does not mount this directory, checked 2026-09-25). This is the first of
the `prisma generate` runs listed in section 4.3.

Proof:
```bash
bash -c "$VT test/unit/twoLevelSchema.test.ts test/unit/twoLevelMigration.test.ts"   # 14 + 10 green
cd $A && env $DUMMY npx prisma validate                                               # valid; never connects
sha256sum $A/prisma/migrations/2026092509*/migration.sql $A/prisma/migrations/20260925120000*/migration.sql   # the two task 0 hashes
```
Early DB checkpoint (recommended, it catches SQL mistakes before anything depends on them):
`cd $A && test/db/throwaway-db.sh` expected: 3 files, 89 tests, **87 passed, 2 failed**. The two failures are
`T3 QuestionnaireService.resolve(...)` and `T3 QuestionSetService.resolveSetVersion(...)`, which need task 5, 8
and 9 modules. Anything else failing is the migration's fault; `cardVersions.db.test.ts` or
`cardVersionOfItsProject.db.test.ts` failing with "column `qualification.form_version_id` does not exist"
means `prisma generate` did not run. Then
`docker ps -a --format '{{.Names}}' | grep aisc-t-qual- || echo none` prints `none`.

T-ids: T1, T2.

### Task 2. The Dockerfile line and DEPLOY.md (T59)

Files:
- `Dockerfile`: only the last line changes, to exactly
  `CMD ["sh", "-c", "npx prisma migrate deploy && npx next start -p 3000"]`. Every other byte stays (the test
  compares every other line with `test/fixtures/Dockerfile.before`). No other docker or compose file is touched.
- `DEPLOY.md` (tracked, clean; do not rewrite its existing lines, some of which contain dashes this plan did not
  write):
  - line 63: "The container runs `prisma db push` on startup, so the schema is created automatically." becomes
    "The container runs `prisma migrate deploy` on startup, so the schema is created and migrated automatically."
    (the test needs the exact phrase "The container runs `prisma migrate deploy` on startup" and the old phrase
    gone).
  - a new paragraph right after it (one paragraph, no blank line inside): "Before deploying
    20260925150000_two_level_forms, take a backup of the qualification schema: `pg_dump --schema=qualification`
    (for example `docker compose exec db pg_dump -U <user> -d <db> --schema=qualification > qualification-before-two-level-forms.sql`).
    The migration drops the old form tables in the same transaction that copies them, and there is no down
    migration: the dump is the way back."
  - a second new paragraph: "A database created by `prisma db push` has no migration history. Baseline it
    before the first start with the new image: run `prisma migrate resolve --applied <name>` for every migration
    in `prisma/migrations` that the database already reflects, then start the container, which applies the rest."
    (the test needs, in one paragraph: `prisma migrate resolve --applied`, `db push`, "no migration history",
    "every migration", "before the first start").
  - No em dash in anything added.

Proof: `bash -c "$VT test/unit/dockerfile.test.ts"` 6 green.

T-ids: T59.

### Task 3. Ontology: coverage groups by question set (T11, T43 Python half)

File: `services/ontology/airo_min/coverage.py` only.
- `_owner_key(q)`: `("id", q["ownerSetId"])` when the key is present, else `("id", q["ownerFormId"])` when present,
  else `("name", q.get("ownerSet", q.get("ownerForm")))`.
- The name shown for a group (in `_owners_in_order`, and wherever `q["ownerForm"]` is read today) is
  `q.get("ownerSet", q.get("ownerForm"))`. No other `ownerForm` read may remain (grep the file).
- Output keys (`forms`, `form`, `additionalDocumentation`) and every summary string unchanged. Update the module
  docstring's question shape (both key styles accepted).
- `build.py`, `view.py`, `app.py`: no change (the graph never reads owner keys; T11 proves it).

Proof:
```bash
bash -c "$ONTO tests/test_owner_set_keys.py tests/test_coverage.py"   # 11 green + every test_coverage test green
bash -c "$ONTO"                                                       # 272 passed, 3 failed (the 3 pre-existing, section 6.2)
```

T-ids: T11, T43 (Python).

### Task 4. Prefill: the questionnaire file (T50, T51, T52, T61 Python)

Files:
- New `services/prefill/prefill/questionnaire_file.py`, imports only the standard library and `prefill.*`
  modules (an AST test enforces it). Exports `QuestionnaireFileError(Exception)` (its detail is `str(error)`),
  `write_questionnaire(q: dict, bundle: str) -> ExportedFile` (reuse `ExportedFile` and `slug` from
  `prefill.form_export`, and `ANNEX_POINT_IDS` from `prefill.fields`), `read_questionnaire(raw: bytes,
  filename: str) -> dict`. Behaviour: spec T50 (key order, `json.dumps(doc, ensure_ascii=False, indent=2) + "\n"`,
  filename `<slug(name)>-v<version>.questionnaire.json`, content type `application/json; charset=utf-8`), T51
  (the checks in that exact order with those exact details; the output carries `bundle`; a references file drops
  the wording keys; "missing wording" means the key is absent, a `null` annexPoint/groupLabel is present), T52
  (round trip). A module constant for the 200-item limit and the regexes of the DB (`^[a-z0-9-]+$`,
  `^[a-z0-9]+$`).
- `services/prefill/app.py`: `POST /questionnaires/export` (JSON body `{"bundle", "questionnaire"}`; 422 messages
  of T50; pydantic models with plain `str` for `bundle` so a wrong value reaches the handler's own message; the
  item wording fields optional in the model so the handler, not pydantic, reports missing wording) and
  `POST /questionnaires/import` (multipart `file`; `QuestionnaireFileError` to 422 with its detail; a file over
  `PREFILL_MAX_BYTES` to 413, the same reader as `/forms/import`). Both behind the existing service-token
  middleware (nothing to add: every path but `/health` is covered). Nothing above the new endpoints changes
  (`test_app.py` only appended a class).
- `services/prefill/README.md`: document the two endpoints (request, response, the 422 details). No new
  markdown file.

Proof:
```bash
bash -c "$PREF tests/test_questionnaire_file.py"                          # 84 green
bash -c "$PREF tests/test_app.py"                                         # 81 green (56 old + 25 TestQuestionnaireEndpoints)
bash -c "$PREF"                                                           # 420 passed
```

T-ids: T50, T51, T52, T61 (Python half).

### Task 5. Types and the in-memory builtin twins (T3 unit half)

Files:
- `src/domain/forms/types.ts`: replaced by spec 5.1 exactly (`ResolvedQuestion` with `setId`, `setName`,
  `setVersionId`, `setVersionNumber`, `setBuiltin`; `ResolvedQuestionnaireVersion`; `ResolvedSetVersion`;
  `VersionStamp`; `QuestionnaireResolver`). `ResolvedFormVersion` and `FormResolver` are removed.
- `src/domain/forms/legacy.ts`: the constants of spec 3.4 (`ANNEX_SET_ID`, `ANNEX_SET_VERSION_ID`,
  `DEFAULT_QUESTIONNAIRE_ID`, `DEFAULT_VERSION_ID`, plus the builtin names), `resolveQuestionnaireVersionId(id)`,
  `annexDefaultVersion()` (fresh value per call; `description` is `EU AI Act Annex IV points 1 and 2, as 14 questions.`,
  `retired: false`, all 9 blocks in `FORM_BLOCKS` order, questions as T3 says), `annexSetVersion()` (same
  questions, `origin: "builtin"`, same description). `DEFAULT_FORM_ID` and `resolveFormVersionId` are removed.

Expected fallout, on purpose: files that still import the removed names (the old UI under
`src/app/p/[project]/forms/`, `FormService.ts`, `FormRepository.ts`, `formDraft.ts`, `FormChooser.tsx`, the edit and
card pages, `QualifyForm.tsx`, `AnsweredForm.tsx`, `chooser.ts`) stop type-checking. Half A fixes the server ones
(task 10); half B the rest. Do not add compatibility aliases for the removed names: tests assert they are gone.

Proof:
```bash
bash -c "$VT test/unit/annexDefaultForm.test.ts test/unit/annexDefaultExportFixture.test.ts test/unit/keyQuestions.test.ts"   # 24 + 2 + 15 green
```

T-ids: T3 (unit).

### Task 6. Pure domain modules (T12, T13, T16, T22, T23, T26 to T33 reducer, T41 and T42 functions, T53 pure)

All under `src/domain/forms/`, pure (no Prisma, no env, no fetch, no React). Interface names: spec 5.2 and
`02-tests.md` section 5.1, which are the contract where the spec is silent.

- New `questionSetDraft.ts`: `SetDraft`, `parseSetDraft(input, {takenNames?})` (never throws; T12's checks in
  that order and those messages), `sameSetContent(draft, latest)` (T13).
- New `setEditorState.ts`: `SetEditorState`, `setEditorReducer`, `initialSetEditorState`, `toSetDraft` (T16;
  `initialSetEditorState({})` is exactly the object of `02-tests.md` 5.1; an edit/remove of a missing index
  returns the same state object; `toSetDraft` omits `questionId` for new rows).
- New `questionnaireDraft.ts`: `QuestionnaireDraft`, `parseQuestionnaireDraft(input, {takenNames?})`,
  `sameQuestionnaireContent(draft, version)` (T22, T23; extra item keys dropped; the same question twice is
  refused even when pinned to two set versions).
- `library.ts`: `SetGroup` replaces `LibraryGroup`; `filterLibrary`, `overlapHints`, `overlapLabel` byte-unchanged
  in behaviour; `updatesAvailable(rows, groups)` replaces `sourceUpdates` (T26: keyed by row index; reworded on
  any of the five wording fields; removed; retired groups count; a missing group is no update; pure).
- `builderState.ts`, rewritten: `BuilderState` with exactly the keys of `02-tests.md` 5.1, pick rows only, the
  actions listed there (`tick`, `untick`, `selectSet`, `deselectSet`, `move`, `remove`, `toggleBlock`, `setName`,
  `acceptUpdate`, `acceptAllUpdates`); unknown actions (`addOwn`, `edit`, `copy`) return the same state object;
  `BuilderInit` of 5.1 (`startFrom`, `edit`, `picks`); `toQuestionnaireDraft(state)` (T33: blocks in
  `FORM_BLOCKS` order; neither `selected` nor `viaSetId` travels). Never mutates its input.
- New `moveCard.ts`: `rewordedSince`, `droppedAnswers`, `moveNotice` (each count sentence only when its count is
  above 0), `newerVersion(card, latest | null)` (T41, T42).
- New `references.ts`: `ReferenceItem`, `FoundSetVersion`, `missingReferences(items, found)` (T53: item order,
  once per missing `(setId, setVersion)`, the two exact sentences).
- `useOnceName.ts`, `annexPoints.ts`, `blocks.ts`: unchanged.
- `chooser.ts` is **not** touched in half A (task 17): the edit page still imports `pickFormParams`, and
  `editSystemPage.test.tsx`'s two green guards must stay green until half B rewrites the page with it.
- `formDraft.ts` stays on disk until task 16 (the old builder and `FormService.ts` still import it). Nothing new
  may import it.

Proof:
```bash
bash -c "$VT test/unit/questionSetDraft.test.ts test/unit/setEditorState.test.ts test/unit/questionnaireDraft.test.ts"   # 26 + 12 + 22 green
bash -c "$VT test/unit/formLibrary.test.ts test/unit/builderState.test.ts"                                               # 25 + 38 green
bash -c "$VT test/unit/moveCard.test.ts test/unit/references.test.ts test/unit/useOnceName.test.ts"                      # 18 + 7 + 9 green
```

T-ids: T12, T13, T16, T22, T23, T26, T27 to T33 (reducer and state), T41 and T42 (functions), T53 (message
building).

### Task 7. The caller's name (T55 function)

File: new `src/server/access/callerName.ts`: `identityFromToken(token: string | null): string | null` (pure: split
on `.`, base64url-decode the payload, parse JSON, the first non-blank string of `preferred_username`, `email`,
`sub`, trimmed and cut to 200; null otherwise, never throws) and `callerName(): Promise<string>` =
`identityFromToken(await callerToken()) ?? "unknown"`, with `callerToken` imported from
`@/server/services/callerToken` (the test mocks that path). Reads no env.

Proof: `bash -c "$VT test/unit/callerName.test.ts"` 10 green.

T-ids: T55 (function).

### Task 8. The repositories and QuestionSetService (T14, T15, T19, T45, T49 service, T57, T63)

Files:
- New `src/server/repositories/QuestionSetRepository.ts`: `export class QuestionSetRepository { constructor(db: PrismaClient = prisma) }`
  (`prisma` from `@/lib/prisma`), implementing exactly the set methods of the contract in the header of
  `test/support/fakeQuestionnaireStore.ts` (`listSets`, `findSet`, `findSetVersion`, `setVersionsOf`,
  `findQuestion`, `questionsOf`, `insertSetVersion(plan)`, `retireSet(id, at)`), row shapes the Prisma models,
  version reads including items in position order with their `question`. `insertSetVersion` is one
  `$transaction`: the new set (when `plan.set`), the new questions, the version, its items, and when
  `plan.questionnaire` is given the questionnaire (when new), its version and items. `retireSet` is the only
  `update` (retired_at only). No other write.
- New `src/server/repositories/QuestionnaireRepository.ts`: `QuestionnaireRepository` (it may extend
  `QuestionSetRepository`) adding `listQuestionnaires`, `findQuestionnaire`, `findQuestionnaireVersion`,
  `questionnaireVersionsOf`, `insertQuestionnaireVersion(plan)`, `retireQuestionnaire(id, at)`; a questionnaire
  item read includes `setItem` with its `question` and its `setVersion.set`.
- New `src/server/services/QuestionSetService.ts`: `QuestionSetService(repository = new QuestionSetRepository(), { newId = () => randomUUID(), now = () => new Date() } = {})`
  with `list({retired})`, `groups()`, `resolveSetVersion(id)`, `latest(setId)`, `atNumber(setId, n?)`,
  `history(setId)`, `saveDraft(draft, opts)`, `retire(setId)`; singleton `questionSetService`. Behaviour: T14,
  T15 (next local number is max over every question the set owns, never reused; new question keys
  `s-<setId>:q<n>`; group labels carried; name and description fixed after creation; the P2002 messages), T19,
  T45 (Annex IV first, then by name ignoring case; retired groups included with `retired: true`), T49
  (`alsoQuestionnaire`: one transaction; the questionnaire named as the set, listed, origin `import`, all 9
  blocks, a taken questionnaire name refuses the whole save), T57 (`history` newest first, ISO 8601 UTC), row
  shapes of `02-tests.md` 5.2.

Rules every one of the four new server files obeys (scans in `formsDefaultIsFixed.test.ts`): no method parameter
named `project`, `projectId` or `_project`; the text `projectId` / `project_id` nowhere, comments included; no
`setDefault`; class methods at two-space indentation; nothing runs a query at import or in a constructor (tests
import them with `@/lib/prisma` mocked as `{}`); `newId` values must match `^[a-z0-9-]+$` because a set id becomes
the scope `s-<setId>` (`question_scope_check`); `randomUUID()` does.

Proof:
```bash
bash -c "$VT test/unit/QuestionSetService.test.ts"                       # 36 green
```

T-ids: T14, T15 (service), T19, T45, T49 (service), T57 (sets), T63 (sets).

### Task 9. QuestionnaireService (T24, T25, T35, T46, T53 service, T54 service, T57, T63)

File: new `src/server/services/QuestionnaireService.ts`:
`QuestionnaireService(repository = new QuestionnaireRepository(), { newId, now } = {})`, methods of spec 5.3:
`resolve(id | null)` (null is `annexDefaultVersion()` without touching the repository: section 3 conflict 4 needs
this), `latestVersion(id)`, `exportable(id, n?)`, `library({retired})`, `chooserOptions()`, `history(id)`,
`saveDraft(draft, opts)`, `retire(id)`, `resolveReferences(items)`, `importSelfContained(file, opts)`; singleton
`questionnaireService`. Behaviour: T24 (never writes a set-level row; `Question <n> no longer exists.`; use once
names through `useOnceFormName(systemName, now(), <every questionnaire name>)`; the two P2002 messages), T25
(pinned wording; `key` from the question's scope and local id; blocks sorted into `FORM_BLOCKS` order), T35, T46
(`isDefault` from the constant; `updates` = count of `updatesAvailable` of the latest version against the set
groups), T53 (looks up each `(setId, setVersion)` and `(scope, localId)` in it, then `missingReferences`), T54
(one `insertSetVersion` with `plan.questionnaire`: new set origin `import`, questions `s-<setId>:q1..qN`, v1 with
the file's wording, a listed questionnaire origin `import` v1 with the file's blocks), T57. The same four rules as
task 8.

Proof:
```bash
bash -c "$VT test/unit/QuestionnaireService.test.ts"                     # 40 green
bash -c "$VT test/unit/formsDefaultIsFixed.test.ts"                      # 24 green, 1 red: "R44 T30 the questionnaire actions export exactly ..." (task 15)
```

T-ids: T24, T25, T35 (service), T46, T53 (service), T54 (service), T57, T63.

### Task 10. The server-side consumers (T10, T40 service, T41 service, T43 TS, T58)

Files (every one reads `ResolvedQuestionnaireVersion` now; the field renames are those of spec 5.1):
- `src/server/services/QualificationExporter.ts`: per `form.questions[]` entry exactly
  `{key, text, citation, required, annexPoint, ownerSet: setName, ownerSetId: setId, ownerBuiltin: setBuiltin}`,
  in that key order; `form.name` = `questionnaireName`, `form.version` = `versionNumber`; the export type
  follows. Nothing else (without a questionnaire the export is byte for byte the legacy one).
- `src/server/services/OntologyService.ts`: `forms: QuestionnaireResolver = questionnaireService`; reads
  `q.questionnaireVersionId ?? null`.
- `src/server/services/QualificationService.ts`: `forms: QuestionnaireResolver = questionnaireService`;
  `createFromForm` reads the posted `questionnaireVersionId`, else `formVersionId` (D20 alias), else null; an
  unknown one throws `FormValidationError("The questionnaire this was filled with no longer exists. Reload the page.")`
  before the platform is called; `repo.create` gets `questionnaireVersionId: form.versionId` and **no**
  `formVersionId` key (strip the parser's `formVersionId`, section 3 conflict 3); `startingPoint()` returns
  `fromQuestionnaireVersionId` (via `resolveQuestionnaireVersionId`). The previous card is never updated (T41).
- `src/server/forms/QualificationFormParser.ts`: the parameter type becomes `ResolvedQuestionnaireVersion`; its
  output field stays **`formVersionId`** (the unchanged `QualificationFormParser.test.ts` pins it). Logic
  unchanged.
- `src/server/repositories/QualificationRepository.ts` and `src/domain/cardVersions.ts`: `formVersionId` becomes
  `questionnaireVersionId` (the Prisma field after task 1's generate).
- `src/app/api/qualifications/[id]/extracted/route.ts` (a file of the other session's commits e9d0693 and
  8f0ab50): only the import (`questionnaireService` from `@/server/services/QuestionnaireService`) and the one
  resolve line (`questionnaireService.resolve(q.questionnaireVersionId ?? null)`). Nothing else in the file.
- `src/lib/prefillChoice.ts`, `src/app/p/[project]/qualify/new/useDocumentPrefill.ts`: type renames, and the
  question spec carries the pinned wording (T58). No logic change beyond what `prefillChoice.test.ts` needs.
- `src/server/services/PrefillClient.ts`: only if `PrefillClient.test.ts`'s T58 case needs it (it was green in
  the red run; keep it green).

Proof:
```bash
bash -c "$VT test/unit/QualificationExporter.test.ts test/unit/annexIdentity.test.ts test/unit/QualificationService.forms.test.ts"   # 13 + 4 + 12 green
bash -c "$VT test/unit/PrefillClient.test.ts test/unit/prefillChoice.test.ts test/unit/QualificationFormParser.test.ts"              # 10 + 16 + 45 green
bash -c "$VT test/unit/fillerReadsItsProject.test.ts test/unit/agentToken.test.ts test/unit/writeAccess.test.ts test/unit/aiCardExport.test.ts test/unit/cardSubmission.test.ts"   # 4 + 10 + 16 + 10 + 2 green (guards)
```
`test/fixtures/mcas-export-before.json` is the T10 fixture the test author already wrote from the old code (the
spec's "first task" is done): never regenerate it.

T-ids: T10, T40 (service), T41 (service), T43 (TS), T58.

### Task 11. The file clients (T47 client, T54 client)

Files:
- `src/server/services/FormExportClient.ts`: `write(list: {name: string; version: number; questions: {text, citation, required, annexPoint}[]}, format)`;
  the body sends `{format, form: {name, version, questions}}` as today; everything else (503/502 messages, token
  header, `PREFILL_URL`) unchanged.
- New `src/server/services/QuestionnaireFileClient.ts`: `QuestionnaireFileClient(baseUrl = process.env.PREFILL_URL ?? "", fetchImpl = fetch, serviceToken = process.env.QUALIFICATION_WEB_TO_PREFILL_TOKEN ?? "")`,
  `write(file: QuestionnaireFileInput, bundle)` to `POST /questionnaires/export`, `read(file: File)` to
  `POST /questionnaires/import` (multipart), both never throwing: 503 `Questionnaire files are not available on this install.`
  when the base URL is empty (no fetch), 502 `The questionnaire file service could not be reached.` when fetch
  throws, a 4xx keeps the service's status and its `detail`; header `X-AISC-Service-Token` through
  `serviceTokenHeaders` of `@/server/services/http`; exported types `QuestionnaireFileInput`, `QuestionnaireFile`;
  singleton `questionnaireFileClient`. Reads only `PREFILL_URL` and `QUALIFICATION_WEB_TO_PREFILL_TOKEN`.

Proof:
```bash
bash -c "$VT test/unit/FormExportClient.test.ts test/unit/QuestionnaireFileClient.test.ts test/unit/serviceTokens.test.ts test/unit/FormImportClient.test.ts"   # 9 + 14 + 10 + 7 green
```

T-ids: T47 (client), T54 (client).

### Task 12. The DB proof and the half A checkpoint (T3 DB, T4 to T9)

```bash
cd $A && npx prisma generate                     # again: idempotent, and the DB tests need the current client
cd $A && test/db/throwaway-db.sh                 # random port, refuses 5432, removes its container on exit
docker ps -a --format '{{.Names}}' | grep aisc-t-qual- || echo none
```
Expected: Test Files 3 passed (3); Tests 89 passed (89): `twoLevelForms` 70, `cardVersions` 13,
`cardVersionOfItsProject` 6; then `none`. If docker is unavailable, say so and stop: there is no other way to a
database.

Then the half A checkpoint of section 1.3.

T-ids: T3 (DB), T4, T5, T6, T7, T8, T9.

---

### 1.3 SPLIT POINT: half A ends here, half B starts here

Why here: everything half B needs is an interface half A has finished and proven (types, domain modules,
services, clients, the DB). Half A touched nothing under `src/app/p/[project]/` except the prefill hook's types;
half B touches no file half A created, except to import it. Nothing half A made depends on anything of half B.

Half A's last act, and half B's first act, is this checkpoint (half B also re-runs task 0 steps 1 to 3 and 8, and
compares `git -C $A log --oneline -3` with half A's report):

1. `bash $P/tlf/run-all.sh split`. Expected:
   - vitest: every half A file of tasks 1 to 11 green at the counts above. Every other file exactly at its red-run
     count (table below), and every file that was fully green at task 0 still fully green. Derived total:
     about 934 passed, 367 failed, 90 skipped (1391); the per-file table is the contract, the total a cross-check.
   - ontology 272 passed, 3 failed; prefill 420 passed; renderer 50 passed; agents 168 passed.

   | Still red at the split (half B) | failed / total |
   |---|---|
   | `AnsweredForm.test.tsx` | 2 / 19 |
   | `FormChooser.test.tsx` | 11 / 15 |
   | `FormLine.test.tsx` | 6 / 9 |
   | `QualifyFormBlocks.test.tsx` | 5 / 20 |
   | `QualifyFormMove.test.tsx` | 7 / 10 |
   | `QuestionSetEditor.test.tsx` | 16 / 16 |
   | `QuestionSetImport.test.tsx` | 13 / 13 |
   | `QuestionSetPage.test.tsx` | 12 / 12 |
   | `QuestionSetsPage.test.tsx` | 11 / 11 |
   | `QuestionnaireBuilder.test.tsx` | 43 / 43 |
   | `QuestionnaireImport.test.tsx` | 10 / 10 |
   | `QuestionnairesPage.test.tsx` | 12 / 12 |
   | `RetireButton.test.tsx` | 6 / 6 |
   | `SiteHeader.test.tsx` | 1 / 2 |
   | `editSystemPage.test.tsx` | 30 / 32 |
   | `formChooser.test.ts` | 34 / 34 |
   | `formsDefaultIsFixed.test.ts` | 1 / 25 |
   | `formsLayout.test.tsx` | 20 / 22 |
   | `formsNoModel.test.ts` | 2 / 8 |
   | `formsRedirects.test.ts` | 12 / 13 |
   | `questionSetActions.test.ts` | 22 / 23 |
   | `questionSetExportRoute.test.ts` | 21 / 21 |
   | `questionnaireActions.test.ts` | 32 / 33 |
   | `questionnaireEditPage.test.tsx` | 7 / 7 |
   | `questionnaireExportRoute.test.ts` | 30 / 30 |
   | `widePage.test.ts` | 1 / 5 |

   A file that passes more than its red count is fine; one that passes fewer is half A's regression to fix
   before handing over.
2. tsc: `cd $A && npx tsc --noEmit 2>&1 | grep "error TS" | cut -d'(' -f1 | sort -u` lists only files half B owns
   (section 5 "Half B"), or test files for half B components. Zero errors in a file half A created or edited.
3. DB: task 12's 89 passed.
4. `cd $A && sha256sum -c --quiet $P/tlf/impl-tests.sha` prints nothing.
5. Half A's report lists: HEAD, the checkpoint output, every file it created, edited or deleted, anything it had
   to decide.

---

### Task 13. RetireButton and the header (T56, T60)

Files:
- New `src/app/p/[project]/RetireButton.tsx` (`"use client"`): props `{name, action: () => Promise<{error?: string} | void>}`;
  ghost `Retire`; the confirm line `Retire <name>? Cards and questionnaires that use it keep it.` with `Retire`
  and `Cancel`; an `{error}` in `div.error`.
- `src/components/SiteHeader.tsx`: with a project, `← Back`, `AI system`, `Versions`, `Question sets`
  (`/p/<project>/question-sets`), `Questionnaires` (`/p/<project>/questionnaires`), `Methodology`, in that order;
  the `Forms` link goes; without a project neither.

Proof: `bash -c "$VT test/unit/RetireButton.test.tsx test/unit/SiteHeader.test.tsx"` 6 + 2 green.

T-ids: T56, T60.

### Task 14. Question sets: actions, export route, pages, editor, import (T15 404, T17, T18, T20, T21, T47 route, T49 UI, T55 actions, T63)

Files (all new, under `src/app/p/[project]/question-sets/`):
- `actions.ts` (`"use server"` first): `saveQuestionSet(project, draftJson, setId | undefined, {origin, alsoQuestionnaire})`
  and `retireQuestionSet(project, setId)` exactly as T18 (unparseable JSON message; `createdBy: await callerName()`;
  the redirects with `?version=<n>` and `&unchanged=1`; the retire messages passed through; the service is never
  given the project).
- `import/actions.ts` (`"use server"`): `readQuestionSetFile` with the body of today's
  `forms/import/actions.ts` `readFormFile` (copy it before task 16 removes the old file).
- `[setId]/export/route.ts`, GET only: 06 R57's contract on the set (400 `format must be csv or md`; `version`
  must match `^[1-9]\d*$` else 404 `Not found` without asking the service; `questionSetService.atNumber`;
  `formExportClient.write({name, version, questions})`; client failures keep status and error; 200 bytes via
  `TextEncoder` with `Content-Type`, `Content-Disposition: attachment; filename="<filename>"`,
  `Cache-Control: no-store`). Builtin and retired sets export.
- `page.tsx` (T20, `?retired=1`), `[setId]/page.tsx` (T21, `ol.qf-set-versions`, `?version`, 404,
  `?unchanged=1`), `new/page.tsx` and `[setId]/edit/page.tsx` (T17, T15: `notFound()` for builtin, retired or
  unknown, via `questionSetService.latest`), `QuestionSetEditor.tsx` (`"use client"`, T17; reuses the old
  builder's editor panel markup and classes `qf-builder-editor`, `qf-builder-row`; no Use once, no block
  checkbox), `import/page.tsx` and `import/QuestionSetImport.tsx` (T49: `mv` the old
  `forms/import/FormImport.tsx` here, then edit; the preview is unchanged; confirming mounts the set editor with
  origin `import` and the `Also make a questionnaire with all its questions` checkbox, unchecked).
- Every page reads `NEXT_BASE_PATH` for download hrefs where it needs one (allowed by T61); no other env.
- Pages are `<main className="qualify-page qualify-page--form qf-forms-page">`.

Proof:
```bash
bash -c "$VT test/unit/questionSetActions.test.ts test/unit/questionSetExportRoute.test.ts"            # 23 + 21 green
bash -c "$VT test/unit/QuestionSetsPage.test.tsx test/unit/QuestionSetPage.test.tsx test/unit/QuestionSetEditor.test.tsx test/unit/QuestionSetImport.test.tsx"   # 11 + 12 + 16 + 13 green
```

T-ids: T15 (404), T17, T18, T20, T21, T47 (route), T49 (UI), T55 (actions), T63 (sets page).

### Task 15. Questionnaires: actions, builder, pages, export route, import (T27 to T35 UI, T48, T53 UI, T54 UI, T57 page, T63)

Files (under `src/app/p/[project]/questionnaires/`):
- `actions.ts` (`"use server"` first): exactly three exported async functions, `saveQuestionnaire`,
  `useQuestionnaireOnce`, `retireQuestionnaire` (T30), no `export const|let|var|default`, no `.admin`.
  `useQuestionnaireOnce` takes the system name from `platformClient.latestVersion(project)` (`name`), else the
  project.
- `libraryData.ts`: `builderData()` returns `{groups: await questionSetService.groups()}` (`mv` the old
  `forms/libraryData.ts` here, then rewrite).
- `QuestionnaireBuilder.tsx` (`"use client"`): `mv` the old `forms/FormBuilder.tsx` here, then rewrite to T27 to
  T33 (library column `section[aria-label="Question library"]` with `fieldset.qf-builder-forms` legend
  `Select question sets`, chips for non-retired groups only; right column `section[aria-label="Your questionnaire"]`;
  no `Edit`, no `+ New question`; `p.qf-builder-author` with the link `Write a question set`; the update box and
  `Accept all updates`; footer `Use once` and `Save questionnaire` / `Save as v<N+1>`; root
  `div.qualify-form.qf-builder` with the two sections as its only children).
- `new/page.tsx` (`?from=`), `[questionnaireId]/edit/page.tsx` (404 for builtin, unlisted, retired, unknown;
  `p.qf-saved-by`), both `<main className="qualify-page qualify-page--wide qf-forms-page">` (T31, T32, T57).
- `page.tsx` (T34, `?retired=1`, `update available` tags from `questionSetService.groups()`).
- `[questionnaireId]/export/route.ts`, GET only (T48: format, then bundle, then version; `json` through
  `questionnaireFileClient.write`, `csv`/`md` through `formExportClient.write` with the questionnaire's name and
  number; unlisted, retired and builtin export).
- `import/page.tsx`, `import/actions.ts` (`readQuestionnaireFile(formData)` with the result shapes of
  `02-tests.md` 5.4; `importSelfContained(project, fileJson, setName, questionnaireName)`), and
  `import/QuestionnaireImport.tsx` (T53 `div.error` plus `ul.qf-import-missing`; T54 preview; the page is `--form`
  for upload and preview, `--wide` once the builder mounts).

Proof:
```bash
bash -c "$VT test/unit/questionnaireActions.test.ts test/unit/questionnaireExportRoute.test.ts test/unit/formsDefaultIsFixed.test.ts"   # 33 + 30 + 25 green
bash -c "$VT test/unit/QuestionnaireBuilder.test.tsx test/unit/questionnaireEditPage.test.tsx test/unit/QuestionnairesPage.test.tsx test/unit/QuestionnaireImport.test.tsx"   # 43 + 7 + 12 + 10 green
```

T-ids: T27 to T33 (component), T30, T31, T32 (pages), T34, T35 (pages), T48, T53 (UI), T54 (UI), T57 (page), T63.

### Task 16. The old /forms: redirects, and the old form code removed (T62, T61)

1. `tar -tf $P/tlf/impl-untracked-src.tar | head` works (the backup exists). If it does not, stop.
2. The four old pages become redirects only, each calling `permanentRedirect` from `next/navigation`, importing
   no service and no builder (the test greps the source for `FormBuilder|QuestionnaireBuilder|FormImport|builderData|formService`):
   - `forms/page.tsx` to `/p/<project>/questionnaires`;
   - `forms/new/page.tsx` to `/p/<project>/questionnaires/new`, plus `?from=<encodeURIComponent(from)>` when a
     non-empty `from` is given;
   - `forms/[formId]/edit/page.tsx` to `/p/<project>/questionnaires/<encodeURIComponent(formId)>/edit`;
   - `forms/import/page.tsx` to `/p/<project>/question-sets/import`.
3. `forms/[formId]/export/route.ts`, GET only: a plain `Response` with status 308 and
   `Location: <NEXT_BASE_PATH or ""> + /p/<project>/questionnaires/<encodeURIComponent(formId)>/export + <new URL(request.url).search>`
   (the query passed on untouched; `formId` arrives decoded, so `a b` goes out as `a%20b`). It reads only
   `NEXT_BASE_PATH`.
4. Delete (plain `rm`, one path at a time; they are untracked, and the backup is in `$P`): `src/app/p/[project]/forms/actions.ts`,
   `forms/import/actions.ts`, and, if a copy was left behind by the `mv`s of tasks 14 and 15, `forms/FormBuilder.tsx`,
   `forms/libraryData.ts`, `forms/import/FormImport.tsx`; also `src/domain/forms/formDraft.ts`,
   `src/server/services/FormService.ts`, `src/server/repositories/FormRepository.ts`.
5. The grep that proves nothing references the removed code (from `$A`):
   ```bash
   grep -rnE "FormService|FormRepository|formDraft|FormBuilder|FormImport[^C]|FormImport$|libraryGroups|ResolvedFormVersion|FormResolver|DEFAULT_FORM_ID|resolveFormVersionId|formService|pickFormParams|sourceUpdates|LibraryGroup|ownerFormName|fromFormVersionId|takeLatest|prisma\.form\b|prisma\.formVersion|\.formVersionQuestion|\.formQuestion" src scripts prisma/schema.prisma
   ```
   Expected: no output. Then `grep -rn "formVersionId\|ownerFormId\|ownerForm\b" src` lists exactly the three
   deliberate keepers: the D20 alias read in `src/server/services/QualificationService.ts`, the parser's output
   field in `src/server/forms/QualificationFormParser.ts` (and the service line that strips it), and nothing
   else; any other hit is dead code to remove. `?form=`/`?formVersion=` stay only in `chooser.ts` and the edit
   page (T39 aliases).

Proof:
```bash
bash -c "$VT test/unit/formsRedirects.test.ts test/unit/formsNoModel.test.ts"                    # 13 + 8 green
```

T-ids: T62, T61 (TS scans).

### Task 17. The chooser, the edit page and the card (T36 to T42, T44)

Files:
- `src/domain/forms/chooser.ts`: `preselect(options, {fromVersionId})` (T37: the exact previous version, D11),
  `QuestionnaireLookup`, `pickQuestionnaireParams({example, questionnaire, questionnaireVersion, form, formVersion})`
  (T39 precedence, empty strings absent); `pickFormParams` gone.
- `src/app/p/[project]/system/edit/FormChooser.tsx`: texts and values of T36, T38 and `02-tests.md` 5.4.
- `src/app/p/[project]/system/edit/page.tsx`: `questionnaireService` (resolve / latestVersion), the lookups, the
  error `That questionnaire was not found.`, `previous` and `cardNumber` to `QualifyForm` only when the chosen
  version differs from the previous card's (T41), and `FormLine` with the new props. Keep the strings the
  unchanged source tests need (`prefillOnEditPage.test.ts`, `FormLine.test.tsx`, `editSystemPage.test.tsx`: no
  `defaultFormId`, no `find((o) => o.isDefault)`, `<FormLine`, no `Form: {`).
- `src/app/p/[project]/qualify/new/QualifyForm.tsx`: `form: ResolvedQuestionnaireVersion`; heading
  `groupLabel ?? setName`; hidden input `questionnaireVersionId` (no `formVersionId` input); `p.qf-moving` and
  `p.qf-wording-changed` from `moveNotice` / `rewordedSince` (T40, T41).
- `src/app/p/[project]/qualify/[id]/AnsweredForm.tsx`: same type and heading rule (T40).
- `src/app/p/[project]/FormLine.tsx`: props `{project, questionnaireId, questionnaireName, versionNumber, basePath?, newer?}`
  (tests also pass `form`: accept and ignore it, or type it optional); `Questionnaire: <name> v<N>`, the `JSON`,
  `CSV`, `Markdown` links to `/questionnaires/<id>/export`, `p.qf-questionnaire-update` and `Move to v<M>` (T42).
  Reads no env (the pages pass `basePath`).
- `src/app/p/[project]/qualify/[id]/page.tsx`: the line matching
  `resolve\(q\.questionnaireVersionId \?\? null\)\)\s*\?\?\s*annexDefaultVersion\(\)`, `newerVersion(` for the
  current card only, `<FormLine ... newer=...>`, no `formVersionId`, no `Form: {` or `Questionnaire: {`.
- `VerticalCard.tsx`: no change expected (T44 was green in the red run).

Proof:
```bash
bash -c "$VT test/unit/formChooser.test.ts test/unit/editSystemPage.test.tsx"          # 34 (+ FormChooser.test.tsx 15, by substring) + 32 green
bash -c "$VT test/unit/QualifyFormMove.test.tsx test/unit/QualifyFormBlocks.test.tsx test/unit/AnsweredForm.test.tsx test/unit/FormLine.test.tsx test/unit/VerticalCard.test.tsx"   # 10 + 20 + 19 + 9 + 8 green
bash -c "$VT test/unit/formPrefill.test.tsx test/unit/formUpload.test.tsx test/unit/prefillOnEditPage.test.ts test/unit/cardSubmission.test.ts"   # 10 + 6 + 7 + 2 green (guards)
```

T-ids: T36, T37, T38, T39, T40 (components), T41 (UI), T42, T44.

### Task 18. Layout (T32)

Files: `src/app/globals.css` only if a pinned rule needs it (formsLayout B2, B4, P4 and widePage's rules must stay
byte-compatible with their regexes); new classes (`qf-set-versions`, `qf-builder-update`, `qf-new-wording`,
`qf-moving`, `qf-wording-changed`, `qf-questionnaire-update`, `qf-import-missing`, `qf-saved-by`,
`qf-builder-author`, `qf-tag--notice`) get minimal rules in the design-pass style, or none.

Proof: `bash -c "$VT test/unit/formsLayout.test.tsx test/unit/widePage.test.ts"` 22 + 5 green; then
`bash -c "$VT"` with 0 failed (section 6.1).

T-ids: T32.

### Task 19. Full verification

Section 6, in full. Then the report of section 6.6.

---

## 2. The migration: `prisma/migrations/20260925150000_two_level_forms/migration.sql`

### 2.1 File rules (spec 4.1, and what `twoLevelMigration.test.ts`, `twoLevelSchema.test.ts` and `formsDefaultIsFixed.test.ts` scan)

- Every table, index target, function and trigger target is `qualification.`-qualified. Temp tables are named
  `tlf_*` (the only unqualified `INSERT INTO` targets the scan accepts).
- Never write `BEGIN;` (a DO body's `BEGIN` followed by a newline is fine), `COMMIT` (the only allowed form is
  `ON COMMIT DROP`), `CONCURRENTLY`, `IF EXISTS` (not even inside a DO block: write `IF NOT EXISTS (...)` or
  `IF (SELECT count(*) ...) > 0`), `CASCADE`, `START TRANSACTION`. This holds for DO bodies too; only the bodies of
  `CREATE OR REPLACE FUNCTION ... $$ ... $$` are exempt from the scan.
- No line (after leading spaces) and no text after a `;` starts with `UPDATE`, `DELETE FROM` or `TRUNCATE`, DO
  bodies included. Rows are only written with `INSERT`.
- No DO block has an `EXCEPTION` clause (no line starting `EXCEPTION` or `EXCEPTION WHEN`); `RAISE EXCEPTION` is fine.
- Comments: plain `--` lines. No `$$` inside comments; no trailing `--` comment after code on a line that
  contains a `'` (the scan's comment stripper toggles on quotes); no word `COMMIT`, `CASCADE`, `IF EXISTS` in
  comments either (one scan strips comments naively with `--[^\n]*`, but keep them clean anyway).
- Every `CREATE TABLE qualification.<t> (` has one space before `(` and ends with `);` alone on its own line at
  column 0 (the T63 regex is `CREATE TABLE qualification\.(t) \(([\s\S]*?)\n\);`).
- The capture is written exactly `CREATE TEMP TABLE tlf_counts ON COMMIT DROP AS SELECT` (the T2 regex).
- The questionnaire item position index is written `CREATE UNIQUE INDEX questionnaire_version_item_version_id_position_key`
  then whitespace (a newline is fine) then exactly `ON qualification.questionnaire_version_item (questionnaire_version_id, position)`,
  and the same name is the schema's `map:` (T1).
- Do not copy the scratch reference: it keeps the 64-byte index name and omits parts of C2 to C4.

### 2.2 Order of operations (one implicit transaction; any `RAISE EXCEPTION` rolls back everything)

1. **Capture.** `CREATE TEMP TABLE tlf_counts ON COMMIT DROP AS SELECT` one row with nine bigint columns: the
   counts of `qualification`, `qualification_answer`, `qualification_risk`, `knowledge_graph`, `card_component`,
   `form`, `form_version`, `form_question`, `form_version_question`.
2. **Precondition P1** (one DO block). Raise exactly `two-level forms migration: the builtin form annex-iv-default v1 is not as seeded`
   unless all hold: exactly one `form` row has `origin = 'builtin'`; it is `annex-iv-default`; `annex-iv-default`
   has exactly one `form_version`, and it is `annex-iv-default-v1` with `number = 1`; that version has exactly
   14 `form_version_question` rows; and exactly 14 of them join a `form_question` owned by `annex-iv-default`
   whose id is one of the 14 `annex-iv-<id>` (`1a 1b 1c 1de 1f 1gh 2a 2b 2c 2d 2e 2f 2g 2h`). The wording is not
   checked (T9 "tampered wording" expects it copied as is).
3. **Create** the seven tables in the order of spec 3.1 (`question_set`, `question_set_version`, `question`,
   `question_set_version_item`, `questionnaire`, `questionnaire_version`, `questionnaire_version_item`), each
   followed by its indexes, with the DDL of 3.1 verbatim except the one index name. No trigger yet.
   `questionnaire_version_item` must be made by a plain `CREATE TABLE` (the C5/C8 abort tests arm their trigger
   from an event trigger on exactly that command and that object).
4. **Builtin level**: seven `INSERT ... SELECT` from the old rows, in this order: `question_set` (`annex-iv`,
   `Annex IV`, the literal description `EU AI Act Annex IV points 1 and 2, as 14 questions.`, `builtin`, NULL,
   the created_at of form `annex-iv-default`, `system`); `question` (one per `form_question` owned by
   `annex-iv-default`, same id, scope, local_id, created_at, `set_id = 'annex-iv'`); `question_set_version`
   (`annex-iv-v1`, `annex-iv`, 1, the created_at of `annex-iv-default-v1`, `system`); `question_set_version_item`
   (one per old row of `annex-iv-default-v1`, every column copied); `questionnaire` (`annex-iv-default`,
   `Annex IV default`, the form's description, `builtin`, true, NULL, the form's created_at, `system`);
   `questionnaire_version` (`annex-iv-default-v1`, `annex-iv-default`, 1, the old blocks, the old created_at,
   `system`); `questionnaire_version_item` (one per old row: same position, `annex-iv-v1`, same question_id).
5. **Pass A, sets from the other forms.** `CREATE TEMP TABLE tlf_assigned (form_version_id text PRIMARY KEY, set_version_id text NOT NULL) ON COMMIT DROP`,
   then one DO block. For each form F with `origin <> 'builtin'` that owns at least one `form_question`, ordered by
   `(created_at, id)`:
   1. insert its `question_set`: `id = F.id`, name, description, origin as F, `retired_at = now()` when F is
      unlisted else NULL (D2), `created_at = F.created_at`, `created_by = 'unknown'`;
   2. insert one `question` per `form_question` F owns (same id, scope, local_id, created_at; `set_id = F.id`);
   3. for each version Vk of F in `number` order: build L(Vk), the rows of Vk whose question F owns, in position
      order, as a list of `(question_id, text, citation, required, annex_point, group_label)`. A convenient exact
      form is a `jsonb_agg(jsonb_build_array(...) ORDER BY position)`: jsonb equality compares element by
      element and treats JSON null as equal to JSON null, which is the `IS NOT DISTINCT FROM` the spec asks for.
      Empty L: Vk gets no set version and no `tlf_assigned` row. L equal to the list of the set version this pass
      made last for F: Vk is assigned that one. Otherwise insert set version
      `n = coalesce(max(number) of F's set, 0) + 1`, `id = F.id || '-v' || n`, `created_at = Vk.created_at`,
      `created_by = 'unknown'`, with items L(Vk) at positions 0, 1, ... (renumbered, not the form positions), and
      assign it. Record `(Vk.id, set_version_id)` in `tlf_assigned`.
6. **Pass B, questionnaires from the other forms.** One DO block. For each form F with `origin <> 'builtin'`,
   ordered by `(created_at, id)` (the order matters: in T8, `once` must pin `acme-v2` before `odd` creates
   `acme-v3`):
   1. insert its `questionnaire`: `id = F.id`, name, description, origin, listed as F, `retired_at` NULL,
      `created_at = F.created_at`, `created_by = 'unknown'`;
   2. for each version Vk in `number` order: insert `questionnaire_version` with `id = Vk.id` (D1: no card row
      needs an UPDATE), `questionnaire_id = F.id`, same number, blocks, created_at, `created_by = 'unknown'`;
   3. for each row r of Vk in position order, with X its question and O its owner form: S = `annex-iv` when O is
      `annex-iv-default`, else O. The pin: when O = F, Vk's row in `tlf_assigned`; otherwise the set version of S
      with the highest `number` whose item for X has the same text, citation, required and, with
      `IS NOT DISTINCT FROM`, annex_point and group_label. When none matches: S = `annex-iv` raises
      `two-level forms migration: form version % pins wording of % that no version of Annex IV has` (Vk.id, X);
      otherwise insert set version `n = coalesce(max, 0) + 1` of S (`id = S || '-v' || n`,
      `created_at = Vk.created_at`, `created_by = 'unknown'`) whose items are S's highest version's items (same
      positions) with X's wording replaced by r's, or, when X is not among them, X appended at
      `coalesce(max(position) + 1, 0)`; then `RAISE NOTICE 'two-level forms migration: made question set version % for the wording pinned in form version %'`
      (the new id, Vk.id), and pin to it. A later pick of the same wording then finds this version as the highest
      match, so one fallback per distinct wording.
   4. insert `questionnaire_version_item (Vk.id, r.position, <pin>, X)`: the form positions are kept as they are
      (the C5 check compares them).
7. **Checks C1 to C7**, one DO block, in this order, each failure
   `RAISE EXCEPTION 'two-level forms migration: check C<n> failed: expected %, found %'` with the numbers:
   - C1 `count(question_set)` = 1 + the number of non-builtin forms owning at least one `form_question`.
   - C2 `count(question)` = `count(form_question)`; then zero `form_question` rows without a `question` of the same
     id, scope, local_id and the expected set_id (expected 0, found <that count>).
   - C3 `count(questionnaire)` = `count(form)`; then zero forms without a questionnaire of the same id, name,
     description, origin, listed, created_at.
   - C4 `count(questionnaire_version)` = `count(form_version)`; then zero form versions without a questionnaire
     version of the same id, `questionnaire_id = form_id`, number, blocks, created_at.
   - C5 `count(questionnaire_version_item)` = `count(form_version_question)`; then zero `form_version_question`
     rows without an item of the same (version id, question_id, position) whose set item has the same five wording
     fields (nullable ones with `IS NOT DISTINCT FROM`). The C5 abort test accepts either
     `expected 14, found 13` or `expected 0, found 1`.
   - C6 zero `question_set_version_item` rows whose question's set_id differs from its set version's set_id.
   - C7 `annex-iv-v1` has 14 items; `annex-iv-default-v1` has 14 items; zero of those point elsewhere than
     `annex-iv-v1`. C7 must come after C5: the C5 abort test's swallowed item would trip C7 too, and the test wants
     the C5 message.
8. **The card column**, exactly the four statements of spec 4.2 step 8, in that order (drop the old FK first:
   without it `DROP TABLE qualification.form_version` fails, since there is no CASCADE). No row is updated, so the
   card triggers do not fire; `ADD CONSTRAINT` validates every non-NULL value, each an old form version id that
   step 6.2 made a questionnaire version id.
9. **Drops**, in this order, no CASCADE: `DROP TABLE qualification.form_version_question;`,
   `DROP TABLE qualification.form_question;`, `DROP TABLE qualification.form_version;`,
   `DROP TABLE qualification.form;` (the text `DROP TABLE qualification.form;` must appear exactly, with the
   semicolon), then `DROP FUNCTION qualification.<f>();` for `form_version_is_append_only`,
   `form_version_question_is_append_only`, `form_question_identity_is_fixed`, `form_name_is_fixed`,
   `form_builtin_is_fixed`. The old triggers, `form_builtin_is_the_default`, `form_listed_name_key` and the
   `copied_from_id` FK go with their tables.
10. **Triggers**, after the last `DROP TABLE` (T2 checks each `CREATE TRIGGER` comes after it), in the order of
    spec 3.2, for each: `CREATE OR REPLACE FUNCTION qualification.<name>() RETURNS trigger LANGUAGE plpgsql AS $$ ... $$;`
    then `CREATE TRIGGER <name> <timing> ON qualification.<table> FOR EACH ROW EXECUTE FUNCTION qualification.<name>();`
    (plain `CREATE TRIGGER`, not `CREATE OR REPLACE TRIGGER`: the test regex wants `CREATE\s+TRIGGER\s+<name>`,
    each exactly once). Trigger name = function name. Bodies and messages exactly spec 3.2:
    - the four `_is_append_only`: BEFORE UPDATE OR DELETE, raise the "immutable" message with `OLD.id`,
      `OLD.set_version_id`, `OLD.id`, `OLD.questionnaire_version_id` respectively;
    - `question_identity_is_fixed`: BEFORE UPDATE OR DELETE on `question`; DELETE raises `question % cannot be deleted: versions refer to it`;
      a change of set_id, scope, local_id or created_at raises `question % keeps its identity: set, scope and local id are fixed`;
      otherwise `RETURN NEW`;
    - `question_set_version_item_is_of_its_set`: BEFORE INSERT; the two subselects compared with `IS DISTINCT FROM`;
      `question % is not a question of the set of version %` (NEW.question_id, NEW.set_version_id);
    - `question_set_row_is_fixed` and `questionnaire_row_is_fixed`: BEFORE UPDATE OR DELETE; DELETE raises
      `... cannot be deleted: retire it instead`; an UPDATE changing name, origin, created_at, created_by (and
      listed for the questionnaire), or changing retired_at when `OLD.retired_at IS NOT NULL`, raises the "keeps its
      name, origin ..." message; description and a first retire pass. The builtin rows cannot be retired because
      the CHECK refuses it after the trigger passes (T5 wants the CHECK's name in that error);
    - `question_set_version_is_allowed` and `questionnaire_version_is_allowed`: BEFORE INSERT; first the builtin
      rule (the parent is builtin and a version exists), then the retired rule.
11. **Final check C8**, one DO block: each of the five history counts equals its value in `tlf_counts`, table by
    table, raising `check C8 failed: expected <captured>, found <now>` for the first that differs (the C8 abort
    test wants found = expected + 1 for `qualification_risk`); then zero of `to_regclass('qualification.form')`,
    `..._version`, `..._question`, `..._version_question` is non-NULL (expected 0, found <how many remain>).

The unique answer index `qualification_answer_qualification_id_tool_id_question_id_key` is not touched.

### 2.3 Coexistence with the existing triggers and objects

- **Card triggers** (`qualification_only_latest_changes` BEFORE UPDATE on `qualification`,
  `qualification_answer_only_latest_changes` on answers, `component_only_latest_changes` on `card_component`): the
  migration writes no row of any history table, and `ALTER TABLE ... DROP/ADD CONSTRAINT`, `RENAME COLUMN` and
  `ALTER INDEX ... RENAME` fire no row trigger. T9's write log (AFTER triggers on the five tables, including
  TRUNCATE) and its `ctid` comparison would catch even a no-op UPDATE.
- **Old form triggers** go with their tables (step 9); their five functions are dropped by name after the
  tables, so no trigger still references them.
- **Name clashes**: the ten new function names do not exist in schema `qualification` today (the existing ones
  are `card_is_latest`, the three `*_only_latest_changes`, and the five `form_*` this migration drops).
- **Test-only objects** (the DB tests' `t_log_write`, `t_arm` event trigger, `t_swallow`, `t_write_history`) are
  created by the tests around the migration; the migration must not depend on or disturb them.
- **Ownership**: `prisma migrate deploy` runs the file as `qualification_rw` on the throwaway DB, which owns the
  form tables, their functions and `qualification.qualification` (every earlier migration ran as it). On live,
  `qualification-migrate` must run it as the same role that applied 090000; otherwise `DROP FUNCTION` fails
  loudly and the transaction rolls back.
- **Locks**: `ALTER TABLE qualification.qualification` takes an ACCESS EXCLUSIVE lock for the few milliseconds of
  the rename and FK validation (one row on live).
- **Prisma bookkeeping**: 090000 and 120000 keep their bytes, so `_prisma_migrations` never reports them modified.
  Never `prisma migrate dev`, `db push` or `migrate reset`.

### 2.4 Abort paths (what a failure leaves)

Every abort is one of: P1's message; the Annex IV pin message; a CHECK of 3.1 (for example D29's 600-character
description on `question_set_description_length`), a unique index (a custom listed form named "Annex IV" in any
case, section 3 item 9), or an FK; C1 to C8. In each case Postgres rolls back the whole file: the old tables,
the old column and every row are as they were (the DB tests prove it for P1, D29, C5 and C8). `prisma migrate deploy`
then records the migration as failed (P3009) and refuses to go on until
`prisma migrate resolve --rolled-back 20260925150000_two_level_forms` after the data is fixed (spec 4.4). There
is no down path after success: the `pg_dump` of task 2's DEPLOY.md step is the way back.

---

## 3. Conflicts found, and how this plan resolves them (tests win)

1. **The 64-byte index name** (spec 3.1, 3.3 vs `prisma validate` and T1). The name
   `questionnaire_version_item_version_id_position_key` (50 bytes) is used in the schema and the migration.
2. **`ON COMMIT DROP` vs "no COMMIT"** (spec 4.1 vs 4.2 step 1). T2 exempts exactly `ON COMMIT DROP`.
3. **The parser's output field** (spec 5.1 renames consumers; the unchanged `QualificationFormParser.test.ts`
   still expects `formVersionId` in the parsed output, and `QualificationService.forms.test.ts` wants
   `repo.create` without a `formVersionId` key). The parser keeps `formVersionId`; `QualificationService` strips
   it and stores `questionnaireVersionId`.
4. **Three committed tests mock a module this plan deletes.** `agentToken.test.ts`, `fillerReadsItsProject.test.ts`
   and `writeAccess.test.ts` (the other session's) mock `@/server/services/FormService`. After task 10 the
   extracted route imports `QuestionnaireService` instead: their mock becomes inert (vitest accepts a factory mock
   of a module nobody imports) and the real `QuestionnaireService` loads with `@/lib/prisma` mocked. So the new
   service and repositories must do nothing at import or construction, and `resolve(null)` must not touch the
   repository. Task 10's proof runs those three files. If one still fails, stop and report: those tests are not
   this pipeline's to edit.
5. **The spec's "plan's first task" writes the T10 fixture.** The test author already wrote
   `test/fixtures/mcas-export-before.json` from the unchanged code; task 10 must not regenerate it.
6. **The scratch reference migration** passes the DB tests but keeps the 64-byte name (Postgres cut it with a
   NOTICE) and checks only counts in C2 to C4. The plan implements every part of spec 4.2 step 7.
7. **Chooser placement.** Spec 5.2 lists `chooser.ts` with the pure modules; this plan does it in half B (task 17)
   so that `editSystemPage.test.tsx`'s two green guards do not go red between the halves (the page imports
   `pickFormParams`, which T39 removes).
8. **Old files still required by `formsNoModel.test.ts`** (`R73 NEW_PARTS`): `src/app/p/[project]/FormLine.tsx` and
   `src/app/p/[project]/forms/[formId]/export/route.ts` must keep existing (the latter as a redirect).
9. **Not tested, left as is (decision for the product owner, not taken here):** a custom listed form named
   "Annex IV" in any case that owns questions would make a second active set of that name and abort the migration
   on `question_set_active_name_key` with Postgres' bare unique-violation message. Live has none. This plan adds no
   extra precondition for it; say so in the final report.
10. **The e9d0693 / 8f0ab50 files.** Only `src/app/api/qualifications/[id]/extracted/route.ts` overlaps; task 10
    changes its import and one line, nothing else.

---

## 4. Risks, and how each is guarded

1. **Graph digest.** The ontology graph reads per answer `toolId`, `questionId`, `answer`, `annexPoint` and, for
   non-Annex scopes, `citation`; never the owner keys. Guards: T11 (`test_owner_set_keys.py`: digest, Turtle
   isomorphism and the whole view equal with either key style), `test_coverage.py` unchanged and green, and T9's
   live test (the stored `knowledge_graph` row, digest, md5 of Turtle and JSON-LD, counts and `built_at`
   unchanged). Do not touch `build.py`, `view.py` or the examples.
2. **Card JSON bytes.** The stored `systemCardJson` is never written by the migration (T9 live: byte-identical
   card JSON and whole card row minus the renamed column). A card JSON rebuilt later is the same because the view
   keeps its keys `form`, `forms`, `additionalDocumentation` (D17) and the Annex IV names are unchanged (T10's
   fixture, T11). Do not rename view keys.
3. **Answers identity.** Answers are keyed `(toolId = scope, questionId = localId)`. The migration keeps every
   question's id, scope and local id; new questions are `s-<setId>:q<n>`, never reused; answers carry over by field
   `q:<scope>:<localId>` (T41). Guards: T8's before/after lists per version, T9's answer rows with `ctid`, T7's
   answer index.
4. **Migration abort paths.** Section 2.4. The early DB checkpoint in task 1 finds SQL mistakes before code
   depends on them; task 12 proves all 70 migration tests.
5. **The two older DB test files need `prisma generate`.** `cardVersions.db.test.ts` and
   `cardVersionOfItsProject.db.test.ts` use the generated client (`app.qualification.create`); with a stale client
   they fail on "column `qualification.form_version_id` does not exist". Section 4.3 lists every generate.
6. **Root-owned files.** `services/agents/application.log` and `services/ontology/{,airo_min/,tests/}__pycache__`
   are root-owned. Always `PYTHONPYCACHEPREFIX=$P/pyc` and `-p no:cacheprovider`; run agents from `$P/agents-cwd`.
   Never `sudo`, `chown`, `chmod` or delete them.
7. **The other session commits on this branch.** It may commit while this runs, and a careless commit of theirs
   could sweep in this pipeline's untracked files. Before every proof run: `git -C $A log --oneline -3` and
   `git -C $A status --short`; if a new commit touches a file of section 5, or includes files this pipeline
   created, stop and report. Never commit, stash, reset or checkout to "fix" it.
8. **Irreversible deletes.** Every file this plan removes is untracked: task 0's tar is the only copy. Moves are
   `mv` (never copy-then-rewrite-from-memory), and deletes happen only in task 16, after the backup check.
9. **`prisma generate` is shared.** It rewrites `node_modules/.prisma` for everyone using `$A`, the other session
   included (their tests would then see `questionnaireVersionId`). It does not affect the live stack (image-based,
   no mount). Mention it in both halves' reports.
10. **tsc between the halves.** After half A, type errors are expected in files half B owns (section 1.3 step 2).
    At the end: zero. A test file that cannot type-check against any reasonable source (as happened once in round
    2) is reported, never edited.
11. **Timing of vitest runs.** A failing file imported through `loadSrc` fails only its tests; a full run with
    many ENOENT/"Cannot find module" failures is slower but not hung.

### 4.3 When `prisma generate` runs

1. Task 1, right after the schema edit (the repositories of task 8 need the new client types; the DB tests need
   the new client).
2. Task 12, before `throwaway-db.sh`.
3. Half B's first act (after the split checkpoint): once, in case the other session regenerated from another
   schema in between.
4. Section 6, before the DB run and before `tsc`.

---

## 5. Files

### Half A
Created: `prisma/migrations/20260925150000_two_level_forms/migration.sql`,
`services/prefill/prefill/questionnaire_file.py`, `src/domain/forms/{questionSetDraft,setEditorState,questionnaireDraft,moveCard,references}.ts`,
`src/server/access/callerName.ts`, `src/server/repositories/{QuestionSetRepository,QuestionnaireRepository}.ts`,
`src/server/services/{QuestionSetService,QuestionnaireService,QuestionnaireFileClient}.ts`.

Edited: `prisma/schema.prisma`, `Dockerfile` (last line), `DEPLOY.md`, `services/ontology/airo_min/coverage.py`,
`services/prefill/app.py`, `services/prefill/README.md`, `src/domain/forms/{types,legacy,library,builderState}.ts`,
`src/server/services/{QualificationExporter,OntologyService,QualificationService,FormExportClient}.ts` (and
`PrefillClient.ts` only if needed), `src/server/forms/QualificationFormParser.ts`,
`src/server/repositories/QualificationRepository.ts`, `src/domain/cardVersions.ts`, `src/lib/prefillChoice.ts`,
`src/app/p/[project]/qualify/new/useDocumentPrefill.ts`, `src/app/api/qualifications/[id]/extracted/route.ts`.

Deleted: none (`formDraft.ts`, `FormService.ts`, `FormRepository.ts` wait for task 16).

### Half B
Created: `src/app/p/[project]/RetireButton.tsx`; under `src/app/p/[project]/question-sets/`: `page.tsx`,
`actions.ts`, `QuestionSetEditor.tsx`, `new/page.tsx`, `[setId]/page.tsx`, `[setId]/edit/page.tsx`,
`[setId]/export/route.ts`, `import/page.tsx`, `import/actions.ts`, `import/QuestionSetImport.tsx` (moved from
`forms/import/FormImport.tsx`); under `src/app/p/[project]/questionnaires/`: `page.tsx`, `actions.ts`,
`QuestionnaireBuilder.tsx` (moved from `forms/FormBuilder.tsx`), `libraryData.ts` (moved from
`forms/libraryData.ts`), `new/page.tsx`, `[questionnaireId]/edit/page.tsx`, `[questionnaireId]/export/route.ts`,
`import/page.tsx`, `import/actions.ts`, `import/QuestionnaireImport.tsx`.

Edited: `src/components/SiteHeader.tsx`, `src/domain/forms/chooser.ts`, `src/app/p/[project]/FormLine.tsx`,
`src/app/p/[project]/system/edit/{page.tsx,FormChooser.tsx}`, `src/app/p/[project]/qualify/new/QualifyForm.tsx`,
`src/app/p/[project]/qualify/[id]/{page.tsx,AnsweredForm.tsx}`, `src/app/p/[project]/forms/{page.tsx,new/page.tsx,[formId]/edit/page.tsx,[formId]/export/route.ts,import/page.tsx}`
(redirects), `src/app/globals.css` (only if needed).

Deleted: `src/app/p/[project]/forms/{actions.ts,import/actions.ts}` (and any leftover of the three moves),
`src/domain/forms/formDraft.ts`, `src/server/services/FormService.ts`, `src/server/repositories/FormRepository.ts`.

Generated, not tracked: `node_modules/.prisma`. Nothing else in the repository changes; no test, fixture or
support file changes at all.

---

## 6. Full verification (task 19; expected final counts)

From a clean shell with the variables of the top.

### 6.1 TypeScript
```bash
cd $A && npx prisma generate
cd $A && npx vitest run
cd $A && npx tsc --noEmit
cd $A && env $DUMMY npx prisma validate
```
Expected: **Test Files 99 passed, 4 skipped (103); Tests 1301 passed, 90 skipped (1391); 0 failed** (the 90 are
the 89 DB tests plus `test/chain/chain.test.ts`'s one skip; the 4 skipped files are the 3 DB files and the chain
file). `tsc`: 0 errors. Prisma: valid.

Optional, only when `pgrep -af "next (dev|start)"` shows no process whose cwd is `$A`: `cd $A && npm run build`,
exit 0, the route list gaining `/p/[project]/question-sets*` and `/p/[project]/questionnaires*`, the `/forms*`
routes still listed (as redirects).

### 6.2 Python
```bash
bash -c "$ONTO"      # 272 passed, 3 failed: test_build.py::test_a_full_qualification_exercises_all_nineteen_properties,
                     # test_example_mcas.py::test_it_exercises_all_nineteen_properties,
                     # test_roundtrip.py::test_the_rebuilt_graph_keeps_every_airo_relation (pre-existing; do not fix)
bash -c "$PREF"      # 420 passed
bash -c "$REND"      # 50 passed
bash -c "$AGENTS"    # 168 passed
```
or `bash $P/tlf/run-all.sh impl-after`.

### 6.3 DB (throwaway only)
`cd $A && test/db/throwaway-db.sh`: Test Files 3 passed (3), Tests 89 passed (89). Then
`docker ps -a --format '{{.Names}}' | grep aisc-t-qual- || echo none` prints `none`.

### 6.4 By reading
- `cd $A && sha256sum -c --quiet $P/tlf/impl-tests.sha` prints nothing (every test, fixture and support file
  byte-identical to task 0). A line printed: check `git -C $A log -1 -- <file>` (the other session?) before
  reporting.
- The two applied migrations still hash to task 0's values.
- Task 16's grep prints nothing, and its keeper grep lists only the deliberate keepers.
- `grep -rnP "\x{2014}" <every file of section 5>` finds no em dash this pipeline added (DEPLOY.md has old ones; compare
  with `git -C $A diff -- DEPLOY.md`).
- `git -C $A status --short` differs from `$P/tlf/impl-status-before.txt` only by section 5's files;
  `git -C $A log --oneline -3` unchanged, or only the other session's commits.
- `git -C $A diff --stat -- Dockerfile` is one line changed.
- T-id closure: every T1 to T63 has its tests green (table 6.5); list any that does not.

### 6.5 T-ids closed per task

| Task | T-ids |
|---|---|
| 1 | T1, T2 |
| 2 | T59 |
| 3 | T11, T43 (Python) |
| 4 | T50, T51, T52, T61 (Python) |
| 5 | T3 (unit) |
| 6 | T12, T13, T16, T22, T23, T26, T27 to T33 (state), T41, T42 (functions), T53 (pure) |
| 7 | T55 (function) |
| 8 | T14, T15 (service), T19, T45, T49 (service), T57, T63 |
| 9 | T24, T25, T35 (service), T46, T53 (service), T54 (service), T57, T63 |
| 10 | T10, T40 (service), T41 (service), T43 (TS), T58 |
| 11 | T47 (client), T54 (client) |
| 12 | T3 (DB), T4, T5, T6, T7, T8, T9 |
| 13 | T56, T60 |
| 14 | T15 (404), T17, T18, T20, T21, T47 (route), T49 (UI), T55 (actions), T63 |
| 15 | T27 to T35 (UI), T48, T53 (UI), T54 (UI), T57 (page), T63 |
| 16 | T61 (TS), T62 |
| 17 | T36, T37, T38, T39, T40, T41 (UI), T42, T44 |
| 18 | T32 |

### 6.6 The final report (half B)

Counts of 6.1 to 6.3 as printed; the grep results; every file created, edited, moved or deleted; the decisions
this plan left open (section 3 item 9); that the Dockerfile changed and the live stack did not (nothing was
rebuilt, restarted or deployed); that `prisma generate` rewrote `node_modules/.prisma`.

---

## 7. Must not do (from the brief, and from this plan)

- No `prisma migrate deploy|dev|reset|resolve`, no `prisma db push`, no SQL or psql against any running database.
  Ports 5432 and 5433 are the live stack. The only database allowed is the one `test/db/throwaway-db.sh` starts on a
  random port and removes; DB tests run only through that script. Leave no container behind; never touch another
  session's containers.
- No docker change other than the Dockerfile's last line (T59): no compose edits, no image build or pull, no
  rebuild, restart or deploy.
- No commits, pushes, branch switches, `git stash`, `git reset`, `git checkout` (any form), `git restore`,
  `git clean`, `git add -A` or `git add .`: another session commits on this branch.
- Never edit, weaken, skip, rename or delete a test, fixture or test-support file (`test/**`,
  `services/*/tests/**`, `test/fixtures/*`, `test/support/*`). The tests the spec changed were already changed by
  the test author. If a test looks wrong, stop and report it with the reason.
- Never edit `prisma/migrations/20260925090000_forms_are_data/migration.sql` or
  `20260925120000_the_default_form_is_fixed/migration.sql`.
- Do not touch the other session's files beyond task 10's two lines in `extracted/route.ts`: `services/agents/**`,
  `services/llm/**`, the `service_token.py` files, `src/server/services/FillerClient.ts`,
  `src/app/p/[project]/qualify/new/actions.ts`, `src/app/api/qualifications/[id]/fill/route.ts`,
  `src/server/access/{projectAccess,qualificationAccess}.ts`, `component-actions.ts`, `ontology-actions.ts`. Nor
  the frozen files: `src/data/keyQuestions.ts`, `src/data/prefillFields.json`, `src/data/annexPoints.json`,
  `src/data/examples/mcas.ts`, `src/middleware.ts`, `scripts/*.mjs`, `services/ontology/{build.py,view.py}`,
  `services/ontology/examples/*`, `airo.ttl`/`vair.ttl`.
- Do not fix the three pre-existing ontology failures.
- Python venvs only in `$P`; never create one in the repository; prefill uses its own `.venv`. Always
  `PYTHONPYCACHEPREFIX=$P/pyc` and `-p no:cacheprovider`; agents from `$P/agents-cwd`. Never `sudo`, `chown` or
  delete root-owned files.
- No new dependency, no model or LLM call, no new markdown file (only the README and DEPLOY.md edits listed).
- No em dashes in any prose or UI text written (user rule).
