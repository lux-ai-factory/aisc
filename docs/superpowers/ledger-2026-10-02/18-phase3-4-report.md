# Ledger: phases 3 and 4 report, emit, relay, panel, export (2026-10-03)

Phases 3 and 4 of `03-coding-plan.md`, their independent reviews (`16-phase3-review.md`,
`17-phase4-review.md`) and the fixes. All commits are on `feat/unified-modules` (aisc), local and not
pushed:

| Commit | What |
|---|---|
| 04b8160, 6b44233, e3ab8e5 | phase 3: the outbox in every project database, the relay, the platform's own events, the delete drain |
| b44e7d0, 430e6eb | phase 4: read routes, export and checker, admin heads and re-anchor, internal route, beacon, Activity log page |
| 790bf57, db20318 | the phase 3 drills (opt-in), timed on a monotonic clock |
| dc47757 | S9: the export from immudb itself; a stale gRPC client dropped after an outage |
| f6a4f83 | phase 4 review fixes: B1, M1 to M6, minors |
| 2901e81 and the commit after this report | phase 3 review fixes |

**Nothing is deployed.** The running stack is untouched, apart from one thing already noted in phase 2:
Caddy bind-mounts the repo's `Caddyfile`, so its next restart loads the new one. With `LEDGER_GATEWAY`
unset, a test proves that gateway is the old one plus the header strip and the `/api/authz/*`
allow-list.

## What was built

| Part | Where | What it does |
|---|---|---|
| project outbox | `platform/project-template/0020_ledger_outbox.sql`, `0021` | `ledger.emit(jsonb)`, SECURITY DEFINER: stamps the role and the time, refuses the platform's own actions; `pg_temp` last on its path |
| platform outbox | migration `0008`, `ledger/outbox.py` | `core.outbox` for the platform's events, in the change's transaction |
| relay | `ledger/relay.py` | every check of spec 4.2 to 4.5. A bad row is a rejection (`unencodable`, `too_large`, `duplicate_event_id`) and never stalls its log, and one log's failure never stops another. Reads are batched in time order; each log takes a try-lock on a connection of its own |
| relay worker | `ledger/worker.py`, the app's startup hook | a pass every 5 s over every log (idle while `LEDGER_MODE=off`), and a daily page-view expiry |
| verifier | `ledger/verify.py` | entries, item chains (key rotations compared on the frozen states), action-id conflicts, witnessed writes with no event, index rows that disagree or are missing |
| platform events | `db.py`, `llm_store.py`, `connection_store.py`, `connection_allowlist.py`, `targets.py` | covers projects, members, card versions, LLM providers and choices, connections (saved, linked, deleted, tested: the result only) and allowed hosts, plus target syncs, each in its change's transaction. A target sync gets one of its own, after its calls to the engine. Base URLs are logged without query or user part |
| delete drain | `app.py` `_ledger_drain_or_refuse` | revokes CONNECT from every grantee, refuses while another role holds a session (409) or when the count fails (503), and restores the grants on any refusal |
| read routes | `app.py`, `ledger/index.py` | the list and one entry, verified against the store. The index must account for every seq and is compared column by column, the filter columns included |
| export | `ledger/export.py`, `ImmudbLedger.export`, `ledger/immudb_proof.py` | on immudb: every transaction 1..N with its entries' digests, each entry, and immudb's signed state, all checked by the platform before the file leaves |
| offline checker | `scripts/verify-ledger-export.py` | trusts only the public key it is given. It recomputes every transaction and the signed state, requires every `e:` key, checks contents by default, refuses duplicate keys, NaN, unknown fields and mixed projects, and names the log and project (`--log`, `--project`) |
| admin | `GET /ledger/projects`, `POST /ledger/reanchor` | heads per log, both verified and as the server holds them. A re-anchor checks the head the admin saw, records first and otherwise changes nothing; the platform log comes first |
| internal route | `POST /internal/projects/{pid}/ledger/events` | per-caller tokens (equal tokens are refused), size caps, `outcome` limited to ok and failed, `registry_version` kept, a re-sent id with other content refused (409) |
| beacon | `POST /ledger/beacon`, `ledger/pageviews.py`, migrations `0009`, `0010` | witnessed in every mode, 2 KB (streamed), `page.*` only, the registry's keys with short scalar values, one per request, a per-person rate; kept in Postgres, never in immudb |
| page | `homepage/logs.html`, Manage > Audit > Activity log, `assets/ledger-beacon.js` | thin, `textContent` only, export for owners and admins |
| gateway | `Caddyfile` | the launcher's `/api/authz/*` block is an allow-list: everything is closed except the pages' role route |

## Tests (`LEDGER_TESTS_REQUIRED=1`: a skip is a failure)

| Suite | Result |
|---|---|
| `platform/tests/ledger` (all phases) | see the last section |
| repo-level ledger tests (`test_ledger_{caddy,caddy_equivalence,gateway,pages,credentials,pool_script}.py`, `test_compose.py`) | 141 passed (with `pyyaml`) |
| `test_ledger_coverage.py` | red by design: C1 and C4 wait for each app's phase. See open item 1 for the platform's case |
| platform suite without `tests/ledger` | see the last section |

**How the tests were checked.**
- **Mutations:** 40 of my own were applied one at a time with the named tests run, and every one was caught. Two first survived and their tests were made stronger: the re-anchor's head check, and the export's entries root. The reviewers ran 31 more; the ones that survived are now covered by tests.
- **Real store:** the export runs on a real immudb with its signing key. The checker refuses an edited entry, a dropped entry or transaction, a changed digest, another state or database, and another key.
- **Page:** the Activity log was rendered in headless Chrome against a stub API. This found the `hidden` bug, which would have shown the export link to every member.

## Drills (real immudb 1.11.1 with its signing key, state in Postgres)

| Drill | Result |
|---|---|
| relay killed with SIGKILL mid-batch, three times | 82 entries, numbered with no gap, each event once |
| two relays at once on one project | 62 entries, numbered with no gap, each once |
| immudb stopped for 10 minutes (awake, monotonic clock), people working throughout | 20 rounds; pending rose from 6 to 120, nothing was rejected; after the restart 132 entries, each once |
| an export checked offline | route-level test on immudb, checker exit 0 with `--check-content` |

**What the outage drill found.** After a long outage, the store's cached gRPC clients stayed in
reconnect backoff (up to about 2 minutes) after immudb was back. An unreachable answer now drops the
client. The first re-run seemed to pass in 241 s, because the laptop slept during it and the drill
timed the outage on the wall clock. It now uses a monotonic clock and was re-run for a real 10
minutes.

## Reviews and what was done

- **Phase 4 (`17`):** B1, M1 to M6 and the minors are fixed (f6a4f83). m8 and m9 went with S9.
  m10 (more beacon moments, the witness record on one entry, a verify route, alarms in the admin
  view) and m14 (batched reads) moved to named phases in the coding plan.
- **Phase 3 (`16`):**
  - fixed: B1, M1 to M5, M7, and minors m1, m3 to m6, m8, m9, m11, m12 and m15;
  - m2 (check order), m7 (inspector) and m9 (forwarded ids) are written into the spec as built;
  - M6 is fixed apart from `evidence.links.saved`, see open item 2;
  - m10, m13 and m14 are recorded below.

## Open items, with what they need

1. **C4 for the platform (decision).** The test wants each route handler to call the emitter itself.
   The platform emits in its data layer, in the same transaction as the change, which the spec
   requires. Proposal: let C4 follow one call level and match `outbox.emit*`, and give the
   platform's actions their `routes`. Say yes and I do it.
2. **`evidence.links.saved`.** It is not emitted yet, because another session is changing
   `evidence.py` (step 4 test tiles, uncommitted). It goes in once that work lands.
3. **Deleting a project while the apps run (decision, before `record`).** The control-objectives app
   keeps a pool of 2 connections per project database. `platform_rw` can't end another role's session,
   so a delete is refused (409) while those connections live. Before this change the
   `DROP ... WITH (FORCE)` failed in the same situation, with a privilege error and a 500.
   - Proposal: `postgres-setup` grants `pg_signal_backend` to `platform_rw`. The drain then ends the
     apps' sessions itself, after revoking CONNECT and before counting.
   - The other option is an "evict project" call to each app, like the dashboard's.
4. **D12**: who posts the engine's events, since `aisc-backend` imports plugins (phase 8). **L3**:
   where the locked archive lives (phase 10). **S2, S4, S6** stay open, as in the spec.
5. **Recorded minors.**
   - m10: the platform-only action list is filled at provisioning (the relay still refuses as `emitter`).
   - m13: the reconciliation's cause near-misses and pool level wait for phase 10.
   - m14: the relay's statistics are approximate.
   - Flakes: `test_tg2` (token timing, from before the ledger); a teardown drop once raced a closing session.

## To deploy, when you say so (adds to the phase 2 order in `14-phase2-report.md`)

1. Phase 2's steps 1 to 3.
2. Rebuild and recreate `platform`. It migrates 0006 to 0010 and the project template to 0021, and starts the relay worker, which is idle while `LEDGER_MODE=off`.
3. Decide item 3, before turning on `record`.
4. `LEDGER_MODE=record` and `LEDGER_GATEWAY=on`; run phase 2's two drills on the real stack.
5. Then in a browser: the Activity log on a project, the export as an owner, and the checker on the file with `--public-key immudb-signing.pub`.

## Final runs (2026-10-03, on the last commit)

| Suite | Result | Skips |
|---|---|---|
| `platform/tests/ledger` | 585 passed, plus 1 cleanup error (the session-end drop raced a closing session; the cleanup now retries as the superuser) | 3: the opt-in drills, run separately above |
| platform suite without `tests/ledger` | 587 passed, 1 failed (`test_tg2`, the known token-timing flake) | 2 (pre-existing) |
| repo-level ledger tests | 141 passed | 0 |
