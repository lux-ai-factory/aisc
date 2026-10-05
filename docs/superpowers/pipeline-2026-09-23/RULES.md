# Rules for every stage (read this first)

## Goal (the user's words)
Pipeline: "qualification -> agentic system to make a machine readable card -> agentic system to suggest
control objectives based on card -> select and install test plugins and controls locally (controls
installed with one click from the catalogue like the tests) -> execute tests and answer controls ->
visualise and comment."
Current goal: "get to the point where everything up to step 6 is done coherently, i.e. that the
information is written and consumed on a dataset and everything is installed seamlessly."
Out of scope for now: the final report (it will read everything from qualification to plots and comments; discussed later).

## Decided model (user, 2026-09-23)
- One AI system per project, NOT versioned; its components NOT versioned.
- Only the AI card (the system's description) is versioned. "System version" = card version.
  Old versions read-only.
- Every assessment records the system version that was the latest when it happened: a test when the
  evaluation starts, a control when answered; a control-objectives assessment belongs to exactly one
  version. This never blocks edits; live screens show the latest version.
- Card components link to the engine's real components via AIRO (hasModel, hasTrainingData,
  hasTestingData, hasComponent). Drift is shown, not auto-fixed.

## FROZEN: must not change
1. **The engine data model, all of it** (apps/backend Django models and tables): Project, AISystem,
   AIComponent, EvaluationInput, Plugin, PluginConfig, ProjectConfig, PluginConfigProjectConfig,
   Evaluation, EvaluationPlugin, Artifact, Observation, Measurement, Metric/Direct/Derived,
   MetricCategory. The reference is the state at the merge of Sean's work, backend commit `e34fca3`.
   The ONLY allowed engine migration is a new one that undoes our migration `0022`
   (`0022_parts_belong_to_a_version_of_the_one_system`, plus the SystemVersionParts model and the
   related code), restoring exactly the `e34fca3` schema. Table names and placement stay as they are
   now (unprefixed, and the current schema); do not rename or move them.
2. **Sean's code from today** in apps/backend, apps/webapp, apps/eval, shared/plugin-interface
   (author seanblevins, commits of 2026-09-23). Other engine code may change only where needed and
   without touching the schema.
3. **AIRO**: the vendored AIRO/VAIR ontology files, and qualification's `knowledge_graph` and
   `QualificationRisk` tables.
Anything else (platform core, the rest of qualification, controls, control-objectives, catalogue, the
dashboard's own tables) MAY be changed to harmonise the modules. Links to frozen rows are added on the
non-frozen side (e.g. a table outside the engine that references engine.evaluation).

## Safety
- Branch `feat/unified-modules` in every repo. Local commits are allowed; NEVER push.
- NEVER run `docker compose` up/down/build/restart against the running stack (compose project `aisc`),
  and never migrate, write to or drop anything in its live databases. Reading the live DB is OK.
- Tests use throwaway databases only (e.g. `docker run --rm -d -p <free port>:5432 postgres:16` under a
  unique container name, removed afterwards). Platform tests default to the LIVE DB, so always set
  `PLATFORM_TEST_DATABASE_URL` (and each module's equivalent) to the throwaway one.
- Do not edit shared/plugin-manager.
- TDD: tests before implementation.
- Prose in docs: no em dashes.
