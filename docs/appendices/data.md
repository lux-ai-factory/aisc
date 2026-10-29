# Appendix 8: Data

Back to [How AISC works](../architecture.md).

Where AISC keeps what, and who may read it.

## PostgreSQL

| Database | Schemas and what they hold | Written by |
|---|---|---|
| `platform` | `core`: projects, members, the platform's ledger outbox. `ledger`: the witness records, the index of every log, the pool of immudb databases, the verified state. The run passes. | `platform` |
| `project_<pid>` (one per project, the pid without its hyphens) | `project`: the AI card versions | `platform` |
| | `qualification`: answers, components, risks, the agent's draft, corrections, card links to the engine's components | `qualification-web` |
| | `control_objectives`: assessments, ratings, links to objectives, mapping runs, priority choices, objective sets and profiles, the objective selection | `control-objectives` |
| | `catalogue`: the catalogue choice, and the private copy with local dimensions | `platform` |
| | `controls`: installed checklists and their answers | `controls-web` |
| | `engine`: plugins, evaluations, measurements | `aisc-backend` |
| | `connection`, `target`, `helper`, `llm`: connections and run keys, assessment targets, helper models, the AI assistants' models and keys (secrets encrypted) | `platform` |
| | `evidence`: the Evidence map's links and reviews | `platform` |
| | `report_composer`: layouts, templates, generated reports | `report-composer` |
| | `ledger`: the project's outbox of ledger events | every application, through `ledger.emit` |
| `keycloak` | accounts, passwords, sessions | `keycloak` |
| `superset` | the dashboard's own data: dashboards, charts, comments, review requests | `dashboard` |
| `ledger_identity` | who is behind each person reference in the ledger | `platform` only |

Each application connects with its own role (`qualification_rw`, `control_objectives_rw`, `controls_rw`, `engine_rw`,
`report_composer_rw`, `platform_rw`) and may write only its own schema. Three roles only read: `report_ro` (the report
renderer and the platform's evidence pages), `dashboard_ro` (the dashboard), `inspector_ro` (pgAdmin and the
diagrams).

## Other stores

| Store | What it holds |
|---|---|
| MinIO | buckets `datasets` and `models` (uploads), `artifacts` (files tests write) |
| `devpi` | the plugin interface and the packages of installed tests |
| immudb | one database per project (the ledger), and the engine's audit log `auditdb` |
| RabbitMQ, Redis | test runs waiting and their task results (passing data, not records) |

## Lifetime

- **AI card versions** never change once a newer one exists: database triggers refuse it. Everything stamped with a
  version (answers, runs, links, reports) keeps meaning what it meant.
- **Deleting a project** (admins, typing its name) first delivers its pending ledger events, then drops its
  database. Its ledger in immudb stays.
- **Removing the install** (`uv run scripts/aisc.py remove`) deletes every volume, so every database and file.
- **The ledger** keeps its entries; erasing a person (see [Manage](manage.md#logs)) removes only the link between
  their reference and their identity.
