# Ledger: specification, version 2 (2026-10-02)

Companion of `01-plan.md` (the design) and `../ledger-events-2026-10-02/01-event-registry.md` (every
event). Version 2 rewrites version 1 (commit 0819c5f) from the independent review
(`05-independent-review.md`, "R" + finding number) and the spike (`06-spike.md`, "G"/"M" + number).
Section 12 maps every blocker and major to where it is answered. Version 2.1 closes the second
review's open majors (`07-second-review.md`, N1-N5 and 6.2) and its cheap minors; version 2.2 closes
the third review's (`08-third-review.md`, M1-M4, n-a to n-j); section 12 lists both. The tests (`04-test-plan.md`) check this file.

Decisions D1-D11, W1-W5 and L1-L2 (section 11) are at their defaults until the user changes them:
**ASSUMED**. Every number that depends on one is a named setting in `ledger/settings.py`, never a
literal in a test (R6.8).

## 0. What the ledger claims, and what it doesn't

**Claim.** For every event a person caused, the ledger names a person who:
- made a request through the gateway that the platform witnessed;
- presented a Keycloak-signed token, verified by the platform itself;
- matches the event: the same app, a route the registry allows for that action, the same Next.js
  action id when there is one, the same project, the same item when the route names it, and a time
  inside the window.

For an AI or worker event, it names the program and the person whose request started that run. No
app can name a person who made no such request.

**Not claimed (residual, section 10).** Inside one app, a compromised or buggy app can attribute an
event to the wrong one of several matching requests (two people saving the same form at the same
moment). It can also attribute an AI or worker result to the person who started the run when it
wasn't the result of that run. Reconciliation (I11, section 7.4) raises an alarm on the patterns this
leaves (two different event actions under one action id, a broken item chain, a witnessed write with
no event), but can't prevent them. The immudb superuser can delete a whole log. That is detected
(I4, section 7.3), not prevented.

## 1. Invariants

| # | Invariant |
|---|---|
| I1 | Every state-changing request that reaches an app through the gateway has exactly one witness record, made before the app saw it. In `enforce`, a request with a missing, malformed, wrongly signed, foreign-issuer, expired or mismatched token never reaches the app. |
| I2 | No app chooses who acted. A person's identity comes only from a witness record that passes section 4's binding rules. An AI or worker run's person comes from its start event. A system event's identity comes from the caller's service token. Any actor-like field an app sends is ignored and recorded (`ledger.rejected`, `actor_supplied`). |
| I3 | Every event is recorded exactly once. The idempotency key is `(event_id, content digest)`. A replay is a no-op. The same `event_id` with a different digest is an alarm (`duplicate_event_id`), never silently dropped (R2.3). A crash at any point loses and duplicates nothing. Undelivered events survive a project delete (R2.4). |
| I4 | Every entry the platform shows or exports is a verified immudb read. The platform's verified state per database is kept outside immudb and only moves forward. A rollback, a rewrite or a missing database is an alarm, never an "unavailable" (M13-M15). |
| I5 | A change made in a project database outside the apps is detected against a baseline. Each evidence table gets a genesis snapshot when its app's phase starts, and every migration that touches evidence emits a `system` event with digests before and after (R2.13). |
| I6 | No event is lost while the platform, immudb or the relay is down. When immudb is down, nothing an app does is blocked: witness records and outbox rows wait in Postgres. When the platform is down, witnessed requests fail and other requests work (section 5.3). |
| I7 | Every state-changing route, and every read route listed as "reads that matter", is covered. The coverage test finds it in the code, a registry action names it, and from each app's phase a static check finds that handler emitting that action (R4.14). |
| I8 | No secret reaches the ledger. Tokens, passwords, keys and query strings appear only as keyed fingerprints (`hmac:v<N>:` + 32 hex, under the project's `fingerprint` key, section 7.5), in `details` and in `content` alike (R1.16, R4.8). |
| I9 | One project's records never land in another project's log. A member of one project can't read another's. A caller who isn't a member can't add to a project's log (R1.2). |
| I10 | **Minimisation.** immudb holds a **random** actor reference per (project, person), never a subject or a name, so nothing can recompute it. The mapping to the person lives in Postgres with a MAC (a swapped row is detected) and can be erased, which really cuts the link. Page views stay out of immudb, with a retention limit. Every digest is computed by the platform under a per-project key, so low-entropy answers can't be reversed (R2.5, N4, N5). |
| I11 | **Item chain.** For each item, an accepted event's `before_sha256` equals the previous accepted event's `after_sha256` (both computed by the platform from the `before` and `after` states the app sends). A break is recorded as an alarm, not a rejection, since concurrent edits are legitimate (R2.6). |

## 2. Threats

| # | Threat | Stopped or detected by |
|---|---|---|
| T1 | An app writes a person's name into an event | I2 |
| T2 | An app cites another person's request | section 4.2: app, route, action id, project, item and time must all match, and the request's subject is the actor |
| T3 | An app cites an old request | the window: outbox `occurred_at` (set by the database) minus witness `at` must be within `WINDOW` (section 4.2). An AI or worker event must cite an accepted start event of the same run, within `RUN_WINDOW` (section 4.4) |
| T4 | One request used for more events than its action allows | `per_request`, counted under the project's relay lock (section 7.2) |
| T5 | A forged, expired or foreign token | witness verification (section 3.3): signature, issuer, `azp`, expiry with 30 s leeway, not-before |
| T6 | A token for one project used on another's path | the witness resolves the project per app from the original URI or `X-AISC-Project`. A non-member's request goes to the platform log. The event's project must equal the witness's (I9) |
| T7 | An app edits, deletes or back-dates its outbox rows | no table grant at all. Apps call `ledger.emit(...)`, a SECURITY DEFINER function that stamps `db_role := session_user` and `occurred_at := clock_timestamp()` (R2.1, R3.3) |
| T8 | Replay of an outbox row or an internal event | I3 |
| T9 | A relay crash between the immudb write and the delivery mark | I3: the immudb `id:` key is checked before every append |
| T10 | Someone with database rights rewrites evidence rows | I5 |
| T11 | Someone with immudb rights rewrites or rolls back a log | immudb proofs, plus the verified state in Postgres, plus heads published to the object-locked bucket (I4) |
| T12 | The read index is altered to hide or change events | every entry shown is read back verified from immudb and compared with its index row. A difference is an alarm |
| T13 | A secret leaks through `details` or `content` | I8: allowed keys per action; known secret patterns fingerprinted; query strings never stored |
| T14 | Clock skew | both times in the window check come from the same Postgres cluster's clock (witness: platform database; `occurred_at`: project database). The internal route uses the platform's receive time |
| T15 | Two writes of one item at once | each is its own request and event. I11 shows the order and flags a fork |
| T16 | An app silently doesn't emit | I7 static check, plus the "witnessed write with no event" reconciliation from phase 3 |
| T17 | Untrusted code holds ledger credentials (plugins, R1.9) | no ledger credential in any process that runs or imports plugin code: the eval worker runs it, and the engine backend imports plugin packages in-process (phase 2 review M2), so the engine's token goes to a process that never imports plugins (D12, phase 8). Until each caller's phase, only the platform holds the caller tokens. The credentials test checks every compose service (`RUNS_PLUGINS` includes `aisc-backend`) |
| T18 | Anyone calls the witness directly (G2) | the gateway secret `X-AISC-Gateway`, compared in constant time; the launcher blocks `/api/authz/*`; without the secret: 401, no record |
| T19 | A forged `X-AISC-Request-Id` or identity header (G3) | `protect` strips them first, inside `route` (G7). The platform also checks a presented id against the presenter (section 4.3) |
| T20 | Two tokens on one request (G5) | if `Authorization` and the gateway token are both present, their subjects must be equal, or the witness refuses (`enforce`) or records `request.unverified`, reason `token_mismatch` (`record`) |
| T21 | A restore from backup (R2.9) | immudb: `illegal state` is an alarm; an admin's `ledger.reanchored` entry in the platform log, naming both heads, is the only way forward. Project Postgres: rows re-sent are no-ops by I3; `delivered` is rebuilt from immudb's `id:` keys |
| T22 | Key rotation (R2.9) | JWKS re-fetched on an unknown `kid` (at most once per 30 s); the gateway secret and the ledger tokens accept old and new during an overlap (`ROTATION_OVERLAP`, 24 h); ledger master keys are **versioned** (`PLATFORM_LEDGER_KEYS`), new digests use the newest and every kept version still checks (section 7.5); the immudb user's password is rotated by an operator script |
| T23 | A flood of witness calls with random project ids (R1.2) | a project id is used only if `db.get_project` finds it; an immudb database is never created on the request path (section 7.1) |
| T24 | Two platform workers or two relays (R2.7) | one immudb client per database with its own lock; a per-project advisory lock around each relay batch; verified state updated by compare-and-set |

## 3. The gateway and the witness

### 3.1 The `protect` snippets (G7, G8, S1)

The reference implementation, run by the real-Caddy suite, is `spike/Caddyfile.reference`:
`scripts/tests/test_ledger_gateway.py` passes on it with `LEDGER_TESTS_REQUIRED=1`. Its parts:

| Snippet | Content |
|---|---|
| `(strip-and-sign-in)` | `request_header -X-AISC-Request-Id`, `-X-AISC-App`, `-X-AISC-Gateway`, `-X-AISC-Original-Uri`, `-X-Auth-Request-*`, then today's oauth2-proxy `forward_auth` |
| `(protect)` | `route { import strip-and-sign-in; import witness-{$LEDGER_GATEWAY} {args[0]} }` |
| `(protect-reads)` | the same, plus `import witness-reads-{$LEDGER_GATEWAY} {args[0:]}` |
| `(witness-on)` | matcher `@witnessed_{args[0]} { not method GET HEAD OPTIONS }`; `forward_auth @witnessed_{args[0]} platform:8000` with `uri /authz/witness`, `header_up X-AISC-App {args[0]}`, `header_up X-AISC-Original-Uri {http.request.orig_uri}`, `header_up X-AISC-Gateway {$AISC_WITNESS_GATEWAY_SECRET}`, `copy_headers X-AISC-Request-Id` |
| `(witness-reads-on)` | the same with `@witnessed_reads_{args[0]} { method GET; path {args[1:]} }` |
| `(witness-off)`, `(witness-reads-off)` | empty |

- Every handle imports `protect <app>`, or `protect-reads <app> <path>...` when it has reads that
  matter (downloads, exports, "report viewed", an older card version viewed), with `<app>` from
  `KNOWN_APPS`.
- `route` is required. Without it Caddy runs the witness before sign-in and the strip after the
  witness (G7).
- **S1, settled.** `{args[1:]}` expands to several paths, and `{args[0:]}` passes through a nested
  import. An empty path list stops Caddy at load ("module value cannot be null"), and `caddy adapt`
  doesn't catch it. That's why `protect-reads` is a snippet of its own, never `protect` with zero
  paths.
- `LEDGER_GATEWAY` (`off` or `on`) picks the snippets at Caddy start, so the witness costs nothing
  until `record` is switched on (R6.4). The strip is deployed first, on its own (phase 0b), because
  G3 is a defect today.
- The launcher answers 404 to `/api/authz/*`, before its `handle_path /api/*`, as it does to
  `/api/internal/*`.
- **A refused page load** (`Sec-Fetch-Dest: document`): the witness itself answers 302 to
  `/oauth2/start?rd=<original uri>`, and forward_auth passes it through. Otherwise it answers 401
  (R1.12). Caddy's `handle_response` matchers see only the auth server's response headers, so the
  decision can't be made in Caddy.
- Flower and pgAdmin: `flower.request` and `pgadmin.request` are witness-born actions. The witness
  record is the event (R1.14).
- The catalogue is hosted elsewhere and never passes this gateway. It is out of scope, except the
  local `plugin.installed` and `control.installed` (R1.10).

### 3.2 What the witness receives and trusts

| Header | Set by | Trusted for |
|---|---|---|
| `X-AISC-Gateway` | Caddy (`header_up`), after the strip | that the call came from Caddy (T18) |
| `X-AISC-App` | Caddy, per handle | the app (G1) |
| `X-AISC-Original-Uri` | Caddy (`{http.request.orig_uri}`) | the path before stripping: the project and the route. The query is cut off and fingerprinted (G10) |
| `X-Forwarded-Method` | Caddy (forward_auth) | the method |
| `X-Forwarded-Host` | Caddy | the site (recorded, not used to decide) |
| `X-AISC-Project` | the client (the engine web app) | engine routes only: the project, checked for membership |
| `Next-Action` | the client (Next.js) | the server action id (G6), recorded for binding |
| `X-Auth-Request-Access-Token` | oauth2-proxy via `copy_headers` | the gateway token: the person |
| `Authorization: Bearer` | the client | compared with the gateway token (T20) |

The witness ignores its own query string (G10) and every other header.

### 3.3 Token verification (one function, shared)

`aisc_identity.gateway_identity(headers) -> Identity | Refusal` lives in `shared/identity` (Python) with
a TypeScript twin in `shared/identity-ts`, and is used by the witness and by every app that isn't
frozen (R1.4):
- The gateway token is authoritative. A Bearer token, when present, must be validly signed and carry
  the same `sub`. Otherwise the result is a refusal, `token_mismatch`.
- Signature against Keycloak's JWKS, re-fetched on an unknown `kid`. `iss` is the realm. `exp` and
  `nbf` with `LEEWAY` = 30 s. `azp == aisc-gateway` for the gateway token (R1.15). The Bearer token
  may come from another client (the engine web app's keycloak-js), so its `azp` isn't checked.
- oauth2-proxy refreshes at 4 minutes, under the 5-minute token lifespan (`--cookie-refresh=4m`,
  R1.12).
- The engine is frozen and keeps its own precedence. The witness refuses the mismatch before the
  engine sees it.

### 3.4 What the witness records

The witness writes to `ledger.witness` **in the platform's Postgres**, in the request (about 1 ms),
not to immudb (M16, I6). The relay copies each record into its project's immudb log as
`request.witnessed`.

`ledger.witness(request_id uuid pk default gen_random_uuid(), at timestamptz default clock_timestamp(),
mode, app, method, route_path, query_hmac, host, project_pid null, member bool, actor_ref, verified
bool, reason null, next_action null, token_jti, token_exp, delivered_seq null)`.

- `project_pid` is set only when the app's rule finds a pid that `db.get_project` knows **and** the
  caller is a member. Otherwise it's null and the record goes to the platform log (T6, T23, I9). One
  exception, in `record` only: a request with no verified person keeps the project its path names
  (`member=false`, `verified=false`), so the events it caused are recorded in that project's log,
  marked unverified (4.2). `enforce` refuses such a request outright.
  D11 decides whether non-member requests are kept at all.
- It answers 200 with `X-AISC-Request-Id` for every witnessed request in `record` and `enforce`, so
  Caddy always overwrites the header (G3). `off` isn't reachable (the snippet is empty).

Project rule per app (`registry.APP_PROJECT_RULES`), against the unstripped path:

| App | Project from |
|---|---|
| qualification, controls | `/qualification/p/{slug}/...`, `/controls/p/{slug}/...` |
| control_objectives | `/control-objectives/p/{pid}/...` |
| report_composer | `/report-composer/p/{slug}/...` |
| platform | `/api/projects/{slug}/...` (launcher) and `/platform/api/projects` (none) |
| launcher | `/p/{slug}` |
| engine | `X-AISC-Project` |
| dashboard | the dashboard bridge table (dashboard id to project), else the platform log |
| flower, pgadmin, schema, engine_webapp | none (platform log) |

### 3.5 Page views

Page views don't go through the witness (G9). They are **best effort**, `reported_by=browser`:
- the shared beacon sends `page.opened`, `page.left`, `dialog.cancelled` and `unsaved_changes`;
- it posts `text/plain` to `/ledger/beacon` on its own origin, so every site gets a beacon route
  (R3.6); the beacon POST is itself witnessed, so who sent it is certain;
- the records are kept in Postgres `ledger.page_view` with retention `PAGE_VIEW_RETENTION` (D10:
  90 days), never in immudb (I10).

## 4. Binding an event to its request

### 4.1 Registry fields

`Action(name, step, origin, emitters, item_type, routes, caused_by, actor_kinds, details_keys,
content_required, per_request, runs, run_window, registry_version)`:
- `origin`: `app` (an app emits it through `ledger.emit` or the internal route), `platform` (the
  witness or the relay makes it; no emitters), or `browser` (the beacon route reports it, `page.*`).
- `emitters`: the apps that may emit it (by `db_role` or token).
- `caused_by`: the witnessed requests that may cause it, as `(app, METHOD, path_regex)` or
  `(app, "ACTION", page_regex)` for a Next.js server action. An `item` named group in the regex binds
  the event's `item_id` (R1.7). `caused_by` names the **originating** app, which may differ from the
  emitter: `card_version.created` is emitted by `platform`, caused by `qualification`'s submit (R1.6).
- `routes`: where the code handles it, for coverage. `(app, file, function)`: a file path relative to
  the repo and the handler's function name, never a path template, which collides across routers
  (R4.12).
- `runs`: for a start action, the AI or worker actions its run may produce. `run_window` defaults to
  24 h.
- A witness-born action (`request.witnessed`, `flower.request`, `pgadmin.request`) has no
  `caused_by` and no `routes` (R4.3).

### 4.2 The relay's checks for a person's event

An outbox or internal event citing `request_id` is accepted only if all of these hold. Otherwise it
becomes `ledger.rejected` with the first failing reason. As built (phase 3 review m2, M2): the
content checks of item 9 come first, then items 1 to 4 and 6 to 8, and the action id (item 5) last,
so the binding of section 4.5 learns only from an event that passed everything else; it is written
after the append. A value canonical JSON refuses is `unencodable`, an entry over `MAX_ENTRY_BYTES`
`too_large`: a bad row is a rejection, never a stall of its log.

1. `missing_request` / `unknown_request`: the event cites a request, and its witness record exists.
2. `project_mismatch`: its `project_pid` equals the event's project.
3. `emitter`: the event's emitter is in `action.emitters`.
4. `cause`: `(witness.app, witness.method, witness.route_path)` matches an entry of `caused_by`.
5. `action_id`: for a server action, see section 4.5 (an event caused by a server action whose
   request carries no action id is refused too).
6. `item`: when the matching regex has an `item` group, it equals the event's `item_id`.
7. `stale_request` / `early_event`: `0 <= event.occurred_at - witness.at <= WINDOW` (W3: 5 min), with
   `CLOCK_SKEW` = 2 s of tolerance below zero (R2.2). Relay time never enters the check, so a backlog
   never makes an event stale.
8. `per_request`: the count of accepted events of this action citing this request stays within
   `per_request`.
9. `actor_supplied`, `details_key`, `secret_in`, `unknown_action`: as in version 1.
   `platform_field:<name>`: the app sent something only the platform computes (`content_sha256`,
   `before_sha256`, `after_sha256`, `recorded_at`, `seq`; N4). The platform digests `content`,
   `before` and `after` itself, as canonical JSON under the project's `content` key.
   An unknown action whose `registry_version` is newer than the platform's is **held** for
   `HOLD_UNKNOWN` (24 h), then rejected (R2.12).

`actor_ref := witness.actor_ref`. When the witness is unverified (record mode), the event is accepted
with `verified=false` (R2.14).

A `ledger.rejected` entry carries `actor_kind=system`, `program=relay`, the rejected row's digest and
the cited request id. It is never attributed to the cited person (R4.7).

### 4.3 Requests that travel on (app to app, R1.6)

When an app calls another app's write route on behalf of the person (qualification to platform
`system-versions` and `targets/sync`; the platform to the engine and the dashboard bridge):
- It forwards `X-AISC-Request-Id` together with the person's token. The qualification app already
  sends the person's token (G11).
- The receiving app accepts a forwarded id only with a valid person token (section 3.3) whose `sub`
  equals the witness's, or with a service token from a caller listed for that action. Otherwise it
  answers 401 in `enforce`.
- The relay applies section 4.2. The cited request's app is the originating one, which is why
  `caused_by` is separate from `emitters`.
- The platform checks every presented id against the presenter's subject and route (R1.5). In
  `enforce` a failing id refuses the write (401); in `record` it is not used, so the platform's event
  cites no request rather than someone else's (phase 3 review m9). The route is compared for an id the
  launcher's gateway gave (app `platform`); an id forwarded by another app was witnessed for that
  app's own route, so for it only the subject is compared.

### 4.4 AI and worker runs (R1.8)

- The person's request emits a start event, for example `ai.refinement.requested` or
  `engine.evaluation.run_requested`, with a fresh `run_id`. It is checked under section 4.2.
- Every event of the run carries `(request_id, run_id)`. The relay requires an accepted start event
  with that `run_id` citing that request, the event's action in the start action's `runs`, and
  `occurred_at - start.occurred_at <= run_window`. The reasons are `run` (no such start event, or an
  action the run doesn't produce) and `run_window`.
- `on_behalf_of := start.actor_ref`. `actor_kind` and `program` come from the emitter's token, and
  `model` from the event.
- The internal route answers 202 and records a refused AI event as `ledger.rejected`, as I2 says,
  rather than 422 (R4.10). A malformed body is still 422.

### 4.5 Next.js server actions (G6)

A server action is a POST to the page, with `Next-Action: <id>`. The build doesn't say which function
an id is, so:
- `caused_by` names the page regex, and the witness records the id.
- `ledger.action_binding(app, next_action) -> set of actions` is learned from the **first request**
  witnessed with that id that has accepted events: the set grows with every action that request's
  events carry (one server action may save and rename at once). Every other request with the same id
  is checked, at any time, against the set as it stands: it may produce any subset; an event of an
  action outside it is rejected (`action_id`) and raises an alarm (N3, third review n-d).
- Only events emitted by the app that serves the action bind or are checked: an event another app
  emits on the same request (the platform's `card_version.created` on a step-1 submit) is checked by
  its `caused_by` alone, and run events (section 4.4) are checked by their start event, never by the
  binding.
- Limits, stated: the binding learns on first use after each build, so a compromised app can teach
  it; and a server action whose first call happens not to take a conditional branch will see that
  branch's event rejected later (recorded as `ledger.rejected`, so not lost, and listed by
  reconciliation for review). The static bound stays `caused_by`: no event of an action whose
  `caused_by` doesn't name the page is ever accepted.
- Ids change with each build. A new id simply binds afresh.
- Open item S2: if a later Next version writes the export name into the manifest, the binding is
  seeded at build time instead.

## 5. Modes, rollout and failure

### 5.1 Modes

`LEDGER_MODE` (platform): `off`, `record`, `enforce`. `LEDGER_GATEWAY` (Caddy): `off`, `on`; unset is
`off`, so a Caddy restarted without the setting behaves as before. The pairs that are allowed: (`off`,
`off`), (`record`, `on`), (`enforce`, `on`). In `record` or `enforce` without the gateway secret, the
witness answers 503 to every call (phase 2 does this per request rather than refusing to start; a
start-up check, and a check for the disallowed pair `on` + `off`, come with the deploy checklist of
phase 4).

### 5.2 Rollout order (R2.14)

1. Header strip in Caddy (fixes G3 today).
2. Platform with the ledger core and registry, `off`.
3. `record` + `LEDGER_GATEWAY=on`.
4. Each app's emitter, platform first.
5. A clean reconciliation period (`RECONCILE_DAYS` = 14).
6. `enforce`, on the user's yes.

The platform always deploys before an app that emits a new action.

### 5.3 Failure behaviour (W2 restated, R1.11)

| Down | Witnessed requests (writes, listed reads) | Other requests | Events |
|---|---|---|---|
| platform | fail (502) | work | wait in the outboxes |
| immudb | work | work | witness records and outbox rows wait; nothing is rejected for waiting |
| relay | work | work | wait |
| Keycloak (JWKS cached) | work until the cache expires (`JWKS_TTL`) | work | wait |

In `enforce`, apps also refuse a write with no `X-AISC-Request-Id` (defence in depth), except calls
carrying a service token.

**`record` fails closed too.** If the witness can't write its record (the platform database or
`ledger_identity` unreachable), it answers 500 and Caddy refuses the write, in `record` as in
`enforce`. `record` relaxes only the token rule (an unverified person is let through and marked), never
the record itself: an unrecorded write is what the ledger exists to prevent.

## 6. Interfaces

### 6.1 Python package `platform/platform_service/ledger/`

`__init__.py`, `registry.py`, `settings.py`, `canonical.py` and `naming.py` import only the standard
library, so the repo-level tests can load them (R3.7).

- `settings`: `WINDOW`, `CLOCK_SKEW`, `RUN_WINDOW`, `LEEWAY`, `HOLD_UNKNOWN`, `ROTATION_OVERLAP`,
  `PAGE_VIEW_RETENTION`, `RECONCILE_DAYS`, `MAX_ENTRY_BYTES` (64 KiB), `BEACON_PER_MINUTE` (60),
  `BACKUP_RETENTION` (30 days), `EXPORT_ROLES` (D1), `KEEP_STRANGER_REQUESTS` (D11).
- `naming.pool_name() -> str`: `"ledger" + 32 random lowercase hex`. `naming.is_ledger_name(name)`
  is checked before any immudb call. A name never carries a pid: the pool makes databases before
  projects exist and immudb can't rename one (N1). The platform log is `"ledgerplatform"`.
- `canonical.canonical(value) -> bytes`: RFC 8785. It refuses integers beyond ±2^53, `bool` posing as
  a number, lone surrogates, NaN and infinities, `Decimal` and `datetime` (R2.11, R4.1). The shared
  vectors file `platform/tests/ledger/fixtures/canonical_vectors.json` is used by the TypeScript twin
  in phase 5.
- `secrets` (section 7.5): `derive(pid, purpose, version=None) -> (version, key)` and
  `derive_all(pid, purpose) -> {version: key}` (HKDF-SHA256 from `PLATFORM_LEDGER_KEYS`, info
  `aisc-ledger/<purpose>/<pid lowercased>`, or `.../platform` for the platform log; purposes `content`,
  `state`, `query`, `mapping`, `fingerprint`). `PLATFORM_LEDGER_KEYS` is read on every call, so a
  rotation needs no restart (n-j).
  `digest(pid, purpose, value) -> "hmac:v<N>:" + 32 hex` under the newest version;
  `check(pid, purpose, value, digest) -> bool` under the digest's own version, if still kept;
  `content_digest(pid, content)` = `digest(pid, "content", canonical(content))`;
  `state_digest(pid, state)` = `digest(pid, "state", canonical(state))`, for `before_sha256` and
  `after_sha256`: the chain needs only equality, and the `state` key is never exported, so a rating
  history can't be brute-forced from an export (n-e);
  `fingerprint(pid, value)` = `digest(pid, "fingerprint", value)`.
- `actors.ref_for(pid, sub, name) -> actor_ref` gives the person's reference in that project,
  creating it on first sight: `"actor:" + 32 random hex`, with a mapping row
  `actor(scope, actor_ref, sub, name, mac)` in the separate database `ledger_identity` (S8), where
  `scope` is the pid as text, or
  `'platform'` for `pid=None` (never NULL, which a unique key wouldn't cover); unique on
  `(scope, sub)`, so first sightings at once make one reference, in either scope; and
  `mac = digest(pid, "mapping", canonical([actor_ref, sub, name]))`. A name change rewrites the row
  and its MAC (n-g, fourth review 3).
  `actors.resolve(pid, actor_ref) -> (sub, name) | None` checks the MAC and raises `MappingAlarm` on a
  mismatch. `actors.erase(pid, sub)` deletes the rows; the next sight of that person makes a new,
  unrelated reference. `actors.tamper` is a test hook.
- `pageviews.recent(pid)` and `pageviews.expire(older_than)` (section 3.5).
- `registry.REGISTRY`, `registry.VERSION`, `registry.KNOWN_APPS`, `registry.APP_PROJECT_RULES`,
  `registry.override(actions)` (tests): a context manager that **merges** the given actions over
  the real registry and restores it on exit, so the fixtures' own events stay known (third review M2).
- `registry.check(event, emitter) -> list[str]` gets the emitter (R4.3). `emitter` is the problem
  when the emitter may not emit the action, which covers every app emitting a platform-only action.
  `actor_supplied` covers an actor-like key in `details` and a platform field set at top level
  (`actor_*`, `on_behalf_of_ref`, `source_app`, `verified`). It never scans `content` for actor
  fields, since content legitimately carries `reviewed_by`. It does scan `content` for secrets (I8).
- `KNOWN_APPS` holds every app behind the gateway (`engine`, `engine_webapp`, `flower`, `controls`,
  `qualification`, `control_objectives`, `report_composer`, `platform`, `launcher`, `pgadmin`,
  `schema`, `dashboard`) and every app that serves routes inside the network (`engine_worker`,
  `connectors`, `report_renderer`, `qualification_agents`, `qualification_prefill`,
  `qualification_ontology`, `qualification_llm`, `qualification_pdf`).
- `store.Ledger` protocol: `append(db, entry) -> int`, `get(db, seq) -> Entry` (verified),
  `head(db) -> Head`, `scan(db, after_seq, limit)`, and the test hooks `state(db)` and
  `set_state(db, state)` (R3.4). `State.claiming(tx_id=...)` makes a state that claims more than the
  server holds.
  - Errors: `DuplicateEvent` (same id, other content), `EntryTooLarge`, `UnknownDatabase` (not made
    by the pool), `TamperAlarm`.
  - Every store has a `server_id` (the immudb address, or `memory:<uuid>`) and `databases()`.
  - `MemoryLedger` test hooks: `create(db)`, `drop(db)`, `tamper(db, seq, field, value)`, `down`,
    `crash_after_appends`, `public_key_pem()`.
  - `store.ImmudbLedger(url, user, password, state_store)` uses the key-value API only (M8):
    `e:<seq, 20 digits>` to the canonical entry, `id:<event_id>` to seq and digest. Event ids are
    unique **per log**; `ledger.event_index` is keyed `(project_pid, seq)` and unique on
    `(project_pid, event_id)`, never on `event_id` alone (fourth review 6).
  - It keeps one client per database, each behind its own lock, and never calls `useDatabase` on a
    shared client (M9).
  - Its `state_store` is `state.PostgresStateStore`, over `ledger.state(db pk, tx_id, tx_hash,
    signature, updated_at)`, or `state.MemoryStateStore` in tests. `get(db)`, and
    `put(db, state, expected)`, a compare-and-set that raises `ValueError` on a stale `expected`
    (M11).
  - `illegal state`, `ErrCorruptedData`, a failed proof and a bad state signature all raise
    `TamperAlarm` (M13, M14). It never creates a database (M1).
  - **Two writers** (phase 1 review B2): each append writes `e:<seq>`, `id:<event_id>` and `seq:last` in
    one transaction with immudb `KeyMustNotExist` preconditions on the first two; a writer that loses
    the race reads again and takes the next number. No event is ever lost or numbered twice, whether
    or not the relay's advisory lock is held.
  - **A lost session** (an immudb restart, B1) is logged in again once and the call retried, so the
    same store recovers on its own.
  - **Shared verified state** (M1): a proof of an older state than the stored one is not tampering
    (another worker moved it on); the state only moves forward, by compare-and-set with retry.
  - **Signed states** (S3, settled): with immudb's `--signingKey`, the store is given the public key
    (`LEDGER_IMMUDB_PUBLIC_KEY`) and every state's signature is checked.
  - **First sight**: a database with no saved state trusts the server's current state as the anchor.
    With the signing key on, that state is at least the server's own; the anchor then only moves
    forward. Stated here and in the runbook.
  - `store.MemoryLedger()` is for tests.
- `pool.create_databases(url, *, admin_user="immudb", admin_password, names, grantee,
  grantee_password)`: the operator's step behind `scripts/ledger-pool.sh`. It raises `PermissionError`
  when the account isn't the superuser (M1).
- Platform-database tables, with the columns other code and the test cleanup rely on:
  `ledger.witness(request_id, project_pid, ...)` (section 3.4), `ledger.actor(scope, actor_ref, sub,
  name, mac)`, `ledger.event_index(project_pid, seq, event_id, action, actor_ref, step, item_type,
  item_id, card_version, outcome, occurred_at)`, `ledger.page_view(project_pid, actor_ref, action,
  details, at)`, `ledger.state(db pk, tx_id, tx_hash, signature, updated_at)`,
  `core.outbox(..., project_pid, request_id)`.
- `ledger.pool(db pk, server_id, created_at, assigned_pid null, assigned_at)` in the platform
  database: the operator's script inserts a row per database it makes (`pool.register(store, names)`
  refuses a name that isn't a ledger name). `server_id` is the server's own identity, never its
  address: immudb's server UUID (sent in the `immudb-uuid` response metadata; open item S7), or
  `memory:<uuid>` (n-c). `provision.assign(pid, conn=None) -> db | None` (None when the pool is
  empty) neither looks the project up nor holds a foreign key to it, so phase 1 can test it alone
  (fourth review 4); it runs **inside the project creation's transaction** (`provision.transaction()`), so a failed creation consumes nothing; it is idempotent
  per pid, and takes a free row **of the current store's `server_id`** with `FOR UPDATE SKIP LOCKED`, so two creations never share one and another server's database is never handed out
  (N1). `provision.database_for(pid) -> db | None`; `provision.assigned()`; `provision.pool_level()`;
  `provision.assign_pending(pid) -> bool` after a refill. With the pool empty the project is still
  created, `database_for` is `None`, and its events wait (I6). The assignment is kept for ever (D2):
  it is also the expected-databases list (R2.10).
- `witness.witness(headers) -> Answer(status, headers)`, with the mode read from `LEDGER_MODE`. It takes
  the raw headers, so the tests send exactly what Caddy sends (G1, G8). `witness.record(request_id)`
  returns the stored record; `witness.count(route_path=...)` counts records (tests).
- The one token rule is `aisc_identity.gateway.gateway_identity` in `shared/identity` (Python). Its
  TypeScript twin, and the apps' own adoption of the rule, come with each app's phase (5 for the
  TypeScript apps); until then the witness applies it before any app sees the request.
- `relay.relay_once(pid=None) -> RelayStats(delivered, rejected, held, pending)`. A project whose
  assigned database the current store doesn't have (gone from immudb, or another server's) counts
  as pending and raises the `missing_database` alarm for that project only; the batch never aborts
  and the other projects are delivered (third review M4). It takes the
  project's advisory lock and drains `ledger.witness`, the platform's `core.outbox` and the project's
  `ledger.outbox`, in `occurred_at` order, with a seq per log.
- `verify.verify(pid) -> Report(entries_ok, entries_failed, chain_breaks, action_id_conflicts,
  evidence_ok, evidence_failed, witness_without_event, outside_changes, missing_database: bool)`.
- `testing.seed(pid, events)` writes entries as the relay does (immudb, the index, the actor
  mapping). `testing.rehash_export(lines)` is an attacker's best effort at re-hashing an edited export.
  `testing.fill_pool(store, n)` makes `n` databases (and the platform log) in a store and registers
  them, as the operator's script does. All three are for tests.

### 6.2 Entry (immudb, key `e:<seq>`)

`seq, event_id, occurred_at, recorded_at, project_pid, card_version, step, source_app, action,
actor_kind, actor_ref, on_behalf_of_ref, program, model, request_id, run_id, next_action, verified,
reported_by, item_type, item_id, item_version, before_sha256, after_sha256, content_sha256,
evidence_ref, depends_on, outcome, details, registry_version`.
- No subject or name (I10).
- `actor_*`, `on_behalf_of_ref`, `source_app`, `recorded_at` and `verified` are always set by the
  platform.
- At most `MAX_ENTRY_BYTES` canonical. Larger content goes to the evidence store, and its digest goes
  in the entry (M10).

### 6.3 Routes

| Route | Who | Behaviour |
|---|---|---|
| `GET /authz/witness` | Caddy only (gateway secret) | section 3. 401 without the secret, with no record |
| `POST /internal/projects/{pid}/ledger/events` | services, per-caller token `PLATFORM_LEDGER_<APP>_TOKEN` | engine backend, dashboard, AI services. Each token is bound to its `emitters` (R4.10). 202, or `ledger.rejected` |
| `POST /ledger/beacon` (each site) | the browser, witnessed | `text/plain`, at most 2 KB, at most 60 per minute per person. Page view records (section 3.5) |
| `GET /projects/{slug}/ledger/events` | members (D1) | read from the index `ledger.event_index`, each entry verified from immudb before it's shown (T12) |
| `GET /projects/{slug}/ledger/events/{seq}` | members | the entry, verified, with its witness record and the person behind `actor_ref` when the mapping still exists |
| `POST /projects/{slug}/ledger/verify` | owners, admins | `verify` now |
| `GET /projects/{slug}/ledger/export` | `EXPORT_ROLES` | JSONL: each entry with its inclusion proof and its frozen content, the server-signed state and the head; the head carries `keys.content` = this project's derived content keys by version, never another project's and never a master key (N5). `scripts/verify-ledger-export.py --public-key K [--check-content]` checks it against immudb's public signing key and, with `--check-content`, every content digest (R4.9) |
| `GET /ledger/projects` | admins | each project's head, last verification, alarms |
| `POST /ledger/reanchor` | admins | after a restore: records `ledger.reanchored` with both heads in the platform log (T21) |

### 6.4 Outbox (project template `0020_ledger_outbox.sql`; platform `core.outbox` in `init/platform-db.sql`)

- Table `ledger.outbox(event_id uuid pk, occurred_at timestamptz, db_role text, request_id uuid,
  run_id uuid, action, item_type, item_id, item_version, card_version uuid, content jsonb,
  before jsonb, after jsonb, details jsonb, outcome, extra jsonb)`. Apps send plain states and never
  a digest (N4); the relay digests them, and moves content over `MAX_ENTRY_BYTES` to the evidence
  store. `emit` keeps every top-level key it doesn't know in `extra`, unrefused, because refusing
  would roll back the business write; the relay rejects them (`platform_field:<name>`, n-b).
  **No grant** to any module role.
- Function `ledger.emit(event jsonb) RETURNS void`, SECURITY DEFINER, `EXECUTE` granted only to
  `qualification_rw`, `controls_rw`, `control_objectives_rw`, `report_composer_rw`, `platform_rw`.
  - It sets `db_role := session_user` and `occurred_at := clock_timestamp()`, and refuses every
    action whose registry `origin` isn't `app` (today `request.*`, `flower.request`,
    `pgadmin.request`, `page.*`, `ledger.*`; R4.7). The list is generated from the registry into the
    template by that one rule, and a test checks it against the registry, so the two can't drift
    (n11, fourth review 2).
  - Apps call it with a plain statement (`SELECT ledger.emit($1)`): Prisma `$executeRaw` inside
    `$transaction`, SQLAlchemy `text()`, so no ORM `RETURNING` is involved (R3.3).
  - It runs in the app's own transaction, so a rollback leaves no event.
- In the project database, `ledger.delivered` and `ledger.action_binding` are reachable only by the
  platform; `ledger.witness`, `ledger.event_index`, `ledger.actor` and `ledger.pool` live in the
  platform database, which no module role can reach (n2). Every other module role (`engine_rw`,
  `dashboard_ro`, `report_ro`) has neither EXECUTE nor any table right (R4.6). `inspector_ro`
  (pgAdmin, SchemaSpy) reads every table it can connect to through `pg_read_all_data`, which can't be
  narrowed per schema; as decided in S8 it may read these tables, which hold only random references,
  and the one table that names people lives where it can't connect (`ledger_identity`). It has no
  EXECUTE on `ledger.emit` and no write right (phase 3 review m7).
- `core.outbox` in the platform database has the same shape plus `project_pid` (null for the
  platform log). Member and project changes write to it in their own transaction (R2.4).
- **Project delete** runs `relay_once(pid)` first, and refuses (409, "the log still has undelivered
  events") while any row of the **project database's** outbox is undelivered. The delete's own
  witness record and its `project.deleted` row live in the platform database, so they never block
  it (n3). Only then does it drop the project's Postgres database; its ledger database stays (D2).

### 6.5 App mapping

| `db_role` / token | app |
|---|---|
| `qualification_rw` | qualification |
| `controls_rw` | controls |
| `control_objectives_rw` | control_objectives |
| `report_composer_rw` | report_composer |
| `platform_rw` | platform |
| `PLATFORM_LEDGER_ENGINE_TOKEN` | engine (held by the engine backend only, never the worker: T17) |
| `PLATFORM_LEDGER_DASHBOARD_TOKEN` | dashboard |
| `PLATFORM_LEDGER_AGENTS_TOKEN` | qualification_agents |

## 7. Operations

### 7.1 immudb accounts and databases (M1-M7)

- The platform holds only `aisc_ledger`, with RW on its assigned databases.
- An operator script, `scripts/ledger-pool.sh`, holds the superuser. It pre-creates `LEDGER_POOL`
  databases (default 20), grants `aisc_ledger` RW on them, inserts a `ledger.pool` row for each with
  the server's id, and is run again when the pool runs low.
  The panel shows the pool level (L1).
- After a grant, the platform logs in again (M7).
- Databases are never deleted (D2), and a deleted name is never reused (M12).

### 7.2 Concurrency (M9, R2.7, R2.8)

- One immudb client per database, each behind its own lock.
- The relay takes `pg_try_advisory_lock(hash(pid))` on the platform database per batch. The seq, the
  `per_request` counts and the delivery marks are written under it.
- The relay polls with backoff (1 s to 30 s) and holds at most `RELAY_CONNECTIONS` (4) project
  connections at once. There is no LISTEN/NOTIFY.

### 7.3 Anchoring, restore, deletion by the superuser (R2.9, R2.10)

- The server signing key is on (`--signingKey`); the platform and the export checker verify state
  signatures. This wasn't spiked; it is phase 1's first immudb test.
- Every `HEAD_PUBLISH` (1 h), each project's signed head is written to the object-locked `evidence`
  bucket (phase 10; until then to `ledger.published_head` in Postgres).
- **The ten-year record (D4).** At the same hour, the entries added since the last archive, each with
  its inclusion proof, are written to `evidence/ledger/<pid>/<first seq>-<last seq>.jsonl` under the
  same lock (the export format of 6.3). immudb is the working log, fast and verifiable; the locked
  archive is what lasts. `archive.rebuild(pid, into_db)` replays a project's archive into a fresh
  database and checks it against the signed heads, so a log deleted by the immudb superuser is
  recoverable, not only detected. The platform never deletes an archive object, and in compliance
  mode MinIO refuses it to everyone.
- **Who the lock stops.** Object Lock is enforced by the storage software. It stops the apps, the
  platform and MinIO's own admin. It does not stop whoever has root on the machine that holds the
  bytes (they can delete the volume). So in staging and production the locked bucket lives on
  storage the AISC host can't administer (decision L3); on a laptop or a development stack the lock
  is off (`LEDGER_ARCHIVE_LOCK=off`), because test data must stay erasable and compliance mode can't
  be undone.
- **Backups.** Backups of the locked bucket keep the same ten years. Backups of the Postgres mapping
  rows don't (`BACKUP_RETENTION`, 30 days), which is what lets an erasure complete (section 7.5).
- A database assigned in `ledger.pool` that immudb no longer has is a `missing_database` alarm.
- Restore runbook (`docs/runbooks/ledger-restore.md`, phase 1): restore immudb, see the alarm, an
  admin re-anchors, the verifier runs.

### 7.4 Reconciliation (from phase 3, R2.6)

Daily and on demand:
- witnessed writes with no event after `WINDOW`;
- events whose cited request had another app's events (`cause` near-misses);
- events rejected as outside their action id's set (section 4.5), for review;
- item chain breaks;
- pool level;
- missing databases.

Each is a panel alarm.

### 7.5 Privacy (I10, D9, D10)

- **References.** `actor_ref` is random per (project, person) (section 6.1). Deleting the mapping
  row is real erasure: neither the keys nor a list of users can rebuild the link. The row's MAC
  catches a swapped row.
- **Keys.** `PLATFORM_LEDGER_KEYS="v1:<secret>,v2:<secret>"`, held by the platform alone. Per
  project and purpose, keys are derived with HKDF, so no derived key opens another project or
  another purpose. Every digest names its version. Rotation adds a version; new digests use it.
  Versions are **kept for ever**: digests in immudb can't be re-made, and removing a version makes
  its digests uncheckable (a test shows that consequence, n-f). Rotation protects new records after
  a suspected leak; it doesn't re-protect old ones.
- **Auditors.** The export carries that project's `content` keys only, so an auditor checks every
  content digest offline and learns nothing about another project. `fingerprint`, `query` and
  `mapping` keys are never exported.
- Erasing a person deletes their mapping rows. Their entries stay, pseudonymous.
- **Retention** (n-h): `token_jti` and `token_exp` in `ledger.witness` are nulled after
  `RECONCILE_DAYS`; Postgres backups keep erased mapping rows until they expire (`BACKUP_RETENTION`,
  30 days), so an erasure is complete only after that, and the DPIA says so.
- Page views stay in Postgres with retention (section 3.5).
- A DPIA is required before `record` is switched on in staging. D1 (who sees per-person activity) is
  revisited in it.

## 8. Limits

| Limit | Value |
|---|---|
| canonical entry | at most 64 KiB (`MAX_ENTRY_BYTES`); 5 MiB went through immudb (M10), so this is our cap, not immudb's |
| integers in canonical JSON | at most ±2^53 |
| beacon body | at most 2 KB, 60 per minute per person |
| write latency added by the witness | one platform call plus one Postgres insert; immudb (about 30 ms, M16) is off the request path |

## 9. Tests must not pass on skips (R6.2)

With `LEDGER_TESTS_REQUIRED=1`, every skip in `platform/tests/ledger` and `scripts/tests/test_ledger_*`
becomes a failure. Every Definition-of-Done run sets it, and every phase report states the skip count.
The mechanism is `need()` in the ledger conftest; database tests use the fixture marker `needs_db`,
never the platform's collection-time `needs_database` skipif, which no flag can turn into a failure
(second review 6.2). Verified 2026-10-02 on every file that collects before phase 1 (witness, outbox, internal,
failure): with no database, every test skips without the flag and fails with it, none skipping.
A whole-directory run stops at the collection errors first, so the check is run on those files.

## 10. Residual risks (accepted, stated)

1. Within one app, the swap of two matching concurrent requests (section 0).
2. An AI service misreporting what its run produced. Its prompt and answer are frozen (W4), which
   makes this checkable after the fact.
3. The immudb superuser deleting a log. Detected (7.3), not prevented, and recoverable from the
   locked archive when that lives off the AISC host (L3). Anyone with root on the archive's own
   storage can still destroy it: that is why L3 puts it elsewhere. External timestamping stays out of
   scope.
4. A person's own token used by a compromised app within the window on a matching route.
5. Page views are best effort and browser-reported.
6. The engine is frozen. Its own token precedence is unchanged, and the witness covers it.

## 11. Decisions (ASSUMED until answered)

From the 09-30 plan: D1 every member sees the panel; D2 the log is kept after a project is deleted;
D3 engine forwarding by one registered exception; D4 a 10-year lock; D5 personal data frozen in the
evidence store, hashed in the log; D6 Superset page views out of immudb; D7 fix the defects before each
app's phase; D8 immudb in staging and production.

Version 1: W1 witness every write at the gateway; W2 as restated in 5.3; W3 a 5-minute window; W4 full
AI prompts and answers frozen; W5 operator actions logged as `operator`, unverified.

New in version 2:

| # | Decision | Default |
|---|---|---|
| D9 | Pseudonymous actors in immudb, mapping in Postgres | yes |
| D10 | Page views: best effort, in Postgres, retention | 90 days |
| D11 | Requests by non-members of the project in the path | recorded in the platform log, never the project's |
| L1 | How ledger databases are created | pre-created pool by an operator script; the platform never holds the superuser |
| L2 | Ledger content cap | 64 KiB per entry, larger content in the evidence store |
| D12 | Who posts the engine's ledger events, given that aisc-backend imports plugin code | **open, for phase 8**: recommended, a small forwarder process (no plugin imports) next to the engine backend holds the token, or the engine's events reach the platform through its database outbox instead of a token |
| L3 | Where the locked archive lives in staging and production | **open**: storage the AISC host can't administer (a MinIO run by LIST IT, or a cloud bucket with Object Lock), at least replicated to a second site; off on development stacks |

## 12. Review findings, and where each is answered

| Finding | Where |
|---|---|
| 1.1 (blocker) app/project from paths | 3.1 per-handle app, 3.4 project rules; G1, G8 |
| 1.2 (blocker) witness callable by anyone | T18, T23, 3.1, 3.4; G2 |
| 1.6 (blocker) app-to-app writes | 4.1 `caused_by`, 4.3; G11 |
| 1.3 forged request id | T19, 3.1; G3 |
| 1.4 two tokens | T20, 3.3; G5 |
| 1.7 shape-only binding | 0 (narrowed claim), 4.2 item, 4.5 action ids; G6 |
| 1.8 AI runs | 4.4 |
| 1.9 plugin env | T17 |
| 1.10 apps without a project in the path | 3.4 table, catalogue out of scope (3.1) |
| 1.11, 6.4 witness on every request | 3.1 writes-only matcher, `LEDGER_GATEWAY`; 5.3; G9 |
| 1.12 token expiry | 3.3 leeway, refresh at 4 min, 3.1 redirect |
| 2.1 occurred_at set by apps | 6.4 `ledger.emit` |
| 2.2 stale window | 4.2 rule 7 |
| 2.4 platform events, delete | 6.4 `core.outbox`, delete drain |
| 2.5 privacy | I10, 7.5, D9-D10 |
| 2.6 ordering | I11, 7.4 |
| 2.7 concurrency | T24, 7.2; M9 |
| 2.9 backup, rotation | T21, T22, 7.3 |
| 2.10 superuser delete | 7.3, section 10 |
| 3.1 database creation | 7.1, L1; M1-M5 |
| 3.3 ORM RETURNING | 6.4 `ledger.emit` |
| 4.4 store tests | 6.1 test hooks; 04-test-plan |
| 4.5 witness tests | 6.1 `witness(headers=...)`; 04-test-plan |
| 4.7 relay tests | 4.2; 04-test-plan |
| 4.9 export without a trust root | 6.3 export with proofs and a signed state |
| 4.12, 4.13 coverage discovery | 4.1 `routes` by file and function; 04-test-plan C1 |
| 4.14 coverage only declarative | I7 static check |
| 5.1 no real-Caddy test | 04-test-plan G-suite (the spike becomes a test) |
| 5.2 I6 untested | 04-test-plan F-suite |
| 6.1 riskiest last | done: `06-spike.md` |
| 6.2 skips | section 9 |

Second review (`07-second-review.md`):

| Finding | Where |
|---|---|
| N1 database names against the pool | 6.1 `naming`, `ledger.pool`, `provision`; tests `test_ledger_provision.py`, `log_of` |
| N2 `enforce` before the project | tests: projects are made through the witness (`through_gateway`, `make_project`) |
| N3 action id bound on first use | 4.5 rewritten; relay tests for a multi-action first request and a step-1 submit |
| N4 who computes digests | 4.2 rule 9, 6.4; relay and privacy tests |
| N5 one global key | I10, T22, 6.1 `secrets`/`actors`, 6.3 export, 7.5; privacy tests PR1-PR8 |
| 6.2 skips bypassing `LEDGER_TESTS_REQUIRED` | 9; the ledger suites use `needs_db` (a fixture), not the platform's collection-time `skipif` |
| n1, n3, n4, n11 | witness test counts records; 6.4 delete rule; witness 302 test; 6.4 `emit` list |

Third review (`08-third-review.md`):

| Finding | Where |
|---|---|
| M1 phase-1 provisioning tests needing phases 2-3 | `test_ledger_provision.py` (phase 1, no HTTP) and `test_ledger_provision_flow.py` (phase 3) |
| M2 exact relay counts, `override` semantics | 6.1 `override` merges; R1 counts its own request's entries; a registry test pins the merge |
| M3 P4 against the delete rule | P4 blocks on a project-DB row; a new test shows platform-DB rows never block |
| M4 shared state, whole-database relay | 6.1 relay: missing database is pending + alarm per project; tests clean exactly the rows they recorded |
| n-a to n-j | `own_store` order; 6.4 `extra`; pool `server_id`, assign in the creation transaction; 4.5 wording; `state` key; versions kept; mapping MAC with name, uniqueness, platform scope, pid case; retention; keys read per call; export negative check |

Fourth review (`09-fourth-review.md`, 0 blocker, 0 major): minors 1 (cleanup by recorded ids,
per statement, reported; `test_ledger_cleanup.py`; PF4 checks its own project), 2 (`origin`), 3
(fresh subjects, `scope` never NULL), 4 (assign contract), 5 (labels, `ledger.pool`), 6 (random event
ids, per-log uniqueness) are closed in the sections above.

The minors are in the same sections, or in `04-test-plan.md` where they are test changes. Section 3.5
of 01-plan and the test file names are made consistent with this file (R3.5).

## Open items

- ~~S1~~ settled: section 3.1.
- **S2** Next.js action names at build time (4.5).
- ~~S3~~ settled in phase 1: immudb `--signingKey` with immudb-py `publicKeyFile`, tested.
- **S4** the real oauth2-proxy and Preferred-Username (G3): check the header it returns.
- **S6** whether a conditional branch of a server action needs registry support beyond `caused_by`
  (section 4.5 limits): decide from phase 5's real actions.
- ~~S7~~ settled in phase 1: the `immudb-uuid` of a login-free `Health` call, with a 5 s deadline.
- ~~S8~~ decided 2026-10-02 (the user delegated it): `inspector_ro` (pgAdmin, SchemaSpy) reads every
  table it can connect to through `pg_read_all_data`, which can't be narrowed per schema. So the one
  table that names people, the mapping `actor(scope, actor_ref, sub, name, mac)`, lives in its own
  database **`ledger_identity`**, owned by `platform_rw`, with CONNECT revoked from PUBLIC and never
  granted to `inspector_ro` or any module role; made by the init files like the `ledger` schema.
  Everything else stays in the platform database's `ledger` schema: the witness records, the index
  and the page views hold only random references, so an admin inspecting them learns no name.
  Phase 3 builds it; `test_ledger_privacy.py` checks it.
- ~~S9~~ settled in phase 4 (2026-10-02): the export from immudb itself. immudb signs its own state
  (the accumulated hash of its last transaction), not the platform's chain. So the export carries
  every transaction of the log's database, 1..N, with its entries' digests, then each ledger entry
  with the transaction that wrote it, then the state immudb signed. The checker recomputes each
  transaction's entries root and accumulated hash, chained from sha256(""), requires the last to be
  the signed state (ECDSA over db, tx id and hash, as immudb-py's `State.Hash`), and requires every
  `e:<seq>` key of every transaction to be in the file with that exact value, numbered 1..N: nothing
  can be changed, added or left out without the signing key. The platform runs the same checks
  before handing the file out, plus one more: the chain must pass through the state it verified
  (`platform_service/ledger/immudb_proof.py`, `ImmudbLedger.export`). Header version 1 only
  (immudb 1.11); another version is refused, never guessed.
- **S5** M8, SQL privileges lost after another database's grant. Not needed (we use key-value);
  worth an upstream issue.
