# Ledger: specification (2026-10-02)

Companion of `01-plan.md` (the design) and `../ledger-events-2026-10-02/01-event-registry.md` (every
event). This file is what the tests (`04-test-plan.md`) check. Decisions D1-D8 and W1-W5 are at their
defaults (`01-plan.md` section 11) until the user changes them: **ASSUMED**.

## 1. Invariants

| # | Invariant |
|---|---|
| I1 | No state-changing request reaches an app without a witness entry. In `enforce` mode a request whose token is missing, malformed, wrongly signed, from another issuer or expired never reaches the app (401). |
| I2 | No app can choose who acted. The actor of every event is copied from the witness entry its `request_id` names, or from the service token for system events. Any actor-like field an app sends is ignored, and its presence is itself recorded (`ledger.rejected`, reason `actor_supplied`). |
| I3 | Every event is recorded exactly once. A replay of the same `event_id` is a no-op; a relay crash at any point loses nothing and duplicates nothing. |
| I4 | Nothing written to a ledger can be changed or removed without the verifier noticing: every read the platform shows is a verified immudb read, and the platform's last verified state per project only moves forward. |
| I5 | A change made directly in a project database (outside the apps) is detected: the verifier recomputes the canonical content of the evidence rows and compares it with the latest frozen content. |
| I6 | When the platform, immudb or the relay is down, no event is lost; writes are refused in `enforce` (W2) and let through but marked in `record`. |
| I7 | Every state-changing route of every app is covered: it maps to at least one registry action, and every registry action names the routes allowed to cause it. A new route without one fails the build. |
| I8 | No secret ever reaches the ledger: tokens, passwords, API keys appear only as fingerprints (`sha256:` of the value, first 12 hex). |
| I9 | One project's events never land in another project's ledger, and a member of one project can't read another's. |

## 2. Threats and the invariant that stops each

| # | Threat | Stopped by |
|---|---|---|
| T1 | An app writes a person's name into an event | I2 (actor from witness only) |
| T2 | An app cites another user's request id | witness match: the request's app (Caddy upstream) must equal the event's app (outbox `db_role` or service token), the route must be one the registry allows for the action, and the event must name an item that appears in the request path or body digest |
| T3 | An app cites an old request id | the window W3 (5 min) for user events; AI and worker events must cite a request whose action is the one that starts them (`ai.mapping.requested`, `engine.evaluation.run_requested`, ...) |
| T4 | A request id is used for more events than its action allows | the registry's `per_request` limit per action |
| T5 | A forged or expired token | witness verification (JWKS, issuer, audience, expiry, not-before) |
| T6 | A token for one project used on another project's path | the witness records the project from the path; the event's project is the outbox's database; they must match (I9) |
| T7 | An app edits or deletes its outbox rows | INSERT-only grant; `db_role` set by a trigger; delivery state in a platform-only table |
| T8 | Replay of an outbox row or an internal event | `event_id` idempotency key (I3) |
| T9 | Relay crash between the immudb write and the delivery mark | the write is idempotent on `event_id`; the mark is retried (I3) |
| T10 | Someone with DB rights rewrites evidence rows | I5 |
| T11 | Someone with immudb rights rewrites the ledger | immudb's own proofs + the platform's persisted verified state (I4) |
| T12 | The read index is altered to hide events | every shown entry is read back verified from immudb and compared with its index row (I4) |
| T13 | A secret leaks through `details` | the registry's allowed keys per action; a value matching a known secret pattern is replaced by its fingerprint (I8) |
| T14 | Clock skew between apps and the platform | `occurred_at` from the project database's clock, `recorded_at` from the platform; the window check uses the witness time and the outbox `occurred_at` of the same database server |
| T15 | Two writes of the same item at once | each is its own request and its own event; the content before/after hashes show the order |
| T16 | Events silently not emitted by an app | I7 coverage tests + the daily reconciliation (witnessed writes with no event) |

## 3. Modes

`LEDGER_MODE` on the platform: `off` (nothing happens; the default until phase 4 is deployed), `record`
(the witness verifies and records but never refuses; a bad token gives `request.unverified`), `enforce`
(a bad token is 401; a platform outage refuses writes through Caddy).

**Defence in depth**: in `enforce`, every app also refuses (401) a state-changing request that has no
`X-AISC-Request-Id`, so a request that reaches an app on the internal network without passing Caddy
changes nothing. The platform also checks that the id is one it issued (its witness index); the other
apps can't, and the relay rejects their events citing an unknown id (`unknown_request`).

## 4. Interfaces

### 4.1 Python package `platform/platform_service/ledger/`

- `naming.database_name(pid) -> str`: `"ledger" + uuid hex` (32 hex), refusing anything not a pid.
  The platform's own events (no project) go to `"ledgerplatform"`.
- `canonical.canonical(value) -> bytes`: RFC 8785 JSON canonicalisation (UTF-8, keys sorted by UTF-16
  code units, no insignificant whitespace, ECMAScript number form). `canonical.sha256_hex(value) -> str`.
- `secrets.fingerprint(value) -> str`: `"sha256:" + first 12 hex`.
- `registry.REGISTRY: dict[str, Action]` with `Action(name, step, apps, item_type, routes, paths,
  actor_kinds, details_keys, content_required, per_request, starts)`:
  - `routes`: where the code causes it, for the coverage test (I7): `(app, METHOD, path template as
    declared in that app's code)`, or `(app, "ACTION", "path/to/file.ts#exportedFunction")` for a
    Next.js server action;
  - `paths`: `(METHOD, regex)` of the public gateway path of the request that may cause it, for the
    relay's check (T2); an empty `paths` means the action has no user request (system, AI, worker);
  - `starts`: for an AI or worker action, the actions whose request it may cite (T3);
  - `per_request`: how many events of this action one request may produce (T4; `None` = no limit).
  `registry.check(event) -> list[str]` (problems; empty = valid). Problem codes: `unknown_action`,
  `missing:<field>`, `details_key:<key>`, `secret_in:<key>`, `actor_supplied`, `content_required`.
- `registry.KNOWN_APPS`: the app names of section 4.5.
- `platform_service.ledger.current() -> Ledger` and `platform_service.ledger.use(ledger)` (tests).
- `store.Ledger` protocol: `ensure(db)`, `append(db, entry) -> int seq` (idempotent on `event_id`:
  a second append returns the first seq), `get(db, seq) -> Entry` (verified), `head(db) -> Head(seq,
  state_hash)`, `scan(db, after_seq, limit) -> list[Entry]`. `store.ImmudbLedger(url, user, password,
  state_path)` and `store.MemoryLedger()` (tests). A verification failure raises `TamperAlarm`.
- `witness.witness(*, mode, token, method, uri, host, fetch_dest, now) -> Witnessed | None`: `None` when
  the request needs no witness (a GET that is not a document load). Raises `Unauthorised` in `enforce`.
  `Witnessed(request_id, project_pid, app, subject, name, method, path, verified, at)`.
- `relay.relay_once(pid, now=None) -> RelayStats(delivered, rejected, skipped)`; a rejected row
  becomes a `ledger.rejected` entry whose `details.reason` is one of `missing_request`,
  `unknown_request`, `app_mismatch`, `project_mismatch`, `stale_request`, `path_not_allowed`,
  `per_request`, `content_hash`, `unknown_action`, `actor_supplied`, `starts`.
- `verify.verify(pid) -> Report(entries_ok, entries_failed, evidence_ok, evidence_failed,
  witness_mismatches, outside_changes)`.

### 4.2 Entry (immudb table `event`)

`seq, event_id, occurred_at, recorded_at, project_pid, card_version, step, source_app, action,
actor_kind, actor_sub, actor_name, on_behalf_of_sub, program, model, request_id, reported_by,
item_type, item_id, item_version, before_sha256, after_sha256, content_sha256, evidence_ref,
depends_on, outcome, details`. `actor_*`, `on_behalf_of_sub`, `source_app`, `recorded_at` are always
set by the platform.

### 4.3 Routes

| Route | Who | Behaviour |
|---|---|---|
| `GET /authz/witness` (Caddy `forward_auth`, inside the `protect` snippet) | Caddy | reads `X-Forwarded-Method`, `X-Forwarded-Uri`, `X-Forwarded-Host`, `Sec-Fetch-Dest`, the token (`X-Auth-Request-Access-Token`, else `Authorization`); 200 + `X-AISC-Request-Id` (copied upstream by Caddy), 401 per mode |
| `POST /internal/projects/{pid}/ledger/events` | services (per-caller token `PLATFORM_LEDGER_<APP>_TOKEN`) | events of the engine, the dashboard, the AI services; each cites `request_id` |
| `POST /projects/{slug}/ledger/beacon` | the browser (witnessed) | `page.left`, `dialog.cancelled`, `unsaved_changes`, ...; ≤ 2 KB; `reported_by=browser` |
| `GET /projects/{slug}/ledger/events` | members | filters `actor, step, app, action, item_type, item_id, card_version, outcome, ai, from, to, cursor` |
| `GET /projects/{slug}/ledger/events/{seq}` | members | the entry, verified, with its witness |
| `POST /projects/{slug}/ledger/verify` | owners, admins | runs `verify` now |
| `GET /projects/{slug}/ledger/export` | owners, admins | JSONL of the entries + the head |
| `GET /ledger/projects` | admins | each project's head and last verification |

### 4.4 Outbox (project template `0020_ledger_outbox.sql`)

Schema `ledger`: `outbox(event_id uuid pk, occurred_at timestamptz default now(), db_role text, request_id
uuid, action text, item_type text, item_id text, item_version text, card_version uuid, content jsonb,
content_sha256 text, before_sha256 text, after_sha256 text, details jsonb default '{}', outcome text
default 'ok')`; a `BEFORE INSERT` trigger sets `db_role := current_user`; INSERT only for the module
roles (qualification, controls, control objectives, report composer, platform); no SELECT, UPDATE or
DELETE for them. `delivered(event_id pk, seq, delivered_at)` and `witness_index(request_id pk, ...)`
in `core` (platform only).

### 4.5 App mapping (who `source_app` is)

| `db_role` / token | app |
|---|---|
| `qualification_rw` | qualification |
| `controls_rw` | controls |
| `control_objectives_rw` | control_objectives |
| `report_composer_rw` | report_composer |
| `platform_rw` | platform |
| `PLATFORM_LEDGER_ENGINE_TOKEN` | engine |
| `PLATFORM_LEDGER_DASHBOARD_TOKEN` | dashboard |
| `PLATFORM_LEDGER_AGENTS_TOKEN` | qualification_agents |
| `PLATFORM_LEDGER_CATALOGUE_TOKEN` | catalogue |

Caddy upstream → app (for the witness): `/api/*` engine, `/controls*` controls, `/qualification*`
qualification, `/control-objectives*` control_objectives, `/report-composer*` report_composer, platform
`/api/*` and `/p/*` platform, the dashboard site dashboard, the rest webapp.
