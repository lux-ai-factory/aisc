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

