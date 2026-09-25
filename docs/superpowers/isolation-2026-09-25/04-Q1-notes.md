# Stage 4, WP Q1: qualification on one database per project

Date: 2026-09-25. Submodule worktree `~/aisc-isolation/apps/qualification`, branch `isolation/2026-09-25`. Nothing
pushed; no live database or running container touched. Every DB run used the harness's own throwaway
`postgres:14-alpine` (`aisc-t-iso-Q-*`, random port, credentials generated inside the harness and never written to
a file; outputs in `scratchpad/Q1/`); no `aisc-t-*` container is left. The work was interrupted once by a usage limit
and resumed from the uncommitted tree; everything was re-checked before committing.

## Commits (apps/qualification)

| commit | content |
|---|---|
| `0631f8b` | agents: `/fill/{pid}/{id}`, runs keyed `"{pid}/{qid}"`, `fill_one(pid, qid)`, clients under `/p/{pid}`; the 4 agents tests of S-D13 |
| `3b2b9dc` | `Isolation test correction T3` (`test_isolation_paths.py` fake `config_for`) |
| `6f42369` | `Isolation test correction T1` (baseline name in `isolationBaseline.test.ts`, `projectDatabase.db.test.ts`) |
| `e16229a` | `Isolation test correction T2` (`isolationActionsAndPages.test.ts` closes cached clients) |
| `4586fd7` | projectDb.ts and the doors, middleware, repository, services, routes under `/p/[project]`, actions, pages, schema, baseline `20260925000000_project_database`, scripts, the changed tests of sections 5 and 7 |
| `0016d51` | `env.development` (`PROJECT_DATABASE_URL`, `FORM_LIBRARY_DATABASE_URL`), `Dockerfile` CMD `next start` only |

Top level: the `apps/qualification` gitlink (the plan's top-level commit minus compose, which W1 owns and has landed).

## Test counts

| suite | before (red) | after |
|---|---|---|
| unit vitest (`test/unit`) | 97 failed, 458 passed, 3 skipped (with the local node_modules; `secrets.test.ts` passes now) | 551 passed, 3 skipped (0 failed) |
| `tsc --noEmit` | clean | clean |
| DB (`test/db/throwaway-db.sh`) | 02-tests.md: 9 passed, 22 failed, 16 skipped (not re-measured: the old harness migrates into `platform`, which P1's init files no longer allow) | 31 passed, 9 skipped (the Q2 formLibrary cases, gate I4.6) |
| agents pytest | 8 failed, 167 passed | 175 passed |
| top-level `test_compose.py`, `test_compose_isolation.py`, `test_service_tokens.py`, `test_llm_keys.py` | | 74 passed, 1 failed (the known `test_llm_keys` red of 02-tests.md) |
| `test_project_grants.py -k qualification` | | 3 passed, 5 failed: every failure is `report_composer ... schema_migration missing` (the bed requires all modules; R1 is wave 2). The bed recorded no qualification problem. |

## Deviations and decisions

- **D-Q1-1 Probe before migrating.** The I2.5 DB test showed that `prisma migrate deploy` on a dropped database tries
  to CREATE it again (it failed only because qualification_rw has no CREATEDB, with a message that does not say
  "does not exist"). `prismaFor` now runs `SELECT 1` on the new client before the migration: a missing database fails
  with P1003, the entry is forgotten, and the doors answer 404. Also a safety gain: the app can never recreate a
  deleted project's database.
- **D-Q1-2 T2 typed.** The plan's literal T2 line fails `tsc` (`load` returns `Record<string, unknown>`); it is
  written `load<{ closeProjectDatabases?: () => Promise<void> }>(...)`. Same behaviour.
- **D-Q1-3 `test/chain/chain.test.ts`** (not in the plan's lists): only the `projectId` line of the card it creates is
  removed, because `tsc --noEmit` fails otherwise. Its `core.system` assertion and its harness stay for V1 (G2, I19.2).
- **D-Q1-4 `writeAccess.test.ts`**: the deleted `qualificationForWriter`/`projectForWriter` cases are re-expressed
  against the real `projectDbForAction` (Prisma and `node:child_process` faked); "a missing qualification is 404" is
  no longer a door case (the door does not know cards), it is pinned per database by the F6/F7 and isolation tests.
- **D-Q1-5** The fill route and FillerClient encode both path segments (`encodeURIComponent`); identical for pids and
  cuids. Routes were moved with `git mv` (history kept) rather than deleted and created.
- **D-Q1-6** The agent refuses an export whose `projectId` differs from the path pid (`ServiceError`), as the plan says.
- **D-Q1-7** The harness also refuses to run unless every exported test URL is on the throwaway's port (the new RULES
  item after the O1 incident).

## Not done / for other packages

- Left as the plan says: `scripts/seed_examples.mjs` (cannot create a card since WP3), the submodule's standalone
  `docker-compose*.yml`, `DEPLOY.md` and `README.md` still describe `DATABASE_URL` and `prisma db push`.
- **V1 (F6)**: `scripts/tests/test_card_version_keys_orders.py` (step Q), `scripts/guard-frozen.sh --orders` and
  `scripts/test-pipeline-chain.sh` migrate qualification into `platform`; the new baseline cannot replay there
  (`project.system` absent). `test/chain/chain.test.ts` still asserts the FK target `core.system`.
- **Q2**: the forms migrations must sort after `20260925000000_project_database` (they do by name). The forms
  migration drops `qualification."QualificationAnswer_qualificationId_questionId_key"`, which the baseline creates.
  `FORM_LIBRARY_DATABASE_URL` is in env but unused; migrate-projects.mjs has no library step yet.
- **R1**: the qualification-parametrised grant tests pass only once report_composer migrates in the bed.
- **X1/cutover**: live URLs under `/api/qualifications/*` are gone; anything outside this app that linked them must
  use `/p/{pid}/api/qualifications/*`. The control-objectives HTTP call to
  `/p/{project}/api/system-versions/{pid}/ontology.jsonld` is unchanged, but `{project}` must now be a pid (a slug is
  404 at the middleware).
- **Local node_modules**: the worktree has a real, untracked `node_modules` (symlinks plus private `@prisma` and
  `.prisma`); `npx prisma generate` writes only there. The install's `.prisma/client` was regenerated at 19:17 by
  another session (its schema still has `projectId` and the form models, which this branch's schema has not); this WP
  did not write it.
