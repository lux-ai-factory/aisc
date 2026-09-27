# Stage 4, WP W1: compose and env wiring

Date: 2026-09-25. Branch `isolation/2026-09-25`, top-level worktree `~/aisc-isolation` only. Nothing pushed, nothing
built or started: every check is `docker compose config` on copies of the files (project names `aisc-t-config`,
`aisc`, `aisc-isolation-build`, config only). No database was touched. W1 is the only writer of the top-level
compose and env files (G1); the module WPs' compose requests (Q1 3.10, O1.7, E1 "Files, top level", R1, D1 step 6)
are all applied here, and the module agents must not edit these files.

## Commits (top-level repo)

| commit | content |
|---|---|
| `3a3c672` | `scripts/tests/test_compose_w1.py` (new, red before the wiring) |
| `215bb95` | `docker-compose.development.yml`, `docker-compose-infra.development.yml`, `env.development` |
| (this commit) | these notes and the PROGRESS.md line |

## What changed

- **4.0 image tags (G9).** Every built service has `image: <name>:${AISC_IMAGE_TAG:-latest}` and
  `pull_policy: never`. The existing names are kept. The eight services that used compose's default name now
  have it written out: `aisc-controls-{pdf,migrate,web}`, `aisc-qualification-{llm,ontology,pdf,migrate,web}`.
  `aisc-eval-flower` uses `aisc-eval:${AISC_IMAGE_TAG:-latest}`, and `schema-docs` is in the infra file. With the
  variable unset, every name equals the f01288a name under project `aisc` (tested).
- **4.1 qualification.** `env_file: apps/qualification/env.development` is removed from `qualification-web` and
  `qualification-migrate`, so `DATABASE_URL` no longer merges in. Both services get `PROJECT_DATABASE_URL`
  (`{database}`, `schema=qualification`, `connection_limit=2`) and `FORM_LIBRARY_DATABASE_URL` (`platform`,
  `schema=form_library`) through one anchor, `&qualification-db-env`. `qualification-web` gets the file's other
  variables inline: `LLM_SERVICE_URL`, `SYSTEM_CARD_RENDERER_URL`, `ONTOLOGY_SERVICE_URL`, `PLATFORM_URL`,
  `LAUNCHER_URL` (now `${LAUNCHER_EXTERNAL_URL:-http://localhost:8100/}`). `qualification-migrate` runs
  `node scripts/migrate-projects.mjs` in the exit-2-aware loop and depends on `postgres` and `platform`. Every
  token line is unchanged.
- **4.2 control objectives.** Both services keep `DATABASE_URL` (platform, membership) and get
  `PROJECT_DATABASE_URL: ${CONTROL_OBJECTIVES_PROJECT_DATABASE_URL:-postgresql+psycopg://control_objectives_rw:control_objectives_rw@postgres:5432/{database}}`.
  `control-objectives-migrate` runs `python -m aisc_control_objectives.migrate_projects` in the exit-2 loop and
  depends on `postgres` and `platform`. No `PYTHONPATH` was added: the image sets `PYTHONPATH=/app/src` and installs
  the package editable. The header comment was updated.
- **4.3 engine.** The environment of `aisc-backend` became `&backend-env`. Its command no longer runs
  `manage.py migrate`, and it waits for `aisc-backend-migrate` (completed successfully). The new
  `aisc-backend-migrate` has the same build, image, environment, volumes and network. It depends on `postgres`
  and `platform` (started), has `restart: "no"`, and runs `uv run manage.py migrate_projects` in the exit-2 loop
  after the same `uv pip install` prefix. `DB_NAME=platform`, `DB_USER=engine_rw` and `DB_SCHEMA=engine` stay.
- **4.4 composer.** The environment of `report-composer` became `&composer-env`. `REPORT_COMPOSER_DATABASE_URL` is
  unchanged, and `REPORT_COMPOSER_PROJECT_DATABASE_URL` (`{database}`) was added. The composer now waits for
  `report-composer-migrate` (completed) and `platform` (started). The new `report-composer-migrate` uses the
  composer image and the same environment and identity volume. It runs
  `["python","-m","report_composer.migrate"]`, depends on `postgres-setup` (completed) and `platform`, and has
  `restart: "no"`. `report-grants` also waits for `aisc-backend-migrate`. The renderer is unchanged.
- **4.5 dashboard.** `AISC_RESULTS_DB_URI` is gone from the `&dashboard-env` anchor and from `dashboard`.
  `dashboard` alone gets
  `AISC_MEMBERSHIP_DB_URI: ${AISC_MEMBERSHIP_DB_URI:-postgresql+psycopg2://dashboard_ro:dashboard_ro@localhost:5432/platform}`.
  The header comment was updated.
- **4.6 `isolate` one-shot.** It is written as in the plan: platform image, `profiles: ["isolation"]`,
  entrypoint `python -m platform_service.isolate`. `ISOLATE_SUPERUSER_URL` carries no password, and
  `PGPASSWORD` comes from `POSTGRES_PASSWORD`. It mounts identity and the project template read-only, runs on
  network `backend`, and has `restart: "no"`. It has no `container_name`, so `run --rm` can be repeated.
- **`env.development`:** two comments only (`POSTGRES_DB`, the engine's `DB_*` block). No value changed.

## Deviations and decisions

- **D-W1-1 New test file** `scripts/tests/test_compose_w1.py` (6 tests; TDD: all 6 red before the wiring, green
  after). No stage-2 test pins the image tags, the `isolate` one-shot, `report-composer-migrate`, the
  report-grants wait, or the backend one-shot's environment. It resolves the f01288a files for the "names
  unchanged" check (no pyyaml needed). It never prints a DSN or password.
- **D-W1-2 Dashboard membership DSN on `dashboard` only**, not on the anchor. The plan override allows the anchor
  only when `test_i10_2_...[dashboard-migrate]` requires it, and that test only requires the absence of
  `AISC_RESULTS_DB_URI`. D1 step 6 had proposed both lines. If D1's `superset init` path needs the DSN in
  `dashboard-migrate`, W1 (or its successor) adds it there with `@postgres:5432`.
- **D-W1-3 Qualification DSNs through one anchor** (`&qualification-db-env` on `qualification-migrate`, merged
  into `qualification-web`). The resolved values are the same as two literal copies.
- **D-W1-4 `${VAR:-...{database}...}` form** for the qualification and control-objectives templates (W1 text),
  not O1.7's literal form. The resolved strings were checked byte for byte against the intended defaults.
- **D-W1-5 `report-composer-migrate` has no `build:`.** It reuses the composer's image, like `aisc-eval-flower`
  (as the plan says). `aisc-backend-migrate` keeps its own `build:` (as the plan says).
- Only the development compose files were changed. `docker-compose.staging.yml`, `docker-compose.yml`,
  `docker-compose.demo.nbg.yml`, `docker-compose.plugin_downloader.yml`, `env.staging` and
  `env.plugin_downloader` are untouched: the plan does not list them. The two dev files resolve with
  `--env-file env.plugin_downloader`, `AISC_IMAGE_TAG=isolation` and `--profile isolation` (exit 0, rule 4.7).
- `platform/Dockerfile` (`postgresql-client`) is P2's and was not touched.

## Test counts (config-only; before = branch at `0d408d2`, after = `215bb95`)

Command: the W1 command of 03-coding-plan.md, plus `scripts/tests/test_compose_w1.py` after it was written.

| suite | before | after |
|---|---|---|
| `test_compose_isolation.py` | 19 failed, 7 passed | 26 passed |
| `test_compose.py`, `test_service_tokens.py`, `test_inspector_network.py`, `test_isolation_unchanged.py` | green | green |
| `test_report_stack.py` | 2 known reds (`test_d6_guard_init_files_do_not_mention_report_roles`, `test_final_guard_frozen_passes`) | same 2 |
| `test_llm_keys.py` | 1 known red (`test_s4_2_the_manage_menu_links_the_page_for_admins_only`) | same 1 |
| `test_compose_w1.py` (new) | 6 failed | 6 passed |
| whole W1 command | 22 failed, 93 passed | 3 failed (the known ones), 112 passed; with the new file 3 failed, 118 passed |

`test_final_guard_frozen_passes` runs `scripts/guard-frozen.sh`, which starts and removes its own throwaway. No
`aisc-t-*` container of this WP was left. The ones listed during the run belonged to other wave-1 agents.

## What later packages must know

- **Every module:** these are the variable names compose now passes. Qualification: `PROJECT_DATABASE_URL`,
  `FORM_LIBRARY_DATABASE_URL`, and no `DATABASE_URL`. Control objectives: `DATABASE_URL` (platform) and
  `PROJECT_DATABASE_URL` with `postgresql+psycopg://`. Composer: `REPORT_COMPOSER_DATABASE_URL` and
  `REPORT_COMPOSER_PROJECT_DATABASE_URL`. Dashboard: `AISC_MEMBERSHIP_DB_URI` on `dashboard` only. Engine: the
  unchanged `DB_*`.
- **Q1:** `qualification-web` no longer reads `apps/qualification/env.development`, so a variable that must reach
  the container has to be requested from W1. The submodule's own `env.development` and Dockerfile `CMD` stay Q1's.
  `migrate-projects.mjs` must exit 2 on a permanent error and non-zero (not 2) to be retried.
- **O1:** the same exit-code contract for `aisc_control_objectives.migrate_projects`. The image's own
  `PYTHONPATH=/app/src` is relied on.
- **E1:** `manage.py migrate_projects` must exist and follow the exit-code contract. `aisc-backend` no longer
  migrates `platform` at start.
- **R1:** `python -m report_composer.migrate` runs in `report-composer-migrate` with the composer's full
  environment, before the composer starts.
- **D1:** see D-W1-2.
- **P2:** the one-shot is `docker compose --profile isolation run --rm isolate <subcommand> ...`. The URL has no
  password, and libpq takes `PGPASSWORD`. The container has `/app/project-template` and `/app/shared/identity`,
  and it does not mount `/app/migrations`. P2 still owns `platform/Dockerfile` (`postgresql-client` for
  `pg_restore`).
- **X1, stage 5 and 6:** build with
  `AISC_IMAGE_TAG=isolation REPORT_GENERATOR_DIR=$HOME/aisc-isolation-report-generator docker compose -p aisc-isolation-build ... build`.
  Unset, the names equal the running stack's. The live `up` must then use `AISC_IMAGE_TAG=isolation` (or
  re-tag), or it will run the old `:latest` images. `report-grants` now waits for `aisc-backend-migrate`, so V1's
  600 s wait for `engine.measurement` is no longer needed.
