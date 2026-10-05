# Form assembly: specification

Date: 2026-09-24. App: `apps/qualification` on branch `feat/unified-modules`.
Status: specification only. No code, tests or migrations exist for it yet.

Readers: the agents who will write tests, a plan and code from this file alone. Every rule has an
id (R1, R2, ...) that a test cites. Each rule says which test file and layer covers it. Items marked
**ASSUMED** are decisions this spec had to make without the product owner; they are collected in
section 12.

---

## 1. Context and current state

### 1.1 What exists

| Concern | Where | What it does today |
|---|---|---|
| The 14 Annex IV questions | `src/data/keyQuestions.ts` (`KEY_QUESTIONS`, `KeyQuestion`, `keyQuestionField`, `keyQuestionIdSet`) | Fixed TS constant. Each question has `id` (`1a`, `1de`, ... `2h`), `group` (`annex-1` / `annex-2`), `groupLabel`, `citation` (`Annex IV(1)(a)`), `text`, `optional?`. Form field name is `q:<group>:<id>`. |
| Metadata labels and citations | `src/data/formFields.ts` (`METADATA_FIELDS`, `MetadataFieldId`) | 11 ids: `systemName`, `systemVersion`, `company`, `description`, `targetUseCase`, `targetUsers`, `intendedDeployers`, `targetSystemTags`, `sectorTags`, `marketFormTags`, `localityTags`. |
| Risk block | `src/data/riskFields.ts` (`RISK_BLOCK`, `RISK_FIELDS`) | "Question 15": one row per risk, fields `risk:<i>:<field>`. |
| Form parsing and validation | `src/server/forms/QualificationFormParser.ts` | zod `metadataSchema` requires all 7 text metadata fields; at least one of each of the 4 pickers; every non-optional `KEY_QUESTIONS` answer; at least one risk row. Answers outside `keyQuestionIdSet()` are dropped. |
| Persistence | `src/server/repositories/QualificationRepository.ts`, `prisma/schema.prisma` | `Qualification` (columns `description`, `targetUseCase`, `targetUsers` are `NOT NULL`; `intendedDeployers` nullable; tag arrays default `[]`), `QualificationAnswer` (`toolId` = group, `questionId` = id, `@@unique([qualificationId, questionId])`, DB index name `QualificationAnswer_qualificationId_questionId_key`), `QualificationRisk`, `KnowledgeGraph`, `CardComponent`. Tables live in Postgres schema `qualification`. |
| Save flow | `src/server/services/QualificationService.ts` `createFromForm`, `src/app/p/[project]/qualify/new/actions.ts` `submitQualification` | Parse, ask the platform for the next card version (`PlatformClient.createVersion`), store the card, start the filler. |
| Card versioning | `src/domain/cardVersions.ts` (`nextCard`, `cardAsFormStart`, `cardStanding`), migrations `20260923210000_card_versions_point_at_core_system` and `20260924120000_a_card_is_of_a_version_of_its_project` | One card per `core.system` row; only the latest version's card changes. Triggers `qualification_only_latest_changes` (BEFORE UPDATE on `qualification`) and `qualification_answer_only_latest_changes` (BEFORE INSERT OR UPDATE on `qualification_answer`) refuse changes to older cards. |
| The form page | `src/app/p/[project]/system/edit/page.tsx` renders `src/app/p/[project]/qualify/new/QualifyForm.tsx` with `KEY_QUESTIONS`; `qualify/new/page.tsx` only redirects | Metadata section, 4 pickers, 14 questions, `RiskRows`, document upload (`DocumentUpload`, `useDocumentPrefill`). |
| The answered form | `src/app/p/[project]/qualify/[id]/AnsweredForm.tsx` | Walks `KEY_QUESTIONS`, shows "left blank" for unanswered; always shows every metadata field and the risk section. |
| Export to the ontology service | `src/server/services/QualificationExporter.ts` (`toExport`, `QualificationExport`), `scripts/export_qualification.mjs` (CLI mirror) | Answers exported as `{toolId, questionId, answer}` sorted by `questionId`. |
| Graph build | `services/ontology/app.py` (`/build`, pydantic `Qualification` requires `description`, `targetUseCase`, `targetUsers`), `services/ontology/airo_min/build.py` (`build_graph`, `_annex_citation`, `_add_risk`), `airo_min/view.py` (`build_view`, `_answers`), `airo_min/mapping.py` (`FORM_MAPPING`) | Structured fields become AIRO nodes. Every answer becomes a `qual:answer` blank node with `qual:citation`, `qual:questionId` (`<toolId>:<questionId>`), `qual:text`. `hasPurpose`, `isProvidedBy`, `hasAIUser` nodes are always created. A risk row with `affected = user` takes the `hasAIUser` node with `next(iter(...))`, which raises when there is none. |
| Prose-derived nodes | `services/agents/fill/workflow.py` `answer_for(qualification, citation)` | Finds the 2(a) and 2(c) answers by suffix match on `toolId:questionId`. |
| AI card | `src/app/p/[project]/qualify/[id]/VerticalCard.tsx`, `src/domain/SystemCard.ts` (`systemCardPayload`, `aiCardExport`), `src/app/api/qualifications/[id]/ai-card.json/route.ts`, `ai-card.pdf`, `services/system_card_renderer` (`models.py` `SystemCard`, `Ontology`; `templates/system_card.html.j2`) | View model computed in Python; PDF template renders `card.ontology.rows` and `chains`. |
| Prefill | `services/prefill` (`app.py` `/prefill`, `prefill/fields.py` `proposals_from_text`, `annex_sections`, `metadata_from_text`, `prefill/documents.py` `read_document` for pdf/docx/txt/md, `prefill/merge.py`), shared `src/data/prefillFields.json`, TS `src/server/services/PrefillClient.ts`, `src/lib/prefillFlow.ts`, `src/lib/prefillChoice.ts` | Deterministic: Annex headings (`1(a)`, `Annex IV(2)(c)`) and metadata labels. No model. |
| Access | `src/middleware.ts`, `src/server/access/projectAccess.ts` (`fetchAccess` returns `{role, admin, may_write}`), `qualificationAccess.ts` | Pages under `/p/:project` only. GET needs a role in the project; POST (every server action) needs `may_write`. `admin` is the platform realm admin. |

### 1.2 What the code has no concept of

There is **no organisation** anywhere: not in `prisma/schema.prisma`, not in `core` (`init/platform-db.sql` has `core.project`, `core.system`, `core.project_member`), not in the platform API (`platform/platform_service/app.py`). The unit of ownership is the project; the only cross-project authority is the Keycloak realm role `admin`, surfaced to this app as `Access.admin`. One install has one Postgres database with one `qualification` schema.

**ASSUMED (A1):** the "organisation" is the install. The form library is one set of rows in the `qualification` schema, visible to every project on the install. No `org_id` column is added. If a later install hosts several organisations, an `org` column is added then (out of scope, section 11).

### 1.3 Frozen things this feature must not change

Carried from `docs/superpowers/pipeline-2026-09-23/RULES.md`: the vendored `airo.ttl` / `vair.ttl`, `src/data/airo_vocab.json`, and the `knowledge_graph` and `qualification_risk` tables (no new column, index, trigger or FK). **ASSUMED (A2):** that freeze still holds. This spec needs no change to either table.

---

## 2. Decisions on where logic lives

The product owner reads Python, not TS. Chosen split:

| Logic | Where | Why |
|---|---|---|
| Import parsing (.csv, .md, .docx to questions) | Python, `services/prefill/prefill/form_import.py`, new endpoint `POST /forms/import` on the prefill service | Prefill already reads .docx/.md with `python-docx` and has the text decoding (`_decode`); the rules are text rules and belong beside the Annex heading rules. |
| Prefill matching for custom forms | Python, `services/prefill/prefill/fields.py` (extended) | It already holds the Annex and label matching. |
| Annex IV mapping into the graph, coverage, "Additional documentation" | Python, `services/ontology/airo_min/build.py` (extended) and new `services/ontology/airo_min/coverage.py`, called from `build_view` | The view model is already computed there; the card, JSON export and PDF all read that one view, so they cannot disagree. |
| Form parsing and validation (`QualificationFormParser`) | TS, stays in `src/server/forms/QualificationFormParser.ts` as a pure class that takes the resolved form as an argument | It runs inside the Next server action before any write; moving it to Python would add a network hop to every save. It stays pure and unit-tested. |
| Builder draft validation, builder state, library search, overlap hints | TS, small pure modules under `src/domain/forms/` | They run in the browser on every click (overlap, search, reorder) or directly before a Prisma write (draft validation). Each is a pure function with no React, no Prisma, no network. |
| React components | Thin. They render state from the pure modules and call server actions. | |

The Annex IV points are a shared data file, `src/data/annexPoints.json`, read by TS directly and by Python through a three-place loader identical in shape to `services/ontology/airo_min/pickers.py` (env var `ANNEX_POINTS_PATH`, then the repo layout, then a copy beside the package). The ontology image needs one extra `COPY src/data/annexPoints.json ./airo_min/annex_points.json` line in `services/ontology/Dockerfile` (a file edit, not running docker). The prefill service derives the same points from `prefillFields.json`, which it already loads, so its image needs no change.

`src/data/annexPoints.json` content (exact, 14 entries, in this order):

```json
{
  "_comment": "The 14 Annex IV points the default form asks about. A custom question may be tagged with one of these ids. Shared with services/ontology; test/unit/annexPoints.test.ts checks it against KEY_QUESTIONS.",
  "points": [
    {"id": "1a",  "citation": "Annex IV(1)(a)"},
    {"id": "1b",  "citation": "Annex IV(1)(b)"},
    {"id": "1c",  "citation": "Annex IV(1)(c)"},
    {"id": "1de", "citation": "Annex IV(1)(d)-(e)"},
    {"id": "1f",  "citation": "Annex IV(1)(f)"},
    {"id": "1gh", "citation": "Annex IV(1)(g)-(h)"},
    {"id": "2a",  "citation": "Annex IV(2)(a)"},
    {"id": "2b",  "citation": "Annex IV(2)(b)"},
    {"id": "2c",  "citation": "Annex IV(2)(c)"},
    {"id": "2d",  "citation": "Annex IV(2)(d)"},
    {"id": "2e",  "citation": "Annex IV(2)(e)"},
    {"id": "2f",  "citation": "Annex IV(2)(f)"},
    {"id": "2g",  "citation": "Annex IV(2)(g)"},
    {"id": "2h",  "citation": "Annex IV(2)(h)"}
  ]
}
```

An "Annex point" in this spec always means one of these 14 ids. The coverage denominator is always 14.

---

## 3. Vocabulary

- **Form**: a named, owned-by-the-install entry in the library. Has versions.
- **Form version**: an immutable, ordered list of question snapshots plus a set of included blocks.
- **Question identity** (`FormQuestion`): a stable id plus a namespaced key `(scope, localId)`; owned by exactly one form (its *owner form*). Identity never changes; its wording lives in each version's snapshot.
- **Snapshot** (`FormVersionQuestion`): the wording, citation, required flag, Annex tag and group label of one question as it appears in one version.
- **Blocks**: the removable non-question parts of the form. Block ids (exact strings): `description`, `targetUseCase`, `targetUsers`, `intendedDeployers`, `targetSystemTags`, `sectorTags`, `marketFormTags`, `localityTags`, `risks`. Exported as `FORM_BLOCKS` from `src/domain/forms/blocks.ts`.
- **Identity block**: `systemName`, `systemVersion`, `company` (the provider). Always present; not a block; cannot be removed.
- **Builtin form**: the seeded "Annex IV default". Read-only.
- **Listed / unlisted**: listed forms appear in the library and chooser; an unlisted form is what "Use once" creates.
- **Question key**: the string `<scope>:<localId>`, e.g. `annex-1:1a`, `f-clx9abc:q3`. The form field name is `q:<scope>:<localId>` (the existing `q:<group>:<id>` convention, unchanged).

---

## 4. Data model

### 4.1 Prisma models (added to `prisma/schema.prisma`)

```prisma
/// A form in the install's library. The install is the organisation (spec A1).
model Form {
  id          String         @id @default(cuid())
  /// Fixed at creation: cards name their "Additional documentation" sections after it.
  name        String
  description String         @default("")
  /// "builtin" (the seeded Annex IV default), "builder" or "import".
  origin      String
  /// false for a form made by "Use once": never in the library or the chooser.
  listed      Boolean        @default(true)
  /// The install's default form. Exactly one listed form has it (partial unique index).
  isDefault   Boolean        @default(false) @map("is_default")
  createdAt   DateTime       @default(now()) @map("created_at") @db.Timestamptz(3)
  versions    FormVersion[]
  questions   FormQuestion[]

  @@map("form")
}

/// One immutable version of a form. Append-only: never updated, never deleted.
model FormVersion {
  id             String                @id @default(cuid())
  formId         String                @map("form_id")
  /// 1, 2, ... per form.
  number         Int
  /// Included blocks, a subset of FORM_BLOCKS. The identity block is implicit.
  blocks         String[]
  createdAt      DateTime              @default(now()) @map("created_at") @db.Timestamptz(3)
  form           Form                  @relation(fields: [formId], references: [id], onDelete: Restrict)
  questions      FormVersionQuestion[]
  qualifications Qualification[]

  @@unique([formId, number])
  @@map("form_version")
}

/// A question's identity: its namespaced key and its owner form. The wording is per version.
model FormQuestion {
  id           String                @id @default(cuid())
  ownerFormId  String                @map("owner_form_id")
  /// "annex-1" / "annex-2" for the seeded questions, "f-<ownerFormId>" for every other.
  scope        String
  /// "1a" ... for the seeded questions, "q1", "q2", ... for every other, per owner form.
  localId      String                @map("local_id")
  /// Set when "Edit" on another form's question made this copy.
  copiedFromId String?               @map("copied_from_id")
  createdAt    DateTime              @default(now()) @map("created_at") @db.Timestamptz(3)
  ownerForm    Form                  @relation(fields: [ownerFormId], references: [id], onDelete: Restrict)
  copiedFrom   FormQuestion?         @relation("QuestionCopies", fields: [copiedFromId], references: [id], onDelete: Restrict)
  copies       FormQuestion[]        @relation("QuestionCopies")
  inVersions   FormVersionQuestion[]

  @@unique([scope, localId])
  @@map("form_question")
}

/// A question as one version shows it. Immutable.
model FormVersionQuestion {
  formVersionId String       @map("form_version_id")
  questionId    String       @map("question_id")
  position      Int
  text          String
  /// Free text for any source, e.g. "Acme AI Policy §4.2". May be "".
  citation      String       @default("")
  required      Boolean
  /// One of the 14 ids in src/data/annexPoints.json, or null (untagged).
  annexPoint    String?      @map("annex_point")
  /// The seeded questions keep "About the system" / "How the system was built"; others null.
  groupLabel    String?      @map("group_label")
  formVersion   FormVersion  @relation(fields: [formVersionId], references: [id], onDelete: Restrict)
  question      FormQuestion @relation(fields: [questionId], references: [id], onDelete: Restrict)

  @@id([formVersionId, questionId])
  @@unique([formVersionId, position])
  @@map("form_version_question")
}
```

Changes to existing models:

```prisma
model Qualification {
  // ... every existing field unchanged ...
  /// The form version this card was filled with. NULL means the seeded
  /// "Annex IV default" version 1: every card saved before forms existed.
  formVersionId String?      @map("form_version_id")
  formVersion   FormVersion? @relation(fields: [formVersionId], references: [id], onDelete: Restrict)
}

model QualificationAnswer {
  // toolId now means the question's scope (it always held "annex-1"/"annex-2", which
  // are the seeded questions' scopes); questionId is the local id within that scope.
  // Field names are kept so existing rows, seeds and exports need no rewrite.
  @@unique([qualificationId, toolId, questionId])   // replaces @@unique([qualificationId, questionId])
  @@index([qualificationId, toolId])               // unchanged
}
```

`QualificationRisk`, `KnowledgeGraph`, `CardComponent`: unchanged.

### 4.2 Constraints (in the migration)

- `form`: `CHECK (origin IN ('builtin','builder','import'))`; `CREATE UNIQUE INDEX form_one_default ON qualification.form ((true)) WHERE is_default`; `CREATE UNIQUE INDEX form_listed_name_key ON qualification.form (lower(name)) WHERE listed`; `CHECK (NOT is_default OR listed)`; `CHECK (length(btrim(name)) BETWEEN 1 AND 120)`.
- `form_version`: `CHECK (number >= 1)`; `CHECK (blocks <@ ARRAY['description','targetUseCase','targetUsers','intendedDeployers','targetSystemTags','sectorTags','marketFormTags','localityTags','risks']::text[])`.
- `form_question`: `CHECK (scope ~ '^[a-z0-9-]+$')`, `CHECK (local_id ~ '^[a-z0-9]+$')`.
- `form_version_question`: `CHECK (position >= 0)`; `CHECK (length(btrim(text)) BETWEEN 1 AND 2000)`; `CHECK (length(citation) <= 200)`; `CHECK (annex_point IS NULL OR annex_point IN ('1a','1b','1c','1de','1f','1gh','2a','2b','2c','2d','2e','2f','2g','2h'))`.
- Immutability triggers (PL/pgSQL, in schema `qualification`):
  - `form_version_is_append_only`: BEFORE UPDATE OR DELETE on `form_version` raises `'form version % is immutable: save a new version instead'`.
  - `form_version_question_is_append_only`: BEFORE UPDATE OR DELETE on `form_version_question` raises the same message with the version id.
  - `form_question_identity_is_fixed`: BEFORE UPDATE on `form_question` raises when `scope`, `local_id`, `owner_form_id` or `copied_from_id` changes; BEFORE DELETE raises always.
  - `form_name_is_fixed`: BEFORE UPDATE on `form` raises when `name` or `origin` changes, or when `listed` changes. Only `is_default` and `description` may change.
  - `form_builtin_is_fixed`: BEFORE INSERT on `form_version` raises when the parent form's `origin = 'builtin'` and a version already exists (the builtin form never gets a second version from the app).
  - No DELETE on `form` is offered by the app; `ON DELETE RESTRICT` on every FK means a used form cannot be removed even by hand.
- `qualification.form_version_id` FK to `form_version(id)` `ON DELETE RESTRICT`; index `qualification_form_version_id_idx`.
- No FK from `qualification_answer (toolId, questionId)` to `form_question (scope, local_id)`: adding one would validate every historic row and some installs may hold hand-made rows; integrity is kept by the parser (R13). **ASSUMED (A3).**

### 4.3 Migration `prisma/migrations/20260925090000_forms_are_data/migration.sql`

Order, in one migration:

1. Create the four tables, their indexes, checks and FKs (snake_case names, per `20260922110000_one_naming_convention`).
2. Seed the builtin form with fixed ids:
   - `form`: `id='annex-iv-default'`, `name='Annex IV default'`, `origin='builtin'`, `listed=true`, `is_default=true`, `description='EU AI Act Annex IV points 1 and 2, as 14 questions.'`
   - `form_version`: `id='annex-iv-default-v1'`, `form_id='annex-iv-default'`, `number=1`, `blocks` = all 9 block ids in `FORM_BLOCKS` order.
   - 14 `form_question` rows: `id='annex-iv-<id>'` (e.g. `annex-iv-1a`, `annex-iv-1de`), `owner_form_id='annex-iv-default'`, `scope=<group>` (`annex-1` or `annex-2`), `local_id=<id>`.
   - 14 `form_version_question` rows for `annex-iv-default-v1`, `position` 0..13 in `KEY_QUESTIONS` order, `text` and `citation` verbatim from `KEY_QUESTIONS`, `required = NOT optional`, `annex_point = <id>`, `group_label = <groupLabel>`.
3. `ALTER TABLE qualification.qualification ADD COLUMN form_version_id text NULL REFERENCES qualification.form_version(id) ON DELETE RESTRICT;` plus the index. No default, no backfill: existing rows keep NULL (see 4.4).
4. `DROP INDEX qualification."QualificationAnswer_qualificationId_questionId_key";` then `CREATE UNIQUE INDEX qualification_answer_qualification_id_tool_id_question_id_key ON qualification.qualification_answer ("qualificationId", "toolId", "questionId");`. Every existing row satisfies the new, weaker-or-equal constraint, so it cannot fail.
5. Create the triggers of 4.2 last (so the seed in step 2 is not blocked by `form_builtin_is_fixed`).

Nothing in this migration updates or deletes an existing row of `qualification`, `qualification_answer`, `qualification_risk`, `knowledge_graph` or `card_component`. That matters: `qualification_only_latest_changes` and `answer_only_latest_changes` would refuse updates to older cards, and history must stay byte-identical.

### 4.4 Backfill and the meaning of NULL

- No row is backfilled. `qualification.form_version_id IS NULL` means "filled with `annex-iv-default-v1`", resolved in code by `resolveFormVersionId(id: string | null): string` in `src/domain/forms/legacy.ts`, which returns `'annex-iv-default-v1'` for null and the id otherwise. Every reader goes through it (R6).
- Existing answers (`toolId` `annex-1`/`annex-2`, `questionId` `1a`...) are exactly the seeded questions' `(scope, localId)`, so they resolve with no rewrite.
- New cards always store a non-null `form_version_id`, including cards filled with the default form.

---

## 5. Server modules and API

### 5.1 New TS modules

| File | Exports | Pure? |
|---|---|---|
| `src/data/annexPoints.json` | the 14 points | data |
| `src/domain/forms/annexPoints.ts` | `ANNEX_POINTS: {id, citation}[]`, `AnnexPointId` (union of the 14), `isAnnexPoint(s)`, `annexCitation(id)` | yes |
| `src/domain/forms/blocks.ts` | `FORM_BLOCKS` (9 ids, order of 3), `FormBlock`, `IDENTITY_FIELDS = ["systemName","systemVersion","company"]` | yes |
| `src/domain/forms/types.ts` | `ResolvedQuestion`, `ResolvedFormVersion` (below) | types |
| `src/domain/forms/legacy.ts` | `DEFAULT_FORM_ID = 'annex-iv-default'`, `DEFAULT_VERSION_ID = 'annex-iv-default-v1'`, `resolveFormVersionId`, `annexDefaultVersion(): ResolvedFormVersion` built from `KEY_QUESTIONS` (used by tests and as the in-memory twin of the seed) | yes |
| `src/domain/forms/formDraft.ts` | `FormDraft` type, `parseFormDraft(input: unknown): {ok:true, value} \| {ok:false, error}` (zod), `sameContent(draft, version): boolean` | yes |
| `src/domain/forms/builderState.ts` | `BuilderState`, `builderReducer(state, action)`, `initialBuilderState(...)` | yes |
| `src/domain/forms/library.ts` | `filterLibrary(groups, query)`, `overlapHints(selected, candidates)` | yes |
| `src/server/repositories/FormRepository.ts` | `FormRepository` class (Prisma), injectable like `QualificationRepository` | no |
| `src/server/services/FormService.ts` | `FormService`: `library()`, `chooserOptions(project)`, `resolve(versionId \| null)`, `latestVersion(formId)`, `saveDraft(draft, {formId?, listed})`, `setDefault(project, formId)` | no, deps injected |
| `src/server/services/FormImportClient.ts` | `FormImportClient.read(file): Promise<{ok:true, questions, warnings, found} \| {ok:false, error}>`; never throws (same contract as `PrefillClient`) | no, fetch injected |

```ts
type ResolvedQuestion = {
  questionId: string;          // FormQuestion.id
  scope: string;               // "annex-1" | "f-<id>"
  localId: string;             // "1a" | "q3"
  key: string;                 // `${scope}:${localId}`
  field: string;               // `q:${scope}:${localId}`
  text: string;
  citation: string;            // free text, may be ""
  required: boolean;
  annexPoint: AnnexPointId | null;
  groupLabel: string | null;
  ownerFormId: string;
  ownerFormName: string;
  ownerBuiltin: boolean;
};
type ResolvedFormVersion = {
  formId: string; formName: string; listed: boolean; builtin: boolean;
  versionId: string; versionNumber: number;
  blocks: FormBlock[];         // in FORM_BLOCKS order
  questions: ResolvedQuestion[]; // in position order
};
```

`FormDraft` (the builder's save payload, validated server side):

```ts
type FormDraft = {
  name: string;                 // 1..120 after trim; ignored when saving a new version of an existing form
  description?: string;         // 0..500
  blocks: FormBlock[];          // any subset, duplicates rejected
  questions: Array<
    | { kind: "pick"; questionId: string }                          // another form's question, by reference
    | { kind: "own"; questionId?: string; text: string; citation: string; required: boolean; annexPoint: AnnexPointId | null }
    | { kind: "copy"; fromQuestionId: string; text: string; citation: string; required: boolean; annexPoint: AnnexPointId | null }
  >;                            // 0..200 entries, order = position
};
```

### 5.2 Changed TS modules

- `QualificationFormParser.parse(formData, form: ResolvedFormVersion)`: new required second argument (R9 to R13).
- `QualificationService.createFromForm(project, formData)`: reads the hidden field `formVersionId`, resolves it through `FormService.resolve` (missing field means `DEFAULT_VERSION_ID`), passes it to the parser, stores `formVersionId`. `startingPoint(project)` additionally returns `fromFormVersionId: string` (the previous card's resolved version id) or null.
- `QualificationRepository`: `CreateQualificationInput.formVersionId: string`; `cardSummary` selects `formVersionId`.
- `cardVersions.ts`: `CardContent` gains `formVersionId: string | null`; `cardAsFormStart` unchanged in shape (answers keyed by field already).
- `QualificationExporter.toExport(q, form: ResolvedFormVersion)` (R29).
- `OntologyService` gets a `forms: { resolve(id: string | null): Promise<ResolvedFormVersion> }` dependency and passes the resolved form to `toExport` in `build` and `patchNode`.
- `src/app/api/qualifications/[id]/extracted/route.ts` GET: `toExport(q, form)`.
- `PrefillClient.read(file, mode, current, currentRisks, formSpec?)` where `formSpec = {fields: string[], questions: {field, text, citation, annexPoint}[]}` (R37 to R39).
- `src/domain/OntologyView.ts`: `OntologyView` gains optional `form?: {name: string; version: number}`, `coverage?: Coverage`, `additionalDocumentation?: AdditionalSection[]` (shapes in R33, R34).

### 5.3 Pages and server actions (all under `/p/[project]`, so `src/middleware.ts` applies)

| Route | Kind | Behaviour |
|---|---|---|
| `/p/[project]/system/edit` | page (changed) | No `form`/`formVersion`/`example` param: the chooser (R7). `?form=<formId>`: the form's latest version. `?formVersion=<versionId>`: that version (listed or not). `?example=mcas`: the default version, as today. |
| `/p/[project]/forms` | page (new) | The library: listed forms, "Default" badge, "Edit" (non-builtin), "Start from", "Set as default" (admins only). |
| `/p/[project]/forms/new` | page (new) | Builder, empty right column. `?from=<formId>` pre-fills from that form. |
| `/p/[project]/forms/[formId]/edit` | page (new) | Builder on the form's latest version; saving makes the next version. 404 for a builtin or unlisted form. |
| `/p/[project]/forms/import` | page (new) | Upload, preview, confirm, then the builder in place. |
| `saveForm(project, draftJson, formId?)` | server action, `src/app/p/[project]/forms/actions.ts` | Validates with `parseFormDraft`; `FormService.saveDraft`; redirects to `/p/[project]/system/edit?form=<formId>`. |
| `useFormOnce(project, draftJson)` | server action, same file | Saves an unlisted form (name `"Custom questions"`, origin `builder` or `import`) with version 1; redirects to `/p/[project]/system/edit?formVersion=<versionId>`. |
| `setDefaultForm(project, formId)` | server action, same file | Requires `callerAccess(project).admin === true`; otherwise returns `{error: "Only an administrator can change the default form."}`. |
| `readFormFile(formData)` | server action, `src/app/p/[project]/forms/import/actions.ts` | Carries the file to `FormImportClient`. Stores nothing. |

Prefill service, new endpoint:

```
POST /forms/import
  file   the form file: .csv, .md or .docx
-> 200 { "format": "csv"|"md"|"docx", "found": N, "questions": [ {"text", "citation", "required"} ], "warnings": [ "..." ] }
-> 413 larger than PREFILL_MAX_BYTES
-> 422 { "detail": "..." } unreadable, wrong extension, or more than 200 questions
```

Prefill service, changed endpoint: `POST /prefill` accepts two new optional form fields, `fields` (JSON list of form field names the form has, including `"risks"` when the risk block is in) and `questions` (JSON list of `{field, text, citation, annexPoint}`).

Ontology service, changed request: `BuildRequest.qualification` gains optional `form` (below); `Qualification.description`, `targetUseCase`, `targetUsers` become `str = ""` (optional). Response `view` gains `form`, `coverage`, `additionalDocumentation` when `form` is sent.

```json
"form": {
  "name": "Acme mix", "version": 2,
  "questions": [
    {"key": "annex-2:2a", "text": "...", "citation": "Annex IV(2)(a)", "required": true,
     "annexPoint": "2a", "ownerForm": "Annex IV default", "ownerBuiltin": true},
    {"key": "f-clx9abc:q1", "text": "Who signs off a model release?", "citation": "Acme AI Policy §4.2",
     "required": true, "annexPoint": null, "ownerForm": "Acme AI policy", "ownerBuiltin": false}
  ]
}
```

---

## 6. Requirements and acceptance criteria

Conventions: "the default version" is `annex-iv-default-v1`. "MCAS" is the worked example `src/data/examples/mcas.ts` / `services/ontology/examples/mcas.qualification.json`. Test paths are new files unless marked (existing). DB-gated tests under `test/db/` run only through `test/db/throwaway-db.sh`, as today; everything else needs no network, model, database or running service.

### A. The library

**R1. The seeded default form equals `KEY_QUESTIONS`.**
- Given `src/domain/forms/legacy.ts`, when `annexDefaultVersion()` is called, then it returns 14 questions in `KEY_QUESTIONS` order, each with `scope = group`, `localId = id`, `text` and `citation` verbatim, `required = !optional`, `annexPoint = id`, `groupLabel = groupLabel`, `ownerFormName = "Annex IV default"`, `ownerBuiltin = true`, and `blocks` equal to all 9 `FORM_BLOCKS`.
- Given the migration SQL file, when a test reads it as text, then for every `KEY_QUESTIONS` entry it contains an insert of `form_question` id `annex-iv-<id>` with scope `<group>` and local id `<id>`, and an insert of `form_version_question` with that entry's exact text (SQL-escaped), citation, required flag and position.
- Given a migrated throwaway DB, when `form_version_question` rows of `annex-iv-default-v1` are read in position order, then they equal `annexDefaultVersion().questions` field by field.
- Tests: `test/unit/annexDefaultForm.test.ts` (vitest, first two), `test/db/forms.db.test.ts` (DB-gated, third).

**R2. `annexPoints.json` agrees with the code.**
- Given `src/data/annexPoints.json`, then it has exactly 14 points whose ids equal the `KEY_QUESTIONS` ids in order and whose citations equal the `KEY_QUESTIONS` citations.
- Given `services/ontology/airo_min/annex_points.py` (the Python loader), when `ANNEX_POINTS` is loaded with `ANNEX_POINTS_PATH` unset in the repo layout, then it equals the JSON; and for every id, `annex_citation(id)` equals `_annex_citation({"questionId": id})` from `build.py`.
- Given `ANNEX_POINTS_PATH` pointing at a missing file and no other candidate, then import raises `FileNotFoundError` naming every place looked in.
- Tests: `test/unit/annexPoints.test.ts` (vitest), `services/ontology/tests/test_annex_points.py` (pytest, ontology).

**R3. The library lists every listed form, for every project.**
- Given listed forms "Annex IV default" (builtin, default) and "Acme AI policy" (builder), and an unlisted form "Custom questions", when `FormService.library()` runs with a fake repository, then it returns the two listed forms, the default first, then builtin, then the rest by case-insensitive name; each with its latest version number and question count; the unlisted form is absent.
- Given two projects A and B on the install, when `library()` is called from either, then the result is the same (no project filter).
- Tests: `test/unit/FormService.test.ts` (vitest, fake repository).

**R4. Exactly one org default, set only by an administrator.**
- Given the caller's access `{role: "editor", admin: false, may_write: true}`, when `setDefaultForm(project, "acme")` runs, then it returns `{error: "Only an administrator can change the default form."}` and the repository's `setDefault` is not called.
- Given `{admin: true}`, when it runs for a listed form, then in one transaction the previous default gets `is_default=false` and the new one `true`; `library()` then lists the new default first.
- Given an unlisted form id or an unknown id, then it returns `{error: "That form cannot be the default."}`.
- Given a DB, when two rows are set `is_default = true` directly, then the second update fails on `form_one_default`.
- Tests: `test/unit/formActions.test.ts` (vitest, injected access and service), `test/db/forms.db.test.ts` (DB-gated, last).
- **ASSUMED (A4):** only a platform admin may change the org default.

### B. Namespaced ids and immutable versions

**R5. Question keys are form-scoped and cannot collide.**
- Given a new form F (id `clx9abc`) created with two own questions, when saved, then their `form_question` rows have `scope = "f-clx9abc"` and `local_id` `q1`, `q2`; the next own question added in a later version of F gets `q3` (max existing number + 1 over every question F owns, never reused).
- Given form F and form G each with an own question whose visible text is "1a", when both are used in one mixed version, then their keys differ (`f-<F>:q1`, `f-<G>:q1`) and two `QualificationAnswer` rows `(qid, "f-<F>", "q1")` and `(qid, "f-<G>", "q1")` can both be stored.
- Given a DB, when two answers with the same `(qualificationId, toolId, questionId)` are inserted, then the second fails on `qualification_answer_qualification_id_tool_id_question_id_key`; when two with the same `(qualificationId, questionId)` but different `toolId` are inserted, then both succeed.
- Tests: `test/unit/FormService.test.ts` (key minting with a fake repository), `test/db/forms.db.test.ts` (DB-gated, constraints).

**R6. Versions are immutable; a qualification records and renders its version forever.**
- Given a form version row, when anything issues `UPDATE` or `DELETE` on it or on one of its `form_version_question` rows, then Postgres raises "form version ... is immutable".
- Given form F at version 2 with question `f-F:q1` worded "A", when the builder saves F with q1 reworded "B", then version 3 exists with q1 = "B", version 2 still says "A", and `form_question` for q1 is the same row (same id, scope, localId).
- Given a draft whose content equals F's latest version (`sameContent` true: same blocks, same question ids in the same order with identical snapshots), when saved, then no new version is created and the latest version id is returned.
- Given a card saved with F v2, when F later gets v3, then `/p/[project]/qualify/<card>` renders v2's questions and wording, and the graph export uses v2.
- Given two concurrent saves of F that both compute number 4, then the second fails on `@@unique([formId, number])` and `saveForm` returns `{error: "This form was saved by someone else meanwhile. Reload it and save again."}`.
- Given a builtin form, when a second version is inserted, then `form_builtin_is_fixed` raises; and `/p/[project]/forms/annex-iv-default/edit` answers 404.
- Tests: `test/db/forms.db.test.ts` (DB-gated: triggers, uniqueness), `test/unit/formDraft.test.ts` (`sameContent`), `test/unit/FormService.test.ts` (new version vs none, concurrency error mapping), `test/unit/AnsweredForm.test.tsx` (existing, extended: renders the given version's wording).

**R7. Legacy cards keep working unchanged.**
- Given a `Qualification` row with `formVersionId = null` and answers `(annex-1, 1a)` ... , when `FormService.resolve(null)` runs, then it returns the default version.
- Given that card, when `AnsweredForm` renders it, then its output is identical to the current output for the same data (every metadata field, 14 questions in 2 groups, the risk section).
- Given `services/ontology/examples/mcas.qualification.json` as committed (answers without `annexPoint`, no `form`), when `build_graph` runs, then the Turtle equals the committed `examples/mcas.ttl` / `.jsonld` graph as today (the existing test `test_the_committed_turtle_matches_what_the_builder_produces` still passes, unmodified).
- Given the MCAS export produced by the new `toExport` with the default version (answers now carrying `citation` and `annexPoint`, plus `form`), when `build_graph` runs, then `graph_digest` equals the digest of the legacy export's graph (no triple added, removed or changed for default questions).
- Given the migration, when it runs on a DB holding a non-latest card, then it succeeds and no row of `qualification`, `qualification_answer`, `qualification_risk`, `knowledge_graph` or `card_component` changes (compare a full dump of those tables before and after).
- Tests: `test/unit/FormService.test.ts`, `test/unit/AnsweredForm.test.tsx` (existing, extended), `services/ontology/tests/test_example_mcas.py` (existing, unchanged), `services/ontology/tests/test_form_answers.py` (pytest, ontology: digest equality), `test/db/forms.db.test.ts` (DB-gated: migration touches no history).

### C. Starting a qualification

**R8. The chooser: "Which form?"**
- Given the project has no card yet and the org default is "Acme AI policy", when `/p/[project]/system/edit` is opened with no params, then the page shows one radio group labelled "Which form?" listing every listed form (name, "v<N>", "<Q> questions", "default" tag on the default), with "Acme AI policy" checked, a "Continue" button, and two links: "+ New form" (`/p/[project]/forms/new`) and "Import form" (`/p/[project]/forms/import`).
- Given the latest card was filled with form F (listed), then F is checked instead of the org default, labelled "same as v<N>". Given it was filled with an unlisted (use once) version U, then an extra first option "Same form as v<N>" (value `formVersion=U`) is listed and checked.
- When "Continue" is pressed, then the browser goes to `?form=<formId>` (or `?formVersion=<id>` for the extra option) and the qualification form renders for that version.
- Given `?form=<unknown>` or `?formVersion=<unknown>`, then the chooser renders with the message "That form was not found." and the usual preselection.
- Given `?example=mcas`, then the chooser is skipped and the default version is used, as today.
- The chooser is a thin component `src/app/p/[project]/system/edit/FormChooser.tsx`; which option is preselected is decided by the pure function `preselect(options, {fromFormVersionId, fromFormListed, defaultFormId})` in `src/domain/forms/chooser.ts`.
- Tests: `test/unit/formChooser.test.ts` (vitest, `preselect`), `test/unit/FormChooser.test.tsx` (jsdom: labels, links, button), `test/unit/prefillOnEditPage.test.ts` (existing; must keep passing: the edit page source still renders `<QualifyForm`).

**R9. The form renders from the resolved version.**
- Given a resolved version, when `QualifyForm` renders it (prop `form: ResolvedFormVersion` replaces `keyQuestions`), then: the identity fields always render and are `required`; each block renders only when in `form.blocks` (metadata text fields, the 4 pickers, `RiskRows`); questions render in `position` order, each with its citation chip (`qf-citation`, only when `citation` is non-empty), "where applicable" when not `required`, `required` attribute when required, and name `q:<scope>:<localId>`; a group heading `h3.qf-group` appears whenever the heading value changes, where the heading value is `groupLabel ?? ownerFormName`; a hidden input `formVersionId` carries `form.versionId`.
- Given the next card starts from a previous card (`cardAsFormStart`), when the chosen version differs, then answers are carried over for fields that exist in the chosen version, and dropped for the rest; metadata of excluded blocks is not rendered.
- Given the default version, then the rendered form has the same fields, names, order and headings as today.
- Tests: `test/unit/formPrefill.test.tsx` (existing, extended) or `test/unit/QualifyFormBlocks.test.tsx` (jsdom).

### D. Parsing and validation

**R10. The identity block is always required.**
- Given any resolved version (including one with `blocks = []` and zero questions), when `systemName`, `systemVersion` or `company` is missing or blank, then `parse` throws `FormValidationError` with the current messages ("System name is required", "Version is required", "Company is required").
- Given all three and a version with no blocks and no questions, then `parse` succeeds with `description = ""`, `targetUseCase = ""`, `targetUsers = ""`, `intendedDeployers = null`, all four tag arrays `[]`, `answers = []`, `risks = []`, `formVersionId = form.versionId`.
- Tests: `test/unit/QualificationFormParser.test.ts` (existing, extended).

**R11. Optional metadata text fields.**
- Given `description` (or `targetUseCase`, `targetUsers`, `intendedDeployers`) is in `form.blocks`, then its current rule holds: blank throws the current message.
- Given it is not in `form.blocks`, then any posted value is ignored and the parsed value is `""` (`intendedDeployers`: `null`).
- **ASSUMED (A5):** an included metadata field keeps today's rule (required); only questions have a per-form required flag.
- Tests: `test/unit/QualificationFormParser.test.ts`.

**R12. Optional pickers.**
- Given `targetSystemTags` / `sectorTags` / `marketFormTags` / `localityTags` in `form.blocks`, then today's rules hold (at least one, each valid, current messages).
- Given one is not in `form.blocks`, then posted values for it are ignored (even invalid ones) and it parses as `[]`.
- Tests: `test/unit/QualificationFormParser.test.ts`.

**R13. Optional risk block.**
- Given `risks` in `form.blocks`, then today's `parseRisks` rules hold, including "Add at least one risk."
- Given `risks` not in `form.blocks`, then every `risk:*` field is ignored and `risks = []`, with no error.
- Tests: `test/unit/QualificationFormParser.test.ts`.

**R14. Questions come from the version.**
- Given a version, when a `required` question's field `q:<scope>:<localId>` is missing or blank, then `parse` throws "Please answer all required questions (N missing)." with N the count of such questions.
- Given a non-required question left blank, then no answer is produced for it.
- Given a posted `q:` field whose key is not a question of this version (for example `q:annex-2:2a` when the version has no such question, or a key from another form), then it is ignored.
- Given answers, then each `AnswerInput` is `{toolId: scope, questionId: localId, answer: trimmed}`.
- Given the default version, then behaviour equals today's parser exactly (existing tests that build `fullySubmittable()` from `KEY_QUESTIONS` pass when given `annexDefaultVersion()`).
- Tests: `test/unit/QualificationFormParser.test.ts`.

**R15. Saving stores the version and never trusts the client's form definition.**
- Given a posted `formVersionId` for a version that exists, when `createFromForm` runs, then the parser receives the version loaded server side (question wording, required flags and blocks come from the database, not the request), and the repository receives `formVersionId`.
- Given no `formVersionId` field, then the default version is used. Given an unknown id, then `FormValidationError("The form this was filled with no longer exists. Reload the page.")` and the platform is not called.
- Given `description = ""`, then `PlatformClient.createVersion` is called with `description: null`.
- Tests: `test/unit/cardSubmission.test.ts` (existing, extended) or `test/unit/QualificationService.forms.test.ts` (vitest, fakes for repository, parser, platform, forms).

### E. The builder

**R16. Left column: the library, grouped, searchable, with checkboxes.**
- Given listed forms, when the builder opens, then the left column has one group per listed form (heading = form name), each listing the questions that form owns in its latest version, in position order, each with a checkbox, its text and its citation chip. A question appears under its owner only, never twice.
- Given a search query, when `filterLibrary(groups, query)` runs, then a question matches when the lowercased, whitespace-collapsed query is a substring of its lowercased, whitespace-collapsed text or citation; groups with no match are omitted; an empty query returns every group.
- Given a checkbox is ticked, then the question is appended to the right column as `{kind: "pick"}`; unticking removes it; a question already in the right column shows its box ticked.
- Tests: `test/unit/formLibrary.test.ts` (vitest, `filterLibrary`), `test/unit/builderState.test.ts` (reducer), `test/unit/FormBuilder.test.tsx` (jsdom, rendering and ticking).

**R17. "Start from".**
- Given the "Start from: [form]" selector set to form S, when applied, then the right column is replaced by S's latest version: every question as `{kind: "pick"}` for questions S does not own and `{kind: "pick"}` for those it does (the new form references them; nothing is copied), in S's order, and the blocks set to S's blocks. When the right column was not empty, a confirmation "Replace the N questions in your form?" is shown first.
- Given `/p/[project]/forms/new?from=<S>`, then the builder opens already started from S.
- Tests: `test/unit/builderState.test.ts`, `test/unit/FormBuilder.test.tsx`.

**R18. Right column: reorder with drag or move buttons.**
- Given the right column, then each row has "Move up" and "Move down" buttons with `aria-label="Move <first 40 chars of text> up"` / `"... down"`; the first row's "Move up" and the last row's "Move down" are disabled; pressing one moves the row by one and keeps focus on the moved row's same button.
- Rows are also `draggable`; a drop calls the same reducer action `move(from, to)`. Drag is not required for any test beyond the reducer; no drag-and-drop library is added (**ASSUMED (A6)**).
- Tests: `test/unit/builderState.test.ts` (`move`, bounds), `test/unit/FormBuilder.test.tsx` (buttons, aria labels, disabled state).

**R19. "+ New question".**
- When "+ New question" is pressed, then an inline editor appears with: text (textarea, required, 1..2000 chars), citation (input, 0..200 chars, placeholder "e.g. Acme AI Policy §4.2"), "Required" (checkbox, default checked), "Answers Annex IV point" (select: "None" plus the 14 points by citation, default "None"). Saving the editor appends `{kind: "own", ...}` to the right column.
- Given an own question in the right column, then "Edit" reopens the same editor and changes it in place (same `questionId` if it already had one), and "Remove" removes it.
- Tests: `test/unit/builderState.test.ts`, `test/unit/FormBuilder.test.tsx`.

**R20. Another form's question is never edited in place.**
- Given a `{kind: "pick"}` row, then it shows the owner form's name as a small label and an "Edit" button; pressing "Edit" and saving turns that row into `{kind: "copy", fromQuestionId, ...}` with the edited values, at the same position; the source form is unchanged.
- On save, a copy gets a new `form_question` owned by the form being saved, with `copied_from_id` set; its snapshot keeps the source's `annexPoint` unless changed in the editor.
- Tests: `test/unit/builderState.test.ts`, `test/unit/FormService.test.ts` (copy creates a new identity with `copiedFromId`).

**R21. Blocks: identity locked, everything else toggleable.**
- Given the builder, then above the question list it shows "Always included: System name, Version, Company (provider)" with no control to remove them, and one checkbox per block in `FORM_BLOCKS` with the labels from `METADATA_FIELDS` and `RISK_BLOCK.title`.
- Tests: `test/unit/FormBuilder.test.tsx`.

**R22. Save as a named form, or use once.**
- Given a new form, when "Save form" is pressed with a name, then `saveForm` validates with `parseFormDraft`, creates the `form` (origin `builder`, or `import` when the builder was opened from the import page), version 1 and the questions, and redirects to `/p/[project]/system/edit?form=<id>`.
- Given an existing form, then the button reads "Save as v<N+1>" and the name is shown read-only.
- When "Use once" is pressed, then an unlisted form named "Custom questions" with version 1 is created and the browser goes to `/p/[project]/system/edit?formVersion=<versionId>`.
- `parseFormDraft` rejects, with these exact messages: blank name ("Give the form a name."); name longer than 120 ("A form name is at most 120 characters."); name equal, case-insensitively, to another listed form's ("A form called <name> already exists."); an own or copy question with blank text ("Question <n> has no text."), text over 2000 ("Question <n> is longer than 2000 characters."), citation over 200 ("The citation of question <n> is longer than 200 characters."), an `annexPoint` outside the 14 ("Question <n> names an Annex IV point that does not exist."); a duplicate `questionId` or `fromQuestionId` ("Question <n> is already in the form."); more than 200 questions ("A form has at most 200 questions."); an unknown block id ("<id> is not a part of the form."). `<n>` is the 1-based position.
- `FormService.saveDraft` additionally rejects: a `pick` whose question does not exist ("Question <n> no longer exists."), an `own` whose `questionId` belongs to another form ("Question <n> belongs to another form: edit makes a copy.").
- A `pick` takes its snapshot (text, citation, required, annexPoint, groupLabel) from the most recent `form_version_question` row for that question id in its owner form's versions; the draft's own wording for a pick is ignored.
- A form with zero questions is valid (**ASSUMED (A7)**).
- Tests: `test/unit/formDraft.test.ts`, `test/unit/FormService.test.ts`, `test/unit/formActions.test.ts`.

**R23. Overlap hints.**
- Given selected questions and candidates, when `overlapHints(selected, candidates)` runs, then for every question Q (selected or candidate) with `annexPoint = p`, the result maps Q's id to `p` when at least one *other* selected question has `annexPoint = p`; questions with `annexPoint = null` never get a hint.
- The UI shows the hint as a chip "≈ overlaps <citation of p>" (e.g. "≈ overlaps Annex IV(2)(a)") next to the question in both columns.
- Deterministic: the result depends only on the ids and tags given; no LLM, no text similarity.
- Tests: `test/unit/formLibrary.test.ts`, `test/unit/FormBuilder.test.tsx` (the chip text).

### F. Import

**R24. CSV.**
- Given `acme.csv` (UTF-8, optional BOM):
  ```
  question,citation,required
  Who signs off a model release?,Acme AI Policy §4.2,yes
  "Which datasets are approved, and by whom?",Acme AI Policy §5.1,
  How are incidents reported?,,no
  ```
  when `parse_form_file(raw, "acme.csv")` runs, then it returns 3 questions: `("Who signs off a model release?", "Acme AI Policy §4.2", True)`, `("Which datasets are approved, and by whom?", "Acme AI Policy §5.1", False)`, `("How are incidents reported?", "", False)`, and `format = "csv"`.
- Header detection: the first row is a header when its first cell, trimmed and lowercased, is one of `question`, `questions`, `text`, `question text`. Header columns are matched by name: question (`question`, `questions`, `text`, `question text`), citation (`citation`, `reference`, `source`, `clause`), required (`required`, `mandatory`). Without a header: column 1 is the question, column 2 the citation, column 3 required; extra columns are ignored.
- Delimiter: comma; semicolon when the first line contains `;` and no `,`.
- Required values: `yes`, `y`, `true`, `1`, `required` (any case) are true; blank and everything else false. **ASSUMED (A8):** an imported question is not required unless the file says so.
- Rows whose question cell is blank are skipped silently.
- Encoding: UTF-8, then cp1252 (the existing `_decode` in `prefill/documents.py`).
- Tests: `services/prefill/tests/test_form_import.py` (pytest, prefill).

**R25. Markdown.**
- Given `acme.md`:
  ```
  # Acme AI policy questionnaire

  1. Who signs off a model release? [Acme AI Policy §4.2]
  2. Which datasets are approved?
  - How are incidents reported? [§7]
  See [the policy](https://intranet/policy) for details.

  | Question | Citation |
  |---|---|
  | Who may retrain the model? | Acme AI Policy §6.3 |
  ```
  then it returns 5 questions in order: "Who signs off a model release?" (citation "Acme AI Policy §4.2"), "Which datasets are approved?" (""), "How are incidents reported?" ("§7"), "See [the policy](https://intranet/policy) for details." (""), "Who may retrain the model?" ("Acme AI Policy §6.3"); `required` false for all; and one warning "Skipped 1 heading.".
- Rules: every non-blank line is one question after removing a leading list marker (`-`, `*`, `+`, `1.`, `1)`) and surrounding `**`/`__`. Lines starting with `#` are headings and are skipped (counted in one warning "Skipped N heading(s)."; singular "heading" for 1). Fenced code blocks (between ```` ``` ```` lines), horizontal rules (`---`, `***`) and HTML comments are skipped. A trailing `[...]` that is not immediately followed by `(` is the citation and is removed from the text. A table row `| a | b | c |` is read like a CSV row with the same header rules; the separator row `|---|---|` is skipped.
- Tests: `services/prefill/tests/test_form_import.py`.

**R26. Word (.docx).**
- Given a .docx with paragraphs: "Acme questionnaire" (style Title), "Governance" (style Heading 1), "Who signs off a model release? [Acme AI Policy §4.2]" (Normal), "Which datasets are approved?" (List Paragraph), an empty paragraph, and a table with header row `Question | Citation | Required` and one row `Who may retrain the model? | §6.3 | yes`, then it returns 3 questions: the two paragraphs (citation from the trailing bracket rule) then the table row (required true), and the warning "Skipped 2 headings.".
- Rules: paragraphs whose style name starts with `Heading` or equals `Title` or `Subtitle` are skipped and counted; empty paragraphs skipped; every other paragraph is one question with the markdown bracket rule for citations; tables are read after the paragraphs, row by row, with the CSV header rules.
- Tests: `services/prefill/tests/test_form_import.py` (fixtures built in the test with `python-docx`, as existing prefill tests do).

**R27. Import limits and errors.**
- Whitespace in text and citation is collapsed to single spaces and trimmed.
- Duplicate questions (same text after lowercasing and whitespace collapse) keep the first; warning "Removed N duplicate question(s)."
- A question longer than 2000 characters is skipped with warning "Question on line <L> is longer than 2000 characters and was skipped." (row number for CSV, paragraph number for .docx). A citation longer than 200 is cut to 200 with warning "The citation on line <L> was shortened to 200 characters."
- More than 200 questions: 422 "This file has more than 200 questions; split it into smaller forms."
- Extension not `.csv`, `.md`, `.markdown` or `.docx` (including `.pdf` and `.txt`): 422 "<ext> is not a form format this reads: csv, docx, md". **ASSUMED (A9):** PDF import is out of scope although prefill reads PDFs.
- Empty file: 422 "the file is empty" (existing `DocumentUnreadable` message). A file that yields 0 questions: 200 with `found: 0`.
- Larger than `PREFILL_MAX_BYTES`: 413.
- `found` equals `len(questions)`.
- Tests: `services/prefill/tests/test_form_import.py` (module), `services/prefill/tests/test_app.py` (existing, extended: the endpoint's status codes and body shape).

**R28. Import preview and confirm.**
- Given `readFormFile` returns `{ok: true, found: N, questions, warnings}`, then the page shows "Found N questions in <filename>", the warnings as a list, and one editable row per question (text, citation, "Required" checkbox, "Remove" button). The confirm button reads "Continue with M questions" where M is the number of rows left, and is disabled when M is 0.
- When confirmed, then the builder mounts in place with the rows as `{kind: "own"}` questions (no `questionId`), all 9 blocks included (**ASSUMED (A10)**), name prefilled with the file name without extension, and origin `import` for the save.
- Given `{ok: false, error}` (service down, not configured, 4xx), then the page shows the error and nothing else changes. `FormImportClient` returns `{ok:false, error:"Importing forms is not available on this install."}` when `PREFILL_URL` is unset and `"The form reader could not be reached."` when fetch throws.
- Tests: `test/unit/FormImportClient.test.ts` (vitest, fake fetch), `test/unit/FormImport.test.tsx` (jsdom).

### G. Citations

**R29. Free-text citations use the Annex chip.**
- Given a question with citation "Acme AI Policy §4.2", then `QualifyForm`, `AnsweredForm`, the builder and the card's "Additional documentation" section render it in the same `span.qf-citation` element used for "Annex IV(1)(a)"; a question with an empty citation renders no chip.
- Tests: `test/unit/formPrefill.test.tsx` or `QualifyFormBlocks.test.tsx`, `test/unit/AnsweredForm.test.tsx`, `test/unit/VerticalCard.test.tsx` (existing files, extended).

### H. Annex IV mapping and the graph

**R30. The export carries the form and each answer's tag.**
- Given a card and its resolved version, when `toExport(q, form)` runs, then each answer is `{toolId, questionId, answer, citation, annexPoint}` with `citation` and `annexPoint` from the version's snapshot of that question; answers are ordered by the question's position in the version, and any stored answer whose key is not in the version comes last, sorted by key; and the export has `form` as in 5.3 (`name` = the version's form name, `version` = its number, `questions` in position order).
- Given an excluded text block, then the export carries `""` (or `null` for `intendedDeployers`), as stored.
- Tests: `test/unit/QualificationExporter.test.ts` (existing, extended).

**R31. Tagged answers feed the graph; untagged ones do not.**
- Given an answer with key `annexPoint` present and non-null `p`, when `build_graph` runs, then it adds one `qual:answer` blank node with `qual:citation` = `annex_citation(p)` (never the free-text citation), `qual:questionId` = `"<toolId>:<questionId>"`, `qual:text` = the answer. When `toolId` is not `annex-1` or `annex-2`, it also adds `qual:annexPoint` = `p` and, when the answer's `citation` is non-empty, `qual:sourceCitation` = that citation. For `annex-1`/`annex-2` answers nothing else is added, so their triples equal today's.
- Given an answer with `annexPoint` present and `null`, then no triple mentions it anywhere in the graph (search the Turtle for its text: absent).
- Given an answer without the `annexPoint` key (legacy exports, the CLI script), then today's behaviour is kept: a `qual:answer` node with `_annex_citation(answer)`.
- Given a custom question tagged `2a`, then `view.answers` lists it with citation "Annex IV(2)(a)".
- Tests: `services/ontology/tests/test_form_answers.py`.

**R32. The filler drafts from tagged answers.**
- Given a qualification whose answers carry `annexPoint`, when `answer_for(qualification, "Annex IV(2)(a)")` runs, then it returns the texts of every answer with `annexPoint == "2a"`, in export order, joined by `"\n\n"`; an answer keyed `f-x:q12a` with `annexPoint` null is not returned (the suffix match does not apply when any answer has the `annexPoint` key).
- Given no answer has the `annexPoint` key, then today's suffix rule is used unchanged.
- Given no tagged answer for 2(a), then it returns `""` and the workflow drafts nothing for techniques, as today for a blank answer.
- Tests: `services/agents/tests/test_workflow.py` (existing, extended).

**R33. The graph builds when blocks are absent.**
- Given `description = ""`, then no `qual:description` triple is added. Given `targetUseCase = ""`, then no Purpose node and no `hasPurpose`. Given `targetUsers = ""`, then no AIUser node and no `hasAIUser`. Given `intendedDeployers` null or `""`, then no deployer (as today).
- Given the risk block is present, `targetUsers = ""` and a risk row with `affected = "user"`, then the chain is built without `hasImpactOnStakeholder` (no exception), and `view.chains[i].stakeholder` is null.
- Given the pydantic `Qualification` in `app.py`, then `description`, `targetUseCase`, `targetUsers` default to `""`, so a request without them is accepted (200).
- Given a policy-only qualification (identity only, no blocks, 18 untagged answers), then `/build` returns 200, `problems = []`, a graph with the AISystem and provider nodes only, `view.rows` with only "Provider", `view.chains = []`.
- Tests: `services/ontology/tests/test_absent_blocks.py` (pytest, ontology), `services/ontology/tests/test_app.py` (existing, extended: the request without the three fields).

### I. Coverage and the card

**R34. Coverage is computed in Python.**
- New function `coverage(form: dict, answers: list[dict]) -> dict` in `services/ontology/airo_min/coverage.py`, pure. An answer counts as answered when its text is non-blank after trimming.
- Output shape:
  ```json
  {
    "annex": {"covered": 3, "total": 14,
              "points": [{"id": "1a", "citation": "Annex IV(1)(a)", "covered": true}, "... 14 entries in annexPoints order"]},
    "forms": [{"name": "Acme AI policy", "answered": 18, "total": 18}],
    "summary": "Annex IV coverage: 3 of 14 points; Acme AI policy: 18 of 18 answered."
  }
  ```
- `annex.points[i].covered` is true when some answered question in the form has `annexPoint == id`. `annex.covered` counts them. `total` is always 14.
- `forms` has one entry per owner form that is not builtin, in order of the first question of that owner in the version; `total` = that owner's questions in this version, `answered` = those answered. Builtin-owned questions count only in `annex`.
- `summary` is `"Annex IV coverage: <c> of 14 points"`, then for each `forms` entry `"; <name>: <a> of <t> answered"`, then `"."`.
- Given the MCAS example with the default form, then `summary` is "Annex IV coverage: 14 of 14 points."
- Given a policy-only form with 18 answered Acme questions, 3 of them tagged `1a`, `2a`, `2g`, then `summary` is "Annex IV coverage: 3 of 14 points; Acme AI policy: 18 of 18 answered."
- Given no `form` in the request, then `build_view` returns no `coverage`, `form` or `additionalDocumentation` key (legacy callers unchanged).
- Tests: `services/ontology/tests/test_coverage.py`.

**R35. "Additional documentation".**
- `build_view(graph, form=None, answers=None)` adds `additionalDocumentation`: one section per owner form (builtin included, though the seeded questions are always tagged so it never appears in practice), in first-appearance order, `{"form": <owner name>, "entries": [{"key", "question", "citation", "answer"}]}` listing the answered questions with `annexPoint` null, in version order. Sections with no entries are omitted.
- Given the MCAS default card, then `additionalDocumentation` is `[]`.
- Tests: `services/ontology/tests/test_coverage.py`.

**R36. The card shows coverage and never breaks.**
- `VerticalCard`: when `view.coverage` exists, then its `summary` is shown as the first line (`p.qf-coverage`); after the risk chains, one `h3.qf-group` "Additional documentation: <form>" per section, each entry as question text, citation chip, answer. When `view.chains` is empty, the "Risks" heading is not rendered. When `view.rows` is empty, the "About the system" table is not rendered.
- `AnsweredForm` takes `form: ResolvedFormVersion`: renders the identity fields always, other metadata and pickers only when their block is included, the questions of the version (grouping as in R9, "left blank" for unanswered), the risk section only when `risks` is included.
- PDF: `services/system_card_renderer/models.py` `Ontology` gains `coverage: Optional[Coverage] = None` and `additionalDocumentation: List[AdditionalSection] = []`; the template prints `coverage.summary` under the ontology heading and one section per `additionalDocumentation` entry; `kv` rows for empty `description`, `target_use_case`, `target_users` are omitted.
- Given a policy-only payload (empty description/use case/users, no classification, no rows, no chains, coverage and 18 additional entries), then the PDF template renders without error and contains the summary line and "Acme AI policy".
- Given the existing ontology-only payload (no coverage), then rendering is unchanged.
- Tests: `test/unit/VerticalCard.test.tsx` (existing, extended), `test/unit/AnsweredForm.test.tsx` (existing, extended), `services/system_card_renderer/tests/test_form_coverage.py` (pytest, renderer), `services/system_card_renderer/tests/test_ontology_only_card.py` (existing, unchanged).

**R37. The JSON export carries it.**
- Given a card built with a form, when `aiCardExport` runs, then its `ontology` (the view) contains `form`, `coverage` and `additionalDocumentation`; nothing else in the export changes shape.
- Tests: `test/unit/aiCardExport.test.ts` (existing, extended).

### J. Prefill

**R38. The default form prefills exactly as today.**
- Given `/prefill` without `questions` and `fields`, then the response is identical to today's for every existing test fixture.
- Given the default version's question list sent as `questions` (with `annexPoint` = id) and all fields, then `values`, `filled`, `kept`, `proposed` equal the legacy call's for the same document.
- Tests: `services/prefill/tests/test_app.py`, `services/prefill/tests/test_fields.py` (existing, extended).

**R39. Custom forms match headings, labels and citations.**
- Function `proposals_for_questions(text, questions) -> dict[field, str]` in `services/prefill/prefill/fields.py`. Normalisation `norm(s)`: Unicode NFKC, lowercase, remove leading `#`s, list markers (`-`, `*`, `•`), numbering (`1.`, `1)`, `4.2`), surrounding `**`, whitespace around `§` removed, whitespace collapsed, trailing `?`, `:`, `.` and spaces stripped.
- A line *names* question Q when `norm(line)` equals `norm(Q.text)`, or equals `norm(Q.citation)` (only when that is at least 3 characters), or equals `norm(Q.citation) + " " + norm(Q.text)`. A line `Label: value` names Q when `norm(Label)` does, and then `value` (when non-blank) is the answer's first line.
- The answer is the text after the naming line up to the next line that names any question, any Annex heading (existing `_ANNEX_HEADING`), any markdown heading `^#{1,6}\s`, or the risks heading; joined with single spaces as `annex_sections` does.
- A question with `annexPoint = p` is also filled by the Annex heading for `p` (the existing `ANNEX_FIELDS` table, where both letters of `1de` / `1gh` map to that point).
- First match in document order wins per field. Two questions with the same normalised text both get it.
- Example: document
  ```
  ## Acme AI Policy §4.2
  The head of data science signs off every release.
  ## How are incidents reported?
  Through the risk desk, within 24 hours.
  ```
  with questions `q:f-x:q1` (text "Who signs off a model release?", citation "Acme AI Policy §4.2") and `q:f-x:q2` (text "How are incidents reported?", citation "") proposes `{"q:f-x:q1": "The head of data science signs off every release.", "q:f-x:q2": "Through the risk desk, within 24 hours."}`.
- Tests: `services/prefill/tests/test_custom_form_prefill.py` (pytest, prefill).

**R40. Prefill respects the form's parts.**
- Given `fields` without `description`, then no `description` proposal is returned even if the document has a "Description:" line. Given `fields` without `"risks"`, then `risks` is `null`, `risksKept` false, `risksProposed` 0.
- Given `fields` and `questions` that are not JSON lists, then 422 naming the field (existing `_form_json` pattern).
- TS: `useDocumentPrefill` sends `fields` = identity + included blocks' field names + `"risks"` when included + every question field, and `questions` from the resolved version. `src/lib/prefillChoice.ts` computes the prefillable set from the form instead of the fixed 21 (the existing "exactly the 21 mapped fields" test stays true for the default version).
- Tests: `services/prefill/tests/test_app.py`, `test/unit/PrefillClient.test.ts` (existing, extended), `test/unit/prefillChoice.test.ts` (existing, extended).

### K. No model, access

**R41. Nothing in this feature calls a model.**
- Given the new TS modules (`src/domain/forms/*`, `src/server/services/FormService.ts`, `FormImportClient.ts`, `src/server/repositories/FormRepository.ts`, the new pages and actions), then none imports `FillerClient`, `services/llm`, or any URL env other than `PREFILL_URL` and `PLATFORM_URL` (a source scan test, like `oneSystemEntryPoints.test.ts`).
- Given `services/prefill/prefill/form_import.py` and `coverage.py`, then they import nothing outside the standard library, `docx`, and their own packages; their tests pass with no model env set.
- Tests: `test/unit/formsNoModel.test.ts` (vitest, source scan), the pytest files above.

**R42. Access follows the project door.**
- Given every new page and action lives under `/p/[project]/`, then `src/middleware.ts` (unchanged) gives GET to any project member and POST only with `may_write`: a viewer can open the library and the builder but "Save form", "Use once", and import confirm are refused with 403 by the middleware.
- `setDefaultForm` additionally requires `admin` (R4).
- Tests: `test/unit/projectAccess.test.ts` (existing, unchanged; `decide` already covers POST), `test/unit/formActions.test.ts`.

---

## 7. UI behaviour summary

- **Chooser** (`/system/edit`): heading "Which form?", radio list, "Continue" (primary), "+ New form", "Import form". Nothing else on the page. Keyboard: the radio group is one tab stop; Enter on "Continue" submits.
- **Library** (`/forms`): a table of listed forms: name, "default" tag, "v<N>", "<Q> questions", origin; actions "Start from", "Edit" (not for builtin), "Set as default" (shown only when `callerAccess(project).admin`).
- **Builder**: two columns on wide screens, stacked on narrow (the left column first). Left: search input (label "Search questions"), "Start from" select plus "Apply", groups with checkboxes. Right: form name input (new forms only), "Always included" line, block checkboxes, ordered question rows (position number, text, citation chip, owner label for picks, "≈ overlaps" chip, "Required" or "Optional" tag, "Move up", "Move down", "Edit", "Remove"), "+ New question", and the footer buttons "Save form" / "Save as v<N+1>" and "Use once". Errors from `saveForm` show above the footer in the existing `div.error`.
- **Import**: file input `accept=".csv,.md,.markdown,.docx"`, then the preview of R28, then the builder.
- **Qualification form**: as R9. The header line names the form: "Form: <name> v<N>".
- **Card page**: the coverage line under the header (R36), and the "Answered form" tab per R36.
- All builder state lives in `builderReducer`; `FormBuilder.tsx` holds `useReducer(builderReducer, initial)` and nothing else of substance.

---

## 8. Error cases (collected)

| Case | Where | Result |
|---|---|---|
| Unknown `formVersionId` posted on save | `createFromForm` | `FormValidationError("The form this was filled with no longer exists. Reload the page.")`, platform not called |
| `?form` / `?formVersion` unknown | edit page | chooser with "That form was not found." |
| Builder draft invalid | `saveForm` | the exact messages of R22 |
| Concurrent save | `saveForm` | "This form was saved by someone else meanwhile. Reload it and save again." |
| Non-admin sets default | `setDefaultForm` | "Only an administrator can change the default form." |
| Default set to unlisted/unknown | `setDefaultForm` | "That form cannot be the default." |
| Edit builtin or unlisted form | `/forms/[id]/edit` | 404 |
| Import: bad extension, empty, too many, too big | prefill `/forms/import` | 422 / 422 / 422 / 413, messages in R27 |
| Import service down / not configured | `FormImportClient` | messages in R28, never throws |
| Direct SQL update of a version | DB | trigger exception (R6) |
| Risk row "user" with no users block | ontology build | chain without stakeholder, no exception (R33) |

---

## 9. Backward compatibility

1. **Stored cards.** No existing row changes (R7). `form_version_id IS NULL` resolves to the default version. Their answered form, card view, graph digest and downloads are identical to today's.
2. **Stored answers.** `(toolId, questionId)` already equals the seeded questions' `(scope, localId)`. The unique constraint becomes `(qualificationId, toolId, questionId)`, which every existing row satisfies.
3. **Exported cards** (JSON-LD, Turtle, JSON, PDF already handed over). Default answers keep `qual:questionId "annex-1:1a"` and their citation, so a file exported before and after this feature for the same card describes the same graph (same digest). `ai-card.json` gains `ontology.form`, `ontology.coverage`, `ontology.additionalDocumentation`: additive keys only.
4. **Old ontology-service callers** (`scripts/export_qualification.mjs`, `examples/*.json`, the filler's `/build` call): requests without `form` and answers without `annexPoint` build exactly as today (R7, R31, R34). The CLI script may stay as it is.
5. **The filler** keeps its suffix rule for payloads with no `annexPoint` key (R32).
6. **Prefill** without `questions`/`fields` is unchanged (R38).
7. **Seeds** (`scripts/seed_mcas.mjs`, `seed_examples.mjs`) create cards with `formVersionId` absent (NULL), so they need no change and produce default-form cards.
8. **Existing tests** that must keep passing unmodified: `test_example_mcas.py`, `test_ontology_only_card.py`, `oneSystemEntryPoints.test.ts`, `prefillOnEditPage.test.ts`, `keyQuestions.test.ts`, `projectAccess.test.ts`. Tests that are extended rather than rewritten: `QualificationFormParser.test.ts` (the parser gains its second argument; existing cases pass `annexDefaultVersion()`), `AnsweredForm.test.tsx`, `VerticalCard.test.tsx`, `QualificationExporter.test.ts`, `aiCardExport.test.ts`, `PrefillClient.test.ts`, `prefillChoice.test.ts`, `formPrefill.test.tsx`, `test_workflow.py`, `test_app.py` (ontology and prefill), `cardSubmission.test.ts`.
9. **`KEY_QUESTIONS`** stays as the source of the seed and of `annexDefaultVersion()`; its tests stay. Changing it later means a new migration adding a version 2 of the builtin form through a migration (the app cannot), not an edit of version 1.

---

## 10. Files affected

New:
- `prisma/migrations/20260925090000_forms_are_data/migration.sql`
- `src/data/annexPoints.json`
- `src/domain/forms/annexPoints.ts`, `blocks.ts`, `types.ts`, `legacy.ts`, `formDraft.ts`, `builderState.ts`, `library.ts`, `chooser.ts`
- `src/server/repositories/FormRepository.ts`
- `src/server/services/FormService.ts`, `FormImportClient.ts`
- `src/app/p/[project]/system/edit/FormChooser.tsx`
- `src/app/p/[project]/forms/page.tsx`, `forms/actions.ts`, `forms/FormBuilder.tsx`, `forms/new/page.tsx`, `forms/[formId]/edit/page.tsx`, `forms/import/page.tsx`, `forms/import/actions.ts`, `forms/import/FormImport.tsx`
- `services/ontology/airo_min/annex_points.py`, `services/ontology/airo_min/coverage.py`
- `services/prefill/prefill/form_import.py`
- Tests: `test/unit/annexDefaultForm.test.ts`, `annexPoints.test.ts`, `FormService.test.ts`, `formActions.test.ts`, `formDraft.test.ts`, `builderState.test.ts`, `formLibrary.test.ts`, `formChooser.test.ts`, `FormChooser.test.tsx`, `FormBuilder.test.tsx`, `FormImportClient.test.ts`, `FormImport.test.tsx`, `QualifyFormBlocks.test.tsx`, `QualificationService.forms.test.ts`, `formsNoModel.test.ts`; `test/db/forms.db.test.ts`; `services/ontology/tests/test_annex_points.py`, `test_form_answers.py`, `test_absent_blocks.py`, `test_coverage.py`; `services/prefill/tests/test_form_import.py`, `test_custom_form_prefill.py`; `services/system_card_renderer/tests/test_form_coverage.py`

Changed:
- `prisma/schema.prisma`
- `src/server/forms/QualificationFormParser.ts`
- `src/server/repositories/QualificationRepository.ts`
- `src/server/services/QualificationService.ts`, `QualificationExporter.ts`, `OntologyService.ts`, `PrefillClient.ts`
- `src/domain/cardVersions.ts`, `src/domain/OntologyView.ts`
- `src/lib/prefillChoice.ts`
- `src/app/p/[project]/system/edit/page.tsx`
- `src/app/p/[project]/qualify/new/QualifyForm.tsx`, `actions.ts`, `useDocumentPrefill.ts`, `prefill-actions.ts`
- `src/app/p/[project]/qualify/[id]/page.tsx`, `AnsweredForm.tsx`, `VerticalCard.tsx`
- `src/app/api/qualifications/[id]/extracted/route.ts` (and the `ai-card.json`, `ai-card.pdf`, `system-card.pdf` routes only insofar as they call `ontologyService.build`, whose signature is unchanged)
- `services/ontology/app.py`, `airo_min/build.py`, `airo_min/view.py`, `services/ontology/Dockerfile` (one `COPY` line)
- `services/agents/fill/workflow.py` (`answer_for`)
- `services/prefill/app.py`, `prefill/fields.py`, `services/prefill/README.md`
- `services/system_card_renderer/models.py`, `templates/system_card.html.j2`
- `README.md` (the "14 questions" overview line gains a sentence on forms)

Unchanged on purpose: `src/data/keyQuestions.ts`, `src/data/prefillFields.json`, `src/data/airo_vocab.json`, the vendored ontology files, `qualification_risk`, `knowledge_graph`, `card_component`, `src/middleware.ts`, `scripts/*.mjs`.

---

## 11. Out of scope (v1)

- Several organisations per install, or per-project private forms.
- Renaming, archiving or deleting forms; deleting versions.
- Custom field types (choice lists, dates, numbers), conditional or branching questions, per-question help text.
- Automatic Annex tagging of imported questions, text-similarity overlap, any LLM assistance.
- Reordering or relabelling the fixed blocks; making an included metadata field optional.
- PDF and .txt form import; .xlsx import.
- Exporting a form to a file.
- A migration that moves existing cards to explicit `form_version_id` values.
- Mapping Annex IV points 3 to 9.
- Recording who created a form (the app does not decode the caller's token today).

---

## 12. Assumptions and open questions

Every item below is a decision this spec made. Each can be reversed by editing only the rules it names.

- **ASSUMED (A1)** Organisation = the install. The code has no org concept (no table, column or platform endpoint); one install is one `qualification` schema, and the library is shared by every project on it. Consequence: the names and questions of a form are visible to members of every project on the install. (Sections 1.2, R3.)
- **ASSUMED (A2)** The 2026-09-23 freeze on `knowledge_graph` and `qualification_risk` still holds; this spec does not touch them. (1.3.)
- **ASSUMED (A3)** No FK from answers to `form_question`; integrity through the parser. (4.2.)
- **ASSUMED (A4)** Only a platform admin (`Access.admin`) may change the org default; any project editor may create forms. (R4, R42.)
- **ASSUMED (A5)** An included metadata field keeps today's "required"; only questions carry a per-form required flag. (R11.)
- **ASSUMED (A6)** Reorder is move-up/move-down buttons plus native HTML5 drag; no drag-and-drop dependency. (R18.)
- **ASSUMED (A7)** A form may have zero questions (identity plus blocks, or identity alone). (R22.)
- **ASSUMED (A8)** Imported questions are optional unless the file marks them required. (R24.)
- **ASSUMED (A9)** Import accepts .csv, .md and .docx only, as the requirement lists; PDF is refused although prefill reads PDFs. (R27.)
- **ASSUMED (A10)** An imported form starts with all 9 blocks included; the user unticks what the policy does not need. (R28.)
- **ASSUMED (A11)** Versions are append-only from creation, which is stricter than "immutable once used": every save that changes content makes a new version, and a save with no change makes none. (R6.)
- **ASSUMED (A12)** Form names are fixed at creation, so a card's "Additional documentation: <form>" heading cannot change after the fact. (4.2, R22.)
- **ASSUMED (A13)** The builtin "Annex IV default" is read-only in the app; to change it, start from it and save a new form. (R6.)
- **ASSUMED (A14)** The chooser preselects the previous card's form when there is one, and the org default only for a project's first card, so a next version does not silently switch forms and drop answers. (R8.)
- **ASSUMED (A15)** The library's left column lists each question once, under the form that owns it; "Start from" is how a whole mixed form is reused. Unlisted (use-once) forms' own questions are not offered in the library. (R16.)
- **ASSUMED (A16)** Coverage counts a point or question as covered only when its answer is non-blank; a skipped optional Annex question lowers the Annex count. Denominator is always 14. (R34.)
- **ASSUMED (A17)** Untagged answers are not written to the graph at all (not even as `qual:answer` annotations), and so do not change its digest; they reach the card through the view only. Tagged custom answers get two new annotation properties, `qual:annexPoint` and `qual:sourceCitation`, in the app's own `qual:` namespace, never in `airo:`. (R31.)
- **ASSUMED (A18)** "Use once" forms are named "Custom questions" and listed nowhere. (R22.)
- **Open question (Q1)** Should a project editor be able to set the org default (instead of only a platform admin)? Only R4 changes.
- **Open question (Q2)** Should form visibility across projects be limited (for example to projects whose members created them) before a multi-customer install uses this? Would need an ownership column; out of scope today.
