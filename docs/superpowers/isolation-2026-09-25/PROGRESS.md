# Progress

| stage | output | status |
|---|---|---|
| 1 survey + specs | 01-specs.md | done 2026-09-25 |
| 2 tests | 02-tests.md + tests | done 2026-09-25 |
| 3 coding plan | 03-coding-plan.md (work packages) | pending |
| 4 code | one fresh agent per work package | pending |
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
