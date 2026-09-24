# Progress

| stage | output | status |
|---|---|---|
| 1 specs | 01-specs.md | done |
| 2 tests | 02-tests.md + test files | pending |
| 3 plan | 03-coding-plan.md | pending |
| 4 code | commits | pending |
| 5 verify until green | 05-report.md | pending |

## Stage 1 notes (specs)

- Wrote 01-specs.md: sections 0 (findings), 1 data model (project-template 0005_llm.sql, schema `llm`,
  tables `provider` and `system_choice`), 2 platform API (admin-only routes under /projects/{slug}/llm,
  live model listers per provider, internal resolve route with X-AISC-Service-Token), 3 shared
  `baf_llm.py` (identical copy in A and B plus parity test), 4 page `homepage/llm.html`, 5 security,
  6 compose/env/Caddy wiring (not applied), 7 decisions D1-D11 and risks R1-R5, 8 test map.
- Key decisions: system ids card_agent / risk_mapper; base URL on the provider row; fail closed once a
  project is known; models route answers 200 with `error`; model need not be in the live list; A gets the
  pid as `?project=` from qualification-web (small TS change in FillerClient and createFromForm).
- Open for later stages: stage 4 edits homepage/project.html on top of the user's uncommitted edit and must
  not commit it; scripts/secrets.sh must only be tested on a scratch copy (it rewrites env.runtime).
- No product code or tests written. Nothing run against the live stack.
