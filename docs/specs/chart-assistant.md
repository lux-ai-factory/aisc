# Chart assistant: specification

Status: draft for the owner's review. Nothing is built. Written 2026-11-06 against `~/aisc`, branch `hardening`,
uncommitted working tree.

## 1. What it is for

A person asks for a chart in words, for example "radar of the baseline rate by category, OpenAI only, legend below".
The assistant:

1. knows the project's **data model** (tables, columns, what they mean, which values they take), never the data;
2. builds the chart as a real Superset chart on a **mock database** of invented rows with the same structure;
3. shows it, marked MOCK DATA, with its query and a plain description of what it computes;
4. edits it when asked ("bar instead", "add Local", "only English");
5. once the person **validates**, the same query, unchanged and fingerprinted, is pointed at the real project data;
   Superset computes the real values.

Validated charts are ordinary Superset charts: filters, comments and Save to report work on them as on any other.

## 2. Rules (each is a requirement the build must test)

| # | Rule |
|---|---|
| R1 | The model never receives a value read from a project's real data: no row, no sample, no count. The one exception (owner's decision, 2026-11-06): per metric, the minimum and maximum of the score and of each numeric label in the first finished run, which the mock draws its values within. It receives the data model description (section 4) and, when it asks, results computed on the **mock** database only. |
| R2 | The model never writes a number shown in a chart. It writes a query and chart settings; Superset computes the values. |
| R3 | The query run on real data is byte for byte the query the person validated: its SHA-256 is recorded at validation and checked before the switch. Any change after validation needs a new validation. |
| R4 | Every query is read only, twice over: it must be a single `SELECT`/`WITH` (checked before running), and it runs as a role that can only read (section 6). |
| R5 | A query reaches only the reader tables of its own project. No other schema, no other project's database. |
| R6 | Validating is a person's act, recorded in the ledger with who, when, the query fingerprint and the chart. |
| R7 | Each request names its project; the assistant refuses one whose caller is not a member of it. |

## 3. What exists today that it builds on (inspected)

| Need | Already there | Where |
|---|---|---|
| A read-only role on each project database | `dashboard_ro`, Superset's connection to `project_<hex>` | `apps/results-dashboard/aisc_ext/projects.py:281` |
| The tables a reader may see | one exhaustive reader list (project, target, controls, qualification, control_objectives, 15 engine tables); `trace.*` and secrets are not on it | `scripts/report-grants.sh:48` |
| Results with their labels | `engine.aisc_backend_measurement.dimensions` (JSON); 23 distinct keys on the Mijke project today | live DB |
| Per-conversation results of LangBiTe (Mijke) | metric `Conversation`, dimensions written by `_dimensions` | `~/mijke-langbite/aisc_plugin_langbite_mijke/conversation_records.py:23` |
| A worked example of the target output | the "Mijke conversations compared" dashboard: criterion as SQL datasets, radars, filters | `apps/chart-assistant/tests/fixtures/bias-plots/` (base.sql, vs_baseline.sql, widest_pair.sql) |
| Per-project model choice and key | providers and agent choices in the project database; agents listed in `SYSTEMS` | `platform/platform_service/llm_store.py:33` |
| How an agent gets its model and key | internal route, one service token per agent, backend network only | `platform/platform_service/routes/llm.py:242-246` |
| Creating charts and datasets in Superset | the overlay's importer (export bundle, Superset's own import) | `apps/results-dashboard/aisc_ext/projects.py:622,771` |
| Code on every Superset page | the hook template plus our script (Save to report, screen styling) | `apps/results-dashboard/templates_override/tail_js_custom_extra.html`, `branding/save-to-report/save-to-report.js` |
| A dashboard API with CSRF, per-dashboard access and a ledger event | `ReportExportApi`, granted to the comment roles | `aisc_ext/report_exports/api.py`, `superset_config.py:175,185` |
| Dashboard ledger actions | listed, then declared in the platform registry | `aisc_ext/ledger.py:118`, `platform/platform_service/ledger/registry.py:507` |

What does **not** exist: a description of the data model, a mock database, an assistant service, templated SQL in
Superset (off), and an agent entry for charts in `SYSTEMS`.

## 4. The data model description

A file per project kind, kept in the repository (`data-model/reader-model.yaml`), plus a per-project part generated
from the database.

**Fixed part (written by hand, reviewed):** each reader table and column with its meaning, type and joins. Example:

```yaml
engine.aisc_backend_measurement:
  meaning: one result of one test run
  columns:
    score: {type: float, meaning: the result's value; its metric says what it measures}
    dimensions: {type: json, meaning: labels of the result; keys depend on the metric (see metrics)}
  joins: [observation_id -> engine.aisc_backend_observation.id, metric_id -> engine.aisc_backend_metric.id]
```

**Generated part, per project** (computed on the dashboard side, which already has read access; the service has none): which metrics exist, the first finished run's minimum and maximum per score and numeric label, and for each the dimension keys it uses,
each key's type, and its values when the key is categorical (at most 50 distinct values). For LangBiTe (Mijke):
`Conversation` with category, community, register, language, outcome, organisations...

**Checks:** a test compares the fixed part with the database catalog (every reader table and column described, no
description of a column that is gone). The generated part is made by the assistant service with the read-only role,
and goes to the model only after the label decision (D2).

## 5. The mock database

- One database `assistant_mock` (not per project), schemas and tables made from the same migrations as a project
  database, so the structure is the real one.
- **Rows are invented** per request from the description: for each metric, rows over the cross product of its
  categorical dimension values (or neutral stand-ins, D2), with numbers drawn (triangular, peaked in the middle; whole
  numbers stay whole) between the minimum and maximum of the metric's first finished run.
- **Edge cases are put in on purpose:** empty organisations, a missing baseline, a duplicated row, a null score, a
  category with one row. A query that only works on clean data shows it on mock first.
- Superset gets a connection to it, read only, named "Mock data". Charts on it carry "MOCK DATA" in their title.
- The mock is regenerated when the description changes; it holds nothing real, so it needs no access control beyond
  being read only.

## 6. The assistant service

A small FastAPI service `chart-assistant` on the backend network (no port to the host), like the other sidecars.

**Endpoints** (called by the panel through the dashboard, section 7):

| Route | Does |
|---|---|
| `POST /v1/projects/{pid}/conversations` | starts a conversation; returns its id |
| `POST /v1/conversations/{id}/messages` | the person's request; returns a proposal: SQL, chart settings, plain description, the mock result (rows, at most 200) |
| `POST /v1/conversations/{id}/validate` | the person accepts proposal N; returns the query fingerprint |

**What the model may do** (its tools, all run by the service, never by the model directly):

| Tool | Runs on |
|---|---|
| `describe()` | the description (section 4) |
| `run_on_mock(sql)` | the mock database, after the read-only check, 5 s timeout, 200 rows |
| `propose_chart(sql, chart)` | nothing: returns the proposal to the person |

There is no tool that touches real data. That is R1, enforced by construction, and tested by asserting that the
service holds no credential for a project database.

**The query check (R4, R5):** parsed with `sqlglot`; one statement; `SELECT` or `WITH ... SELECT` only; every table
on the reader list; no function outside an allow list (no `pg_read_file`, `dblink`, `lo_*`, `pg_sleep`...). The
role is the second barrier.

**Model and key:** a new agent `chart_assistant` in `llm_store.SYSTEMS`, chosen per project in Manage > Connectivity
like the card agent; resolved on the internal route with its own token `PLATFORM_CHART_ASSISTANT_TOKEN`.
Without a choice the panel says so and does nothing.

**Conversation state:** kept in the project database, a new schema `assistant` (conversation, message, proposal with
its SQL and fingerprint), written by a new role `assistant_rw`. Messages are kept as the audit of how a chart came
to be.

## 7. In Superset

- **The panel:** a "Chart assistant" button beside Save to report on dashboards of a project, from the same hook
  script. It opens a side panel: the conversation, each proposal drawn from its mock result (the chart, its SQL
  folded, its description), and three actions: Edit (keep talking), Validate, Discard.
- **Calls:** the panel calls a new dashboard API `aisc_assistant` (CSRF, per-dashboard access as
  `ReportExportApi`), which forwards to the service with the dashboard's own service token. The browser never talks
  to the service directly.
- **Validate:** the dashboard API asks the service for the validated SQL and checks its fingerprint (R3), then makes,
  with the overlay's importer, a dataset with that SQL on the **project's** connection and a chart with the proposed
  settings, adds it to the dashboard under "Assistant charts", owned by the person. The mock chart is deleted.
- **Ledger:** `dashboard.assistant.validated` (chart, dataset, query SHA-256, conversation id), declared in the
  registry, emitted in the same transaction as the chart, as comments do.

## 8. Changing a validated chart

Asking for a change after validation starts from the validated query, runs again on mock, and needs a new validation.
The new version replaces the chart in place; the ledger keeps both fingerprints. A chart changed by hand in Superset
after validation loses its "validated" mark (its dataset SQL fingerprint no longer matches; the panel shows it).

## 9. Security and privacy

- R1 to R7 above, each with a test.
- With a hosted model (OpenAI, Anthropic, Mistral) only the description reaches it: table and column names, meanings,
  and, depending on D2, label values.
- The service runs with no project database credential and no Superset credential; it reaches the mock database and
  the platform's resolve route only.
- Rate limit per project and per person; a token budget per conversation (D4).
- The model's text is shown as text (escaped), never as HTML.

## 10. Testing

- Unit: query check (allowed and refused statements, functions, schemas), description against the catalog, mock
  generation (edge cases present), fingerprint check.
- Service: a stand-in model returning fixed tool calls; assert no real data reaches the model's input.
- Dashboard: the API refuses without CSRF, without dashboard access, with a changed query.
- End to end on the temporary loopback Superset already used for Save to report: ask, see a mock chart, validate,
  see the same chart on real data with the same SQL.

## 11. Decisions for the owner

| # | Decision | Default proposed |
|---|---|---|
| D1 | Which model for the assistant | the project's choice in Manage > Connectivity; local model allowed but slower at SQL |
| D2 | Do label values (community names, categories) go to the model? | Yes for categorical labels the person can already see in filters; free text (prompts, answers) never |
| D3 | Who may validate | project editors and owners only; viewers may ask and see mock charts |
| D4 | Cost limits | 30 messages and 200k tokens per conversation |
| D5 | Where validated charts go | the dashboard where the panel was opened, section "Assistant charts" |
| D6 | Keep conversations | yes, in the project database, as the record of how a chart was made |

## 12. Out of scope

Writing to any database, charts outside Superset, answering questions in prose about the data ("which group is
worst?"), other chart libraries.

## 13. Size

| Part | Estimate |
|---|---|
| Description file, generator, catalog test | 2-3 days |
| Mock database and generator with edge cases | 2-3 days |
| Assistant service: tools, query check, model loop, state | 4-5 days |
| Dashboard API, panel, validate and import, ledger | 4-5 days |
| Hardening: rate limits, budgets, tests end to end | 3-4 days |

About 3 to 4 weeks for one person, test first. A first usable slice (description, mock, service, panel without
editing after validation) is about 2 weeks.
