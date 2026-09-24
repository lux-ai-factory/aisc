# Rules for every stage of the report run (read this first; binding)

## What the user asked (confirmed with the user, 2026-09-23)
Make the AISC report generator **versatile** and **modular**:
- **Versatile:** a report can include all data the pipeline produces, from qualification to the dashboard
  plots and their comments. Each kind of data is a **macro block**:

| block | shows | source (read-only) |
|---|---|---|
| Cover | project, system, card (system) version, date | platform: core.project, core.system |
| AI card | the system's description at that version, its components | qualification: the AIRO card (knowledge_graph, JSON-LD per version) |
| Risk classification | AI Act role, risk class, AIRO risk chains | qualification: QualificationRisk |
| Control objectives | objectives chosen for this version and their status | control-objectives: the assessment of that version |
| Test results | one per test plugin: what ran, on which component, measures | engine: evaluation, observation, measurement (plugin-specific renderers, as today's report plugins) |
| Control answers | each checklist's answers and scores | controls: the project's own database |
| Dashboard plots + comments | a dashboard chart with its review comments | dashboard: Superset chart rendering + the review/comment tables |
| Summary / coverage | objective -> which tests/controls cover it -> result | computed from the blocks above |
| Free text | an editor's own paragraph | stored with the report layout |

- **Modular:** a NEW service, the **report composer**, where a user assembles a report for a project:
  picks blocks, orders them (move up/down or drag), sets per-block options (which evaluation, which chart,
  show comments or not), saves it as a **report layout** (reusable as a template for other projects),
  previews it as HTML, and generates the PDF.
- The existing `aisc-report-generator` becomes the **renderer**: it takes a saved layout and renders the
  blocks in that order. Its plugin idea generalises from "one plugin per test tool" to "one renderer per
  block type"; test tools keep their own plugins inside the Test results block.
- Out of scope: the Catalogue module (the report does not use it).

## Decided model (binding)
- One AI system per project, not versioned; only the AI card is versioned ("system version" = card version,
  platform core.system rows with a `number`). Tests (engine evaluation.system_id), control answers and
  control-objectives assessments are stamped with the system version that was latest when they happened.
- **A report is of ONE system version.** Every block reads the data stamped with that version. If newer
  results exist, the report says so; it never mixes versions silently.
- Composer: a new app in aisc-install at `apps/report-composer` (a plain folder, NOT a git submodule),
  behind the same sign-in (Caddy + oauth2-proxy + Keycloak), editor/viewer rights from the platform's
  project roles, step 7 on the launcher. Layouts stored in the `platform` database in the composer's own
  schema. **Logic in Python** (the user reads Python, not JS/TS); the frontend stays thin.
- Plot images come from Superset's own rendering of each chart at generation time (mockable in tests).

## Repos and branches (local commits only, NEVER push, no new GitHub repos)
- /home/listuser/aisc-install, branch feat/unified-modules (the stack; the composer lives in apps/report-composer)
- /home/listuser/aisc-report-generator, branch dev
- /home/listuser/aisc-report-plugin-interface, branch dev
- /home/listuser/aisc-report-mlareject, branch dev
Other people's uncommitted files (apps/qualification prefill, apps/results-dashboard review page,
docker-compose.development.yml prefill hunks, scripts/verify.sh) stay unstaged; commit only your own
files and hunks (use `git apply --cached` with a filtered patch for shared files).

## FROZEN (read, never change)
1. The engine data model (apps/backend Django models and tables, as at backend commit e34fca3 plus 0023),
   and Sean's files of 2026-09-23 in apps/backend, apps/webapp, apps/eval, shared/plugin-interface.
2. AIRO: the vendored AIRO/VAIR files, qualification's knowledge_graph and QualificationRisk tables.
`/home/listuser/aisc-install/scripts/guard-frozen.sh` must pass at the end.

## Safety
- The running stack (compose project `aisc`) is the user's live demo: NEVER docker compose up/down/build/
  restart/run against it, NEVER write to its databases (the live postgres container is `postgres` on
  127.0.0.1:5432). Reading the live DB to learn the real schema is OK.
- Tests use throwaway postgres:14-alpine containers named `aisc-t-*` on free ports, removed afterwards
  (helper: aisc-install/scripts/lib/throwaway-pg.sh). Check every DB URL env var before running tests.
  The controls integration tests create and drop databases on whatever server they point at.
- Building a NEW image for the composer or generator for a smoke test is fine, if you tag it `*:report-test`
  and remove it afterwards; never rebuild the stack's own images.
- TDD: tests before implementation. Do not weaken or delete tests to get green.
- Docs: no em dashes.
