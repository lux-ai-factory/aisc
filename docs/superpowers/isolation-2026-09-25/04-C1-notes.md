# Stage 4, WP C1: controls, the answer key into project.system, reader grants, 404 after a drop

Date: 2026-09-25. Branch `isolation/2026-09-25`, worktree `~/aisc-isolation/apps/controls` (plus these notes, the
PROGRESS line and the controls gitlink in the top-level worktree). Nothing pushed. No live database or running
container touched: every run was on throwaway `postgres:14-alpine` containers named `aisc-t-iso-C1-*` on random
ports (new-layout recipe of 03-coding-plan.md section 1.1), all removed afterwards. The controls integration
files that `docker exec postgres` (project-scope, action-access, install, project-database, submission-lifecycle,
chain) were never run. `node_modules` (a symlink into `~/aisc-install`) was not modified or committed. The
catalogue install fix (CATALOGUE_URL) and the controls-pdf service token are untouched (no file of theirs in the
diff).

## Commits (`apps/controls`)

| commit | content |
|---|---|
| `d63751b` | test helpers of C1.4: `throwawayDb.makeProject()` applies every template file as platform_rw (inline loop, honours `ISOLATION_TEMPLATE_DIR`); `answer-stamps.test.ts` inserts V1 and V2 into `project.system`; two new cases in `projectDb.test.ts` |
| `c8e7ff7` | `dashboard-grants.test.ts`: one existing case changed (deviation D-C1-2), one case added |
| `9415f85` | migrations `20260926000000_an_answer_is_of_a_version_in_this_database` (I6.2) and `20260926000100_readers_read_the_listed_tables` (N5, I2.6); `src/lib/projectDb.ts` (I2.5); `src/types/pg.d.ts` |

Top level: the controls gitlink and these notes (C1.7 step 3).

## What changed

- **FK migration** exactly as C1.3: it refuses when `project.system` is missing, then when an answer names a pid
  absent from `project.system` (the message names the first such pid, the count and `project.system`, no other row
  value), and only then adds `submission_answer_system_version_pid_fkey` ON DELETE NO ACTION ON UPDATE NO ACTION.
  The operational note for X1 (`prisma migrate resolve --rolled-back ...` after a refusal) is in the file's comment.
- **Reader migration** exactly as the plan override: the default privilege for dashboard_ro revoked, SELECT on
  `_prisma_migrations` revoked from dashboard_ro, SELECT on the five listed tables granted to report_ro and
  dashboard_ro when the role exists. `20260923210100_dashboard_reads_controls` is unchanged (Prisma checksums).
- **`projectDb.ts` (I2.5)**:
  - `isMissingDatabase` also reads `err.stderr` and `err.stdout` (P1003 or "database ... does not exist").
  - The `$use` handler forgets the client and calls `notFound()` on a missing database. On a lost connection
    (P1001, P1017, "terminating connection", "server has closed the connection") it forgets the client, asks
    `pg_database` over `pg` on the template with `{database}` replaced by `postgres`, and calls `notFound()` when the
    database is gone; otherwise it rethrows.
  - `projectDbFor` wraps `prismaFor`: a failed open is `notFound()` when the error names a missing database or when
    `pg_database` says it is gone (see D-C1-1).
  - `MAX_OPEN_PROJECTS = 20` and `connection_limit=2` are unchanged. If the probe cannot reach the cluster, the
    original error is kept.

## Deviations and decisions (the plan was wrong or silent)

- **D-C1-1 A database that never existed does not fail with P1003.** Measured: `prisma migrate deploy` against an
  absent database tries to create it and fails with "Schema engine error: ERROR: permission denied to create
  database" (controls_rw has no CREATEDB). The plan's stderr match alone cannot turn "a pid whose database never
  existed is not found" green. Smallest fix: after a failed open, `projectDbFor` asks `pg_database` (the same probe
  the plan already asks for after a lost connection). Consequence worth knowing: **if controls_rw ever gained
  CREATEDB, opening a deleted project's pid would re-create its database.** The live role must keep NOCREATEDB.
- **D-C1-2 A pre-existing test pinned the default privilege that N5 revokes.** In `dashboard-grants.test.ts`, the
  case "a table controls_rw makes later is readable too (default privileges)" contradicts I2.6 and the plan's N5
  override, but the plan did not list it. The approved design changes what it pins, so it becomes "I2.6: a table
  controls_rw makes later is not readable (no default privilege to a reader)", which also asserts that
  `pg_default_acl` has no reader entry. It was committed on its own (`c8e7ff7`, reason in the message). The same
  commit adds "I2.6: report_ro and dashboard_ro read exactly the five listed tables, not _prisma_migrations",
  because `scripts/tests/test_project_grants.py` cannot prove the controls part until every module WP has landed.
- **D-C1-3 `src/types/pg.d.ts`** (new): the probe uses `pg`, which ships no types, and `@types/pg` is not installed
  (node_modules must not change). A minimal declaration of `Client` keeps `npx tsc --noEmit` clean.
- **D-C1-4** `answer-stamps.test.ts` inserts the versions with the test's uuid constants V1 and V2. The plan's text
  wrote literal `'V1'` and `'V2'`, which are not uuids.
- `projectDb.test.ts` new cases: "recognise a missing database in a failed migration's output" (red before) and
  "do not take a lost connection, on its own, for a missing database" (a guard, green before and after).

## Test counts (throwaway databases)

Command: C1.6 step 1 (unit plus answer-stamps, dashboard-grants, install-once-throwaway, isolation-answer-fk,
isolation-routes-by-id).

| state | result |
|---|---|
| before (branch at `bc5aca2`) | 9 failed, 150 passed (159): the 9 reds of C1.1 |
| after the test commits (`c8e7ff7`, no product code) | 12 failed, 150 passed (162): the 9, plus the new stderr unit case and the two dashboard-grants cases |
| after (`9415f85`) | **162 passed, 0 failed** (the plan's 159 target plus the 3 cases added here) |
| `npx tsc --noEmit` | clean |
| `scripts/tests/test_project_grants.py -k controls` | 4 failed, 1 passed, before and after. All 4 stop in `bed.require(*ALL_MODULES)` on qualification (I3.6), control objectives (I5.5) and the composer; controls is no longer among the missing features. They turn green once Q1, O1 and R1 land. |

## What later packages must know

- **X1 / cutover**: both new migrations are held back to C8b (after the copy), per the plan override. If
  `controls-migrate` runs at C7 unchanged, `migrate deploy` applies them too and the FK refuses on any database
  whose `project.system` is not yet filled. So C7 must pin controls to `20260923210100` (or skip controls) and C8b
  runs the full deploy. After a refusal, run `prisma migrate resolve --rolled-back
  20260926000000_an_answer_is_of_a_version_in_this_database` before deploying again. The grants migration sorts
  after the FK migration, so it never applies while the FK is refused.
- **Every stamped answer needs its version in `project.system`** of the same database before insert: the platform
  writes the version first (D2, I2.2). Test beds that stub the platform must insert those rows (as answer-stamps
  now does).
- **Every controls test bed must make project databases with every template file** (at least 0006). A database with
  only 0001 can no longer be migrated by controls.
- **V1 / Z1**: dashboard_ro no longer reads `_prisma_migrations` or later tables in the controls schema, and
  report_ro now reads the five controls tables through the migration (not only through report-grants).
  `scripts/report-grants.sh` (I2.7) should grant the same five and nothing else.
- **Live role check (D-C1-1)**: controls_rw must stay NOCREATEDB, or a deleted project's database is re-created on
  the next open.
- **Probe connection**: the 404 check connects as controls_rw to the `postgres` database (as migrate-projects.mjs
  already does), with a short-lived `pg.Client`, only after an error.
