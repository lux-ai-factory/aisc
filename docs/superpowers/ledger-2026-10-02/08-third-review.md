**Verdict: 0 blockers, 4 majors and 12 minors are open. Phase 1 can start once one cheap test-only fix is made (M1: re-phase the provisioning tests). The other three majors block phase 3, not phase 1.**

Of the 11 items from the second review, 9 are closed and 2 are partly closed (n2, n11). n3's spec fix also caused a new major (M3).

# Ledger: third independent review (2026-10-02, commit 43d26b3)

This was a read-only review with fresh context. I read the second review, the doc diff from 34a1483 to 43d26b3, every changed file under `platform/tests/ledger/`, the related sections of `02-spec.md` and both `conftest.py` files. I edited nothing, ran no docker and created no containers.

## 1. The items from the second review

"Closed" means the spec says what to do and a test would fail if it were not done.

| Item | Status | Evidence |
|---|---|---|
| **N1** DB names vs pool | **Closed** | Spec: random names (`02-spec.md:326-328`), `ledger.pool` with `server_id`, `FOR UPDATE SKIP LOCKED`, `database_for` and `assign_pending` (`382-389`), the operator script inserts pool rows (`474-476`). Tests: `test_ledger_naming.py:12-31`, PV1-PV6 (`test_ledger_provision.py:36-98`), `log_of()` lookup (`conftest.py:96-102`), and `memory_ledger` now fills a pool before any project exists (`conftest.py:80-93`). New problems in M1, M4 and n-c. |
| **N2** enforce before the project | **Closed** | Projects are made through the witness (`conftest.py:147-181`). No route is exempt. The `other_project` cases mid-test use `make_project` (`test_ledger_relay.py:136`, `test_ledger_internal.py:118`). |
| **N3** action-id first-use binding | **Closed** | Spec `02-spec.md:267-282`: the set of actions from the first request, only the serving app's events bind, run events are checked by their start event, the limits are stated. Tests: multi-action first request (`relay:226-238`), step-1 submit with two apps (`relay:241-253`), an action outside the set rejected (`relay:211-223`), and AI run events citing an action-id request accepted (`internal:43-68`). Wording ambiguity in n-d. |
| **N4** who computes digests | **Closed** | Rule 9 `platform_field:<name>` (`02-spec.md:224-226`). The outbox carries plain `before`/`after` (`432-434`). Tests: R1 checks the platform's digest (`relay:95`), an app-sent digest is rejected (`relay:126,147`; `privacy:112-116`), before/after digests (`privacy:106-109`), key order ignored (`relay:379-386`), registry `check` (`registry:194-197`). Storage gap in n-b. |
| **N5** one global key | **Closed** | Random `actor_ref` with a MAC'd mapping (`02-spec.md:340-345`), HKDF per project and purpose with versioned prefixes (`333-339`, `515-519`), export carries only this project's content keys (`425`). Tests: erasure then re-sight gives a new ref (`privacy:89-94`; this is what fails a deterministic HMAC), swapped row raises `MappingAlarm` (`82-86`), keys differ per project (`119-121`), rotation v1 to v2 and retirement (`126-139`), export keys (`144-160`). Design minors in n-e to n-h. |
| **6.2** `needs_database` bypass | **Closed** | `needs_db` is now a fixture marker that goes through `need()` (`conftest.py:55-62`), and every ledger file uses it (grep: no `needs_database` left). Verified by run, see section 3. |
| **n1** "no record" not checked | **Closed** | `witness.count(route_path=...)` before and after (`test_ledger_witness.py:62-66`). `route_path` is the unstripped path (`witness:33-34`), so the count is meaningful. |
| **n2** document drift | **Partly** | Fixed: the reasons are now in 4.2 and 4.4, `ledger.witness` is placed in the platform DB (`02-spec.md:445-447`), `01-plan.md:72` is updated. Still wrong: `04-test-plan.md:6-8` says only the witness and outbox files collect, but `failure` and `internal` collect too (117 tests). Spec `02-spec.md:543` says "96 tests"; the real number is 100. |
| **n3** delete rule | **Partly** | The spec is fixed (`02-spec.md:450-453`), but test P4 now contradicts it. See M3. |
| **n4** witness 302 | **Closed** | `test_ledger_witness.py:129-140`: `Sec-Fetch-Dest: document` gives 302 to `/oauth2/start?rd=`, without it 401. |
| **n11** `emit` list | **Partly** | The three missing actions are now tested (`test_ledger_outbox.py:98-102`). The spec's claim that the list "is generated from the registry, so the two can't drift" (`02-spec.md:440`) has no test. A hand-written SQL list passes. Fix: parametrize over the registry's platform-only actions. |

## 2. New problems the fix introduced

### Majors

**M1. PV1-PV6 are phase-1 tests that can't go green in phase 1.**
- `04-test-plan.md:49` puts them under "Phase 1: core", whose Definition of Done is "platform ledger tests green, `LEDGER_TESTS_REQUIRED=1`, no skips" (`01-plan.md:222`).
- They need code from later phases:
  - `make_project` goes through `/authz/witness` and asserts 200 (`conftest.py:154-155`). That is phase 2.
  - PV5 (`provision:70-84`) needs `ledger.emit` and the relay. That is phase 3.
  - PV6 (`provision:87-92`) needs the delete drain. That is phase 3.
  - `verify.missing_database` (`provision:95-98`) is verify, so phase 3 or 10.
- Fix:
  - give phase 1 a provisioning-level fixture (a plain project insert plus `provision.assign`, mode `off`);
  - move PV5, PV6 and the missing-database test to phase 3;
  - or narrow phase 1's Definition of Done to L1-L4 and PV1-PV4.

**M2. The relay's exact counts ignore the events the new setup creates, and `registry.override` semantics are unspecified.**
- `project` now adds MEMBER through a witnessed `POST /api/projects/{slug}/members` (`conftest.py:171-172`).
- The owner is a member, so that witness record has `project_pid` set (`02-spec.md:159-160`). Its `member.added` row is in `core.outbox` with the pid (`platform_events:97-113`). `relay_once(pid)` drains both (`02-spec.md:393-395`).
- So R1's `(stats.delivered, stats.rejected) == (2, 0)` (`relay:92`) can't hold for a correct implementation. It will see at least 4 delivered, plus `project.created` if that lands in the project log.
- `registry.override(actions)` (`02-spec.md:348`) doesn't say whether it replaces or merges.
  - If it replaces, `member.added` becomes `unknown_action`.
  - Then every `rejected(...) == [reason]` and `== []` in the relay file fails (about 20 tests).
- Fix:
  - spec: override merges over the real registry;
  - R1: count only the events the test made (filter on `request_id == closing`), not `RelayStats` totals.

**M3. P4 contradicts the new delete rule (n3).**
- The spec now refuses a delete only while rows of the **project database's** outbox are undelivered (`02-spec.md:450-453`).
- P4 (`test_ledger_platform_events.py:93-104`) creates only a `member.added`, which lives in `core.outbox` in the platform DB (`106-113`). It then expects 409 "undelivered" with immudb down.
- Under the spec, that DELETE must succeed. A correct implementation fails the test; one that also blocks on `core.outbox` passes.
- Fix: emit a project-DB outbox row (for example `controls_rw`) before the first DELETE, and add the inverse case: only `core.outbox` rows pending, the DELETE succeeds.

**M4. The suite is order-dependent: shared Postgres state and a whole-database relay.**
- `ledger.pool`, `ledger.witness`, `ledger.actor` and `core.outbox` rows survive every test.
  - The session cleanup deletes only `core.project` rows and project DBs (`tests/conftest.py:56-73`).
  - That breaks the platform suite's rule of leaving the database as it found it (`tests/conftest.py:44-47`).
  - Each test adds 8 pool rows, for ever.
- `relay_all()` with no pid (`provision:91`, `platform_events:102`) drains every leftover row from earlier tests:
  - Their `database_for(pid)` names databases in discarded `MemoryLedger` stores, which raises `UnknownDatabase`.
  - Their platform-log records are delivered into the current store's `ledgerplatform`.
- The spec doesn't say what the relay does with an assigned database the current store lacks. The natural choice (raise) makes those two tests fail or pass depending on test order.
- Fix:
  - spec: the relay treats such a database as pending plus an alarm, per project, and never aborts the batch;
  - tests: pass the pid, and clean `ledger.*` and `core.outbox` rows for `pytest-` projects (and pool rows of `memory:` servers) at session end.

### Minors (new)

- **n-a.** The `own_store` teardown leaks a stale global store. `own_store` is set up before `make_project`/`memory_ledger` (`provision:21-33,62,70`), so it tears down after them and restores `memory_ledger`'s store as current. Fix: make it depend on `memory_ledger`.
- **n-b.** Spec 6.4's outbox columns (`02-spec.md:431-434`) have no place for the app-sent `content_sha256`, `recorded_at` or `seq` that rule 9 must see and reject. Say that `emit` keeps unknown top-level keys (for example an `extra jsonb` column) for the relay. Refusing in `emit` would roll back the business write.
- **n-c.** Pool details:
  - `server_id` is the immudb address, which breaks on a hostname change; prefer immudb's server UUID.
  - A pool row is consumed if project creation rolls back; say whether `assign` runs in the creation transaction.
- **n-d.** N3 wording: the set is final "after that request's window closes" (`02-spec.md:269-271`). The tests need checking during the window (`relay:211-238`, all within seconds). Say the set grows with the first request's events and later requests are checked against the current set.
- **n-e.** Before/after digests use the `content` key, which the export hands to every exporter and auditor (`02-spec.md:425,520-522`). They can then brute-force low-entropy rating histories. The chain check needs only digest equality, so use a separate, non-exported `state` purpose.
- **n-f.** "A version is removed only after every digest made with it has been re-made" (`02-spec.md:518`) can't happen for digests in immudb. Say that content, query and fingerprint versions are kept for ever.
- **n-g.** `actors` details:
  - the MAC covers `actor_ref + sub` but not `name`;
  - two first sightings at once can mint two refs, so a unique (pid, sub) constraint is needed (untested);
  - the ref scope for platform-log records (`pid=None`) is unspecified;
  - the HKDF info includes the pid, so its case must be normalised.
- **n-h.** Erasure leaves `token_jti` in `ledger.witness` (`02-spec.md:157`) and old rows in Postgres backups. State the retention.
- **n-i.** PR8 (`privacy:144-160`) has no negative case. A `--check-content` that always exits 0 passes. Add a tampered-content line that must fail.
- **n-j.** The spec doesn't say that `secrets` reads `PLATFORM_LEDGER_KEYS` on each call, but the rotation test needs it (`privacy:128`).

### Security points checked and found sound

- **Random refs.** Erasure is real: the re-sight test catches any derivation.
- **Pool names.** A strict regex on names, and no pid in a name (`naming:28-31`).
- **Project setup.** `through_gateway` makes no route exempt from the witness.
- **Export keys.** Per-project HKDF; the master key never leaves (`privacy:154`).
- **302 redirect.** The `rd` comes from the Caddy-set original URI after the strip. oauth2-proxy's whitelist still guards it.

## 3. What I ran

| Command | Result | Right reason? |
|---|---|---|
| `PLATFORM_TEST_DATABASE_URL=...:1/none uv run --extra dev pytest --collect-only -q tests/ledger` | 117 collected, 10 errors | Yes. 9 are `No module named 'platform_service.ledger'`, 1 is `cannot import name 'ledger' from 'platform_service'` (provision). The ones that collect: witness 46, outbox 54, internal 14, failure 3. |
| The same with `LEDGER_TESTS_REQUIRED=1`, `test_ledger_witness.py` and `test_ledger_outbox.py` | **100 errors, 0 skips** | Yes. 46 say `LEDGER_TESTS_REQUIRED=1 but no platform database reachable`, 54 say `... PLATFORM_TEST_SUPERUSER_URL is not set`. 6.2 is fixed. |
| The same without the flag | 100 skipped | As designed. |
| `uvx pyflakes platform/tests/ledger` | clean (exit 0) | Yes. |

With a database present, these tests would next fail on the missing package inside the fixtures, which is still the right reason. M1 to M3 only show up once the code exists, which is why they need fixing before phase 3 is built.

## 4. Must fix, ranked

1. **M1** re-phase PV1-PV6. This gates phase 1's Definition of Done, and it's a test-only change.
2. **M2** override merges; R1 counts only its own events. Blocks phase 3.
3. **M3** P4 must emit a project-DB outbox row; add the inverse case. Blocks phase 3.
4. **M4** relay behaviour for an unknown assigned database; test cleanup and per-pid relays. Blocks phases 1 and 3.
5. Minors **n-b**, **n-e** and **n-g** before phase 1's `secrets`/`actors` code. The rest can be done in their phases.
