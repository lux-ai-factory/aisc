# Progress

| stage | output | status |
|---|---|---|
| 1 survey + specs | 01-specs.md | done 2026-09-25 |
| 2 tests | 02-tests.md + tests | done 2026-09-25 |
| 3 coding plan | 03-coding-plan.md (work packages) | done 2026-09-25 |
| 4 code | one fresh agent per work package | pending |
| 4 / P1 | platform: template 0006..0010, project.system, init files (04-P1-notes.md; commits 8c13e87, a9a0397, d9fe305, a774ba2, aae72d1) | done 2026-09-25 |
| 4 / W1 | compose and env wiring: DSN templates, migrate one-shots, membership DSN, isolate one-shot, image tags (04-W1-notes.md; commits 3a3c672, 215bb95) | done 2026-09-25 |
| 4 / C1 | controls: FK into project.system (I6.2), reader grants of I2.6 (N5), 404 after a dropped database (I2.5); controls suite 162 passed, 0 failed (04-C1-notes.md; controls commits d63751b, c8e7ff7, 9415f85) | done 2026-09-25 |
| 4 / D1 | dashboard: engine dataset on each project's own connection (project.system, no pid filter), memberships over AISC_MEMBERSHIP_DB_URI (NullPool), no AISC Results registration, remove_results_connection() for C12; dashboard suite 140 passed, 0 failed (04-D1-notes.md; results-dashboard commit 7ff4999) | done 2026-09-25 |
| 4 / E1 | engine part 1: project aliases + router (dummy default, core-only platform alias), migrate_projects with advisory lock and I2.6 reader grants, 0025 FK to project.system, stamp on project.system, Dockerfile without migrate; E1 tests green except one flagged test bug (i7_9 `%` placeholder); sqlite 32F/5E and single-db Postgres 32F/5E, none newly red (04-E1-notes.md; backend commits 922f6dc T5, 58fed4c, fe5cdeb) | done 2026-09-25 |
| 4 / O1 | control objectives: ProjectDatabases.open (membership before connect, LRU 20, pool 2), /p/{pid}/api, alembic baseline 20260926000000_project_database on project.system, migrate_projects; suite 372 passed, 1 skipped (was 38F/20E); incident: one early run hit the live leftover control_objectives_test (04-O1-notes.md; control-objectives commits 8af01ca, 3ef8b69) | done 2026-09-25 |
| 4 / Q1 | qualification: projectDb.ts doors (LRU 20, limit 2, probe before migrate), card routes under /p/{pid}, baseline 20260925000000_project_database on project.system, migrate-projects.mjs, agents /fill/{pid}/{id}; unit 551 passed (was 97F), DB 31 passed 9 skipped (Q2), agents 175 passed (was 8F); T1, T2, T3 made (04-Q1-notes.md; qualification commits 0631f8b, 3b2b9dc, 6f42369, e16229a, 4586fd7, 0016d51) | done 2026-09-25 |
| 4 / R2 | renderer reads project databases (04-R2-notes.md; renderer 91346b1, top-level c85c5b0); renderer 672 passed; 3 composer e2e red until R1 | done 2026-09-25 |
| 4 / P2 | move tool `python -m platform_service.isolate` (catalog placement + rule L, conflicts, one transaction per project, FK anti-join, count + md5 before commit, idempotent/resumable, dry run writes nothing, verify-dump of the two G7 files; Dockerfile bookworm + postgresql-client); test_isolate 54 passed, 4 failed (was 55F/3P; the 4 are flagged test bugs T8 xact_commit x3 and T9 unique clash, orchestrator decides), rest of platform 342 passed 2 skipped (unchanged); live copy: 1 project, 45 tables classified, 0 unclassified/conflicts/unowned, dry run 47 project + 30 library rows, wrote nothing (04-P2-notes.md; commits fd5d992, 4b7046b, 61db3f9, cfcfe5e, 5504dce, e3a897a, f55b7fa) | done 2026-09-25 |
| 4 / E2 | engine part 2: the door (X-AISC-Project; worker secret, run ticket, named evaluation; membership before the database opens; core.project check; open_alias 404/503; same-project checks on paths and bodies), ticket on dispatch, worker carries project/evaluation/ticket on every internal call, SPA's one network module (apiFetch/apiAxios); open issue 7 closed and pinned (ROUTES row + new test_isolation_result_route.py, 4 red before, 4 green); T6, T7 made; sqlite 2F/5E (was 29F/5E), engine_db 24 passed 4 red (was 10 red), eval 15P 1F 1E (was 6P 10F 1E), webapp 46P 1F (was 42P 5F); flagged D-E2-1..4 (three engine_db test bugs, wp13Undo S13.2 byte pin) (04-E2-notes.md; backend 10005c9, 6e31f06, 18e670c; eval e0d6d42; webapp 77b4346, a6e46dd) | done 2026-09-25 |
| 4 / T11 | isolation test correction (D-E2-1): `CONTROLS` row for `/evaluations/{evaluation_pid}` and `test_i7_3_the_worker_reads_its_own_evaluation` now send `?include=plugin` / `?include=project,plugin`, which the frozen route needs (backend commit 1371a57) | done 2026-09-25 |
| 4 / T12 | isolation test correction (D-E2-2): `test_i7_2_listings_under_b_hold_nothing_of_a` reads `e["evaluation_pid"]`, matching `EvaluationByStatusResponseSchema` (backend commit e0e70a3) | done 2026-09-25 |
| 4 / T13 | isolation test correction (D-E2-3): `ApiCaller.call` passes multipart POST bodies as a field dict, not pre-encoded bytes, so Django's test client no longer tries `.items()` on bytes (backend commit 03b7c97) | done 2026-09-25 |
| 4 / T14 | isolation test correction (D-E2-4): `wp13Undo.test.ts` S13.2 compares `AISystemSettings.tsx` to 429f62c after the G4 normalisation (`apiFetch(` -> `fetch(`, drop the `projectHeader` import, drop `// I7.4 (isolation)` lines) (webapp commit bf9c889); verified `test_isolation_engine_db.py` 28 of 28 and webapp `npx vitest run` 47 passed, throwaway container removed | done 2026-09-25 |
| 4 / R1 | report composer: two DSNs (platform for core.project/members and report_library, `{database}` template per project), ProjectDatabases (guard first, migrate on first open under lock 8_190_233_707, 404 after a dropped database, one connection per call), project baseline 0001 and library 0001_presets (D4), old 0001..0005 moved to pre_isolation_migrations; composer 483 passed, 0 failed (was 59F/424P), renderer 672 passed, move-tool fixtures 3 passed, scripts reds unchanged (V1's and the 2 known); no flagged tests (04-R1-notes.md; commits 657f822, ea75695) | done 2026-09-26 |
| 4 / V1 | verification and harnesses: schema-docs labels (I11.3), tpg_project_db (I19.2), db_consistency per project database + heads.py (I16.6), report-grants.sh repairs the I2.6 list in every project database, platform untouched (I2.7), verify-project-databases.sh (I16.1..I16.7) run by verify.sh, verify-db-access.sh on a throwaway project database (I19.1), guard G1/G2 in a project database, G4 lists of E1/E2, --orders on f01288a trees (I7.12), pipeline chain on project databases, N7 narrowed (I19.3), report-composer-migrate exit-2 convention; scripts/tests 429 passed 56 failed (was 335/131): left red X1 44, Q2 2, known homepage/on-purpose 6, guard 4 not the isolation's (0024 and older Sean-file changes, D-V1-5, orchestrator decides); composer 489 passed, renderer 672 passed; CHAIN PASS and every break OK (04-V1-notes.md; commits e8ea680, 28c9a7c, a5c182c, 2951a13, 0f434d9, 9708f12, 361f138, 29c4495, f85900c, 99d253b, c5204ab; qualification 0d6f8ca, control-objectives f1e8c07, backend 1cc8bbc) | done 2026-09-26 |
| 5 verify + full rehearsal on the live copy | 05-rehearsal.md | pending |
| 6 live migration | orchestrator, stack quiet | pending |
| 7 drop shared schemas after dump + verify | orchestrator | pending |

## Stage 1 notes (2026-09-25)

- Survey read-only (live DB with SELECTs in read-only sessions); nothing written outside this folder.
- Key decisions (01-specs.md section 22): `core.system` becomes `project.system` in each project database
  (D1), the platform stays its only writer (D2); the forms library stays install-wide in
  `platform.form_library` with copy-on-use into each project (D3, conflicts with strict isolation, flagged
  for the user); report presets in `platform.report_library` (D4); the move tool is
  `python -m platform_service.isolate`, superuser, one transaction per project, catalog-driven ownership,
  count + md5 checksums, never writes `platform` (D5, D14, D15); shared schemas are retired (owner to
  superuser, privileges revoked) at cutover and dropped only in stage 7 after dump + verify-dump (D12).
- Gates for later stages: the forms work must be committed on feat/unified-modules and merged here before
  WP Q2 and before cutover (I4.6); the report renderer needs a new worktree
  `~/aisc-isolation-report-generator` (D9); report_composer 0003..0005 are not applied live and run first
  in cutover step C4 (D13).
- Work packages (section 21): P1, P2, Q1, Q2, O1, C1, E1, E2, R1, R2, D1, V1, X1.

## Stage 2 notes (2026-09-25)

- Resumed after a usage limit; every file left behind was reviewed and kept (fixed or finished), none deleted.
  No product code changed; nothing pushed; every throwaway container removed.
- Commits: top-level 78b64fd, fd88f32, ebd0ae8, efded99, 07a2e19 (+ the docs/gitlinks commit); qualification
  bfc69ef; control-objectives 22ba3a2; controls bc5aca2; backend 3e262a7; eval 7f7de02; webapp a27871b;
  results-dashboard 9e0d018; renderer (~/aisc-isolation-report-generator) 27bb0cb.
- Every requirement ID of 01-specs.md is named by at least one test (119 of 119). Red counts, baselines and
  commands per suite in 02-tests.md section 3; every pre-existing test keeps its baseline result.
- Q2 (forms, D3) tests are written and skip at run time with the I4.6 gate reason until the forms work is merged.
- Decisions S-D1..S-D13 and 12 open issues for stage 3 in 02-tests.md sections 5 and 6; notable: I15.2's
  pg_dump command is wrong (-t overrides -n), engine.metric_category_metrics is not placed by I12.3, fresh
  volume needs platform migrations 0002..0004 guarded, and an existing unguarded engine route
  (GET /plugins/{pid}/evaluations/{uuid}/result) was found.

## Stage 3 notes (2026-09-25)

- Read-only research (one agent per module, the platform and framework by the stage agent); one throwaway PG14
  probe (removed) confirmed that platform_rw cannot `ALTER ROLE <other> IN DATABASE ... SET`. No product code, no
  test edited, nothing pushed.
- Order (03-coding-plan.md section 3): wave 0 P1; wave 1 W1, P2, Q1, O1, C1, E1, R2, D1; wave 2 E2, R1; wave 3 V1
  and Q2 (when the I4.6 gate opens); wave 4 X1; wave 5 Z1 (every suite together).
- Global decisions G1..G9 (section 2): W1 is the only writer of compose and env files; V1 owns guard-frozen,
  throwaway-pg, pipeline chain; the old layout is a fixture copied from f01288a; C9 marks retired objects with a
  `retired:` comment that every-start init files respect; a superuser-owned definer function sets the module
  search_paths; the qualification baseline is `20260925000000_project_database` (supersedes I3.5's name); the
  stage-7 dump is two files (supersedes I15.2); the copy stops at the first failed project; isolation images get
  their own tag.
- Open issues 1..12 of 02-tests.md resolved in section 5 (engine.metric_category_metrics by rule L, fresh volume by
  guards inside platform migrations 0002..0004, the live leak on
  GET /plugins/{evaluation_plugin_pid}/evaluations/{evaluation_uuid}/result closed by E2's door and still exposed
  live until cutover), plus new issues N1..N9.
- Tests flagged wrong, with the named correction a WP makes (section 4): T1 baseline name (3 files), T2
  isolationActionsAndPages cache reset, T3 agents fixture type, T4 formLibrary fixture (Q2), T5 engine _seed
  connection, T6 engine CONTROLS artifacts row, T7 Sean's two webapp tests. Weak but kept: W-1..W-6.
- For the user before stage 6: which env file the live cutover uses, and which directory the live stack runs from
  after C11 (section 5).

