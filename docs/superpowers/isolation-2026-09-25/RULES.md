# Rules for every stage of the isolation (read first, then PROGRESS.md)

## Goal and decisions (the user's)
- 2026-09-23, final: "every project is completely isolated from the others. Everything from step 1
  (qualification) to step 6 (dashboard) belongs to one project and lives in that project's own
  Postgres database. The only thing that connects projects is the homepage."
  (docs/superpowers/plans/2026-09-23-project-databases-roadmap.md; plan 1, controls, is built).
- 2026-09-25: "complete the isolation METICULOUSLY. It is a CRITICAL task." Full isolation INCLUDING
  the engine (Django backend + Celery worker route per project database; the engine's table
  definitions do not change, only where they live). The report composer, added after the roadmap,
  is in scope too. The old shared schemas may be dropped at the end, but only after a pg_dump of each
  and a row-by-row verification that every row is present in the project databases.
- What stays shared (roadmap): `platform` database with core.project and core.project_member (and
  core.schema_migration), the catalogue, Keycloak, Superset's metadata database, plugin code/devpi.
  Everything else, including core.system (the versioned AI card rows), moves into
  `project_<pid without hyphens>`.

## Workspace (other sessions are active in ~/aisc-install: never edit files there)
- Work ONLY in ~/aisc-isolation: a git worktree of the top-level repo, and one worktree per submodule,
  all on branch `isolation/2026-09-25`. Commit there by explicit path. NEVER push. Never check out,
  reset or commit anything in ~/aisc-install.
- node_modules are symlinked from ~/aisc-install (do not modify them).
- A copy of the live databases (pg_dumpall, 2026-09-25 11:49) is at ~/aisc-isolation-rehearsal/.
  Restore it ONLY into throwaway Postgres containers. It contains password hashes: never print it,
  never copy it into the repo.

## The running stack and live data
- NEVER run docker compose up/down/build/restart against the running stack (project `aisc`), never
  write to, migrate or drop anything in its databases, never exec into its containers to change them.
  Reading the live DB and logs is allowed. The orchestrator alone does the live migration.
- The live qualification schema already has the other session's forms tables
  (migrations 20260925090000_forms_are_data, 20260925120000_the_default_form_is_fixed, NOT committed
  anywhere yet; the files are in ~/aisc-install/apps/qualification/prisma/migrations, read them).
  Design so that per-project qualification schemas are built by replaying qualification's own Prisma
  migrations, and so the data move copies whatever tables and rows the live schema actually has
  (driven by the catalog, not by a hard-coded list), forms tables included.

## Method
- TDD: failing tests before implementation. Never weaken existing tests; change a test only where the
  approved design changes the behaviour it pins, and say so.
- Tests on throwaway databases only (recipe:
  ~/aisc-isolation/docs/superpowers/pipeline-2026-09-24-llm-keys/02-tests.md section 3, paths adapted
  to ~/aisc-isolation). ALWAYS set PLATFORM_TEST_DATABASE_URL and each module's test DB variable (the
  platform conftest deletes projects from the LIVE DB when it is unset). Remove containers afterwards.
- Data movement must be: idempotent, resumable, one project at a time, inside transactions where
  possible, and verified per table by row count AND an order-independent checksum of every row
  (e.g. md5 of the sorted row texts) between source and target. Any mismatch aborts.
- Security work already deployed must survive: per-caller service tokens, API auth, per-system LLM
  tokens, the LLM keys in each project's `llm` schema, the diagrams gate.
- Prose in docs without em dashes. Record progress in PROGRESS.md at the end of every stage.

## Confirmed by the user after stage 1 (2026-09-25)
- D3/D4: forms and report presets are ONE shared library in the `platform` database (like the
  catalogue); when a project uses a form version or a preset, that version is copied into the project
  database, so the project's data never depends on the shared copy afterwards. (01-specs.md D3, D4.)

## Added after the O1 incident (2026-09-25)
At about 14:54 UTC an O1 baseline run read a throwaway-DB env file from the SHARED scratchpad that
another agent had overwritten; its test DB variable was unset and an old conftest default pointed at
the live cluster, which dropped and recreated the (already empty) leftover database
`control_objectives_test` there. No data was lost (it was empty in the 11:49 dump). From now on:
- Each work package keeps its throwaway credentials and files ONLY in its own subdirectory
  `<scratchpad>/<WP>/` (e.g. .../scratchpad/Q1/), never in a file another agent could write.
- Before any test run, check that every DB URL you pass points at your own throwaway container's
  port (never 5432) and a non-live database name; abort otherwise.
