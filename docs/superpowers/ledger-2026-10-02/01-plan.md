# An immudb log of everything, with certainty about who: plan (2026-10-02)

Status: PLAN, nothing built. Builds on the ledger plan of 2026-09-30
(`~/aisc-fresh-2026-09-29b/aisc/docs/superpowers/ledger-2026-09-30/01-plan.md`, "the 09-30 plan")
and the event registry of today (`../ledger-events-2026-10-02/01-event-registry.md`, "the registry").
Code base: `~/aisc-fresh-2026-09-30b/aisc`, branch `feat/unified-modules`.

## 1. Goal (user, 2026-10-02)

"make a plan to have immudb logs, which log with certainty who and solve the other problems".

Success means:
1. Every event of the registry lands, exactly once, in its project's own immudb log.
2. **Who** is never taken from an app's word. For a person it comes from a Keycloak-signed token the
   platform verified itself; for an AI or a worker it names the program and the person it acted for;
   for a browser-only moment it names the signed-in person and says the details are browser-reported.
3. The five problems found today are solved (section 8): missing authors, history destroyed, global
   logs, AI prompts kept nowhere, browser-only moments.
4. Anyone allowed can browse, filter and verify the log under Manage, and export it for an auditor.

## 2. Why today's "who" can't be trusted

- Apps write the user name they think is calling. Step 1 decodes a token **without checking its
  signature**; step 2 ignores the verified caller; the catalogue discards it; the engine writes
  "unknown" for workers; the dashboard writes a numeric id or a display name.
- Even a correct app could put any name in an event: the ledger would have to believe it.
- So certainty has to come from a component that **sees the person's signed token itself** and that
  the apps can't influence: the gateway and the platform.

## 3. The design in one paragraph

**Every request goes through the gateway (Caddy), and every state-changing request is witnessed by
the platform before the app sees it.** Caddy's `forward_auth` calls a new platform route,
`/authz/witness`, with the request's method, path and the user's access token (oauth2-proxy already
passes it). The platform verifies the token's signature and expiry against Keycloak, writes a
**`request.witnessed`** entry to the project's log (request id, person's subject and name, method,
path, app, time) and answers with a fresh **request id** that Caddy forwards to the app as
`X-AISC-Request-Id`. The app then records what the request did (an outbox row in the same database
transaction as the change) and **cites that request id; it never names a person**. The platform's
relay moves outbox rows into immudb, and **copies the actor from its own witness record**, after
checking that the action fits the request (right app, a route the registry allows for that action,
within a short time window). An event without a valid request id is recorded as `ledger.rejected`,
not trusted. AI and worker events cite the request that started them, so they name the program
**and** the person it acted for.

```
browser --(signed token)--> Caddy --forward_auth--> platform /authz/witness
                              |                         | verifies token, writes request.witnessed
                              |<--- X-AISC-Request-Id --|
                              v
                             app  --same transaction--> outbox row {action, item, before/after, request_id}
                                                           |
                                    platform relay <-------+  actor := witness(request_id).person
                                           |
                                           v
                                  immudb ledger_<project>   (+ evidence store for content and files)
```

## 4. How each kind of "who" is established

| Kind | Example | Where the identity comes from | Recorded as |
|---|---|---|---|
| A person, through the browser or the API | rating a risk, saving links, generating a report | the platform verifies the Keycloak token at the gateway (`request.witnessed`) | `actor_kind=user`, subject + name from the token |
| An AI agent | Suggest with AI, card refinement, control ingest | the agent's own service token names the program; the event cites the request that started it | `actor_kind=ai`, `program`, `model`, `on_behalf_of` = that request's person |
| A worker | a test run's plugin steps | worker service token; cites the run's request | `actor_kind=worker`, `on_behalf_of` |
| The platform or an app on its own | provisioning, a target sync on save, startup retries | the per-caller service token (`scripts/secrets.sh`) | `actor_kind=system`, `program` |
| A browser-only moment | page left with unsaved changes, a dialog cancelled | the beacon request is itself witnessed (the person is certain); its details come from the browser | `actor_kind=user`, `reported_by=browser` |
| Sign-in and sign-out | | Keycloak's own login events, read by the platform | `actor_kind=user`, `reported_by=keycloak` |
| Operators | CLI rotation, migrations, isolate tool | the command runs a `ledger note` step with the operator's name, marked unverified | `actor_kind=operator`, `verified=false` |

What stays outside: someone with database superuser rights could change rows directly. That can't be
prevented here, but it is **detected**: the verifier (section 9) compares the current evidence tables
with the latest frozen content in the log and raises "changed outside the app".

## 5. What gets logged

The whole registry (`../ledger-events-2026-10-02/01-event-registry.md`): about 180 events over
Manage and steps 1 to 6. Each entry carries the fields of the registry's first section, plus
`request_id` and, for AI and workers, `on_behalf_of`.

- **Page opened** comes from the witness: Caddy also calls the witness for top-level page loads
  (`Sec-Fetch-Dest: document`), not for scripts, images or background API reads.
- **Reads that matter** (downloads, exports, a report viewed, an older version viewed) are events of
  their own, emitted by the app.
- **Content** (before/after of what changed) is hashed in the log and frozen in the evidence store.

## 6. Storage

As the 09-30 plan, sections 5 and 7.3, with two changes:
- **One immudb database per project** (`ledger_<pid hex>`), written and read only by the platform
  with its own immudb user (`aisc_ledger`, not the superuser; generated password in
  `scripts/secrets.sh`). The superuser password committed in `env.development` is rotated.
- **Evidence store**: small canonical JSON (RFC 8785) inside immudb; files (artifacts, PDFs, plot
  images, AI prompts and answers above 256 KiB) in a MinIO bucket `evidence` with Object Lock in
  compliance mode and versioning.

## 7. How events travel

- **Outbox** (09-30 plan 7.1), for every app with a project database: qualification, controls,
  control objectives, report composer, platform. INSERT-only grants, a trigger stamps `db_role`, so
  the app is known for certain too. New column `request_id`.
- **Witness** route `POST /authz/witness` (new), called by Caddy `forward_auth` on every non-GET
  request and every document load under `/p/`, `/control-objectives/p/`, `/controls/p/`,
  `/report-composer/p/`, the engine and the dashboard. It answers 401 to a bad token (the request
  never reaches the app), 200 with `X-AISC-Request-Id` otherwise. Witness entries go straight to
  immudb.
- **Internal route** `POST /internal/projects/{pid}/ledger/events` (09-30 plan 7.2) for the engine,
  the dashboard and the AI services, which have no outbox transaction; per-caller tokens; the event
  cites its request id.
- **Beacon** `POST /p/{slug}/ledger/beacon` for browser-only moments: a 1 KB script shared by every
  app (sends `page.left`, `dialog.cancelled`, `unsaved_changes`), itself witnessed.
- **Correlation**: the request id travels with the work it starts: the AI services, Celery headers,
  the report renderer get it as `X-AISC-Request-Id` and cite it.

## 8. The five problems, and their fixes

### 8.1 Missing or unreliable authors
Solved by the witness (section 3): the ledger never takes a name from an app. In addition each app
stores the subject on its own rows where it is missing, so its pages can show it:
qualification (card, corrections, component links, retirements), control objectives (drafts, ratings,
mappings, keys: use `request.state.caller.subject`, not the username), catalogue (`reviewed_by`,
`submitted_by`), dashboard (subject, not a display name).

### 8.2 History destroyed today
| Where | Today | Fix |
|---|---|---|
| Controls: question review | deletes the answers of **closed** submissions | questions become versioned: a review makes a new checklist version; closed submissions keep pointing at theirs |
| Controls: draft save | answers deleted and recreated | update in place; every save also frozen in the log |
| Report composer: layout delete | deletes its generated reports and documents | soft delete for layouts; generated reports never deleted (RESTRICT) |
| Report composer: layout update | old revisions lost | keep every revision (append-only table) |
| Step 2: Suggest with AI | deletes the previous run and the assessor's own rows | runs kept (`mapping_run` keyed by run id); a new run never removes `person` rows |
| Step 2: assessment delete | cascades everything, any version | only the latest version, and soft delete |
| Step 1: AI draft, corrections, links | overwritten | append-only history tables; the "archive" the code promises is built |
| Step 1: knowledge graph | rewritten on a page view | rebuilt only on change; older versions never rewritten |
| Engine: settings, files, configs | overwritten in place | via D3, events with before/after hashes; files frozen in the evidence store on upload |
| Catalogue | hard deletes, review overwritten | soft deletes; review decisions as their own rows |
| Dashboard: comments, reviews | hard delete, status overwritten, admin views bypass the API | soft delete; status history; admin edit views removed for viewers |
| Step 4 links | removal hard-deletes | removal recorded in the log (the before/after of each save) |

### 8.3 Global logs
The engine's `auditdb` and Superset's `superset_audit` stop being the record. The engine forwards to
the project log (D3); Superset's comment, review and chart events move to the project log, and page
views are taken from the witness instead (D6). The old tables are left read-only.

### 8.4 AI prompts and answers kept nowhere
Every model call (step 1 agent, step 2 Suggest with AI, catalogue ingest, LLM plugins through the
connections facade) emits `ai.llm_call` with model, purpose, prompt and answer hashes; the prompt and
the answer themselves are frozen in the evidence store (personal data per D5). The step 1 agent's run
result moves from memory to its database.

### 8.5 Browser-only moments
The shared beacon (section 7), witnessed, marked `reported_by=browser`.

## 9. Verification, anchoring, export

As the 09-30 plan section 8, plus:
- **Witness check**: every event's `request_id` must exist in the same log, by the same app, within
  the window; an event whose request is missing or mismatched raises an alarm.
- **Outside-the-app check**: the verifier recomputes the canonical content of the key evidence rows
  (cards, answers, ratings, mappings, links, reports) and compares it with the last frozen content in
  the log.
- **Report anchoring**: every generated report prints the log head; generation refuses an input that
  fails verification.

## 10. The Logs panel

As the 09-30 plan section 9, under Manage, "Audit" > "Activity log": newest first, filters (person,
step, app, action, item, card version, outcome, AI only, dates), entry view with the frozen content
and the request it came from, "Verify", "Export for audit". The witness makes "everything this person
did" and "everything that led to this report" exact queries.

## 11. Decisions needed

The 09-30 plan's D1-D8 stand with their defaults (D1 who sees the panel: every member; D2 log kept
after project delete; D3 engine forwarding by one registered exception; D4 10-year lock; D5 personal
data frozen in the evidence store, hashed in the log; D6 Superset page views out of immudb; D7 fix
the defects before each app's phase; D8 immudb in staging and production). New:

| # | Decision | Default |
|---|---|---|
| W1 | Witness every state-changing request at the gateway (adds one platform call per write) | Yes; reads only for page loads |
| W2 | What happens when the platform is down | Writes are refused (fail closed): no unwitnessed change. Reads still work |
| W3 | Event window between witness and app event | 5 minutes; long work (AI, runs) cites the request and is matched by correlation, not time |
| W4 | Full AI prompts and answers frozen | Yes, in the evidence store, under D5 |
| W5 | Operator actions (CLI) | Logged as `operator`, unverified, with the OS user and host |

## 12. Phases

TDD in every phase, throwaway Postgres and immudb only, local commits, nothing pushed, a deploy needs
a yes. Stop and report at the end of every phase and on any red isolation, frozen-guard or
service-token suite.

| Phase | Content | Done when |
|---|---|---|
| 0 | D1-D8 and W1-W5 answered | recorded here |
| 1 | Ledger core (platform): per-project immudb, `aisc_ledger` user, registry, canonical JSON, idempotent writer, verified reader | platform ledger tests green |
| 2 | **Witness**: `/authz/witness`, Caddy `forward_auth` on writes and page loads, request ids forwarded, `request.witnessed` | a write with a forged or missing token never reaches an app; every write has exactly one witness entry |
| 3 | Outbox + relay with actor from the witness; platform's own events (Manage, projects, card versions, step 4) | an outbox row citing a wrong or missing request is rejected; the actor can't be set by an app |
| 4 | Logs panel and export | route and page tests; browser check after a deploy yes |
| 5 | Step 1 (qualification + agents): emitter, history tables, agent runs persisted, AI calls | each action writes exactly one event in its transaction; an AI event names the agent and the person |
| 6 | Step 2 (control objectives): emitter, runs kept, assessor rows kept, authors by subject | as above |
| 7 | Steps 3 and 4 (catalogue, controls app): emitters, checklist versions, soft deletes, AI ingest calls | closed answers survive a question review |
| 8 | Engine and workers (D3): forwarding with request id and Celery correlation | frozen guard green with the one registered file |
| 9 | Steps 5 and 6 (dashboard, report composer): events, soft deletes, layout revisions, report anchoring | a report prints a head that the offline checker accepts |
| 10 | Beacon, Keycloak login events, evidence bucket with lock, verifier (witness and outside-the-app checks) | altering a row directly in Postgres raises the alarm |

Phases 1 to 4 give a working log with certain identity for every write. Phases 5 to 9 are
independent of each other once 3 is in.

## 13. Out of scope

Signing PDFs and external timestamps; migrating the old global logs (they have no project and their
actors can't be trusted); container logs.
