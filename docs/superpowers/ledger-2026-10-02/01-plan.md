# An immudb log of everything, with certainty about who: plan (2026-10-02)

Status: PLAN, nothing built. **Version 2** (2026-10-02, after the review `05` and the spike `06`):
sections 3, 5, 6, 7, 11 and 12 changed; `02-spec.md` is the precise statement and wins where this file is shorter. Builds on the ledger plan of 2026-09-30
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
the platform before the app sees it.** Caddy's `protect` snippet, imported by each handle with the
app's name, strips any identity or request-id header the client sent, signs the person in through
oauth2-proxy, then for a write calls the platform's `/authz/witness` with a gateway secret, the app's
name and the unstripped path. The platform verifies the Keycloak token itself, writes a witness record
(request id, a pseudonymous reference to the person, app, route, project, Next.js action id, time) to
its Postgres, and answers with the **request id**, which Caddy forwards as `X-AISC-Request-Id`. The app
records what the request did by calling `ledger.emit(...)` in the same transaction as the change; it
**cites the request id and never names a person**. An app that calls another app on the person's
behalf forwards the id with the person's token. The relay moves witness records and outbox rows into
the project's immudb log and **copies the actor from the witness record**, after checking that the
event fits the request: an app and route the registry allows for that action, the same action id, the
same project, the same item when the route names it, inside the window. Anything else becomes
`ledger.rejected`. AI and worker events cite the start event of their run, so they name the program
**and** the person who started it.

What this proves, exactly: the actor is a person who made a matching witnessed request (`02-spec.md`
section 0). An app can't invent a person; a compromised app could still swap two matching requests,
and reconciliation flags the traces that leaves.

```
browser --(signed token)--> Caddy protect <app>: strip, sign in, witness (writes only)
                              |  --forward_auth + gateway secret--> platform /authz/witness
                              |                                       verifies token, ledger.witness row
                              |<----------- X-AISC-Request-Id --------|
                              v
                             app --same transaction--> SELECT ledger.emit({action, item, request_id, ...})
                              |  (calls another app with the person's token + the same request id)
                              v
                     platform relay (per-project lock): checks the binding, actor := witness person
                              |
                              v
                     immudb ledger<pid hex> (key-value, verified)   + evidence store for large content
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

- **Page opened** is best effort: the shared beacon reports it (`reported_by=browser`), kept in
  Postgres for 90 days (D10), never in immudb. The witness doesn't see page loads, so reads keep
  working when the platform is down.
- **Reads that matter** (downloads, exports, a report viewed, an older version viewed) are witnessed
  routes listed per app, and events of their own, emitted by the app.
- **Content** (before/after of what changed) is hashed in the log and frozen in the evidence store.

## 6. Storage

As the 09-30 plan, sections 5 and 7.3, with these changes (spike M1-M16):
- **One immudb database per project** (`ledger<pid hex>`), used through the **key-value** API (SQL
  privileges proved fragile, M8). The platform holds only its own immudb user `aisc_ledger` (RW, never
  the superuser). Databases come from a **pool pre-created by an operator script** that holds the
  superuser (M1-M5; L1). The committed superuser password is rotated.
- One immudb client per database, each behind its own lock: a shared client wrote 18% of entries into
  the wrong database in the spike (M9).
- The verified state per database is kept in Postgres and only moves forward. A rollback or a rewrite
  is an alarm (M13, M14). Each project's signed head is published hourly to the object-locked bucket.
- **Evidence store**: entries up to 64 KiB canonical JSON (RFC 8785) inside immudb; anything larger
  (artifacts, PDFs, plot images, long AI prompts and answers) in a MinIO bucket `evidence` with Object
  Lock in compliance mode and versioning.
- **Personal data**: immudb holds a pseudonymous `actor_ref` (an HMAC of the subject); the mapping to
  the person is in Postgres and can be erased (D9).

## 7. How events travel

- **Witness** (`GET /authz/witness`): Caddy's `forward_auth` on writes and on listed reads, with the
  gateway secret; never reachable from a browser or another container without it. Records go to
  Postgres `ledger.witness`, then the relay copies them to immudb (the request never waits on
  immudb). Only switched on in Caddy with `LEDGER_GATEWAY=on`.
- **Outbox**, for every app with a project database (qualification, controls, control objectives,
  report composer, platform): the app calls `ledger.emit(...)` in its transaction. The function stamps
  the database role and the time, so neither can come from the app. The platform's own member and
  project changes use `core.outbox` in the platform database.
- **Forwarded requests**: an app calling another app's write route on the person's behalf passes the
  person's token and the same request id; the registry's `caused_by` says which originating request
  may cause which event.
- **Internal route** `POST /internal/projects/{pid}/ledger/events` for the engine backend, the
  dashboard and the AI services; per-caller tokens, each bound to the actions it may emit; never held
  by a process that runs plugin code.
- **Runs**: an AI or worker run starts with a start event carrying a `run_id`; every event of the run
  cites it.
- **Beacon** `POST /ledger/beacon` on each site, `text/plain`, for browser-only moments and page views.

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

All defaults, **ASSUMED** until answered; the full list is `02-spec.md` section 11.
- From the 09-30 plan, D1-D8: D1 who sees the panel, every member; D2 log kept after project delete;
  D3 engine forwarding by one registered exception; D4 10-year lock; D5 personal data frozen in the
  evidence store, hashed in the log; D6 Superset page views out of immudb; D7 fix the defects before
  each app's phase; D8 immudb in staging and production.
- W1 witness every state-changing request at the gateway: yes, writes and listed reads only.
- W2 platform down: **witnessed requests (writes, listed reads) fail; everything else works**;
  immudb down blocks nothing (version 1 said "reads still work", which held only once page loads left
  the witness).
- W3 window 5 minutes between the witness and the event's database time; runs use their start event
  and a 24 h run window instead.
- W4 full AI prompts and answers frozen, in the evidence store, under D5.
- W5 operator actions logged as `operator`, unverified.
- New: D9 pseudonymous actors (yes); D10 page views best effort, 90 days; D11 non-members' requests
  in the platform log only; L1 a pre-created database pool; L2 a 64 KiB entry cap.

## 12. Phases

TDD in every phase, throwaway Postgres and immudb only, local commits, nothing pushed, a deploy needs
a yes. Stop and report at the end of every phase and on any red isolation, frozen-guard or
service-token suite. `03-coding-plan.md` has the detail.

| Phase | Content | Done when |
|---|---|---|
| 0 | spec, plan, tests; review; spike (done: `06-spike.md`); spec v2; second review | no open blocker |
| 0b | **Header strip** in Caddy `protect` (inside `route`), deployable alone: fixes G3 today | the Caddy suite (real Caddy) shows forged headers never reach an app |
| 1 | Ledger core: registry, settings, canonical JSON, key-value store with per-database clients, Postgres state, pool provisioning, signing key | platform ledger tests green, `LEDGER_TESTS_REQUIRED=1`, no skips |
| 2 | Witness: `/authz/witness`, gateway secret, per-app project rules, token rule, `witness-on` snippet | the real-Caddy suite green; a write with a forged or missing token never reaches an app |
| 3 | `ledger.emit`, `core.outbox`, relay with every binding check, forwarded requests, runs, platform's own events, project delete drain, reconciliation | a row citing a wrong request is rejected; the actor can't be set by an app |
| 3b | **Red team** (moved before the apps rely on it) | every finding becomes a test first |
| 4 | Logs panel, export with proofs, internal route, beacon | route and page tests; browser check after a deploy yes |
| 5-9 | Steps 1 to 6 and the engine, as in version 1, each with its static emitter check | as in version 1 |
| 10 | Keycloak login events, evidence bucket with lock, published heads, verifier | altering a row directly in Postgres raises the alarm |

Phases 5 to 9 depend on phase 3's `caused_by` and runs, not on each other.

## 13. Out of scope

Signing PDFs and external timestamps; migrating the old global logs (they have no project and their
actors can't be trusted); container logs.
