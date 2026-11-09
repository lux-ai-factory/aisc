# Appendix 8: Data

Back to [How AISC works](../architecture.md).

Where AISC keeps what, and who may read it.

## PostgreSQL

| Database | Schemas and what they hold | Written by |
|---|---|---|
| `platform` | `core`: projects, members, the platform's ledger outbox. `ledger`: the witness records, the index of every log, the frozen content of each entry (`ledger.content`; the log keeps only its digest), the page views (`ledger.page_view`, never in immudb), the pool of immudb databases, the verified state. The run passes. | `platform` |
| `project_<pid>` (one per project, the pid without its hyphens) | `project`: the AI card versions | `platform` |
| | `qualification`: answers, components, risks, the agent's draft, corrections, card links to the engine's components, the forms (question sets and questionnaires), the card's knowledge graph and history | `qualification-web` |
| | `control_objectives`: assessments, ratings, links to objectives, mapping runs, priority choices, objective sets and profiles, the objective selection | `control-objectives` |
| | `catalogue`: the catalogue choice, and the private copy with local dimensions | `platform` |
| | `controls`: installed checklists and their answers | `controls-web` |
| | `engine`: plugins, evaluations, measurements | `aisc-backend` |
| | `connection`, `target`, `helper`, `llm`: connections and run keys, assessment targets, helper models, the AI assistants' models and keys (secrets encrypted) | `platform` |
| | `evidence`: the Evidence map's links and reviews | `platform` |
| | `trace`: every call a test made to the system under test, append-only and chained per run; the platform stops a run whose calls keep failing from it (`run_stop.py`) | `platform` |
| | `report_composer`: layouts, templates, generated reports | `report-composer` |
| | `ledger`: the project's outbox of ledger events | every application but the engine, through `ledger.emit`; the engine keeps its own outbox (`engine.aisc_backend_ledgeroutbox`), which `aisc-backend-ledger` sends to the platform |
| `keycloak` | accounts, passwords, sessions | `keycloak` |
| `superset` | the dashboard's own data: dashboards, charts, comments, review requests | `dashboard` |
| `ledger_identity` | who is behind each person reference in the ledger | `platform` only |
| `assistant_mock_<pid>_<digest>` (one per project and description of its data, the pid without its hyphens) | invented rows only, made from the description so the chart assistant can try a chart before a person validates it; a new description makes a new one and the project's older ones are dropped. Owned by the role `assistant_mock`, which may create databases and connects to no project database and not to `platform` | `chart-assistant` |

Each application connects with its own role (`qualification_rw`, `control_objectives_rw`, `controls_rw`, `engine_rw`,
`report_composer_rw`, `platform_rw`) and may write only its own schema. Three roles only read: `report_ro` (the report
renderer and the platform's evidence pages), `dashboard_ro` (the dashboard), `inspector_ro` (pgAdmin and the
diagrams).

## Other stores

| Store | What it holds |
|---|---|
| MinIO | buckets `datasets` and `models` (uploads), `artifacts` (files tests write), and one `proof-<pid>` per project, written only by the platform: the proof files attached to checklist answers, never replaced or deleted while the project exists |
| `devpi` | the plugin interface and the packages of installed tests |
| immudb | one database per project (the ledger, taken from a pool of spare `ledger<hex>` databases), the platform's own log `ledgerplatform`, and the engine's audit log `auditdb` |
| RabbitMQ, Redis | test runs waiting and their task results (passing data, not records) |

## Lifetime

- **AI card versions** never change once a newer one exists: database triggers refuse it. Everything stamped with a
  version (answers, runs, links, reports) keeps meaning what it meant.
- **Deleting a project** (admins, typing its name) first delivers its pending ledger events, then drops its
  database and removes its proof-file bucket (`proof-<pid>`) with its files. Its ledger in immudb stays.
- **Removing the install** (`uv run scripts/aisc.py remove`) deletes every volume, so every database and file.
- **The ledger** keeps its entries; erasing a person (see [Manage](manage.md#logs)) removes only the link between
  their reference and their identity.
