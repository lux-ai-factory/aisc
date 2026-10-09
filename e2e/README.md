# AISC end-to-end smoke test

A [Playwright](https://playwright.dev) test that starts the **user-facing**
stack (`../docker-compose.yml`, pulling the published GHCR images), waits for it
to become ready, and drives a real Chromium browser to confirm the platform is
actually accessible at `http://localhost:8080`.

It guards against the exact class of failure that is invisible to
`docker compose config`: images that pull but serve a blank page.

## Run locally

Prerequisites: Docker + Compose v2, Node.js 20+.

```bash
cd e2e
npm install
npx playwright install chromium   # first time only

npm test                          # starts the stack, runs the browser test, tears it down
```

Useful options:

```bash
E2E_PORT=18080 npm test            # bind the stack to a different host port
AISC_IMAGE_TAG=v1.3.0 npm test     # test a specific published image tag
npm run test:headed                # watch the browser
npm run report                     # open the last HTML report
```

The stack runs under the Compose project `aisc-e2e` with a generated
`e2e/.env.e2e`, so your own `.env` and `aisc` stack are left untouched.

## In CI

`.github/workflows/e2e-compose.yaml` runs this suite on every `v*.*.*` tag (and
on manual dispatch) against the published `ghcr.io/lux-ai-factory/*` images.
