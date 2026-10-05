# Two-layer control objectives (brief, 2026-09-25)

## What the user asked
Give the control-objectives module the same two-layer mechanism as qualification's form work:
- a **granular** layer that owns the wording of objectives, versioned, where objectives are written or
  imported (working name: **objective set**);
- an **assembled** layer that only picks objectives from sets, each pinned to one set version, and can
  never create or reword an objective (working name: **objective profile**);
- an assessment (one per AI card version of a project) pins one profile version; versioning and
  persistence are essential: a saved version is never edited, and an assessment keeps exactly what it
  was assessed against.

The qualification equivalent (question set / questionnaire), as explained to the user and accepted:
question identity never changes; wording lives only on the set version's item rows (append-only);
a questionnaire item holds no text, it points at one question as worded in one set version (the pin);
"update available" when a newer set version rewords a pinned question, and accepting creates a new
questionnaire version; retired_at replaces deleting; created_by recorded; pinned only (no auto-follow);
export as references by default, self-contained bundle as an option; import always creates a set.
Docs of that work: /home/listuser/aisc-install/docs/superpowers/form-assembly-2026-09-24/ (the two-level
model itself is not yet specified there; follow the rules above).

## User decisions (binding)
- D1 **Existing control-objectives data is fake; losing it is fine.** No data-preserving migration: the old
  tables may be dropped and recreated, and the built-ins seeded fresh. (A pg_dump before a live drop stays
  good practice.)
- D2 **Library location:** the DEFAULT (built-in) sets and profiles are seeded and shared (platform
  database, read-only in the app, a new version ships with a release). EVERYTHING users create (custom
  sets, profiles) is isolated in its own project's database. Reuse across projects only by export/import.
  The same rule will apply to qualification's question sets and questionnaires.
- D3 Pinned only: a profile moves to a newer set version only when an editor accepts an update.

## Orchestrator defaults (the user may correct)
- A1 Names "objective set" and "objective profile": DEFAULT (user to confirm).
- A2 When an assessment starts on a profile version that uses built-in sets, the pinned built-in wording is
  copied into the project's database, so every link stays inside the project DB and the project DB is
  complete by itself. The spec may argue for a plain reference instead, with reasons.
- A3 Built on the per-project database layout of the isolation run in progress: /home/listuser/aisc-isolation
  (branch isolation/2026-09-25), docs in docs/superpowers/isolation-2026-09-25/ (01-specs, 02-tests,
  03-coding-plan). Implementation starts only after that run is merged into feat/unified-modules.

## Facts found (2026-09-25, read-only)
- The objectives are a packaged CSV: apps/control-objectives/src/aisc_control_objectives/data/
  ai_act_control_objectives.csv, 50 rows R1.1..R9.x, columns ID, Macro_Requirement, Legal_Basis,
  Sub_Requirement_Label, Control_Objective, Assessment_Mode, Target, Standards_Grounding,
  Grounding_Tier_Flag, Notes; validated by models/control_objective.py; loaded by control_objectives.py
  (ControlObjectiveCatalogue, digest = sha256 of the bytes).
- Tables (db/tables.py, schema control_objectives): project (the assessment; objectives_digest), graph,
  risk (assessor severity), mapped_objective (objective_id bare text "R1.1", no FK), mapping_run.
  Scores and tiers are computed, never stored.
- Live: 1 assessment, 5 risks, 0 mapped objectives (all fake, D1).
- Consumers: aisc-report-generator report_renderer/data/control_objectives.py queries these tables and
  reads objective wording; the report composer's coverage map stores bare objective ids ("R1.1");
  risk_mapping.py gives the catalogue to the LLM that maps risks to objectives.
