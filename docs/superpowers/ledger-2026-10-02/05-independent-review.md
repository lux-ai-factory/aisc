# Ledger: independent review of the design and the tests written first (2026-10-02)

Reviewer: fresh context, read-only. Base: `feat/unified-modules` at 0819c5f. Read: 01-plan, 02-spec,
03-coding-plan, 04-test-plan, the event registry, every file under `platform/tests/ledger/`,
`scripts/tests/test_ledger_{coverage,caddy}.py` and the exception fixture, then checked the claims
against the Caddyfile, `platform/platform_service/{app,db,projectdb,engine_components,targets}.py`,
`shared/identity`, `platform/project-template/*.sql`, `init/platform-db.sql`, the compose files, the
engine's `project_door.py` and `config/urls.py`, the Next.js apps' server actions and clients, the
dashboard's `aisc_ext`, the eval worker, and the installed immudb-py 1.5.0 source.
What I ran: the coverage discovery function, standalone, to list what it finds; the repo-level ledger
tests (4 fail for the expected reason, 4 pass); and test collection on `platform/tests/ledger` (it
fails only because `platform_service.ledger` does not exist yet, which is the right red reason).
Nothing touched the running stack or the live database.

Statements about Caddy's forward_auth internals and immudb's permission rules come from my knowledge
of their source, not from running them. They are marked **(verify)**, and finding 6.1 proposes the
spike that settles them.

## Verdict

The direction is right. A component the apps can't influence should verify the token and name the
actor, and the relay should copy the actor rather than trust the app. But as written the design
does not deliver "who is never taken from an app's word", and three of its load-bearing assumptions
contradict the code and the gateway as they are:

1. The witness can't tell the app or the project from the path. Caddy strips prefixes before
   forward_auth runs, and two apps share `/api/*` on different listeners.
2. Much of the real write traffic is server to server (qualification to the platform, the platform
   to the engine and the dashboard). It never passes Caddy, so in `enforce` it is refused, or
   rejected by the relay as `app_mismatch`.
3. Any signed-in browser, and anything on the internal network, can call `/authz/witness` itself
   with X-Forwarded-* headers it chose.

Within one app, the binding between an event and "its" request is a shape match: same app, a path
regex, 5 minutes, a count. That match is the app's word in another form. So the core claim should be
narrowed: "the actor is always a person who made a matching witnessed request". The tests are mostly
well aimed, and the RFC 8785 vectors are correct. Some tests are impossible to satisfy (the shared
immudb databases, the exception parser), one pins the wrong semantics (the stale window), and the
riskiest behaviour (real Caddy) has no executable test at all.

**Counts: 3 blocker, 30 major, 29 minor (62 findings; 5.3 is a coverage summary, not a finding).**

## Top 5 findings

1. **(blocker, 1.1)** Caddy hands the witness the *stripped* URI under `handle_path`, and `/api/*`
   means the engine on one listener and the platform on another. The spec's rule "app and project
   from the path" can't work, and the witness tests use URIs Caddy never sends.
2. **(blocker, 1.6)** The apps call each other's write routes server to server: qualification calls
   platform `POST /projects/{p}/system-versions` and `/targets/sync`, the platform calls engine
   components and the dashboard bridge. In `enforce` these are refused for lack of a request id. If
   they forward one, the relay rejects them as `app_mismatch`. Step 1 card creation breaks.
3. **(blocker, 1.2)** `/authz/witness` is publicly reachable at `https://<launcher>/api/authz/witness`
   (the launcher's `handle_path /api/*` goes to the platform) and from every container. The caller
   sets X-Forwarded-Method and X-Forwarded-Uri itself, so it can mint witness entries for any path and
   any project (including ones it isn't a member of), spam `page.opened`, and make the platform
   create an immudb database for every random pid it puts in a path.
4. **(major, 1.11 and 6.4)** In the `protect` snippet, every request (every JS chunk, image and API
   read) calls the witness, and a witnessed request is written to immudb synchronously. So W2 ("reads
   still work") is false: a platform or immudb outage takes down every page in every mode, including
   `off` from the day phase 2 is deployed.
5. **(major, 1.7 and 1.8)** The binding is weak where it matters. A Next.js server action POSTs to the
   page URL with its ids in the body, and forward_auth carries no body. So any action on a page can
   cite any POST to that page, and an app can swap two concurrent users' ids. An AI or worker event
   is checked only by the cited request's path, with no start event, no run id and no time bound: an
   AI service can attribute work to anyone who ever opened the refine flow.

---

## 1. Soundness of the identity design

**1.1 (blocker) The witness can't derive the app or the project from X-Forwarded-Uri.**
Evidence: forward_auth sets `X-Forwarded-Uri: {http.request.uri}`, the URI *after* earlier rewrites
**(verify)**. `handle_path` strips its prefix before the `import protect` inside it runs:
`Caddyfile:109-114` (`/control-objectives*`), `118-123` (`/report-composer*`), `162-165` (launcher
`/api/*`). The current code already hedges on this (`app.py:246-247`, "with or without the
/inspect/schema prefix it strips"). So the witness sees `/p/{pid}/api/projects/...` for control
objectives, `/p/{slug}/layouts` for the composer and `/projects/...` for the launcher API. The CO and
composer forms look alike. And `/api/*` is the engine on the main listener (`Caddyfile:76-81`) but
the platform on the launcher (`162-165`). Spec 4.5 maps only by path prefix. The tests send
unstripped URIs (`test_ledger_witness.py:20-21, 94-106`; `test_ledger_platform_events.py:23`;
`test_ledger_beacon.py:22`) and always `host=localhost` (`conftest.py:65-72`), so they would pass an
implementation that can never work behind the real Caddy.
Fix (spec, Caddyfile, tests): make `protect` take the app as an argument
(`import protect control_objectives`). In its witness forward_auth, set
`header_up X-AISC-App {args[0]}` and `header_up X-AISC-Original-Uri {http.request.orig_uri}`. The
witness takes the app only from X-AISC-App, and the project from the original URI or X-AISC-Project
(1.10). Witness tests send these headers. The Caddy test asserts that every `import protect` names
an app from `KNOWN_APPS`.

**1.2 (blocker) The witness endpoint is callable by anyone, with headers they choose.**
Evidence: the launcher's `handle_path /api/* { import protect; reverse_proxy platform:8000 }`
(`Caddyfile:162-165`) serves `/api/authz/witness` to any signed-in browser. Caddy's reverse_proxy
overwrites X-Forwarded-For, Proto and Host, but passes X-Forwarded-Method and X-Forwarded-Uri from
the client unchanged **(verify)**. `platform:8000` is also reachable from every container on the
`backend` network. Consequences:
- Anyone can mint `request.witnessed` and `page.opened` entries in any project's log under their own
  name, for paths they never requested and projects they don't belong to (an I9-style pollution).
- The platform creates immudb databases for random pids, since `ensure(db)` is implied by a
  witnessed path: an unbounded disk and goroutine DoS.
- Anyone can obtain fresh valid request ids for 1.3.

Nothing in the tests calls the witness the way an attacker would.
Fix: the witness requires a gateway secret that only Caddy sets
(`header_up X-AISC-Gateway {env.AISC_WITNESS_GATEWAY_SECRET}`, compared in constant time). The
launcher blocks `/api/authz/*` as it blocks `/api/internal/*` (`Caddyfile:157-159`). A pid in a path
is used only if `db.get_project(pid)` exists (otherwise the platform log, never a new database).
Decide whether a non-member's request is recorded in the project log at all. Tests: no gateway
secret gives 401; an unknown pid creates no database; a stranger's witness goes to the platform log.

**1.3 (major) A client-supplied `X-AISC-Request-Id` reaches the app whenever the witness returns no id.**
Evidence: forward_auth's `copy_headers` sets the request header only when the auth response carries
it, and otherwise leaves the client's header in place **(verify on caddy:2.10.2)**. `protect` strips
nothing (`Caddyfile:12-24`). The witness returns 200 *without* an id for non-document GETs (spec
4.1: `None` when no witness is needed; `test_ledger_witness.py:86-91`), and in `off` mode. The
"reads that matter" (downloads, exports, report viewed: plan 5) are exactly such GETs. Request ids
are shown to every member ("the request it came from", plan 10). So a member can replay a
colleague's recent id on a GET download and have the event attributed to that colleague.
Fix: the first line of `protect` is `request_header -X-AISC-Request-Id`, plus the other identity
headers (`-X-Auth-Request-*`). The Caddy test asserts the strip. A drill with curl and a forged
header confirms the upstream sees none. Alternatively, the witness issues an id for every request it
lets through.

**1.4 (major) The witness and the apps read different tokens when both are present.**
Evidence: spec 4.3 reads `X-Auth-Request-Access-Token`, else `Authorization`. The shared library
does the opposite: `shared/identity/aisc_identity/headers.py:16-25` takes Bearer first, and so do
`apps/qualification/src/server/services/callerToken.ts:24-30` and the engine's `bearer_from_gateway`.
Say a browser SPA still holds a keycloak-js token for user A after the gateway session became user B,
or a script sends its own Bearer through the gateway. The app acts as A while the witness records B.
Fix: one precedence, in one function, used by both. If both tokens are present and their subjects
differ, the witness answers 401 in `enforce` and `request.unverified` in `record`. Add a test.

**1.5 (minor) The platform doesn't bind a presented request id to the presenter.**
Evidence: spec 3 says the platform "checks that the id is one it issued". The tests
(`test_ledger_platform_events.py:17-26`, `test_ledger_beacon.py:18-23`) never present OWNER's id with
MEMBER's token. Through Caddy the two travel together, but from the internal network they don't.
Fix: the platform checks the witness's subject, method and path against the caller and route. Add a
test with a mismatched id.

**1.6 (blocker) Server-to-server writes have no witness of their own and the wrong app on the cited one.**
Evidence:
- `qualify/new/actions.ts` calls `PlatformClient.createVersion` and `syncTargets` (`PlatformClient.ts:91-105`):
  platform POSTs straight to `PLATFORM_URL`.
- The platform calls the engine (`engine_components.py:27`) and the dashboard
  (`dashboard_bridge.py:38`).
- The registry itself says `card_version.created` is "user (via step 1)".
- In `enforce`, the platform refuses writes that carry no id (spec 3;
  `test_ledger_platform_events.py:59-63`).
- If qualification forwards its own id, the witness says app=qualification on a qualification path,
  while the event's `db_role` is `platform_rw`, so the relay says `app_mismatch` or
  `path_not_allowed` (spec T2; `test_ledger_relay.py:86-87`).

`test_a_card_version_is_recorded` sidesteps this by witnessing `/api/projects/...` directly, which
is not how the card is saved.
Fix (spec and tests): model "caused by". An action declares `caused_by: [(app, METHOD, regex)]` for
the originating gateway request, separate from `apps` (who may emit it). Downstream calls forward
`X-AISC-Request-Id`. The relay accepts an event whose cited request's app is in `caused_by` and whose
emitter is in `apps`. Defence in depth accepts a forwarded id only from a service-token caller. Tests:
a qualification-witnessed submit makes the platform's `card_version.created` count; a CO-witnessed
request does not.

**1.7 (major) Within one app, an event is bound to its request by shape only.**
Evidence: the relay checks app, path regex, a 5-minute window and `per_request` (spec T2-T4). T2's
"the event must name an item that appears in the request path **or body digest**" is infeasible,
because forward_auth sends the witness no body; no test checks the item at all. Every Next.js server
action POSTs to the page URL with its ids in arguments (`fill-actions.ts:21`
`rerunFill(project, qualificationId)`; the 26 actions listed by discovery). So on one page any action
can cite any POST, and the path tells nothing about which item changed. A buggy or compromised app
can swap the ids of two concurrent users of the same route. Each swap passes every check unless the
`per_request` limit happens to collide.
Fix:
- Narrow the claim in 01-plan section 3 and spec I2 to "the actor is a person whose witnessed request
  matches the event's app, route, item (when the path names it) and time", and say what's left over.
- The witness records the `Next-Action` header (forward_auth forwards request headers) and the
  registry maps server-action ids from `.next/server/server-reference-manifest.json` at build time.
- Bind the item when the path carries it.
- Add reconciliation alarms for a request with events from unrelated actions.
- Tests: an s2 event citing an s1 request is rejected; an action id that doesn't match is rejected.

**1.8 (major) AI and worker "starts" is a path check with no correlation and no time limit.**
Evidence: `test_ledger_internal.py:36-48` accepts `card.augmented_by_ai` citing a witnessed POST to
`/qualification/p/{pid}/qualify/q1`. No `card.ai_refinement_requested` event exists and there is no
run id. W3 exempts AI from the window. So an AI service can name as `on_behalf_of` anyone who ever
POSTed to that page, at any later time. `test_..._citing_a_request_that_does_not_start_it` only shows
that a *different app's* path is refused.
Fix: the start event carries a `run_id`. AI and worker events cite `(request_id, run_id)`. The relay
requires an accepted start event with that run id from that request, a bounded run window (for
example 24 h, set per action) and per-run limits. Add a test with no start event.

**1.9 (major) Third-party plugin code inherits the worker's environment, and so would the ledger token.**
Evidence: `apps/eval/aisc_eval/celery_tasks.py:402-417` runs plugins with
`child_env = os.environ.copy()`. If the worker holds `PLATFORM_LEDGER_ENGINE_TOKEN` (or a worker
token) for phase 8, any installed plugin can post forged `engine.*` or worker events citing its own
run's request. No threat in spec section 2 covers this.
Fix: add T17 "untrusted code holds ledger credentials". Strip `PLATFORM_LEDGER_*` and the internal
secret from `child_env` (or post through a separate sidecar). Add a test that the child env has no
ledger token.

**1.10 (major) For several apps the project isn't in the path, or the app isn't behind this gateway.**
Evidence:
- The engine names its project in the `X-AISC-Project` header (`project_door.py:3-5`), and its routes
  are `/api/v1/components/{component_pid}` and similar.
- Superset URLs carry no pid.
- The controls install entry `src/app/install/actions.ts` sits outside `/p/[project]`.
- The catalogue is the hosted one, "no catalogue runs in this stack"
  (`docker-compose.development.yml:251-259, 901-904`), so its writes never pass this Caddy. Yet the
  spec has a `PLATFORM_LEDGER_CATALOGUE_TOKEN`, and the coverage test scans `apps/catalogue/backend`.

All such requests land in the platform log, and every project event citing them is rejected as
`project_mismatch`.
Fix: the witness reads X-AISC-Project for the engine. For the dashboard, either a resolver from
dashboard or chart to project (the bridge table) or a rule that dashboard events may cite a
platform-log request. Scope the catalogue out: it keeps its own log, and only the local
`plugin.installed` and `control.installed` are in scope. Add a witness test per app.

**1.11 (major) The witness runs on every request, and that breaks W2.**
Evidence: `protect` is imported by every handle. The spec has the witness decide (`witness()`
returns `None` for a non-document GET; `test_ledger_witness.py:86-91` sends one), so Caddy calls the
platform for every chunk, image and API read. When the platform is down, the forward_auth upstream
fails and *every* request fails, reads included, and in `off` mode too. 01-plan W2 says "Reads still
work". There are also one or two extra synchronous calls per request on a single uvicorn process
(`platform/Dockerfile:15`).
Fix: restrict the witness with a matcher in the snippet (`forward_auth @witnessed platform:8000`,
where `@witnessed` = `not method GET HEAD OPTIONS` or `header Sec-Fetch-Dest document`). Switch it
off in Caddy for `off` (an env-selected snippet). Restate W2 honestly: page loads fail when the
platform is down. Note that the Caddy test (`test_ledger_caddy.py:153`, `startswith("forward_auth
platform:8000")`) would reject the matcher form.

**1.12 (major) Tokens at the edge of expiry will produce 401s on writes in `enforce`.**
Evidence: Keycloak `accessTokenLifespan` is 300 (`keycloak/aisc-realm.json`); oauth2-proxy has
`--cookie-refresh=5m` (`docker-compose-infra.development.yml:208`). So a token can reach the witness
seconds before it expires. `tokens.py:38-47` verifies `exp` with no leeway. A witness 401 is not the
oauth2 `@unauth` case Caddy redirects (`Caddyfile:19-22`), so the user's POST or server action just
fails.
Fix: refresh before the lifespan (4 min) or lengthen the lifespan, add 30 s leeway in the witness,
handle the witness's 401 in Caddy (redirect for documents). Add a drill for the boundary.

**1.13 (minor) `page.opened` from Sec-Fetch-Dest misses most views and can be forged.**
Evidence: Next.js client navigations are RSC fetches, the engine is an SPA, and Superset embeds use
`iframe`, so none of them is `document`. The header is client-set.
Fix: say page views are best-effort. Count RSC navigations (`RSC: 1`) or use the beacon, and mark
these `reported_by=browser`.

**1.14 (minor) Gateway paths with writes but no events.**
Evidence: Flower (`Caddyfile:84-89`, task revoke) and pgAdmin (`177-181`, arbitrary SQL by admins)
are witnessed but in no registry, so reconciliation will flag them as witnessed writes with no event,
and pgAdmin edits will surface only as "changed outside the app".
Fix: registry entries (`flower.request`, `pgadmin.request`), or read-only pgAdmin.

**1.15 (minor) The audience claim in T5 isn't what the code does.**
Evidence: `tokens.py:43-46` deliberately sets `verify_aud: False`.
Fix: for the witness, require `azp == aisc-gateway` (the only client whose token oauth2-proxy
forwards), or delete "audience" from T5. Add a test with a token from another client.

**1.16 (minor) The query string goes into the log.**
Evidence: X-Forwarded-Uri includes the query; the test asserts `details["path"]` equals the full URI
(`test_ledger_witness.py:35`). Tokens or codes in query strings would land in immudb, against I8.
Fix: record the path, plus a fingerprint of the query. Add a test with `?token=`.

## 2. Completeness of invariants and threats

**2.1 (major) `occurred_at` can be set by the app.**
Evidence: spec 4.4 has `occurred_at timestamptz default now()`, and the trigger stamps only
`db_role`. An app that inserts an explicit `occurred_at` fits any old request inside the window,
which defeats T3 and T14.
Fix: the trigger also sets `occurred_at := clock_timestamp()`. Add a test in `test_ledger_outbox.py`.

**2.2 (major) The stale-window test pins the wrong clock.**
Evidence: `test_ledger_relay.py:101-107` makes a row stale by running the relay with `now` 6 minutes
later. T14 says the window is witness time against outbox `occurred_at`. With the test's semantics,
any relay backlog over 5 minutes (immudb down, the phase 3 drill) turns legitimate events into
`stale_request`, which violates I6.
Fix: window = `occurred_at - witness.at`. Tests: a row inserted 10 s after its witness and relayed
1 h later is accepted; a row whose `occurred_at` is 6 min after the witness is stale.

**2.3 (minor) A reused `event_id` silently drops the second event.**
Evidence: store `append` returns the first seq for a known `event_id` (spec 4.1;
`test_ledger_store.py:30-35` uses identical content). A buggy emitter that reuses ids, or a row
replayed with changed content, loses an event without an alarm.
Fix: idempotency on `(event_id, content digest)`. Same id with different content gives
`ledger.rejected (duplicate_event_id)` and an alarm. Add the test.

**2.4 (major) The platform's own events have no transactional outbox.**
Evidence:
- Members and projects live in the shared `platform` database (`db.py:393-432` uses `pool()` on
  `PLATFORM_DATABASE_URL`); the outbox exists only in the project template (spec 4.4).
- Project delete runs `DROP DATABASE ... WITH (FORCE)` (`projectdb.py:96-100`), destroying
  undelivered outbox rows. That breaks I3 and I6, and D2 ("log kept after delete") can't hold for
  the last events.
- `test_member_changes_are_recorded...` expects member events in the project ledger after
  `relay_once(pid)` without saying where they were queued.

Fix: `core.outbox` in the platform DB, in the same transaction as membership and project changes,
relayed into the right project ledger. A delete drains the project's outbox (or refuses until it is
empty) before the drop. Tests: a member change rolled back leaves no event; undelivered rows survive
a delete.

**2.5 (major) No privacy invariant, though the log holds identities and page views for ten years.**
Evidence: every witnessed request and page view stores subject and name in immudb under D4's 10-year
lock. D1 lets every member browse colleagues' activity (that is workplace monitoring). Hashes of
low-entropy personal data (an answer "yes", a short comment) can be reversed by dictionary. D5 can
erase the evidence copy but not names in witness entries.
Fix:
- Add I10 (minimisation and erasure).
- Use pseudonymous actor ids in immudb (a per-project HMAC of `sub`, with the mapping in Postgres;
  erasing the mapping is crypto-shredding).
- Use keyed hashes (HMAC per project) for content digests.
- Keep page views out of immudb, with retention (as D6 already does for Superset).
- Do a DPIA, and revisit D1 for per-person activity.

**2.6 (major) No invariant ties events to each other (ordering and gaps).**
Evidence: nothing requires an item's `before_sha256` to equal the previous event's `after_sha256`.
A missing or reordered event is invisible until phase 10's reconciliation.
Fix: add I11 (an unbroken item chain). The relay records a break as an alarm, and the verifier
checks it. Start the "witnessed write with no event" reconciliation in phase 3, since the data exists
from phase 2.

**2.7 (major) Concurrency, and more than one platform worker, are not covered.**
Evidence:
- immudb-py keeps one current database per client (`useDatabase`) and one RootService. FastAPI runs
  sync handlers in a threadpool, so a shared client switching databases can append into another
  project's database, which breaks I9.
- `PersistentRootService` pickles every state into one file and is "not thread/process safe"
  (`immudb/rootService.py:79-85`).
- Two relays, or two uvicorn workers, race the `per_request` count and the state file.

Fix: one client per database with a lock, or a pool keyed by database. Keep the verified state in
Postgres with compare-and-set. Take a per-project advisory lock in the relay. Add a concurrency test:
two threads, two databases, 1,000 appends, no entry in the wrong one.

**2.8 (minor) LISTEN/NOTIFY doesn't cross databases.**
Evidence: the 09-30 plan section 7.1 (inherited here) wakes the relay with LISTEN/NOTIFY, but that
needs one listening connection per project database.
Fix: poll with backoff, with a connection budget stated in the spec.

**2.9 (major) Backup, restore and key rotation aren't covered.**
Evidence: there's no threat or runbook for these.
- Restoring immudb from a backup makes the persisted state "from the future": a permanent
  `TamperAlarm` with no recovery path.
- Restoring a project's Postgres rewinds `delivered` and `witness_index`.
- A Keycloak signing-key rotation, with a stale JWKS cache, gives a 401 storm in `enforce`.
- Nothing covers rotating `aisc_ledger`, the `PLATFORM_LEDGER_*` tokens, or immudb's server signing
  key.

Fix: add threats T18-T21, an operator "re-anchor after restore" event signed off by an admin, JWKS
refresh on an unknown `kid`, rotation with an overlap window, and drills.

**2.10 (major) The immudb superuser can delete a whole log without detection.**
Evidence: the superuser stays (the dashboard uses immudb today; `docker-compose-infra.development.yml:260-276`)
and can delete or unload databases. The platform's state file sits on the same host. T11 assumes that
state survives. External anchoring is out of scope.
Fix: state the residual risk. Publish each project's head periodically to the object-locked
`evidence` bucket (cheap anchoring with what's already planned). Keep an expected-databases list in
Postgres, and alarm on a missing database.

**2.11 (minor) Large content limits are unstated.**
Evidence: immudb-py's default gRPC receive limit is 4 MB (`client.py:48-72`). immudb SQL has row and
VARCHAR limits. jsonb refuses `\u0000` and keeps integers beyond 2^53 exactly, which the TypeScript
twin can't.
Fix: write the limits into the spec. Test a 256 KiB round trip on immudb. Canonical JSON refuses
integers beyond 2^53.

**2.12 (minor) The registry can't evolve safely.**
Evidence: entries carry no registry version. An app deployed before the platform will see its new
actions rejected.
Fix: add `registry_version` to entries. An unknown action from a newer app is held and retried, not
rejected. Rule: the platform deploys first.

**2.13 (minor) I5 has no baseline.**
Evidence: rows that predate the ledger, and data migrations, all look like "changed outside the
app".
Fix: a genesis snapshot event per evidence table in each app's phase, and migrations emit a
`system` event with digests before and after.

**2.14 (minor) Mode transitions and record-mode events are unspecified.**
Evidence: the spec doesn't say what actor an event gets when it cites a `request.unverified`, or how
events behave across the off, record and enforce switches.
Fix: specify both, and add a rollout order (Caddy plus witness in `record`, then emitters, then
`enforce`).

## 3. Feasibility against the real code

**3.1 (major) A non-superuser immudb user probably can't create databases.**
Evidence: immudb's `CreateDatabaseV2` requires a sysadmin, and granting a user permissions on a new
database requires sysadmin or that database's admin **(verify on 1.11.1)**. So `ensure(db)` for each
new project needs the superuser, against plan section 6. The store tests log in as `immudb`
(`conftest.py:43`, `test_ledger_store.py:96`), which hides this.
Fix: create databases in a separate step at project creation that holds the superuser credentials
(or pre-create a pool). Run the store tests as `aisc_ledger`.

**3.2 (minor) The test plan uses a different immudb than the stack.**
Evidence: the test plan uses `codenotary/immudb:1.9.5` (04-test-plan.md:9); the stack runs `1.11.1`
(`docker-compose-infra.development.yml:264`).
Fix: one pin.

**3.3 (major) An INSERT-only outbox breaks the apps' ORMs.**
Evidence: qualification and controls use Prisma 5 (`package.json`), whose `create()` always does
`INSERT ... RETURNING`. CO uses SQLAlchemy, whose ORM inserts use RETURNING for server defaults.
RETURNING needs SELECT, so the business transaction fails with a permission error.
Fix: the spec says emitters use a plain INSERT without RETURNING (Prisma `$executeRaw` inside
`$transaction`; SQLAlchemy Core). Test each app's emitter against the real grant in phases 5-9.

**3.4 (minor) The state-from-the-future test pins a file format.**
Evidence: it expects one JSON file per database, a name prefix and a `txId` key
(`test_ledger_store.py:100-103`). immudb-py's own persistence is one pickle for all databases.
Fix: the store exposes `state(db)` and `set_state(db, s)` test hooks, or the test rolls the server
back with a real backup and restore.

**3.5 (minor) The documents contradict each other in several places.**
Evidence:
- The witness is `POST` in 01-plan section 7 but `GET` in spec 4.3; forward_auth always sends GET.
- The beacon is `/p/{slug}/ledger/beacon` in the plan, which the launcher's `/p/*` file_server would
  swallow (`Caddyfile:169-174`), and `/projects/{slug}/...` in the spec.
- The database name is `ledger_<hex>` in the plan and `ledger<hex>` in the spec.
- `delivered` is in `core` in spec 4.4 but `ledger.delivered` in `test_ledger_outbox.py:61`.
- The test file names in 04-test-plan don't match the real ones.
- The registry document says `agent.llm_call`, the tests `ai.llm_call`.
- T13 says "replaced by fingerprint"; `check` reports a `secret_in` problem.

Fix: one consistency pass.

**3.6 (minor) The beacon can't be shared across origins as planned.**
Evidence: the main site, the launcher and the dashboard are three origins (three ports), and
`sendBeacon` with `application/json` isn't CORS-safelisted.
Fix: a beacon route on every site, and a `text/plain` body.

**3.7 (minor) The repo-level test imports the registry without the platform's dependencies.**
Evidence: `uvx --with pyyaml pytest` with `platform/` on the path (`test_ledger_coverage.py:17,80`).
Fix: the spec says `platform_service/ledger/__init__.py` and `registry.py` import only the standard
library.

## 4. Test quality, file by file

**4.1 `test_ledger_canonical.py` (minor; the expectations are correct).**
I checked each one:
- UTF-16 ordering puts U+1F600 (D83D) before U+FB33.
- The RFC 8785 example output is byte-exact, including `\u000f`, the doubled backslashes and the
  unescaped `/`.
- `-0.0` gives `0`, `1e21` gives `1e+21`, `1e-7` gives `1e-7`, and `333333333.33333329` gives
  `333333333.3333333`.

Gaps: `True` vs `1` (bool subclasses int); integers beyond 2^53; lone surrogates refused; the short
escapes `\b \f \t \r`; U+007F left unescaped; the 1e-6 and 1e20 boundaries; Decimal and datetime
refused. The shared fixture file the TypeScript twin needs (phase 5) should exist now.

**4.2 `test_ledger_naming.py` (minor).**
It's sound. It accepts uppercase undashed pids, which `projects.PID` doesn't. Decide on purpose and
add the nil UUID.

**4.3 `test_ledger_registry.py` (minor).**
- `_event` pins details keys `impact` and `likelihood` for `risk.rated`, where the registry document
  says before and after: over-specified.
- `check(event)` gets no `source_app`, so it can never check `apps`.
- `actor_supplied` is tested only inside `details`.
- Content snapshots legitimately carry author fields (`reviewed_by`, plan 8.1), so the rule must not
  scan content.
- The "user action needs paths" rule forces placeholder paths on witness-born actions
  (`request.witnessed`, `page.opened`).

**4.4 `test_ledger_store.py` (major).**
The `immudb` parameter shares database names `A` and `B` across tests on a persistent server
(lines 11-12). `test_the_same_event_twice_is_recorded_once` (scan equals one id) and
`test_scan_is_in_order_and_paged` (after_seq=0) therefore fail once any earlier test has written to
`A`: they can't be satisfied. Use `"ledger" + uuid4().hex` per test, as the last test already does.
Tamper detection is tested only on `MemoryLedger.tamper`. Also missing: the concurrency test (2.7),
the same id with different content (2.3), and runs as `aisc_ledger` (3.1).

**4.5 `test_ledger_witness.py` (major).**
It's under-specified against the real gateway:
- unstripped URIs and a constant host (1.1);
- no engine or dashboard case (1.10);
- no caller without the gateway secret, no unknown or stranger project (1.2);
- no audience, `nbf` or leeway case (1.12, 1.15);
- no dual-token case (1.4);
- no query-string case (1.16).

Nor does it check that a document load returns an id that GET-born events can cite.

**4.6 `test_ledger_outbox.py` (minor).**
It's good as far as it goes. Missing:
- `occurred_at` forced by the trigger (2.1);
- module roles can't INSERT into `delivered` or `witness_index`, which would be a forged witness;
- no TRUNCATE;
- unlisted roles (`engine_rw`, `catalogue_rw`, `dashboard_ro`, `report_ro`, `inspector_ro`) can't
  insert;
- an insert through the real ORMs (3.3).

**4.7 `test_ledger_relay.py` (major).**
- The stale semantics are wrong (2.2).
- It pins the private `relay._mark_delivered`.
- Missing:
  - item binding (1.7);
  - an app emitting platform-only actions: an outbox row with `action='request.witnessed'` or
    `ledger.rejected` must be refused, and `check` doesn't look at `apps`;
  - rows committed out of order: a high-water mark on `occurred_at` or a random UUID loses a late
    commit;
  - two relays racing on `per_request`;
  - immudb down, where rows must stay pending rather than be rejected;
  - what actor a `ledger.rejected` entry carries.

**4.8 `test_ledger_platform_events.py` (minor).**
- Exact equality on `details` pins key names.
- It asserts the error text contains "witness".
- Paths use the `/api` prefix that Caddy strips (1.1).
- The card-version test sidesteps the real chain (1.6).
- A 12-hex unsalted fingerprint is 48 bits, guessable for low-entropy connection passwords; use an
  HMAC with a server key.

**4.9 `test_ledger_routes.py` (major).**
- It seeds the store directly, so listing must read immudb. That contradicts the read index (T12;
  the 09-30 plan section 9, `ledger.event_index`).
- A2's "an index row that disagrees with immudb is an alarm" has no test.
- The export test proves only that the file is self-consistent, which anyone can recompute after
  editing it.

Fix: immudb's server signing key and the client `verifying_key`, with inclusion proofs per entry in
the export, so the offline checker verifies against a signed state.

**4.10 `test_ledger_internal.py` (minor beyond 1.8).**
- There's no test that the agents token can't post `engine.*` actions (binding app to action).
- There's no project-mismatch test on the internal route.
- It answers 422 where I2 says the attempt is recorded as `ledger.rejected`.

**4.11 `test_ledger_beacon.py` (minor).**
It's fine. Missing: binding the presenter to the request (1.5), a rate limit, and the beacon on
every origin (3.6).

**4.12 `test_ledger_coverage.py`, false negatives (major).**
I ran `discovered()`:
- **Collisions.** Routes are relative to their router, so different routes collapse into one tuple.
  `('engine','POST','')` comes from several routers (project, evaluation, audit), and so do
  `('engine','PATCH','/{pid}')` and `('dashboard','POST','/')` (`comments/api.py:133` and
  `reviews/api.py:57`). One registry entry silently covers all of them.
- **Flask-AppBuilder views.** `ModelView` CRUD routes aren't decorated with `@expose`
  (`aisc_ext/comments/views.py:13`, `reviews/views.py:11`, the "admin edit views" of plan 8.2), so
  they're missed. Superset's own write APIs aren't considered at all.
- **Globs miss write routes.** `apps/qualification/services/agents/service.py:80`
  (`POST /fill/{pid}/{qualification_id}`, the AI run), `prefill`, `ontology/build`, `llm/generate`,
  `apps/connectors/aisc_connectors/routes_admin.py` (7 write routes, secrets included), and the
  controls PDF renderer.
- **GETs are never discovered.** So download and export events (`ai-card.pdf/route.ts` and others)
  can't be named, or C3 marks them stale.
- **Syntax gaps.** Single-quoted decorators, `api_route` or `add_api_route`,
  `export { h as POST }`, and `export const x = async` in "use server" files.

Fix: key routes by (app, file, function), or resolve mount prefixes (`config/urls.py:52-72`).
Discover GETs with a flag. Glob every app directory against an explicit ignore list.

**4.13 `test_ledger_coverage.py`, false positives and the exception parser (major).**
`spec, _, reason = line.partition("#")` (line 73) cuts server-action ids like
`.../ontology-actions.ts#loadOntology`. So the read-only server actions (`loadOntology`,
`readDocument`, `readQuestionSetFile`) and the POST-reads (engine `measurements/aggregate`, catalogue
`methods/filter`, renderer `/v1/render`) can't be listed as exceptions. C1 can't go green without
inventing events for them.
Fix: separate the reason with `" # "`, or use a TSV.

**4.14 C1 only proves a registry entry exists (major).**
A route counts as covered if any registry entry names it, whether or not the code emits anything. So
T16 has no real guard until phase 10.
Fix: a static check that each registered handler calls the emitter with that action, or a runtime
per-route test harness. Start witness-based reconciliation in phase 3 (2.6).

**4.15 `test_ledger_caddy.py` (minor).**
- `blocks()` also counts placeholder braces (`{$CADDY_DOMAIN}`, `{http.request.uri}`) as blocks.
  That's harmless today but fragile.
- Witness detection requires a header that starts with `forward_auth platform:8000`, which rejects
  the matcher form (1.11).
- It inspects only handles that contain `reverse_proxy`, not `file_server` handles or a site-level
  `reverse_proxy`.
- It doesn't check the header strip (1.3) or the per-handle app (1.1).
- The `UNPROTECTED` reason for `/api/v1/internal/*` is wrong: that handle answers 403, it isn't
  proxied.
- `test_every_proxied_handle...` already passes today, so it's a guard, not a phase 2 red test.

## 5. Gaps between invariants and tests

**5.1 (major) I1 has no executable test against a real Caddy.**
Only a text parse of the Caddyfile (C2) and unit calls that skip the gateway. Every gateway
assumption (1.1, 1.2, 1.3, 1.11) is untested.
Fix: a throwaway `caddy:2.10.2` with stub upstreams that echo the headers they receive (see 6.1).

**5.2 (major) I6 has no automated test in phases 1-4, only drills.**
Missing: platform down gives refused writes in `enforce` and marked ones in `record`; immudb down
keeps rows pending; the internal route queues instead of losing events.

**5.3 Coverage of each invariant and threat (status only; the fixes are in the findings cited).**
- **I2:** no test for a within-app swap, a chained call, or an app-emitted platform action (1.6,
  1.7, 4.7).
- **I3:** no test for out-of-order commits, the same id with different content, or deletion with
  undelivered rows (2.3, 2.4, 4.7).
- **I4:** tamper detection is tested on memory only; the export has no trust root (4.9).
- **I5:** phase 10 only, with no baseline (2.13).
- **I7:** declarative only (4.14).
- **I8:** the query string (1.16); secrets inside `content`, not only `details`; fingerprint
  strength (4.8).
- **I9:** no concurrency leak test, and strangers can pollute a log (2.7, 1.2).
- **T10:** phase 10.
- **T12:** untested (4.9).
- **T14:** untested, and contradicted by R2 (2.2).
- **T15:** untested.
- **T16:** untested until phase 10 (4.14).
- **T3 for AI:** path only (1.8).

## 6. Plan and process

**6.1 (major) The riskiest part is de-risked last, or never.**
The riskiest part is the gateway's real behaviour, plus server-to-server chains and Next.js server
actions. Phases 3-9 build on it, but no phase checks it end to end before the red-team in 4b.
Fix: a phase 1.5 spike, half a day:
- Run caddy:2.10.2 with this Caddyfile, a stub witness that logs every header and an echo upstream
  per handle.
- Assert, for each handle: the X-Forwarded-Uri seen (stripped or not), X-Forwarded-Host with port,
  the fate of a client-sent X-AISC-Request-Id, `copy_headers` when the header is absent, the matcher
  form, latency, and the 401 path.
- Also: one qualification server action, recording `Next-Action` and the body, and one
  qualification-to-platform call.
- Rewrite spec 4.5 and the witness tests from what the spike observes.

**6.2 (major) Skipped tests can make "the phase's tests are green" true.**
The relay and outbox suites skip without `PLATFORM_TEST_SUPERUSER_URL`
(`test_ledger_outbox.py:15`), and the immudb half of the store suite skips without
`LEDGER_TEST_IMMUDB_URL`. So the DoD, and the "red invariant test" stop rule, can pass on skips.
Fix: `LEDGER_TESTS_REQUIRED=1` turns those skips into failures in every DoD run, and each phase
report states the skip count.

**6.3 (minor) "An independent review with no open finding" has no bound.**
Fix: "no open blocker or major; minors listed with an owner".

**6.4 (major) Phase 2 changes availability even with `LEDGER_MODE=off`.**
Caddy calls the witness whatever the mode, so from the phase 2 deploy every request depends on the
platform (1.11).
Fix: gate the witness forward_auth in Caddy itself (an env-selected snippet), and deploy the Caddy
change only when switching to `record`.

**6.5 (minor) The red-team pass comes too late.**
It runs at 4b, after the panel. Move the identity red-team to right after phase 3, before phases 5-9
rely on the binding.

**6.6 (minor) Drills are missing.**
Not covered by any drill:
- the record to enforce flip, in a browser, across every app (server actions, the engine SPA, the
  dashboard);
- a token at the edge of expiry;
- a JWKS key rotation;
- a project delete with a pending outbox;
- a relay backlog longer than the window;
- two platform workers;
- a plugin trying to read the ledger token;
- a witness flood with random pids.

**6.7 (minor) Phases 5-9 are not independent once phase 3 is in.**
The chained calls (step 1 to platform card versions, platform to engine targets, 1.6) make them
depend on a "caused by" mechanism, which belongs in phase 3.

**6.8 (minor) The tests hard-code decisions that are still open.**
D1-D8 and W1-W5 are ASSUMED, but the tests encode them: the 5-minute window, owner-only export, the
status codes. Reference named constants or settings, so that a decision changes one line, not
several tests.
