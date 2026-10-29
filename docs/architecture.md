# How AISC works

This document explains what AISC is for, the four steps of an assessment and how the software behind them fits
together. The [README](../README.md) says how to install it, and the [guide](guide.md) is the operator's reference
(settings, ports, tests).

The appendices give the details. One per step, plus Manage:

- [Appendix 1: Qualify the AI system](appendices/1-qualify.md)
- [Appendix 2: Set control objectives](appendices/2-control-objectives.md)
- [Appendix 3: Choose tests and checklists](appendices/3-tests-and-checklists.md)
- [Appendix 4: Collect evidence](appendices/4-collect-evidence.md)
- [Appendix 5: Manage](appendices/manage.md), the project's settings that the steps rely on

And four for developers and operators:

- [Appendix 6: Services](appendices/services.md), every service the stack runs
- [Appendix 7: Flows](appendices/flows.md), how a request travels for each thing people do
- [Appendix 8: Data](appendices/data.md), where everything is kept and who may read it
- [Appendix 9: Security](appendices/security.md), roles, secrets, the network and its limits

## The idea in one paragraph

A project in AISC is the assessment of one AI system. The team first writes down what the system is and what can go
wrong with it (step 1), then decides which control objectives it must meet (step 2), then picks the tests and
checklists that will show whether it does (step 3), and finally runs them, links each objective to its evidence and
reports on it (step 4). Each step reads what the previous one produced, so the report can say, for one version of the
system: these are its risks, these the objectives they call for, this is the evidence for each objective, and this is
what the evidence shows.

## The four steps and their purpose

| Step | Question it answers | What you do | What it produces | Who uses that next |
|---|---|---|---|---|
| **1. Qualify the AI system** | What is this system, what is it made of, and what can go wrong with it? | Answer the questionnaire (by default the Annex IV points 1 and 2), list the components, describe the risks; optionally prefill from a document and let an AI assistant suggest additions | The **AI card**, versioned (v1, v2, ...): the system, its components and its risk chains | Step 2 reads its risks; step 4 assesses the system or one of its components; the report shows it |
| **2. Set control objectives** | Which control objectives must this system meet, and which matter most? | Rate each risk (impact x likelihood), link risks to objectives (by hand or with an AI assistant), choose the priority objectives | The **risk and control matrix**: rated risks, the objectives each one calls for, a priority score per objective, the priority objectives | Step 3 filters the catalogue by the objectives' dimensions; step 4 and the report use the selected objectives |
| **3. Choose tests and checklists** | Which tests and checklists will produce the evidence? | Choose the project's catalogue once (public or private), filter it, install tests and checklists | Tests installed in the engine, checklists installed in the controls app | Step 4 runs and answers them |
| **4. Collect evidence** | What do the tests and the answers show, which objective do they prove, and how is it reported? | Answer the checklists, run the tests, look at the results, link each objective to its evidence on the Evidence map, compose and download the report | Checklist answers, test runs and their results, the Evidence map (reviewed by a second person), reports (PDF or Word) | The people who read the report |

**Step 1 does not decide the system's AI Act risk class.** Annex III classification is a legal judgement, which AISC
leaves to people: the questionnaire lets you tag the Annex III areas that apply, and whoever composes the report
states the class in its Risk classification block ("Not determined" by default).

**The AI card version ties the steps together.** Every save in step 1 makes a new version of the card; earlier
versions stay readable and can no longer change. Step 2 makes one assessment per version. In step 4 every checklist
answer and every test run is stamped with the version that was latest when it was made; the Evidence map and the
reports are per version. So everything in a report is about one version of the system.

## Architecture

```mermaid
flowchart TB
    B[Browser] -->|sign in| KC["keycloak (127.0.0.1:8081)"]
    B --> GW["caddy, asking oauth2-proxy"]
    GW -->|":8100"| L["launcher pages: projects, the four steps,<br/>Collect evidence, Evidence map, Results, Manage<br/>+ catalogue-private at /project-catalogue/"]
    GW -->|":80"| APPS["qualification-web, control-objectives,<br/>controls-web, report-composer,<br/>engine: aisc-webapp + aisc-backend"]
    GW -->|":8188"| DASH["dashboard (Superset)"]
    L -->|"/api/*"| P["platform"]
    APPS --> P
    APPS --> BE["aisc-backend"]
    P --> PUB["plugin-publisher"] --> IDX[("devpi")]
    P --> BE
    BE -->|queue| W["aisc-eval-worker"]
    W --> BE
    W --> IDX
    W -->|"run pass; the test calls the platform's doors"| P
    P -->|"forwards to the connection"| SYS(("the AI system<br/>being assessed"))
    BE --> M[("minio")]
    P & APPS & BE & DASH --> DB[("postgres")]
    P & BE --> IM[("immudb")]
```

AISC is a set of web applications run together with Docker Compose, in four layers.

### 1. Gateway and sign-in

`caddy` is the way in. The launcher is on port 8100, the step applications and the engine on 80, the dashboard on 8188
(defaults: `start` moves a port that is taken). Before passing a request on, Caddy asks `oauth2-proxy` whether the
caller is signed in and sends anyone who is not to `keycloak`, which the browser reaches on `127.0.0.1:8081`. One
sign-in covers every port. Each service then checks the caller again itself, so the gateway is not the only guard.

### 2. The step applications

Each step is its own application, most of them in a submodule of this repository, each keeping its records in its own
schema of the project's database:

| Step | Application (compose service) | Code |
|---|---|---|
| Launcher | pages served by `caddy` | `homepage/` |
| 1 | `qualification-web`, with `qualification-prefill`, `qualification-agents`, `qualification-ontology`, `qualification-pdf` | `apps/qualification` |
| 2 | `control-objectives` | `apps/control-objectives` |
| 3 | `catalogue-private` (the catalogue's pages; the data comes from the platform) | `apps/catalogue` |
| 4, checklists | `controls-web`, with `controls-pdf` | `apps/controls` |
| 4, tests | the engine: `aisc-webapp` (pages), `aisc-backend` (API), `aisc-eval-worker` (runs) | `apps/webapp`, `apps/backend`, `apps/eval` |
| 4, results | the launcher's Results page and `dashboard` (Superset) | `homepage/`, `apps/results-dashboard`, `dashboard-gateway/` |
| 4, Evidence map | a launcher page, served by the platform's API | `homepage/`, `platform/` |
| 4, report | `report-composer` (layouts) and `report-renderer` (PDF and Word) | `apps/report-composer`, `apps/report-generator` |

An application reads what it needs of the other steps through the platform (for what the platform owns), from another
application's API with the caller's own token (control objectives reads the AI card from qualification;
qualification lists the engine's components), or from the project's database with a read-only role (the report
renderer and the dashboard).

### 3. The platform

`platform` (FastAPI, in `platform/`) holds what all steps share:

- **projects and roles**: each project's members are owners, editors or viewers; the realm role `admin` counts as
  owner of every project and holds a few powers of its own (deleting a project, installing a test);
- **one database per project**, created with the project;
- **the AI card versions**;
- **the project's catalogue** and the installs it starts;
- **connections** to the AI system being assessed, and the **helper models** tests use as tools;
- the **AI assistants'** models and keys for steps 1 and 2;
- **the Evidence map**, the data of the Collect evidence and Results pages, and the dashboards;
- the **ledger**: who did what, kept in `immudb`.

### 4. Running tests

A test is a Python plugin built on the plugin interface (`shared/plugin-interface`). Installing it (admins) has
`plugin-publisher` build it, from its lux-ai-factory repository or from your folder in `local_plugins/`, onto the
stack's own package index, `devpi`, from which the engine installs it.

Running it: `aisc-backend` records the run and queues it (through `rabbitmq` and `redis`); `aisc-eval-worker` installs
the test in a fresh environment, runs it and sends the results back to `aisc-backend`, which keeps them in the
project's database and in `minio`.

A test never holds the secrets of the system it assesses. It calls one of the platform's doors (OpenAI-compatible,
A2A, Open Inference Protocol, or a plain "ask") with a short-lived run key, and the platform forwards the call to the
connection registered under Manage, adding the secrets and holding it to the allowed hosts and the timeout. A system
that speaks none of these protocols is reached through an adapter plugin from `adapters/`. Models a test uses as tools
(a judge, an attacker, a grader) are helper models, registered apart and never what is assessed.

### Where data is kept

In short: `postgres` holds the platform's database and one database per project (every step's records), `minio` the
uploaded datasets and models and the files tests write, `devpi` the test packages, `immudb` the ledger, `keycloak`
the accounts. [Appendix 8](appendices/data.md) has the full map.

## Reading further

- The step appendices: [1](appendices/1-qualify.md), [2](appendices/2-control-objectives.md),
  [3](appendices/3-tests-and-checklists.md), [4](appendices/4-collect-evidence.md), [Manage](appendices/manage.md).
- The technical appendices: [Services](appendices/services.md), [Flows](appendices/flows.md),
  [Data](appendices/data.md), [Security](appendices/security.md).
- [The guide](guide.md): settings, ports, passwords and keys, tests.
- Each submodule's README, for the application's own internals.
