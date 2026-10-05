# Two-level forms: question sets and questionnaires (specification)

Date: 2026-09-25. App: `apps/qualification`, branch `feat/unified-modules`, uncommitted working tree.
Status: specification only. No test, code or migration for anything below exists yet.

Readers: the agents who write tests, a plan and code from this file alone. It replaces the "form"
object of `../form-assembly-2026-09-24/` (01-spec, 06-spec-addendum, 10-ui-plan) with two objects, as
agreed in `00-brief.md`. Where this file and those conflict, **this file wins**. Requirements are T1,
T2, ...; each names its test file and layer. Gaps this spec had to fill are marked **ASSUMED (Dn)** and
collected in section 10. Section 8 lists every earlier requirement and test this file supersedes.

Paths are relative to `apps/qualification` unless absolute. Layers:

- **unit**: vitest, node environment, no network, database, docker or service.
- **component**: vitest with jsdom (the existing `// @vitest-environment jsdom` pragma), no network.
- **DB**: `test/db/*.db.test.ts`, run only through `test/db/throwaway-db.sh` (it starts a throwaway
  Postgres on a random port, migrates it with `prisma migrate deploy`, runs `npx vitest run test/db`,
  removes the container). Ports 5432 and 5433 are refused, as today.
- **pytest (prefill)** / **pytest (ontology)**: the service's own suite, as today.

---

## 1. Vocabulary

- **Question set**: where questions are written. Has versions. Every question belongs to exactly one set.
  No blocks. The builtin set "Annex IV" (id `annex-iv`) is read-only.
- **Question**: a stable identity `(scope, local_id)` owned by one set. The wording (text, citation,
  required, Annex point, group label) is per set version.
- **Set version**: an immutable ordered list of the set's questions with their wording.
- **Questionnaire**: assembled only by picking questions from set versions, plus choosing blocks. It
  never creates or rewords a question. It is what a card is filled with. The builtin questionnaire
  "Annex IV default" (id `annex-iv-default`) is the fixed default for every project.
- **Questionnaire version**: an immutable ordered list of items, each pinned to one set version and one
  question of it, plus a set of blocks.
- **Pinned**: an item names a specific set version. It never follows the set's latest version by itself.
- **Update available**: a picked question whose set has a newer version in which that question's wording
  differs or the question is absent.
- **Blocks**: the 9 ids of `FORM_BLOCKS` (`src/domain/forms/blocks.ts`, unchanged). The identity block
  (`systemName`, `systemVersion`, `company`) is always included and cannot be removed.
- **Use once**: an unlisted questionnaire (never in lists or the chooser).
- **Retired**: hidden from lists, pickers and the chooser; still resolvable forever.
- **Question key**: `<scope>:<localId>`; form field name `q:<scope>:<localId>` (unchanged).
  Scopes: `annex-1`/`annex-2` (builtin), `f-<old form id>` (questions made before this feature, kept),
  `s-<set id>` (every question made from now on).

---

## 2. Where logic lives

The product owner reads Python. React stays thin: components render state from pure modules and call
server actions. No model is called anywhere in Next.js.

| Logic | Where | Why |
|---|---|---|
| Question-set CSV and Markdown write/read | Python, unchanged: `services/prefill/prefill/form_export.py`, `form_import.py`, endpoints `POST /forms/export`, `POST /forms/import` | Already exact and round-trip tested (06 R50 to R55, G1). The file carries one question list; a set version is one question list. |
| Questionnaire file write/read (JSON, references or self-contained) | Python, new `services/prefill/prefill/questionnaire_file.py`, endpoints `POST /questionnaires/export`, `POST /questionnaires/import` | All file formats in one Python place, one-language round trip (T52), readable by the owner. Stores nothing, reads no database. |
| Resolving a reference file against this install, the "missing" list | TS: data lookups in `QuestionnaireService.resolveReferences`, message building in pure `src/domain/forms/references.ts` | Needs the database, which only this app reads. |
| The split migration | SQL/PL-pgSQL in the migration file | Must run inside the one migration transaction. |
| Coverage and "Additional documentation" | Python, `services/ontology/airo_min/coverage.py` (small change, T46) | Already computed there for card, JSON and PDF. |
| Set draft and questionnaire draft validation, "same content", editor and builder state, update detection, chooser preselection, move notice and reworded flags, use-once name, caller name from token | TS, pure modules under `src/domain/forms/` and `src/server/access/callerName.ts` | They run on every click or right before a Prisma write; each is a pure function with a unit test. |
| Parsing a filled card (`QualificationFormParser`) | TS, unchanged logic, takes the resolved questionnaire version | As 01-spec section 2. |
| Prefill for custom questionnaires | Python, unchanged (`services/prefill/prefill/fields.py`) | The TS side sends the pinned wording (T58). |

If the prefill service is not configured, file export and import of both levels are unavailable (as today,
06 B1).

---

## 3. Data model

### 3.1 Tables (all in schema `qualification`, snake_case, per `20260922110000_one_naming_convention`)

Exact DDL, part of the migration of section 4. Every name is schema-qualified.

```sql
CREATE TABLE qualification.question_set (
  id          text PRIMARY KEY,
  name        text NOT NULL,
  description text NOT NULL DEFAULT '',
  origin      text NOT NULL,
  retired_at  timestamptz(3) NULL,
  created_at  timestamptz(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by  text NOT NULL,
  CONSTRAINT question_set_origin_check CHECK (origin IN ('builtin', 'builder', 'import')),
  CONSTRAINT question_set_name_length CHECK (length(btrim(name)) BETWEEN 1 AND 120),
  CONSTRAINT question_set_description_length CHECK (length(description) <= 500),
  CONSTRAINT question_set_created_by_length CHECK (length(btrim(created_by)) BETWEEN 1 AND 200),
  CONSTRAINT question_set_builtin_is_annex_iv
    CHECK (origin <> 'builtin' OR (id = 'annex-iv' AND retired_at IS NULL))
);
CREATE UNIQUE INDEX question_set_active_name_key
  ON qualification.question_set (lower(name)) WHERE retired_at IS NULL;

CREATE TABLE qualification.question_set_version (
  id         text PRIMARY KEY,
  set_id     text NOT NULL,
  number     integer NOT NULL,
  created_at timestamptz(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by text NOT NULL,
  CONSTRAINT question_set_version_set_id_fkey FOREIGN KEY (set_id)
    REFERENCES qualification.question_set (id) ON DELETE RESTRICT,
  CONSTRAINT question_set_version_number_check CHECK (number >= 1),
  CONSTRAINT question_set_version_created_by_length CHECK (length(btrim(created_by)) BETWEEN 1 AND 200)
);
CREATE UNIQUE INDEX question_set_version_set_id_number_key
  ON qualification.question_set_version (set_id, number);

CREATE TABLE qualification.question (
  id         text PRIMARY KEY,
  set_id     text NOT NULL,
  scope      text NOT NULL,
  local_id   text NOT NULL,
  created_at timestamptz(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT question_set_id_fkey FOREIGN KEY (set_id)
    REFERENCES qualification.question_set (id) ON DELETE RESTRICT,
  CONSTRAINT question_scope_check CHECK (scope ~ '^[a-z0-9-]+$'),
  CONSTRAINT question_local_id_check CHECK (local_id ~ '^[a-z0-9]+$')
);
CREATE UNIQUE INDEX question_scope_local_id_key ON qualification.question (scope, local_id);
CREATE INDEX question_set_id_idx ON qualification.question (set_id);

-- THE wording: one row per question per set version.
CREATE TABLE qualification.question_set_version_item (
  set_version_id text NOT NULL,
  question_id    text NOT NULL,
  position       integer NOT NULL,
  text           text NOT NULL,
  citation       text NOT NULL DEFAULT '',
  required       boolean NOT NULL,
  annex_point    text NULL,
  group_label    text NULL,
  CONSTRAINT question_set_version_item_pkey PRIMARY KEY (set_version_id, question_id),
  CONSTRAINT question_set_version_item_set_version_id_fkey FOREIGN KEY (set_version_id)
    REFERENCES qualification.question_set_version (id) ON DELETE RESTRICT,
  CONSTRAINT question_set_version_item_question_id_fkey FOREIGN KEY (question_id)
    REFERENCES qualification.question (id) ON DELETE RESTRICT,
  CONSTRAINT question_set_version_item_position_check CHECK (position >= 0),
  CONSTRAINT question_set_version_item_text_check CHECK (length(btrim(text)) BETWEEN 1 AND 2000),
  CONSTRAINT question_set_version_item_citation_check CHECK (length(citation) <= 200),
  CONSTRAINT question_set_version_item_annex_point_check CHECK (annex_point IS NULL OR annex_point IN
    ('1a','1b','1c','1de','1f','1gh','2a','2b','2c','2d','2e','2f','2g','2h')),
  CONSTRAINT question_set_version_item_group_label_check
    CHECK (group_label IS NULL OR length(btrim(group_label)) BETWEEN 1 AND 120)
);
CREATE UNIQUE INDEX question_set_version_item_set_version_id_position_key
  ON qualification.question_set_version_item (set_version_id, position);
CREATE INDEX question_set_version_item_question_id_idx
  ON qualification.question_set_version_item (question_id);

CREATE TABLE qualification.questionnaire (
  id          text PRIMARY KEY,
  name        text NOT NULL,
  description text NOT NULL DEFAULT '',
  origin      text NOT NULL,
  listed      boolean NOT NULL DEFAULT true,
  retired_at  timestamptz(3) NULL,
  created_at  timestamptz(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by  text NOT NULL,
  CONSTRAINT questionnaire_origin_check CHECK (origin IN ('builtin', 'builder', 'import')),
  CONSTRAINT questionnaire_name_length CHECK (length(btrim(name)) BETWEEN 1 AND 120),
  CONSTRAINT questionnaire_description_length CHECK (length(description) <= 500),
  CONSTRAINT questionnaire_created_by_length CHECK (length(btrim(created_by)) BETWEEN 1 AND 200),
  CONSTRAINT questionnaire_builtin_is_the_default
    CHECK (origin <> 'builtin' OR (id = 'annex-iv-default' AND listed AND retired_at IS NULL))
);
CREATE UNIQUE INDEX questionnaire_listed_name_key
  ON qualification.questionnaire (lower(name)) WHERE listed AND retired_at IS NULL;

CREATE TABLE qualification.questionnaire_version (
  id               text PRIMARY KEY,
  questionnaire_id text NOT NULL,
  number           integer NOT NULL,
  blocks           text[] NOT NULL,
  created_at       timestamptz(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by       text NOT NULL,
  CONSTRAINT questionnaire_version_questionnaire_id_fkey FOREIGN KEY (questionnaire_id)
    REFERENCES qualification.questionnaire (id) ON DELETE RESTRICT,
  CONSTRAINT questionnaire_version_number_check CHECK (number >= 1),
  CONSTRAINT questionnaire_version_blocks_check CHECK (blocks <@ ARRAY['description','targetUseCase',
    'targetUsers','intendedDeployers','targetSystemTags','sectorTags','marketFormTags',
    'localityTags','risks']::text[]),
  CONSTRAINT questionnaire_version_created_by_length CHECK (length(btrim(created_by)) BETWEEN 1 AND 200)
);
CREATE UNIQUE INDEX questionnaire_version_questionnaire_id_number_key
  ON qualification.questionnaire_version (questionnaire_id, number);

CREATE TABLE qualification.questionnaire_version_item (
  questionnaire_version_id text NOT NULL,
  position                 integer NOT NULL,
  set_version_id           text NOT NULL,
  question_id              text NOT NULL,
  CONSTRAINT questionnaire_version_item_pkey PRIMARY KEY (questionnaire_version_id, question_id),
  CONSTRAINT questionnaire_version_item_questionnaire_version_id_fkey FOREIGN KEY (questionnaire_version_id)
    REFERENCES qualification.questionnaire_version (id) ON DELETE RESTRICT,
  -- the composite key: an item is a question AS one set version words it
  CONSTRAINT questionnaire_version_item_set_item_fkey FOREIGN KEY (set_version_id, question_id)
    REFERENCES qualification.question_set_version_item (set_version_id, question_id) ON DELETE RESTRICT,
  CONSTRAINT questionnaire_version_item_position_check CHECK (position >= 0)
);
CREATE UNIQUE INDEX questionnaire_version_item_questionnaire_version_id_position_key
  ON qualification.questionnaire_version_item (questionnaire_version_id, position);
CREATE INDEX questionnaire_version_item_set_version_id_question_id_idx
  ON qualification.questionnaire_version_item (set_version_id, question_id);
```

`qualification.qualification`: column `form_version_id` is renamed `questionnaire_version_id` (text, NULL),
FK `qualification_questionnaire_version_id_fkey` to `questionnaire_version (id) ON DELETE RESTRICT`, index
`qualification_questionnaire_version_id_idx`. NULL means `annex-iv-default-v1`. `qualification_answer`,
`qualification_risk`, `knowledge_graph`, `card_component`: unchanged (the 2026-09-23 freeze on
`knowledge_graph` and `qualification_risk` holds).

No FK from `qualification_answer (toolId, questionId)` to `question (scope, local_id)` (01-spec A3 kept).

### 3.2 Triggers (PL/pgSQL, `CREATE OR REPLACE FUNCTION qualification.<name>() ... ; CREATE TRIGGER <name>`)

| Trigger (function of the same name) | When | Raises (exact message, `%` = the row id named) |
|---|---|---|
| `question_set_version_is_append_only` | BEFORE UPDATE OR DELETE on `question_set_version` | `question set version % is immutable: save a new version instead` (OLD.id) |
| `question_set_version_item_is_append_only` | BEFORE UPDATE OR DELETE on `question_set_version_item` | same message with OLD.set_version_id |
| `questionnaire_version_is_append_only` | BEFORE UPDATE OR DELETE on `questionnaire_version` | `questionnaire version % is immutable: save a new version instead` (OLD.id) |
| `questionnaire_version_item_is_append_only` | BEFORE UPDATE OR DELETE on `questionnaire_version_item` | same message with OLD.questionnaire_version_id |
| `question_identity_is_fixed` | BEFORE UPDATE OR DELETE on `question` | DELETE: `question % cannot be deleted: versions refer to it`; UPDATE of `set_id`, `scope`, `local_id` or `created_at`: `question % keeps its identity: set, scope and local id are fixed` |
| `question_set_version_item_is_of_its_set` | BEFORE INSERT on `question_set_version_item` | when `(SELECT set_id FROM question WHERE id = NEW.question_id)` IS DISTINCT FROM `(SELECT set_id FROM question_set_version WHERE id = NEW.set_version_id)`: `question % is not a question of the set of version %` (NEW.question_id, NEW.set_version_id) |
| `question_set_row_is_fixed` | BEFORE UPDATE OR DELETE on `question_set` | DELETE: `question set % cannot be deleted: retire it instead`; UPDATE changing `name`, `origin`, `created_at` or `created_by`, or changing `retired_at` when OLD.retired_at IS NOT NULL: `question set % keeps its name, origin and author; it can only be retired, once`. Changing `description`, and `retired_at` from NULL to a value, pass. |
| `questionnaire_row_is_fixed` | BEFORE UPDATE OR DELETE on `questionnaire` | same rules plus `listed`; messages `questionnaire % cannot be deleted: retire it instead` / `questionnaire % keeps its name, origin, listing and author; it can only be retired, once` |
| `question_set_version_is_allowed` | BEFORE INSERT on `question_set_version` | set `origin = 'builtin'` and a version exists: `question set % is builtin: it has one version, made by a migration`; set retired: `question set % is retired: it gets no new version` |
| `questionnaire_version_is_allowed` | BEFORE INSERT on `questionnaire_version` | same two rules: `questionnaire % is builtin: it has one version, made by a migration` / `questionnaire % is retired: it gets no new version` |

The builtin rules ("one builtin, it is the default, it has one version") move from `form` to
`question_set` and `questionnaire` (the CHECKs of 3.1 and the two `_is_allowed` triggers). There is no
default flag: the default is the constant `annex-iv-default` (06 R43 kept).

Not enforced by the database (as today for `form_version_question`): an INSERT of an item into an already
existing version. The app never does it (**ASSUMED (D26)**).

### 3.3 Prisma models (`prisma/schema.prisma`)

`Form`, `FormVersion`, `FormQuestion`, `FormVersionQuestion` are removed. Added (partial indexes, CHECKs
and triggers live only in the migration, as today):

```prisma
/// Where questions are written. The builtin set is id "annex-iv" (ANNEX_SET_ID in src/domain/forms/legacy.ts).
model QuestionSet {
  id          String               @id @default(cuid())
  /// Fixed at creation.
  name        String
  description String               @default("")
  /// "builtin" (Annex IV), "builder" or "import".
  origin      String
  /// Retired: hidden from lists and pickers, still resolvable. Set once, never cleared.
  retiredAt   DateTime?            @map("retired_at") @db.Timestamptz(3)
  createdAt   DateTime             @default(now()) @map("created_at") @db.Timestamptz(3)
  createdBy   String               @map("created_by")
  versions    QuestionSetVersion[]
  questions   Question[]

  @@map("question_set")
}

/// One immutable version of a question set. Append-only.
model QuestionSetVersion {
  id        String                   @id @default(cuid())
  setId     String                   @map("set_id")
  number    Int
  createdAt DateTime                 @default(now()) @map("created_at") @db.Timestamptz(3)
  createdBy String                   @map("created_by")
  set       QuestionSet              @relation(fields: [setId], references: [id], onDelete: Restrict)
  items     QuestionSetVersionItem[]

  @@unique([setId, number], map: "question_set_version_set_id_number_key")
  @@map("question_set_version")
}

/// A question's identity. Its wording is per set version.
model Question {
  id        String                   @id @default(cuid())
  setId     String                   @map("set_id")
  /// "annex-1"/"annex-2" (builtin), "f-<old form id>" (before 2026-09-25), "s-<set id>" (after).
  scope     String
  /// "1a" ... (builtin), "q1", "q2", ... per set, never reused.
  localId   String                   @map("local_id")
  createdAt DateTime                 @default(now()) @map("created_at") @db.Timestamptz(3)
  set       QuestionSet              @relation(fields: [setId], references: [id], onDelete: Restrict)
  items     QuestionSetVersionItem[]

  @@unique([scope, localId], map: "question_scope_local_id_key")
  @@index([setId], map: "question_set_id_idx")
  @@map("question")
}

/// A question as one set version words it. Immutable. The only place wording lives.
model QuestionSetVersionItem {
  setVersionId String                     @map("set_version_id")
  questionId   String                     @map("question_id")
  position     Int
  text         String
  citation     String                     @default("")
  required     Boolean
  annexPoint   String?                    @map("annex_point")
  groupLabel   String?                    @map("group_label")
  setVersion   QuestionSetVersion         @relation(fields: [setVersionId], references: [id], onDelete: Restrict)
  question     Question                   @relation(fields: [questionId], references: [id], onDelete: Restrict)
  usedBy       QuestionnaireVersionItem[]

  @@id([setVersionId, questionId], map: "question_set_version_item_pkey")
  @@unique([setVersionId, position], map: "question_set_version_item_set_version_id_position_key")
  @@index([questionId], map: "question_set_version_item_question_id_idx")
  @@map("question_set_version_item")
}

/// What a card is filled with. The default is always id "annex-iv-default" (DEFAULT_QUESTIONNAIRE_ID). There is no default flag.
model Questionnaire {
  id          String                 @id @default(cuid())
  name        String
  description String                 @default("")
  origin      String
  /// false for "Use once": never in lists or the chooser.
  listed      Boolean                @default(true)
  retiredAt   DateTime?              @map("retired_at") @db.Timestamptz(3)
  createdAt   DateTime               @default(now()) @map("created_at") @db.Timestamptz(3)
  createdBy   String                 @map("created_by")
  versions    QuestionnaireVersion[]

  @@map("questionnaire")
}

/// One immutable questionnaire version. Append-only.
model QuestionnaireVersion {
  id              String                     @id @default(cuid())
  questionnaireId String                     @map("questionnaire_id")
  number          Int
  /// Included blocks, a subset of FORM_BLOCKS. The identity block is implicit.
  blocks          String[]
  createdAt       DateTime                   @default(now()) @map("created_at") @db.Timestamptz(3)
  createdBy       String                     @map("created_by")
  questionnaire   Questionnaire              @relation(fields: [questionnaireId], references: [id], onDelete: Restrict)
  items           QuestionnaireVersionItem[]
  qualifications  Qualification[]

  @@unique([questionnaireId, number], map: "questionnaire_version_questionnaire_id_number_key")
  @@map("questionnaire_version")
}

/// One picked question, pinned to the set version whose wording it shows.
model QuestionnaireVersionItem {
  questionnaireVersionId String                 @map("questionnaire_version_id")
  position               Int
  setVersionId           String                 @map("set_version_id")
  questionId             String                 @map("question_id")
  questionnaireVersion   QuestionnaireVersion   @relation(fields: [questionnaireVersionId], references: [id], onDelete: Restrict)
  setItem                QuestionSetVersionItem @relation(fields: [setVersionId, questionId], references: [setVersionId, questionId], onDelete: Restrict, map: "questionnaire_version_item_set_item_fkey")

  @@id([questionnaireVersionId, questionId], map: "questionnaire_version_item_pkey")
  @@unique([questionnaireVersionId, position], map: "questionnaire_version_item_questionnaire_version_id_position_key")
  @@index([setVersionId, questionId], map: "questionnaire_version_item_set_version_id_question_id_idx")
  @@map("questionnaire_version_item")
}
```

In `model Qualification`, `formVersionId`/`formVersion` become:

```prisma
  /// The questionnaire version this card was filled with. NULL means "Annex IV default" v1
  /// (annex-iv-default-v1): every card saved before forms existed.
  questionnaireVersionId String?               @map("questionnaire_version_id")
  questionnaireVersion   QuestionnaireVersion? @relation(fields: [questionnaireVersionId], references: [id], onDelete: Restrict, map: "qualification_questionnaire_version_id_fkey")
  @@index([questionnaireVersionId], map: "qualification_questionnaire_version_id_idx")   // replaces the formVersionId index
```

`npx prisma validate` (dummy `DATABASE_URL`) must pass.

### 3.4 Fixed ids

| Constant (`src/domain/forms/legacy.ts`) | Value |
|---|---|
| `ANNEX_SET_ID` | `annex-iv` |
| `ANNEX_SET_VERSION_ID` | `annex-iv-v1` |
| `DEFAULT_QUESTIONNAIRE_ID` | `annex-iv-default` |
| `DEFAULT_VERSION_ID` | `annex-iv-default-v1` (unchanged) |
| builtin question ids | `annex-iv-<id>` (unchanged: `annex-iv-1a`, ..., `annex-iv-2h`) |
| builtin set name / questionnaire name | `Annex IV` / `Annex IV default` |
| `created_by` of builtin rows | `system` |
| `created_by` of rows migrated from forms | `unknown` (**ASSUMED (D3)**) |

`DEFAULT_FORM_ID` is removed (06 R44's source scan of `setDefault` and friends stays valid).

---

## 4. The forward migration

### 4.1 File and rules

`prisma/migrations/20260925150000_two_level_forms/migration.sql` (**ASSUMED (D28)**: the name). The
migrations `20260925090000_forms_are_data` and `20260925120000_the_default_form_is_fixed` are applied on
live and are **not edited** (their bytes stay; `test/unit/annexDefaultForm.test.ts` pins them).

Rules (as 090000 and 120000): every name schema-qualified; no `BEGIN`/`COMMIT` (the file runs as one
multi-statement query, which Postgres executes as one implicit transaction: any `RAISE EXCEPTION` rolls
back everything and leaves the old tables as they were); no `CONCURRENTLY`; no `IF EXISTS` (an unexpected
shape fails loudly); no `CASCADE`; no `UPDATE`, `DELETE` or `TRUNCATE` of any row in any table (outside
the bodies of the `CREATE OR REPLACE FUNCTION` trigger functions, which only raise). New rows are only
`INSERT ... SELECT` from the old tables. No `DO` block uses an `EXCEPTION` clause (no subtransactions).

### 4.2 Order of operations (all in the one transaction)

1. **Capture.** `CREATE TEMP TABLE tlf_counts ON COMMIT DROP AS SELECT` the row counts of
   `qualification`, `qualification_answer`, `qualification_risk`, `knowledge_graph`, `card_component`,
   `form`, `form_version`, `form_question`, `form_version_question`.
2. **Precondition P1** (DO block): exactly one `form` with `origin = 'builtin'`, its id is
   `annex-iv-default`, it has exactly one `form_version`, id `annex-iv-default-v1`, number 1, with exactly
   14 `form_version_question` rows whose `question_id`s are the 14 `annex-iv-<id>` ids owned by
   `annex-iv-default`. Otherwise `RAISE EXCEPTION 'two-level forms migration: the builtin form
   annex-iv-default v1 is not as seeded'`.
3. **Create** the seven tables, their constraints and indexes of 3.1. No trigger yet.
4. **Builtin level** (INSERT ... SELECT from the old rows, so the wording is byte for byte what cards were
   rendered with):
   - `question_set`: (`annex-iv`, `Annex IV`, description `EU AI Act Annex IV points 1 and 2, as 14
     questions.`, `builtin`, NULL, created_at of form `annex-iv-default`, `system`).
   - `question`: one per `form_question` owned by `annex-iv-default`: same `id`, `set_id = 'annex-iv'`,
     same `scope`, `local_id`, `created_at`.
   - `question_set_version`: (`annex-iv-v1`, `annex-iv`, 1, created_at of `annex-iv-default-v1`, `system`).
   - `question_set_version_item`: one per `form_version_question` of `annex-iv-default-v1`:
     `set_version_id = 'annex-iv-v1'`, same `question_id`, `position`, `text`, `citation`, `required`,
     `annex_point`, `group_label`.
   - `questionnaire`: (`annex-iv-default`, `Annex IV default`, the form's description, `builtin`, true,
     NULL, the form's created_at, `system`).
   - `questionnaire_version`: (`annex-iv-default-v1`, `annex-iv-default`, 1, the old version's `blocks`,
     its created_at, `system`).
   - `questionnaire_version_item`: one per old row: (`annex-iv-default-v1`, same `position`,
     `annex-iv-v1`, same `question_id`).
5. **Pass A: sets from the other forms.** For every form F with `origin <> 'builtin'`, in order
   `(created_at, id)`, that owns at least one `form_question` (**ASSUMED (D6)**: a form owning none gets
   no set):
   1. `question_set`: `id = F.id`, `name = F.name`, `description = F.description`, `origin = F.origin`,
      `retired_at = CASE WHEN F.listed THEN NULL ELSE now() END` (**ASSUMED (D2)**: a use-once form's own
      questions become a retired set), `created_at = F.created_at`, `created_by = 'unknown'`
      (**ASSUMED (D1)**: the set keeps the form's id).
   2. `question`: one per `form_question` q owned by F: `id = q.id`, `set_id = F.id`, same `scope`
      (`f-<F.id>`), `local_id`, `created_at`. `copied_from_id` is not carried (**ASSUMED (D8)**).
   3. For each version Vk of F in `number` order: let L(Vk) be the rows of Vk whose question is owned by F,
      in `position` order, as the list of tuples `(question_id, text, citation, required, annex_point,
      group_label)`. If L(Vk) is empty, Vk gets no set version. Else, if the set's most recent set version
      made in this pass has the same list (same length, and at every index every tuple field equal, using
      `IS NOT DISTINCT FROM` for the nullable ones), Vk is **assigned** that set version. Else insert set
      version `n = (max number of the set, 0 if none) + 1` with `id = F.id || '-v' || n`,
      `created_at = Vk.created_at`, `created_by = 'unknown'`, and its items: L(Vk) in order with
      `position` 0, 1, ... ; Vk is assigned it. The assignment is kept in a temp table
      `tlf_assigned (form_version_id, set_version_id)`.
6. **Pass B: questionnaires from the other forms.** For every form F with `origin <> 'builtin'`, in order
   `(created_at, id)`:
   1. `questionnaire`: `id = F.id`, same `name`, `description`, `origin`, `listed`, `retired_at = NULL`,
      `created_at = F.created_at`, `created_by = 'unknown'`.
   2. For each version Vk: `questionnaire_version`: `id = Vk.id` (**ASSUMED (D1)**: the version keeps the
      form version's id, so no card row needs an UPDATE), `questionnaire_id = F.id`, same `number`,
      `blocks`, `created_at`, `created_by = 'unknown'`.
   3. For each row r of Vk in `position` order (question X, owner form O, wording W = the five fields):
      the owner set S is `annex-iv` when O is `annex-iv-default`, else O's id. The pinned set version:
      - when O = F (an own question): the set version assigned to Vk in pass A;
      - otherwise (a pick): among the set versions of S whose item for X has wording equal to W (five
        fields, `IS NOT DISTINCT FROM` for the nullable ones), the one with the highest `number`
        (**ASSUMED (D7)**);
      - when none matches (only possible for hand-edited data: every pick copies a snapshot that
        originates in the owner's own rows): if S is `annex-iv`, `RAISE EXCEPTION 'two-level forms
        migration: form version % pins wording of % that no version of Annex IV has'` (Vk.id, X); else
        insert set version `n = max + 1` of S (`id = S || '-v' || n`, `created_at = Vk.created_at`,
        `created_by = 'unknown'`) whose items are the items of S's current highest version with X's row
        replaced by W at the same position, or, when X is not in it, appended at the next position; then
        `RAISE NOTICE 'two-level forms migration: made question set version % for the wording pinned in
        form version %'` and pin to it.
      Insert `questionnaire_version_item (Vk.id, r.position, <pinned set version id>, X)`.
7. **Checks** (DO block; each failure is `RAISE EXCEPTION 'two-level forms migration: check <id>
   failed: expected <x>, found <y>'`):
   - C1 `count(question_set)` = 1 + number of non-builtin forms owning at least one `form_question`.
   - C2 `count(question)` = `count(form_question)`, and zero `form_question` rows without a `question` of
     the same `id`, `scope`, `local_id` and `set_id` (= `annex-iv` for questions owned by
     `annex-iv-default`, else the owner form id).
   - C3 `count(questionnaire)` = `count(form)`, and zero forms without a questionnaire of the same `id`,
     `name`, `description`, `origin`, `listed`, `created_at`.
   - C4 `count(questionnaire_version)` = `count(form_version)`, and zero form versions without a
     questionnaire version of the same `id`, `questionnaire_id = form_id`, `number`, `blocks`,
     `created_at`.
   - C5 `count(questionnaire_version_item)` = `count(form_version_question)`, and zero
     `form_version_question` rows without an item of the same `(questionnaire_version_id, question_id,
     position)` whose `question_set_version_item` has the same `text`, `citation`, `required`,
     `annex_point`, `group_label` (nullable ones with `IS NOT DISTINCT FROM`). This is the "no wording is
     lost, no card changes" check.
   - C6 zero `question_set_version_item` rows whose question's `set_id` differs from its set version's
     `set_id`.
   - C7 `annex-iv-v1` has 14 items, `annex-iv-default-v1` has 14 items, all pointing at `annex-iv-v1`.
8. **The card column** (no row is updated, so `qualification_only_latest_changes`, a BEFORE UPDATE row
   trigger, and `answer_only_latest_changes`, BEFORE INSERT OR UPDATE on answers, never fire):
   ```sql
   ALTER TABLE qualification.qualification DROP CONSTRAINT qualification_form_version_id_fkey;
   ALTER TABLE qualification.qualification RENAME COLUMN form_version_id TO questionnaire_version_id;
   ALTER INDEX qualification.qualification_form_version_id_idx RENAME TO qualification_questionnaire_version_id_idx;
   ALTER TABLE qualification.qualification ADD CONSTRAINT qualification_questionnaire_version_id_fkey
     FOREIGN KEY (questionnaire_version_id) REFERENCES qualification.questionnaire_version (id) ON DELETE RESTRICT;
   ```
   Every non-NULL value is an old form version id, which step 6.2 made a questionnaire version id, so the
   FK validates. `ALTER ... RENAME` and `ADD CONSTRAINT` fire no row trigger.
9. **Drop** (after the checks, in this order, no CASCADE):
   `DROP TABLE qualification.form_version_question;` `DROP TABLE qualification.form_question;`
   `DROP TABLE qualification.form_version;` `DROP TABLE qualification.form;` (their triggers go with
   them), then `DROP FUNCTION` for `qualification.form_version_is_append_only()`,
   `form_version_question_is_append_only()`, `form_question_identity_is_fixed()`,
   `form_name_is_fixed()`, `form_builtin_is_fixed()`. Also dropped with the tables: the `form` CHECK
   `form_builtin_is_the_default`, index `form_listed_name_key`, the `copied_from_id` lineage.
10. **Triggers** of 3.2: create the functions and triggers now (after the data, so steps 4 to 6 are not
    refused by `_is_allowed` for the retired sets of D2 or the builtin rows).
11. **Final check C8**: the five history counts in `tlf_counts` are unchanged
    (`qualification`, `qualification_answer`, `qualification_risk`, `knowledge_graph`,
    `card_component`); and `to_regclass('qualification.form')` etc. are NULL for the four old tables.

The unique answer index `qualification_answer_qualification_id_tool_id_question_id_key` is untouched.

### 4.3 Proof on paper: Annex IV cards keep answers, graph and digest byte-identical

Let c be any card filled with the Annex IV default: `form_version_id` NULL (every live card today) or
`annex-iv-default-v1`.

1. **Rows.** The migration issues no UPDATE, DELETE or TRUNCATE and no INSERT into
   `qualification`, `qualification_answer`, `qualification_risk`, `knowledge_graph`, `card_component`
   (4.1, checked by C8 and by T9's digest). The column rename changes the column's name, not its values.
   So c's row, answers (`toolId` `annex-1`/`annex-2`, `questionId` `1a`...), risks, stored graph and
   components are the same bytes.
2. **Resolved questionnaire.** NULL resolves in memory to `annexDefaultVersion()` (T3 proves it equals the
   migrated DB rows); `annex-iv-default-v1` resolves from the DB, whose items point at `annex-iv-v1`, whose
   wording rows were copied column for column from the old `annex-iv-default-v1` rows (step 4, checked by
   C5). Both give, per question, the same `key` (`annex-1:1a`...), `field`, `text`, `citation`,
   `required`, `annexPoint`, `groupLabel` as before, in the same order, and the same blocks.
3. **Export to the ontology service** (`toExport`). `answers` are built from `key`, `citation`,
   `annexPoint` of the resolved questions only (`answersInForm`): identical. `form.name` = the
   questionnaire name `Annex IV default` = the old form name; `form.version` = 1. The per-question owner
   fields change: `ownerForm: "Annex IV default"`, `ownerFormId: "annex-iv-default"` become
   `ownerSet: "Annex IV"`, `ownerSetId: "annex-iv"`; `ownerBuiltin` stays `true` (T45).
4. **Graph.** `build_graph` reads per answer `toolId`, `questionId`, `answer`, `annexPoint`, and `citation`
   only for scopes other than `annex-1`/`annex-2` (`build.py` lines 346 to 370); it never reads `form`. So
   the triples are identical, and so are `graph_digest`, Turtle and JSON-LD.
5. **View, card JSON, PDF.** `build_view` adds `form: {name, version}` (identical), `coverage` and
   `additionalDocumentation`. `coverage` counts points from `key`/`annexPoint`/`required`, and lists
   `forms` only for questions whose `ownerBuiltin` is false: none. `additional_documentation` lists only
   answered questions with `annexPoint` null: none (all 14 are tagged). So coverage and
   `additionalDocumentation` (`[]`) are identical, whichever owner keys are sent. `ai-card.json`
   (`aiCardExport`) and the PDF read that view, and the view's key names (`forms`, `form`) are kept
   (**ASSUMED (D17)**). Identical.
6. **Custom-form cards** (none on live) are identical too: their questionnaire version has the old form
   version's id, its items carry the old wording (C5), and their owner set has the owner form's id and name
   (step 5.1), so coverage groups them under the same id and name as before.

T9 checks points 1 and 2 on a real database; T10 and T11 check points 3 to 5 in code.

### 4.4 Down path

None. Prisma has no down migrations, and the forward migration drops the form tables. Recovery is the
database backup: `DEPLOY.md` gains a step "before deploying 20260925150000_two_level_forms, `pg_dump
--schema=qualification`" (**ASSUMED (D25)**). A migration that fails leaves the database as it was (one
transaction); `prisma migrate deploy` then records it as failed (P3009) and refuses to continue until
`prisma migrate resolve --rolled-back 20260925150000_two_level_forms` is run after the data is fixed.

---

## 5. TS modules and routes

### 5.1 Types (`src/domain/forms/types.ts`, replaced)

```ts
export type ResolvedQuestion = {
  questionId: string;        // question.id
  scope: string;             // "annex-1" | "f-<old form id>" | "s-<set id>"
  localId: string;
  key: string;               // `${scope}:${localId}`
  field: string;             // `q:${scope}:${localId}`
  text: string;
  citation: string;          // may be ""
  required: boolean;
  annexPoint: AnnexPointId | null;
  groupLabel: string | null;
  setId: string;
  setName: string;
  setVersionId: string;      // the set version this wording is from
  setVersionNumber: number;
  setBuiltin: boolean;
};
export type ResolvedQuestionnaireVersion = {
  questionnaireId: string;
  questionnaireName: string;
  description: string;
  listed: boolean;
  builtin: boolean;
  retired: boolean;
  versionId: string;
  versionNumber: number;
  blocks: FormBlock[];               // FORM_BLOCKS order
  questions: ResolvedQuestion[];     // item position order
};
export type ResolvedSetVersion = {
  setId: string;
  setName: string;
  description: string;
  origin: "builtin" | "builder" | "import";
  builtin: boolean;
  retired: boolean;
  versionId: string;
  versionNumber: number;
  questions: ResolvedQuestion[];     // set item position order
};
/** One version's stamp: who saved it, when. */
export type VersionStamp = { versionId: string; number: number; createdAt: string /* ISO 8601 */; createdBy: string };
export type QuestionnaireResolver = {
  resolve(id: string | null): Promise<ResolvedQuestionnaireVersion | null>;
};
```

`ResolvedFormVersion` and `FormResolver` are removed. Every consumer (`QualificationFormParser`,
`QualificationService`, `OntologyService`, `QualificationExporter`, `QualifyForm`, `AnsweredForm`,
`useDocumentPrefill`, `prefillChoice`, the card and edit pages, `extracted/route.ts`) takes
`ResolvedQuestionnaireVersion`; where they read `ownerFormName` they read `setName`, where `ownerFormId`
`setId`, where `ownerBuiltin` `setBuiltin`, where `formId`/`formName` `questionnaireId`/`questionnaireName`.
The hidden form field is `questionnaireVersionId`; `createFromForm` also accepts the old name
`formVersionId` when the new one is absent (pages open during the deploy) (**ASSUMED (D20)**).

### 5.2 Pure modules (`src/domain/forms/`)

| File | Exports |
|---|---|
| `legacy.ts` (changed) | constants of 3.4; `resolveQuestionnaireVersionId(id: string \| null): string`; `annexDefaultVersion(): ResolvedQuestionnaireVersion` (fresh value each call); `annexSetVersion(): ResolvedSetVersion` |
| `questionSetDraft.ts` (new) | `SetDraft`, `parseSetDraft(input, {takenNames?})`, `sameSetContent(draft, latest: ResolvedSetVersion)` |
| `setEditorState.ts` (new) | `SetEditorState`, `setEditorReducer`, `initialSetEditorState`, `toSetDraft` |
| `questionnaireDraft.ts` (new, replaces `formDraft.ts`) | `QuestionnaireDraft`, `parseQuestionnaireDraft(input, {takenNames?})`, `sameQuestionnaireContent(draft, version)` |
| `builderState.ts` (rewritten) | the questionnaire builder's state (T27 to T33) |
| `library.ts` (changed) | `SetGroup`, `filterLibrary` (unchanged), `overlapHints` (unchanged), `overlapLabel` (unchanged), `updatesAvailable` (replaces `sourceUpdates`) |
| `chooser.ts` (changed) | `preselect`, `pickQuestionnaireParams` (replaces `pickFormParams`) |
| `moveCard.ts` (new) | `rewordedSince`, `droppedAnswers`, `moveNotice`, `newerVersion` |
| `references.ts` (new) | `missingReferences` |
| `useOnceName.ts` | unchanged (`useOnceFormName`) (**ASSUMED (D30)**: use-once names keep the prefix "Custom questions: ") |
| `annexPoints.ts`, `blocks.ts` | unchanged |

`src/server/access/callerName.ts` (new): `identityFromToken(token: string | null): string | null` (pure) and
`callerName(): Promise<string>`.

### 5.3 Server modules

| File | Replaces | Exports |
|---|---|---|
| `src/server/repositories/QuestionSetRepository.ts` | `FormRepository.ts` (deleted) | Prisma reads and one-transaction writes for sets |
| `src/server/repositories/QuestionnaireRepository.ts` | same | same for questionnaires |
| `src/server/services/QuestionSetService.ts` | `FormService.ts` (deleted) | `list({retired})`, `groups()`, `resolveSetVersion(id)`, `latest(setId)`, `atNumber(setId, n?)`, `history(setId): VersionStamp[]`, `saveDraft(draft, opts)`, `retire(setId)`; singleton `questionSetService` |
| `src/server/services/QuestionnaireService.ts` | same | `resolve(id \| null)`, `latestVersion(id)`, `exportable(id, n?)`, `library({retired})`, `chooserOptions()`, `history(id)`, `saveDraft(draft, opts)`, `retire(id)`, `resolveReferences(items)`, `importSelfContained(file, opts)`; singleton `questionnaireService` |
| `src/server/services/FormExportClient.ts` | (changed) | `write(list: {name: string; version: number; questions: {text, citation, required, annexPoint}[]}, format)`; everything else as 06 R56 |
| `src/server/services/QuestionnaireFileClient.ts` | new | `write(file: QuestionnaireFileInput, bundle)`, `read(file: File)`; never throws; same 503/502 contract and `QUALIFICATION_WEB_TO_PREFILL_TOKEN` header as `FormImportClient` |
| `src/server/services/FormImportClient.ts` | unchanged | |

Both services take their repository in the constructor and `{ newId = randomUUID, now = () => new Date() }`
as today; `test/support/fakeQuestionnaireStore.ts` (replaces `fakeFormStore.ts`) implements both
repositories in memory.

### 5.4 Routes (all under `/p/[project]`, so `src/middleware.ts`, unchanged, applies: GET for any member,
POST only with `may_write`)

| Route | Kind | Behaviour |
|---|---|---|
| `/question-sets` | page | List of non-retired sets; `?retired=1` lists retired ones (T20) |
| `/question-sets/new` | page | Set editor, empty (T14) |
| `/question-sets/[setId]` | page | One set: versions with who and when, one version's questions (`?version=<n>`, default latest) (T21) |
| `/question-sets/[setId]/edit` | page | Set editor on the latest version; 404 for builtin, retired or unknown (T15) |
| `/question-sets/import` | page | Upload CSV/MD/DOCX, preview, then the set editor (T49) |
| `/question-sets/[setId]/export` | GET route | `?format=csv\|md[&version=<n>]` (T47) |
| `/question-sets/actions.ts` | server actions | `saveQuestionSet`, `retireQuestionSet` |
| `/question-sets/import/actions.ts` | server action | `readQuestionSetFile` (was `readFormFile`, same body) |
| `/questionnaires` | page | List of listed, non-retired questionnaires; `?retired=1` retired ones (T34) |
| `/questionnaires/new` | page | Builder; `?from=<id>` starts from that questionnaire (T31) |
| `/questionnaires/[questionnaireId]/edit` | page | Builder on the latest version; 404 for builtin, unlisted, retired or unknown |
| `/questionnaires/import` | page | Upload a questionnaire `.json`, then the builder (reference) or the create-both preview (self-contained) (T53, T54) |
| `/questionnaires/[questionnaireId]/export` | GET route | `?format=json\|csv\|md[&bundle=self-contained][&version=<n>]` (T48) |
| `/questionnaires/actions.ts` | server actions | `saveQuestionnaire`, `useQuestionnaireOnce`, `retireQuestionnaire` |
| `/questionnaires/import/actions.ts` | server actions | `readQuestionnaireFile`, `importSelfContained` |
| `/system/edit` | page (changed) | the chooser and the card form (T36 to T41) |
| `/forms`, `/forms/new`, `/forms/[formId]/edit`, `/forms/import`, `/forms/[formId]/export` | kept as redirects only | T62 |

Files deleted: `src/app/p/[project]/forms/FormBuilder.tsx`, `forms/actions.ts`, `forms/libraryData.ts`,
`forms/import/FormImport.tsx`, `forms/import/actions.ts`, `src/domain/forms/formDraft.ts`,
`src/server/services/FormService.ts`, `src/server/repositories/FormRepository.ts`,
`test/support/fakeFormStore.ts`. New components: `question-sets/QuestionSetEditor.tsx`,
`question-sets/import/QuestionSetImport.tsx` (the old import preview, moved), `questionnaires/QuestionnaireBuilder.tsx`
(from `FormBuilder.tsx`), `questionnaires/import/QuestionnaireImport.tsx`, `questionnaires/libraryData.ts`,
`src/app/p/[project]/RetireButton.tsx`. `system/edit/FormChooser.tsx` and `FormLine.tsx` keep their file
names; their texts change (T36, T42). CSS: the design-pass classes of 10-ui-plan are reused (`qf-forms-page`,
`qf-forms-table`, `qf-builder*`, `qf-import*`, `qf-tag*`); the set editor uses the builder's editor panel
(`qf-builder-editor`) and row (`qf-builder-row`) classes.

---

## 6. Requirements

### A. Schema and migration

**T1. The Prisma schema has the two levels and nothing of the form.**
- Given `prisma/schema.prisma` read as text, then it has models `QuestionSet`, `QuestionSetVersion`,
  `Question`, `QuestionSetVersionItem`, `Questionnaire`, `QuestionnaireVersion`,
  `QuestionnaireVersionItem` with the fields and `@map`/`@@map` names of 3.3; it has no model `Form`,
  `FormVersion`, `FormQuestion`, `FormVersionQuestion`; `Qualification` has `questionnaireVersionId`
  mapped to `questionnaire_version_id` and no `formVersionId`; no field of the seven models contains
  `project` (case-insensitive; 06 R47 carried over).
- Tests: `test/unit/twoLevelSchema.test.ts` (unit).

**T2. The migration file obeys its rules.**
- Given `prisma/migrations/20260925150000_two_level_forms/migration.sql`, with `--` comments stripped and
  the bodies of every `CREATE OR REPLACE FUNCTION ... $$ ... $$` removed, then it contains no `BEGIN`,
  `COMMIT`, `CONCURRENTLY`, `IF EXISTS`, `CASCADE`, and no statement (a line, after leading whitespace,
  or text after a `;`) starting with `UPDATE`, `DELETE FROM` or `TRUNCATE` (`ON DELETE RESTRICT` and
  `BEFORE UPDATE OR DELETE` are not statements; `DO $$ ... $$` bodies are kept for this scan, so the split
  contains no such statement either); it contains, in this
  order, `CREATE TABLE qualification.question_set`, `RENAME COLUMN form_version_id TO
  questionnaire_version_id`, `DROP TABLE qualification.form_version_question`, `DROP TABLE
  qualification.form;`, and the `CREATE TRIGGER` statements of every trigger in 3.2 after the last `DROP
  TABLE`.
- Given the files of 20260925090000 and 20260925120000, then their bytes are unchanged (the existing tests
  in `annexDefaultForm.test.ts` that pin them keep passing unmodified).
- Tests: `test/unit/twoLevelMigration.test.ts` (unit).

**T3. A fresh install has the builtin set and the default questionnaire, equal to the in-memory twin.**
- Given a migrated throwaway DB, when `QuestionnaireService.resolve("annex-iv-default-v1")` runs with the
  real repository, then it deep-equals `annexDefaultVersion()`; and `annexDefaultVersion().questions[i]`
  has `questionId = "annex-iv-<id>"`, `scope = group`, `localId = id`, text and citation verbatim from
  `KEY_QUESTIONS`, `required = !optional`, `annexPoint = id`, `groupLabel = groupLabel`,
  `setId = "annex-iv"`, `setName = "Annex IV"`, `setVersionId = "annex-iv-v1"`, `setVersionNumber = 1`,
  `setBuiltin = true`; the version has `questionnaireName = "Annex IV default"`, `builtin = true`,
  `listed = true`, `retired = false`, all 9 blocks.
- Given the DB, then `question_set` `annex-iv` and `questionnaire` `annex-iv-default` have `created_by =
  'system'`, and no table `form`, `form_version`, `form_question`, `form_version_question` exists.
- Tests: `test/unit/annexDefaultForm.test.ts` (unit, existing, the `annexDefaultVersion` tests updated to
  these field names), `test/db/twoLevelForms.db.test.ts` (DB).

**T4. Versions are append-only; identity is fixed.**
- Given the migrated DB, when anything issues UPDATE or DELETE on a row of `question_set_version`,
  `question_set_version_item`, `questionnaire_version` or `questionnaire_version_item`, then Postgres
  raises the message of 3.2 (`... is immutable: save a new version instead`).
- When `question.local_id`, `scope` or `set_id` is updated, or a question deleted, then it raises.
- When a `question_set_version_item` is inserted whose question belongs to another set, then
  `question_set_version_item_is_of_its_set` raises.
- When a `questionnaire_version_item` names a `(set_version_id, question_id)` that is not a set item, then
  the insert fails on `questionnaire_version_item_set_item_fkey`; when two items of one version name the
  same question, the second fails on the primary key.
- Tests: `test/db/twoLevelForms.db.test.ts` (DB).

**T5. The builtin rows are fixed and the default is not a flag.**
- Inserting a `question_set_version` for `annex-iv` raises `question set annex-iv is builtin ...`;
  inserting a `questionnaire_version` for `annex-iv-default` raises the questionnaire twin.
- Inserting a `question_set` with origin `builtin` and another id fails on
  `question_set_builtin_is_annex_iv`; the same for `questionnaire_builtin_is_the_default`; setting
  `retired_at` on either builtin row fails on that CHECK.
- Updating `annex-iv-default` to `listed = false` raises `questionnaire annex-iv-default keeps its name,
  origin, listing and author; it can only be retired, once`; updating its `description` succeeds (rolled
  back).
- Tests: `test/db/twoLevelForms.db.test.ts` (DB).

**T6. Retiring is one-way and frees the name.**
- Given a set S (`builder`), when `retired_at` is set, then it succeeds; setting it again (to another
  time or NULL) raises; inserting a new version of S raises `question set <S> is retired ...`.
- Given two non-retired sets, a second with the same name in other case fails on
  `question_set_active_name_key`; after the first is retired, a new set with that name succeeds.
- Given two listed non-retired questionnaires, the same rule on `questionnaire_listed_name_key`; two
  unlisted questionnaires with one name both succeed.
- DELETE of a `question_set` or `questionnaire` row raises (`cannot be deleted: retire it instead`).
- Tests: `test/db/twoLevelForms.db.test.ts` (DB).

**T7. Answer keys are unchanged.**
- The index `qualification_answer_qualification_id_tool_id_question_id_key` exists once; the same
  `(qualificationId, toolId, questionId)` twice fails; the same `questionId` under two `toolId`s succeeds
  (the old R5 DB test, moved unchanged in substance).
- Given a card, when its `questionnaireVersionId` is set to `annex-iv-default-v1`, then
  `pg_constraint` shows one FK from `qualification` to `questionnaire_version` with `confdeltype = 'r'`.
- Tests: `test/db/twoLevelForms.db.test.ts` (DB).

**T8. The split, on a fixture library.**
In one psql script inside `BEGIN; ... ROLLBACK;` (the pattern of the old R7 test): put the schema back to
before this migration (drop the seven new tables, their trigger functions, and
`qualification.questionnaire_version_id`; recreate the unique index
`"QualificationAnswer_qualificationId_questionId_key"` after deleting rows only the new key allows, as the
old test did; run the texts of 20260925090000 and 20260925120000); insert the fixture below; run the new
migration's text; then assert. Fixture (ids literal):

| Form | origin, listed | Versions |
|---|---|---|
| `acme` "Acme AI policy" | builder, listed | v1: own `acme-q1` "Who signs off?" (citation "§4.2", required, untagged), own `acme-q2` "Which data?" (optional, `2d`). v2: `acme-q1` "Who signs off a release?" (reworded), `acme-q2` unchanged, pick `annex-iv-2a` (verbatim). v3: same content as v2 but blocks `[]` |
| `mix` "Mix" | builder, listed | v1: pick `acme-q1` pinned to the v1 wording "Who signs off?", pick `annex-iv-1a`. Owns nothing. |
| `once` "Custom questions: MCAS, 2026-09-25" | builder, unlisted | v1: own `once-q1` "Only here?", pick `acme-q2` |
| `odd` "Odd" | import, listed | v1: pick `acme-q1` with the wording "Hand edited?" (matches no acme version) |

Every fixture row is a plain INSERT (the old triggers refuse only UPDATE and DELETE). The forms'
`created_at` are set explicitly to 2026-09-01, -02, -03, -04 in the table's order, so passes A and B visit
them in that order (this fixes which set versions exist when `once` is mapped).

Cards: project P with versions 1 and 2 in `core.system`; card c1 of version 1 filled with `mix` v1 (answers
`f-acme:q1`, `annex-1:1a`), inserted while version 1 is the latest, then version 2 is added (so c1 is not
the latest); card c2 of version 2 with `form_version_id` NULL and 14 Annex answers.

Then, after the migration:
- `question_set` rows: `annex-iv`, `acme` (retired_at NULL), `once` (retired_at NOT NULL); none for `mix`
  or `odd`.
- `acme` set versions: `acme-v1` (items `acme-q1` "Who signs off?", `acme-q2`), `acme-v2` (items `acme-q1`
  "Who signs off a release?", `acme-q2`), `acme-v3` (the fallback: `acme-v2`'s items with `acme-q1`
  worded "Hand edited?"); acme form v3 was assigned `acme-v2` (same own list as v2), not a new version.
- `questionnaire_version_item`: acme v1 -> `acme-v1` twice; acme v2 and v3 -> `acme-v2`, `acme-v2`,
  `annex-iv-v1`; mix v1 -> `acme-v1` (the highest version with the wording "Who signs off?"),
  `annex-iv-v1`; once v1 -> `once-v1`, `acme-v2` (highest matching); odd v1 -> `acme-v3`.
- The script output contains the NOTICE `made question set version acme-v3 for the wording pinned in form
  version <odd v1 id>`.
- `questionnaire` rows: `annex-iv-default`, `acme`, `mix`, `once` (listed false), `odd`, with the forms'
  names; `questionnaire_version` ids equal the old `form_version` ids and numbers.
- c1's `questionnaire_version_id` is mix v1's id (unchanged value); c2's is NULL.
- For every old form version V, the list `(key, text, citation, required, annex_point, group_label)` in
  position order computed before the migration from the old tables equals the same list computed after
  from `questionnaire_version_item` joined to `question_set_version_item` and `question` (the queries are
  written once in the test and run into temp tables before and after).
- Tests: `test/db/twoLevelForms.db.test.ts` (DB).

**T9. The migration changes no history and trips no card trigger.**
- In the T8 script, the md5 digests of every row (as JSON, minus the renamed column) of `qualification`,
  `qualification_answer`, `qualification_risk`, `knowledge_graph`, `card_component`, taken before and
  after, are equal; c1 (not the latest) is untouched and the migration did not raise
  `is of a version that is not the latest`.
- Given the migration run on a DB whose builtin form version lacks one of its 14 rows (the script, after
  the revert of T8, drops `form_version_question_is_append_only` and deletes one row), then psql reports
  `the builtin form annex-iv-default v1 is not as seeded`. (That the old tables survive a failed run is the
  transaction's property, not tested further.)
- Given a fixture form whose description is 600 characters, then the migration fails (on
  `question_set_description_length` or `questionnaire_description_length`) and nothing is changed
  (**ASSUMED (D29)**: data breaking the new checks aborts; nothing is truncated).
- Tests: `test/db/twoLevelForms.db.test.ts` (DB).

**T10. An Annex IV card exports the same answers and form header as before.**
- Before any other change, the implementer writes
  `test/fixtures/mcas-export-before.json`: `toExport(<the MCAS card built from src/data/examples/mcas.ts as
  a QualificationWithAnswers>, annexDefaultVersion())` from the **current** code, serialised with
  `JSON.stringify(x, null, 2)`. (This is the one fixture written before the change; the plan's first task.)
- After the change, given the same card and the new `annexDefaultVersion()`, when `toExport` runs, then the
  result equals the fixture after mapping, in the fixture, each `form.questions[]` entry's `ownerForm` to
  `ownerSet: "Annex IV"`, `ownerFormId` to `ownerSetId: "annex-iv"` (key order: `key, text, citation,
  required, annexPoint, ownerSet, ownerSetId, ownerBuiltin`); every other byte (answers, their order,
  `form.name`, `form.version`, metadata, risks) is equal.
- Tests: `test/unit/annexIdentity.test.ts` (unit).

**T11. Owner keys do not change the graph or the view.**
- Given `services/ontology/examples/mcas.qualification.json` with a `form` whose questions carry the old
  keys (`ownerForm`, `ownerFormId`), and the same with the new keys (`ownerSet`, `ownerSetId`), when
  `/build` runs for each, then `graph_digest`, the Turtle, and the whole `view` (including `coverage` and
  `additionalDocumentation`) are equal.
- Given a custom payload with two sets (one untagged question each, answered), then both key styles give
  the same `coverage.forms` and `additionalDocumentation`.
- Tests: `services/ontology/tests/test_owner_set_keys.py` (pytest, ontology).

### B. Question-set editor

**T12. `parseSetDraft`.**
- `SetDraft = { name: string; description?: string; questions: Array<{ questionId?: string; text: string;
  citation: string; required: boolean; annexPoint: AnnexPointId | null }> }`. Never throws; returns
  `{ok: true, value}` (name, description, text, citation trimmed) or `{ok: false, error}` with, in this
  order of checks: shape wrong: `The question set could not be read.`; blank name: `Give the question set a
  name.`; over 120: `A question set name is at most 120 characters.`; equal case-insensitively to one of
  `takenNames`: `A question set called <name> already exists.`; description over 500: `A description is
  at most 500 characters.`; zero questions: `A question set needs at least one question.`
  (**ASSUMED (D18)**); over 200: `A question set has at most 200 questions.`; per question `<n>` (1-based):
  blank text `Question <n> has no text.`, over 2000 `Question <n> is longer than 2000 characters.`,
  citation over 200 `The citation of question <n> is longer than 200 characters.`, point outside the 14
  `Question <n> names an Annex IV point that does not exist.`, a `questionId` already seen `Question <n> is
  already in the question set.`
- Tests: `test/unit/questionSetDraft.test.ts` (unit).

**T13. `sameSetContent`.**
- True exactly when the draft has as many questions as `latest`, and at every index the draft question has
  a `questionId` equal to `latest.questions[i].questionId` and equal `text`, `citation`, `required`,
  `annexPoint`. A question without `questionId` (new) is always a change. Name and description are not
  content.
- Tests: `test/unit/questionSetDraft.test.ts` (unit).

**T14. Creating a set.**
- Given `QuestionSetService.saveDraft(draft, {origin: "builder", createdBy: "alice"})` with no `setId` and
  a draft of questions "A" (citation "§1", required, `2a`) and "B" (optional, untagged), with ids from
  `newId` = `s1`, ... , then one transaction writes: `question_set` (`id` from `newId`, the draft's name and
  description, `origin`, `created_by = "alice"`), questions `s-<setId>:q1`, `s-<setId>:q2`, set version 1
  (`created_by = "alice"`) with items at positions 0 and 1, `group_label` null; the result is
  `{ok: true, setId, versionId, number: 1, created: true}`.
- Given a name taken by a non-retired set, then `{ok: false, error: "A question set called <name> already
  exists."}`; the names of retired sets are not taken. A unique-index race (Prisma `P2002` on insert of a
  new set) maps to the same message.
- Tests: `test/unit/QuestionSetService.test.ts` (unit, fake store).

**T15. Editing a set makes its next version; a no-op save makes none.**
- Given set S at v2 with q1 "A", q2 "B", when saved with q1 reworded "A2", q2 removed, a new question "C"
  appended, and q1 moved after "C", then v3 exists with items C (`s-S:q3`, the next local number: max over
  every question S owns, never reused), q1 "A2"; v2 is unchanged; q2's identity row still exists; the
  result has `created: true, number: 3`.
- Given the draft equals v2 (`sameSetContent`), then no row is written and the result is
  `{ok: true, setId: S, versionId: <v2 id>, number: 2, created: false}`.
- Given a question id that belongs to another set: `Question <n> belongs to another question set.`; an
  unknown question id: `Question <n> no longer exists.`
- Given S builtin, retired or unknown: `{ok: false, error: "That question set cannot be changed."}`, and
  `/question-sets/<S>/edit` answers 404 (`notFound()`).
- Given two concurrent saves computing the same number (Prisma `P2002` on the version insert):
  `This question set was saved by someone else meanwhile. Reload it and save again.`
- An existing question keeps its stored `group_label` in the new version (so a set imported with group
  labels keeps them); a new question's is null (**ASSUMED (D19)**: group labels are not editable).
- The name is fixed at creation: the draft's name is ignored when `setId` is given; the description is
  fixed too (**ASSUMED (D21)**).
- Tests: `test/unit/QuestionSetService.test.ts` (unit).

**T16. The set editor's state.**
- `SetEditorState = { setId: string | null; name: string; description: string; rows: SetRow[]; origin:
  "builder" | "import"; alsoQuestionnaire: boolean; nextRow: number }`, `SetRow = { rowKey: string;
  questionId?: string; text; citation; required; annexPoint; groupLabel: string | null }`.
- Actions: `add {values}` (appends a row without `questionId`, `groupLabel` null), `edit {index, values}`
  (in place, keeps `questionId` and `groupLabel`), `move {from, to}` (as 01 R18, out of range is a no-op),
  `remove {index}`, `setName`, `setDescription`, `toggleAlsoQuestionnaire`. The reducer never mutates its
  input.
- `initialSetEditorState({edit: ResolvedSetVersion})` opens every question as a row with its id and
  wording; `{rows, name, origin: "import"}` opens imported rows without ids.
- `toSetDraft(state)` gives `{name, description, questions}` without row keys or group labels.
- Tests: `test/unit/setEditorState.test.ts` (unit).

**T17. The set editor component.**
- Given `/question-sets/new`, then the page is `<main className="qualify-page qualify-page--form
  qf-forms-page">` with crumb `← Question sets` (to `/p/<project>/question-sets`), heading `New question
  set`, inputs `Name` (maxLength 120) and `Description` (textarea, maxLength 500), the list `ol.qf-builder-rows`
  of rows (position, text, citation chip, Annex point chip showing its citation, `Required`/`Optional` tag,
  `Move <first 40 chars> up`/`down` buttons as 01 R18, `Edit`, `Remove`), the button `+ New question`, and
  the footer button `Save question set`.
- `+ New question` opens the 01 R19 editor (Question, Citation with placeholder `e.g. Acme AI Policy
  §4.2`, `Answers Annex IV point` select with `None` plus the 14 by citation, `Required` checked); `Save
  question` appends; `Edit` reopens it on the row; `Cancel` closes it.
- Given `/question-sets/<S>/edit`, then the heading is `Edit <name>`, the name and description show as
  text, not inputs, the intro reads `v<N> is the latest version. Saving makes v<N+1>; questionnaires pinned
  to earlier versions keep them.`, and the footer button reads `Save as v<N+1>`.
- Pressing the save button calls `saveQuestionSet(project, JSON.stringify(toSetDraft(state)), setId?,
  {origin, alsoQuestionnaire})`; an `{error}` shows in `div.error` above the footer.
- There is no `Use once` button and no block checkbox in the set editor.
- Tests: `test/unit/QuestionSetEditor.test.tsx` (component).

**T18. `saveQuestionSet` and `retireQuestionSet` actions.**
- `saveQuestionSet(project, draftJson, setId?, opts?: {origin?: "builder" | "import"; alsoQuestionnaire?:
  boolean})`: JSON that does not parse: `{error: "The question set could not be read."}`; else
  `parseSetDraft`, then `questionSetService.saveDraft(draft, {setId, origin, createdBy: await callerName(),
  alsoQuestionnaire})`; on success `redirect("/p/<project>/question-sets/<setId>?version=<n>")`, with
  `&unchanged=1` appended when `created` is false.
- `retireQuestionSet(project, setId)`: `questionSetService.retire(setId)`; builtin: `{error: "Annex IV
  cannot be retired."}`; unknown or already retired: `{error: "That question set cannot be retired."}`;
  success redirects to `/p/<project>/question-sets`.
- Both files start with `"use server"`; the service is never given the project (06 R47).
- Tests: `test/unit/questionSetActions.test.ts` (unit, services and `callerName` mocked).

**T19. Retiring a set.**
- Given S used by questionnaire Q's v1, when `retire(S)` runs, then `retired_at` is set to `now()`; Q v1
  still resolves with S's wording; `groups()` still returns S with `retired: true` (for update detection)
  but the builder shows no chip for it (T27); `list({retired: false})` omits it, `list({retired: true})`
  lists it; `saveDraft` with `setId = S` refuses (T15).
- Tests: `test/unit/QuestionSetService.test.ts` (unit).

**T20. The question sets page.**
- Given sets "Annex IV" (builtin), "Zeta" and "Acme AI policy", then `/p/<project>/question-sets` renders
  `<main className="qualify-page qualify-page--form qf-forms-page">`, `h1` `Question sets`, an intro
  containing exactly `Questions are written here. Questionnaires pick them.`, header links `+ New question
  set` (primary, to `.../question-sets/new`) and `Import question set` (ghost), and a `table.qf-forms-table`
  with columns `Question set`, `Version`, `Questions`, `Made by`, `Saved by`, and a hidden `Actions`; rows
  in the order Annex IV, then by name ignoring case; Annex IV's name cell has `span.qf-tag` `built in`.
- `Saved by` reads `<created_by of the latest version>, <YYYY-MM-DD of its created_at in UTC>`
  (e.g. `system, 2026-09-25`).
- Each row's actions, in order: `Open` (to `/question-sets/<id>`), `Edit` (not for builtin), `Export CSV`
  and `Export Markdown` (download links to `/question-sets/<id>/export?format=csv|md&version=<N>`, with the
  base path, as 06 R58), `Retire` (a `RetireButton`, not for builtin).
- `?retired=1` lists only retired sets, with a `Retired` column (`YYYY-MM-DD`) instead of `Saved by`, and
  only `Open`, `Export CSV`, `Export Markdown`; a link `Show retired question sets` / `Show current question
  sets` toggles.
- Tests: `test/unit/QuestionSetsPage.test.tsx` (component; the server component is awaited with mocked
  `questionSetService`, as `FormsPage.test.tsx` did).

**T21. One set's page shows who and when.**
- Given S with v1 (by `alice`) and v2 (by `bob`), then `/question-sets/<S>` shows `h1` S's name, its
  description, a list `ol.qf-set-versions` with one `li` per version, newest first, reading
  `v<n> · <created_by> · <YYYY-MM-DD>` and linking `?version=<n>`; the shown version (latest by default,
  `?version=1` for v1) lists its questions as the set editor rows do, without buttons; `Edit` (hidden for
  builtin or retired) and the two export links for the shown version. `?version=<unknown>` answers 404.
- `?unchanged=1` shows `p.qf-prefilled` `No changes: still v<N>.`
- Tests: `test/unit/QuestionSetPage.test.tsx` (component).

### C. Questionnaire builder

**T22. `parseQuestionnaireDraft`.**
- `QuestionnaireDraft = { name: string; description?: string; blocks: FormBlock[]; items: Array<{
  setVersionId: string; questionId: string }> }`. Messages, in check order: shape: `The questionnaire could
  not be read.`; blank name `Give the questionnaire a name.`; over 120 `A questionnaire name is at most
  120 characters.`; taken `A questionnaire called <name> already exists.`; description over 500 `A
  description is at most 500 characters.`; unknown block `<id> is not a part of the questionnaire.`;
  duplicate block `<id> is in the questionnaire twice.`; over 200 items `A questionnaire has at most 200
  questions.`; a `questionId` seen before `Question <n> is already in the questionnaire.` Zero items is
  valid (01 A7 kept).
- An item carries no wording: extra keys (text, citation) are dropped, never read.
- Tests: `test/unit/questionnaireDraft.test.ts` (unit).

**T23. `sameQuestionnaireContent`.**
- True exactly when the blocks are equal as sets and the items are the same `(setVersionId, questionId)`
  pairs in the same order. So the same question pinned to another set version is a change, even with
  identical wording.
- Tests: `test/unit/questionnaireDraft.test.ts` (unit).

**T24. Saving a questionnaire never authors a question.**
- Given `QuestionnaireService.saveDraft(draft, {listed: true, origin: "builder", createdBy: "alice"})`
  with no id, then one transaction writes a `questionnaire`, version 1 (`created_by = "alice"`, blocks in
  `FORM_BLOCKS` order) and one item per draft item, position = index; no row is written to `question`,
  `question_set`, `question_set_version` or `question_set_version_item`.
- Given an item whose `(setVersionId, questionId)` is not a set item: `Question <n> no longer exists.`
- Given `questionnaireId` of a builtin, unlisted, retired or unknown questionnaire: `That questionnaire
  cannot be changed.`; given a draft equal to the latest version (T23): `created: false`, no row; else the
  next number; `P2002` on the version: `This questionnaire was saved by someone else meanwhile. Reload it
  and save again.`; `P2002` on a new questionnaire: `A questionnaire called <name> already exists.`
- `listed: false` (use once): the name is `useOnceFormName(systemName, now(), <every questionnaire name>)`
  whatever the draft says (06 R67, R68 carried over).
- The service has no method that takes a project (06 R47).
- Tests: `test/unit/QuestionnaireService.test.ts` (unit, fake store).

**T25. Resolving a questionnaire version renders the pinned wording.**
- Given set S v1 with q1 "A" and v2 with q1 "B", and questionnaire Q v1 pinning q1 to S v1, when
  `resolve(<Q v1 id>)` runs, then the question has text "A", `setVersionId = <S v1>`, `setVersionNumber =
  1`, `setName` = S's name, and `key` `s-S:q1`; after S v3 rewords q1 again, Q v1 still resolves to "A".
- `resolve(null)` is `annexDefaultVersion()` without calling the repository; an unknown id is null; a
  retired questionnaire's version still resolves (with `retired: true`).
- Tests: `test/unit/QuestionnaireService.test.ts` (unit).

**T26. `updatesAvailable`.**
- `SetGroup = { setId; setName; versionId; versionNumber; retired: boolean; questions: ResolvedQuestion[] }`
  (a set's latest version). `updatesAvailable(rows: BuilderRow[], groups: SetGroup[]): Record<number,
  Update>` keyed by row index, where `Update = { kind: "reworded"; question: ResolvedQuestion; versionId:
  string; versionNumber: number } | { kind: "removed"; setName: string; versionNumber: number }`.
- A pick row pinned to `(setVersionId, questionId)` of set S is listed when the group of S has a
  `versionId` different from the pin and: the question is absent from the group (`removed`), or present
  with any of `text`, `citation`, `required`, `annexPoint`, `groupLabel` different from the pinned wording
  (`reworded`). Not listed: same wording (the pin is never bumped silently, **ASSUMED (D13)**); a set
  missing from `groups`; questions a newer set version added (they were never picked). Retired groups
  count.
- Pure: rows and groups are not changed.
- Tests: `test/unit/formLibrary.test.ts` (unit; its `sourceUpdates` tests are replaced by these).

**T27. The builder's library column selects question-set versions.**
- The builder is `QuestionnaireBuilder.tsx` with props `{project, groups: SetGroup[], initial:
  BuilderInit}`. The toolbar holds `fieldset.qf-builder-forms` with legend `Select question sets` and one
  checkbox chip `label.qf-builder-formchip` per non-retired group, in the order Annex IV, then by name,
  reading `<set name>` then `v<N> · <count> questions` (`1 question` for one) (**ASSUMED (D14)**: a chip is
  the set's latest version; an older version cannot be picked).
- With none selected: `p.qf-builder-prompt` `Select one or more question sets to see their questions.`
- Selecting set S (`{type: "selectSet", group: S}`) ticks every question of S not already ticked, appended
  in S's order, each a pick pinned to S's latest `versionId` and marked `viaSetId = S`; S's group appears
  under the ones selected before it. Unselecting (`deselectSet`) removes S's group and every pick with
  `viaSetId = S`. Ticking and unticking inside a group, and the placement rule of a re-tick, are 06 R76 to
  R78 with "set" for "form". Search (`Search questions`) filters within the selected groups
  (`filterLibrary`, unchanged).
- Tests: `test/unit/builderState.test.ts` (unit), `test/unit/QuestionnaireBuilder.test.tsx` (component).

**T28. The builder's questionnaire column: locked identity, blocks, picks only.**
- The right column (`section[aria-label="Your questionnaire"]`) has, for a new questionnaire, the input
  `Questionnaire name` (maxLength 120); for an existing one, the name as `h2`; the line `Always included:
  System name, Version, Company (provider)` with no control (06 B5 markup kept); one checkbox per block
  (01 R21); `h3` `Questions (<n>)`; and the rows.
- Each row shows position, text, citation chip, `span.qf-builder-owner` `<set name> v<N>` (the pinned set
  version), overlap chip (01 R23, unchanged), `Required`/`Optional`, `Move ... up`/`down`, and `Remove`.
  There is **no** `Edit` button on any row and **no** `+ New question` button anywhere in the builder;
  instead `p.qf-builder-author` reads `Questions are written in question sets.` followed by the link `Write
  a question set` to `/p/<project>/question-sets/new`.
- The empty hint reads `No questions yet. Select a question set in the library.`
- The reducer has no `addOwn`, `edit` or copy action; `BuilderRow` is only `{rowKey, kind: "pick",
  questionId, setVersionId, source: ResolvedQuestion, viaSetId?}`.
- Tests: `test/unit/builderState.test.ts` (unit), `test/unit/QuestionnaireBuilder.test.tsx` (component).

**T29. "Update available" and accepting it.**
- A row listed by `updatesAvailable` shows, in one `div.qf-builder-update`: `span.qf-tag.qf-tag--notice`
  `Update available`, then for `reworded` `p.qf-new-wording` `<set name> v<M> words it: <new text>` and the
  button `Accept update` (`aria-label` `Accept the update of <first 40 characters of the pinned text>`);
  for `removed` `p.qf-new-wording` `Removed from <set name> v<M>.` and the button `Remove from
  questionnaire` (same aria pattern with `Remove`).
- `Accept update` dispatches `{type: "acceptUpdate", index, question, setVersionId}`: the row's `source`
  becomes the new question and `setVersionId` the new version; the box disappears. On a row that is not
  there, the state is returned unchanged; the reducer never mutates.
- `Remove from questionnaire` dispatches `remove {index}`.
- A header button `Accept all updates` (shown only when at least one `reworded` update exists) accepts every
  `reworded` one in one action `acceptAllUpdates {updates}`; `removed` ones stay for the person to decide.
- Saving after accepting makes the next questionnaire version (T23: the pin changed); cards filled with
  earlier versions keep their wording (T25).
- Tests: `test/unit/builderState.test.ts`, `test/unit/QuestionnaireBuilder.test.tsx`.

**T30. Save, use once.**
- Footer: `Use once` (ghost) and `Save questionnaire` (new) or `Save as v<N+1>` (existing).
- `saveQuestionnaire(project, draftJson, questionnaireId?, origin?)`: `parseQuestionnaireDraft`, then
  `questionnaireService.saveDraft(draft, {questionnaireId, listed: true, origin, createdBy: await
  callerName()})`, then `redirect("/p/<project>/system/edit?questionnaire=<id>")`. Unparseable JSON:
  `{error: "The questionnaire could not be read."}`.
- `useQuestionnaireOnce(project, draftJson, origin?)`: system name from `platformClient.latestVersion(project)`
  (`name`), else the project (06 R68, B5); `saveDraft(draft, {listed: false, origin, createdBy,
  systemName})`; `redirect("/p/<project>/system/edit?questionnaireVersion=<versionId>")`.
- `retireQuestionnaire(project, id)`: builtin `{error: "The Annex IV default cannot be retired."}`;
  unknown, unlisted or already retired `{error: "That questionnaire cannot be retired."}`; success
  redirects to `/p/<project>/questionnaires`.
- The actions file exports exactly `saveQuestionnaire`, `useQuestionnaireOnce`, `retireQuestionnaire` and
  reads no `admin` flag (06 R44, R73 carried over).
- Tests: `test/unit/questionnaireActions.test.ts` (unit).

**T31. Where the builder opens.**
- `/questionnaires/new`: nothing selected, all 9 blocks, origin `builder`.
- `/questionnaires/new?from=<Q>`: the rows are Q's latest items as picks pinned to the same set versions
  as Q (never re-pinned to newer ones), Q's blocks, and `selected` = the sets of those items in first
  appearance order, each pick's `viaSetId` its set. An unknown or retired Q opens the empty builder.
- `/questionnaires/<Q>/edit`: the same rows, selection and blocks from Q's latest version, the name shown
  read-only; 404 (`notFound()`) for builtin, unlisted, retired or unknown.
- An import by reference (T53) opens with the resolved rows, their sets selected, the file's blocks and
  name, origin `import`.
- Tests: `test/unit/builderState.test.ts` (unit), `test/unit/QuestionnaireBuilder.test.tsx`,
  `test/unit/questionnaireActions.test.ts` (the 404 cases, as the old R6 edit-page tests).

**T32. Wide layout and the design pass are kept.**
- `/questionnaires/new` and `/questionnaires/<Q>/edit` render `<main className="qualify-page
  qualify-page--wide qf-forms-page">`; `/questionnaires` and `/question-sets*` render `qualify-page
  qualify-page--form qf-forms-page`; the import page is `--form` for upload and preview, `--wide` once the
  builder mounts (06 R74). The builder root is `div.qualify-form.qf-builder` with the two sections as its
  only children (10-ui-plan B1). The CSS rules pinned by `formsLayout.test.tsx` B2, B3, P4 and
  `widePage.test.ts` stay.
- Tests: `test/unit/formsLayout.test.tsx` (component, paths updated), `test/unit/widePage.test.ts` (unit,
  paths updated).

**T33. The builder state stays pure and thin.**
- `BuilderState = { questionnaireId: string | null; name; description; blocks; rows: BuilderRow[]; origin:
  "builder" | "import"; selected: string[] /* set ids */; nextRow }`. `toQuestionnaireDraft(state)` gives
  `{name, description, blocks (FORM_BLOCKS order), items: [{setVersionId, questionId}]}`; neither
  `selected` nor `viaSetId` travels. Every action returns a new state and never mutates its input.
- Tests: `test/unit/builderState.test.ts` (unit).

**T34. The questionnaires page.**
- `/p/<project>/questionnaires`: `h1` `Questionnaires`; intro containing exactly `A questionnaire is what
  an AI card is filled with. Every project on this install sees the same questionnaires. A new AI card
  starts with the Annex IV default.`; header links `+ New questionnaire` (primary), `Import questionnaire`
  (ghost), `Question sets` (ghost, to `/p/<project>/question-sets`); `table.qf-forms-table` with columns
  `Questionnaire`, `Version`, `Questions`, `Made by`, `Saved by`, hidden `Actions`.
- Rows: Annex IV default first with `span.qf-tag.qf-tag--default` `default`, then by name ignoring case;
  only listed, non-retired questionnaires. A row whose latest version has at least one update (T26 applied
  to its items against `questionSetService.groups()`) carries `span.qf-tag.qf-tag--notice` `update
  available`.
- Actions, in order: `Start from` (`/questionnaires/new?from=<id>`), `Edit` (not builtin), `Export`
  (`/questionnaires/<id>/export?format=json&version=<N>`), `Export self-contained` (`...&bundle=self-contained`),
  `Retire` (not builtin). `?retired=1` as T20.
- No `Set as default` anywhere (06 R44 kept).
- Tests: `test/unit/QuestionnairesPage.test.tsx` (component).

**T35. Retiring a questionnaire.**
- Given Q used by a card, when retired, then the card still renders Q's version; Q leaves the list, the
  chooser and `Start from`; `/questionnaires/<Q>/edit` is 404; `saveDraft` with Q's id refuses.
- Tests: `test/unit/QuestionnaireService.test.ts` (unit).

### D. Chooser and default questionnaire

**T36. "Which questionnaire?"**
- `FormChooser` renders `legend` `Which questionnaire?`, one radio per option (listed, non-retired
  questionnaires, library order): `<name>`, `v<N>`, `<Q> questions`; the `default` tag on Annex IV default
  only; links `+ New questionnaire` (`/p/<project>/questionnaires/new`) and `Import questionnaire`
  (`/p/<project>/questionnaires/import`); button `Continue`, which goes to
  `/p/<project>/system/edit?<param>=<encodeURIComponent(id)>` with `param` `questionnaire` or
  `questionnaireVersion`.
- An unknown questionnaire or version named in the URL shows `That questionnaire was not found.` in
  `div.error`.
- Tests: `test/unit/FormChooser.test.tsx` (component).

**T37. `preselect`: the default for a first card, the exact previous version after that.**
- `preselect(options: {questionnaireId; versionId /* latest */}[], from: {fromVersionId: string | null}):
  ChooserPick | null`, `ChooserPick = {param: "questionnaire" | "questionnaireVersion"; id: string}`.
- No previous card (`fromVersionId` null): `{questionnaire, "annex-iv-default"}` when that option exists,
  else the first option, else null.
- A previous card filled with version P: when some option's latest `versionId` is P, `{questionnaire,
  <that id>}`; otherwise (P is an older version, a use-once version, or of a retired questionnaire)
  `{questionnaireVersion, P}`. A legacy card has P = `annex-iv-default-v1`, the latest of the default, so
  `{questionnaire, "annex-iv-default"}`. A card never moves to a newer version by itself
  (**ASSUMED (D11)**).
- Tests: `test/unit/formChooser.test.ts` (unit).

**T38. The chooser offers the previous version and the newer one.**
- Given the latest card v4 filled with P, and P is not the latest version of a listed, non-retired
  questionnaire, then the first option is `Same questionnaire as v4 (<P's name> v<k>)` with value
  `questionnaireVersion:P`, checked. When P is an older version of listed questionnaire Q, Q's option also
  carries `span.qf-tag` `update available`. When P is Q's latest, Q's option carries `same as v4` (06
  behaviour kept) and no extra option.
- A card filled with a retired questionnaire's version is offered again the same way (**ASSUMED (D10)**).
- Tests: `test/unit/FormChooser.test.tsx` (component), `test/unit/editSystemPage.test.tsx` (component).

**T39. URL parameters.**
- `pickQuestionnaireParams({example, questionnaire, questionnaireVersion, form, formVersion})`, empty
  strings absent: a known `example` wins (`{lookup: "example"}`); else `questionnaireVersion`, else
  `formVersion` (alias), else `questionnaire`, else `form` (alias), each `{lookup: "version" | "latest", id}`;
  else `{lookup: "none"}`. An unknown version never falls back to a questionnaire parameter (06 R71 rule
  kept).
- The edit page resolves `version` through `questionnaireService.resolve`, `latest` through
  `latestVersion`; not found shows the chooser with T36's message.
- Tests: `test/unit/formChooser.test.ts` (unit, one case per row), `test/unit/editSystemPage.test.tsx`.

### E. Cards

**T40. The card form renders the pinned wording and records the version.**
- `QualifyForm` takes `form: ResolvedQuestionnaireVersion` and renders as 01 R9 with the group heading
  `groupLabel ?? setName` (a new heading whenever it changes, so a questionnaire mixing sets shows each
  set's name above its run of questions) and the hidden input `questionnaireVersionId`.
- `QualificationService.createFromForm` reads `questionnaireVersionId` (else `formVersionId`, else the
  default), loads it server side (`questionnaireService.resolve`), refuses an unknown one with `The
  questionnaire this was filled with no longer exists. Reload the page.` before calling the platform, and
  stores `questionnaireVersionId`.
- `AnsweredForm` renders the card's version the same way.
- Given the default version, the rendered form's fields, names, order and headings equal today's (the
  existing `formPrefill`, `QualifyFormBlocks`, `AnsweredForm` tests pass with only the support builders'
  field names changed).
- Tests: `test/unit/QualifyFormBlocks.test.tsx`, `test/unit/AnsweredForm.test.tsx` (component, existing),
  `test/unit/QualificationService.forms.test.ts` (unit, existing, updated).

**T41. Moving a card to another questionnaire version.**
- `rewordedSince(from: ResolvedQuestionnaireVersion, to: ResolvedQuestionnaireVersion): Record<string,
  string>` maps the `field` of every question of `to` whose `key` is also in `from` and whose `text`
  differs (exact string) to `from`'s text (**ASSUMED (D12)**: text only).
- `droppedAnswers(answers: Record<string, string>, to)`: the number of non-blank entries whose field is not
  a question field of `to`.
- `moveNotice({from, to, cardNumber, answers})`: null when `from.versionId === to.versionId`; else exactly
  `Moving from <from name> v<k> to <to name> v<m>. Answers are carried over by question.`, then
  ` <d> answer to a question this version does not ask will not be carried over.` (d = 1) or
  ` <d> answers to questions this version does not ask will not be carried over.` (d > 1), then
  ` <c> reworded question is marked for review.` (c = 1) or ` <c> reworded questions are marked for
  review.` (c > 1), where c counts the reworded fields whose carried answer is non-blank.
- The edit page, given a previous card filled with P and a chosen version V != P, passes `previous` (P
  resolved) and `cardNumber` to `QualifyForm`, which shows `p.qf-moving` with the notice in the header and,
  under the label of each reworded question with a non-blank carried answer, `p.qf-wording-changed`
  `Reworded since v<cardNumber>. Previous wording: <old text>`. Answers are carried by field
  (`cardAsFormStart`, unchanged), so by `(scope, localId)`.
- Saving makes the next card version filled with V (existing card versioning); the previous card is not
  changed (the database refuses it anyway). The flag is not stored.
- Tests: `test/unit/moveCard.test.ts` (unit), `test/unit/QualifyFormMove.test.tsx` (component),
  `test/unit/QualificationService.forms.test.ts` (unit: the new card stores V's id, and the repository's
  update is never called for the previous card).

**T42. The questionnaire line on the card and edit pages.**
- `FormLine` renders `p.qf-row-form`: `span.qf-row-form-name` `Questionnaire: <name> v<N>`, then
  `span.qf-row-form-sep` ` · ` separated links `JSON`, `CSV`, `Markdown` exporting that exact version
  (`/p/<project>/questionnaires/<id>/export?format=json|csv|md&version=<N>`, base path prefixed, `download`,
  `aria-label` `Export <name> v<N> as JSON|CSV|Markdown`). A legacy card reads `Questionnaire: Annex IV
  default v1`.
- With prop `newer: {versionId, versionNumber}` (given by the card page only for the current card, when
  `newerVersion(card version, latest of its questionnaire)` says so: the questionnaire is listed, not
  retired, and its latest number is higher), it also renders `p.qf-questionnaire-update` `<name> has a newer
  version, v<M>.` and the link `Move to v<M>` to `/p/<project>/system/edit?questionnaireVersion=<versionId>`
  (**ASSUMED (D27)**).
- Tests: `test/unit/FormLine.test.tsx` (component, existing, updated), `test/unit/moveCard.test.ts`
  (`newerVersion`).

### F. Coverage and "Additional documentation"

**T43. Grouped by question set.**
- `toExport` sends, per `form.questions[]` entry, `{key, text, citation, required, annexPoint, ownerSet:
  setName, ownerSetId: setId, ownerBuiltin: setBuiltin}` (in that key order); `form.name` is the
  questionnaire name, `form.version` its number.
- `coverage.py`: `_owner_key(q)` is `("id", q["ownerSetId"])` when present, else `("id",
  q["ownerFormId"])`, else `("name", q.get("ownerSet", q.get("ownerForm")))`; the name shown is
  `q.get("ownerSet", q.get("ownerForm"))`. The output keys (`forms`, `form`, `additionalDocumentation`) and
  every summary string of 06 R65 are unchanged.
- Given a questionnaire with Annex IV 2a (answered) and two questions of set "Acme AI policy" (one tagged
  2g answered, one untagged answered), then `summary` = `Annex IV coverage: 2 of 14 points; Acme AI policy:
  2 of 2 answered.` and `additionalDocumentation` = one section `{"form": "Acme AI policy", "entries": [the
  untagged one]}`; two sets sharing a name but not an id give two entries and two sections.
- Tests: `services/ontology/tests/test_owner_set_keys.py` (pytest, ontology),
  `test/unit/QualificationExporter.test.ts` (unit, existing, updated keys). Every existing
  `test_coverage.py` test passes unmodified (old keys still read).

**T44. The card names its extra sections after the set.**
- Given a view whose `additionalDocumentation` is `[{"form": "Acme AI policy", "entries": [...]}]` (the
  set's name, T43), then `VerticalCard` renders `h3.qf-group` `Additional documentation: Acme AI policy`
  and the entries as today (01 R36 unchanged); the PDF template is unchanged.
- Tests: `test/unit/VerticalCard.test.tsx` (component, existing; one case added with a set name).

**T45. `QuestionSetService.groups()`.**
- Returns one `SetGroup` per set (retired included, `retired` flag set), each the set's latest version
  with its questions in position order (`setVersionId`/`setVersionNumber` of that version), ordered Annex
  IV first, then by name ignoring case. `list({retired})` returns the rows of T20 for non-retired
  (`retired: false`) or retired sets.
- `questionnaires/libraryData.ts` `builderData()` returns `{groups: await questionSetService.groups()}`;
  the new, edit and import pages pass `groups` to the builder, which offers chips only for non-retired ones
  (T27) and uses all of them for `updatesAvailable` and overlap candidates.
- Tests: `test/unit/QuestionSetService.test.ts` (unit).

### G. Export and import

**T46. `QuestionnaireService.chooserOptions()` and `library()`.**
- `library({retired: false})` returns listed questionnaires with `retired_at` NULL, Annex IV default first
  (`isDefault: true`, computed from the constant, never stored), then by name ignoring case; each row
  `{questionnaireId, name, description, origin, builtin, isDefault, versionId, version, questionCount,
  savedBy, savedAt, updates}` where `updates` is the count of T26 updates of its latest version.
  `library({retired: true})` returns listed retired ones. `chooserOptions()` is `library({retired: false})`
  plus `versionIds` (every version id, oldest first).
- Tests: `test/unit/QuestionnaireService.test.ts` (unit).

**T47. Question-set export.**
- `GET /p/<project>/question-sets/<setId>/export?format=csv|md[&version=<n>]`: exactly 06 R57's contract
  (400 `format must be csv or md`, 404 `Not found` for a bad or unknown version or set, the client's
  status and error on failure, 200 with the bytes, `Content-Type`, `Content-Disposition: attachment;
  filename="<filename>"`, `Cache-Control: no-store`), with `FormExportClient.write({name: set name,
  version: set version number, questions})`. Builtin and retired sets export too. The file formats are 06
  R50 to R52 unchanged (so `Annex IV` v1 exports as `annex-iv-v1.csv`).
- Tests: `test/unit/questionSetExportRoute.test.ts` (unit, mocked service and client).

**T48. Questionnaire export.**
- `GET /p/<project>/questionnaires/<id>/export?format=json|csv|md[&bundle=self-contained][&version=<n>]`:
  `format` missing or other: 400 `format must be json, csv or md`; `bundle` present with a value other
  than `self-contained`, or with `csv`/`md`: 400 `bundle applies to json only, and is self-contained`;
  version and unknown ids as T47.
- `json`: `QuestionnaireFileClient.write(<the version as T50's input>, bundle ?? "references")` through
  `POST /questionnaires/export`. `csv`/`md`: the questionnaire's resolved questions flattened into 06 R50/R51
  files with `name` = questionnaire name and `version` = its number (this is what old `/forms/<id>/export`
  links and the card's CSV/Markdown links download; importing such a file makes a question set, T49)
  (**ASSUMED (D23)**).
- Unlisted, retired and the builtin questionnaire export too.
- Tests: `test/unit/questionnaireExportRoute.test.ts` (unit).

**T49. Question-set import (CSV, Markdown, Word).**
- `/question-sets/import` is the old import page moved: file input `accept=".csv,.md,.markdown,.docx"`,
  `readQuestionSetFile` (same contract as `readFormFile`), the preview of 01 R28 and 06 R59 unchanged
  (found line, warnings, one editable row per question with text, citation, Required, Annex point select,
  Remove; `Continue with <M> questions`).
- Confirming mounts the **set editor** (not the builder) in place, with the rows as new questions, the
  name from the file name, origin `import`, and an extra checkbox `Also make a questionnaire with all its
  questions` (unchecked, **ASSUMED (D22)**).
- Saving with the box ticked makes, in the same transaction, the set v1 and a listed questionnaire named as
  the set, origin `import`, all 9 blocks, one item per set question in order pinned to set v1, `created_by`
  the caller; a name taken by a questionnaire refuses the whole save with `A questionnaire called <name>
  already exists.`
- Tests: `test/unit/QuestionSetImport.test.tsx` (component; the old `FormImport.test.tsx` R28 and R59
  cases carried over), `test/unit/QuestionSetService.test.ts` (the `alsoQuestionnaire` transaction).

**T50. The questionnaire file (exact).**
- `write_questionnaire(q: dict, bundle: str) -> ExportedFile` in `prefill/questionnaire_file.py`, pure.
  Input `q = {"name", "description", "version", "blocks", "items": [{"setId", "setName", "setVersion",
  "scope", "localId", "text", "citation", "required", "annexPoint", "groupLabel"}]}`. Output `content` is
  `json.dumps(doc, ensure_ascii=False, indent=2) + "\n"` where `doc` has, in this key order: `"format":
  "aisc-questionnaire"`, `"formatVersion": 1`, `"bundle": "references" | "self-contained"`, `"name"`,
  `"description"`, `"version"`, `"blocks"`, `"items"`; each item has `setId`, `setName`, `setVersion`,
  `scope`, `localId`, and, only for `self-contained`, then `text`, `citation`, `required`, `annexPoint`,
  `groupLabel`. `filename` = `<slug(name)>-v<version>.questionnaire.json` (06 R52's `slug`),
  `content_type` = `application/json; charset=utf-8`.
- Example (references, first item only shown):
  ```json
  {
    "format": "aisc-questionnaire",
    "formatVersion": 1,
    "bundle": "references",
    "name": "Annex IV default",
    "description": "EU AI Act Annex IV points 1 and 2, as 14 questions.",
    "version": 1,
    "blocks": ["description", "targetUseCase", "targetUsers", "intendedDeployers", "targetSystemTags", "sectorTags", "marketFormTags", "localityTags", "risks"],
    "items": [
      {"setId": "annex-iv", "setName": "Annex IV", "setVersion": 1, "scope": "annex-1", "localId": "1a"}
    ]
  }
  ```
  (with `indent=2` every list element is on its own line; the example is compacted for reading; the test
  compares against the exact `json.dumps` output). The self-contained twin of that item adds `"text": "If
  this version replaces an earlier one, ...", "citation": "Annex IV(1)(a)", "required": true,
  "annexPoint": "1a", "groupLabel": "About the system"`. Filename `annex-iv-default-v1.questionnaire.json`.
- `POST /questionnaires/export` (JSON body `{"bundle", "questionnaire": q}`): 200 `{"filename",
  "contentType", "content"}`; 422 `bundle must be references or self-contained`; 422 `item <n> has no
  wording: a self-contained file needs text, citation, required, annexPoint and groupLabel` when bundling
  and a field is missing; 422 `a questionnaire has at most 200 questions`; pydantic's detail for a
  mistyped field.
- Tests: `services/prefill/tests/test_questionnaire_file.py` (pytest, prefill),
  `services/prefill/tests/test_app.py` (extended, `TestQuestionnaireEndpoints`).

**T51. Reading a questionnaire file (exact errors).**
- `read_questionnaire(raw: bytes, filename: str) -> dict` raises `QuestionnaireFileError(detail)`; the
  endpoint `POST /questionnaires/import` (multipart `file`) turns it into 422, a file over
  `PREFILL_MAX_BYTES` into 413. Checks in order, with these details: extension not `.json`: `<ext> is not a
  questionnaire file format: json`; empty: `the file is empty`; not UTF-8 JSON: `this file is not JSON`; not
  an object: `a questionnaire file is a JSON object`; `format`/`formatVersion` not `aisc-questionnaire`/`1`:
  `this is not a questionnaire file: format must be aisc-questionnaire, formatVersion 1`; bundle: `bundle
  must be references or self-contained`; name (whitespace collapsed) blank: `the questionnaire has no
  name`, over 120: `the questionnaire name is longer than 120 characters`; description (optional, default
  "") over 500: `the description is longer than 500 characters`; version (optional) not a positive integer:
  `version must be a positive whole number`; blocks not a list of block ids: `<x> is not a block`,
  duplicate: `<x> is listed twice`; items over 200: `a questionnaire has at most 200 questions`; item `<n>`
  (1-based): `item <n> has no setId`, `item <n> has no setVersion` (positive integer), `item <n> has no valid
  scope and localId` (the DB regexes), `item <n> is in the file twice` (same scope and localId); for
  self-contained: `item <n>: text must be 1 to 2000 characters` (after collapse), `item <n>: citation must be
  at most 200 characters`, `item <n>: required must be true or false`, `item <n>: annexPoint must be one of
  the 14 Annex IV points or null`, `item <n>: groupLabel must be text of at most 120 characters or null`.
- 200 body: the normalised document (collapsed name, description default "", `setName` default "",
  wording keys dropped for a references file).
- Tests: `services/prefill/tests/test_questionnaire_file.py`, `services/prefill/tests/test_app.py`.

**T52. The questionnaire file round-trips.**
- For `bundle` in both values, `read_questionnaire(write_questionnaire(q, b).content.encode(), filename)`
  equals `q` normalised (for references: without wording keys) for: the Annex IV default (14 items with
  group labels); a three-set questionnaire of 200 items with non-ASCII text, `"`, `\`, newlines inside text
  (compared after collapse); zero items and zero blocks.
- Tests: `services/prefill/tests/test_questionnaire_file.py`.

**T53. Importing a reference file.**
- `readQuestionnaireFile(formData)` sends the file to `QuestionnaireFileClient.read`; for a references file,
  `questionnaireService.resolveReferences(items)` looks up each `(setId, setVersion)` and, in it, the
  question `(scope, localId)`.
- All found: the result is `{ok: true, bundle: "references", open: BuilderInit}` and the page mounts the
  builder (T31).
- Anything missing: `{ok: false, error: "This questionnaire refers to questions this install does not
  have. Import its self-contained file, or import those question sets first.", missing: string[]}`, built
  by the pure `missingReferences(items, found)` in item order: once per missing `(setId, setVersion)`:
  `Question set "<setName, or setId when empty>" (<setId>) v<setVersion> is not on this install.`; per item
  whose set version exists but lacks the question: `<scope>:<localId> is not in question set "<name on
  this install>" v<n>.` Nothing is stored. The page shows `div.error` and `ul.qf-import-missing` with one
  `li` per entry.
- Example: items `annex-iv` v1 `annex-2:2a` (present), `acme` v3 `s-acme:q1` and `s-acme:q2` (no acme v3
  here), `acme` v1 `s-acme:q9` (acme v1 exists without q9) give `["Question set \"Acme AI policy\" (acme)
  v3 is not on this install.", "s-acme:q9 is not in question set \"Acme AI policy\" v1."]`.
- Tests: `test/unit/references.test.ts` (unit), `test/unit/QuestionnaireService.test.ts`,
  `test/unit/QuestionnaireImport.test.tsx` (component).

**T54. Importing a self-contained file.**
- For a self-contained file the page shows `Found <N> questions in <file name>`, the questions (text and
  citation chip, read-only), two inputs `Question set name` (default `<file's name> questions`) and
  `Questionnaire name` (default the file's name), and the button `Create question set and questionnaire`
  (**ASSUMED (D16)**: always a new set, even when the referenced sets exist here).
- `importSelfContained(project, fileJson, setName, questionnaireName)` calls
  `questionnaireService.importSelfContained(file, {setName, questionnaireName, createdBy})`, which in one
  transaction creates a set (origin `import`) with one question per item (`s-<setId>:q1..qN`, item order),
  its v1 with the file's wording (text, citation, required, annexPoint, groupLabel), and a listed
  questionnaire (origin `import`) v1 with the file's blocks and one item per question pinned to that set
  v1. Name errors are T12's and T22's messages. Success redirects to
  `/p/<project>/system/edit?questionnaire=<id>`.
- Round trip: exporting questionnaire Q self-contained and importing it gives a questionnaire whose resolved
  questions equal Q's in `text`, `citation`, `required`, `annexPoint`, `groupLabel` and order, with equal
  blocks; identities, set and names differ.
- Tests: `test/unit/QuestionnaireService.test.ts` (unit), `test/unit/QuestionnaireImport.test.tsx`
  (component), `test/unit/QuestionnaireFileClient.test.ts` (unit, fake fetch: the 503 `Questionnaire files
  are not available on this install.` when `PREFILL_URL` is unset, 502 `The questionnaire file service
  could not be reached.` when fetch throws, the service's `detail` passed through on 4xx).

### H. Who and when, retire

**T55. `created_by` is the signed-in user.**
- `identityFromToken(token)`: splits a JWT on `.`, base64url-decodes the payload, parses JSON, returns
  the first non-blank string of `preferred_username`, `email`, `sub`, trimmed and cut to 200 characters;
  null for null, a malformed token, or none of the three. No signature check: the middleware has already had
  this token accepted by the platform for this request (**ASSUMED (D4)**).
- `callerName()` = `identityFromToken(await callerToken()) ?? "unknown"`.
- Every save action passes it as `createdBy`; every version row and every new set/questionnaire row
  stores it (T14, T24); the list and set pages show it (T20, T21, T34).
- Tests: `test/unit/callerName.test.ts` (unit), the action tests of T18 and T30.

**T56. The retire button.**
- `RetireButton` props `{name, action: () => Promise<{error?: string} | void>}`: renders the ghost button
  `Retire`; pressing it replaces it with `Retire <name>? Cards and questionnaires that use it keep it.` and
  buttons `Retire` (calls `action`) and `Cancel` (restores); an `{error}` shows in `div.error`. Access: the
  action is a POST, so `may_write` in the current project (**ASSUMED (D9)**: retiring is install-wide and
  any project writer may do it; it is one-way; the builtin rows cannot be retired).
- Tests: `test/unit/RetireButton.test.tsx` (component).

### I. Prefill for custom questionnaires

**T57. The history of a questionnaire.**
- `QuestionnaireService.history(id)` and `QuestionSetService.history(setId)` return `VersionStamp[]`,
  newest first, with `createdAt` as ISO 8601 in UTC; the edit page of a questionnaire shows under its
  heading `p.qf-saved-by` `v<N> saved by <createdBy> on <YYYY-MM-DD>` for the latest version.
- Tests: `test/unit/QuestionnaireService.test.ts`, `test/unit/QuestionSetService.test.ts` (unit),
  `test/unit/questionnaireEditPage.test.tsx` (component: the server page awaited with a mocked service).

**T58. Prefill uses the pinned wording.**
- Given a questionnaire version mixing Annex IV 2a and a set question `s-acme:q1` (text "Who signs off a
  model release?", citation "Acme AI Policy §4.2") pinned to its v1 while the set's v2 rewords it, when
  `useDocumentPrefill` builds the `PrefillClient` form spec, then `questions` holds `{field:
  "q:s-acme:q1", text: <the v1 text>, citation, annexPoint}` and `fields` the identity fields, the
  version's blocks' fields, `"risks"` when included, and every question field (01 R40 unchanged).
- Python is unchanged; 01 R38 to R40 tests pass unmodified.
- Tests: `test/unit/PrefillClient.test.ts`, `test/unit/prefillChoice.test.ts` (unit, existing, extended).

### J. Deployment, routes, header, no model

**T59. The Dockerfile migrates instead of pushing.**
- The last line of `Dockerfile` is exactly
  `CMD ["sh", "-c", "npx prisma migrate deploy && npx next start -p 3000"]`, and the file contains neither
  `db push` nor `accept-data-loss`. Nothing else in the Dockerfile changes (a test compares every other
  line with the committed text, read from a fixture copy taken before the change,
  `test/fixtures/Dockerfile.before`). `DEPLOY.md` line "The container runs `prisma db push` on startup"
  becomes "The container runs `prisma migrate deploy` on startup", plus the backup step of 4.4 and one
  sentence: a database created by `db push` has no migration history; baseline it with `prisma migrate
  resolve --applied <name>` for every migration before the first start.
- The live stack is unaffected: its `qualification-web` overrides the command and `qualification-migrate`
  already runs `migrate deploy` (root `docker-compose.development.yml`).
- Tests: `test/unit/dockerfile.test.ts` (unit).

**T60. The header links both levels.**
- `SiteHeader` with a project: nav `← Back`, `AI system`, `Versions`, `Question sets`
  (`/p/<project>/question-sets`), `Questionnaires` (`/p/<project>/questionnaires`), `Methodology`, in that
  order; without a project neither link (**ASSUMED (D24)**).
- Tests: `test/unit/SiteHeader.test.tsx` (component, existing, updated).

**T61. No model in the new parts.**
- `test/unit/formsNoModel.test.ts` scans every file of `src/domain/forms/`, `src/server/services/QuestionSetService.ts`,
  `QuestionnaireService.ts`, `QuestionnaireFileClient.ts`, `FormExportClient.ts`, `FormImportClient.ts`,
  `src/server/repositories/QuestionSetRepository.ts`, `QuestionnaireRepository.ts`,
  `src/server/access/callerName.ts`, and every file under `src/app/p/[project]/question-sets/`,
  `src/app/p/[project]/questionnaires/`, `src/app/p/[project]/forms/`: none imports `FillerClient` or
  `services/llm`; the only env names read are `PREFILL_URL`, `PLATFORM_URL`, `NEXT_BASE_PATH`,
  `QUALIFICATION_WEB_TO_PREFILL_TOKEN`.
- `questionnaire_file.py` imports only the standard library and `prefill` modules (AST scan).
- Tests: `test/unit/formsNoModel.test.ts` (unit, updated), `services/prefill/tests/test_questionnaire_file.py`.

**T62. Old forms URLs redirect.**
- Each old page calls `permanentRedirect` (308): `/p/<p>/forms` to `/p/<p>/questionnaires`;
  `/forms/new[?from=<id>]` to `/questionnaires/new[?from=<id>]`; `/forms/<id>/edit` to
  `/questionnaires/<id>/edit`; `/forms/import` to `/question-sets/import` (the old page imported question
  files). `GET /forms/<id>/export?<query>` answers 308 with `Location: <basePath>/p/<p>/questionnaires/<id>/export?<the
  same query>` (ids are the same: D1). The edit page keeps reading `?form=`/`?formVersion=` (T39)
  (**ASSUMED (D20)**).
- Tests: `test/unit/formsRedirects.test.ts` (unit, `next/navigation` mocked).

**T63. Forms are install-wide.**
- `QuestionSetService` and `QuestionnaireService` have no public method with a `project` or `projectId`
  parameter and do not mention `projectId`/`project_id`; a set and a questionnaire saved from project a are
  listed, grouped and resolved identically for project b; the list pages for a and b differ only in the
  `/p/<project>/` prefixes (06 R47, R48 carried over).
- Tests: `test/unit/formsDefaultIsFixed.test.ts` (unit, updated), `test/unit/QuestionnairesPage.test.tsx`,
  `test/unit/QuestionSetsPage.test.tsx`.

---

## 7. Error cases (collected)

| Case | Where | Result |
|---|---|---|
| Unknown questionnaire version posted on save | `createFromForm` | `The questionnaire this was filled with no longer exists. Reload the page.`, platform not called |
| Unknown `?questionnaire`/`?questionnaireVersion` (or aliases) | edit page | chooser with `That questionnaire was not found.` |
| Set draft invalid | `saveQuestionSet` | T12 messages |
| Questionnaire draft invalid | `saveQuestionnaire` | T22 messages |
| Edit builtin/retired/unknown set; builtin/unlisted/retired/unknown questionnaire | edit pages | 404 |
| Concurrent save | both services | T15 / T24 messages |
| Reference import with missing set versions or questions | questionnaire import | T53 message and list, nothing stored |
| Questionnaire file malformed | prefill `/questionnaires/import` | 422 with T51 detail; 413 too big |
| Prefill not configured / unreachable | file clients | 503 / 502 messages, never thrown |
| Retire builtin | actions | `Annex IV cannot be retired.` / `The Annex IV default cannot be retired.` |
| Direct SQL update of a version or item | DB | 3.2 messages |
| Migration: builtin not as seeded, a check fails, data breaks a new CHECK | migration | whole transaction rolled back, message of 4.2 |

---

## 8. Superseded items and tests that change deliberately

### 8.1 Requirements of `../form-assembly-2026-09-24/`

| Item | Status | By |
|---|---|---|
| 01 section 3 vocabulary "Form", "Form version", "Question identity ... owned by one form", "Snapshot", "Builtin form" | replaced by section 1 | 1 |
| 01 4.1 to 4.4 (four form models, their constraints, `formVersionId`) | replaced; 090000 text stays on disk, its objects dropped by the new migration | 3, 4 |
| 01 5.1, 5.2 `FormService`, `FormRepository`, `formDraft.ts`, `ResolvedFormVersion` | replaced | 5 |
| 01 5.3 route table | replaced; old routes redirect | 5.4, T62 |
| 01 R1 (seed = default) | kept in substance, new tables | T3 |
| 01 R3 (library) | split into set and questionnaire lists | T20, T34 |
| 01 R5 (keys `f-<form id>:q<n>` minted per form) | new questions are `s-<set id>:q<n>` minted per set; migrated `f-` keys kept | T14, T15 |
| 01 R6 (immutable versions, no-op save, builtin 404) | carried to both levels | T4, T5, T15, T24 |
| 01 R7 (legacy cards unchanged) | re-proved | 4.3, T9 to T11 |
| 01 R8 (chooser) | replaced | T36 to T39 |
| 01 R9 (render; heading `groupLabel ?? ownerFormName`) | heading `groupLabel ?? setName` | T40 |
| 01 R15 (hidden `formVersionId`) | `questionnaireVersionId`, old name accepted | T40 |
| 01 R16 (library groups by owner form) | groups are set versions | T27 |
| 01 R19 ("+ New question" in the builder) | moved to the set editor | T17, T28 |
| 01 R20 (edit a pick makes a copy) | **removed**: a questionnaire never rewords | T28 |
| 01 R22 (save named form or use once; pick/own/copy draft) | split: T12 to T15 (sets), T22 to T24, T30 (questionnaires) | |
| 01 R28 (import preview then builder) | preview then set editor | T49 |
| 01 R30 (export owner fields) | `ownerSet`, `ownerSetId` | T43 |
| 01 R34, R35 (grouping by owner form) | by question set | T43 |
| 01 R36 ("Form: <name> v<N>") | `Questionnaire: <name> v<N>` | T42 |
| 01 R41 (no-model scan list) | extended | T61 |
| 01 section 11 "Renaming, archiving or deleting forms" out of scope | retiring is now in scope; renaming and deleting stay out | T6, T19, T35 |
| 01 section 11 "Recording who created a form" out of scope | now in scope | T55 |
| 06 R43 (default constant) | kept for questionnaires | T34, T37 |
| 06 R44 (nothing sets a default) | kept; action export list renamed | T30 |
| 06 R45 (form table has no `is_default`, `form_builtin_is_the_default`) | form table dropped; builtin CHECKs on the new tables | T5 |
| 06 R46 (preselect previous card's form, its latest version) | previous card's exact version | T37 |
| 06 R47, R48 (install-wide; intro sentence) | kept on new models and pages; intro texts changed | T1, T34, T63 |
| 06 R49 ("Forms" header link) | two links | T60 |
| 06 R57, R58 (form export route, export buttons) | set route T47, questionnaire route T48; buttons T20, T34 | |
| 06 R59 (import Annex select) | kept, in the set import | T49 |
| 06 R60 to R64 (picks pinned to a form version, "Source updated", "Use new wording") | pins to set versions; "Update available", "Accept update" | T23, T25, T26, T29 |
| 06 R66 (legacy "Form:" line) | `Questionnaire: Annex IV default v1` | T42 |
| 06 R68 (use-once form) | use-once questionnaire | T24, T30 |
| 06 R69 (group by owner form id) | by set id (old keys still read) | T43 |
| 06 R71 (`?formVersion` wins over `?form`) | extended with the new names | T39 |
| 06 R73 (no-model scan) | extended | T61 |
| 06 R74 to R80 (wide builder, multi-select of forms) | multi-select of question sets; no own or copy rows | T27, T28, T31 to T33 |
| 06 C2, C4 (own rows and copies survive unselecting; copy vs tick) | void: no own rows or copies | T28 |
| 06 C5 (group lists all a form's questions incl. picks) | a group is a set version's questions | T27 |
| 06 C7 (edit selects owners of picks) | selects the sets of the items | T31 |
| 01 A12 (names fixed) | kept for both levels | T15, 3.2 |
| 01 A13 (builtin read-only) | kept for both builtin rows | T5 |
| 01 A15 (each question once, under its owner) | superseded by T27 | |
| 06 B1 (export through prefill) | kept, and for questionnaire files | 2 |
| 10-ui-plan section 3 (library page), 4.3 (builder markup "Edit", "+ New question") | library page becomes the questionnaires page; the builder loses both | T28, T34 |

### 8.2 Existing tests: deleted and replaced (behaviour changed; each case lives on in the named new file)

| File | Replaced by | Notes |
|---|---|---|
| `test/unit/FormService.test.ts` | `QuestionSetService.test.ts`, `QuestionnaireService.test.ts` | R3, R5, R6, R7, R16, R43, R47, R57, R60 to R62, R68 cases re-expressed on the two services; R20 copy and R22 "own question belongs to another form" cases removed (no copies; T15's "belongs to another question set" replaces the latter); R60 "no latestSnapshot" dropped with `FormService` |
| `test/unit/formDraft.test.ts` | `questionSetDraft.test.ts`, `questionnaireDraft.test.ts` | pick/own/copy kinds gone |
| `test/unit/formActions.test.ts` | `questionSetActions.test.ts`, `questionnaireActions.test.ts` | R42 door tests, R48 redirects, R68 naming, R73 export list carried over |
| `test/unit/FormsPage.test.tsx` | `QuestionnairesPage.test.tsx`, `QuestionSetsPage.test.tsx` | R44 "no Set as default" carried over; R58 actions changed (T20, T34) |
| `test/unit/formExportRoute.test.ts` | `questionSetExportRoute.test.ts`, `questionnaireExportRoute.test.ts`, `formsRedirects.test.ts` | the R57 cases carried to the set route unchanged |
| `test/unit/FormImport.test.tsx` | `QuestionSetImport.test.tsx` | R28 "confirming mounts the builder" becomes "mounts the set editor"; R59 cases unchanged |
| `test/unit/FormBuilder.test.tsx` | `QuestionnaireBuilder.test.tsx` | R19 (+ New question) and R20 (copy) cases move to `QuestionSetEditor.test.tsx` (R19) or are removed (R20); R22 labels `Save questionnaire`; R64 becomes T29; R75 "Select forms" becomes `Select question sets` |
| `test/support/fakeFormStore.ts` | `test/support/fakeQuestionnaireStore.ts` | |
| `test/db/forms.db.test.ts` | `test/db/twoLevelForms.db.test.ts` | R1 seed rows, R6 triggers, R5 answer index, R45 builtin rules and R7 no-history re-expressed on the new tables (T3 to T9); the R7 "revert 090000" recipe becomes T8's revert of the new migration |

### 8.3 Existing tests: kept, changed deliberately (minimal edits, reason given)

| File | Change | Reason |
|---|---|---|
| `test/support/forms.ts` | builders return `ResolvedQuestion`/`ResolvedQuestionnaireVersion` with the new field names (`setId`, `setName`, `setVersionId`, `setVersionNumber`, `setBuiltin`, `questionnaireId`, `questionnaireName`, `description`, `retired`) | type change; every test using it keeps its assertions |
| `test/unit/annexDefaultForm.test.ts` | `annexDefaultVersion()` field names (T3); the two "schema has no default flag" tests (R45, 3.3) replaced by T1; `resolveFormVersionId` renamed `resolveQuestionnaireVersionId` | model removed; texts of 090000 and 120000 still pinned unchanged |
| `test/unit/builderState.test.ts` | R16, R18, R21, R76 to R79 kept with sets; R6/R19 "edit opens own questions as own", R19, R20, R28 "import opens as own", R62 `fromVersionId`, R64 `takeLatest` removed or renamed (`setVersionId`, `acceptUpdate`) | T27 to T33 |
| `test/unit/formLibrary.test.ts` | `filterLibrary`, `overlapHints` tests unchanged; `sourceUpdates` tests replaced by `updatesAvailable` | T26 |
| `test/unit/formChooser.test.ts` | R8 "an older version of a form still starts on that form (its latest version)" flips to "starts on that exact version" (T37); `preselect` signature; `pickFormParams` renamed and extended | D11 |
| `test/unit/FormChooser.test.tsx` | texts `Which questionnaire?`, `+ New questionnaire`, `Import questionnaire`, `That questionnaire was not found.`, `Same questionnaire as v<N> (...)`; hrefs `?questionnaire=` | vocabulary, T36, T38 |
| `test/unit/editSystemPage.test.tsx` | parameter names and messages; A14 cases per T37, T38; new cases for T41 | |
| `test/unit/FormLine.test.tsx` | text `Questionnaire:`, the JSON link, hrefs under `/questionnaires/` | T42 |
| `test/unit/formsLayout.test.tsx` | page paths (`forms/*` to `questionnaires/*`, `question-sets/*`); L tests target the questionnaires page; B6 (editor panel) moves to the set editor; B7 expects `Remove` only (no `Edit`); B8 text `Update available` | T28, T29, T32 |
| `test/unit/widePage.test.ts` | the last test's paths | T32 |
| `test/unit/SiteHeader.test.tsx` | two links instead of `Forms` | T60 |
| `test/unit/formsNoModel.test.ts` | the file list | T61 |
| `test/unit/formsDefaultIsFixed.test.ts` | R44 "actions export exactly saveForm and useFormOnce" becomes T30's list; R47 model names become the seven new models; `setDefault` scans unchanged | T30, T63 |
| `test/unit/QualificationService.forms.test.ts` | posted field `questionnaireVersionId` (one extra case: `formVersionId` still read); stored `questionnaireVersionId`; `startingPoint().fromQuestionnaireVersionId`; the error message | T40 |
| `test/unit/QualificationExporter.test.ts` | owner keys `ownerSet`, `ownerSetId` | T43 |
| `test/unit/FormExportClient.test.ts` | `write` takes `{name, version, questions}` | 5.3 |
| `test/unit/cardSubmission.test.ts`, `formPrefill.test.tsx`, `QualifyFormBlocks.test.tsx`, `AnsweredForm.test.tsx`, `PrefillClient.test.ts`, `prefillChoice.test.ts`, `VerticalCard.test.tsx` | only where they build a resolved version or read the renamed fields | type change |

Unchanged: `useOnceName.test.ts`, `annexPoints.test.ts`, `annexDefaultExportFixture.test.ts`,
`mcasExampleAgrees.test.ts`, `FormImportClient.test.ts`, `projectAccess.test.ts`, `keyQuestions.test.ts`,
`test/db/cardVersions.db.test.ts`, `test/db/cardVersionOfItsProject.db.test.ts`, and every Python test
(ontology, prefill, renderer, agents).

---

## 9. Out of scope

- Renaming or deleting sets, questionnaires, versions or questions; un-retiring.
- Editing a set's or questionnaire's description after creation (D21); editing group labels (D19).
- Picking an older set version in the builder (D14); following a set's latest version automatically.
- Branching, conditional or typed questions; per-question help text.
- Notifying anyone when a set changes (update available shows only in the builder and the questionnaires
  list; the card page shows a newer questionnaire version, T42).
- "Used by" lists (which questionnaires pin a set version).
- Storing the "reworded" review flag on a card (D12).
- Importing a self-contained file into existing sets (D16); merging a reference import with partial matches.
- A database guard against inserting items into an existing version (D26).
- A down migration (D25); baselining a `db push` database automatically.
- Any docker, compose, rebuild or deploy change beyond the Dockerfile line (T59).
- Per-project or per-organisation visibility (06 decision 2).

---

## 10. Assumptions

- **ASSUMED (D1)** Migrated ids: a questionnaire keeps its form's id, a questionnaire version its form
  version's id, a migrated set its owner form's id. Why: no card row needs an UPDATE (the latest-card
  triggers stay untouched), old export links and `?formVersion` keep working, and coverage groups by the
  same id and name.
- **ASSUMED (D2)** Own questions of an unlisted (use-once) form become a set that is created retired, as
  they were never offered in the library (01 A15); the use-once questionnaire keeps working.
- **ASSUMED (D3)** Rows migrated from forms have `created_by = 'unknown'`; builtin rows `system`.
- **ASSUMED (D4)** `created_by` is the token's `preferred_username`, else `email`, else `sub`, decoded
  without a signature check (the platform accepted the token for this request); `unknown` when none.
- **ASSUMED (D5)** New questions are keyed `s-<set id>:q<n>`; questions from before keep `f-<form id>:...`.
- **ASSUMED (D6)** A set version is made per distinct list of a form's own questions, in version order;
  empty lists make none; a form that owns no question gets no set.
- **ASSUMED (D7)** A migrated pick pins the highest-numbered set version with identical wording; no match
  makes a new latest set version (the owner's latest items with that wording), except for Annex IV, which
  aborts.
- **ASSUMED (D8)** The `copied_from_id` lineage is not carried.
- **ASSUMED (D9)** Retiring is one-way, install-wide, allowed to any writer of the current project; the
  builtin rows cannot be retired; a retired name may be reused.
- **ASSUMED (D10)** A card filled with a retired questionnaire's version is offered "Same questionnaire as
  vN" in the chooser.
- **ASSUMED (D11)** The chooser preselects the previous card's exact questionnaire version; a newer one is
  offered, never taken silently.
- **ASSUMED (D12)** "Wording changed" compares question text only, is shown while editing, and is not stored.
- **ASSUMED (D13)** "Update available" covers reworded (any of the five wording fields) or removed picked
  questions; a newer set version with the same wording is no update and does not move the pin.
- **ASSUMED (D14)** The builder offers each non-retired set's latest version only.
- **ASSUMED (D15)** Questionnaire files are JSON (`aisc-questionnaire`, format version 1), written and read
  in Python; references match by `(setId, setVersion, scope, localId)`, never by names.
- **ASSUMED (D16)** A self-contained import always creates a new set, default name `<name> questions`.
- **ASSUMED (D17)** The ontology payload's owner keys become `ownerSet`/`ownerSetId` (old keys still read);
  the view's keys `form`, `forms`, `additionalDocumentation` are kept so card JSON bytes do not change.
- **ASSUMED (D18)** A question set needs at least one question; a questionnaire may have none.
- **ASSUMED (D19)** Group labels are not editable; existing ones are carried to new set versions.
- **ASSUMED (D20)** Old `/forms` pages redirect (308) to the new routes; `?form`, `?formVersion` and the
  posted `formVersionId` stay accepted as aliases.
- **ASSUMED (D21)** Set and questionnaire descriptions are set at creation and not edited in the app.
- **ASSUMED (D22)** A question-set import offers "Also make a questionnaire with all its questions",
  unchecked; the questionnaire is named as the set, listed, with all 9 blocks.
- **ASSUMED (D23)** A questionnaire can also be downloaded as flattened CSV/Markdown (the old form file),
  which imports as a question set.
- **ASSUMED (D24)** The header shows "Question sets" and "Questionnaires" in place of "Forms".
- **ASSUMED (D25)** No down migration; a `pg_dump` of schema `qualification` before deploying is the way
  back.
- **ASSUMED (D26)** The database does not stop an INSERT of items into an existing version; the app never
  does it.
- **ASSUMED (D27)** The card page shows "has a newer version ... Move to vM" only on the current card.
- **ASSUMED (D28)** The migration is named `20260925150000_two_level_forms`.
- **ASSUMED (D29)** Old data that breaks a new CHECK (for example a description over 500) aborts the
  migration; nothing is truncated.
- **ASSUMED (D30)** Use-once questionnaire names keep the "Custom questions: <system>, <date>" pattern.
