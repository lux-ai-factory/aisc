# apps/catalogue review pass, 2026-10-06

Pushed 2026-10-06 as one squashed commit `d9047f5`; the short hashes below are the pre-squash ones (kept on the local branch `backup/catalogue-pass-2026-10-06-presquash`).


Scope: the user's own code only. Branch `feat/unified-modules`, from origin `4a2d40d`. The branch starts at the
squash `feef7f7` (2026-09-14), which holds the work of Méril Miangouila (30 commits on master), Sean Blevins
(8) and the user (20). In scope:

- every line from a commit after the squash (all the user's): 4,633;
- squash lines that `git blame` on every remote branch credits only to the user: 6,326.

10,959 lines in 123 files. The other 6,643 (others' lines, and blank lines nobody is credited with) were not
reviewed or changed; one test fix touched a line by someone else because the user's `2396bf2` broke it.

Steps 1-7 by a fork (its own reading for steps 4 and 6); the parent session then ran the `code-review` skill
at high and a separate security-review agent on the in-scope code (R1-R7 below). Step 8 on an isolated stack
(Docker-in-Docker from `~/aisc-macfix`), not the live `~/aisc`. Commits are local, unpushed, not squashed.

## Findings

| Id | Sev | Where | Finding | Outcome | Commit |
|---|---|---|---|---|---|
| F1 | A (bug) | `backend/database.py` `init_db` | `CreateSchema` used without being imported: NameError on a database without the schema | imported; test | `d4eb04b` |
| F2 | A | `backend/Dockerfile` | Python 3.11 while `pyproject.toml` needs 3.12 (uv sync refused); no `.dockerignore`, a host `.venv` replaced the image's | 3.12, `.dockerignore`; test | `03aaac5` |
| F3 | S | `devpi/entrypoint.sh` | devpi's root user kept the image's empty password: anything that reached the index could publish a package the engine installs and runs | the entrypoint sets the password it is handed, says so when there is none; checked on the real image; root side generates and requires it (below) | `71f356a` |
| F4 | A | `frontend/src/crossSite/` back link | The `#env=` fragment is anyone's to write; the Back link took any scheme | absolute http(s) only | `0b9ab65` |
| F5 | A | `frontend/src/services/platformApi`, config | A dead one-click path would build `VITE_PLATFORM_INSTALL_TOKEN` into the bundle | removed; a test refuses secret-like `VITE_` variables; `tsc` clean | `c31e99c` |
| F6 | A (bug) | `backend/main_api.py` devpi upload | The stored row read the package name from the version segment: uploads were not installable | `/packages/<name>`; old rows resolve to the name | `6340afb` |
| F7 | A (bug) | `backend/main_api.py` `tools_seed.json` | An unreadable file was read as empty and overwritten; writes not atomic | refused when unreadable; atomic replace | `91b8a5b` |
| F8 | A (bug) | `PUT /tool/{id}/` | Any tag gave a 500 (ids assigned to the relationship) | tags set from ids, kept when absent | `e2960f3` |
| F9 | A | control ingest | Parsing and the LLM call blocked the event loop (health stopped answering) | run off the loop | `cf0d2c6` |
| F10 | A | control form | Fields longer than their columns gave a 500 after the paid LLM call | checked before parsing and the call | `1403048` |
| F11 | A | control upload | `.xls` taken for `.xlsx`; a damaged file gave a 500 | 400 with the reason | `59fd2e5` |
| F12 | A (bug) | frontend install | A framework entry went down the control install | only the control tag does | `43baab7` |
| F13 | A | backend | 216 ruff errors; two star imports | clean; explicit imports | `fa55f19`, `7140f08` |
| R1 | B | `backend/sql_alchemy.py`, migration 0002 | Five tables renamed; only the Postgres migration moves the data, and SQLite deployments (AWS deploy, standalone compose) never run Alembic: an existing SQLite catalogue comes up with tools missing tags, metadata and questions (the old rows stay, recoverable) | not changed: user decision (add a SQLite rename step, or declare Postgres-only) |  |
| R2 | A | `ToolDetailModal.tsx:173` | The new install action ignored `VITE_ENABLE_INSTALL`: a build without installs offered "Install into a project" everywhere | gated again (the stack's build sets it) | `8021565`, `11c0c82` |
| R3 | B | `ToolDetailModal.tsx:208` + `catalogue_bridge.py:191` | The browser's install-info check is behind the server-to-server bridge token: once the hosted catalogue sets it, the public site says "could not reach the install service" on every test | not changed: user decision |  |
| R4 | A | `main_api.py:1427,1478` | A topic standing in for the description, and the file name, could still exceed their columns after the LLM call | held to the column before the call | `358397f` |
| R5 | A | `main_api.py:177` | Two tool writes at once could drop one entry from `tools_seed.json` (shared temp name, no lock) | own temp file, one locked step | `f7a7fe1` |
| R6 | A | `CrossSiteContext.tsx:136` | Disconnect kept the back link, the handshake and the project | forgets all of them | `59f249f` |
| R7 | A | `catalogueApi.ts:283` (security review, medium) | The slug went unencoded into the install path: with `/` or `..` the admin's POST could reach another platform route | encoded as one path segment, install and install-info | `014131b` |
| R9 | A (after "fix all") | `docker-compose.yml:51`, `deploy-aws/docker-compose.prod.yml:53` | devpi got `DEVPI_PASSWORD`, which it never reads (root stayed passwordless), with a literal `devpi-password` | devpi gets `DEVPI_ROOT_PASSWORD`, the backend the same value as `DEVPI_PASSWORD`, both required; 6 tests (one line was Méril's `c5634e6`, changed because `71f356a` made `DEVPI_ROOT_PASSWORD` what devpi reads) | `af3ed3c` |
| R8 | A | `devpi/entrypoint.sh:35` | A volume holding another root password made devpi restart-loop without a word | says why and how to fix, still exits 1 | `d4eaadb` |

The security review found nothing at high confidence: writes need a verified Keycloak token with the admin
role (fails closed without the settings), entry text renders as escaped React text, the cross-site fields
accept only http(s) addresses and a uuid, CORS is a named allow-list.

## Decisions for the user (not changed)

1. The standalone backend image cannot start: `aisc_identity` is not in it (recommended: install it from the
   aisc repo at a pinned tag).
2. Migrations 0001/0002 fail on a fresh database (`no such table: metadata`); they are applied migrations,
   so making 0002's renames conditional needs a yes.
3. Deleted seeded controls reappear after a restart.
4. Back link: an allow-list of platform origins, and a cap on the handshake's `expires`?
5. The handshake is shared by every tab (`localStorage`); `sessionStorage` would keep one project per tab.
7. R1 (SQLite renames) and R3 (install-info behind the bridge token).

Out of scope, reported only: `AddControl.tsx:418` still offers `.xls`; `POST /tool/bulk/` has the tag bug of
F8; a new wheel version creates a duplicate slug row (`.first()` then picks one).

## Third round: the user's decisions ("do all", 2026-10-06)

| Decision | Change | Commit |
|---|---|---|
| 1 | The standalone backend image has `aisc_identity`, from the aisc repo's `shared/identity` at pinned commit `1a06b3f` (a source archive: a git source would clone two private submodules); the build checks the import | `1179ed9` |
| 2 | Migration 0002 renames only what exists under the old name (user approved changing an applied migration): a fresh database and one at 0001 end at the same schema, rows kept (throwaway Postgres) | `1f1ed20` |
| 3 | Deleted seeded entries stay deleted (`deleted_seed`, migration 0003); creating the slug again lifts it | `aa65696`, `fc16515` |
| 4, 5 | The handshake is per tab (`sessionStorage`), one lasting more than 61 minutes is refused, Back only to `VITE_BACK_ORIGINS` (default `http://localhost`, `http://localhost:8100`) | `bb30556` |
| R1 | SQLite start-up adopts the old table names once (rename, or copy rows and drop) | `e99426c` |
| R3 | install-info is open (read-only, public data); the bridge token guards the controls export; controls and frameworks no longer ask devpi | `8f6bc19` |

Backend 132 -> 145 passed, frontend 130 -> 133 passed; ruff, tsc and build clean.

## Before / after

| Check | Before | After |
|---|---|---|
| backend pytest | 101 passed | 132 passed |
| ruff | 216 errors | 0 |
| frontend vitest | 125 passed | 130 passed |
| `tsc --noEmit` | 82 errors (test files) | 0 |
| frontend build | ok | ok |

## Step 8, on the isolated stack

`./scripts/start.sh` rebuilt and restarted what changed (exit 0). devpi refuses root with an empty password
("401 Unauthorized") and accepts the generated one; `plugin-publisher` uploaded with it (exit 0);
`scripts/verify-plugins.sh` 31 PASS. `catalogue_rw`'s old password is refused, the generated one works.
In a real browser, signed in: `/project-catalogue/?project=<slug>` 200.

One warning, not this code: `sandboxconfigurator.aifactory.lu` resolves to two addresses, one of which serves a
certificate for `aws.list.lu`, so calls to the hosted catalogue fail at random with a certificate error.

## Root changes (made in the aisc root, same commit as this report)

- devpi's root password generated and required: `DEVPI_ROOT_PASSWORD=rand` in `scripts/secrets.sh`,
  `${DEVPI_ROOT_PASSWORD:?...}` for `devpi` and `plugin-publisher`, the empty `DEVPI_ROOT_PASSWORD=` removed
  from `env.plugin_downloader` and `env.development`; `scripts/tests/test_devpi_root_password.py`.
- `catalogue_rw` gets a generated password (no service of this stack logs in as it; the role could):
  `init/catalogue-role.sql`, `CATALOGUE_RW_PASSWORD`, `postgres-setup`, `scripts/verify-db-access.sh`;
  `scripts/tests/test_controls_catalogue_role_passwords.py`.
