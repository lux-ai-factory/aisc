# WP3 notes: pgAdmin and schema-docs off the shared network

Date 2026-09-25. Branch feat/unified-modules, top-level repo only, local commits, nothing pushed,
nothing deployed, the running stack not touched. Addresses findings 4 (pgAdmin open on `backend`)
and 10 (schema-docs open on `backend`) of 01-inventory.md.

## Commits

| repo | commit | what |
|---|---|---|
| top-level | `9d60bb8` | docker-compose-infra.development.yml (the `inspector` network), scripts/tests/test_inspector_network.py |
| top-level | the follow-up commit | these notes |

## Where things are defined

- pgadmin and schema-docs: docker-compose-infra.development.yml only (docker-compose.development.yml
  has neither, so WP2's changes there are untouched). No staging compose file defines them.
- The schema docs are made inside schema-docs itself: inspector/schema-docs/server.py runs the
  SchemaSpy jar in the container on a visit (`-host $PGHOST`, `postgres`) and serves the result from
  its own filesystem. There is no separate SchemaSpy job and no shared volume, so the only thing the
  generation path needs is postgres, which is on the new network.
- pgAdmin's server list (inspector/pgadmin-servers.json) names host `postgres`, and its pgpass line is
  `postgres:5432:*:inspector_ro`; both resolve on the new network.
- Caddy (Caddyfile, launcher site block `{$CADDY_DOMAIN}:{$HOMEPAGE_PORT}`) routes
  `/inspect/pgadmin*` to `pgadmin:80` (path unstripped, pgAdmin serves under SCRIPT_NAME) and
  `/inspect/schema*` to `schema-docs:8080` (handle_path), both behind `protect` and `admin_only`.
  The Caddyfile is unchanged: the names resolve over `inspector` now.

## Network map

Before:

| network | members |
|---|---|
| backend | every containerised service, pgadmin and schema-docs included (aisc-eval-worker, which runs plugins, among them) |
| frontend | caddy and the services already on it |

After:

| network | members |
|---|---|
| backend | as before, minus pgadmin and schema-docs |
| frontend | unchanged |
| inspector (new) | pgadmin, schema-docs, caddy, postgres |

Decision recorded: caddy and postgres join `inspector` in addition to their existing networks;
pgadmin and schema-docs are on `inspector` only. Does postgres on `inspector` give anything new
access? No: the only other members are caddy, which already reached postgres over `backend`, and the
two inspectors, which reached it over `backend` before and read only as `inspector_ro`. Caddy on
`inspector` is reachable from the inspectors, but caddy is the public entry point anyway. The
dashboard (network_mode: host) joins no compose network and reads postgres on 127.0.0.1:5432 as
before.

## Tests (scripts/tests/test_inspector_network.py, reuses test_compose.py's resolved-config fixture)

Checks: compose stays valid; `inspector` is declared; pgadmin and schema-docs are on `inspector`
only; caddy and postgres are on it; no other service shares any network with either inspector;
aisc-eval-worker shares none; the members of `inspector` are exactly the four; both inspectors still
depend on postgres and postgres is on their network.

| run | result |
|---|---|
| new file, HEAD compose (red) | 11 failed, 1 passed (the validity check) |
| new file, after the change (green) | 12 passed |
| test_inspector_network + test_compose + test_llm_keys + test_service_tokens | 62 passed |
| scripts/tests, whole (uvx, pyyaml, psycopg) | 226 passed, 11 failed |

The 11 whole-suite failures are all in WP2's note c list, none reads the network sections:
test_db_consistency (2), test_guard_frozen (3), test_pipeline_chain (3), test_report_stack
(init-file guard, launcher card seven with the user's uncommitted homepage/project.html, final
frozen guard). Fewer than WP2's 25 because the throwaway-DB suites ran cleanly this time.

## Deploy (the orchestrator)

The four containers must be recreated for the network change to apply (`docker compose -p aisc
... up -d caddy postgres pgadmin schema-docs`). Recreating postgres means a short database outage;
if that matters, attach the two long-lived ones live and recreate only the inspectors:

```bash
docker network create aisc_inspector   # or let `up -d pgadmin` create it first, then:
docker network connect aisc_inspector postgres
docker network connect aisc_inspector caddy
docker compose -p aisc -f docker-compose-infra.development.yml -f docker-compose.development.yml \
  --env-file env.runtime up -d --no-deps pgadmin schema-docs
```

(Use whatever env-file and file list the stack is normally started with. A later full `up -d` will
see caddy and postgres already on the network and leave them alone or recreate them to match.)

## Live probes for after the deploy

```bash
# 1. From the plugin-running container: both names fail (no DNS entry on its networks).
docker exec aisc-eval-worker python - <<'PY'
import socket, urllib.request as u
for host, port, path in [("pgadmin", 80, "/inspect/pgadmin/browser/"), ("schema-docs", 8080, "/health")]:
    try:
        print(host, "REACHABLE", u.urlopen(f"http://{host}:{port}{path}", timeout=5).status)
    except Exception as x:
        print(host, "unreachable:", type(x).__name__, x)
PY
# expected: both lines "unreachable" (URLError, Name or service not known / Temporary failure in name resolution)

# 2. The same from any other backend service, e.g. the platform and qualification-web:
docker exec platform python -c 'import socket
for h in ("pgadmin","schema-docs"):
    try: print(h, socket.gethostbyname(h))
    except OSError as x: print(h, "unresolvable", x)'
# expected: both unresolvable

# 3. Caddy still reaches them (the only way in):
docker exec caddy wget -q -S -O /dev/null http://pgadmin:80/inspect/pgadmin/misc/ping 2>&1 | head -1
docker exec caddy wget -q -S -O /dev/null http://schema-docs:8080/health 2>&1 | head -1
# expected: HTTP/1.1 200 (pgadmin ping) and HTTP/1.1 204 (schema-docs)

# 4. The inspectors still reach postgres:
docker exec pgadmin sh -c 'nc -z -w 3 postgres 5432 && echo postgres ok'
docker exec schema-docs sh -c 'getent hosts postgres && echo postgres resolves'
# expected: "postgres ok" and "postgres resolves"

# 5. Through the launcher, unauthenticated: the gate answers (redirect to sign-in), not 502.
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8100/inspect/pgadmin/
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8100/inspect/schema/platform/
# expected: 302 (or 401), never 502

# 6. In the browser, signed in as a platform admin: http://localhost:8100/inspect/pgadmin/ opens
#    pgAdmin and a query on the platform database runs; /inspect/schema/platform/ shows (or
#    generates) the SchemaSpy pages. A non-admin still gets the admin_only refusal.
```

## Open items

1. pgAdmin still runs in desktop mode with a preloaded pgpass. After this change only Caddy's
   admin gate stands in front of it, which is what the design relies on; if Caddy is ever bypassed
   (for example a port published on pgadmin), finding 4 is back. Nothing publishes a port today.
2. Probes 3 and 4 rely on wget in the caddy image and nc/getent in the
   pgadmin and schema-docs images; if one is missing, use `docker run --rm --network aisc_inspector
   curlimages/curl ...` instead.
