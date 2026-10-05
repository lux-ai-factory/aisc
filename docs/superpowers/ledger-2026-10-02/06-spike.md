# Ledger: the gateway and immudb spike (2026-10-02)

The independent review (05) marked its statements about Caddy and immudb **(verify)**. This spike
runs them. Everything ran on throwaway containers (`aisc-t-spike-*`, network `aisc-t-spike`), never
on the running stack. The scripts are in `spike/`; `spike/run.sh` re-creates the setup.

## Setup

- `caddy:2.10.2` (the stack's pin) with the real `Caddyfile`, changed only where it must be:
  `host.docker.internal:4180` became `auth:4180`, TLS became an empty snippet, the listeners moved to
  18080 (main), 18100 (launcher) and 18088 (dashboard).
- Stub upstreams (`spike/stub.py`), one container each, under the real upstream names:
  - `auth` plays oauth2-proxy. It answers 202 with `X-Auth-Request-User: alice-sub`,
    `X-Auth-Request-Email` and `X-Auth-Request-Access-Token: token-of-alice`, and 401 on request.
  - `platform` plays the witness at `/authz/witness`. It logs every header it gets and answers
    200 with `X-AISC-Request-Id: rid-from-witness`, or 200 without an id, 401, 503 or a slow answer,
    as each probe asks.
  - Every app upstream answers with the method, path and headers it received.
- `spike/probe.py PORT METHOD PATH [Header:value ...]` sends one request and prints what the witness
  saw and what reached the app.
- `codenotary/immudb:1.11.1` (the stack's pin) with immudb-py 1.5.0 (the engine's pin);
  `spike/immu_spike.py` and `spike/immu_restore2.py`.

Three Caddyfiles:

| File | `protect` |
|---|---|
| `Caddyfile.v0` | today's snippet plus the witness as spec v1 drew it: a second `forward_auth platform:8000 { uri /authz/witness; copy_headers X-AISC-Request-Id }` after sign-in |
| `Caddyfile.v1a` | the review's fixes (an app argument, the original URI, a gateway secret, a strip, a writes-only matcher) written straight into the snippet |
| `Caddyfile.v1c` | the same inside `route { }`, with every identity header stripped first |

## What the gateway does (observed)

### G1. The witness sees the path after `handle_path` has stripped it (review 1.1: confirmed)

| Request | `X-Forwarded-Uri` at the witness |
|---|---|
| `GET :18080/control-objectives/p/PID123/projects/a1` | `/p/PID123/projects/a1` |
| `GET :18080/report-composer/p/mcas/layouts` | `/p/mcas/layouts` |
| `GET :18100/api/projects/mcas/evidence` (launcher) | `/projects/mcas/evidence` |
| `GET :18080/api/v1/components/c1` (engine) | `/api/v1/components/c1` |
| `GET :18088/superset/dashboard/3/` | `/superset/dashboard/3/` |

`X-Forwarded-Host` keeps the port (`localhost:18080`, `localhost:18100`, `localhost:18088`). The host
can tell the three sites apart; the path can't tell the apps apart.

### G2. Anyone signed in can call the witness with headers they choose (review 1.2: confirmed)

`GET :18100/api/authz/witness` with `X-Forwarded-Method: POST` and
`X-Forwarded-Uri: /control-objectives/p/OTHER/x` reached the platform twice: once as the real witness
call, then as the proxied request, carrying the client's method and URI unchanged and a fresh request
id. From inside the network, a container calling `http://platform:8000/authz/witness` directly with
any headers got 200 and an id.

### G3. A forged `X-AISC-Request-Id` reaches the app whenever the witness returns none (review 1.3: confirmed)

| Witness answer | Client sends `X-AISC-Request-Id: FORGED` | App receives |
|---|---|---|
| 200 with an id | yes | `rid-from-witness` (`copy_headers` overwrites) |
| 200 without an id | yes | `FORGED` |

The same holds for identity headers. `copy_headers` overwrites the ones oauth2-proxy returns, and
leaves a client-sent header in place when the auth response lacks it. A forged
`X-Auth-Request-Preferred-Username: mallory` reached the app untouched, because the stub returns no
such header. **This is a defect in today's gateway, not only in the ledger design**, whenever
oauth2-proxy omits a header (it sends Preferred-Username only when the claim is set). Not yet checked
against the real oauth2-proxy.

### G4. Apps receive the client's own `X-Forwarded-Uri` and `X-Forwarded-Method`

On a normal handle, a client-sent `X-Forwarded-Uri: /evil` and `X-Forwarded-Method: DELETE` were
replaced in the witness's request (forward_auth sets its own), but reached the **app** unchanged. No
app may read these headers to decide anything.

### G5. Both tokens reach the app (review 1.4: confirmed)

A client-sent `Authorization: Bearer tok-bob` reached the witness and the app next to the gateway's
`X-Auth-Request-Access-Token: token-of-alice`. The engine's web app (`apps/webapp`, frozen code) sends
its own keycloak-js Bearer token on purpose, so Caddy can't strip `Authorization`. The witness has to
compare the two.

### G6. A Next.js server action is a POST to the page, with its id in a header (review 1.7: partly confirmed)

`POST /qualification/p/mcas/qualify/new` with `Next-Action: 60b7a2ef` and body `["mcas"]`: the
witness got `Next-Action` and no body. Read-only, in the running `qualification-web` container
(Next 15.0.3):
- `.next/server/server-reference-manifest.json` maps each of the 14 action ids to the **pages** that
  use it, never to a function name.
- The production chunks register actions with the name `null`.
- No source maps are shipped.
- The ids are salted per build. Not one of the 14 equals sha1(`file:export`) for the 16 exported
  server functions.

So the witness can record which action ran (its id) and on which page, but no build artefact says
which function an id is. The review's "map ids from the manifest at build time" doesn't work on this
Next version.

### G7. Without `route`, Caddy reorders the snippet and breaks it (new)

In `Caddyfile.v1a`, Caddy's own directive order applied:
- The witness `forward_auth` (it has a matcher) ran **before** the sign-in `forward_auth`. The witness
  received no `X-Auth-Request-*` headers, so it had no verified person.
- `request_header -X-AISC-Request-Id` ran **after** both `forward_auth`s. It deleted the id the
  witness had just copied in, and the app got no id at all.

`caddy adapt` raised no warning. The snippet must wrap its directives in `route { }`. A Caddy test
has to assert that, because the text of the snippet reads correctly either way.

### G8. The fixed snippet works (`Caddyfile.v1c`)

```caddyfile
(protect) {
  route {
    request_header -X-AISC-Request-Id
    request_header -X-AISC-App
    request_header -X-AISC-Gateway
    request_header -X-AISC-Original-Uri
    request_header -X-Auth-Request-*
    forward_auth auth:4180 {
      uri /oauth2/auth
      copy_headers X-Auth-Request-User X-Auth-Request-Email X-Auth-Request-Preferred-Username
      copy_headers X-Auth-Request-Access-Token
      @unauth status 401
      handle_response @unauth {
        redir * /oauth2/start?rd={http.request.uri}
      }
    }
    @witnessed_{args[0]} {
      not method GET HEAD OPTIONS
    }
    forward_auth @witnessed_{args[0]} platform:8000 {
      uri /authz/witness
      header_up X-AISC-App {args[0]}
      header_up X-AISC-Original-Uri {http.request.orig_uri}
      header_up X-AISC-Gateway {$AISC_WITNESS_GATEWAY_SECRET}
      copy_headers X-AISC-Request-Id
    }
  }
}
```

Each handle imports it with its app: `import protect control_objectives`. Observed:

| Check | Result |
|---|---|
| Order | sign-in first; the witness got alice's token |
| App name | `X-AISC-App` set per handle (`control_objectives`, `engine`, `platform`, `dashboard`, ...) |
| Original URI | `/control-objectives/p/PID123/api/projects/a1/ratings`, unstripped |
| Forged `X-AISC-App: platform`, `X-AISC-Gateway: guess` | the witness got the real values; the app got neither (stripped) |
| Forged `X-AISC-Request-Id` on a write | the app got the witness's id |
| Forged `X-AISC-Request-Id` on a read | the app got no id (stripped; the witness isn't called on reads) |
| Forged `X-Auth-Request-Preferred-Username` | stripped by the wildcard |
| Client `X-AISC-Project` (the engine needs it) | kept, and the witness sees it |
| The gateway secret | reaches the witness only, never an app |
| Launcher `/api/authz/*` | 404 (a new `handle /api/authz/* { respond 404 }`) |
| Named matchers | `@witnessed_launcher` imported twice in one site: no conflict |
| Not signed in | 302 to `/oauth2/start` before the witness is asked |

### G9. Failure behaviour (review 1.11: confirmed for v0, fixed by the matcher)

| Situation | v0 (witness on every request) | v1c (writes only) |
|---|---|---|
| Witness answers 401 | 401 to the browser, no redirect | the same, on writes only |
| Witness answers 503 | 503 | the same, on writes only |
| Witness takes 1.5 s | every asset takes 1.5 s longer | only writes |
| Platform container stopped | **502 on a static JS chunk** | GET 200, POST 502 |

### G10. `forward_auth` passes the client's query string to the witness (new; review 1.16)

`POST /qualification/p/mcas/qualify/new?token=abc` reached the platform as
`GET /authz/witness?token=abc`, and `X-Forwarded-Uri` and `X-AISC-Original-Uri` carried the query too.
The witness must ignore its own query, and record only the path plus a keyed fingerprint of the query.

### G11. App-to-app calls carry the person's token, not a witness (review 1.6: confirmed from code)

`apps/qualification/src/server/services/PlatformClient.ts` calls `PLATFORM_URL` (inside the network)
with `Authorization: Bearer <the person's token>` for `POST /projects/{p}/system-versions` and
`POST /projects/{p}/targets/sync`. It has no service account and forwards no request id. The platform
can verify that token itself. It can't know that the person's browser made a matching request just
now, unless qualification forwards the witness's id.

## What immudb does (observed)

| # | Check (immudb 1.11.1, immudb-py 1.5.0) | Result |
|---|---|---|
| M1 | user `aisc_ledger` with RW on `ledgera` creates a database | refused: "loggedin user does not have permissions for this operation" |
| M2 | user with ADMIN on `ledgera` creates a database | refused, same message |
| M3 | ADMIN on `ledgera` grants RW on `ledgerd` | refused: "you do not have permission on this database" |
| M4 | RW user grants itself ADMIN | refused: "changing your own permissions is not allowed" |
| M5 | RW user unloads `ledgera` | refused: "you do not have admin permission" |
| M6 | RW user: `verifiedSet`/`verifiedGet`, SQL CREATE TABLE, INSERT, SELECT | all work at first |
| M7 | a grant made after the user logged in | `useDatabase` gives "Please login"; a new login works |
| M8 | after the superuser changed this user's rights on **another** database | SQL INSERT in `ledgera` refused ("statement requires [INSERT] privileges"), even after a fresh login; key-value `verifiedSet` still works. Cause not found |
| M9 | **one client, two threads, `useDatabase` then `set`, 300 each** | **54 of 299 entries in `ledgerx` and 55 of 301 in `ledgery` belong to the other database. Not one error** |
| M10 | 256 KiB and 5 MiB values with `verifiedSet` | both stored |
| M11 | `PersistentRootService` | one pickle for every database. The keys are inconsistent (`"127.0.0.1:13322/b'ledgery'"` and `b'ledgerx'`), and include the server address |
| M12 | a database deleted by the superuser, then recreated under the same name | the delete works; the recreate fails ("tbtree: key not found: while loading database settings") |
| M13 | client with a saved state at tx 10, server restored to an older copy (tx 3), same address | `verifiedGet` fails with gRPC `INVALID_ARGUMENT "illegal state"`, an error easy to take for "immudb down" |
| M14 | the same, server holding a different longer history (12 tx) | `ErrCorruptedData` |
| M15 | a client with no saved state, either case | accepts whatever the server holds |
| M16 | write latency, 600-byte values, 200 writes | `set` median 29.2 ms (p95 34.5), `verifiedSet` median 29.5 ms (p95 31.9) |

Not tested: the server signing key (`--signingKey`) with a client `publicKeyFile`; immudb's own
backup tooling.

## What changes in the design

| Finding | Consequence for spec v2 |
|---|---|
| G1, G8 | The app comes from `X-AISC-App`, set per handle, never from the path. The project comes from `X-AISC-Original-Uri` (per app rule) or `X-AISC-Project` (engine). |
| G2, G8 | The witness requires `X-AISC-Gateway`. The launcher blocks `/api/authz/*`. |
| G3, G7, G8 | `protect` is wrapped in `route`, and strips the identity headers first. The Caddy test asserts both. Today's gateway gets the strip even with the ledger off. |
| G4 | Apps never read `X-Forwarded-*` or `X-AISC-*` except `X-AISC-Request-Id` and `X-AISC-Project`. |
| G5 | One token rule: if both tokens are present, their subjects must match, or the witness refuses. |
| G6 | A server action is bound by (page, action id). Function names are not available, so the relay learns each id's event action on first use and alarms on a second, different one. The claim is narrowed accordingly. |
| G9 | Only writes are witnessed (the matcher). Reads that matter (downloads, exports) are listed per app in the matcher, so they fail when the platform is down, and W2 says so. Page views leave the witness (beacon, best effort). |
| G10 | The witness ignores its query, records the path, and keeps an HMAC of the query. |
| G11 | App-to-app writes carry the person's token and the forwarded `X-AISC-Request-Id`. The platform checks that the witness's subject is the token's subject and that the action's `caused_by` names the witnessed app and route. |
| M1-M5, M7 | Database creation is a separate step holding the superuser credentials (at project creation, or a pre-created pool). The relay runs as `aisc_ledger`, RW only. A new grant means a new login. |
| M8 | The ledger uses the key-value API (`verifiedSet`/`verifiedGet` and a sequence key), not SQL. |
| M9 | One client per project database, each with its own lock. Never `useDatabase` on a shared client. |
| M10 | Content limit set by the ledger, not by immudb: 64 KiB per entry; larger content goes to the evidence store with its digest in the entry. |
| M11, M13-M15 | The platform keeps each database's verified state in Postgres (compare-and-set), keyed by database name, not by address. `illegal state` and `ErrCorruptedData` are both tamper alarms, never "unavailable". A restore needs an admin-signed re-anchor event. Each project's head is published periodically to the object-locked evidence bucket. |
| M12 | A project's ledger database is never deleted (D2), and a deleted name is never reused. |
| M16 | About 30 ms per write. The witness writes to Postgres (`ledger.witness`, platform DB) in the request; the relay copies it to immudb. A write then doesn't wait on immudb, and immudb down never blocks the app. |

## Clean-up

```bash
docker rm -f $(docker ps -aq -f name=aisc-t-spike-); docker network rm aisc-t-spike
```

## Addendum: settled while writing the tests

- **S1** (`{args[1:]}` in a snippet matcher), on caddy:2.10.2: it expands to several paths, and
  `{args[0:]}` passes through a nested import. With **no** extra arguments, the matcher becomes
  `"path": null`. `caddy adapt` accepts it; `caddy run` refuses to load ("module value cannot be
  null"). So read paths need their own snippet (`protect-reads`).
- A refused page load can't be told apart in Caddy: `handle_response` matchers see the auth
  server's response headers, not the request's. The witness answers a refused `Sec-Fetch-Dest:
  document` request with a 302 itself, and forward_auth passes it through.
- `spike/Caddyfile.reference` implements spec v2 section 3.1. The real-Caddy suite passes on it
  (30 of 30, `LEDGER_TESTS_REQUIRED=1`), and fails on today's Caddyfile.
