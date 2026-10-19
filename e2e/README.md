# AISC end-to-end tests

[Playwright](https://playwright.dev) tests that start the Compose stack, wait for
it to become ready, and drive a real Chromium browser against
`http://localhost:8080`.

`tests/smoke.spec.ts` confirms the webapp mounts and renders and that the backend
API and Keycloak are reachable through Caddy. It catches the class of failure
`docker compose config` cannot see: images that pull fine but serve a blank page.

## Run locally

Prerequisites: Docker + Compose v2, Node.js 20+.

```bash
cd e2e
npm install
npx playwright install chromium   # first time only

npm test                          # published GHCR images
npm run test:build                # build apps/* locally, then run the same suite
```

Useful options:

```bash
E2E_PORT=18080 npm test            # bind the stack to a different host port
AISC_IMAGE_TAG=v1.3.0 npm test     # test a specific published image tag
E2E_BUILD=1 npm test               # same as `npm run test:build`
E2E_KEEP=1 npm run test:build      # leave the stack running to browse it yourself
npm run test:ui                    # interactive UI mode (click tests, inspect results)
npm run test:build:ui              # UI mode, building apps/* first
npm run test:headed                # watch the browser
npm run report                     # open the last HTML report
```

To build the images, start the stack, **and leave it up** to click around in your
own browser:

```bash
E2E_KEEP=1 npm run test:build
# -> webapp at http://localhost:8080/   (override the port with E2E_PORT)
```

The setup prints what it waits for and, if the stack never becomes healthy,
dumps `docker compose ps` plus the last 150 log lines — so a failure is
diagnosable instead of looking like a hang.

The stack runs under the Compose project `aisc-e2e` with a generated
`e2e/.env.e2e`, so your own `.env` and `aisc` stack are left untouched.

`npm run test:build` needs the submodules initialised
(`git submodule update --init --recursive`); it uses
`../docker-compose.build.yml`, which builds `apps/backend`, `apps/eval` and
`apps/webapp` instead of pulling them.

## UI mode

[Playwright UI mode](https://playwright.dev/docs/test-ui-mode) is an interactive
runner: click a test to run it, then step through it and inspect the DOM,
network, console and traces.

```bash
npm run test:ui          # against the published images
npm run test:build:ui    # build apps/* first, then open UI mode
```

The stack is brought up once when the UI opens and torn down when you close it;
if it is already running, setup reuses it. The same `E2E_PORT` / `E2E_KEEP`
options apply.

## In CI

`.github/workflows/e2e-compose.yaml` runs both flavours on every `v*.*.*` tag
and on manual dispatch: against the published `ghcr.io/lux-ai-factory/*` images,
and against images built from the checked-out submodules.
