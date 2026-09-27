# One system, a versioned description, and assessments that say which version

**Status:** draft for review (2026-09-23). Replaces the "versioned system" model
built earlier the same day (see *What today's build gives up*).
**Fits:** `docs/superpowers/plans/2026-09-23-project-databases-roadmap.md`. Every
table below lives in the project's own database (`project_<pid>`); nothing here
is shared between projects.

## The model, in the user's words

> a project has one system as per Sean's changes → the AI card is the
> description of a system and there can be multiple versions of it → control
> objectives are tied to the description of the system → tests and controls are
> tied to the system itself (only one)

> we need to tie each assessment to the system version (for the auditor)

## Terms

| Term | Is | Versioned? |
|---|---|---|
| **System** | The project's one AI system (Sean's AISystem). | No. One row, edited in place. |
| **Component** | A part of the system: dataset, model, LLM, datashape, resource (Sean's AIComponent). | No. One row each, edited in place. Uploads already get a new object name, so no file is ever overwritten. |
| **System version** | A version of the system's *description*: one saved AI card. v1, v2, v3... | Yes: this is the only versioned thing. |
| **Assessment** | Anything done to or about the system: a test (engine evaluation), a control (controls submission), a control-objectives assessment. | It records the system version it was made under. |

## Rules

1. **One system per project.** Held by the database: `project.system` has one row.
2. **Saving the AI card makes the next system version.** Always, even with no
   change to the system's parts: the card is what is versioned. Older versions
   are read-only (a trigger refuses updates, as `core.ai_system_version` does today).
3. **Nothing freezes and nothing is copied.** Editing the system or a
   component never makes a version and is never refused because of one.
4. **Every assessment records the latest system version at the moment it
   happens.** A test when it starts, a control when it is answered. This is a
   stamp, set automatically, informational: it never blocks anything, and live
   screens always show the latest version. It answers the auditor's question:
   *under which documented description was this done?*
5. **A control-objectives assessment belongs to exactly one system version.**
   It maps that version's risks. A new version starts a new assessment; the old
   one is history. (Whether ratings carry forward: open question 3.)
6. **The card's components point at the real components.** Each component on
   the card links to the engine part it describes, with AIRO's own properties:
   `airo:hasModel` for a model, `airo:hasTrainingData` / `hasTestingData` /
   `hasValidationData` for datasets, `airo:hasComponent` otherwise. This
   replaces today's free-text labels extracted from Annex IV 2(c).
7. **Drift is shown, not fixed silently.** When the system's components no
   longer match the latest card (a part added, removed, re-uploaded), the
   qualification app says the description is out of date and offers to start
   the next version with the change. The card is a person's statement; the
   person confirms it.

## Data, per module (all in the project database)

```
project.system            (1 row)       pid, name, provider, created_at
project.system_version    (n rows)      pid, number, created_at, created_by,
                                        card_id -> qualification.qualification
                                        UNIQUE(number); frozen by trigger

engine.ai_component                     + no version columns (as in Sean's)
engine.evaluation                       + system_version_id -> project.system_version  (stamp)

controls.submission                     + system_version_id -> project.system_version  (stamp)

control_objectives.assessment           + system_version_id -> project.system_version  (one per version)

qualification.qualification (the card)  1:1 with project.system_version
qualification.card_component            card_id, engine component pid, AIRO property
```

Foreign keys are real: one database per project, so every schema can point at
`project.system_version`. Each module role gets `SELECT, REFERENCES` on schema
`project`; only qualification writes `project.system_version` (it makes a
version when a card is saved), and the platform no longer writes any of it.

## What today's build gives up

Built and deployed on 2026-09-23 (feat/unified-modules), to be undone:

- Versions of the *system*: `core.ai_system_version` with freeze-on-use and
  drafts, the engine's copy-on-write of components into new versions
  (`lineage`, `system_version_id` on parts, `system_version_parts`), and
  evaluations freezing a version. Evaluations keep a version link, as a stamp.
- `core.ai_system` / `core.ai_system_version` in the shared `platform` database:
  they move into the project database (roadmap plan 2), and the platform stops
  writing them.

Kept: one system per project; one card per version; the qualification screens
("AI system", "Edit the AI system", "Versions"); saving the card makes the next
version; the membership checks on Sean's routes; the unprefixed table names.

The live database holds nothing that depends on the dropped parts yet: MCAS has
one version, 0 components, 0 evaluations.

## Fit with the project-databases plans

Plans 2 (qualification), 3 (control objectives) and 4 (engine) are written
against the old model and need these changes before they run:

- **Plan 2:** `project.system` is one row, plus `project.system_version`;
  qualification writes versions when a card is saved. Drop "a project may name
  several systems".
- **Plan 3:** no upload. An assessment is created for the latest system version
  and reads that version's card and risks from the same database. The
  `assessment` table gets `system_version_id`; its `system_name` and
  `qualification_id` copies go.
- **Plan 4:** `engine.evaluation.system_version_id` is a stamp. No versioning of
  parts.

## Open questions

1. **Order of work.** Rework today's build in the shared database first (seen
   sooner, redone by plans 2-4), or fold it into plans 2-4 directly (built
   once)?
2. **Controls.** Does a control get its stamp when it is answered, when the
   checklist is submitted, or both?
3. **Carry-forward.** When version N+1 starts a new control-objectives
   assessment, are version N's severity ratings and objective mappings copied
   for risks that did not change (saves model calls), or does it start empty?
4. **Drift.** Is a re-uploaded file (same component, new data) a change that
   makes the description out of date, or only an added or removed component?
