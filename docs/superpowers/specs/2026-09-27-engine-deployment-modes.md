# The execution engine in two deployment modes

Date: 2026-09-27. Agreed with the user in conversation; to be confirmed with Sean (engine owner).

## Why

Sean wants the execution engine usable on its own: projects are created in the engine, it has its
own login, it keeps its data in its own database. The Sandbox Configurator needs the opposite: the
platform owns projects and memberships, every project has a database of its own, the engine never
creates a project and only works inside the one chosen on the launcher. Both must install tests
through the public (hosted) catalogue, whose handoff to the engine is Méril's
`feat/dev-catalogue-staging` build, unchanged.

The engine is rebuilt **from Sean's `master` (v1.3.0)**, and everything the Configurator needs is
added on top as the `configurator` mode. Nothing Sean's standalone engine does today is removed.

## The switch

`AISC_DEPLOYMENT` = `standalone` | `configurator`, read by the backend, the eval worker and the web
app (web app: `VITE_DEPLOYMENT=APP_DEPLOYMENT`, substituted by `env.sh` at start, like
`APP_CATALOG_URL`). Default `standalone`, so Sean's repos deployed alone behave as today. Any
other value, or a `configurator` without `PLATFORM_URL` and `PROJECT_DATABASE_TEMPLATE`, refuses
to start with a message naming the variable.

## What the switch decides

| Concern | standalone | configurator |
|---|---|---|
| Where projects live | one engine database, all projects in it | one database per platform project (`ProjectDoor`, `projectdb`) |
| Creating a project | engine UI wizard, `POST /projects` | never; `POST /projects/for-platform/<pid>` finds or makes the engine's row |
| Login | Sean's: Django admin, allauth, JWT, the web app's LoginDialog | the gateway's session; no login of its own (the `0024` table drop runs only here) |
| Who may act | Keycloak roles | platform memberships |
| `X-AISC-Project` header, door | off | on |
| Engine start page | Sean's project list | opens the launcher's project |
| Install dialog | Sean's: lists all projects (`GET /projects`) | the link's `project` if present, else the project last opened in this browser, preselected and named; the list of the caller's platform projects to change it; a message when there is none |
| Celery tasks page | Sean's page | hidden (it lists every project's tasks) |
| Launcher links | hidden | shown |
| Eval worker calls | plain | project, run ticket, evaluation headers |

The data model (models and migrations) is **one**, the same in both modes: a schema cannot sit
behind a switch. Our migrations are appended after Sean's `0014_ai_system_and_project_config_squashed`.

## Decisions taken as defaults (change them with Sean)

- Standalone keeps one database for everything.
- Standalone login is Sean's, `AUTH_ENABLED` as he has it.
- Name `AISC_DEPLOYMENT`, default `standalone`.
