# Progress

| stage | output | status |
|---|---|---|
| 1 survey + specs | 01-specs.md | done 2026-09-25 |
| 2 tests | 02-tests.md + tests | pending |
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
