# Stage 1: specification for two-layer control objectives (objective sets and objective profiles)

Date: 2026-09-25. Binding inputs: `RULES.md` and `BRIEF.md` in this folder (decisions D1 to D3, defaults A1
to A3). Built on the isolation run in `/home/listuser/aisc-isolation` (branch `isolation/2026-09-25`,
docs `docs/superpowers/isolation-2026-09-25/01-specs.md`, `02-tests.md`, `03-coding-plan.md`), read-only.
Implementation starts only after that run is merged into `feat/unified-modules` (A3).

Conventions of this file:

- Requirements are **R1.1, R1.2, ...** in bold. Control objective ids are always written in code with
  their set where it matters (`ai-act:R1.1`) or bare (`R1.1`) when the text is about the CSV. The two
  never mean the same thing.
- Every requirement names where it lands ("Lands in") and how it is proven ("Proof"). Test layers:
  **unit** (pytest, no database), **DB** (pytest against a throwaway `aisc-t-*` postgres, project
  databases made through the platform template as in the isolation run's recipe), **golden** (the
  renderer's golden captures), **static** (a source scan).
- Paths without a repo are relative to `apps/control-objectives` (the submodule, as it will be after the
  isolation merge). `CO` = that app. `RG` = `/home/listuser/aisc-report-generator` (branch `dev`, after the
  isolation renderer work R2 is merged there). `RC` = `apps/report-composer`. `TOP` = the top-level
  `aisc-install` repo.
- "MUST" is binding. "Note" is context.

Survey method: every file named in the brief was read, plus the isolation run's O1, P1, R1, R2 and V1
sections and the parallel qualification spec
`docs/superpowers/two-level-forms-2026-09-25/01-spec.md` (the same two-level pattern for questions). The
live database was read with SELECTs in a `default_transaction_read_only` session. Nothing was written
except this file and PROGRESS.md.

---

## 0. What exists (survey, 2026-09-25)

### 0.1 The module today (`feat/unified-modules`)

- The objectives are one packaged CSV, `src/aisc_control_objectives/data/ai_act_control_objectives.csv`:
  50 rows `R1.1` to `R11.x`, 11 macro requirements, header
  `"ID","Macro_Requirement","Legal_Basis","Sub_Requirement_Label","Control_Objective","Assessment_Mode","Target","Standards_Grounding","Grounding_Tier_Flag","Notes"`,
  every cell double-quoted, `\n` line ends, no BOM. sha256 of the bytes:
  `0321234f0b793444f8115dcd4228d9b62fec0f247c3e691d4bf23e2272041d96` (the live assessment's
  `objectives_digest`). Python's `csv.writer(quoting=csv.QUOTE_ALL, lineterminator="\n")` over the parsed
  rows reproduces the file byte for byte (checked).
- `control_objectives.py`: `COLUMNS` (CSV header to model field), `load_control_objectives(path)` (reads
  with `utf-8-sig`, refuses a missing column, skips a row with a blank ID, raises
  `ValueError("<path>: row <n> (ID '<id>'): <pydantic error>")`), `ControlObjectiveCatalogue` (sorted by
  `sort_key`, `by_id`, `macro_requirements()`, `requiring_control()`, `requiring_test()`, `digest`).
  Duplicate IDs are not detected (the dict keeps the last one).
- `models/control_objective.py`: `ControlObjective` validates `id` `^R\d+\.\d+$`, `macro_requirement`
  `^R\d+\s+\S`, the id under its macro, `assessment_mode` in three values, and derives `regimes` (the
  applicability: `ai_act`, `gdpr`, `conditional`, `voluntary`) from `legal_basis` and the note tag, raising
  on a basis or condition it cannot place.
- `prioritising.py`: `prioritise(catalogue, severity, mappings, risks)` gives one `Priority` per objective in
  catalogue order; ties broken by `objective.sort_key`; `VOLUNTARY` rows are non-binding, "Binding" in
  `grounding_tier_flag` adds `BINDING_WEIGHT`.
- `risk_mapping.py`: `RiskMapper._catalogue_text()` lists `id | macro requirement | label | objective` for
  every objective in catalogue order into the model prompt; `run_controls` flags an id not in the
  catalogue (`unknown-objective`).
- `db/tables.py` (schema `control_objectives`): `project` (the assessment: `id`, `project_id`, `system_id`
  unique, `name`, `objectives_digest`, timestamps), `graph`, `risk`, `mapped_objective` (`objective_id`
  bare text, no FK: "the catalogue is a CSV in the package, not a table"), `mapping_run`. Scores and tiers
  are computed, never stored.
- One catalogue is built at start (`server.build_app`) and shared by every page, every assessment and the
  mapper. The public routes `/objectives`, `/api/control-objectives[/{id}]`, `/api/macro-requirements`,
  `/api/config` serve it without a caller.

### 0.2 After the isolation run (what this spec builds on)

From isolation 01-specs I1.1, I1.3, I1.4, I2.6, I5.1 to I5.7 and 03-coding-plan WP O1 (not yet coded; the
tests are committed as `22ba3a2` in the CO worktree):

- Each project's `control_objectives` tables live in its own database `project_<hex>`; the schema is made
  by platform template `0008_control_objectives.sql`, the tables by CO's alembic chain, which becomes one
  baseline `20260926000000_project_database` (`down_revision = None`), shape of today minus `project_id`,
  `system_id` FK `project.system(pid)` ON DELETE CASCADE, reader grants to `report_ro` and `dashboard_ro`.
- `projectdb.py`: `ProjectDatabases.open(project, caller, write)` decides membership on `platform`
  (`core.project_member`) before connecting, then opens (LRU of 20, pool 2) and migrates the project
  database once (`alembic` with `config.attributes["connection"]`, advisory lock
  `hashtext('aisc_control_objectives.alembic')`).
- `python -m aisc_control_objectives.migrate_projects` upgrades every project database the role can enter
  (exit 0 / 1 platform unreachable / 2 permanent error). `DATABASE_URL` = `platform` (membership only),
  `PROJECT_DATABASE_URL` = template with `{database}`.
- JSON API moves under `/p/{pid}/api/projects...`; pages stay `/p/{project}/...`.
- `platform` keeps only `core` (project, project_member, schema_migration), `catalogue`, `form_library`
  (qualification_rw), `report_library` (report_composer_rw). A module role may own a library schema there;
  the library schemas are created by `init/platform-db.sql` (fresh volume) and
  `init/project-databases.sql` (every start), because module roles cannot create schemas on `platform`.
- The renderer reads each module's tables from the project database as `report_ro`; `report_ro` keeps only
  `CONNECT`, `USAGE core`, `SELECT core.project` on `platform` (I1.4).
- Precedent for library plus copy: isolation D3 (the form library in `platform.form_library`, a form
  version copied into the project on use, equal id means equal content, a differing row aborts).

### 0.3 Consumers

- `RG report_renderer/data/control_objectives.py`: `assessment`, `mappings` (risk rows with
  `objective_id`), `mapping_run`, `newest_newer_assessment`, `objective_ids`.
- Wording in the renderer comes from the CSV, not the database: `data/vocab.py objective_labels(path)`
  keyed by bare ID (`macro`, `legal_basis`, `label`, `objective`), path from env
  `REPORT_OBJECTIVES_CSV_PATH` (compose mounts CO's CSV read-only at `/data/ai_act_control_objectives.csv`).
  Used by `ctx.data.objectives` in blocks `control_objectives`, `summary_coverage`, `key_figures`,
  `changes_since`, `chart`, by `objective_filters.requirement_groups`, and by `report_service.py`
  `POST /v1/coverage-choices` (`{"value": oid, "label": "<oid> <label>", "group": macro}`).
- Stored objective ids outside CO: the composer's coverage map (`layout.coverage`, migration 0005,
  entries `{objective_id, tests, checklists}`), the `control_objectives` block option `objectives`
  (list of ids) and the `summary_coverage` block option `links[].objective_id`. All bare (`"R1.1"`).
  `RC coverage_map.py` compares them with the renderer's choices (`reference_problems`, `reset`, `grid`).
- Nothing else reads objective ids (controls, backend, qualification, results-dashboard: none).

### 0.4 Live data (SELECT only, 2026-09-25)

`platform.control_objectives`: 1 assessment (`objectives_digest` = the CSV's sha256), 5 risks,
0 mapped objectives, alembic `7c3e5a9b1d24`. `report_composer.schema_migration` has only 0001 and 0002
(no `coverage` column live). The one `control_objectives` block's options hold no `objectives` list;
the one `summary_coverage` block has `links: []`. So no stored objective id exists live. All of it is
fake (D1).

---

## 1. Vocabulary

- **Objective set** (A1, name to confirm): where objectives are written or imported. It has versions.
  Every objective belongs to exactly one set. Built-in sets live in the platform library; custom sets
  live in one project's database.
- **Objective**: a stable identity `(set, local id)`. Its **key** is `<set id>:<local id>`, for example
  `ai-act:R1.1`. The wording is not on the objective; it is on the set version.
- **Wording**: the nine CSV columns other than `ID`: `macro_requirement`, `legal_basis`,
  `sub_requirement_label`, `text` (CSV `Control_Objective`), `assessment_mode`, `target`,
  `standards_grounding`, `grounding_tier_flag`, `notes`.
- **Set version**: an immutable ordered list of the set's objectives, each with its wording.
- **Objective profile** (A1, name to confirm): assembled only by picking objectives from set versions. It
  never creates or rewords an objective. An assessment is made against one profile version.
- **Profile version**: an immutable ordered list of items; each item is one objective as worded in one set
  version (the **pin**).
- **Pinned**: an item names a specific set version and never follows the set's latest version by itself
  (D3).
- **Update available**: a picked objective whose set has a newer version in which its wording differs
  (**reworded**) or from which it is absent (**removed**); or, for an assessment, a newer version of the
  profile it pinned.
- **Built-in**: shipped with a release, seeded into the platform library, read-only in the app
  (origin `builtin`). **Custom**: made in the app (origin `editor`) or by import (origin `import`) inside
  one project.
- **Library**: schema `objective_library` in the `platform` database: the built-in sets and profiles.
- **Project copy**: a built-in set version or profile version copied, with the same ids and content, into
  the project database the first time the project uses it (A2, section 6).
- **Retired**: hidden from pickers and lists, still resolvable forever; set once, never cleared.
- **Display id**: what a page or report prints for an objective: its local id when no other objective of
  the same profile version has that local id, otherwise its key.
- **Assessment**: a row of `control_objectives.project` (name kept, isolation D6), one per AI card version.

---

## 2. Where logic lives

The user reads Python (memory `user_python_only`). Pages stay server-rendered Jinja; JavaScript is limited
to filtering and ticking checkboxes in the builder.

| Logic | Module (CO unless said) |
|---|---|
| CSV parse (the existing validation, plus duplicate IDs) and exact CSV write | `objective_csv.py` (new; `control_objectives.py` keeps `COLUMNS` and delegates) |
| Canonical digests of a set version and a profile version | `objective_csv.py`, `profile_file.py` |
| Profile file write and read (references, self-contained) | `profile_file.py` (new, pure) |
| Keys, display ids, legacy id reading (`qualify`) | `objective_keys.py` (new, pure) |
| The catalogue an assessment is scored against, built from a pinned profile version | `pinned.py` (new, pure): `PinnedCatalogue` |
| Update detection, next version number, "same content" | `objective_sets.py` (new, pure functions over plain data) |
| Library reads and the seeder | `db/library.py`, `seed_library.py` (new) |
| Project reads and writes of sets, profiles, copies | `db/sets.py` (new), `builtin_copy.py` (new) |
| Service the routes call (sets, profiles, import, export, start with a profile) | `objective_service.py` (new), `projects.py` (changed) |
| Pages | `api/app.py`, `rendering.py`, templates |
| Report wording | `RG report_renderer/data/control_objectives.py`, `RG report_renderer/objective_keys.py` |
| Coverage-map id reading | `RC report_composer/coverage_map.py` |

---

## 3. Data model

### 3.1 Ids

- **R3.1** Built-in ids are fixed text chosen by the release: set `ai-act`, its versions
  `ai-act-v1`, `ai-act-v2`, ...; profile `ai-act-default`, versions `ai-act-default-v1`, ... A built-in set
  or profile id matches `^[a-z][a-z0-9-]{1,39}$` and does not start with `s-` or `p-`.
  Lands in: CO `data/library/library.json`, DDL CHECKs (3.2). Proof: DB (CHECK refuses `s-abc` as builtin).
- **R3.2** Custom ids: set `s-` + 12 lowercase hex (`secrets.token_hex(6)`), profile `p-` + 12 hex. A version
  id is always `<parent id>-v<number>`. An objective id (its key) is always `<set id>:<local id>`.
  Enforced by CHECK constraints (3.2). Lands in: CO `objective_keys.py`, DDL. Proof: unit + DB.
- **R3.3** A local id matches `^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$` in the database; the application
  additionally keeps today's model rule `^R\d+\.\d+$` under its macro (section 7, R7.2). Lands in: DDL,
  `models/control_objective.py` (unchanged). Proof: DB, unit.

### 3.2 Tables (identical columns in the library and in each project database)

The same seven tables exist in two places: schema `objective_library` in `platform` (built-ins only) and
schema `control_objectives` in every project database (project copies of built-ins, plus custom). Exact
shape (library differences in the last column):

| table | columns | keys and checks | library differs |
|---|---|---|---|
| `objective_set` | `id text`, `name text NN`, `description text NN DEFAULT ''`, `origin text NN`, `retired_at timestamptz NULL`, `created_at timestamptz NN DEFAULT now()`, `created_by text NN`, `created_by_subject text NULL` | PK id; origin in (`builtin`,`editor`,`import`); name 1..120 after trim; description <= 500; created_by 1..200; `origin <> 'builtin' OR id` matches R3.1; `origin = 'builtin' OR id ~ '^s-[0-9a-f]{12}$'`; unique `lower(name)` among rows with `retired_at IS NULL` | origin CHECK is `= 'builtin'` |
| `objective_set_version` | `id text`, `set_id text NN`, `number int NN`, `content_digest char(64) NN`, `source_digest char(64) NULL`, `created_at`, `created_by`, `created_by_subject` | PK id; FK set_id RESTRICT; number >= 1; unique (set_id, number); `id = set_id || '-v' || number` | none |
| `objective` | `id text`, `set_id text NN`, `local_id text NN`, `created_at` | PK id; FK set_id RESTRICT; unique (set_id, local_id); `id = set_id || ':' || local_id`; local_id regex R3.3 | none |
| `objective_set_version_item` | `set_version_id text`, `objective_id text`, `position int NN`, `macro_requirement text NN`, `legal_basis text NN`, `sub_requirement_label text NN`, `text text NN`, `assessment_mode text NN`, `target text NN`, `standards_grounding text NN`, `grounding_tier_flag text NN`, `notes text NN` | PK (set_version_id, objective_id); FKs RESTRICT; unique (set_version_id, position); position >= 0; `text` 1..2000; `assessment_mode` in the three modes; every other text <= 2000 | none |
| `objective_profile` | as `objective_set` (id `^p-[0-9a-f]{12}$` for custom) | as `objective_set` | as `objective_set` |
| `objective_profile_version` | `id`, `profile_id NN`, `number NN`, `content_digest char(64) NN`, `source_digest char(64) NULL`, `created_at`, `created_by`, `created_by_subject` | as `objective_set_version`, parent profile | none |
| `objective_profile_version_item` | `profile_version_id text`, `position int NN`, `set_version_id text NN`, `objective_id text NN` | PK (profile_version_id, objective_id); unique (profile_version_id, position); FK `(set_version_id, objective_id)` to `objective_set_version_item` RESTRICT (an item is an objective as one set version words it) | none |

- **R3.4** The seven tables above are created exactly as listed in both schemas, with the indexes their FKs
  need. Lands in: CO `alembic_library/versions/<ts>_objective_library.py` (platform) and CO
  `alembic/versions/<ts>_objective_sets.py` (project databases), section 12. Proof: DB (catalog check of
  columns, types, constraints in both schemas).
- **R3.5** Assessment tables in each project database after the change (D1: dropped and recreated, section
  12):
  - `project`: `id varchar(32) PK`, `name text NN`, `system_id uuid NN UNIQUE` FK `project.system(pid)`
    ON DELETE CASCADE (as the isolation baseline), **`profile_version_id text NN` FK
    `objective_profile_version(id)` ON DELETE RESTRICT**, `created_at`, `updated_at`, `created_by text NULL`,
    `created_by_subject text NULL`. **`objectives_digest` is dropped** (the pin replaces it).
  - `graph`, `risk`, `mapping_run`: exactly the isolation baseline shape.
  - `mapped_objective`: as the baseline, but `objective_id text NN` **FK `objective(id)` ON DELETE
    RESTRICT** (a key, `ai-act:R1.1`), unique (risk_row_id, objective_id) kept.
  Lands in: CO `db/tables.py`, the project revision. Proof: DB.
- **R3.6** Nothing in `objective_library` knows a project; no project data is ever written to `platform`.
  Lands in: CO. Proof: static (no write to `objective_library` outside `seed_library.py`), DB.

### 3.3 Append-only and fixed rows: how it is enforced

PL/pgSQL triggers, the same set in both schemas (functions created per schema), messages exact:

| trigger | on | refuses, with message (`%` = the row id) |
|---|---|---|
| `objective_set_version_is_append_only` | BEFORE UPDATE OR DELETE `objective_set_version` | `objective set version % is immutable: save a new version instead` |
| `objective_set_version_item_is_append_only` | BEFORE UPDATE OR DELETE `objective_set_version_item` | same, with OLD.set_version_id |
| `objective_profile_version_is_append_only` | BEFORE UPDATE OR DELETE `objective_profile_version` | `objective profile version % is immutable: save a new version instead` |
| `objective_profile_version_item_is_append_only` | BEFORE UPDATE OR DELETE `objective_profile_version_item` | same, with OLD.profile_version_id |
| `objective_identity_is_fixed` | BEFORE UPDATE OR DELETE `objective` | `objective % keeps its identity: it is never changed or deleted` |
| `objective_set_row_is_fixed` | BEFORE UPDATE OR DELETE `objective_set` | DELETE: `objective set % cannot be deleted: retire it instead`; UPDATE of anything but `description` and `retired_at` NULL to a value: `objective set % keeps its name, origin and author; it can only be retired, once`; any UPDATE of a `builtin` row outside a seed (below): `objective set % is built in: it changes only with a release` |
| `objective_profile_row_is_fixed` | same for `objective_profile` | same messages with "objective profile" |
| `objective_set_version_is_allowed` | BEFORE INSERT `objective_set_version` | retired set: `objective set % is retired: it gets no new version`; number not `max(number)+1` of its set (1 for the first): `objective set % gets version %, not %` (set, expected, given); a `builtin` set outside a seed or copy: `objective set % is built in: its versions come from a release` |
| `objective_profile_version_is_allowed` | same for profiles | same messages with "objective profile" |
| `objective_set_version_item_is_of_its_set` | BEFORE INSERT `objective_set_version_item` | `objective % is not an objective of the set of version %` |
| `items_come_with_their_version` | BEFORE INSERT on both item tables | the parent version row was not inserted by the current transaction (`xmin` of the version row equals `txid_current() & 4294967295`): `version % is saved: its items cannot change` |
| `assessment_pin_is_fixed` (project databases only) | BEFORE UPDATE `project` | NEW.profile_version_id differs from OLD: `assessment % keeps the profile version it started on` |
| `mapped_objective_is_in_the_pinned_profile` (project databases only) | BEFORE INSERT `mapped_objective` | the objective is not an item of the assessment's pinned profile version: `objective % is not in the profile version assessment % is made against` |

"Outside a seed or copy": a session-local setting. In `platform`, built-in inserts and the one allowed
builtin UPDATE (`retired_at`) pass only when `current_setting('aisc.library_seed', true) = 'on'`; in a
project database, inserts of `builtin` rows pass only when `current_setting('aisc.builtin_copy', true) =
'on'`. Only `seed_library.py` sets the first and only `builtin_copy.py` the second, each with `SET LOCAL`
inside its own transaction.

- **R3.7** Every trigger above exists in both schemas (the two assessment triggers only in project
  databases) and refuses with the exact message. Lands in: both revisions. Proof: DB, one test per row of
  the table, in each schema.
- **R3.8** `SET LOCAL aisc.library_seed` appears in `src/` only in `seed_library.py`; `SET LOCAL
  aisc.builtin_copy` only in `builtin_copy.py`. Proof: static.
- **R3.9** Custom sets and profiles are never deleted by the app; there is no DELETE route for them.
  Proof: static (route table), DB (trigger).

### 3.4 created_by

- **R3.10** Every row with `created_by` gets it from the signed-in caller: `created_by` = the caller's
  `username`, else `email`, else `subject`; `created_by_subject` = `subject`. Built-in rows (library and
  project copies) carry `created_by = 'system'`, `created_by_subject = NULL`. The start of an assessment
  records its caller the same way. Lands in: CO `objective_service.py`, `projects.py`. Proof: unit (caller
  mapping), DB (rows).

---

## 4. The built-in library in `platform`

- **R4.1** Schema `objective_library` in `platform`, owned by `control_objectives_rw`, comment
  `The install-wide library of built-in control objective sets and profiles: no project data.` Created by
  `init/platform-db.sql` (fresh volume) and by `init/project-databases.sql` on every start (`CREATE SCHEMA
  IF NOT EXISTS ... AUTHORIZATION control_objectives_rw`, in the DO block that skips a missing role), next
  to `form_library` and `report_library`. Lands in: TOP `init/`. Proof: TOP `scripts/tests` (fresh volume
  test of the isolation run extended), DB.
- **R4.2** The library's tables are created by a second alembic tree `alembic_library/` (own `env.py`,
  `version_table_schema="objective_library"`, `SET search_path TO objective_library`, advisory lock
  `hashtext('aisc_control_objectives.library')`), refusing any URL whose database is not `platform` or a
  test database. Lands in: CO `alembic_library/`, `alembic_library.ini`. Proof: DB.
- **R4.3** Seed files are package data: `data/library/library.json` (manifest) and
  `data/library/sets/ai-act/v1.csv`, which is today's `ai_act_control_objectives.csv` moved byte for byte
  (same sha256 `0321234f...`). Manifest shape:
  `{"sets": [{"id", "name", "description", "versions": [{"number", "file", "retired": false}]}],
    "profiles": [{"id", "name", "description", "versions": [{"number", "items": [{"set": "<set id>",
    "version": <n>, "objectives": "all" | ["<local id>", ...]}]}]}]}`.
  Initial content: set `ai-act` "EU AI Act control objectives" v1 = the CSV; profile `ai-act-default`
  "AI Act default" v1 = all 50 objectives of `ai-act` v1 in CSV order (A1: names to confirm).
- **R4.4** `python -m aisc_control_objectives.seed_library` (and the same function called first by
  `migrate_projects.main`, before the project databases) upgrades `alembic_library` to head, then in one
  transaction with `SET LOCAL aisc.library_seed = 'on'` inserts every manifest set version and profile
  version that is absent; a present version whose `content_digest` differs from the file's aborts the whole
  seed with exit 2 and `FAILED library: <set or profile id> v<n> differs from the shipped file`; a
  version marked `retired: true` sets `retired_at` on its parent when the whole parent is retired in the
  manifest (a set or profile is retired, never a version). Idempotent: a second run changes nothing
  (`pg_stat_user_tables.n_tup_ins` unchanged). It never deletes. Lands in: CO `seed_library.py`,
  `migrate_projects.py`. Proof: DB (first run seeds 1 set, 1 version, 50 objectives, 50 items, 1 profile,
  1 version, 50 items; second run no insert; a tampered file exits 2 and writes nothing).
- **R4.5** A release ships a new built-in version by adding a file and a manifest entry; it never edits a
  shipped file (R4.4 refuses). Proof: DB (adding `v2` seeds only v2).
- **R4.6** The app itself only reads the library, through the existing `platform` engine
  (`ProjectDatabases.platform`, pool 2). If the library is not at head or not seeded, every library read
  answers 503 `The objective library is not installed yet.` and the public catalogue routes answer the same.
  Lands in: CO `db/library.py`, `api/app.py`. Proof: DB.
- **R4.7** The public routes keep their paths and payloads: `/objectives`, `/api/control-objectives`,
  `/api/control-objectives/{id}`, `/api/macro-requirements` serve the latest non-retired version of
  built-in set `ai-act` from the library. For `ai-act` v1 the JSON is equal to today's (same objects, same
  order, same computed fields). Lands in: CO `api/app.py`. Proof: DB (JSON equality against a fixture
  captured from today's code).

---

## 5. Objective identity, versions, retiring (project databases)

- **R5.1** A set version holds each of its objectives once, in `position` order 0..n-1. The same local id in
  two versions of one set is the same objective (one `objective` row). An objective absent from a newer
  version keeps its row and its older wording; it is never deleted. Proof: DB.
- **R5.2** Saving a set (editor or import) creates the set's next version with `number = max + 1`; saving
  content equal to the latest version (same `content_digest`) creates nothing and answers "No change: this
  is v<n>." Two editors saving at once: the second gets 409 `Someone saved v<n> of this set first. Reload
  and save again.` and nothing is stored (unique `(set_id, number)` plus the trigger). Lands in: CO
  `objective_service.py`. Proof: DB (concurrent save test with two connections).
- **R5.3** `content_digest` of a set version = sha256 of its canonical CSV (R7.4). `content_digest` of a
  profile version = sha256 of its canonical references file (R9.1). For built-in `ai-act` v1 the set digest
  equals `0321234f0b793444f8115dcd4228d9b62fec0f247c3e691d4bf23e2272041d96`. Proof: unit, DB.
- **R5.4** Retire: an editor may retire a custom set or profile (POST, sets `retired_at = now()` once).
  A retired set is not offered as a source in the builder and gets no new version; items already pinned to
  it keep resolving and can be carried into a new profile version. A retired profile is not offered when
  starting an assessment; assessments pinned to it are unchanged. Built-ins are retired only by a release
  (R4.4). Proof: DB, page tests.
- **R5.5** Who may do what (the isolation gate decides first): members read everything of their project
  and the library; editors and owners create, version, import, retire; viewers get 403 on every POST (the
  existing `REFUSALS`). DEFAULT (user to confirm) in Q7. Proof: DB (gate tests mirrored for the new routes).

---

## 6. Built-ins inside a project: copy on use (A2, argued)

**Decision: keep A2 (copy), do not reference.** Reasons:

1. A foreign key cannot cross databases. With a reference, `project.profile_version_id`,
   `objective_profile_version_item` and `mapped_objective.objective_id` could not point at the library, so
   the append-only guarantee "an assessment keeps exactly what it was assessed against" would rest on the
   library never changing, not on the database. With a copy every link is a real FK inside the project
   database.
2. The renderer and the dashboard read only the project database under isolation (I1.4: `report_ro` has no
   read of any library on `platform`). A reference would require new `platform` grants for `report_ro` and
   a second connection per report.
3. The project database stays complete by itself: a dump, a restore, a copy to another host or a future
   project export carries its objectives' wording. A library outage does not stop an assessment page.
4. It is the pattern the isolation run chose for forms (isolation D3), so both modules behave alike.
5. Cost: at most a few hundred rows per project per built-in version (50 objectives today).

What still reads the library: the pickers (which built-ins exist) and "update available" for built-ins
(whether the library has a newer version than the project copy).

- **R6.1** Copy on use: in the same transaction as the write that first uses them, `builtin_copy.ensure(
  project_conn, library, profile_version_ids=..., set_version_ids=...)` copies from the library into the
  project database, with the same ids and values, every row needed: for a profile version, its
  `objective_profile` row (if absent), the version, its items, and for each item's set version the rows
  below; for a set version, its `objective_set` row (if absent), the version, every `objective` it names,
  and all its items. Uses: starting an assessment on a built-in profile version (R10.1); saving a custom
  profile version that picks from a built-in set version (R8.4). Lands in: CO `builtin_copy.py`. Proof: DB.
- **R6.2** Equal id means equal content: a row already present is compared on every column; equal is a
  no-op; different aborts the whole transaction, answers 500 `The built-in objectives in this project differ
  from the library; nothing was saved.` and logs the ids (never the wording). The `objective_set` /
  `objective_profile` row of a built-in is compared on `id`, `name`, `origin` only (a release may retire it
  in the library; the project copy keeps `retired_at` NULL and a retired built-in is still usable where it
  is already pinned). Proof: DB (tampered library row aborts, nothing stored).
- **R6.3** When a new built-in version ships (R4.5): nothing in any project changes; project copies of older
  versions stay; assessments keep their pins; the new version is copied into a project only when that
  project first uses it. DEFAULT (user to confirm) in Q3. Proof: DB.
- **R6.4** An assessment page, a report and a mapping run read only the project database. Proof: DB (with
  the library schema's privileges revoked in the test, the assessment page renders and a map runs).

---

## 7. CSV import and export of a set

- **R7.1** `objective_csv.parse(raw: bytes, source_name: str) -> list[ControlObjective]` keeps today's
  contract exactly: `utf-8-sig` decoding, the ten required columns (extra columns ignored), a row with a
  blank `ID` skipped, every row validated by `ControlObjective` with the message
  `<source_name>: row <n> (ID '<id>'): <pydantic error>`, a missing column
  `<source_name>: missing required column(s): <names>`. Additions, needed by the primary key and by the
  database checks: a repeated ID `<source_name>: row <n>: ID '<id>' appears twice (first on row <m>)`; no
  data row `<source_name>: the file has no objectives`; not UTF-8 `<source_name>: the file is not UTF-8
  text`; more than 1 MiB `the file is larger than 1 MiB`; more than 500 objectives `a set version holds at
  most 500 objectives`; a wording field over its DB limit `<source_name>: row <n> (ID '<id>'): <column> is
  longer than 2000 characters`. `load_control_objectives(path)` becomes `parse(path.read_bytes(),
  str(path))` wrapped in a catalogue; every existing test in `tests/test_control_objectives.py` keeps passing
  unchanged. Lands in: CO `objective_csv.py`, `control_objectives.py`. Proof: unit (existing tests plus one
  per new message).
- **R7.2** The model rules stay as they are for every set, built-in or custom (`id` `^R\d+\.\d+$` under its
  macro, three modes, a placeable legal basis and condition). DEFAULT (user to confirm) in Q5.
- **R7.3** Import (editor, `POST /p/{project}/objectives/sets/import`, multipart `file`, `target` =
  `new` or a custom set id, `name` for `new`): always creates a set or a version, never edits one.
  - `target=new`: if an active set of this project has a version whose `source_digest` or
    `content_digest` equals the file's sha256 or its parsed content digest, nothing is stored and the page
    says `Already imported: <set name> v<n>.` (the no-op of the brief); otherwise a new custom set (origin
    `import`, the given name, default: the file name without extension) and its v1, `source_digest` = the
    file's sha256.
  - `target=<set id>`: content equal to the latest version: `No change: this is v<n>.`, nothing stored;
    otherwise the set's next version. A built-in set id or a retired set as target: 409 `Built-in sets
    change only with a release.` / `This set is retired.`
  - Any parse error: 422 with the R7.1 message(s), nothing stored. A name taken by an active set: 409
    `A set called <name> already exists.`
  Lands in: CO `objective_service.py`, `api/app.py`. Proof: DB (import twice the same bytes: one version;
  import the export of v1 into its own set: no change; import a changed file: v2).
- **R7.4** Export (`GET /p/{project}/objectives/sets/{set_id}/export[?version=<n>]`, any member, built-ins
  from the library or the project copy, retired sets too): the canonical CSV, header as today, rows in
  `position` order, `csv.writer(quoting=csv.QUOTE_ALL, lineterminator="\n")`, UTF-8 without BOM,
  `Content-Type: text/csv; charset=utf-8`, `Content-Disposition: attachment; filename="<set id>-v<n>.csv"`,
  `Cache-Control: no-store`. Unknown set or version: 404. The export of `ai-act` v1 is byte-identical to the
  packaged file. Round trip: `parse(export(v))` equals v's wording in order for any version. Proof: unit
  (round trip with quotes, commas, newlines, non-ASCII), DB (byte equality for `ai-act` v1).
- **R7.5** The set editor (`/p/{project}/objectives/sets/new`, `/p/{project}/objectives/sets/{id}/edit`)
  posts rows (ID plus the nine wording fields, add row, remove row); the server builds the rows into the
  same CSV model and validates with R7.1's rules (messages name the row by its position in the form);
  saving follows R5.2. The editor never shows for a built-in set; a built-in offers "Export CSV" and
  "Make a custom copy" (a new custom set whose v1 has the same rows, origin `editor`). Proof: DB, page tests.

---

## 8. Profiles: builder, versions, update available

- **R8.1** A profile version holds 1..500 items, each objective at most once, positions 0..n-1. Item order:
  the order of the sources as picked in the builder, then each set version's `position`. Proof: DB, unit.
- **R8.2** Built-in profiles are not editable. "Make a custom copy" creates a custom profile (origin
  `editor`) whose v1 has the same items pinned to the same set versions (built-in pins stay built-in; the
  set versions are copied per R6.1). Proof: DB.
- **R8.3** The builder offers as sources: every active custom set of the project (latest version, older
  versions selectable) and every non-retired built-in set of the library (latest version, older selectable).
  Adding a source ticks all its objectives; a search box filters by display id, label and text; untick to
  leave out. A profile may pick from built-in and custom sets together. DEFAULT (user to confirm) in Q2.
- **R8.4** Saving the builder posts the list of picks `<set_version_id>|<objective key>` in order; the
  server checks every pick exists (in the project, or in the library for a built-in, then copied per
  R6.1), refuses duplicates (`<key> is picked twice`) and an empty list (`Pick at least one objective.`),
  and creates the profile's next version (or a new profile with v1, name rules as sets). Content equal to the
  latest version: `No change: this is v<n>.` Proof: DB.
- **R8.5** Update detection (`objective_sets.updates(profile_version, latest_by_set)`, pure): for each item
  pinned to set version `S vN`, let `M` be the latest version of S (for a built-in, the higher of the
  project copy's latest and the library's latest non-retired version; for a custom set, the project's). If
  `M > N`: the objective absent from `S vM` is `removed`; present with any of the nine wording fields
  different is `reworded` (with the new wording); only a different position is no update. Objectives newly
  added in `S vM` are not updates. Proof: unit (reworded in one field, removed, moved only, two sets, a
  retired set).
- **R8.6** The builder shows each update on its row: `Update available`, then for `reworded` the new wording
  (`<set name> v<M> words it: <text>`) and `Accept update`; for `removed` the words `Removed in <set name>
  v<M>` and `Remove`. `Accept all updates` accepts every `reworded` one (not the `removed` ones). Accepting
  changes the pin to `S vM` in the draft; saving makes the next profile version (R8.4). Nothing moves by
  itself (D3). Proof: page tests (form posts), DB.
- **R8.7** The library page lists, per profile, the number of updates of its latest version, and, for a
  built-in profile, whether the library has a newer version than the project's latest copy. If the library
  cannot be read, the page says `Could not check the library for updates.` and still lists the project's
  profiles. Proof: DB.

---

## 9. Profile export and import

- **R9.1** `profile_file.write(profile, bundle) -> (filename, content)`, pure, JSON
  (`json.dumps(doc, ensure_ascii=False, indent=2) + "\n"`), keys in this order: `"format":
  "aisc-objective-profile"`, `"formatVersion": 1`, `"bundle": "references" | "self-contained"`, `"name"`,
  `"description"`, `"version"`, `"items"`; each item `setId`, `setName`, `setVersion`, `localId`, and only for
  `self-contained` the nine wording fields under their model names (`macro_requirement`, `legal_basis`,
  `sub_requirement_label`, `text`, `assessment_mode`, `target`, `standards_grounding`,
  `grounding_tier_flag`, `notes`). Filename `<profile id>-v<n>.profile.json`. The canonical references file
  of a version (bundle `references`) is what `content_digest` hashes (R5.3). Lands in: CO `profile_file.py`.
  Proof: unit (exact bytes for `ai-act-default` v1, first item `{"setId": "ai-act", "setName": "EU AI Act
  control objectives", "setVersion": 1, "localId": "R1.1"}`).
- **R9.2** Export route `GET /p/{project}/objectives/profiles/{id}/export?bundle=references|self-contained
  [&version=<n>]` (default `references`; another value 400 `bundle must be references or self-contained`;
  unknown id or version 404), headers as R7.4 with `application/json; charset=utf-8`. Built-in, custom and
  retired profiles export. Proof: DB.
- **R9.3** `profile_file.read(raw, filename)` checks in order, each a 422 with the exact detail:
  extension `.json` (`<ext> is not a profile file`), not empty, UTF-8 JSON object, `format`/`formatVersion`
  (`this is not an objective profile file`), `bundle`, name 1..120, description <= 500, version a positive
  integer if present, 1..500 items, per item (1-based n) `item <n> has no setId`, `item <n> has no
  setVersion`, `item <n> has no valid localId`, `item <n> is in the file twice`, and for self-contained the
  wording checked by `ControlObjective` (`item <n>: <pydantic error>`). Round trip: `read(write(p, b))`
  equals p normalised for both bundles. Proof: unit.
- **R9.4** Import (editor, `POST /p/{project}/objectives/profiles/import`, multipart `file`, `name`
  default the file's name): always creates a new custom profile (origin `import`) with v1,
  `source_digest` = the file's sha256; if an active profile of the project has a version with that
  `source_digest` or that `content_digest`, nothing is stored: `Already imported: <name> v<n>.`
  - **references**: each `(setId, setVersion, localId)` must resolve to a built-in set version in the library
    or a set version of this project with that id. All found: the profile is created (built-ins copied per
    R6.1). Anything missing: 422 `This profile refers to objectives this project does not have. Import its
    self-contained file, or import those sets first.` plus one line per missing set version
    (`Set "<setName or setId>" (<setId>) v<n> is not available here.`) and per missing objective
    (`<setId>:<localId> is not in set "<name>" v<n>.`), item order; nothing stored. A reference to another
    project's custom set therefore never resolves (custom ids are per project). DEFAULT (user to confirm) in Q6.
  - **self-contained**: items whose `setId` is a built-in library set with that version must match the
    library's wording exactly, else 422 `item <n> claims <setId> v<m> but its wording differs from the
    built-in set.`; they pin to the built-in (copied). All other items: one new custom set per distinct
    source `setId` (origin `import`, name `<setName> (imported)`, suffix ` 2`, ` 3` on a name clash), with one
    version per distinct source `setVersion` in ascending order, each holding that source version's bundled
    items with their local ids; the profile's items pin to the matching new set versions, in file order.
  Lands in: CO `objective_service.py`. Proof: DB (export from project A, import into project B, both bundles;
  the assessment started on the imported profile scores exactly as in A).

---

## 10. The assessment pins one profile version

- **R10.1** Starting an assessment (`POST /p/{project}/projects`) takes `profile_version_id` from the form.
  The chooser lists, as `<name> v<n>`: non-retired built-in profiles from the library (latest version) and
  active custom profiles of the project (latest version). Preselected: the profile of the assessment of the
  project's previous card version, at that profile's latest version; with no previous assessment, the latest
  `ai-act-default`. A missing or unknown id: 422 `Choose an objective profile.`; a retired one: 409 `This
  profile is retired.` A built-in version is copied (R6.1) in the same transaction as the assessment row.
  DEFAULT (user to confirm) in Q8. Lands in: CO `api/app.py`, `projects.py`, template `projects.html.j2`.
  Proof: DB.
- **R10.2** The pin never changes (trigger `assessment_pin_is_fixed`). A newer profile version, or updates in
  its pinned set versions, show on the assessment page as `Update available: <profile name> v<m>` (or
  `<k> objectives of this profile have newer wording`) with the sentence `This assessment stays on v<n>.
  The next card version's assessment can start on the new version.` There is no "accept" on an assessment.
  DEFAULT (user to confirm) in Q4. Proof: DB, page test.
- **R10.3** The assessment page and JSON payload name the pin (`profile: {id, name, version, version_id}`)
  instead of `objectives_digest`; the page footer shows `Profile <name> v<n>` where it showed
  `catalogue <digest>`. Proof: page test, DB.
- **R10.4** Starting again on the same card version opens the existing assessment whatever profile was
  chosen (today's rule), and says `This version's assessment already exists (profile <name> v<n>).` Proof: DB.

---

## 11. Scores, tiers, applicability and risk mapping read the pin

- **R11.1** `pinned.PinnedCatalogue.load(project_conn, profile_version_id)` builds, from the project database
  only, one entry per item in position order: `key`, `local_id`, `set_id`, `set_name`, `set_version`,
  `position`, and `objective`, a `ControlObjective` validated from the item's wording (so applicability,
  modes and regimes are derived exactly as today). It offers the interface the domain uses today:
  iteration in position order, `__len__`, `by_id(key)`, `macro_requirements()` (grouped by `(set_id,
  macro_id)`, titled with the set name when the profile spans more than one set), `requiring_control()`,
  `requiring_test()`, and `display_id(key)`. Lands in: CO `pinned.py`. Proof: unit.
- **R11.2** `prioritise`, `rendering.render_project_page` and `projects.Projects._derive` take the assessment's
  `PinnedCatalogue`; `Priority.objective_id` holds the key; ties are broken by `position` (today:
  `sort_key`), and the page sorts rows by `(-score, position)`. Proof: unit.
- **R11.3** No change in results for the built-in profile: for `ai-act-default` v1 and any severity, mapping
  and risk list, `{local_id: (tier, score, driving_severity, reasons, risk_ids, non_binding)}` computed from
  the pin equals the same map computed by today's `prioritise` over today's CSV catalogue (with mapping
  objective ids read through `qualify`). Proof: unit, property style over the MCAS fixture plus 200 random
  severity/mapping draws with a fixed seed, and one DB test end to end.
- **R11.4** Risk mapping: `map_risks` and `RiskMapper` receive the assessment's `PinnedCatalogue`. The
  prompt lists exactly the pinned objectives, in position order, one per line `<display id> | <macro
  requirement> | <label> | <text>`. For `ai-act-default` v1 the prompt string is byte-identical to today's.
  The model's answer is read through the display ids: a display id maps to its key; an id that is not a
  display id of the pin is `unknown-objective` (today's flag). Stored `mapped_objective.objective_id` is the
  key. The mapper still resolves its LLM with the database's pid (isolation I5.6). Lands in: CO
  `risk_mapping.py`, `projects.py`. Proof: unit (prompt bytes equal to a capture from today's code; a
  profile with `R1.1` in two sets prompts with keys).
- **R11.5** The CSV-wide catalogue built at start remains only for the public routes (R4.7); no assessment
  path reads it. Proof: static (`Projects` no longer takes a catalogue argument).

---

## 12. The schema change (D1: drop, recreate, seed fresh)

- **R12.1** Project databases: one new alembic revision `20261001000000_objective_sets` (name DEFAULT),
  `down_revision = "20260926000000_project_database"`, which in one transaction: drops
  `mapped_objective`, `mapping_run`, `risk`, `graph`, `project` (D1: their rows are fake and are lost);
  creates the seven tables of 3.2, the assessment tables of R3.5, the triggers of 3.3; grants `SELECT` on the
  twelve tables (seven new plus `project`, `graph`, `risk`, `mapped_objective`, `mapping_run`) to
  `report_ro` and `dashboard_ro` when those roles exist (the isolation grant block). Nothing is seeded in
  project databases (copies happen on use, R6.1). Its `downgrade()` drops everything it created and
  recreates the baseline's five tables empty. No `core.` substring in the file. Lands in: CO
  `alembic/versions/`. Proof: DB (upgrade from the baseline on a database with a baseline assessment row:
  tables recreated, old rows gone; upgrade twice: no-op; downgrade then upgrade).
- **R12.2** The revision runs through the isolation mechanism unchanged: `ProjectDatabases.open` migrates a
  database on first open, `migrate_projects` upgrades every project database (exit codes unchanged), with
  the library seed first (R4.4); a library failure exits 2 before any project database is touched.
  Proof: DB (the isolation `test_I5_5_*` tests keep passing with the new head).
- **R12.3** Platform: the library tree's first revision creates the tables of 3.2 in `objective_library`
  plus its triggers; the seed then fills it (R4.4). The old `platform.control_objectives` schema is not
  touched by this work: it is retired at isolation cutover C9 and dropped in isolation stage 7.
- **R12.4** Before applying R12.1 to live, the orchestrator takes `pg_dump -Fc -n control_objectives` of every
  `project_<hex>` database to the backup directory (mode 600, outside any repo). Lands in: stage 6 procedure
  (a checklist line in the coding plan). Proof: the stage-5 verification lists it.
- **R12.5** Isolation tests that pin "one baseline and nothing after it" change deliberately, and only as far
  as this needs (named in the commit): CO `tests/test_isolation_static.py::test_I5_4_one_baseline_revision`
  (the baseline is the first revision and has `down_revision = None`; later revisions are allowed and each
  has no `core.`), CO `tests/test_isolation_project_databases.py::test_I5_4_the_database_is_at_the_baseline_and_readers_get_their_reads`
  (the database is at the chain's head; `READER_TABLES` gains the seven new tables). Proof: those tests,
  changed, pass.

---

## 13. Screens and routes (thin UI)

All pages under `/p/{project}` go through the isolation gate; POSTs need an editor. Server-rendered, the
existing design tokens and `_base.html.j2`. The only JavaScript: builder search, tick all / untick all.

| route | what |
|---|---|
| `GET /p/{project}/objectives` | **Library**: "Objective sets" (built-in first, then custom active, `?retired=1` shows retired) with latest version, objective count, saved by and when; "Objective profiles" likewise with the update count (R8.7). Buttons for editors: `New objective set`, `Import CSV`, `New profile`, `Import profile`. |
| `GET /p/{project}/objectives/sets/{id}[?version=n]` | One set version: today's objectives page layout (macro groups, flags), a version list (number, saved by, when), `Export CSV`; for custom: `New version`, `Retire`; for built-in: `Make a custom copy`. |
| `GET, POST /p/{project}/objectives/sets/new`, `.../sets/{id}/edit` | Set editor (R7.5). |
| `GET, POST /p/{project}/objectives/sets/import` | CSV import (R7.3); the result page shows the created version or the no-op message or the errors. |
| `GET /p/{project}/objectives/sets/{id}/export` | R7.4. |
| `GET /p/{project}/objectives/profiles/{id}[?version=n]` | One profile version: items grouped by source set with their pinned version, update list (R8.5), `Export` (references, self-contained); custom: `Edit`, `Retire`; built-in: `Make a custom copy`. |
| `GET, POST /p/{project}/objectives/profiles/new`, `.../profiles/{id}/edit` | Profile builder (R8.3 to R8.6). |
| `GET, POST /p/{project}/objectives/profiles/import` | R9.4. |
| `GET /p/{project}/objectives/profiles/{id}/export` | R9.2. |
| `GET /p/{project}/projects` | Start form gains the profile chooser (R10.1). |
| `GET /p/{project}/projects/{id}` | Assessment page: pinned profile line and update notice (R10.2, R10.3). |
| `GET /p/{pid}/api/objective-sets[/{id}[/versions/{n}]]`, `GET /p/{pid}/api/objective-profiles[/{id}[/versions/{n}]]`, `GET /p/{pid}/api/objective-profiles/{id}/updates` | Read-only JSON of the same data (writes are the form posts). |

- **R13.1** Every route of the table exists with the stated access (member GET, editor POST, stranger 404,
  no token 401), mirrored in the gate tests like the isolation I18.2 cases. Proof: DB.
- **R13.2** Pages contain no business rule: every decision the page shows (updates, no-op, errors, display
  ids, chooser preselection) comes from a Python function with its own unit test; templates only render.
  Proof: page tests assert that each rendered decision equals the output of the service function behind it.
- **R13.3** No em dash in any template, message or doc of this work. Proof: static (grep for U+2014 in the
  changed files is empty).

---

## 14. Report renderer (RG)

- **R14.1** `data/control_objectives.py` gains `objectives(project_id, system_id)`: the pinned profile
  version's items of that assessment, in position order, each `{key, local_id, display_id, set_id,
  set_name, set_version, position, macro, legal_basis, label, objective}`, read from the project database
  (join `project` to `objective_profile_version_item` to `objective_set_version_item` to `objective` and
  `objective_set`); `[]` when there is no assessment. `mappings` and `objective_ids` return keys.
  `empty` (never `error`) when the tables are missing (isolation I9.3). Proof: renderer pytest on project
  database fixtures.
- **R14.2** `ctx.data.objectives` is built from `objectives()` (keyed by key, fields as today plus
  `display_id`), not from a CSV. `data/vocab.objective_labels`, `REPORT_OBJECTIVES_CSV_PATH`, its entry in
  `data/__init__.py` and the compose volume line for the CSV are removed. Proof: static (no reference to
  the variable), renderer pytest.
- **R14.3** Blocks print `display_id` where they printed the id, and read labels by key:
  `control_objectives`, `summary_coverage`, `key_figures`, `chart`, `changes_since` (each side's labels
  from that side's own pin: removed objectives are labelled from the older version's pin, added from the
  newer one). `requirement_groups` lists macro strings in position order. Proof: golden.
- **R14.4** For assessments pinned to `ai-act-default` v1 every golden capture is byte-identical to the
  captures made before this change (they were made from the CSV). Proof: golden.
- **R14.5** Ids read from options and from the coverage map pass through `objective_keys.qualify(oid)`:
  an id containing `:` is kept; an id matching `^R\d+\.\d+$` becomes `ai-act:<id>`; anything else is kept
  (and then matches nothing). Applies in `objective_filters.Filters` (`objectives` option), `coverage._merged`
  (links), and the `choices` of the blocks. Test vectors (shared with R15.1): `R1.1` to `ai-act:R1.1`,
  `ai-act:R1.1` unchanged, `s-0123456789ab:R1.1` unchanged, `X1` unchanged, `` unchanged. Proof: unit.
- **R14.6** `POST /v1/coverage-choices` returns `{"value": key, "label": "<display id> <label>", "group":
  macro}` in position order. Proof: renderer pytest.

## 15. Report composer (RC)

- **R15.1** `coverage_map.py` compares objective ids through the same `qualify` (a copy of the RG function
  with the same test vectors, in `report_composer/objective_keys.py`): `reference_problems`, `reset` and
  `grid` treat a stored `R1.1` as `ai-act:R1.1`. `normalised()` writes keys, so a map saved after this
  change stores only keys. Proof: RC pytest (a layout stored with `["R1.1"]` shows ticked under
  `ai-act:R1.1`; saving it stores `ai-act:R1.1`; an unknown `R99.1` is an `invalid_reference` as today).
- **R15.2** The composer's block option values (`objectives`, `links[].objective_id`) are saved as keys when
  the layout is saved (same normalisation). Proof: RC pytest.
- **R15.3** The composer still never reads another module's schema (isolation I8.5): it gets objectives only
  from the renderer's choices. Proof: existing RC test `test_pages.py` schema scan stays green.

## 16. Isolation-run artefacts this touches (TOP)

- **R16.1** The places that list what `platform` may hold gain `objective_library` owned by
  `control_objectives_rw`: `scripts/verify-project-databases.sh` (I1.4, I16.1, I16.2 checks),
  `scripts/db_consistency/checks.py` (`KNOWN_PLATFORM_SCHEMAS`, lint list), `inspector/schema-docs`
  (`PLATFORM_SCHEMAS`: `objective_library`, label "Objective library", "the built-in control objective sets
  and profiles every project may use; a project keeps its own copy of each version it uses"),
  `scripts/tests/test_project_grants.py` (the reader list for `control_objectives` gains the seven tables).
  Proof: those tests and scripts, run on a throwaway.
- **R16.2** `db_consistency` gains a check per project database: every `mapped_objective.objective_id` is an
  item of its assessment's pinned profile version, and every project copy of a built-in version has the
  library's `content_digest` (WARN when the library is unreadable). Proof: TOP `scripts/tests`.
- **R16.3** Compose (`docker-compose.development.yml`): the renderer loses the CSV volume and
  `REPORT_OBJECTIVES_CSV_PATH`; `control-objectives-migrate` runs `migrate_projects` as today (the seed is
  inside it). Proof: TOP `scripts/tests/test_compose_isolation.py` extended.

---

## 17. Edge cases and errors (collected)

| case | answer |
|---|---|
| CSV with a repeated ID, no rows, not UTF-8, over 1 MiB, over 500 rows, a bad cell | 422 with the R7.1 message, nothing stored |
| Same CSV bytes imported twice (new set or same set) | no-op message, nothing stored (R7.3) |
| Import onto a built-in or retired set | 409 (R7.3) |
| Two editors save the same set or profile at once | second gets 409, nothing stored (R5.2) |
| Set name or profile name taken by an active one (case-insensitive) | 409 `A set called <name> already exists.` / `A profile called <name> already exists.` |
| A pinned objective removed in a newer set version | `removed` update; the old pin keeps resolving (R8.5) |
| A set retired while profiles pin it | pins keep resolving; no source in the builder; no update from it (R5.4) |
| Profile references file naming another project's custom set | 422 with the missing list (R9.4) |
| Self-contained file claiming built-in wording that differs | 422 (R9.4) |
| Project copy of a built-in differs from the library | 500, nothing stored, ids logged (R6.2) |
| Seed file of a shipped version edited | seed exits 2, nothing written (R4.4) |
| Library not installed or unreachable | pickers and public routes 503; assessment pages, maps, reports work (R4.6, R6.4) |
| Model answers an objective not in the pin | `unknown-objective`, stripped (R11.4) |
| Insert of a mapping to an objective outside the pin (any path) | refused by trigger (3.3) |
| Attempt to change an assessment's profile | refused by trigger (R10.2) |
| Local id `R1.1` in two sets of one profile | display ids become keys for both on pages, prompt and report (R11.4, R14.3) |
| Two sets both use macro `R1` with different titles | grouped per set, titled with the set name (R11.1) |
| Stored bare id in a coverage map | read as `ai-act:<id>`, rewritten as a key on the next save (R15.1) |
| Project deleted | its database is dropped with its copies; the library is untouched |
| Card version deleted | its assessment is deleted (CASCADE, unchanged); profile versions stay (RESTRICT goes from assessment to profile, not the other way) |

---

## 18. Order and dependencies

| step | what | depends on |
|---|---|---|
| 0 | Isolation run merged into `feat/unified-modules` (CO submodule, TOP, and RG `dev`) | A3 |
| 1 | CO domain, pure: `objective_csv`, `objective_keys`, `pinned`, `objective_sets`, `profile_file` (unit tests only) | 0 (can start on the merged code without a database) |
| 2 | Library: `objective_library` schema in TOP `init/`, CO `alembic_library`, `seed_library`, manifest, CSV moved | 0 |
| 3 | Project revision (R12.1), tables, triggers, `builtin_copy`, `db/sets.py`, isolation test changes (R12.5) | 2 (copies need the library) |
| 4 | Services and screens (sections 5, 7 to 10, 13), scoring and mapping on the pin (section 11) | 1, 3 |
| 5 | RG renderer (section 14) and RC composer (section 15); they share the `qualify` vectors | 3 (tables to read), in parallel with 4 |
| 6 | TOP artefacts (section 16), compose | 2, 5 |
| 7 | Deploy to live, stack quiet: only after the isolation live cutover (C0 to C12) and its stage 7 drop are done, then R12.4's dump, then `control-objectives-migrate`, then CO, RG, RC images | all, plus isolation stage 7 |

Why step 7 waits for isolation stage 7: the isolation copy tool requires every target at the baseline head
(I12.6) and its `verify-dump` compares the retired `platform.control_objectives` rows with the project
databases (I12.14, I15.2). If R12.1 ran first, the copy would refuse and the verify would fail. Images
used for the isolation cutover must not contain R12.1.

---

## 19. Test strategy (for stage 2)

| requirements | suite | how |
|---|---|---|
| R3.1 to R3.3, R5.3, R7.1, R7.2, R7.4 round trip, R8.1, R8.5, R9.1, R9.3, R11.1 to R11.4, R14.5, R15.1 vectors | CO pytest unit; RG and RC pytest unit | no database; captures of today's prompt and today's priorities committed as fixtures before any code changes |
| R3.4 to R3.10, R4.*, R5.1, R5.2, R5.4, R5.5, R6.*, R7.3, R7.4 bytes, R7.5, R8.2 to R8.4, R8.6, R8.7, R9.2, R9.4, R10.*, R11.3 end to end, R12.1 to R12.3, R12.5, R13.1 | CO pytest DB | throwaway `aisc-t-*` postgres with the isolation init files; `platform` plus two project databases made by the platform template (isolation recipe); `CONTROL_OBJECTIVES_TEST_DATABASE_URL` and `PLATFORM_TEST_DATABASE_URL` always set; the drop-and-recreate fixture refuses `platform`, `postgres`, `project_*` (isolation I5.7) |
| R14.* | RG pytest and golden | project database fixtures with the new tables; golden captures re-run and compared byte for byte for `ai-act-default` v1 |
| R15.* | RC pytest | fakes of the renderer's choices, as `tests/v2_fakes.py` |
| R4.1, R16.* | TOP `scripts/tests` | throwaway; fresh volume; grants matrix |
| R3.8, R3.9, R11.5, R13.3, R14.2 | static | source scans |

---

## 20. Out of scope

- Qualification's question sets and questionnaires (D2 says the same library rule will apply there; that is
  separate work, see Deviation V4).
- Relaxing the objective id rule for custom sets (Q5), Word or Markdown import of sets, editing wording in
  place, deleting anything.
- Carrying an assessment's ratings or mappings to a new card version's assessment (not done today either).
- Re-pinning an existing assessment (Q4 DEFAULT no).
- Notifications of updates; a per-project "default profile" setting (Q8).
- Renaming `control_objectives.project` to `assessment` (Q9).
- The engine, AIRO files, the catalogue app (RULES).
- Reference resolution across projects for custom sets (Q6).

---

## 21. Deviations

- **V1 Isolation I1.3, I1.4, I16.1, I16.2** say `platform` keeps only `core`, `catalogue`, `form_library`,
  `report_library`, and list the only schemas a module role may own there. D2 requires the built-in library
  in `platform`, so `objective_library` owned by `control_objectives_rw` is added to those lists (R4.1,
  R16.1). Same reasoning as isolation D3 and D4.
- **V2 Isolation I2.6** calls its reader list exhaustive; it gains the seven new `control_objectives`
  tables (R12.1, R16.1).
- **V3 Isolation tests** `test_I5_4_one_baseline_revision` and
  `test_I5_4_the_database_is_at_the_baseline_and_readers_get_their_reads` pin a single revision; they change
  as R12.5 says. The isolation run owns them until its merge; this work changes them after.
- **V4 D2 vs the qualification spec in progress.** `BRIEF.md` D2 says the same rule (built-ins shared,
  everything user-made per project) will apply to question sets and questionnaires. The parallel spec
  `docs/superpowers/two-level-forms-2026-09-25/00-brief.md` decision 9 and isolation D3 / R47 say forms are
  install-wide and never project-scoped. They conflict; this spec follows D2 for objectives only and flags the
  conflict for the user (Q11).
- **V5 "re-importing the same bytes is a no-op"** is extended to "the same content": a file whose parsed
  content equals an existing version (for example saved again with a BOM) is also a no-op (R7.3). Same bytes
  remain a no-op.
- **V6 "the existing row validation is kept"**: kept verbatim, plus checks the database needs (duplicate IDs,
  empty file, size and length limits, R7.1). Today a repeated ID silently keeps the last row.
- **V7 A2 wording** says the copy happens "when an assessment starts on a profile version that uses built-in
  sets". It also happens when a custom profile version picks from a built-in set version (R6.1), so custom
  profiles have real FKs too.
- **V8 Isolation's O1** keeps `objectives_digest` on the assessment; this spec drops it (the pin replaces it,
  D1 allows the drop).

---

## 22. Questions for the user

- **Q1 Names (A1).** "Objective set" and "objective profile"; built-in set `ai-act` named "EU AI Act control
  objectives", built-in profile `ai-act-default` named "AI Act default". `DEFAULT (user to confirm)`.
- **Q2 Mixing.** May one custom profile pick from a built-in set and custom sets together? `DEFAULT (user to
  confirm)`: yes (R8.3).
- **Q3 A new built-in version ships.** Project copies and assessments stay as they are; the library and the
  builder show "update available"; a project gets the new version only when it uses it; new assessments
  preselect the latest built-in version when no previous assessment chose otherwise. `DEFAULT (user to
  confirm)` (R6.3, R10.1).
- **Q4 Re-pin an assessment?** May the latest card version's assessment move to a newer profile version (for
  example, keeping ratings and dropping mappings of removed objectives)? `DEFAULT (user to confirm)`: no, the
  pin is fixed; the next card version's assessment takes the new version (R10.2).
- **Q5 Id rule for custom sets.** Keep `R<n>.<n>` under an `R<n> <title>` macro for every set? `DEFAULT (user to
  confirm)`: keep (R7.2). Relaxing it later needs a model change only; the database already allows more.
- **Q6 References across projects.** A references file resolves only built-in sets and this project's own
  sets; moving a custom profile to another project needs the self-contained file. `DEFAULT (user to confirm)`:
  yes (R9.4).
- **Q7 Who edits.** Editors and owners create, version, import and retire; viewers read. `DEFAULT (user to
  confirm)` (R5.5).
- **Q8 Default profile of a project.** No stored setting; the start form preselects the previous card
  version's profile (latest version), else AI Act default. `DEFAULT (user to confirm)` (R10.1).
- **Q9 Rename** `control_objectives.project` to `assessment` while the tables are recreated anyway?
  `DEFAULT (user to confirm)`: no, keep the name (isolation D6); it would touch the renderer, grants and
  isolation tests for no behaviour.
- **Q10 Live timing.** Deploy only after the isolation cutover and its stage 7 drop (section 18). `DEFAULT
  (user to confirm)`.
- **Q11 Qualification library location (V4).** Which rule holds for question sets and questionnaires:
  D2 (user-made ones per project) or the forms decision (install-wide)? No default: this spec does not depend
  on the answer, but the two modules would behave differently.

---

## 23. Risks

1. **Ordering against the isolation cutover** (section 18): shipping R12.1 before isolation stage 7 breaks the
   copy tool and `verify-dump`. Mitigation: step 7 gate, cutover images without R12.1.
2. **"No change in results"** rests on three things holding at once: position order equal to `sort_key`
   order for `ai-act` v1, a byte-identical prompt, and display ids equal to local ids. Mitigation: R11.3 and
   R11.4 captured from today's code before any change.
3. **Isolation files change under us**: the isolation O1, P1, R2, V1 work packages are not coded yet; this
   spec names their planned files and tests. Stage 3 must re-read the merged code.
4. **Trigger-based append-only** with a session-setting escape hatch is only as strong as the role: the same
   `control_objectives_rw` role that owns the tables could set the flag. Mitigation: R3.8 source scan; a
   separate seeding role would be stronger (not proposed: it needs new roles and init changes).
5. **The `items_come_with_their_version` trigger** relies on comparing `xmin` with the 32-bit current
   transaction id; it must be tested across a wraparound-free throwaway only, and is the least conventional
   part. Fallback if stage 2 finds it unreliable: an application rule with a test, as the qualification spec
   did (its D26).
6. **The V4 conflict** could leave objectives and questions with opposite library rules.
