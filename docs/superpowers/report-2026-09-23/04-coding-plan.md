# Stage 4: Coding plan for the modular AISC report

Status: stage 4 of 5. Inputs: `RULES.md`, `01-specs.md`, `02-architecture.md` (D1 to D16, O1, O2),
`03-tests.md` and the committed failing tests (interface c743d64, mlareject 533f310, generator 6b00397,
aisc-install 17b70b4). Stage 5 follows this plan literally, group by group, in order. Each group ends
with a green checkpoint. Where this plan names a function, class, file, SQL statement or markup, that
is the name to use: the tests import those names.

## 0. Ground rules for stage 5

1. **Before every test run:** `env | grep -iE 'DATABASE|DSN|DB_URL'` must print nothing. If it prints
   anything, `unset` it. Every database suite starts its own throwaway `postgres:14-alpine` container
   `aisc-t-<label>-<hex>` through `aisc-install/scripts/lib/report_bed.py` on a kernel-chosen port and
   removes it at the end. After each run, `docker ps -a --filter name=aisc-t- --format '{{.Names}}'`
   must print nothing (remove leftovers with `docker rm -f`).
2. **Never** `docker compose up/down/build/restart/run` against the stack, never connect to
   127.0.0.1:5432 to write. `docker compose ... config` (what `scripts/tests/test_report_stack.py`
   does, on scratch copies, project `aisc-t-config`) is static and allowed.
3. **TDD:** the failing tests exist. Write code until they pass. Do not weaken or delete tests. The only
   test edits allowed are the ones listed in section 2.3 (a spec-faithful fix) and the new tests of
   step D6 (additive, written and seen failing before the code).
4. **Commits:** local only, never push. Stage files by explicit path (`git add <path>...`), never
   `git add -A` or `git add .`. Never stage `__pycache__/`, `.venv/`, `.pytest_cache/`, `*.egg-info/`.
   In aisc-install, `docker-compose.development.yml` carries someone else's uncommitted hunks
   (qualification-prefill service, PREFILL_URL): commit only the report hunks with a filtered patch
   (step F1 says how). End commit messages as the repo's history does (a plain sentence).
5. **Guard:** `cd ~/aisc-install && scripts/guard-frozen.sh` must print `GUARD PASS`. It reads the
   committed trees of aisc-install only, so run it after each aisc-install commit. A group that commits
   nothing to aisc-install cannot change its verdict: record the aisc-install HEAD sha of the last pass
   and reuse that pass when HEAD is unchanged.
6. **uv:** each repo runs its tests with `uv run --extra dev pytest -q`. After an edit to the interface
   or mlareject `pyproject.toml`, resync the dependants with
   `uv sync --extra dev --reinstall-package vera-report-plugin-interface --reinstall-package vera-report-plugin-mlareject`
   (entry points are only picked up on reinstall). `uv lock` needs network access for new dependencies.
7. **Words the tests forbid in code:** nothing under `aisc-report-generator/report_renderer/`
   (`.py`, `.j2`, `.sql`, `.html`, `.css` included) may contain `catalogue` in any case, including
   comments and column names (never select `catalogueId`, `catalogue_slug`, `catalog_perm`: use
   explicit column lists, never `SELECT *`). No `.py` file under `apps/report-composer/report_composer/`
   may contain `qualification.`, `control_objectives.`, `engine.`, `controls.`, `aisc_comment` or
   `catalogue` (watch docstrings: "the controls." fails; never name a variable `engine`).
8. **No em dashes** in any file or message.

## 1. DO NOT EDIT

- **Frozen engine and Sean's files:** everything in `aisc-install/apps/backend`, `apps/webapp`,
  `apps/eval`, `shared/plugin-interface`, `shared/plugin-manager` (submodules; G1, G4, G5).
- **AIRO:** `apps/qualification/services/ontology/airo/airo.ttl`, `.../vair.ttl`,
  `apps/qualification/src/data/airo_vocab.json` (G3; bind-mounted read-only, never copied), and the
  tables `qualification.knowledge_graph`, `qualification.qualification_risk` (read only; SELECT grants
  outside the guard's init files are all that touches them).
- **`apps/results-dashboard`** (O1: no Superset change tonight), and the rest of the submodules:
  `apps/qualification`, `apps/control-objectives`, `apps/controls`, `apps/catalogue`.
- **Guard inputs:** `init/platform-db.sql`, `init/project-databases.sql` (they must never mention
  `report_ro` or `report_composer`), `init/superset-db.sql`, `init/keycloak.sql`, `platform/migrations/*`,
  `platform/platform_service/*`, `scripts/guard-frozen.sh`, `scripts/lib/throwaway-pg.sh`,
  `scripts/pipeline_chain/*`.
- **Other people's uncommitted work:** the submodule pointer changes, the qualification-prefill hunks of
  `docker-compose.development.yml`, `scripts/verify.sh`, untracked `docs/superpowers/*` folders other
  than this one. Leave them unstaged and unchanged.
- **Stage 3's tests and fixtures:** every file under `*/tests/`, `scripts/tests/`,
  `scripts/lib/report_bed.py`, `scripts/tests/fixtures/report/*`, except the one listed fix in 2.3.
- **Legacy contract:** `aisc-report-plugin-interface/vera_report_plugin_interface/base_report_plugin.py`
  (its behaviour is pinned by `tests/test_legacy_plugin.py`; leave the file untouched) and
  `aisc-report-mlareject/.../templates/template_section.html.j2` (the legacy plugin's template).

## 2. Decisions stage 5 builds on

### 2.1 Resolving 03's notes for stage 4

| 03 note | decision |
|---|---|
| R2.4.3: the Control objectives block has no `links` option | Coverage is computed by one shared function (`report_renderer/coverage.py`) from the pinned version's data and a list of links. The links are those of the first `summary_coverage` block of the same snapshot (passed in `ctx.report.coverage_links`, taken from the snapshot, not from another block's rendering); with none, every objective is "not covered". Faithful to R2.8.3 ("computed from the data ... works even when they are absent"). |
| O1: chart block status with `NoImageProvider` | `ok` with a note (the test is right: nothing failed). `NoImageProvider.image` raises `ImagesDisabled`, a subclass of `ImagesUnavailable` (so `test_o1_no_image_provider_gives_no_image` holds); the block treats `ImagesDisabled` as "off" (status ok) and any other `ImagesUnavailable` as R2.7.6 (status error). |
| R2.6.3 count | Counts the answers of the submission shown whose `system_version_pid` differs from the pinned one, null included (D15). |
| R5.4.1 `/health` | The token is required on every route, `/health` included (the spec's literal reading). No compose healthcheck calls it. |
| Passwords | Dev defaults stay equal to the role names (`report_ro`, `report_composer_rw`). The stack sets the real ones from `REPORT_RO_PASSWORD` / `REPORT_COMPOSER_PASSWORD` through `postgres-setup` (psql `-v`), so the bed keeps working unchanged. |
| Stack tests read the working tree | Accepted. Commits still carry only the report hunks (step F1). |

### 2.2 Where a test and the spec seemed to disagree (the test is right in all of these; no test change)

1. **Free text defaults.** R1.1 wants `default_options` valid against the schema, R2.9 makes `text`
   required with no default. `validate_declaration()` validates the defaults against the schema with
   `required` removed. Same for `dashboard_chart.chart_id`.
2. **The version's own description.** The end-to-end tests expect `echo card E2MARK`, which is only in
   `core.system.description`. RULES' table says the AI card shows "the system's description at that
   version", so the AI card block shows `core.system.description` as "Version description" (when set),
   besides the qualification's description.
3. **R1.3 "exactly".** The cover needs layout name, revision and requester (R2.1.1, R2.1.2), so the
   context also carries `ctx.report` (`ReportInfo`). The listed attributes are exactly as specified.
4. **Templates strip required references.** R3.14 removes `chart_id` from a template, so a layout made
   from it cannot pass R3.5 at creation. POST with `template_id` validates with
   `allow_missing_references=True` (a missing required option that is a data reference is tolerated);
   PUT, validate and generate check fully (generate answers 422 `invalid_options` until the editor
   picks a chart).
5. **R5.1.3 vs R5.1.1.** Blocks render strictly in list order; the table of contents goes right after
   the cover's section when a cover is present, else at the top.
6. **R5.1.6 vs R2.1.3.** The document-level banner is printed only when the layout has no cover; with a
   cover, the cover carries it.
7. **R7.2.4 "3 at a time".** Blocks render one after the other; image fetches go through a
   `BoundedImages` wrapper (semaphore of 3), so the limit holds also if rendering is parallelised later.
8. **Notices are in the HTML.** The composer e2e looks for "Newer results exist for version 2." in the
   HTML, so every section prints its notices (`<ul class="notices">`) under its `<h2>`.
9. **Page breaks.** R1.5's test pins the section's classes to exactly `block block-{type}`, so
   `page_break_before` is an inline `style="break-before: page"`, not a class.

### 2.3 The one test fix (spec is right)

`aisc-report-generator/tests/test_block_control_answers.py::test_r7_2_3_at_most_1000_answers`, line 90:
`assert "and 5 more" in t` becomes `assert "and 6 more" in t`. Why: R7.2.3 caps the whole Control
answers block at 1000 answers. Beta v1 has two checklists shown, "Beta checklist BETAMARK" (1 answered
question) and "Big checklist" (1005), in title order: 1006 rows, 1000 shown, 6 more. The test assumed a
cap per checklist. The rest of the test (at most 1000 cells shown) is unchanged. Commit it on its own
(step D8) with the message given there.

### 2.4 Tests that cannot go green here

None expected. Two behaviours stay manual (they are browser-only and not tests): R4.2.3 drag and drop
and the "unsaved changes" flag, R4.2.5 progress display. If a run cannot reach the network, `uv lock`
in D0 fails: then stop and write it down (it is not a test failure).

---

## Group A: aisc-install, the report's roles and grants

### A1. Roles, composer schema, read grants, project-database template

Repo: `~/aisc-install` (branch feat/unified-modules). Create four files.

**`init/report-roles.sql`** (superuser; initdb and every `postgres-setup` start; idempotent):

```sql
-- The report's two roles and the composer's schema (report run 2026-09-23, 02 D6 (a), D13).
-- Superuser. Runs on a fresh volume from docker-entrypoint-initdb.d (60-report-roles.sql, after the
-- superset database exists) and on every start from postgres-setup, which passes the passwords as
-- psql variables. Kept out of init/platform-db.sql and init/project-databases.sql on purpose: the
-- guard dumps those two (G1/G2).
\if :{?report_ro_password}
\else
\set report_ro_password report_ro
\endif
\if :{?report_composer_password}
\else
\set report_composer_password report_composer_rw
\endif

\connect platform

SELECT 'CREATE ROLE report_ro LOGIN'
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'report_ro') \gexec
SELECT 'CREATE ROLE report_composer_rw LOGIN'
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'report_composer_rw') \gexec
SELECT format('ALTER ROLE report_ro WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
              :'report_ro_password') \gexec
SELECT format('ALTER ROLE report_composer_rw WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
              :'report_composer_password') \gexec

-- the renderer's sessions are read-only by default; its privileges are SELECT only anyway
ALTER ROLE report_ro SET default_transaction_read_only = on;

GRANT CONNECT ON DATABASE platform TO report_ro, report_composer_rw;
SELECT 'GRANT CONNECT ON DATABASE superset TO report_ro'
 WHERE EXISTS (SELECT 1 FROM pg_database WHERE datname = 'superset') \gexec

-- core: the renderer reads project and system; the composer also reads memberships
GRANT USAGE ON SCHEMA core TO report_ro, report_composer_rw;
GRANT SELECT ON core.project, core.system TO report_ro, report_composer_rw;
GRANT REFERENCES ON core.project, core.system TO report_composer_rw;
SELECT 'GRANT SELECT ON core.project_member TO report_composer_rw'
 WHERE to_regclass('core.project_member') IS NOT NULL \gexec
-- project_member is made by platform migration 0001 as platform_rw, possibly after this file ran
ALTER DEFAULT PRIVILEGES FOR ROLE platform_rw IN SCHEMA core GRANT SELECT ON TABLES TO report_composer_rw;

CREATE SCHEMA IF NOT EXISTS report_composer AUTHORIZATION report_composer_rw;
ALTER SCHEMA report_composer OWNER TO report_composer_rw;
COMMENT ON SCHEMA report_composer IS 'Step 7: report layouts, templates and generated reports.';
ALTER ROLE report_composer_rw IN DATABASE platform SET search_path = report_composer, core;
```

**`init/report-ro-grants.sql`** (superuser; idempotent; skips what does not exist):

```sql
-- SELECT for report_ro on exactly the tables the report blocks read (02 D6 (b)). Superuser, safe
-- to run again. A table that does not exist yet is skipped, so it also runs on a database without
-- module schemas. No ALTER DEFAULT PRIVILEGES on module schemas: a table added later is not
-- readable until it is listed here.
\connect platform
DO $grants$
DECLARE
    s text;
    t text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'report_ro') THEN
        RAISE EXCEPTION 'report_ro does not exist: run init/report-roles.sql first';
    END IF;
    FOREACH s IN ARRAY ARRAY['qualification', 'control_objectives', 'engine'] LOOP
        IF to_regnamespace(s) IS NOT NULL THEN
            EXECUTE format('GRANT USAGE ON SCHEMA %I TO report_ro', s);
        END IF;
    END LOOP;
    FOREACH t IN ARRAY ARRAY[
        'qualification.qualification', 'qualification.card_component',
        'qualification.knowledge_graph', 'qualification.qualification_risk',
        'control_objectives.project', 'control_objectives.risk',
        'control_objectives.mapped_objective', 'control_objectives.mapping_run',
        'engine.project', 'engine.evaluation', 'engine.evaluation_plugin', 'engine.evaluation_input',
        'engine.plugin', 'engine.ai_component', 'engine.observation', 'engine.measurement',
        'engine.metric', 'engine.artifact'] LOOP
        IF to_regclass(t) IS NOT NULL THEN
            EXECUTE format('GRANT SELECT ON %s TO report_ro', t);
        END IF;
    END LOOP;
    -- plugin_config.config may hold tool settings: only the columns that tie a run to its tool
    IF to_regclass('engine.plugin_config') IS NOT NULL THEN
        EXECUTE 'GRANT SELECT (id, plugin_id) ON engine.plugin_config TO report_ro';
    END IF;
END
$grants$;

-- superset: chart ownership and the review comments (02 D5), nothing else (never ab_user)
SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'superset') AS has_superset \gset
\if :has_superset
\connect superset
DO $grants$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['public.aisc_comment', 'public.dashboards', 'public.dashboard_roles',
                             'public.ab_role', 'public.dashboard_slices', 'public.slices',
                             'public.tables'] LOOP
        IF to_regclass(t) IS NOT NULL THEN
            EXECUTE format('GRANT SELECT ON %s TO report_ro', t);
        END IF;
    END LOOP;
END
$grants$;
\endif
```

**`scripts/report-grants.sh`** (POSIX `sh`, runs in `postgres:14-alpine` with `PGHOST PGUSER
PGPASSWORD PGDATABASE`; the bed runs it the same way with `REPORT_GRANTS_WAIT_SECONDS=5`):

```sh
#!/bin/sh
# The report-grants one-shot (report run 2026-09-23, 02 D6 (b)(c)): SELECT for report_ro on the
# tables the report reads, in the platform and superset databases and in every project database.
# Superuser, idempotent, runs on every start after the module migrations.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
WAIT=${REPORT_GRANTS_WAIT_SECONDS:-600}

until pg_isready -q; do sleep 1; done

# The engine's tables come from aisc-backend's own migrations, which no one-shot waits for.
i=0
until [ "$(psql -d platform -tAc "SELECT to_regclass('engine.measurement') IS NOT NULL")" = "t" ]; do
  i=$((i + 1))
  if [ "$i" -ge "$WAIT" ]; then
    echo "[report-grants] engine.measurement is not there after ${WAIT}s; granting what exists"
    break
  fi
  sleep 1
done

psql -v ON_ERROR_STOP=1 -d platform -f "$HERE/report-ro-grants.sql"

# Every project database: the controls tables are owned by controls_rw.
for db in $(psql -d platform -tAc "SELECT datname FROM pg_database WHERE datname ~ '^project_[0-9a-f]{32}$' ORDER BY 1"); do
  psql -v ON_ERROR_STOP=1 -d "$db" <<'SQL'
DO $grants$
DECLARE
    t text;
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO report_ro', current_database());
    IF to_regnamespace('controls') IS NOT NULL THEN
        EXECUTE 'GRANT USAGE ON SCHEMA controls TO report_ro';
        FOREACH t IN ARRAY ARRAY['checklist', 'checklist_question', 'submission',
                                 'submission_answer', 'source'] LOOP
            IF to_regclass('controls.' || t) IS NOT NULL THEN
                EXECUTE format('GRANT SELECT ON controls.%I TO report_ro', t);
            END IF;
        END LOOP;
    END IF;
END
$grants$;
SQL
  echo "[report-grants] $db"
done

# Databases made later are copies of template1: controls_rw's tables there become readable too.
psql -v ON_ERROR_STOP=1 -d template1 -c \
  "ALTER DEFAULT PRIVILEGES FOR ROLE controls_rw GRANT SELECT ON TABLES TO report_ro"
echo "[report-grants] done"
```
`chmod +x scripts/report-grants.sh`.

**`platform/project-template/0003_report.sql`** (applied by platform_rw to every project database):

```sql
-- Step 7, the report: its renderer reads this project's answers as report_ro. It may connect and
-- look into the controls schema; the SELECT on the tables comes from the report-grants one-shot
-- (controls_rw owns them) and template1's default privileges. Nothing here lets it write.
-- Skipped where report_ro does not exist (a database without the report's roles).
DO $grant$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'report_ro') THEN
        EXECUTE format('GRANT CONNECT ON DATABASE %I TO report_ro', current_database());
        EXECUTE 'GRANT USAGE ON SCHEMA controls TO report_ro';
    END IF;
END
$grant$;
```

Tests turned green (`scripts/tests/test_report_grants.py`, all): test_d6a_report_roles_sql_reruns_idempotently,
test_d6a_report_ro_logs_in_read_only, test_r6_1_report_ro_reads_core, test_r6_1_report_ro_reads_the_listed_tables
(18 params), test_d6b_plugin_config_is_readable_by_column_only, test_d6b_engine_tables_outside_the_list_are_refused
(5), test_r6_5_report_ro_never_reads_the_catalogue, test_d6b_report_ro_reads_the_superset_tables (7),
test_d6b_report_ro_does_not_read_superset_users, test_d6c_report_ro_reads_controls_of_each_project (3),
test_r6_1_every_write_is_refused (5), test_r6_1_a_write_in_a_project_database_is_refused,
test_r6_1_read_only_even_when_the_session_asks_otherwise, test_d6b_a_new_module_table_is_not_readable,
test_d6c_a_project_database_made_later_is_readable, test_d6b_grants_sql_skips_tables_that_do_not_exist_yet,
test_d13_composer_role_owns_its_schema, test_d13_composer_role_search_path, test_d13_composer_role_can_reference_core,
test_r4_4_2_composer_role_reads_memberships, test_d13_composer_role_never_writes_core,
test_r7_3_3_composer_never_reads_module_schemas (3), test_r7_3_3_composer_cannot_reach_projects_or_comments.
Also `scripts/tests/test_report_stack.py::test_d6_report_grants_files_exist` and
`::test_d6c_project_template_file_exists`.

Command:
```
cd ~/aisc-install && uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider \
    scripts/tests/test_report_grants.py \
    "scripts/tests/test_report_stack.py::test_d6_report_grants_files_exist" \
    "scripts/tests/test_report_stack.py::test_d6c_project_template_file_exists" \
    "scripts/tests/test_report_stack.py::test_d6_guard_init_files_do_not_mention_report_roles"
```
Also run the chain regression (applies the project template, now with 0003):
`cd ~/aisc-install && scripts/test-pipeline-chain.sh` (throwaway; must pass as before).

Commit (aisc-install): `git add init/report-roles.sql init/report-ro-grants.sql scripts/report-grants.sh platform/project-template/0003_report.sql`
Message: `The report's roles: report_ro reads what the blocks read, the composer owns its schema`

### Checkpoint A
The command above is green; `scripts/guard-frozen.sh` prints `GUARD PASS` (record the HEAD sha).

---

## Group B: aisc-report-plugin-interface (branch dev)

### B1. Packaging

- `pyproject.toml`: add `"jsonschema>=4.21"` to `dependencies` (keep jinja2, sqlalchemy).
- New `.gitignore`: `.venv/`, `__pycache__/`, `.pytest_cache/`, `*.egg-info/`.
- `uv lock`.

### B2. `vera_report_plugin_interface/templating.py`

```python
def validate_relative_template_path(path: str) -> str      # ValueError: empty, absolute, "..", "" part
def render_package_template(package: str, template_relative_path: str, **context) -> str
```
- Loader: `jinja2.FileSystemLoader(list(importlib.util.find_spec(package).submodule_search_locations))`;
  a missing package raises `ValueError`.
- `jinja2.Environment(loader=..., autoescape=True)` (on for every extension, `.html.j2` included).
  Cache the environment per package with `functools.lru_cache`.
- Same path rules as the legacy `_validate_relative_template_path` (reimplemented here, the legacy
  file stays untouched).

### B3. `vera_report_plugin_interface/blocks.py`

```python
SOURCES = ("platform", "qualification", "control_objectives", "engine", "controls", "superset")
STATUSES = ("ok", "empty", "stale", "error")

class InvalidBlockType(ValueError): ...

@dataclass
class BlockResult:
    html: str
    status: str
    notices: list[str] = field(default_factory=list)
    # __post_init__: status not in STATUSES -> ValueError;
    # re.search(r"<\s*(!doctype|html|body)\b", html, re.I) -> ValueError ("a fragment, not a document")

COMMON_PROPERTIES = {"title": {"type": "string", "minLength": 0, "maxLength": 200},
                     "page_break_before": {"type": "boolean"}}
COMMON_DEFAULTS = {"title": "", "page_break_before": False}

class BaseBlockRenderer(ABC):
    type_id: str; title: str; contract_version: int
    options_schema: dict; default_options: dict; reads: tuple
    choice_options: tuple[str, ...] = ()      # option names choices() answers for

    @abstractmethod
    def load(self, ctx, options): ...
    @abstractmethod
    def render(self, data, options, ctx): ...
    def choices(self, ctx, option_name) -> list[dict]: return []

    @classmethod
    def validate_declaration(cls) -> None
    @classmethod
    def full_options_schema(cls) -> dict
    @classmethod
    def full_default_options(cls) -> dict
    @classmethod
    def options_problems(cls, options: dict) -> list[dict]     # [{pointer, message}]
    def render_package_template(self, template_relative_path: str, **context) -> str
```
Rules:
- `validate_declaration`: `type_id` matches `^[a-z][a-z0-9_]*$`; `title` non-empty str;
  `contract_version` is `int`, not `bool`, `>= 1`; `options_schema` is a dict and
  `jsonschema.Draft202012Validator.check_schema` passes (SchemaError becomes InvalidBlockType);
  `default_options` is a dict valid against `options_schema` with the top-level `required` removed
  (2.2.1); `reads` is a tuple/list/set whose items are all in `SOURCES`. Every failure raises
  `InvalidBlockType` naming the field.
- `full_options_schema`: deep copy of `options_schema`; `$schema` = draft 2020-12; `type` object;
  `properties` = `{**COMMON_PROPERTIES, **own properties}`; keep the own `required` (key present only
  when non-empty) and the own `additionalProperties` (absent means allowed, as JSON Schema).
- `full_default_options`: `{**COMMON_DEFAULTS, **deepcopy(default_options)}`.
- `options_problems`: iterate `Draft202012Validator(full_options_schema()).iter_errors(options)`,
  sorted by path. A `required` error yields one problem per missing name with pointer
  `"/" + path + "/" + name` (so `/text`). Otherwise pointer = `"/" + "/".join(path)` (root is `""`).
  `message` from a short map that never echoes the value: `maximum` "must be at most {v}", `minimum`
  "must be at least {v}", `maxLength` "must be at most {v} characters", `minLength` "must be at least
  {v} characters", `enum` "must be one of {values}", `type` "must be of type {v}", `required` "is
  required", `additionalProperties` "is not an option of this block", `oneOf`/`anyOf` "is not a valid
  value"; fallback: `err.message[:200]`.
- `render_package_template`: package = `self.__class__.__module__.rsplit(".", 1)[0]` (the module itself
  when it has no dot); delegates to `templating.render_package_template`.

### B4. `vera_report_plugin_interface/tools.py`

```python
def normalise_tool_name(name: str) -> str       # upper(), remove " ", "-", "_"
def tool_keys(display_name=None, name=None, package_name=None) -> set[str]
    # normalised display_name; name; name without a trailing "EvaluationPlugin", else "Plugin";
    # package_name without the "aisc-plugin-" prefix. None / "" skipped.

class BaseToolRenderer(ABC):
    tool_names: tuple[str, ...] = ()
    @abstractmethod
    def render(self, run, ctx) -> str: ...
    def verdict(self, run): return None           # "pass" | "fail" | None
    @classmethod
    def matches(cls, plugin_row: Mapping) -> bool # any normalised tool_name in tool_keys(**row fields)
    def render_package_template(self, rel, **context) -> str   # as the block one

def _freeze(value):   # Mapping -> MappingProxyType of frozen values; list/tuple -> tuple; else value

@dataclass(frozen=True)
class ToolRun:
    evaluation: Mapping; evaluation_plugin: Mapping; tool: Mapping
    components: tuple; observations: tuple; measurements: tuple; artifacts: tuple
    # __post_init__: object.__setattr__(self, f, _freeze(getattr(self, f))) for every field
```

### B5. `vera_report_plugin_interface/__init__.py`

Export: `BaseReporterPlugin, BaseBlockRenderer, BlockResult, InvalidBlockType, SOURCES, BaseToolRenderer,
ToolRun, normalise_tool_name, tool_keys`. Append a short section to `README.md` on the two new
contracts (block renderer, tool renderer, entry-point groups `aisc_report.blocks` / `aisc_report.tools`).

Tests turned green: all of `tests/test_blocks.py` (test_r1_1_a_block_type_declares_its_contract,
test_r1_1_a_bad_declaration_is_refused x7, test_r1_1_sources_are_the_section_6_sources,
test_r5_2_1_load_and_render_are_abstract, test_r1_13_choices_is_optional_and_empty_by_default,
test_r1_4_block_result_carries_html_status_and_notices, test_r1_4_the_four_statuses_are_accepted x4,
test_r1_4_any_other_status_is_refused, test_r1_4_the_html_is_a_fragment x3,
test_r1_6_every_block_accepts_title_and_page_break_before, test_r1_6_the_common_options_validate,
test_r1_11_option_problems_name_the_field_and_the_reason, test_r1_12_block_templates_are_autoescaped_even_as_html_j2,
test_r5_2_1_a_block_renders_its_own_package_templates, test_r5_2_1_template_paths_are_relative_and_stay_inside x4)
and all of `tests/test_tools.py`; `tests/test_legacy_plugin.py` stays green.

Command: `cd ~/aisc-report-plugin-interface && uv sync --extra dev && uv run --extra dev pytest -q` (45 passed).

Commit: `git add pyproject.toml uv.lock .gitignore README.md vera_report_plugin_interface/__init__.py vera_report_plugin_interface/blocks.py vera_report_plugin_interface/tools.py vera_report_plugin_interface/templating.py`
Message: `Block and tool renderer contracts, with templates autoescaped whatever their extension`

### Checkpoint B
45 passed. Guard: aisc-install HEAD unchanged, pass from A stands.

---

## Group C: aisc-report-mlareject (branch dev)

### C1. The package imports cleanly (D9)

- `mlareject_reporter.py`: delete `import inspect` and the `print(...)` line. Nothing else changes.
- `data_loader.py`: delete the top-level `from resources.sql_alchemy import ...`; add
  `def _models(): from resources.sql_alchemy import Dataset, Measure, Metric, Observation; return ...`
  and call it at the start of `_base_rows`, `_harmful_cases` (locals with the same names). `__init__`
  still raises `RuntimeError("No database session available")` first.

### C2. Statistics and the tool renderer

`vera_report_plugin_mlareject/statistics.py`:
```python
THD = 1.5
def compute_statistics(measurements) -> dict
```
- cases = measurements whose `metric` (else `name`) is `"score"`; for each: `score`, and from
  `dimensions or {}` the keys `language`, `jailbreak`, `category`, each `"unknown"` when missing/empty.
- returns `{"nObservations": n, "languages": sorted set, "jailbreakMethods": sorted set, "categories":
  sorted set, "summary": {"total_cases": n, "empty_cases": count(score < THD), "effective_cases",
  "empty_share" (0 when n == 0), "effective_share" (0 when n == 0), "mean_score" (None when n == 0)},
  "byJailbreak", "byLanguage", "byCategory", "harmfulCases": []}`; a group is
  `{"label", "cases", "harmful_cases" (score >= THD), "empty_cases", "avg_score"}`, sorted by
  `(-avg_score, label)`.

`vera_report_plugin_mlareject/tool_renderer.py`:
```python
class MLAREJECTToolRenderer(BaseToolRenderer):
    tool_names = ("MLA-Reject",)
    def render(self, run, ctx) -> str:
        return self.render_package_template("templates/tool_section.html.j2",
                                            tool_name=run.tool.get("display_name") or "MLA-Reject",
                                            statistics=compute_statistics(run.measurements))
    # verdict: inherited (None): no pass/fail threshold is defined for MLA-Reject
```
New template `templates/tool_section.html.j2`: a copy of the "Executive Summary" and the three
aggregate tables of `template_section.html.j2`, without the `{% include 'tool_plots_subsection.html.j2' %}`
line and without the "Non-refused harmful cases" table (no prompts or responses ever).

`__init__.py`: `from .mlareject_reporter import MLAREJECTReportPlugin` and
`from .tool_renderer import MLAREJECTToolRenderer`; `__all__` both.

`pyproject.toml`: add
```toml
[project.entry-points."aisc_report.tools"]
mlareject = "vera_report_plugin_mlareject:MLAREJECTToolRenderer"

[tool.setuptools.package-data]
vera_report_plugin_mlareject = ["templates/*.j2"]
```
New `.gitignore` as in B1. `uv lock`.

Tests turned green: all of `tests/test_packaging.py` (test_d9_the_package_imports_without_the_old_generator_model,
test_d9_importing_prints_nothing, test_d9_both_plugins_are_exported, test_d9_the_legacy_plugin_without_a_session_raises,
test_d10_entry_point_in_the_tools_group, test_d10_the_installed_distribution_advertises_it,
test_d10_the_interface_comes_from_the_local_path), `tests/test_statistics.py` (6), `tests/test_tool_renderer.py` (6).

Command:
```
cd ~/aisc-report-mlareject && uv sync --extra dev --reinstall-package vera-report-plugin-interface \
    --reinstall-package vera-report-plugin-mlareject && uv run --extra dev pytest -q      # 19 passed
```
Commit: `git add pyproject.toml uv.lock .gitignore vera_report_plugin_mlareject/__init__.py vera_report_plugin_mlareject/mlareject_reporter.py vera_report_plugin_mlareject/data_loader.py vera_report_plugin_mlareject/statistics.py vera_report_plugin_mlareject/tool_renderer.py vera_report_plugin_mlareject/templates/tool_section.html.j2`
Message: `MLA-Reject renders from a run's measurements, and the package imports without the old model`

### Checkpoint C
19 passed; interface still 45 passed. Guard pass stands.

---

## Group D: aisc-report-generator (branch dev), the renderer

Needs groups A to C (the bed applies A's files; the registry loads C's entry point). All DB tests run
as `report_ro` on the bed.

Package layout to create (every module named here):

```
report_service.py                 (rewritten)
report_renderer/__init__.py
report_renderer/errors.py         new_error_ref, PlatformUnavailable, SourceUnavailable, log_block_error
report_renderer/snapshot.py       SCHEMA, validate
report_renderer/pdf.py            url_fetcher, html_to_pdf
report_renderer/superset.py       image providers, chart data, BoundedImages
report_renderer/registry.py       Registry, build_registry, DuplicateBlockType, DuplicateToolRenderer
report_renderer/context.py        Deps, ReportInfo, BlockContext, ScopedData, context_for
report_renderer/document.py       render, NotFound, InvalidSnapshot
report_renderer/coverage.py       STATUSES, Coverage, coverage_for
report_renderer/views.py          load_runs, load_answers (shared by blocks and coverage)
report_renderer/data/__init__.py  Sources
report_renderer/data/db.py        connect (the only place that opens connections)
report_renderer/data/scope.py     NotInProject, database_name, check_uuid
report_renderer/data/vocab.py     airo_labels, objective_labels
report_renderer/data/platform.py, qualification.py, control_objectives.py, engine.py, controls.py, superset_db.py
report_renderer/blocks/__init__.py            BUILTIN_BLOCKS (the nine classes, section-2 order)
report_renderer/blocks/_common.py             empty_result, finish (stale rule)
report_renderer/blocks/{cover,ai_card,risk_classification,control_objectives,test_results,
                        control_answers,dashboard_chart,summary_coverage,free_text}.py
report_renderer/blocks/templates/<type_id>.html.j2   (one per block)
report_renderer/tools/__init__.py
report_renderer/tools/generic.py              render_generic
report_renderer/tools/legacy_adapter.py       LegacyToolAdapter
report_renderer/tools/templates/generic.html.j2
report_renderer/templates/document.html.j2
report_renderer/templates/report.css
```
Data-module rule (test_r6_2): every public function defined in the six `data/<name>.py` modules has
`(project_id, system_id, ...)` first, then keyword-only `sources` and options. Helpers are
`_underscored`. `database_name` lives in `data/scope.py` and is imported into `data/controls.py`.

### D0. Packaging and repo hygiene

- `pyproject.toml` `dependencies`: `jinja2>=3.1.6`, `jsonschema>=4.21`, `psycopg[binary]>=3.1`,
  `fastapi>=0.111`, `uvicorn>=0.30`, `httpx>=0.27`, `weasyprint>=68.1`, `vera-report-plugin-interface`,
  `vera-report-plugin-mlareject` (drop `pyyaml`, `sqlalchemy`). `description = "Renders a saved report
  layout into HTML and PDF"`. Keep the dev extra and pytest settings. No build-system (the repo stays a
  virtual project; `pythonpath = ["."]` imports it).
- New `.gitignore` as in B1 (plus `reports/`).
- `uv lock && uv sync --extra dev --reinstall-package vera-report-plugin-interface --reinstall-package vera-report-plugin-mlareject`.

### D1. errors, snapshot, pdf

`errors.py`:
```python
def new_error_ref() -> str: return secrets.token_hex(4)
class PlatformUnavailable(Exception): ...        # the platform database cannot be reached (R7.1.1)
class SourceUnavailable(Exception):              # a source database cannot be reached
    def __init__(self, source: str): ...         # message "the {source} database is unreachable"; never a DSN
def log_block_error(ref, instance_id, block_type): logger.error("block %s (%s) failed, ref %s", ..., exc_info=True)
```
`snapshot.py`: `SCHEMA` (draft 2020-12): object, required `project_id, system_id, layout, blocks, mode`;
`project_id`, `system_id` strings with the uuid pattern
`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`; `layout` object
requiring `id` (string), `name` (string), `revision` (integer); `blocks` array, maxItems 50, items
object requiring `instance_id` (uuid pattern), `block_type` (string, minLength 1), `options` (object);
`mode` enum `preview`, `pdf`; `requested_by` string (optional). `validate(snapshot) -> list[dict]`
with problems `{instance_id, code, pointer, message}`: code `invalid_snapshot`, pointer as in B3
(`required` gives `/.../<name>`), `instance_id` = the block's id when the pointer is under
`/blocks/<i>` and that id is a string, else None; then `duplicate_instance_id` at `/blocks/<i>/instance_id`
for a repeated id. Never mutates the input.

`pdf.py`:
```python
class RefusedURL(ValueError): ...
class _DataResponse(weasyprint.urls.URLFetcherResponse):   # sets self.string = body
def url_fetcher(url, headers=None):
    # only "data:" URIs: parse "data:<mime>[;base64],<payload>" (base64 or percent-encoded) and
    # return _DataResponse(url, body, {"Content-Type": mime}); anything else raises RefusedURL
def html_to_pdf(html: str) -> bytes:
    return weasyprint.HTML(string=html, url_fetcher=url_fetcher, base_url=None).write_pdf()
```
No temporary files (R5.4.4).

Tests green: tests/test_errors.py::test_r1_10_an_error_ref_is_8_hex_characters; tests/test_snapshot.py (all 5,
11 items); tests/test_pdf.py (all 4, 7 items).
Command: `cd ~/aisc-report-generator && uv run --extra dev pytest -q tests/test_errors.py tests/test_snapshot.py tests/test_pdf.py`

### D2. superset providers

`superset.py`:
```python
class ImagesUnavailable(Exception): ...
class ImagesDisabled(ImagesUnavailable): ...
class NoImageProvider:        image(chart_id, width, height) -> raises ImagesDisabled("Superset screenshots are not enabled")
class FakeImageProvider:      __init__(png); image(...) -> png
class SupersetScreenshotProvider:
    __init__(self, base_url, username, password, http=None, monotonic=time.monotonic, sleep=time.sleep, timeout=30.0)
    image(chart_id, width, height) -> bytes
class BoundedImages:          __init__(inner, limit=3); image(...) under a threading.BoundedSemaphore
class ChartDataUnavailable(Exception): ...
class NoChartData:            data(chart_id) -> raises ChartDataUnavailable
class FakeChartData:          __init__(columns, rows); data(chart_id) -> {"columns": list, "rows": list}
class SupersetChartData:      __init__(base_url, username, password, http=None); data(chart_id) -> dict
def image_provider_from_env(env) -> provider
def chart_data_from_env(env) -> provider
```
- Screenshot: login `POST {base}/api/v1/security/login` json `{"username", "password", "provider": "db",
  "refresh": False}` -> `access_token` (kept for the provider's life); then one
  `GET {base}/api/v1/chart/{id}/cache_screenshot/?q=(window_size:!({w},{h}),thumb_size:!({w},{h}))`
  with `Authorization: Bearer`; take `image_url` from the JSON; poll it: 200 with an image content type
  returns the bytes; 404 or 202 sleeps 1 s; any other status raises `ImagesUnavailable`; stop and raise
  when `monotonic()` passes start + 30 s. Never call cache_screenshot twice. No message ever contains
  the password or the token. `http` defaults to `httpx.Client(timeout=30.0)`.
- `image_provider_from_env`: exactly `env.get("REPORT_CHART_IMAGES") == "superset"` gives
  `SupersetScreenshotProvider(env["REPORT_SUPERSET_URL"], env.get("REPORT_SUPERSET_USER", "aisc-report"),
  env.get("REPORT_SUPERSET_PASSWORD", ""))`; anything else `NoImageProvider()`.
- Chart data (O1): `GET {base}/api/v1/chart/{id}/data/?format=json` after the same login; returns
  `{"columns": result[0]["colnames"], "rows": result[0]["data"] as lists}`, capped at 50 rows; any
  failure raises `ChartDataUnavailable`. `chart_data_from_env`: `SupersetChartData` when
  `REPORT_SUPERSET_URL`, `REPORT_SUPERSET_USER` and `REPORT_SUPERSET_PASSWORD` are all set, else
  `NoChartData()`.

**New tests first (additive, see them fail, then implement):** append to `tests/test_superset.py`:
`test_o1_chart_data_from_the_api` (a MockTransport answering login and `/api/v1/chart/33/data/` with
`{"result": [{"colnames": ["system_version", "bias_rate"], "data": [{"system_version": 1, "bias_rate": 0.25}]}]}`,
asserting `{"columns": [...], "rows": [[1, 0.25]]}`) and `test_o1_chart_data_off_without_a_login`
(`chart_data_from_env({"REPORT_SUPERSET_URL": "http://x"})` is a `NoChartData`).

Tests green: all of tests/test_superset.py (10 existing + 2 new).
Command: `uv run --extra dev pytest -q tests/test_superset.py`

Commit D1+D2 together (after both green):
`git add pyproject.toml uv.lock .gitignore report_renderer/errors.py report_renderer/snapshot.py report_renderer/pdf.py report_renderer/superset.py tests/test_superset.py`
Message: `The renderer's snapshot check, data-only PDF fetcher and chart image providers (screenshots off unless asked)`

### D3. Registry and the nine block declarations

`registry.py`:
```python
class DuplicateBlockType(RuntimeError): ...
class DuplicateToolRenderer(RuntimeError): ...
class Registry:
    def register_block(self, cls, origin: str) -> None
    def register_tool(self, cls, origin: str) -> None
    def register_legacy(self, cls, origin: str) -> None
    def block(self, type_id) -> type | None
    def block_types(self) -> list[type]                   # registration order
    def tool_for(self, plugin_row: Mapping) -> object | None
    def tool_names(self) -> list[str]
def build_registry(builtins=True, entry_points=None, plugin_dirs=()) -> Registry
```
- `register_block`: `cls.validate_declaration()`; a second class with the same `type_id` logs
  `logger.error` and raises `DuplicateBlockType(f"block type {type_id!r} is declared twice: by {first_origin} and by {origin}")`.
- `register_tool`: keys = normalised `tool_names`; overlap with a registered tool renderer raises
  `DuplicateToolRenderer` naming both origins.
- `register_legacy`: key = normalised class name without the trailing `ReportPlugin`; a second legacy
  plugin with that key raises `DuplicateToolRenderer`.
- `tool_for(row)`: keys = `tool_keys(row.get("display_name"), row.get("name"), row.get("package_name"))`;
  first tool renderer whose keys intersect returns `cls()`; else a legacy class whose key is in keys
  returns `LegacyToolAdapter(cls)`; else None. (R5.3.4: tool renderers win.)
- `build_registry`: builtins register `BUILTIN_BLOCKS` with `origin=cls.__module__`
  (e.g. `report_renderer.blocks.cover`). `entry_points=None` means
  `importlib.metadata.entry_points(group="aisc_report.blocks")` plus `group="aisc_report.tools"`;
  a given list is used as is, each routed by `ep.group`. `ep.load()` failing logs
  `logger.warning("skipping report plugin %s: %s", ep.value, exc)` and continues; registration errors
  are not caught. Origin of an entry point = `ep.value`.
- Plugin directories: for each dir, each `*.py` file (sorted) and each subpackage (a dir with
  `__init__.py`, as the old `src/plugin_registry.py`): import it under a unique module name with
  `importlib.util.spec_from_file_location`; an import error logs a warning and skips. Register every
  class defined in that module (`obj.__module__ == module.__name__`): non-abstract `BaseBlockRenderer`
  subclasses as blocks, `BaseToolRenderer` subclasses as tools, `BaseReporterPlugin` subclasses whose
  name ends with `ReportPlugin` as legacy. Origin = the file path.

`tools/legacy_adapter.py`:
```python
class LegacyToolAdapter:                        # not a BaseToolRenderer on purpose (R5.3.4 test stays meaningful)
    def __init__(self, cls): ...
    def render(self, run, ctx) -> str:          # cls(db_session=None).generate_content(run=run, tool_plots={});
                                                # a result starting with "[ERROR]" raises RuntimeError
    def verdict(self, run): return None
```

Block declarations (`blocks/*.py`, class name in CamelCase + `Block`, all `contract_version = 1`).
Own `options_schema` is `{"type": "object", "additionalProperties": False, "properties": {...}}` plus
`required` where stated. `x-aisc-reference: true` only where marked.

| type_id | title | properties (own) | default_options | reads | choice_options |
|---|---|---|---|---|---|
| cover | Cover | report_title str 1..200; subtitle str 0..300; show_logo bool; show_generated_by bool | as R2.1 | platform | () |
| ai_card | AI card | show_components, show_tags, show_graph_stats bool | True, True, False | platform, qualification | () |
| risk_classification | Risk classification | show_chains, show_impact_areas bool; stated_risk_class enum not_determined, prohibited, high, limited, minimal | True, True, "not_determined" | platform, qualification | () |
| control_objectives | Control objectives | group_by enum objective, risk; show_rationale, show_quotes, show_status bool | "objective", True, False, True | platform, control_objectives, engine, controls | () |
| test_results | Test results | evaluations {x-aisc-reference, oneOf [const "all", array of uuid-pattern strings, uniqueItems]}; tools {oneOf [const "all", array of strings minLength 1]}; statuses array of enum Done, Failed, Archived, Pending, Processing, Custom, minItems 1; show_measurements, show_artifacts bool | "all", "all", ["Done"], True, False | platform, engine | evaluations, tools |
| control_answers | Control answers | checklists {x-aisc-reference, oneOf [const "all", array of strings]}; show_unanswered, show_scores, include_archived bool | "all", True, True, False | platform, controls | checklists |
| dashboard_chart | Dashboard chart | chart_id {integer, minimum 1, x-aisc-reference}; show_comments, include_replies bool; width integer 400..1600; height integer 300..1200; required [chart_id] | True, True, 1200, 700 (no chart_id) | superset | chart_id |
| summary_coverage | Summary and coverage | links {array, maxItems 200, x-aisc-reference, items object additionalProperties false, required [objective_id], objective_id str minLength 1, tests array of str, checklists array of str}; show_uncovered_only bool | [], False | platform, control_objectives, engine, controls | links.objective_id, links.tests, links.checklists |
| free_text | Free text | text str 1..20000; required [text] | {} | () | () |

In D3 the `load`/`render` bodies may be `raise NotImplementedError` (filled in D5 to D10);
`blocks/__init__.py` lists `BUILTIN_BLOCKS = [CoverBlock, AiCardBlock, RiskClassificationBlock,
ControlObjectivesBlock, TestResultsBlock, ControlAnswersBlock, DashboardChartBlock, SummaryCoverageBlock, FreeTextBlock]`.

Tests green: all of tests/test_registry.py (19 functions).
Command: `uv run --extra dev pytest -q tests/test_registry.py`
Commit: `git add report_renderer/__init__.py report_renderer/registry.py report_renderer/tools report_renderer/blocks`
Message: `The registry: nine built-in block types, plugins from entry points and the plugin directory, duplicates refused`

### D4. Sources, scope, platform data, context, document

`data/__init__.py`:
```python
@dataclass(frozen=True)
class Sources:
    platform_dsn: str = field(repr=False)
    superset_dsn: str = field(repr=False)
    project_db_template: str = field(repr=False)
    airo_vocab_path: str
    objectives_csv_path: str
    superset_url: str | None = None           # link base for charts
    @classmethod
    def from_env(cls, env) -> "Sources"       # REPORT_PLATFORM_DATABASE_URL, REPORT_SUPERSET_DATABASE_URL,
                                              # REPORT_PROJECT_DB_URL, REPORT_AIRO_VOCAB_PATH, REPORT_OBJECTIVES_CSV_PATH,
                                              # superset_url = REPORT_SUPERSET_PUBLIC_URL or REPORT_SUPERSET_URL or None;
                                              # a missing required name raises ValueError naming the variable only
    def project_dsn(self, database: str) -> str   # template.replace("{database}", database)
```
`data/db.py`: `@contextmanager def connect(dsn, source: str)`: `psycopg.connect(dsn, row_factory=dict_row,
autocommit=True, connect_timeout=5)`; `psycopg.OperationalError` at connect raises
`SourceUnavailable(source)` (from None: never the DSN in a message or log).

`data/scope.py`:
```python
class NotInProject(LookupError): ...
def check_uuid(value) -> str          # lowercase str(uuid.UUID(value)); ValueError otherwise
def database_name(pid) -> str         # "project_" + uuid hex; must match ^project_[0-9a-f]{32}$ else ValueError
```
`data/platform.py` (all on the platform DSN):
```python
def pinned_system(project_id, system_id, *, sources) -> dict
    # SELECT pid::text, project_id::text, number, name, version, provider, description, created_at
    #   FROM core.system WHERE pid = %(s)s AND project_id = %(p)s ; none (or a non-uuid) -> NotInProject
def project(project_id, system_id, *, sources) -> dict       # SELECT pid::text, name, slug FROM core.project WHERE pid = %(p)s
def newer_versions(project_id, system_id, *, sources) -> list[dict]
    # SELECT pid::text, number FROM core.system WHERE project_id = %(p)s
    #   AND number > (SELECT number FROM core.system WHERE pid = %(s)s AND project_id = %(p)s) ORDER BY number
def database_exists(project_id, system_id, *, sources, name) -> bool   # SELECT 1 FROM pg_database WHERE datname = %s
```
`data/vocab.py`: `airo_labels(path) -> {"affected": {id: label}, "impactArea": {id: label}}`;
`objective_labels(path) -> {ID: {"macro": Macro_Requirement, "legal_basis": Legal_Basis,
"label": Sub_Requirement_Label, "objective": Control_Objective}}` (csv, `utf-8-sig`); both
`functools.lru_cache`.

`context.py`:
```python
@dataclass
class Deps:
    registry: Registry; sources: Sources; images: object; clock: Callable[[], datetime]
    chart_data: object | None = None; logo: tuple[str, bytes] | None = None     # (mime, bytes)
    @classmethod
    def from_env(cls, env) -> "Deps"
        # registry = build_registry(plugin_dirs=[p for p in env.get("REPORT_PLUGIN_PATH", "").split(":") if p]);
        # sources = Sources.from_env(env); images = image_provider_from_env(env);
        # chart_data = chart_data_from_env(env); clock = lambda: datetime.now(timezone.utc);
        # logo from REPORT_LOGO_PATH when that file exists (image/svg+xml or image/png by extension)

@dataclass(frozen=True)
class ReportInfo: layout_id: str | None; layout_name: str; revision: int | None; requested_by: str; coverage_links: tuple

@dataclass(frozen=True)
class BlockContext:
    project_id: str; project: Mapping; system: Mapping; newer_versions: tuple[int, ...]
    generated_at: datetime; mode: str; data: "ScopedData"; report: ReportInfo

class ScopedData:
    # attributes: project_id, system_id (str), system_number (int), newer (tuple of {"pid", "number"}),
    # sources, images (BoundedImages(deps.images, 3)), chart_data (deps.chart_data or NoChartData()),
    # tools (the registry), superset_url, logo, vocab (airo_labels), objectives (objective_labels)
    # and one bound accessor per data module: platform, qualification, control_objectives, engine,
    # controls, superset_db; `ctx.data.engine.evaluations(statuses=...)` calls
    # engine.evaluations(project_id, system_id, sources=sources, statuses=...)

def context_for(project_id, system_id, *, deps, mode="preview", layout=None, requested_by="",
                coverage_links=()) -> BlockContext
    # pinned_system first (NotInProject propagates); SourceUnavailable("platform") -> PlatformUnavailable;
    # then project, newer_versions; generated_at = deps.clock()
```

`document.py`:
```python
class NotFound(LookupError): ...
class InvalidSnapshot(ValueError): problems: list
def render(snapshot: dict, deps: Deps) -> dict
```
1. `problems = snapshot.validate(s)`; problems raise `InvalidSnapshot(problems)`.
2. `coverage_links` = options.links of the first `summary_coverage` block (default ()).
3. `ctx = context_for(...)`; `NotInProject` raises `NotFound` (before any block is loaded).
4. For each block, in list order, `_render_block(b, ctx, deps)`:
   - `cls = registry.block(type)`; None: status error, notice `Unknown block type: {type}.`, error box.
   - `options = {**cls.full_default_options(), **b["options"]}`; `cls.options_problems(options)`
     non-empty: status error, one notice per problem `Invalid options: {pointer without leading "/"}: {message}`,
     error box, **no load**.
   - `inst = cls(); data = inst.load(ctx, options); result = inst.render(data, options, ctx)`; any
     exception (or a non-BlockResult): `ref = new_error_ref()`, `log_block_error(ref, ...)`, status
     error, box `This section could not be rendered (ref {ref}).`, the traceback only in the log.
   - title = `options["title"]` or `cls.title` (unknown type: the type id).
   - log `logger.info("block %s %s %s", instance_id, block_type, status)` (ids only, R7.1.2).
5. Wrap each (template `templates/document.html.j2`, autoescape via `templating.render_package_template("report_renderer", ...)`):
   ```html
   <section class="block block-{{ type_id }}" id="block-{{ instance_id }}" data-status="{{ status }}"{% if page_break %} style="break-before: page"{% endif %}>
     <h2>{{ title }}</h2>
     {% if notices %}<ul class="notices">{% for n in notices %}<li>{{ n }}</li>{% endfor %}</ul>{% endif %}
     {{ html }}            {# Markup(result.html) #}
   </section>
   ```
   Error box html: `<div class="error-box"><p>{{ message }}</p></div>`.
6. Document: `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{{ layout name }}</title>
   <style>{{ css }}</style></head><body>`, then, when `ctx.newer_versions` is non-empty and no block
   is a `cover`, `<div class="banner">This report covers version {p}. Version {max newer} is newer.</div>`
   (one line of text, no tags inside), then the sections; when there are more than 3 blocks,
   `<nav id="toc"><h2>Contents</h2><ol><li><a href="#block-{iid}">{title}</a></li>...</ol></nav>`
   (every block but covers) right after the first cover's section, or before the first section when
   there is no cover. No element other than sections and the TOC carries an `id`. No `<link>`.
7. CSS = `report.css` read from disk plus a page rule built in Python:
   `@page { size: A4; margin: 22mm 16mm 20mm 16mm; @top-left { content: <css string "{project name}, Version {n}">; font-size: 9pt }
   @bottom-right { content: "Page " counter(page) " of " counter(pages); font-size: 9pt } }`. The CSS
   string escapes `\` and `"`, turns newlines into spaces and `<` into `\3c `; the whole CSS is passed
   as `Markup` (it is inside `<style>`, HTML escaping would break it).
8. `block_statuses = [{"instance_id", "block_type", "status", "notices"}]` in order.
9. `mode == "preview"`: return `{"html", "block_statuses"}`. `mode == "pdf"`: `pdf = html_to_pdf(html)`,
   return `{"pdf_base64": b64, "sha256": sha256(pdf).hexdigest(), "block_statuses"}`.

`templates/report.css`: `resources/templates/l-aif_style.css` followed by
`resources/templates/report_style.css` without its `@import` line, then rules for `.block`,
`.notices`, `.error-box`, `.banner`, `#toc`, tables, `.comments ul` (indent replies). It must not contain
the word the tests forbid (checked: neither source file does).

`blocks/_common.py`:
```python
def newer_notice(number) -> str: return f"Newer results exist for version {number}."
def empty_result(text: str) -> BlockResult      # BlockResult(html=f'<p class="placeholder">{escape(text)}</p>', status="empty")
def finish(html, notices, *, newest_newer: int | None, status="ok") -> BlockResult
    # status ok and newest_newer set -> "stale" with newer_notice(newest_newer) appended first
```
In this step implement `FreeTextBlock` (it is needed by the document tests):
- `load` returns None. `render`: split `options["text"]` on `\n\s*\n`; each paragraph:
  `Markup("<br>").join(escape(line) for line in para.split("\n"))` in `<p>...</p>`. Status always ok,
  never stale.

And a minimal `CoverBlock` render sufficient for the document tests is D5's full one: implement it
fully in D5, but D4's TOC tests need a cover, so run test_document after D5 if it is not ready yet.

Tests green after D4 (+ D5 cover): tests/test_document.py (all 20 functions),
tests/test_data_access.py::test_r6_2_every_data_function_takes_project_and_system_first[platform],
::test_r6_2_a_system_of_another_project_raises_not_in_project, ::test_d1_the_project_database_name_is_validated,
::test_r6_1_sources_from_the_environment, ::test_r6_1_the_renderers_role_cannot_write,
::test_r6_5_the_renderer_never_names_the_catalogue, ::test_r7_1_1_an_unreachable_platform_fails_the_render;
tests/test_block_free_text.py (3).
Command: `uv run --extra dev pytest -q tests/test_document.py tests/test_data_access.py tests/test_block_free_text.py`
(the rest of test_data_access turns green as the other data modules land).
Commit: `git add report_renderer/data report_renderer/context.py report_renderer/document.py report_renderer/templates report_renderer/blocks/_common.py report_renderer/blocks/free_text.py report_renderer/blocks/templates/free_text.html.j2`
Message: `A snapshot becomes one document: blocks in order, each in its section, errors boxed, table of contents and running header`

### D5. Cover, AI card, risk classification

**cover** (`load` returns `{"logo": ctx.data.logo}`); template shows, in this order: `report_title`,
`subtitle` if set, project name, system name, `Version {number}` plus ` ({version})` only when
`core.system.version` is set, `Provider: {provider}` only when set, `Generated {YYYY-MM-DD}` from
`ctx.generated_at` (UTC), `Layout: {layout_name}, revision {n}`; `Generated by {requested_by}` in pdf
mode and `Generated by: preview` in preview mode, only when `show_generated_by`; when newer versions
exist, `<p class="banner">This report covers version {p}. Version {max} is newer.</p>`; logo as a
`data:` `<img>` only when `show_logo` and a logo is configured. Status always `ok`.

**ai_card** (`data/qualification.py`, platform DSN, joins scoped by `q.project_id = %(p)s AND q.system_id = %(s)s`):
```python
def card(project_id, system_id, *, sources) -> dict | None
    # id, "systemName", "systemVersion", company, description, "targetUseCase", "targetUsers",
    # "intendedDeployers", "targetSystemTags", "sectorTags", "marketFormTags", "localityTags" (aliased snake_case)
def components(project_id, system_id, *, sources) -> list[dict]
    # c.name, c.component_type, c.airo_property, c.object_name FROM card_component c JOIN qualification q
    #   ON q.id = c.qualification_id ... ORDER BY c.linked_at, c.name
def knowledge_graph(project_id, system_id, *, sources) -> dict | None
    # k.digest, k.jsonld, k.nodes, k.triples, k.built_at JOIN ON q.id = k."qualificationId"
def risks(project_id, system_id, *, sources) -> list[dict]
    # r.position, r.risk, r.source, r.vulnerability, r.consequence, r.affected, r."impactAreas", r.control,
    #   r."followUpControl" JOIN ON q.id = r."qualificationId" ORDER BY r.position
def newest_newer_card(project_id, system_id, *, sources) -> int | None
    # SELECT max(s.number) FROM qualification.qualification q JOIN core.system s ON s.pid = q.system_id
    #  WHERE q.project_id = %(p)s AND s.project_id = %(p)s
    #    AND s.number > (SELECT number FROM core.system WHERE pid = %(s)s)
```
Render: no card: `empty_result(f"No AI card for version {n}.")`. Else a definition list: System
(`systemName`), Company, Description, Target use case, Target users, Intended deployers (if set),
Version description (`ctx.system["description"]`, if set; 2.2.2); tags (`show_tags`): Target system,
Sector, Market form, Locality, each group omitted when empty; components (`show_components`): table
Name, Type, AIRO property, Object, one `<tr>` per row; graph stats (`show_graph_stats` and a graph):
Nodes, Triples (each value in its own `<td>`), Digest `digest[:12]`, Built `YYYY-MM-DD`.
`finish(..., newest_newer=newest_newer_card)`.

**risk_classification**: load card, knowledge graph, risks, vocab.
- Operators from JSON-LD (`json.loads(jsonld)`): nodes = `@graph` list or the document itself;
  expand a `prefix:term` key or type with the document's `@context` mapping when present; the system
  node is the one whose `@type` (string or list) contains `https://w3id.org/airo#AISystem`; provider =
  values of `https://w3id.org/airo#isProvidedBy`, deployer = `#isDeployedBy`, users = `#hasAIUser`
  (a value is `{"@id"}`, a string, or a list of those); each is shown by the `rdfs:label`
  (`http://www.w3.org/2000/01/rdf-schema#label`, string or `{"@value"}`) of the node with that `@id`,
  else the IRI. Malformed JSON-LD gives no operators (no error).
- Risk class: `not_determined` shows `Not determined`; any other value
  `{value} (stated by the report editor; the qualification does not classify risk)`.
- Chains (`show_chains`): table in position order: Risk, Source, Vulnerability, Consequence,
  Affected (`vocab["affected"].get(id, id)`), Impact areas (only with `show_impact_areas`: labels via
  `vocab["impactArea"]`, raw id when unknown), Control, Follow-up control.
- Empty when no operator, no chain and class `not_determined`; with no card but a stated class: ok,
  with the class and `No AI card for version {n}.` as a paragraph.
- `finish(..., newest_newer=newest_newer_card)`.

Tests green: tests/test_block_cover.py (9), tests/test_block_ai_card.py (8), tests/test_block_risk.py (10),
test_data_access::test_r6_2_...[qualification].
Command: `uv run --extra dev pytest -q tests/test_block_cover.py tests/test_block_ai_card.py tests/test_block_risk.py tests/test_document.py`
Commit: `git add report_renderer/blocks/cover.py report_renderer/blocks/ai_card.py report_renderer/blocks/risk_classification.py report_renderer/blocks/templates/cover.html.j2 report_renderer/blocks/templates/ai_card.html.j2 report_renderer/blocks/templates/risk_classification.html.j2 report_renderer/data/qualification.py report_renderer/data/vocab.py`
Message: `Cover, AI card and risk classification blocks, read for the pinned version only`

### D6. Engine data, runs and the Test results block

`data/engine.py` (platform DSN; every query joins `engine.evaluation e JOIN engine.project pr ON pr.id =
e.project_id WHERE pr.project_id = %(p)s`, and, except the unversioned count, `AND e.system_id = %(s)s`;
explicit columns only, `plugin_config` only by `pc.id` and `pc.plugin_id`):
```python
def evaluations(project_id, system_id, *, sources, statuses=None, pids=None) -> list[dict]
    # e.id, e.pid::text, e.status, e.created_at ... AND (%(st)s::text[] IS NULL OR e.status = ANY(%(st)s))
    #   AND (%(pids)s::uuid[] IS NULL OR e.pid = ANY(%(pids)s)) ORDER BY e.created_at, e.id
def runs(project_id, system_id, *, sources, evaluation_ids) -> list[dict]
    # ep.id, ep.pid::text, ep.name, ep.status, ep.evaluation_id, pl.display_name, pl.name AS plugin_name,
    #   pl.package_name, pl.version  FROM engine.evaluation_plugin ep JOIN (scoped evaluation) ...
    #   LEFT JOIN engine.plugin_config pc ON pc.id = ep.plugin_config_id LEFT JOIN engine.plugin pl ON pl.id = pc.plugin_id
    #   WHERE e.id = ANY(%(ids)s) ORDER BY ep.evaluation_id, ep.id
def inputs(project_id, system_id, *, sources, run_ids) -> list[dict]
    # ei.evaluation_plugin_id, c.name, c.component_type FROM engine.evaluation_input ei JOIN engine.ai_component c ...
def observations(project_id, system_id, *, sources, evaluation_ids) -> list[dict]   # o.id, o.evaluation_id, o.tool
def measurements(project_id, system_id, *, sources, observation_ids) -> list[dict]
    # m.observation_id, m.name, mt.name AS metric, m.score, m.unit, m.uncertainty, m.dimensions, m.direction
    #   JOIN engine.metric mt ON mt.id = m.metric_id (scoped through observation and evaluation) ORDER BY m.observation_id, m.id
def artifacts(project_id, system_id, *, sources, run_ids) -> list[dict]             # a.evaluation_plugin_id, a.name, a.file_size
def unversioned_count(project_id, system_id, *, sources) -> int                    # AND e.system_id IS NULL, any status
def newest_newer_evaluation(project_id, system_id, *, sources) -> int | None      # max core.system.number > pinned, any status
def evaluation_choices(project_id, system_id, *, sources) -> list[dict]           # every status: {"value": pid, "label": "a2e00000 · Done · 2026-09-10"}
def tool_choices(project_id, system_id, *, sources) -> list[dict]                 # distinct pl.display_name of the version's runs (plugin rows only)
```
(Label separator: use " | " rather than a middle dot if the font is a concern; the test only needs a
non-empty label.)

`views.py`:
```python
@dataclass
class RunView: tool: dict; components: list; status: str; run: ToolRun; artifacts: list
@dataclass
class EvaluationView: evaluation: dict; runs: list[RunView]; unmatched: list[dict]; unmatched_count: int
@dataclass
class RunsView: evaluations: list[EvaluationView]; skipped: int; unversioned: int
def load_runs(ctx, *, statuses, evaluation_pids=None, tools=None) -> RunsView
```
- `evaluation_pids` "all" or a list: skipped = requested pids not found for this project and version.
- tool of a run: the plugin row, else `{"display_name": ep.name, "name": ep.name, "package_name": None,
  "version": None}`.
- observations of a run (D8): those of its evaluation with `tool == f"{package_name}::{plugin_name} (v{version})"`;
  when the run has no plugin row or nothing matched and the evaluation has exactly one run, all of the
  evaluation's observations; the evaluation's observations taken by no run are `unmatched`
  (their measurements), counted in `unmatched_count`.
- `tools` "all" or names: a run is kept when `normalise_tool_name(name) in tool_keys(...)` for some
  name; an evaluation left with no run is dropped when `tools` is a list.
- `ToolRun(evaluation={pid, status, created_at}, evaluation_plugin={pid, name, status}, tool,
  components=[{name, component_type}], observations=[{id, tool}], measurements=[{name, metric, score,
  unit, uncertainty, dimensions, direction}], artifacts=[{name, file_size}])`.

`tools/generic.py`: `render_generic(measurements, limit=500) -> Markup` (template
`tools/templates/generic.html.j2`): table header Metric, Value, Unit; one row per measurement with
exactly one `<td>` holding the metric name (`metric` else `name`), value `f"{score:g}"`, unit or empty;
after `limit` rows `<p class="more">and {k} more</p>`.

**test_results** block:
- `load`: `load_runs(ctx, statuses=options["statuses"], evaluation_pids=options["evaluations"], tools=options["tools"])`,
  `newest_newer_evaluation`.
- `render`: no evaluation: `empty_result(f"No test results for version {n}.")`. Else per evaluation
  (created_at order): heading `Evaluation {pid[:8]}`, status, date `YYYY-MM-DD`; per run: tool
  `display_name`, components `name (component_type)` joined with ", ", run status; then the tool
  section: `renderer = ctx.data.tools.tool_for(tool)`; with a renderer: `Markup(renderer.render(run, ctx))`,
  on any exception `ref = new_error_ref()`, log it, notice `The {tool} renderer failed (ref {ref}).`,
  and `render_generic` instead (only if `show_measurements`); without one: notice
  `No dedicated renderer for {tool}; showing raw measurements.` and `render_generic(run.measurements)`
  if `show_measurements`. `show_artifacts`: `<li>{name} ({file_size} bytes)</li>`, never content.
  Unmatched: notice `{k} observations could not be tied to a tool.` and, with `show_measurements`, one
  generic table of those measurements per evaluation.
- notices: skipped `{k} selected evaluations are not of this project and version and are not shown.`;
  `{u} evaluations are not tied to a version and are not shown.` when u > 0.
- `finish(..., newest_newer=newest_newer_evaluation)`.
- `choices(ctx, "evaluations")` = `evaluation_choices`, `"tools"` = `tool_choices`, other names [].

Tests green: tests/test_block_test_results.py (20), test_data_access::test_r6_2_...[engine].
Command: `uv run --extra dev pytest -q tests/test_block_test_results.py`
Commit: `git add report_renderer/data/engine.py report_renderer/views.py report_renderer/tools/generic.py report_renderer/tools/templates/generic.html.j2 report_renderer/blocks/test_results.py report_renderer/blocks/templates/test_results.html.j2`
Message: `Test results: each evaluation of the version, its plugin runs and their tool renderers, with a generic table as fallback`

### D7. Controls data and the Control answers block

`data/controls.py` (`from .scope import database_name`; project database named `database_name(project_id)`,
checked with `platform.database_exists` first; missing: the functions return `None`):
```python
def checklists(project_id, system_id, *, sources) -> list[dict] | None
    # c.id, c.title, c."controlTopic" AS control_topic, s.name AS source_name FROM controls.checklist c
    #   LEFT JOIN controls.source s ON s.id = c."sourceId" ORDER BY c.title, c.id
def submissions_with_answers(project_id, system_id, *, sources, include_archived) -> list[dict] | None
    # sub.id, sub."checklistId", sub.label, sub.status::text, sub.version FROM controls.submission sub
    #  WHERE EXISTS (SELECT 1 FROM controls.submission_answer a WHERE a."submissionId" = sub.id
    #                  AND a.system_version_pid = %(s)s)
    #    AND (%(arch)s OR sub.archived_at IS NULL) ORDER BY sub."checklistId", sub.version DESC
def questions(project_id, system_id, *, sources, checklist_ids) -> list[dict]      # ORDER BY "checklistId", "order"
def answers(project_id, system_id, *, sources, submission_ids) -> list[dict]
    # "submissionId", "questionId", answer, score, system_version_pid::text
def newest_newer_answer(project_id, system_id, *, sources, newer) -> int | None
    # SELECT DISTINCT system_version_pid::text FROM controls.submission_answer
    #  WHERE system_version_pid = ANY(%(pids)s::uuid[]); map pid -> number from `newer`; max
def checklist_choices(project_id, system_id, *, sources) -> list[dict]             # [{"value": id, "label": title}], [] when no database
```
`views.load_answers(ctx, *, checklists="all", include_archived=False) -> AnswersView` with, per
checklist (title order) that has a submission for the version: the highest-version submission, its
questions in order, answer per question (only answers stamped with the pinned pid count),
`other_version_answers` (stamped otherwise or null), `answered`, `total`, `mean` (non-null scores,
`round(x, 1)`); plus `missing_db`, `unknown_checklists` (listed ids not in this database).

**control_answers** block: no database or nothing for the version: `empty_result(f"No control
answers for version {n}.")`. Per checklist: title, source name, control topic, submission label,
status, `version {v}`; table Question, Article, Answer, Score (score only with `show_scores`);
unanswered rows show `Not answered` unless `show_unanswered` is false (then omitted); with
`show_scores` `Mean score {mean}` and `answered {a} of {q}`. Block-wide cap 1000 rows (2.3): after
the cap `<p class="more">and {k} more</p>`. Notices `{k} answers were given for other versions and are
not shown.` (sum over shown submissions, when k > 0) and, for listed ids not found,
`{k} selected checklists are not in this project and are not shown.`
`finish(..., newest_newer=newest_newer_answer)`. `choices(ctx, "checklists")` = `checklist_choices`.

Test fix of 2.3 in `tests/test_block_control_answers.py` line 90.

Tests green: tests/test_block_control_answers.py (13), test_data_access::test_r6_2_...[controls].
Command: `uv run --extra dev pytest -q tests/test_block_control_answers.py`
Commits (two):
1. `git add tests/test_block_control_answers.py`, message: `Test fix: the Control answers cap is 1000 rows per block (R7.2.3), so Beta v1 shows 1000 of 1006`
2. `git add report_renderer/data/controls.py report_renderer/views.py report_renderer/blocks/control_answers.py report_renderer/blocks/templates/control_answers.html.j2`,
   message: `Control answers: the latest submission of each checklist answered for the version, other versions left out`

### D8. Objectives data, coverage, Control objectives and Summary blocks

`data/control_objectives.py` (platform DSN, scoped by `a.project_id = %(p)s AND a.system_id = %(s)s`):
```python
def assessment(project_id, system_id, *, sources) -> dict | None       # id, name FROM control_objectives.project a
def mappings(project_id, system_id, *, sources) -> list[dict]
    # r.risk_id, r.position, r.text, r.short_label, m.objective_id, m.quote, m.rationale
    #   FROM control_objectives.risk r JOIN control_objectives.project a ON a.id = r.project_id
    #   LEFT JOIN control_objectives.mapped_objective m ON m.risk_row_id = r.id ORDER BY r.position, m.objective_id
def mapping_run(project_id, system_id, *, sources) -> dict | None      # mr.stop, mr.ran_at (D14: one per assessment)
def newest_newer_assessment(project_id, system_id, *, sources) -> int | None
def objective_ids(project_id, system_id, *, sources) -> list[str]      # distinct, sorted
```
`coverage.py`:
```python
STATUSES = ("evidence", "evidence, attention", "no evidence", "not covered")
@dataclass(frozen=True)
class Coverage: objective_id: str; status: str; tests: tuple; checklists: tuple   # (name, has_data), (id, title, has_data, mean)
def coverage_for(ctx, objective_ids, links) -> dict[str, Coverage]
```
R2.8.3: links of an objective merged from every link with that id (links for objectives not in the set
are ignored); none: `not covered`; a linked test has data when a run of a `Done` evaluation of the
version matches the name (`load_runs(ctx, statuses=["Done"])`, loaded once and only if any link names
a test); a checklist has data when `load_answers` has answers for it; none with data: `no evidence`;
else `evidence`, and `evidence, attention` when `tools.tool_for(tool).verdict(run) == "fail"` for a
matching run or a linked checklist's mean is below 3 (DEFAULT threshold).

**control_objectives** block: no assessment: empty `No control objectives for version {n}.`.
`group_by=objective`: one `<div class="objective" data-objective="{id}">` per objective id (sorted),
with id, `objectives[id]["objective"]`, legal basis, macro requirement, the risks mapped to it (risk
text, rationale if `show_rationale`, quote if `show_quotes`), and the status word of
`coverage_for(ctx, ids, ctx.report.coverage_links)` when `show_status`. `group_by=risk`: one
`<div class="risk" data-risk="{risk_id}">` per risk in position order, with its text and its objective
ids (and label). Notice `The mapping run stopped: {stop}.` when the run exists and `stop != "clean"`.
`finish(..., newest_newer=newest_newer_assessment)`.

**summary_coverage** block: no assessment: empty `No control objectives for version {n}.`. Table
with one `<tr data-objective="{id}">` per objective (skipping `evidence` rows when
`show_uncovered_only`): id, label, linked test names, linked checklists `{title} ({id})`, status
word. Then `<p class="coverage-counts">` with four `<span data-coverage-count="{status}">{count}</span>`
(always all four, counts over every objective). Status ok (no stale rule).
`choices`: `"links.objective_id"` objective ids with CSV labels, `"links.tests"` = `tool_choices`,
`"links.checklists"` = `checklist_choices`.

Tests green: tests/test_block_control_objectives.py (7), tests/test_block_summary_coverage.py (7),
test_data_access::test_r6_2_...[control_objectives].
Command: `uv run --extra dev pytest -q tests/test_block_control_objectives.py tests/test_block_summary_coverage.py`
Commit: `git add report_renderer/data/control_objectives.py report_renderer/coverage.py report_renderer/blocks/control_objectives.py report_renderer/blocks/summary_coverage.py report_renderer/blocks/templates/control_objectives.html.j2 report_renderer/blocks/templates/summary_coverage.html.j2`
Message: `Control objectives and coverage: one status rule for both, from the version's own data and the layout's links`

### D9. Superset data and the Dashboard chart block

`data/superset_db.py` (superset DSN; role `"AiscProject_" + uuid hex of project_id`):
```sql
-- the project's dashboards
SELECT DISTINCT d.id, d.slug FROM dashboards d
  JOIN dashboard_roles dr ON dr.dashboard_id = d.id JOIN ab_role r ON r.id = dr.role_id
 WHERE r.name = %(role)s
```
```python
def charts(project_id, system_id, *, sources) -> list[dict]           # DISTINCT s.id, s.slice_name via dashboard_slices of those dashboards
def chart(project_id, system_id, *, sources, chart_id) -> dict | None  # s.id, s.slice_name, s.viz_type, min(ds.dashboard_id)
def comments(project_id, system_id, *, sources, chart_id) -> list[dict]
    # c.id, c.parent_id, c.author_name, c.body, c.created_at FROM aisc_comment c WHERE c.chart_id = %(c)s
    #   AND c.dashboard_id IN (ids as text UNION slugs) ORDER BY c.created_at, c.id  (created_at read as UTC)
```
**dashboard_chart** block:
- `load`: `chart(...)`; None: return `{"missing": True}` and fetch nothing. Else comments (if
  `show_comments`), then image: `ctx.data.images.image(chart_id, width, height)`; `ImagesDisabled`
  sets `disabled`; any other exception sets `image_error_ref` (logged); when there is no image, try
  `ctx.data.chart_data.data(chart_id)` (`ChartDataUnavailable` or any error: none).
- `render`: missing: `BlockResult('<p>Chart not available in this project.</p>', "error")`. Else:
  chart name; link `<a href="{superset_url}/explore/?slice_id={id}">Open in the dashboard</a>` when
  `superset_url`; image `<img alt="{name}" src="data:image/png;base64,...">`; disabled:
  `<p class="note">Chart images need Superset screenshots, which are not enabled on this platform.</p>`
  plus, when chart data came back, a table (`<th>` per column, `<td>{value}</td>` per cell); image error:
  `<p class="error-box">Chart image unavailable (ref {ref}).</p>` and status error. Comments: nested
  `<ul class="comments">`, roots in order, replies (`include_replies`) as a `<ul>` inside the parent's
  `<li>`; each `<li>`: author, `YYYY-MM-DD HH:MM UTC`, body (escaped). Notices always
  `This chart shows all system versions; this report covers version {n}.` and, with comments shown,
  `Comments are not tied to a system version.`.
- `choices(ctx, "chart_id")` = `[{"value": id, "label": slice_name}]` from `charts`.

Tests green: tests/test_block_dashboard_chart.py (13), all of tests/test_data_access.py (10 functions).
Command: `uv run --extra dev pytest -q tests/test_block_dashboard_chart.py tests/test_data_access.py`
Commit: `git add report_renderer/data/superset_db.py report_renderer/blocks/dashboard_chart.py report_renderer/blocks/templates/dashboard_chart.html.j2`
Message: `Dashboard chart: the project's chart only, its review comments, an image when screenshots are on`

### D10. The service; the legacy code goes

`report_service.py` (rewritten):
```python
def create_app(deps=None, token=None) -> FastAPI
def __getattr__(name):            # module attribute `app` for `uvicorn report_service:app`: built on first access
```
- `token = token if token is not None else os.environ.get("REPORT_SERVICE_TOKEN", "")`; empty raises
  `RuntimeError("REPORT_SERVICE_TOKEN is not set")`. `deps = deps or Deps.from_env(os.environ)`.
- `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)`; an HTTP middleware on every request:
  `hmac.compare_digest(request.headers.get("x-report-token", "").encode(), token.encode())` (call it
  as `hmac.compare_digest`, the test patches the module attribute); false answers 401
  `{"error": {"code": "unauthorized", "message": "A valid X-Report-Token header is required."}}`.
- `GET /health` -> `{"status": "ok", "block_types": [ids], "tool_renderers": registry.tool_names()}`.
- `GET /v1/block-types` -> `[{type_id, title, contract_version, options_schema: full_options_schema(),
  default_options: full_default_options(), reads: list}]`.
- `POST /v1/choices` body `{project_id, system_id, block_type}`: unknown type or `NotInProject` ->
  404 `not_found`; `PlatformUnavailable` -> 503; else `{name: cls().choices(ctx, name) for name in cls.choice_options}`.
- `POST /v1/render` body = snapshot: `InvalidSnapshot` -> 422 `{"problems": [...]}`; `NotFound` -> 404;
  `PlatformUnavailable` -> 503 `{"error": {"code": "platform_unavailable", "message", "error_ref"}}`;
  else 200 with the document result.
- Routes are plain `def` (thread pool). No file is written (R5.4.4). No log line carries the token or a DSN.
- Remove: `git rm report_generator.py src/*.py resources/sql_alchemy.py resources/templates/*`
  (styles now live in `report_renderer/templates/report.css`). `/generate` and `/reports/` are gone.
- `Dockerfile` (D10 build contexts):
  ```dockerfile
  FROM python:3.12-slim
  COPY --from=ghcr.io/astral-sh/uv:0.9.9 /uv /uvx /bin/
  # (the same apt-get line of WeasyPrint's libraries as today)
  COPY --from=interface . /aisc-report-plugin-interface
  COPY --from=mlareject . /aisc-report-mlareject
  WORKDIR /app
  COPY pyproject.toml uv.lock ./
  RUN uv export --frozen --no-dev --no-emit-project --no-hashes -o /tmp/req.txt \
   && uv pip install --system --no-cache -r /tmp/req.txt && rm /tmp/req.txt
  COPY report_service.py ./
  COPY report_renderer ./report_renderer
  EXPOSE 8001
  CMD ["uvicorn", "report_service:app", "--host", "0.0.0.0", "--port", "8001"]
  ```
  (the path sources `../aisc-report-*` resolve from /app to the two copied folders).
- `README.md`: rewrite to describe the renderer (snapshot in, HTML or PDF out; the four routes; the
  environment variables `REPORT_SERVICE_TOKEN`, `REPORT_PLATFORM_DATABASE_URL`, `REPORT_SUPERSET_DATABASE_URL`,
  `REPORT_PROJECT_DB_URL`, `REPORT_AIRO_VOCAB_PATH`, `REPORT_OBJECTIVES_CSV_PATH`, `REPORT_CHART_IMAGES`,
  `REPORT_SUPERSET_URL/USER/PASSWORD/PUBLIC_URL`, `REPORT_PLUGIN_PATH`, `REPORT_LOGO_PATH`; block and tool
  plugins; how to run the tests).

Tests green: tests/test_service.py (14 functions), tests/test_e2e.py (3), tests/test_performance.py (2),
and the whole suite.
Command: `cd ~/aisc-report-generator && uv run --extra dev pytest -q` (all pass).
Commit: `git add report_service.py Dockerfile README.md` plus the `git rm` paths.
Message: `The renderer's service: token-checked block types, choices and render; the old generator is removed`

### Checkpoint D
`uv run --extra dev pytest -q` in the generator: every test passes (218 + 2 new). Interface 45 and
mlareject 19 still pass. No `aisc-t-*` container left. Guard pass stands (aisc-install unchanged).

---

## Group E: aisc-install, the report composer (`apps/report-composer`)

Needs group A (roles, schema) and, for E6, group D (the real renderer).

Module layout:
```
apps/report-composer/.gitignore                 .venv/ __pycache__/ .pytest_cache/
apps/report-composer/Dockerfile, README.md
apps/report-composer/migrations/0001_report_composer.sql
apps/report-composer/report_composer/{app.py, api.py, pages.py, access.py, db.py, migrate.py,
    layouts.py, reports.py, renderer_client.py, forms.py, errors.py}
apps/report-composer/report_composer/templates/{base,layouts,editor,error,_form}.html.j2
apps/report-composer/report_composer/static/{composer.js, composer.css}
```
(02's `templates_store.py` and `clock.py` fold into `db.py` and `app.py`.)

### E1. Pure logic: layouts, forms, access, filename, renderer client

`layouts.py`:
```python
DEFAULT_ORDER = ["cover", "ai_card", "risk_classification", "control_objectives", "test_results",
                 "control_answers", "summary_coverage"]
MAX_BLOCKS, MAX_CHARTS = 50, 10
def default_blocks(block_types) -> list[dict]            # types of DEFAULT_ORDER present; deepcopy(default_options); new uuid4 ids
def reference_options(block_type: dict) -> list[str]     # properties with "x-aisc-reference": true
def validate_layout(blocks, *, block_types, choices, allow_missing_references=False) -> list[dict]
def reset_invalid(blocks, problems, block_types) -> list[dict]
def to_template(blocks, block_types, keep_text=False) -> list[dict]
def from_template(template_blocks) -> list[dict]
```
`validate_layout` problems `{instance_id, code, pointer, message}`, layout-level first:
`too_many_blocks` (more than 50 blocks, or more than 10 `dashboard_chart`; instance_id None, pointer "")
and `duplicate_cover` (the second cover's id); then per block: missing/invalid uuid `invalid_block`,
repeated id `duplicate_instance_id`, `unknown_block_type`; `invalid_options` from
`Draft202012Validator(options_schema)` over `{**default_options, **options}` (pointer as B3; with
`allow_missing_references`, drop `required` errors of reference options); only when the options are
valid, `invalid_reference`: `choices(block_type)` is called lazily once per type; value `None`, `"all"`
or `[]` is not checked; a list checks each item at `/{name}/{i}`, a scalar at `/{name}`, `links`
checks `/links/{i}/objective_id` against `"links.objective_id"`, `/links/{i}/tests/{j}` against
`"links.tests"`, `/links/{i}/checklists/{j}` against `"links.checklists"`; a key absent from the
choices means no value is allowed.
`reset_invalid`: for each `invalid_reference`, the top option of the pointer is set back to its default
(deep copy) or removed when it has none; returns deep copies. `to_template`: `[{block_type, options}]`
with reference options reset/removed the same way, `free_text.text` -> `"[text]"` unless `keep_text`,
options of an unknown type dropped. `from_template`: deep copies with new `instance_id`s.

`forms.py`: `form_fields(options_schema, values, choices) -> list[dict]`, one per property in schema
order, keys `name, label, widget, value, required, min, max, options, reference`:
`links` widget for the links array (options = the three `links.*` lists); `select` for a scalar with
choices (options = `choices[name]` exactly) or an `enum` (options `[{value, label: str(value)}]`);
`multiselect` for `oneOf [all, array]` (options = choices or the items' enum), and for an array of enum;
`checkbox` for boolean; `number` for integer/number with `min`/`max`; `textarea` for a string with
`maxLength > 300`; `text` otherwise. `required` = name in `schema.get("required", [])`.

`access.py` (control-objectives pattern, admin as viewer):
```python
ADMIN_ROLE = "admin"; SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
@dataclass(frozen=True)
class Access: role: str | None; admin: bool = False
    # may_write: role in ("editor", "owner")
def decide(method, access) -> "allow" | "not-found" | "forbidden" | "unavailable"
    # None -> unavailable; role None and not admin -> not-found; safe method -> allow;
    # else allow if may_write else forbidden (an admin who is not an editor is forbidden)
def same_origin(headers, origin) -> bool
    # case-insensitive lookup; Origin == origin; else Referer == origin or startswith origin + "/"; else False
def find_project(database_url, ref) -> dict | None      # pid::text = ref OR slug = ref ; {pid, slug, name}
def role_in_project(database_url, project_pid, subject) -> str | None   # core.project_member
def access_for(database_url, project, caller) -> Access | None
    # role_in_project looked up as a module global at call time (the test patches it);
    # psycopg.Error -> None (fail closed); admin -> Access(role, admin=True)
```
`reports.py`: `MAX_PDF_BYTES = 25 * 1024 * 1024`;
`pdf_filename(slug, number, layout_name, when) -> f"{slug}-v{number}-{slugify(name)}-{when:%Y%m%d-%H%M}.pdf"`
(UTC; slugify = NFKD to ASCII, lowercase, runs of non `[a-z0-9]` to `-`, stripped, `report` when empty).

`renderer_client.py`:
```python
class RendererError(Exception); class RendererUnavailable(RendererError); class RendererTimeout(RendererError)
class RendererRejected(RendererError): status: int; problems: list
class HttpRendererClient:
    def __init__(self, base_url, token, timeout=120.0): self.timeout = timeout   # token kept private, not in repr
    def block_types(self) -> list          # GET /v1/block-types
    def choices(self, project_id, system_id, block_type) -> dict   # POST /v1/choices
    def render(self, snapshot) -> dict     # POST /v1/render
    # httpx.TimeoutException -> RendererTimeout("no answer within 120 s"); other httpx.HTTPError or
    # status >= 500 or 401 -> RendererUnavailable("renderer answered {status}"); 404/422 -> RendererRejected
```
Tests green: tests/test_layouts_unit.py (16), tests/test_forms_unit.py (4), tests/test_access_unit.py (7),
tests/test_filename_unit.py (1), tests/test_api_reports.py::test_r7_2_2_the_http_client_times_out_at_120_seconds.
Command: `cd ~/aisc-install/apps/report-composer && uv run --extra dev pytest -q tests/test_layouts_unit.py tests/test_forms_unit.py tests/test_access_unit.py tests/test_filename_unit.py`
Commit: `git add apps/report-composer/.gitignore apps/report-composer/report_composer/layouts.py apps/report-composer/report_composer/forms.py apps/report-composer/report_composer/access.py apps/report-composer/report_composer/reports.py apps/report-composer/report_composer/renderer_client.py`
Message: `Report composer logic: layout validation, templates without project data, rights, filenames`

### E2. Schema and migrations

**`apps/report-composer/migrations/0001_report_composer.sql`** (run as report_composer_rw):
```sql
-- The composer's own tables (report run 2026-09-23, 01 section 3.1, 02 D13).
CREATE TABLE report_composer.layout (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES core.project (pid) ON DELETE CASCADE,
    -- NO ACTION, not RESTRICT: deleting a project cascades through core.system and here in one statement
    system_id   uuid NOT NULL REFERENCES core.system (pid),
    name        text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 120),
    description text NOT NULL DEFAULT '',
    revision    integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at  timestamptz NOT NULL DEFAULT now(),
    created_by  text NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    updated_by  text NOT NULL,
    UNIQUE (project_id, name)
);
CREATE TABLE report_composer.layout_block (
    layout_id   uuid NOT NULL REFERENCES report_composer.layout (id) ON DELETE CASCADE,
    instance_id uuid NOT NULL,
    position    integer NOT NULL CHECK (position >= 0),
    block_type  text NOT NULL,
    options     jsonb NOT NULL DEFAULT '{}',
    PRIMARY KEY (layout_id, instance_id),
    UNIQUE (layout_id, position)
);
CREATE TABLE report_composer.template (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name              text NOT NULL UNIQUE CHECK (char_length(name) BETWEEN 1 AND 120),
    description       text NOT NULL DEFAULT '',
    blocks            jsonb NOT NULL,
    source_project_id uuid REFERENCES core.project (pid) ON DELETE SET NULL,
    created_by        text NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE report_composer.generated_report (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    layout_id       uuid NOT NULL REFERENCES report_composer.layout (id) ON DELETE CASCADE,
    layout_revision integer NOT NULL,
    project_id      uuid NOT NULL,
    system_id       uuid NOT NULL,
    snapshot        jsonb NOT NULL,
    status          text NOT NULL CHECK (status IN ('running', 'done', 'partial', 'failed')),
    pdf             bytea,
    sha256          text,
    size_bytes      integer,
    block_statuses  jsonb NOT NULL DEFAULT '[]',
    error_ref       text,
    error_code      text,
    created_by      text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz
);
CREATE INDEX generated_report_layout_idx ON report_composer.generated_report (layout_id, created_at DESC);
```
`migrate.py`: `MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"`;
`migrate(conn, directory=MIGRATIONS, table="report_composer.schema_migration") -> list[str]`, the same
body as `platform/platform_service/migrate.py` (advisory lock key `8_190_233_707`; the schema exists,
so it is only read).

`db.py`: `connect(database_url)` (psycopg, `dict_row`, a transaction per `with`), and the SQL helpers
(all take `conn` first; uuid arguments checked with `uuid.UUID`, a bad one returns None):
`systems(conn, project_pid)` (`pid::text, number, name, version AS release ORDER BY number DESC`),
`system_of_project(conn, project_pid, system_pid)`, `latest_system(conn, project_pid)`,
`list_layouts(conn, project_pid)` (join `core.system` for `system_number`, lateral last report
`{id, created_at, status}` as `last_report` or None), `get_layout(conn, project_pid, layout_id, for_update=False)`
(with blocks by position), `insert_layout(conn, *, project_pid, system_pid, name, description, blocks, who, now)`,
`update_layout(conn, layout_id, *, based_on, name, description, system_pid, blocks, who, now) -> int | None`
(`UPDATE ... SET revision = revision + 1 ... WHERE id = %s AND revision = %s RETURNING revision`, then
delete and re-insert the blocks), `delete_layout`, `insert_template`, `list_templates`, `get_template`,
`delete_template`, `running_report(conn, layout_id, since)`, `insert_report`, `finish_report`,
`list_reports(conn, layout_id)`, `get_report(conn, project_pid, report_id)` (joined to the layout for
the project check and to `core.system` for the number). Options are written with `psycopg.types.json.Jsonb`.

### E3. The app, its API and rights

`errors.py`: `class ApiError(Exception): (status, code, message, details=())`; `install(app)` adds
handlers: `ApiError`, `RequestValidationError` (422 `invalid_request`) and Starlette `HTTPException`
(404 `not_found`, 405 `method_not_allowed`); a path under `/api/` answers
`{"error": {"code", "message", "details": [...]}}`, any other path the `error.html.j2` page with the
same status. Messages never name the project (R4.4.3: stranger and unknown project answer the same body).

`app.py`:
```python
def create_app(*, database_url=None, renderer=None, clock=None) -> FastAPI
    # database_url defaults to REPORT_COMPOSER_DATABASE_URL; renderer to
    # HttpRendererClient(REPORT_RENDERER_URL, REPORT_SERVICE_TOKEN); clock to lambda: datetime.now(timezone.utc);
    # FastAPI(root_path=os.environ.get("REPORT_COMPOSER_ROOT_PATH", ""), lifespan=...) whose lifespan runs migrate();
    # app.state.{database_url, renderer, clock}; errors.install(app); include api.router and pages.router;
    # mount "/static" (StaticFiles of report_composer/static)
def __getattr__(name)   # module attribute `app` for uvicorn, built on first access
```
`api.py` (`APIRouter(prefix="/api")`), rights through two dependencies built in `api.py`:
```python
def signed_in(request) -> Caller          # aisc_identity.service.caller_from_headers; NotAuthenticated -> 401
                                          # not_signed_in; Misconfigured -> 500 misconfigured
def project_guard(right: str)             # "viewer" | "editor" -> dependency returning (caller, project, access)
    # 1. signed_in; 2. access.find_project (psycopg.Error -> 503 unavailable; None -> 404 not_found);
    # 3. access.access_for; 4. verdict = access.decide("GET" if right == "viewer" else "POST", a):
    #    unavailable -> 503, not-found -> 404, forbidden -> 403 forbidden;
    # 5. for methods not in SAFE_METHODS: access.same_origin(request.headers, PLATFORM_ORIGIN (env, default
    #    "http://localhost")) else 403 forbidden "Cross-origin request refused."
```
Routes (the table of R4.3, `{ref}` = slug or pid, D11):

| route | right | behaviour |
|---|---|---|
| GET /api/p/{ref}/systems | viewer | `db.systems` |
| GET /api/block-types | signed in | `renderer.block_types()` |
| GET /api/p/{ref}/choices?block_type=&system_id= | viewer | system not in project: 404 without calling the renderer; else `renderer.choices(pid, system_id, block_type)` |
| GET /api/p/{ref}/layouts | viewer | `list_layouts` rows `{id, name, description, system_id, system_number, revision, updated_at, last_report}` |
| POST /api/p/{ref}/layouts | editor | body `{name, description?, system_id?, template_id?, blocks?}`: system given and not in project -> 422 `system_not_in_project`; missing -> latest (R3.4); blocks: template (404 when missing) via `from_template`, else the given list (even `[]`), else `default_blocks`; `validate_layout(..., allow_missing_references=bool(template_id))`; problems -> 422 with the first problem's code and all problems in details; duplicate name -> 422 `name_taken`; 201 with the layout |
| GET /api/p/{ref}/layouts/{id} | viewer | 404 when not of this project; `{id, project_id, name, description, system_id, revision, blocks, created_at, updated_at}` |
| PUT /api/p/{ref}/layouts/{id} | editor | lookup first (404); `project_id` present and different -> 422 `immutable_field`; system not in project -> 422; validate against the new system's choices; only `invalid_reference` problems and `reset_invalid` -> `reset_invalid` then validate again; problems -> 422; `update_layout` None -> 409 `stale_revision`, message "The layout was saved meanwhile; the current revision is {n}.", details `[{"current_revision": n}]`; 200 with the layout |
| DELETE /api/p/{ref}/layouts/{id} | editor | 204 (reports go by cascade) |
| POST /api/p/{ref}/layouts/{id}/validate | viewer (no origin check: it changes nothing) | `{"valid": not problems, "problems": problems}` |
| GET /api/p/{ref}/layouts/{id}/preview | viewer | snapshot (mode preview) -> `renderer.render`; `HTMLResponse(html)` with `Content-Security-Policy: default-src 'none'; img-src data:; style-src 'unsafe-inline'` and `X-Content-Type-Options: nosniff`; unknown types go to the renderer as they are (R3.10) |
| POST /api/p/{ref}/layouts/{id}/reports | editor | see E4 |
| GET /api/p/{ref}/layouts/{id}/reports | viewer | `[{id, layout_revision, status, created_at, created_by, size_bytes}]` newest first |
| GET /api/p/{ref}/reports/{rid}/pdf | viewer | report of this project with a PDF, else 404; `Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{pdf_filename(...)}"'})` from the project slug, the snapshot's system number, the snapshot's layout name and `created_at` |
| POST /api/p/{ref}/layouts/{id}/template | editor | `to_template(blocks, block_types, keep_text)`; `insert_template(source_project_id=pid, created_by=subject)`; 201 `{id, name, description, block_types}`; duplicate name 422 `name_taken` |
| GET /api/templates | signed in | `[{id, name, description, block_types, created_by, created_at}]` |
| DELETE /api/templates/{tid} | signed in + same origin | 404 missing; creator (`created_by == caller.subject`) or realm role admin -> 204; else 403 |

Snapshot built by one function `api.snapshot_of(project, layout, mode, caller)`:
`{"project_id", "system_id", "layout": {"id", "name", "revision"}, "blocks": [{instance_id, block_type,
options}], "mode", "requested_by": caller.username or caller.email or caller.subject}` (D12).
Renderer errors: `RendererUnavailable` 502 `renderer_unavailable`, `RendererTimeout` 504
`renderer_timeout`, `RendererRejected` 404 `not_found` / 422 `invalid_snapshot`.

### E4. Generation

`reports.generate(database_url, renderer, clock, project, layout_id, caller) -> (status_code, body)`:
1. Transaction: `get_layout(for_update=True)` (404); no blocks -> 422 `empty_layout`; full validation
   (unknown type -> 422 `unknown_block_type`, etc.); `running_report(since=clock() - 15 min)` -> 409
   `generation_running`; `insert_report(status='running', snapshot, layout_revision, project_id,
   system_id, created_by=subject, created_at=clock())`. Commit.
2. `renderer.render(snapshot with mode "pdf")` outside any transaction.
3. Timeout: row `failed`, `error_ref = new ref`, `error_code = 'renderer_timeout'`, 504 with the ref in
   message and details. Unavailable or any other error: `failed`, 502 `renderer_unavailable` with the ref.
4. `pdf = b64decode(pdf_base64)`; `len(pdf) > MAX_PDF_BYTES`: `failed`, `error_code = 'pdf_too_large'`,
   no PDF stored, 507 `pdf_too_large`.
5. Else `done`, or `partial` when any block status is `error`; store pdf, `sha256` (computed here),
   `size_bytes`, `block_statuses`, `finished_at = clock()`; 201 `{id, status, block_statuses}`.
Error refs: `secrets.token_hex(4)`.

Tests green (E2 to E4): tests/test_api_access.py (9), tests/test_api_layouts.py (23), tests/test_api_reports.py (14),
tests/test_api_templates.py (5).
Command: `cd ~/aisc-install/apps/report-composer && uv run --extra dev pytest -q tests/test_api_access.py tests/test_api_layouts.py tests/test_api_reports.py tests/test_api_templates.py`
(test_api_layouts::test_r3_10_a_block_type_that_went_away and ::test_d11_the_project_may_be_named_by_pid
need the pages of E5; run them there.)
Commit: `git add apps/report-composer/migrations apps/report-composer/report_composer/app.py apps/report-composer/report_composer/api.py apps/report-composer/report_composer/db.py apps/report-composer/report_composer/migrate.py apps/report-composer/report_composer/errors.py apps/report-composer/report_composer/reports.py apps/report-composer/report_composer/access.py`
Message: `Report composer API: layouts, templates, preview and generation, behind project roles`

### E5. Pages and the one script

`pages.py` (`APIRouter()`, HTML, the same guard as the API with HTML errors):
- `GET /` -> 303 to `LAUNCHER_URL` (default `http://localhost:8100/`).
- `GET /p/{ref}/` (viewer): a pid ref redirects 303 to `{root_path}/p/{slug}/` after the access check
  (a stranger still gets 404). Page `layouts.html.j2`: table of layouts (name linking to the editor,
  `Version {n}`, `revision {r}`, updated, last report date and status). Editors only: a "New layout"
  form (name, version select), a "New from template" form (template select, name), and a "Delete"
  button per row (`data-control="delete"`). Viewers get none of these words on the page.
- `GET /p/{ref}/layouts/{id}` (viewer; pid redirects as above): page `editor.html.j2`:
  - editors only: `<div data-control="palette">` with one `<button type="button" data-add="{type_id}">{title}</button>`
    per block type; `<select data-control="version">` with `<option value="{pid}">Version {n} ({release})</option>`
    newest first; buttons `data-control="save"`, `"generate"`, `"save-template"`; per block
    `data-control="move-up"`, `"move-down"`, `"remove"` buttons and a `<details data-control="configure">`
    holding the form from `forms.form_fields(schema, options, choices)` (choices fetched once per block
    type of the layout with `renderer.choices(pid, system_id, type)`, only for types with
    `choice_options`/references); a hidden `<template data-block-template="{type_id}">` per type (default
    options), whose content carries no `data-instance-id`.
  - everyone: `<ol id="blocks">` with one `<li data-instance-id="{iid}" data-block-type="{type}">` per
    block in order (title and type; an unregistered type shows `Unknown type: {type}` and no form);
    `<iframe sandbox="" title="Preview" src="{root}/api/p/{slug}/layouts/{id}/preview">`; the reports
    list with Download links.
  - one `<script src="{root}/static/composer.js" defer></script>`, no inline script; page data in
    `data-*` attributes of `<main>` (`data-api`, `data-layout`, `data-revision`).
- Form inputs carry `data-option="{name}"` and `data-kind` (`bool`, `int`, `str`, `enum`,
  `all-or-list`, `list`, `links`).
- `static/composer.js` (under 300 lines, no logic of its own): collect each block's options from its
  inputs by `data-kind`; move up/down, remove, drag and drop (HTML5 `draggable`) and add from the
  palette (clone the `<template>`, set `data-instance-id = crypto.randomUUID()`); mark "Unsaved changes"
  on any change; Save = PUT the full ordered list with the revision and the version select (on 422
  `invalid_reference` after a version change, `confirm()` then resend with `reset_invalid: true`;
  problems shown next to the block with that instance id); reload the preview iframe after Save;
  Generate = POST reports, show "Generating..." then the per-block statuses and reload the list; Save as
  template = `prompt()` for a name, POST; list page: New layout, New from template, Delete (`confirm()`).
  All fetches with `credentials: "same-origin"` and JSON bodies.
- `static/composer.css`: small layout styles.

Tests green: tests/test_pages.py (6), tests/test_api_layouts.py::test_r3_10_a_block_type_that_went_away,
::test_d11_the_project_may_be_named_by_pid.
Command: `uv run --extra dev pytest -q tests/test_pages.py tests/test_api_layouts.py`
Commit: `git add apps/report-composer/report_composer/pages.py apps/report-composer/report_composer/app.py apps/report-composer/report_composer/templates apps/report-composer/report_composer/static`
Message: `Report composer screens: layouts list and editor from Python, one small script`

### E6. Image, README, and the end-to-end run

- `apps/report-composer/Dockerfile`:
  ```dockerfile
  FROM python:3.12-slim
  COPY --from=ghcr.io/astral-sh/uv:0.9.9 /uv /uvx /bin/
  WORKDIR /app
  COPY pyproject.toml uv.lock ./
  RUN uv export --frozen --no-dev --no-emit-project --no-hashes -o /tmp/req.txt \
   && uv pip install --system --no-cache -r /tmp/req.txt && rm /tmp/req.txt
  COPY report_composer ./report_composer
  COPY migrations ./migrations
  ENV PYTHONPATH=/app:/app/shared/identity
  EXPOSE 8095
  CMD ["uvicorn", "report_composer.app:app", "--host", "0.0.0.0", "--port", "8095", "--proxy-headers"]
  ```
- `apps/report-composer/README.md`: what it is, routes, environment (`REPORT_COMPOSER_DATABASE_URL`,
  `REPORT_RENDERER_URL`, `REPORT_SERVICE_TOKEN`, `REPORT_COMPOSER_ROOT_PATH`, `PLATFORM_ORIGIN`,
  `LAUNCHER_URL`, `AUTH_ENABLED`, `KEYCLOAK_*`), how to run the tests.

Tests green: tests/test_e2e.py::test_e2e_compose_preview_and_generate, ::test_e2e_pinned_to_version_1
(real renderer from `~/aisc-report-generator` as a subprocess), and the whole composer suite.
Command: `cd ~/aisc-install/apps/report-composer && uv run --extra dev pytest -q` (107 passed).
Commit: `git add apps/report-composer/Dockerfile apps/report-composer/README.md`
Message: `Report composer image and notes; composer and renderer pass end to end`

### Checkpoint E
Composer suite 107 passed; `scripts/tests/test_report_grants.py` still green; `scripts/guard-frozen.sh`
prints `GUARD PASS`.

---

## Group F: aisc-install, joining the stack

### F1. Compose services (`docker-compose.development.yml`, shared file)

Add after the `control-objectives` service (before "Results dashboard"):
```yaml
  # ── Report (step 7): the composer assembles a report from blocks, the renderer renders it ──
  report-composer:
    build: apps/report-composer
    image: aisc-report-composer:latest
    pull_policy: never
    container_name: report-composer
    volumes:
      - ./shared/identity:/app/shared/identity:ro,z
    environment:
      PYTHONPATH: /app:/app/shared/identity
      AUTH_ENABLED: "true"
      KEYCLOAK_ISSUER: ${KEYCLOAK_URL_EXTERNAL}/realms/aisc
      KEYCLOAK_JWKS_URL: ${KEYCLOAK_INTERNAL_URL:-http://keycloak:8080}/realms/aisc/protocol/openid-connect/certs
      REPORT_COMPOSER_ROOT_PATH: /report-composer
      LAUNCHER_URL: ${LAUNCHER_EXTERNAL_URL:-http://localhost:8100/}
      PLATFORM_ORIGIN: ${PLATFORM_ORIGIN:-http://localhost}
      REPORT_COMPOSER_DATABASE_URL: postgresql://report_composer_rw:${REPORT_COMPOSER_PASSWORD:-report_composer_rw}@postgres:5432/platform
      REPORT_RENDERER_URL: http://report-renderer:8001
      REPORT_SERVICE_TOKEN: ${REPORT_SERVICE_TOKEN:?run scripts/secrets.sh first}
    depends_on:
      postgres-setup:
        condition: service_completed_successfully
      report-renderer:
        condition: service_started
    expose:
      - "8095"
    networks:
      - backend
      - frontend
    restart: unless-stopped

  report-renderer:
    build:
      context: ${REPORT_GENERATOR_DIR:-../aisc-report-generator}
      additional_contexts:
        interface: ${REPORT_INTERFACE_DIR:-../aisc-report-plugin-interface}
        mlareject: ${REPORT_MLAREJECT_DIR:-../aisc-report-mlareject}
    image: aisc-report-renderer:latest
    pull_policy: never
    container_name: report-renderer
    volumes:
      # read-only, never copied (02 D3; airo_vocab.json is pinned by the guard)
      - ./apps/qualification/src/data/airo_vocab.json:/data/airo_vocab.json:ro,z
      - ./apps/control-objectives/src/aisc_control_objectives/data/ai_act_control_objectives.csv:/data/ai_act_control_objectives.csv:ro,z
    environment:
      REPORT_PLATFORM_DATABASE_URL: postgresql://report_ro:${REPORT_RO_PASSWORD:-report_ro}@postgres:5432/platform
      REPORT_SUPERSET_DATABASE_URL: postgresql://report_ro:${REPORT_RO_PASSWORD:-report_ro}@postgres:5432/superset
      REPORT_PROJECT_DB_URL: postgresql://report_ro:${REPORT_RO_PASSWORD:-report_ro}@postgres:5432/{database}
      REPORT_AIRO_VOCAB_PATH: /data/airo_vocab.json
      REPORT_OBJECTIVES_CSV_PATH: /data/ai_act_control_objectives.csv
      REPORT_SERVICE_TOKEN: ${REPORT_SERVICE_TOKEN:?run scripts/secrets.sh first}
      # O1: chart images stay off until Superset screenshots are enabled (set to superset then)
      REPORT_CHART_IMAGES: "off"
      REPORT_SUPERSET_PUBLIC_URL: ${DASHBOARD_EXTERNAL_URL:-http://localhost:8188}
    depends_on:
      report-grants:
        condition: service_completed_successfully
    # called by the composer only: not on the frontend network, not in the Caddyfile
    expose:
      - "8001"
    networks:
      - backend
    restart: unless-stopped

  # SELECT for report_ro on what the report reads, again on every start (02 D6 (b)(c))
  report-grants:
    image: postgres:14-alpine
    container_name: report-grants
    environment:
      PGHOST: postgres
      PGUSER: ${POSTGRES_USER}
      PGPASSWORD: ${POSTGRES_PASSWORD}
      PGDATABASE: ${POSTGRES_DB}
      REPORT_GRANTS_WAIT_SECONDS: "600"
    volumes:
      - ./scripts/report-grants.sh:/setup/report-grants.sh:ro,Z
      - ./init/report-ro-grants.sql:/setup/report-ro-grants.sql:ro,Z
    command: ["sh", "/setup/report-grants.sh"]
    depends_on:
      postgres-setup:
        condition: service_completed_successfully
      qualification-migrate:
        condition: service_completed_successfully
      control-objectives-migrate:
        condition: service_completed_successfully
      controls-migrate:
        condition: service_completed_successfully
    restart: "no"
    networks:
      - backend
```
No comment line may contain `REPORT_SERVICE_TOKEN:` (the stack test scans every occurrence).

Committing only these hunks: `git diff docker-compose.development.yml > $SCRATCH/compose.patch`
(any scratch dir outside the repo), delete the qualification-prefill and PREFILL_URL hunks from the
patch file, `git apply --cached --check $SCRATCH/compose.patch && git apply --cached $SCRATCH/compose.patch`,
then `git diff --cached docker-compose.development.yml` must show only the report services. The working
tree keeps both.

### F2. Infra (`docker-compose-infra.development.yml`)

- `postgres.volumes` add: `- ./init/report-roles.sql:/docker-entrypoint-initdb.d/60-report-roles.sql:ro,Z`
  (after the superset line, with a comment: the report's roles; after 50-superset-db.sql because it
  grants CONNECT on superset).
- `postgres-setup`: add `environment` entries
  `REPORT_RO_PASSWORD: ${REPORT_RO_PASSWORD:-report_ro}` and
  `REPORT_COMPOSER_PASSWORD: ${REPORT_COMPOSER_PASSWORD:-report_composer_rw}`; add volume
  `- ./init/report-roles.sql:/setup/report-roles.sql:ro,Z`; command becomes:
  ```yaml
    command: >
      sh -c "until pg_isready -q; do sleep 1; done
      && psql -v ON_ERROR_STOP=1 -f /setup/project-databases.sql
      && psql -v ON_ERROR_STOP=1 -v report_ro_password=\"$$REPORT_RO_PASSWORD\"
      -v report_composer_password=\"$$REPORT_COMPOSER_PASSWORD\" -f /setup/report-roles.sql"
  ```

### F3. Caddy, launcher, secrets

- `Caddyfile`, inside the `:80` site right after the control-objectives block:
  ```
  # The report composer (apps/report-composer), step 7. handle_path strips the prefix;
  # REPORT_COMPOSER_ROOT_PATH fixes the URLs the app generates. The renderer is never routed.
  handle_path /report-composer* {
    import protect
    reverse_proxy report-composer:8095 {
      header_up X-Real-IP {remote_host}
    }
  }
  ```
  (no occurrence of the renderer's service name anywhere in the file).
- `homepage/project.html`: after the second `.row`, add `<div class="wrap" aria-hidden="true"><i></i><i></i><span></span></div>`
  and a third row:
  ```html
  <div class="row">
    <a class="card" id="report-composer-card" href="http://localhost/report-composer/">
      <span class="n">7</span>
      <span class="svc">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h9l3 3v15H6z"/><path d="M9 9h6M9 13h6M9 17h4"/></svg>
        Report
      </span>
      <h2>Compose the report</h2>
      <p>Assemble the assessment report from its blocks, preview it and generate the PDF.</p>
      <span class="open">Open <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12h15m-6-7 7 7-7 7"/></svg></span>
    </a>
  </div>
  ```
  and in `inProject` add `'report-composer-card': 'http://localhost/report-composer/p/'` (the map
  already appends the pid).
- `scripts/secrets.sh`: in the heredoc add three lines at column 0:
  `REPORT_SERVICE_TOKEN=$(rand)`, `REPORT_RO_PASSWORD=$(rand)`, `REPORT_COMPOSER_PASSWORD=$(rand)`;
  change "8 secrets" to "11 secrets"; after the `if/else` block add a top-up for existing files:
  ```sh
  # Secrets added after this install was made: appended once, never replacing what is there.
  for name in REPORT_SERVICE_TOKEN REPORT_RO_PASSWORD REPORT_COMPOSER_PASSWORD; do
    if ! grep -q "^$name=" "$OUT"; then
      echo "$name=$(rand)" >> "$OUT"
      echo "added $name to $OUT"
    fi
  done
  ```
  Do not run the script (it rewrites the user's env.runtime).

Tests green: all of `scripts/tests/test_report_stack.py` (24 functions).
Command:
```
cd ~/aisc-install && uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider \
    scripts/tests/test_report_stack.py scripts/tests/test_report_grants.py scripts/tests/test_compose.py
```
(test_final_guard_frozen_passes runs the guard; allow up to 20 minutes.)
Commit (after the filtered staging of F1): `git add docker-compose-infra.development.yml Caddyfile homepage/project.html scripts/secrets.sh`
Message: `The report joins the stack: composer behind sign-in as step 7, renderer internal, grants on every start`

### Checkpoint F
Stack and grants suites green; `scripts/guard-frozen.sh` prints `GUARD PASS` on the new HEAD.

---

## Group G: Integration check

1. `env | grep -iE 'DATABASE|DSN|DB_URL'` prints nothing.
2. Every suite:
   ```
   cd ~/aisc-report-plugin-interface && uv run --extra dev pytest -q          # 45 passed
   cd ~/aisc-report-mlareject       && uv run --extra dev pytest -q          # 19 passed
   cd ~/aisc-report-generator       && uv run --extra dev pytest -q          # 220 passed (218 + 2 new)
   cd ~/aisc-install/apps/report-composer && uv run --extra dev pytest -q    # 107 passed
   cd ~/aisc-install && uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests
                                                                              # the report suites (82) and the older ones, all pass
   cd ~/aisc-install && scripts/test-pipeline-chain.sh                        # passes (project template with 0003)
   cd ~/aisc-install && scripts/guard-frozen.sh                               # GUARD PASS
   ```
   Platform's own tests are not part of this run: their default DSN is the live database. Run them
   only with `PLATFORM_TEST_DATABASE_URL` pointing at a throwaway, never without it.
3. Both end-to-end tests, explicitly:
   `cd ~/aisc-report-generator && uv run --extra dev pytest -q tests/test_e2e.py` and
   `cd ~/aisc-install/apps/report-composer && uv run --extra dev pytest -q tests/test_e2e.py`.
4. Optional image smoke (allowed by RULES, tag `report-test`, removed after):
   `docker build --build-context interface=$HOME/aisc-report-plugin-interface --build-context mlareject=$HOME/aisc-report-mlareject -t aisc-report-renderer:report-test ~/aisc-report-generator`,
   `docker build -t aisc-report-composer:report-test ~/aisc-install/apps/report-composer`, then
   `docker rmi aisc-report-renderer:report-test aisc-report-composer:report-test`. No `docker compose`.
5. Clean state: `docker ps -a --filter name=aisc-t- --format '{{.Names}}'` empty; `git status --short`
   in each repo shows only other people's files and untracked caches; `git log --oneline` shows the
   commits of this plan; nothing pushed.
6. Expected remaining failures: **none**. Not automated (manual, browser): R4.2.3 drag and drop and the
   unsaved flag, R4.2.5 progress display. For the user (not done tonight): enabling Superset screenshots
   (O1, `REPORT_CHART_IMAGES=superset`), `scripts/secrets.sh` to add the three new secrets to
   `env.secrets`, rebuilding and starting the stack, and the DEFAULTs of 01 and 02 (D2, R2.8.2 threshold 3,
   plain-text free text, stripped templates).
7. Append the results (counts per suite, guard verdict, commit shas) to `PROGRESS.md` of this folder.
