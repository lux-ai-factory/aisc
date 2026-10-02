**Verdict: 0 blockers, 0 majors, 6 minors open. Phase 1 may start.** All four majors are closed: M4's relay half fully, its cleanup half with a minor left over. Three minors are partly closed (n11, n-g, n-h). The new minors are test-hygiene and spec-wording issues. None of them blocks phase 1's Definition of Done (L1-L4 and PV1-PV7).

# Ledger: fourth review (commit c28510b)

This was read-only. I read `git diff 19792f0 c28510b`, the changed tests, both conftests and the spec sections involved. I edited nothing in the repo and ran no docker. The only write was the contract line your CLAUDE.md asks for, appended to `~/.claude/prompt-log/2026-10.md`.

## 1. Status of the third review's items

"Closed" means the spec says it and a test would fail if it were not done.

| Item | Status | Evidence |
|---|---|---|
| **M1** phase-1 provisioning tests needed phases 2-3 | **Closed** | `test_ledger_provision.py:24-87` calls `provision`/`pool` directly, with no HTTP and no relay. The phase-3 cases moved to `test_ledger_provision_flow.py:21-71`. Phase 1's Definition of Done is narrowed (`01-plan.md:222`). I checked that the phase-1 files (store, canonical, naming, registry, provision) use no phase-2/3 fixture. |
| **M2** exact relay counts; `override` semantics | **Closed** | The spec says `override` **merges** (`02-spec.md:355-356`). A registry test pins the merge and the restore (`test_ledger_registry.py:228-239`). R1 now filters on its own request (`test_ledger_relay.py:92-94`). The other counts in that file are per action (`trusted(..., action)`), so the fixture's `member.added` doesn't disturb them. |
| **M3** P4 against the delete rule | **Closed** | `test_ledger_platform_events.py:94-115` emits a project-DB `risk.rated` and expects 409. The inverse case is `:118-128`: pending platform-DB rows still allow the delete. This matches `02-spec.md:466-470`. |
| **M4** shared state; whole-database relay | **Closed (relay), partly (cleanup)** | Relay: missing database means pending plus a per-project alarm, never an abort (`02-spec.md:404-407`). PF4 and PF5 test this (`provision_flow.py:49-71`), and P4/PF3 now relay by pid. Cleanup: `conftest.py:65-91` exists, but no test fails if it doesn't work. See new minor 1. |
| **n-a** `own_store` order | **Closed** | `conftest.py:125-126` depends on `memory_ledger`. |
| **n-b** app-sent platform fields | **Closed** | `extra jsonb` (`02-spec.md:447-450`); `test_ledger_outbox.py:148-152`; relay rejection in `test_ledger_privacy.py:150-153`. |
| **n-c** pool `server_id`, assign in the creation transaction | **Closed** | `02-spec.md:390-397`; tests at `provision.py:69-77` (rollback) and `:85-87` (`memory:<uuid>`). The immudb UUID is deferred to S7 (`02-spec.md:667`). |
| **n-d** action-set wording | **Closed** | `02-spec.md:267-271` now matches `relay:211-238`. |
| **n-e** `state` key | **Closed** | `02-spec.md:341-343`. `privacy.py:140-146` checks state digest is not content digest, and the export's key set is exactly `{"content"}` (`:188`). |
| **n-f** versions kept for ever | **Closed** | `02-spec.md:533-536`; the retired-version test is at `privacy.py:171-174`. |
| **n-g** actor mapping | **Partly** | Closed: the MAC covers the name (`privacy.py:99-104`) and the pid's case is ignored (`:112-113`). Weak: see new minor 3. |
| **n-h** retention | **Partly** | Spec only (`02-spec.md:541-543`). Nothing tests that `token_jti` is nulled after `RECONCILE_DAYS`. Acceptable to add in phase 2 or 10. |
| **n-i** export negative case | **Closed** | `privacy.py:198-204` tampers the content and expects a non-zero exit. |
| **n-j** keys read on every call | **Closed** | `02-spec.md:336-337`. The rotation test calls `setenv` mid-test after a v1 digest (`privacy.py:162-169`), so a key cached at first use fails it. |
| **n2** document drift | **Closed** | `04-test-plan.md:6-8` names the four files that collect. Spec section 9 (`02-spec.md:563-565`) gives no number any more. Both match my run. |
| **n11** `emit` list from the registry | **Partly** | `test_ledger_outbox.py:137-145` covers every action with no emitters. But `page.opened` must have emitters (`test_ledger_registry.py:99`, and it is not in `PLATFORM_ONLY`). The SQL must still refuse it (`outbox.py:98-99`; `02-spec.md:454-456`). So the "generated from the registry" rule doesn't produce `page.*`, and the spec doesn't say what rule does. |

## 2. New problems

No new blocker or major. I checked for unsatisfiable tests (the `override` test's `Action` kwargs match the relay file's), fixture ordering (`own_store`, `call` setting `enforce` before `witnessed`) and contradictions with spec section 10. I found none.

### Minors

1. **The cleanup is silent, all-or-nothing and untested** (`conftest.py:69-91`).
   - Everything runs in one transaction under `except Exception: pass`. One failing DELETE rolls back all the others, and nobody sees it.
   - A failure is likely: `ledger.event_index.project_pid` and `ledger.page_view.pid` are column names the spec never defines.
   - The `ledger.pool` line (`:75`) is a pattern match (`LIKE 'memory:%'`), which contradicts the comment at `:65-66`. It is safe only because the spec says MemoryLedger is for tests. It would also delete the pool rows of another test session running against the same database at the same time.
   - It misses `ledger.actor` rows with `pid IS NULL` (platform-scope sightings, `privacy.py:109`, project creation) and any alarm or `ledger.state` rows.
   - Leftovers last the whole session, so PF4 and PF5's `stats.pending >= 1` (`provision_flow.py:57,71`) is met by earlier tests' rows. What actually tests M4 there is "no exception, and `fine` delivered".
   - Fix:
     - one transaction per statement, and a warning instead of `pass`;
     - name the columns in the spec;
     - a cleanup self-test;
     - in PF4, assert on `lost`'s own pending state.
2. **n11 generation rule.** Say in `02-spec.md:456` how `page.*` gets into the refused list (for example "no emitters, or reported by the browser"). Then make the generated test use that same rule.
3. **The n-g tests a wrong implementation passes.**
   - `privacy.py:82-96` isn't a first sighting. OWNER already got a project ref from the witnessed member-add during the `project` fixture, so the test passes without the unique constraint. Use a fresh `uuid4` subject.
   - `privacy.py:107-109` is true for any random-ref implementation.
   - Postgres treats NULLs as distinct, so "unique on `(pid, sub)`" doesn't hold for `pid=None`. Concurrent platform-scope sightings mint many refs. The spec needs `NULLS NOT DISTINCT` (PG 15 or later) or a sentinel scope.
4. **`provision.assign` has no return type in the spec** (`02-spec.md:394`), yet the tests use `-> db | None` (`provision.py:27,55,62`). The phase-1 tests also assign random pids that have no `core.project` row. Say that assign and `assign_pending` neither look up the project nor hold a foreign key to it, or PV1-PV7 can't pass under a "reasonable" implementation.
5. **Doc drift.**
   - "PV1-PV7" (`04-test-plan.md:49`, `01-plan.md:222`) covers 8 test functions, none labelled.
   - `02-spec.md:510` says `ledger.databases`, but the expected-databases list is `ledger.pool` (`:400-401`).
6. **Fixed event ids** (`platform_events.py:101`, `provision_flow.py:16`) are safe only if event-id uniqueness is per log (`id:<event_id>` per database, `02-spec.md:376`). Session-long leftovers make that matter if `ledger.event_index` gets a global unique key. Use `uuid4`, or state per-log uniqueness for the index.

Security: I found no new issue. The cleanup deletes only ids the tests recorded, apart from the `memory:` pool pattern in minor 1.

## 3. What I ran

| Command | Result | Right reason? |
|---|---|---|
| `--collect-only -q tests/ledger` (database unreachable) | 119 collected, 11 errors | Yes. All 11 are `No module named 'platform_service.ledger'`, the new `provision_flow` included. Per file: witness 46, outbox 56 (+2), internal 14, failure 3. |
| The same four files with `LEDGER_TESTS_REQUIRED=1` | **119 errors, 0 skips** | Yes. 63 say `no platform database reachable`, 56 say `PLATFORM_TEST_SUPERUSER_URL is not set`. |
| The same without the flag | 119 skipped | As designed. |
| `uvx pyflakes platform/tests/ledger` | clean (exit 0) | Yes. |

Red is for the right reason: the package is missing, or a required service is absent. Nothing is skipped silently.

## 4. Before phase 1, ranked

1. Minor 4 (the assign contract): phase 1's PV tests depend on it.
2. Minor 1 (cleanup robustness): phase 1 creates the `ledger.*` tables it targets.
3. Minor 3 (n-g tests and NULL scope): before phase 2's `actors`.
4. The rest in their phases.
