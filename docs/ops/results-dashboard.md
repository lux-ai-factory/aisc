# Results, the analytics dashboard bridge and the dashboard's own Redis

*ANA-01 (#115). Decisions: [ADR 0007](../adr/0007-results-dashboard-bridge-and-cache.md); the isolated
cache was decided in [ADR 0001](../adr/0001-mainline-first-consolidation.md).*

The results page (per AI-card version: what was run, by which tool, against which component, plus the
metric charts) is the *app's*. The analytics dashboard (**Superset**) is a separate deployment: its own
repository, its own process, its own database. The app never queries it and never reads its store — it
links to it, and it may tell the dashboard's own bridge API that a project exists.

Everything below is optional. With none of it configured, the results page shows the summary and the
charts and no dashboard link at all.

## What a deployment sets

| Variable | What it is | Empty means |
|---|---|---|
| `RESULTS_DASHBOARD_URL` | Where the dashboard's AI-system dashboard lives | no link is built |
| `RESULTS_DASHBOARD_SECRET` | The key the link is signed with; the **same value** must be known to the dashboard (or to the proxy in front of it) | **no link is built** — a link the dashboard cannot verify is not shipped |
| `RESULTS_DASHBOARD_LINK_TTL` | How long a minted link stays valid, in seconds (default 900) | 900 |
| `RESULTS_DASHBOARD_BRIDGE_URL` | The dashboard's bridge API base (`…/api/v1/aisc_project/<pid>` is appended) | nothing is called |
| `RESULTS_DASHBOARD_BRIDGE_TOKEN` | The shared token the bridge reads from `X-AISC-Bridge-Token`; the dashboard refuses a call with an empty one | **nothing is called** |
| `DASHBOARD_REDIS_PASSWORD` | The dashboard's own Redis password (compose profile `analytics`) | `docker compose --profile analytics …` refuses to resolve |

`RESULTS_DASHBOARD_URL`, `RESULTS_DASHBOARD_SECRET`, `RESULTS_DASHBOARD_LINK_TTL`,
`RESULTS_DASHBOARD_BRIDGE_URL` and `RESULTS_DASHBOARD_BRIDGE_TOKEN` are passed to `aisc-backend` by both
`docker-compose.yml` and `docker-compose.development.yml`; the descriptions are in `env.example`.

## The link: signed, scoped, expiring

A link looks like:

```
https://dashboard.example/superset/dashboard/ai-system
  ?project=11111111-1111-1111-1111-111111111111
  &version=3&tool=fairness&exp=1771065600&sig=9f2c…
```

* **Scoped** — `project` always; `version`, `target` and `tool` when the page has chosen them. The
  per-tool link on a tile carries that tool; the page's own link carries none.
* **Authenticated** — `sig` is HMAC-SHA256 over the scope and the expiry, in a fixed order
  (`project`, `version`, `target`, `tool`, `exp`). Editing any of them, or the expiry, breaks it.
* **Expiring** — `exp` is a Unix timestamp; after it, the link verifies as `expired`.

The dashboard side verifies with the same key. The refusals are named, so a proxy can log which one it
was and answer 403: `this link carries no signature`, `this link's signature does not match its scope`,
`this link has expired`, `this link is not for this project`, `no dashboard link key is configured`.
A link minted for one project **does not** verify for another (that is what scoping buys), and no key
configured means no link is minted at all.

The backend returns the link together with what it is about, so the page can say why it has none:

```json
"dashboard": {"url": "…", "authenticated": true, "bridge_configured": true,
              "scope": {"project": "…", "version": "3", "target": null, "tool": null}}
```

## Telling the dashboard about a project

```
POST   /api/v1/projects/{pid}/results/dashboard     # register (and later: sync a tool's tile)
DELETE /api/v1/projects/{pid}/results/dashboard     # unregister
```

Both need **editor** on the project, both are audited (`dashboard_registration`), and both answer with
what the dashboard did rather than raising: `{"registered": true|false, "bridge_configured": …}`. A
dashboard that is down, slow or unconfigured never stops a person working. The bridge calls the pilot's
own API with the pilot's header:

```
POST   <DASHBOARD_BRIDGE_URL>/api/v1/aisc_project/<pid>          {"slug", "name"}
DELETE <DASHBOARD_BRIDGE_URL>/api/v1/aisc_project/<pid>
PUT    <DASHBOARD_BRIDGE_URL>/api/v1/aisc_project/<pid>/plugins  {"plugin", "label", "version", "project_name", "visualizations", "again"}
```

The pilot pushed registration on project create and deletion on drop; here it is an explicit action,
because the unified app has no project-lifecycle hook that may make an external call.

## The dashboard's own Redis (compose profile `analytics`)

Superset's `RedisCache` **unpickles** what it reads. If it shared the eval worker's Redis, a plugin that
wrote a pickle there would run code in a process holding every project's read credentials. So the
dashboard's cache is a Redis of its own:

```bash
# in .env
DASHBOARD_REDIS_PASSWORD=$(openssl rand -hex 32)

# start it (the default `docker compose up -d` does NOT)
docker compose --profile analytics up -d
```

`dashboard-redis` in `docker-compose.yml`:

* asks for the password from its environment (`requirepass` written into a config file, so the value is
  never in `docker compose config` output nor in `ps`);
* publishes **no** port (nothing on the host can reach the cache);
* is on its own network (`dashboard`) that no service running plugin code joins — not `aisc-eval-worker`,
  not `redis`, not `aisc-backend`, not `caddy`;
* has its own volume (`dashboard_redis_data`), not `redis_data`;
* makes the file refuse to resolve without `DASHBOARD_REDIS_PASSWORD` (`:?`), so a stack never starts
  with an open cache.

The Superset process joins the `dashboard` network and reads `DASHBOARD_REDIS_HOST=dashboard-redis`,
`DASHBOARD_REDIS_PORT=6379`, `DASHBOARD_REDIS_PASSWORD=…`. It is deployed from its own repository, so
this stack does not build it.

## Verifying it

**What would start** (no daemon needed, runs in the backend test suite and in CI):

```bash
cd apps/backend && uv run python manage.py test aisc_backend.tests.test_dashboard_redis_compose
```

That reads the compose file *and* the model `docker compose config` resolves, and asserts: the profile
is opt-in, the password is required, `requirepass` is on, no port is published, only the dashboard's
side is on its network, and the two caches have two volumes and two networks.

**What did start** (on a running deployment):

```bash
DASHBOARD_REDIS_PASSWORD=… scripts/verify-dashboard-redis.sh
```

It checks the same four things against the running stack (`redis-cli ping` without a password must
answer `NOAUTH`, the password itself must work, no port must be published, the password must not be in
the server's command line, and no service running plugin code may be attached to the cache's network).
It exits non-zero and says which check failed — it never passes silently.

**The rule itself, with no Docker at all** (a `redis-server` on this host is enough):

```bash
scripts/verify-dashboard-redis.sh --local
```

It starts a throwaway server with the compose service's own configuration
(`requirepass`, `save ""`, `appendonly no`, loopback only) and runs the client-side half of the checks
against it: no password is refused, the password works, nothing is persisted, nothing is published, and
the password is not in the server's command line. The deployment-only checks (which network it is on and
who shares it) are not run and it says so — run the plain form on a stack for those.

**The link contract** (unit tests, no dashboard needed):

```bash
cd apps/backend && uv run python manage.py test aisc_backend.tests.test_dashboard_link
```

Round-trip, edited scope, edited expiry, expired link, another project, another key, no key.

## Charts

The results summary carries `charts` — one row per metric over the scoped runs, read through the
visualizer's own `MeasurementRepository` (`metric_summary`), with `chart_scope` saying how many
evaluations were counted and how many all-local evaluations were left out. A run on a locally served
model is not part of the assessment record, so its measurements never reach a charted figure — the same
rule the report renderer applies.
