# 0007. The results bridge and the dashboard's own Redis in the unified stack

**Status:** accepted
**Invariant:** I11 — the default contract does not grow (the cache is an opt-in profile); ADR [0001](0001-mainline-first-consolidation.md)'s Superset-cache decision implemented here; I8 referenced (one moving part added, and only when a deployment asks for it)
**Owner:** AISC project owner (results/analytics workstream, epic E4 / ANA-01)
**Date:** 2026-11-17

## Context

ANA-01 (#115) is the last E4 port: scoped results, the analytics-dashboard (Superset) bridge and the
charts behind a run summary. Three decisions had to be taken to land it in the unified app:

1. **How does a results page link into the dashboard, and how is that link authenticated?** The pilot
   signs people in once at its gateway (oauth2-proxy in front of Keycloak) and hands Superset the
   verified name as `REMOTE_USER` (`dashboard-gateway/gateway_identity.py`); the platform also tells the
   dashboard's own bridge about each project with a shared token (`DASHBOARD_BRIDGE_TOKEN`), and a
   bridge whose token is empty refuses every call. The unified app has no such gateway in front of it,
   and the dashboard is a separate deployment, so the gateway's cookie cannot be assumed.
2. **Where does the dashboard's cache live?** ADR 0001 already decided this: an *isolated Superset
   cache*, because Superset's `RedisCache` unpickles what it reads and the shared Redis is the eval
   worker's result backend — a plugin that wrote a pickle there would run code in a process holding
   every project's read password. The decision was never carried into the unified deployment's compose
   files, so the unified stack had no dashboard cache at all.
3. **Do the charts need a second query path?** The visualizer already aggregates measurements through
   `MeasurementRepository`; the pilot's dashboard reads Superset's own store.

## Decision

1. **Links are signed and scoped, and minted only when they can be verified.** The backend mints a
   dashboard link that carries its scope (project, AI-card version, target, tool) and an expiry, signed
   with a shared key (`RESULTS_DASHBOARD_SECRET`) the dashboard — or a proxy in front of it — also
   holds (`services/dashboard_link.py`). Verification names its refusals (`NO_SIGNATURE`,
   `BAD_SIGNATURE`, `EXPIRED`, `WRONG_PROJECT`, `NO_SECRET`) so a proxy can log which one it was and a
   test can tell them apart. **With no key configured no link is minted at all**: an unsigned link into
   a dashboard that holds every project's data is worse than no link. This *replaces* the pilot's
   gateway-session mechanism, which needs the gateway deployment; the scope and the expiry are the
   pilot's (it embedded `project`/`version`/`tool` in the link too).
2. **The dashboard's own bridge API is ported, with the pilot's fail-closed rule on our side too.**
   `services/dashboard_bridge.py` calls `POST|DELETE /api/v1/aisc_project/<pid>` and
   `PUT /api/v1/aisc_project/<pid>/plugins` with the pilot's header (`X-AISC-Bridge-Token`) and token
   (`RESULTS_DASHBOARD_BRIDGE_TOKEN`). **With no token — or no URL — no request leaves the process**
   (`BridgeClosed`), because the dashboard refuses such a call anyway. Registration is best-effort
   (a dashboard that is down never stops a person working); a tool tile someone asked for raises
   `BridgeUnavailable` so they are told. It is called explicitly, from
   `POST|DELETE /projects/{pid}/results/dashboard` (editor, audited), rather than from project
   create/delete — the unified app has no project-lifecycle hook that may make external calls (I3).
3. **The dashboard's Redis is an opt-in profile, exactly as the pilot had it.** `dashboard-redis` in
   `docker-compose.yml`, in profile `analytics`: a password read from its environment inside the
   container (never its command line, where `ps` would show it), its own volume, its own network
   (`dashboard`) that no service running plugin code joins, and no published port. The file refuses to
   resolve without `DASHBOARD_REDIS_PASSWORD` (`:?`), so `docker compose config` fails rather than
   starting an open cache. **The default `docker compose up -d` does not include it** (I11): the
   default contract is one Redis, the eval worker's, unchanged.
4. **The charts are the visualizer's own query, and never include a local-model run.** The run summary
   gains `charts` (per metric: count/mean/least/most, over the scoped evaluations) read through
   `MeasurementRepository.metric_summary`, and an all-local evaluation is left out of both the charts
   and the tile counts, as the report renderer already does. No second query path is added.

## Consequences

- The Superset process itself is **not** ported: its own repository (`aisc-results-dashboard`) is not a
  submodule of the unified app, so the dashboard stays a separate deployment that points
  `RESULTS_DASHBOARD_URL`/`BRIDGE_URL` at us and joins the `dashboard` network. Recorded in
  `docs/refactor-deviations.md`.
- A deployment that wants the analytics profile must set `DASHBOARD_REDIS_PASSWORD` (and
  `RESULTS_DASHBOARD_*`); with none of them set, nothing changes for it.
- The link's key and the bridge's token are two different secrets with two different jobs (verifying a
  link a browser follows; authenticating a call we make), and the pilot's single gateway is not needed
  for either.
- Guards: the analytics profile is what I11 asks for, so `tests/architecture` is unchanged
  (5 passed, 3 xfailed, 0 failed). The port's own tests live beside the code
  (`apps/backend/aisc_backend/tests/test_dashboard_link.py`, `test_dashboard_bridge.py`,
  `test_dashboard_redis_compose.py`, `tests/routers/test_results_router.py`).
