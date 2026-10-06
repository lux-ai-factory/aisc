# apps/backend review pass, 2026-10-06 (the user's code only)

Pushed 2026-10-06 as one squashed commit `aef6d8e`; the short hashes below are the pre-squash ones (kept on the local branch `backup/backend-pass-2026-10-06-presquash`).


Branch `feat/unified-modules`, from origin `4f3fb33`. Steps 1-3, 5, 7 of `~/aisc-review-continue.md`;
4 and 6 as a reading in this session (the parent runs separate code-review and security agents);
step 8 is the parent's. Commits are local, unpushed, not squashed.

## Scope

`git blame --line-porcelain HEAD` on every tracked file; a line is in scope when its author is
`alessiobuscemi` or `Alessio Buscemi` (31 commits, 2026-06-10..2026-10-03): **5,869 of 15,856 lines,
80 files**. About 3,000 are tests; non-test code is mainly `project_door.py` (402), `projectdb.py` (270),
`auth/membership.py` (174), `management/commands/migrate_projects.py` (146), `deployment.py` (130),
`routers/target_input.py`, `routers/platform_project.py`, `platform_projects.py`,
`repositories/system_version_repository.py`, `signals/system_stamp.py`, and the user's lines in
`config/settings.py`, `config/urls.py`, `apps.py`, `services/celery_service.py`. Migrations 0015-0021
are the user's and applied: report only. Sean's, Carlo's and others' lines were not reviewed or changed.

## Findings

| Id | Sev | Where | Finding | Outcome | Commit |
|---|---|---|---|---|---|
| B1 | A (lint) | `tests/test_deployment_mode.py:54,67-71`, `tests/test_isolation_engine.py:44`, `tests/test_one_system_per_project.py:24` | ruff E731, E402 x4, F401 x2 | fixed; no fixture among the removed imports | `f8213f9` |
| B2 | A (doc bug) | `tests/test_isolation_engine_db.py` docstring, `README.md` Tests | The Postgres recipe omits `AISC_DEPLOYMENT=configurator`: followed as written, all 30 tests skip and the run says OK | recipe and README say so | `5492788` |
| B3 | B | `routers/target_input.py` `_ensure_system_target` | A GET (allowed to viewers) writes: it creates the system target row when missing, check-then-create with no lock or unique constraint, so two concurrent form loads can mirror the system target twice | not changed: the sound fix is a unique constraint on the component's target value, a migration on Sean's table | |
| B4 | B (follow-up) | `projectdb.run_ticket` | The run ticket has no expiry: valid for its project and evaluation as long as DJANGO_SECRET_KEY is the same (the internal secret is also required) | design choice, listed | |
| C1 | C | `models/__init__.py:2,8` | ruff F403 star imports | judged wrong for this file: lines 1, 3-7 (Sean's) re-export the same way; changing only the user's two would split one idiom | |

Also read, no finding: the door's check order (header, worker secret with constant-time compare and
ticket bound to project and evaluation, token and membership, admin-only plugin routes, platform
existence, open and migrate, every pid of a path or body checked against the admitted database, stored
files and tasks through `membership`); the router refusing any query with no project admitted; the
mode checks in `apps.py` / `deployment.py`; the test stamp; `migrate_projects`.

## Second round: independent code review (high) and security review

The parent session ran the `code-review` skill (high) and a security-review agent on the in-scope lines at
`4f3fb33` (read through git). Neither found a high-confidence bug in the code; the security review's
configuration question was checked against the stack's compose and was real:

| Id | Sev | Where | Finding | Outcome | Commit |
|---|---|---|---|---|---|
| R1 | S | `aisc_backend/projectdb.py` `run_ticket` | Run tickets were keyed with `DJANGO_SECRET_KEY`, which the eval worker holds (it decrypts plugin secrets with it) and the worker runs third-party plugin code: a plugin could mint a ticket for any project and evaluation and, with `INTERNAL_API_KEY` (also the worker's), call the internal routes | keyed with `RUN_TICKET_KEY`, held by the backend only; `deployment.check_environment` refuses configurator mode without it or with it equal to `DJANGO_SECRET_KEY`; standalone falls back to `SECRET_KEY`. Checked live: a ticket signed with `DJANGO_SECRET_KEY` from inside the worker gets 403 "the run ticket is not for this project and evaluation", the backend's own passes the door | `3ea220d` |
| R2 | A | `routers/platform_project.py:36-43` | Two first visits to a project at once: the second hit `IntegrityError` (500) | the row the other made is returned | `ed5ed38` |
| R3 | B | `project_door.py:103` vs `routers/plugin.py:235` (Sean's route) | Removing a plugin needs admin, but `PATCH .../enabled` (editor) flips the same flag | user decision: gate the toggle or drop the DELETE gate |  |
| R4 | B | `routers/target_input.py:46-55` (= B3) | GET creates the system target, no lock or constraint | user decision (a unique constraint is a migration on Sean's table) |  |
| R5 | A (after "fix all") | `config/settings.py:244` (Sean's line) | `AUTH_ENABLED` defaults off and configurator mode did not require it: unset, the door skipped membership and the admin check for every caller | `deployment.check_environment` refuses configurator mode without it; 5 tests; the stack sets it; the guard and the isolation bed set it for their throwaway engine | `10022df` |

## Third round: the user's decisions ("do all", 2026-10-06)

| Id | Change | Commit |
|---|---|---|
| R3 | `PATCH /plugins/{pid}/enabled` needs the realm admin role (gated in `project_door.py`, Sean's route untouched) | `c3fdc7f` |
| R4 | One system target per system: migration 0022 merges duplicates (inputs and derived components moved to the oldest) and adds a partial unique expression index in SQL; the create is race-safe; the guard's G1 lists the index | `c5f0f58`, `4fdf7e5`, `8c417c8`, `095d6b8` |
| B4 | Run tickets expire: `<expiry>.<HMAC over pid.evaluation.expiry>`, `RUN_TICKET_TTL_SECONDS` (default 86400); expired, tampered and old-format tickets refused. Checked live: a forged ticket and the backend's own with its expiry stretched both get 403, the backend's as issued passes the door | `5cd8730` |
| W5 | A project by any name, '/' included: `GET /api/v1/projects/by-name?name=` in a new `routers/project_by_name.py` (Sean's `routers/project.py` byte-identical); the old route still works. Checked live: both 200 | `435fb85`, `f5dfc71` |
| | The isolation harness mints tickets with `projectdb.run_ticket` and toggles as admin | `df1a483` |

Standalone and configurator suites 284 -> 295 run, the same old failures; Postgres isolation 30 OK. Live: 0022 applied in the project database with its index.

## Before / after

| Check | Before | After |
|---|---|---|
| `manage.py test` standalone (sqlite) | 269 run, 3 failed, 4 errors, 128 skipped | same |
| `manage.py test` configurator (sqlite) | 269 run, 3 failed, 4 errors, 49 skipped | same |
| Postgres isolation (30, throwaway Postgres) | 30 OK (with the mode set) | 30 OK |
| ruff E4,E7,E9,F (whole repo) | 37 (9 in the user's lines) | 30 (2 in the user's lines: C1) |
| pip-audit (lock, minus local aisc-*) | ecdsa 0.19.2: 2 advisories, no fix | same (not the user's lines) |

The 7 failures are outside scope: `tests/integration/test_integration.py` imports `DataShapeStatus`,
which Sean removed (`920de82`); three `test_project_config_router` errors come from Sean's
`routers/project_config.py:64` (a synchronous FK read in an async route, and an object compared with a
pid); three `test_keycloak_integration` failures are in a test file entirely by Meril-list.

## Step 8, on the isolated stack

Rebuilt with `./scripts/start.sh` (exit 0): `aisc-backend` started (its check found `RUN_TICKET_KEY`), the worker
holds no `RUN_TICKET_KEY`; R1 checked live as above; `engine_rw`'s old password, its name, is refused
("password authentication failed"), `scripts/verify-db-access.sh` 82 passed, 0 failed.
`scripts/guard-frozen.sh`: GUARD PASS (its G1 build now sets a throwaway `RUN_TICKET_KEY`; the intended list
names `aisc_backend/tests/test_run_ticket_key.py`).

## Root changes (made in the aisc root, same commit as this report)

- `engine_rw`'s password generated: `init/engine-role.sql`, `ENGINE_RW_PASSWORD` in `scripts/secrets.sh`,
  `postgres-setup`, `x-backend-env` `DB_PASSWORD`, `DB_PASSWORD=engine_rw` dropped from `env.plugin_downloader`
  and `env.development`, `scripts/verify-db-access.sh`. The engine-standalone compose now needs its own
  `DB_PASSWORD` (it says so).
- `RUN_TICKET_KEY=rand` in `scripts/secrets.sh`, in `x-backend-env` (aisc-backend and its migration only).
- `scripts/tests/test_engine_rw_and_run_ticket.py`.

## Root changes listed by the pass (now made)

`engine_rw` still logs in with its own name (`env.plugin_downloader:62-63`, `DB_USER=engine_rw`,
`DB_PASSWORD=engine_rw`; `docker-compose.development.yml:15` passes `DB_PASSWORD: ${DB_PASSWORD}` to
`x-backend-env`). The backend needs no change: it reads `DB_PASSWORD`. In the root, as for controls_rw:
`init/engine-role.sql` (`\if :{?engine_rw_password}` ... `ALTER ROLE engine_rw ... PASSWORD %L`);
`scripts/secrets.sh` `ENGINE_RW_PASSWORD=rand`; postgres-setup env, volume and psql line;
`x-backend-env` `DB_PASSWORD: ${ENGINE_RW_PASSWORD:?run scripts/secrets.sh first}` (and any other
service that sets `DB_PASSWORD` for engine_rw); drop `DB_PASSWORD=engine_rw` from `env.plugin_downloader`
and `env.development`; `scripts/verify-db-access.sh` `pw()` case and env.runtime read; a test like
`scripts/tests/test_controls_catalogue_role_passwords.py`.

## Follow-ups

- B3, B4 (decisions). Sean's: `DataShapeStatus` import, `project_config.py:64`, the Keycloak
  integration tests; `ecdsa` advisories when a fixed release exists.
- No functional change was made, so no image rebuild is needed for this pass.
