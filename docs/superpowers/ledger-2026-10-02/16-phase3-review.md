**Verdict: 1 blocker, 7 majors, 16 minors. Phase 3 is not done.** The binding checks of spec 4.2 are there and most of them are pinned by tests. `ledger.emit` is sound: it stamps `session_user` and the database clock, nobody else has rights on the table, and the platform-only actions are refused. What blocks the phase is how the relay copes with a bad row. One row it can't encode or append stops its log for good. For one kind of bad row it also aborts the relay for every project after it and for the platform log. The majors are: no relay process at all, a way to grow a server-action binding from rejected events, run events marked verified in record mode, holds that never expire, a delete race, missing platform events (C4 red), and two crash-safety and concurrency guards that no test pins.

## What I checked

Commits 04b8160, 6b44233 and e3ab8e5, plus the relay and outbox parts of b44e7d0 and 430e6eb. Later, while I worked, someone else committed 790bf57 (the drills) and dc47757 (immudb export). Neither touches `relay.py`, `outbox.py`, `verify.py`, the template or the delete drain. I made no commits and changed no files in the repo. A probe test file existed in `platform/tests/ledger/` for a few minutes and has been removed. My throwaway containers are `aisc-t-rev9-*` (Postgres 14 and immudb 1.11.1), torn down at the end. I never touched the live stack or 5432.

- **Ledger suite** (`LEDGER_TESTS_REQUIRED=1`, at 430e6eb): 495 passed, 9 failed, 3 skipped. The 3 skips are the opt-in drills. The 9 failures are all in `test_ledger_export_checker.py` (phase 4, immudb export), which dc47757 addresses. Every phase 3 file passes: `test_ledger_{outbox,relay,platform_events,failure,privacy,provision_flow}.py`.
- **C4 for the platform** (`scripts/tests/test_ledger_coverage.py -k platform`): fails with "the registry names no routes yet" (see M6).
- **Drills:** not run. They are opt-in and someone else was running them against their own env.
- **Probes** (a temporary test file using the suite's fixtures, run against my env). Every finding marked "confirmed" below comes from one of these:
  1. a big integer in `content`;
  2. a 70 KB `details` value under an allowed key;
  3. a stale event teaching a binding;
  4. a record-mode run;
  5. an event from a far-future registry version followed by a delete;
  6. a key rotation between two events of one item.
- **Mutations.** Each one was applied, then the relevant tests were run, then the file was restored. The first two ran in the shared tree and were restored with `git checkout` of the one file; `git status` was clean afterwards. Then I saw that other agents were committing and editing the same working tree. From then on I ran mutations only in an isolated copy (`git archive HEAD` into my scratchpad), so the shared tree was never mutated again. Results are in section 3.

## 1. Findings

### B1. One bad row stops its log for good; some bad rows stop the whole relay

`platform/platform_service/ledger/relay.py:129-140`, `:221`, `:233`, `:271-273`, `:105`. Also `platform/platform_service/app.py:270-273`.

`_relay_log` catches only `_Hold`, `LedgerUnavailable` and `UnknownDatabase`. Items run oldest first, so any other exception from an item is raised again by that same item on every later run:

- **`canonical()` errors (`ValueError`/`TypeError`).** `_row_digest` (line 221) and `secrets.content_digest`/`state_digest` (271-273) run `canonical()` on what the app sent. An integer beyond 2^53 is a valid `jsonb` number, and so is a nanosecond timestamp (about 1.7e18) or a 20-digit id. So is `1e400`, which `json.loads` turns into `inf`. Any of these raises `ValueError`. This is not a `LedgerError`, so `relay_once(None)` does not catch it at line 105. The exception leaves `relay_once` entirely. No project after this one in pid order is relayed on that run, and neither is the platform log (line 107). **Confirmed:** with `content = {"n": 12345678901234567890}` in one project, `relay_once(None)` raised `ValueError: integer beyond 2**53` on two runs in a row.
- **`EntryTooLarge` from `append`.** `details` passes `details_key` when its key is allowed, and its values are not size-checked before the append. **Confirmed:** with a 70 KB `note`, `relay_once(pid)` raised `EntryTooLarge` on every run, and a valid second event of the same project was never delivered (0 of 1). Under `relay_once(None)` the error counts as one "pending" and the project never moves again.
- **`DuplicateEvent` in `_deliver_witness`** (line 194). A witness entry is rebuilt on every attempt and carries `registry_version`. A crash between the append and the `delivered_seq` update, followed by a deploy that raises `VERSION`, makes the rebuilt entry differ from the stored one. The rebuilt entry then poisons the log the same way.
- **Project delete.** `_ledger_drain_or_refuse` catches only `LedgerError`. For the first kind of bad row the delete answers 500 for good. For the other two it answers 409 for good. Either way the project can't be deleted.

Scenario: in `record` mode, the step-2 app stores a rating payload that holds a `time.time_ns()` value in `content`. From then on no project's events and no platform event reach immudb. Nothing is lost, since the rows stay in Postgres, but I6's "no event is lost while ... down" turns into "nothing is ever delivered", and the only alarm is an exception in a log.

Fix:
- Treat every per-item failure that isn't an outage as a rejection of that item, with its own reason: `unencodable`, `entry_too_large`, `duplicate_event_id`. Do the encoding inside `_judge` so it becomes `_Rejected`.
- Catch `Exception` around each project in `relay_once(None)` and log it, so one project can never stop another or the platform log.
- In `_deliver_witness`, catch `DuplicateEvent` and fall back to the index or the stored `id:` key.
- Add tests: an int beyond 2^53 in `content`, `details` and `before`; an oversized `details`; and the platform log still delivered when one project fails.

### M1. Nothing runs the relay

There is no loop, thread, task or CLI anywhere in `platform/`. `grep relay_once` finds only the delete drain (`app.py:271`) and the tests. Spec 7.2 says "The relay polls with backoff (1 s to 30 s) and holds at most `RELAY_CONNECTIONS` (4) project connections". `settings.RELAY_CONNECTIONS` exists but nothing uses it. The plan's phase 3 drills ("two platform workers") assume a running relay; the drills start it by hand.

Also, `_pending` (`relay.py:146-161`) loads every undelivered row of a log into memory with no limit. It does so while holding the log's lock, and inside an HTTP request when called from a delete.

Scenario: `record` is switched on as planned after phase 4 is deployed. Witness rows and outbox rows pile up and no log moves. The first project delete then drains thousands of rows inside one request.

Fix:
- A relay worker: a lifespan task or a separate compose service with a stop rule. It runs `relay_once(None)` with backoff and a cap of `RELAY_CONNECTIONS`.
- `_pending` reads in batches (`LIMIT n` per source, ordered by `occurred_at`).
- The delete drain gets a deadline.
- A test that the worker delivers with no explicit call.

### M2. A rejected event grows the server-action binding (spec 4.5 bypass)

`relay.py:292-293`, then the item, window and per-request checks at 294-303.

`_bind_action` runs before the `item`, `stale_request`/`early_event` and `per_request` checks. For the first request of an action id it appends the event's action to the binding whether or not the event is then accepted. Spec 4.5 says the binding is learned from the first request "that has accepted events".

**Confirmed:**
1. Request R0 with id `77aa` saves a draft, which is accepted.
2. Six minutes later the app emits `controls.submission.renamed` citing R0. This is rejected as `stale_request`, but `renamed` is now in the binding.
3. A different person's request with id `77aa` then carries a `renamed` event, and it is **accepted**. It should have been `action_id`.

So a compromised app can teach any action that `caused_by` allows for that page at any time after the first use, which defeats the per-id check entirely. The spec accepts that a compromised app "can teach it" on first use; this goes further, to any later moment.

Fix: decide the binding last. Collect the action, run every other check, and update `ledger.action_binding` only once the event is accepted. Make step 2 above a test.

### M3. Run events are marked verified when their start was not

`relay.py:328-329` (`"verified": True`).

`_judge_run` takes the person from the start event (`on_behalf_of_ref`) but always stamps `verified=True`. **Confirmed** in `record` mode with an unverified request:
- `ai.mapping.requested` is recorded with `verified=False`, as expected;
- the run's `ai.mapping.failed` is recorded with `verified=True`.

Spec 4.2 and R2.14: an event bound to an unverified request is `verified=false`. The ledger's claim (spec 0) is that a verified entry names a person who presented a signed token. A record-mode run breaks that claim for every AI and worker event, and record mode is exactly the period whose reconciliation decides the switch to enforce.

Fix: store `verified` in `ledger.event_index` (or read the start's witness record) and copy it onto run events. Test it with the probe above.

### M4. `HOLD_UNKNOWN` is not implemented; a held row blocks delete for ever

`relay.py:252-254`. `settings.HOLD_UNKNOWN` is unused (grep).

An unknown action whose `registry_version` is above `VERSION` is held on every run, with no time limit. Spec R2.12 says it is held for 24 h and then rejected. The version is the app's own number, so any emitter can hold any garbage row for ever. Held rows aren't delivered, so the delete drain counts them. **Confirmed:** with `registry_version=999999` and `occurred_at` three days back, the relay reports `held=1` and the admin's `DELETE` answers 409 "the log still has 1 undelivered events" on every try.

Also, internal-route events never set the `registry_version` column (`outbox.emit` has no parameter for it, and `app.py:1781` sends it to `extra`), so for them the hold never applies.

Fix:
- Reject as `unknown_action` once `occurred_at` is older than `HOLD_UNKNOWN`.
- Cap the accepted version (for example `VERSION + 1`).
- Store `registry_version` from the internal route.
- Test it with a row older than 24 h.

### M5. The delete drain can still lose a committed event

`app.py:261-281` and `projectdb.py:112-115`.

The check counts undelivered rows. Then `dashboard_bridge.unregister` runs, then `DROP DATABASE ... WITH (FORCE)`. Apps keep their connections and keep writing in between. A transaction that commits `ledger.emit` after the count is destroyed by the drop. I3 and R2.4 say "Undelivered events survive a project delete".

Separately, `except Exception: left = 0` (line 279) treats any failure to count as "nothing to lose". That includes a refused connection, `too many connections` or a lock timeout, and the drop then goes ahead.

Scenario: an admin deletes a project while an editor saves a rating. The rating's event commits 50 ms after the drain and is gone. Only a `witness_without_event` count is left.

Fix:
- First `ALTER DATABASE ... ALLOW_CONNECTIONS false` (or `REVOKE CONNECT`) and terminate the backends.
- Then drain and count. Refuse (409 or 503) when the count itself fails, unless the database is known to be absent (`pg_database`).
- Only then drop.
- A test with an open emitting transaction that commits between the count and the drop.

### M6. The platform's own events are incomplete, and C4 for the platform is red

The plan says phase 3 includes "the platform's own events", and its definition of done needs "C4 for its app". Today the platform emits only these: `project.created`, `project.deleted`, the three `member.*`, `card_version.created` and `llm.provider.saved` (`db.py:167,178,318,432,435,464`, `llm_store.py:123`).

The registry gives the platform these other actions, and their write routes exist but emit nothing:
- `llm.provider.removed`, `llm.choice.saved`, `llm.choice.removed`;
- `connection.saved`, `connection.deleted`, `connection.tested`;
- `allowlist.host.allowed`, `allowlist.host.removed`;
- `evidence.links.saved`, `targets.synced`.

In `record` every one of those writes becomes a `witness_without_event` alarm, and the reconciliation period can never be clean.

C4 can't go green as written:
- The registry has no `routes` at all (`registry.py`: 0 `routes=`), so `test_a_registered_handler_emits_its_action[platform]` fails on "the registry names no routes yet".
- `EMIT_CALL` doesn't match `outbox.emit(`/`outbox.emit_project(`.
- The emits live in `db.py`, not in the handlers that C4 reads.

Fix: emit the missing actions in their transactions, fill `routes` for the platform actions, and let C4 follow one call level (or match `outbox.emit*`). Alternatively move these actions out of phase 3 in the plan and say so.

### M7. Two guards of I3 and T24 are not pinned by any test

Mutation results (section 3):
- **`_indexed` short-circuit** (`relay.py:222-226`) replaced by `done = None`: all 41 tests of `test_ledger_relay.py` and `test_ledger_platform_events.py` still pass. Without it, a crash after `_index` and before `_mark` makes the next run judge the row again. For a `per_request=1` action the index already counts it, so the row becomes an extra `ledger.rejected` entry and is marked rejected while its accepted entry stays in the log. The crash test (`crash_after_appends = 2`) only crashes between the append and the index.
- **Advisory lock** (`relay.py:76`) replaced by `pass`: `test_two_relays_at_once_still_honour_per_request` still passes. Two threads on one log are serialised by something else (the memory store's own lock and the test's timing), so the test doesn't show that the lock does anything.

Fix:
- A crash hook between `_index` and `_mark` (for example `relay._after_index` raising once), with a `per_request=1` event, asserting one accepted entry, no rejection, and a `delivered` row that names the accepted seq.
- For the lock, a test that holds `pg_advisory_lock(hashtext('ledger-relay:'||log))` from another connection and asserts that `relay_once` waits, or that two processes on immudb keep `per_request` (the drill does the latter, but it is opt-in).

### Minors

- **m1. Blocking lock on a 4-connection pool** (`relay.py:72-80`, `db.py:77`). Spec 7.2 says `pg_try_advisory_lock`. The code blocks, and holds a pooled connection for the whole batch while each step takes a second one. A delete, a re-anchor and a relay run together can drain the platform pool (`max_size=4`). The witness shares that pool, so every witnessed write then stalls. Use try-lock (skip the log when it is busy) or a dedicated connection.
- **m2. Check order differs from spec 4.2** (`relay.py:251-263`). `unknown_action`, `emitter`, `actor_supplied`, `details_key`, `platform_field` and `secret_in` are checked before `missing_request`/`unknown_request`/`project_mismatch`/`cause`. "The first failing reason" therefore differs from the spec's list. The reasons are not wrong, only ordered differently. Either reorder, or update the spec to say that the content checks come first.
- **m3. False chain breaks after a key rotation** (`verify.py:124-130`). `before_sha256` and `after_sha256` are compared as strings across key versions. **Confirmed:** open to closed under v1, then closed to reopened under v1+v2, gives `chain_breaks == 1`. Compare under one version (re-digest from `ledger.content` with the newest key), or store the version and compare only digests of the same version.
- **m4. Run checks are loose** (`relay.py:315-326`). There is no lower bound, so an AI event that `occurred_at` before its start event is accepted if relayed after it. The start lookup is "first accepted event with this `run_id` and request", whatever its action. A non-start event sent first with the same `run_id` therefore shadows the real start, and the whole run is rejected as `run`. Require `occurred_at >= start.occurred_at - CLOCK_SKEW` and `start.action` with a non-empty `runs`.
- **m5. A replay after a crash is judged again** (`relay.py:227-237`). Between a crash after the append and the re-run, a key rotation or a registry change can change the verdict or the digest. The result is a spurious `duplicate_event_id`, or an accepted entry with no index row. Check the store's `id:` key (spec T9: "the immudb `id:` key is checked before every append") before judging, and index whatever the store already holds.
- **m6. No secret scan of `before`/`after`** (`registry.py:340-342`). Only `details` and `content` are scanned. `before` and `after` are digested for the entry, but stored in plain in `ledger.content`, which `inspector_ro` reads. Scan them too.
- **m7. `inspector_ro` reads the ledger's tables** (`init/inspector-role.sql:18`, test carve-out at `test_ledger_outbox.py:130`). Through `pg_read_all_data` it reads `ledger.outbox`, `delivered`, `action_binding` and, in the platform database, `ledger.witness`, `event_index` and `content`. Spec 6.4 says `inspector_ro` has "neither EXECUTE nor any table right". The test now skips the SELECT for it. Decide it (spec or grants) instead of carving it out silently.
- **m8. The internal route drops a re-sent id silently** (`app.py:1782-1789`). A second post with an existing `event_id` and other content is answered 202 and discarded. I3 says the same id with other content is an alarm. It also answers `{"queued": ...}` with 202 when `LEDGER_MODE=off`, when nothing was queued. The check-then-insert also races into a 500. Insert with `ON CONFLICT`, compare the digest, and record `duplicate_event_id`.
- **m9. Presented ids are checked only in `enforce`, and the route only for platform-born ids** (`app.py:57-82`, `95-99`). In `record` a forwarded `X-AISC-Request-Id` is used as `current_request` with no check, so a platform event can cite another person's request. For a forwarded id (`rec.app != "platform"`) only the subject is checked, never the route. Spec 4.3 says "The platform checks every presented id against the presenter's subject and route". Even the platform branch is untested: with it disabled, every test still passes (section 3). Add a test where a person presents their own id from another route.
- **m10. The platform-only list lives in a table filled at provisioning** (`0020_ledger_outbox.sql:48,65`, `projectdb.py:68-77`). The spec says it is generated into the template. An empty or stale `ledger.platform_action` (a project database migrated by an older platform, or a newly added platform action) lets `emit` accept a platform action. The relay still rejects it as `emitter`, so this is defence in depth only. The test checks a fresh project only.
- **m11. `emit`'s `search_path` has no explicit `pg_temp`** (`0020_ledger_outbox.sql:51`). It is safe today because every relation is schema-qualified and functions and operators are never looked up in `pg_temp`. Add `pg_temp` last as the PostgreSQL docs advise, so a later unqualified table name can't be shadowed by a caller's temp table. The function runs as `platform_rw`, the owner of the project database.
- **m12. Phase 2 m7 is not pinned** (`14-phase2-report.md:75-78`: "phase 3's relay must pin it with a test"). No test sends a case-changed or percent-encoded path and asserts `project_mismatch`/`item`.
- **m13. Reconciliation is partial** (`verify.py`, spec 7.4). There are no `cause` near-misses and no pool level. `missing_database` is computed by `verify` only, while spec 6.1 says the relay raises it. State which come later, or add them.
- **m14. Stats are approximate** (`relay.py:105-106,126-128`). A failed project counts as 1 pending, and a project with no database counts only its platform-side rows. Both are visible in the admin view later.
- **m15. `llm.provider.saved` keeps the raw `base_url_after`** (`llm_store.py:119-121`). An OpenAI-compatible URL can carry `?api-key=...`, which `_SECRET` doesn't recognise. Fingerprint the query, as the witness does, or drop it.
- **m16. There is no phase 3 report,** and the drills were untracked when this review started (committed later in 790bf57). The definition of done needs the drill results and the skip count in a report.

## 2. What holds (verified)

- **`ledger.emit`:**
  - it stamps `db_role := session_user` and `occurred_at` from the column default (`clock_timestamp()`), whatever was sent;
  - unknown top-level keys go to `extra` and the relay rejects them (`platform_field:*`, `actor_supplied`);
  - it returns void, and a rollback leaves no row;
  - the platform-only actions are refused;
  - app roles have no right on `outbox`, and non-emitters can't execute it.

  Tests pass, and the `dbrole` and `platformaction` mutations are in section 3.
- **Binding checks in the relay:** `missing_request`, `unknown_request`, `project_mismatch`, `emitter`, `cause`, `item`, `action_id` (no id), `per_request`, `stale_request` and `early_event` on the databases' clocks. A backlog doesn't make an event stale. The actor comes only from the witness, and a rejection is the relay's own (`actor_kind=system`, `program=relay`, no actor ref).
- **Exactly once across a crash between the append and the index.** The store's append is idempotent on (id, digest without `recorded_at`). A late commit is not skipped, since there is no high-water mark. immudb down means pending and nothing rejected. A database missing from the store is pending for that project only.
- **Platform events are written in the change's transaction** (`db.py` `conn.transaction()` blocks; `llm_store.save_provider`; `create_version` inside its connection's transaction). A failed member change leaves no event.

## 3. Mutations

| Mutation | Where | Tests run | Result |
|---|---|---|---|
| `_indexed` short-circuit removed | relay.py:222 | relay + platform_events | **survived** (41 passed): M7 |
| advisory lock removed | relay.py:76 | two-relays test | **survived**: M7 |
| route check of platform-born ids disabled (`if False and ...`) | app.py:81 | platform_events, beacon, routes, provision_flow | **survived** (only the baseline's export failure): m9 |
| `project_mismatch` of a run removed | relay.py:314 | ledger suite | killed (`test_an_event_for_another_project_is_rejected`) |
| action id not required | relay.py:354-355 | relay | killed (`test_a_server_action_event_needs_an_action_id`) |
| `db_role` taken from the event | 0020 template:72 | outbox, relay | killed (`test_the_row_names_the_role...`) |
| delete drain 409 disabled | app.py:280 | platform_events, provision_flow | killed (`..._not_dropped_until_they_are_delivered`) |
| run's `runs` membership not checked | relay.py:323 | ledger suite | killed (`test_an_action_the_run_does_not_produce_is_rejected`) |
| `run_window` not enforced | relay.py:326 | internal | killed (`test_an_ai_event_after_the_run_window_is_rejected`) |
| `per_request` limit +100 | relay.py:302 | relay | killed (2 tests) |
| emitter not passed to `registry.check` | relay.py:261 | relay, internal | killed (2 tests) |
| platform-action refusal in `emit` off | 0020 template:65 | outbox | killed (8 tests) |

Notes on method:
- The copy (`git archive HEAD` of `platform`, `shared` and `init`) lacks `scripts/verify-ledger-export.py`, so a few export tests fail in it with no mutation applied. I counted a mutation as killed only by a failure outside that baseline.
- Midway through, my immudb container was killed from outside (exit 137; not by my scripts). I restarted it and re-ran the three affected mutations (`routecheck`, `run_window`, `emitter`) with targeted test files. The table shows those re-runs.
