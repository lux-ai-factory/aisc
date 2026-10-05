# AISC databases: from consistent to very good

Date: 2026-09-24. Source: the read-only audit of every AISC database on this date (terminology,
duplicates, missing links, leftovers). This file lists what is left after the first round, so it
can be picked up later.

## Done or in progress in the first round

- `scripts/verify-db-consistency.sh`: read-only checks for orphan project databases, unknown
  databases and schemas, system identity drift, unresolved references, unknown Keycloak subjects,
  stale step-2 graphs, project databases behind on migrations, and naming/type lint.
- Database rules as migrations (not yet applied to the live database): the `(system_id,
  project_id)` foreign key to `core.system` in qualification, control_objectives and
  report_composer; the foreign keys on `report_composer.generated_report`; foreign keys on
  Superset's `aisc_comment` and `aisc_review_request`.
- Renames inside single modules: `control_objectives.project` becomes `assessment`;
  `qualification_answer."toolId"` becomes `section_id`; snake_case columns in qualification via
  Prisma `@map`.

## Needs an explicit decision before it is done

- **Drop the leftovers**, after a `pg_dump` of each: the three orphan project databases
  (`project_2037…`, `project_a4c8…`, `project_d784…`) and the four standalone databases (`aisc`,
  `controls`, `qualification`, `control_objectives`).
- **Apply the new migrations to the live database.**

## Left for "very good"

1. **Unfreeze the engine** (`engine.*`), starting with:
   - `UNIQUE(pid)` on every engine table, then a real foreign key from
     `qualification.card_component.component_pid` to `engine.ai_component.pid`;
   - one meaning per name: `project_id` (core uuid vs engine bigint), `system_id` (engine
     `ai_system` vs card version), `pid`;
   - the engine reads the project's name and description from `core` instead of copying them;
   - a check that an evaluation's card version belongs to the evaluation's project;
   - cosmetic: `aisc_backend_*` constraint and sequence names, stale Django content types, the
     schema comment.
2. **The catalogue** (left alone on purpose in the first round):
   - `UNIQUE(slug)` in the new (dev) catalogue;
   - record which catalogue release a project installed (`checklist` gets the release and
     `installed_at`), and keep the catalogue's source slug as it is (`source-aesia`, not `aesia`);
   - resolve `engine.plugin.catalogue_slug` against the catalogue (StrongREJECT has none);
   - retire the old `platform.catalogue` schema, the `catalogue_rw` role and its compose services.
3. **`core.system` as the only source** of the system's name, version and provider: qualification
   stops keeping `systemName`, `systemVersion` and `company` of its own, and
   `control_objectives.assessment.name` is derived instead of stored.
4. **Who did what**: record the answering person in controls (`submission_answer.answered_by`),
   fill `core.system.created_by`, use the Keycloak subject in every user column (the old catalogue
   stores usernames; `superset.aisc_review_request.resolved_by` lacks the `_sub` suffix), and keep
   a change history for the records an auditor relies on.
5. **One vocabulary**: "card version" for `core.system` rows everywhere (`system_version_pid` and
   `version_pid` become `system_id`), `core.system.version` becomes `vendor_version`, and a short
   glossary in the repo for project / assessment / system / card version / checklist / control.
6. **References across databases** cannot be foreign keys (each project has its own database, and
   `core` lives in `platform`). The nightly consistency run is the safeguard; consider an outbox
   or events so that deleting a project or a card version tells every module.
7. **Staleness of the copies kept on purpose**: store the source `knowledge_graph.digest` on
   `control_objectives.graph`, and the catalogue release on each installed checklist, so a stale
   copy is detected rather than guessed.
8. **A second, read-only audit** of what the first did not look at:
   - roles and grants (who can read or write which schema and database);
   - indexes and query performance on the tables the dashboard and the report read;
   - backups: that every database is backed up, and that a restore works end to end;
   - data quality inside values (free text that should be a controlled vocabulary, such as risk
     sources and impact areas, which qualification and control_objectives spell differently).
9. **Timestamps**: `timestamptz` everywhere (Superset's `aisc_*` tables and the standalone copies
   use `timestamp without time zone`).
