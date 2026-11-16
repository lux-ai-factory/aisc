# Appendix 7: Flows

Back to [How AISC works](../architecture.md).

How a request travels through the stack, for the main things people do. Service names are those of
[Appendix 6](services.md).

## Signing in and one request

1. The browser opens a page on 80, 8100 or 8188. `caddy` asks `oauth2-proxy` whether the caller is signed in. Without
   a session the browser is sent to `keycloak` (`127.0.0.1:8081`); after the login `oauth2-proxy` sets a cookie for the
   host, which covers every port.
2. `caddy` passes the request on with the caller's token.
3. The service checks the caller itself. The Python services verify the token with `aisc_identity` and read the
   caller's role in the project from the platform's database; the Next.js applications (qualification, controls) pass
   the token to the platform's `/authz/projects/{ref}` and follow its answer; the dashboard checks it through
   `dashboard-gateway/`.
4. A write is witnessed first: `caddy` asks the platform, which records who made the request and gives it a request
   id that the service's ledger events cite (see [The ledger](#the-ledger)).

## Creating a project

The launcher calls the platform. The platform records the project and its owner, creates the project's database
`project_<pid>` from `platform/project-template/` (every schema the steps use), and registers the project with the
dashboard (a Superset connection, its datasets and a role). At every start the `*-migrate` services bring each
application's tables up to date in every project database.

## Step 1: saving the AI card

`qualification-web` keeps the answers in `qualification`. The prefill, the card agent, the ontology builder and the PDF
renderer are called when asked. A save asks the platform to make the next AI card version; if the platform does not
answer, nothing is saved. The save also writes the card's links to the engine's components (`card_component`). The
card's graph is built from the answers, the agent's draft and the corrections every time it is read.

## Step 2: assessing

`control-objectives` asks the platform for the latest AI card version, then asks `qualification-web` for that version's
card as JSON-LD, and makes one risk per risk chain. Ratings, links to objectives (by hand, or by the risk mapper with
a quote from the chain for each), priority choices and the objective selection go into `control_objectives`.

## Step 3: installing

- **Choosing the catalogue**: the platform records the choice in the project's `catalogue` schema; for a private
  catalogue it copies the public one there.
- **A test** (admins): the platform works out the version. If `devpi` lacks it, `plugin-publisher` clones the
  repository (or copies the `local_plugins/` folder), builds the package and uploads it; the platform checks that the
  engine sees it, then asks `aisc-backend` to install it.
- **A checklist** (editors): the catalogue page asks `controls-web`, which gets the checklist's package from the
  platform and installs it into `controls`.

## Step 4: a test run

1. On the engine's pages, `aisc-backend` records the evaluation, stamps it with the latest AI card version, and
   queues it on `rabbitmq`: what is assessed, the helper models per role, the datasets and models, the settings.
2. `aisc-eval-worker` takes the tasks: install the test's package in a fresh environment, run each test, finish.
3. The worker gets a **run pass** from the platform and hands it to the test.
4. The test reaches the **assessed system** through the platform: with the run pass it reads the connection's
   settings (secret values masked), takes a run key, and calls one of the platform's doors (`aisc/ask`, OpenAI,
   A2A or Open Inference Protocol). The platform adds the secrets, holds the call to the allowed hosts, the timeout and
   the adapter's limit on calls at once, and calls the system.
5. The test calls **helper models** directly: the worker resolves each one's endpoint and key from the platform and
   gives them to the test.
6. The worker sends the measurements and files to `aisc-backend`, which keeps them in `engine` and in `minio`
   (`artifacts`). A test that fails while it runs marks the run Failed and stops the run's other tests.
7. If the worker stops in the middle, the broker hands each unfinished task to it again, and the task starts over.

## Step 4: results and dashboards

- The Collect evidence and Results pages ask the platform, which reads `engine` and `controls` of the project's
  database read-only and the AI card's targets.
- **Open charts**: the platform takes the test's latest finished run, asks `aisc-backend` for the charts the plugin
  declares (with the caller's token), and hands them to the dashboard, which makes or updates that test's dashboard,
  visible only to the project's members. The dashboard opens on the AI card version the link came from; local runs
  are left out unless its Local filter is on.
- Comments and review requests made in the dashboard reach the ledger through the platform.

## Step 4: the Evidence map

The Evidence map page asks the platform for the selected version's objectives (from `control_objectives`), the
installed tests and checklists, their dimensions (from the project's catalogue), the links and their coverage. A
click links or unlinks (`evidence.link`), a note is kept with its link, and **Mark reviewed** records the reviewer
(`evidence.review`) when that person made none of the version's links. Every change writes a ledger event.

## Step 4: a report

`report-composer` keeps layouts and templates in `report_composer`. **Generate** builds a request: the layout and its
blocks' options, the AI card version and the selection (period, other versions, a version to compare with), the
Evidence map's links, the plugins' declared charts and the look. `report-renderer` reads the data it needs itself,
read-only, draws the PDF or Word document (and a PDF copy of a Word one when it can), and the composer keeps the
document, its checksum and the request.

## The ledger

With the stack's settings (`LEDGER_GATEWAY=on`, `LEDGER_MODE=record`):

1. **Witness**: `caddy` asks the platform about every write; the platform records the person and the request in
   Postgres and returns a request id.
2. **Events**: each service writes an event citing that request id in the same transaction as the change it
   describes: the Python and Next.js applications through the project database's `ledger.emit`, the platform in its
   own outbox, the engine in its outbox, which `aisc-backend-ledger` sends to the platform every 10 seconds.
3. **Relay**: a worker in each platform process turns witness records and events into entries of the project's
   immudb database (an event that does not fit its request is recorded as rejected), and indexes them.
4. **Reading**: Manage > Activity log checks every entry before showing it; an export can be checked offline with
   `scripts/verify-ledger-export.py`.

The engine also keeps its own audit log, in immudb's `auditdb`.

## Start, stop, remove

`uv run scripts/aisc.py start` makes the secrets (`scripts/secrets.sh`), moves a browser port that is taken, and starts
the stack; the one-shot services run every time, and `plugin-publisher` publishes the plugin interface. `stop` stops
it. `remove` deletes the install's containers and volumes, so every project and its data; the images and the folder
stay.
