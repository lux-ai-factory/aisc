# Ledger: phase 6 review, step 2 (control objectives) (2026-10-03)

**Verdict: 0 blockers, 4 majors, 11 minors. Phase 6 is not done yet.**

The core holds. Every state-changing route of `api/app.py` and `api/library_routes.py` calls
`ledger.emit` inside the write's own `sessionmaker.begin()` block. Each route's `caused_by` matches the
URL its form or API call really posts to, with the right `item` group and `per_request`. No event names
a person. A failed AI run sends a code, never the error's text. With `LEDGER_MODE` off, the full suite
is green. Phase 6 does not repeat phase 5's B1, M1 or M3: there is no wrong cause page, no rejected
branch and no action-id issue (Python routes are never `ACTION`).

What keeps the phase open:
- a long AI mapping loses its whole run in the ledger (M1);
- one write is still made with no event (M2);
- the item chains break in normal use, which is phase 5's m1 again, but on the main form (M3);
- the S1-S3 tests miss three of the phase's claims, and one test docstring claims a test that doesn't
  exist (M4).

## What I checked, and how

Commits: aisc `cbd1f2f` and apps/control-objectives `6cc41aa`, both on `feat/unified-modules`. I read
the whole diff of both, the current `api/app.py`, `library_routes.py`, `projects.py`, `library.py`,
`db/repository.py`, `server.py`, `access.py`, the templates' form actions, the Caddyfile's
`control-objectives` handle and witness snippets, spec 4.1 to 4.5, 5.3, 6.4, 6.5 and 7.5, the coding
plan's phase 6 row, test plan S1-S3, and the relay's `_judge`, `_judge_request`, `_judge_run`, `_cause`,
`_check_action`, `registry.check` and `verify.verify`. I committed nothing, pushed nothing, never
touched the live stack, never used port 5432 and never ran docker compose.

| Suite | Result |
|---|---|
| control-objectives, whole (`CONTROL_OBJECTIVES_TEST_DATABASE_URL` = scratch `co_review` on my rev9 Postgres) | **503 passed, 1 skipped** (6 min 53 s); `tests/test_ledger.py` alone: 13 passed, none skipped |
| `platform/tests/ledger/test_ledger_step2.py` (own env `aisc-t-rev9-0b7fc7`, `LEDGER_TESTS_REQUIRED=1`) | 20 passed |
| `scripts/tests/test_ledger_coverage.py` | C4 green for all 7 apps, `control_objectives` included. C1 lists no `control_objectives` route. C1 is red only for other apps' routes (connectors, platform, report composer, report renderer), as expected before their phases |
| `scripts/tests/test_ledger_action_pages.py` | green (qualification and controls) |

**Probes.** I wrote 8 probe tests in a temporary file next to the platform's ledger tests
(`platform/tests/ledger/test_zz_rev11_probe.py`, deleted afterwards). They ran against the real
registry, relay and `verify`, using the event shapes the handlers build. Each asserts the behaviour a
finding describes, and all 8 passed:
- P1 to P3: chain breaks (M3);
- P4: a long run is lost (M1);
- P5: an empty mapping is rejected (m1);
- P6: an AI event with no model is accepted (no finding);
- P7: `profile_version` is refused in `assessment.started` (M2's fix needs a registry change);
- P8: phase 7's `/controls/install` gives a project mismatch (m10).

**Witness paths.** HTML forms post to their `action` URL (`{{ project_base }}/...`, with
`project_base = /control-objectives/p/<project>`). The JSON API posts to `/control-objectives/p/<pid>/api/...`.
Caddy's `handle_path /control-objectives*` gives the witness `{http.request.orig_uri}`, which is the
unstripped path. No page script fetches anything (`grep fetch` finds only a comment).

I checked every `@app.post/put/delete` against its action's `caused_by`. Each `_co(...)` regex matches
both the form path and the `/api/` path. The `item` groups bind:
- the assessment id for `map`, `key`, `profile` and the `DELETE`;
- the risk id for `risks/<r>/mapping`;
- the set id for `publish` and `delete`;
- the objective id for edit, retire and restore;
- the profile id for `profiles/<id>[/versions]`.

The emitted `item_id` is that same value in each case. Every action is `per_request=1`, except
`risk.rated` and `risk.rating_comment.set`, which are `None` and are the only ones emitted per risk.

**Middleware.** `app.add_middleware(ledger.RequestId)` comes after `ProjectAccess` and before CORS, so
the order from the outside in is CORS, `RequestId`, `ProjectAccess` (the auth and membership gate),
then the router. `RequestId` therefore runs before the gate, including on refused requests. That is
harmless, because it only sets a context variable and a refused request writes nothing. Caddy strips
any `X-AISC-Request-Id` a client sends (`strip-and-sign-in`), and the middleware keeps only a value
that parses as a UUID. The context variable reaches sync handlers run in the thread pool:
`test_each_assessment_action_records_its_event_citing_the_request` uses sync routes and sees the id.

## Majors

**M1. A mapping that takes longer than 5 minutes loses its whole run (`stale_request`, then `run`).**
`api/app.py:350` and `:530` emit `ai.mapping.requested` from `on_save`. `on_save` runs inside
`save_mapping_run`'s transaction, which starts only after `map_risks` has made every model call
(`projects.py:210-221`). `ledger.emit` sets `occurred_at := clock_timestamp()` at that point.
- Spec 4.2 item 7 rejects a person's event whose `occurred_at - witness.at > WINDOW` (5 min). So
  `ai.mapping.requested` becomes `stale_request`. `_judge_run` then finds no accepted start, so every
  `ai.llm_call` and the `ai.mapping.completed` become `run`.
- *Reproduced (P4):* requested, one call and completed, 6 minutes after the witness, give
  `['run', 'run', 'stale_request']` and no `ai.*` entry in the log.
- This is realistic. A card has one model call per risk, and `MAX_ATTEMPTS = 3` rounds per risk
  (`rounds.py:31`), each with the whole catalogue in the prompt. For example, 15 risks at 3 attempts of
  7 s each come to 315 s. A local Ollama model (the dev default, `BAF_LLM_BASE_URL` 11434) is slower
  still. Caddy sets no response timeout, so the request itself succeeds, and the page shows a mapping
  the ledger has no record of.
- The mapping is step 2's only AI step, so this is the event that matters most.

*Fix:* emit `ai.mapping.requested` (with the run id) in a transaction of its own, before the first
model call. It describes the person's request, not the save. Keep `ai.llm_call` and
`completed`/`failed` in the save's transaction: as run events, they are checked against
`run_window` (24 h), not the 5-minute window. Extend `verify.open_runs` to count
`ai.mapping.requested` with no `completed`/`failed`, the same idea as phase 5's M4 fix. Add a step-2
probe like P4.

**M2. A new card version's assessment changes its profile with no event, in a second transaction.**
`projects.py:121-123`: after `repository.create` commits the assessment and its `assessment.started`,
`Projects.create` calls `self._repository.set_profile(record.id, previous.profile_version_id, keep=set())`
in a new transaction, with no `record`.
- The assessment's `profile_version_id` changes, and the ledger never says so. This breaks "a
  committed change always has one" (R2.4). From the ledger, an auditor reads the new assessment as
  being on the built-in catalogue, while the page runs it on the previous profile.
- Emitting `assessment.profile.switched` there would not help: its `caused_by` is only `/profile`, so
  it would be rejected (`cause`). Adding `profile_version` to `assessment.started` is refused today
  (P7: `details_key:profile_version`).
- A failure between the two transactions leaves an assessment on no profile. The flow already did
  that before this phase, but it is now also a ledger-visible split.

*Fix:* set the inherited profile inside `repository.create`'s transaction, before `record` runs. Add
`profile_version` to `assessment.started`'s `details_keys` and send it. Add a test: starting on card
version 2 after version 1 used a profile writes one event, and that event names the profile version.

**M3. The item chains (I11) break in normal use.** This is phase 5's m1 again, but here it fires on the
main form and across assessments. `verify` keys the chain on `(item_type, item_id)` across the whole
project log.
- *Mixed part states on one risk.* `risk.rated` sends `{impact, likelihood}`,
  `risk.rating_comment.set` sends `{comment}`, and `mapping.risk.edited` sends a list of objective ids.
  All three use `item = (risk, <risk id>)` (`api/ledger_events.py:11-31`, `api/app.py` map_by_hand).
  `rate_form` saves ratings and comments in one POST. So a save that changes both breaks the chain
  once, and the next rating breaks it again. *Reproduced (P1):* 2 breaks, nothing wrong.
- *Risk ids aren't unique in a project.* A risk's id is the local name of its card node
  (`models/ontology.py:216`), and every card version's assessment of the same system has the same risk
  ids. The first rating in the new assessment (`before` all None) breaks against the old assessment's
  last `after`. *Reproduced (P2):* 1 break.
- *Partial key states.* `objective.key.set` sends `before` and `after` only for the ids in the request.
  `key_form` sends the matrix's ids, and those change whenever the mapping changes
  (`repository.py:207-221`). *Reproduced (P3):* 1 break.
- Each break is a reconciliation alarm with nothing behind it. Reconciliation then becomes noise
  before `enforce` (spec 5.2 step 5 asks for 14 clean days).

*Fix:*
- Give each state its own item type: `risk_rating`, `risk_comment`, `risk_mapping`.
- Make the item id unique in the project, `<assessment>/<risk>`. The `caused_by` of
  `mapping.risk.edited` then needs no `item` group, or the relay needs a compound one.
- For keys, send the assessment's whole key map, read inside the transaction, as `before` and `after`.

Add a step-2 test that runs `verify` after a realistic sequence (rate with a comment, rate again, start
the next card version and rate it, set keys twice with different matrices) and expects
`chain_breaks == 0`.

**M4. S1-S3 don't test three of the phase's claims, and one test claims a test that isn't there.**
Each of these mutations survived the CO tests `test_ledger.py`, `test_library.py` and
`test_assessment_profile.py`, and the trigger mutation also survived the migration and isolation suites:
- *Authors by subject in the routes (S2):* `who_sub=""` in every route call of `library_routes.py`.
  This **survived**. The tests check `_who_sub` on a stub request and the `Library` call on its own, but
  never that a route stores the subject.
- *A profile switch keeps what it drops (S1):* removing `_archive(..., "profile", ...)`
  (`repository.py:317`). This **survived**. No test covers a profile switch's archive row.
- *Append-only archive:* removing the `CREATE TRIGGER` from the migration. This **survived** (56
  passed). The docstring at `tests/test_ledger.py:153` says the trigger is "tested in
  test_migration_project_database", but that file only adds the table name to `TABLES`. The test above
  it, `test_the_archive_is_append_only`, only counts rows after two runs.
- *Run events in the save's transaction:* moving `on_save` into a second transaction after the save.
  This **survived**. Only `rate` has a failure-after-event test.
- *`ai.llm_call` through a route:* removing `calls.recording` (`projects.py:209`). This **survived**.
  The `client` fixture's `SwitchableMapper` has no `_complete`, so no route test ever produces an
  `ai.llm_call`. The ordering assertion `actions[:2] == [requested, completed]` even depends on there
  being none. This is a test fake hiding real behaviour, the same kind of problem as phase 5's M4. In
  production, `RiskMapper` has `_complete` (`server.py:119`), so every model call is recorded there.

*Fix:*
- a route test (with a caller on `request.state`) that reads `created_by_sub` and `published_by_sub`
  back;
- a profile switch that drops a mapped row, then checks the archive;
- a migrated scratch database where `UPDATE` and `DELETE` on `mapping_archive` raise;
- a failure after `save_mapping_run`'s `record` that leaves no run and no event;
- a mapper fake with `_complete`, so `/map` writes `ai.llm_call` rows between requested and completed.

## Minors

- **m1. An AI mapping of a card with no risk is rejected.** `ai.mapping.completed` is
  `content_required`, and `registry.check` treats `{}` as missing. *Reproduced (P5):*
  `content_required`. *Fix:* send `{"risks": {...}}`, or relax the check to `is None`.
- **m2. A model that can't be resolved records nothing.** `ModelUnavailable` from `_mapper_for`
  (`projects.py:201-205`) is raised before a run id exists. The witnessed POST then has no event
  (`witness_without_event`), and the person's request leaves no trace of why. *Fix:* with M1's early
  `ai.mapping.requested`, emit `ai.mapping.failed` (`model_unreachable`) in that branch too.
- **m3. In `enforce`, the app doesn't refuse a write with no request id (spec 5.3).** `ledger.on()`
  treats `record` and `enforce` alike. A write that reaches `control-objectives:8090` without Caddy
  (from another container on the network) commits, and its event is `missing_request`. Qualification
  has the same gap. *Owner:* before the `enforce` flip. A check in `RequestId`, or in a dependency on
  writes: no id and no service token gives 401.
- **m4. `mapping_archive` is append-only against row DML only.** Migrations run as
  `control_objectives_rw` (`docker-compose.development.yml:472`), so that role owns the table and can
  `TRUNCATE` it or `DISABLE TRIGGER`. The trigger doesn't cover TRUNCATE. This is the same as phase 5's
  m8. *Fix:* a `BEFORE TRUNCATE` statement trigger, and state the owner limit in the migration.
- **m5. Deleting an assessment drops what the archive was meant to keep.** `repository.py:343` freezes
  ratings, comments and the mapped ids. It does not keep the mapped rows' quote, rationale and source,
  the run, the key choices or the selection, and no `mapping_archive` row is written. *Fix:* archive
  with a `deleted` reason (extend `ck_mapping_archive_reason`) in the delete's transaction, and add the
  keys to `held`.
- **m6. `objective.restored` names no `routes`** (`registry.py:281`), although `retire_form` and
  `retire` emit it. C4's `registered()` maps one route to one action, so a handler that emits two
  actions is checked for one only. *Fix:* list the two handlers under `objective.restored` too, and let
  `registered()` keep a set per route.
- **m7. `save_profile` reads its "before" outside the write's transaction.** `library.py:463` takes
  `current.current.number` and `dropped` before `sessions.begin()`. Two concurrent saves compute the
  same number (one then fails on the version's uniqueness, or both events say the same version). *Fix:*
  read the latest number with `SELECT ... FOR UPDATE` on the profile row inside the transaction.
- **m8. `ai.llm_call.details.round` is the call's index across the whole run** (`ledger.py:107`), not
  the round of a risk. *Fix:* call it `call`, or pass the risk and its round from `_map_one`.
- **m9. Objective ids come back after a set is deleted.** A set deleted and created again with the same
  code numbers its objectives `LDG1`, `LDG2` again. Their `objective.edited` chain then continues the
  deleted objectives' chain (one break, and two objectives' histories merged). *Fix:* make the item id
  `<set id>/<objective id>`, or never reuse a deleted set's code in a project.
- **m10. (Owner: phase 7, but the entry is in this commit.)** `control.installed` from the
  project-less page `/controls/install` (`installChosen`, now in `caused_by`) is always rejected. The
  witness finds no project in that path, and the event is in the project's outbox. *Reproduced (P8):*
  `project_mismatch`. *Fix:* post the install from `/controls/p/<slug>/install`, or give the witness a
  project rule that reads the chosen project.
- **m11. A failure while recording a failed run hides the run's own exception.**
  `projects.py:213-216` calls `self._repository.recording(...)` inside `except`. If that raises (the
  database is down, or `NotLedgerSafe`), the mapping's real error is lost from the 500's traceback.
  *Fix:* catch and log the recording failure, then `raise` the original.

## What holds (checked, no finding)

- **Same transaction, none on rollback.** Every `record`/`on_save` callback runs inside the repository's
  or the library's `sessions.begin()`, after the change and before the commit. That covers create,
  rate, keys, mapping run, risk mapping, profile switch, delete, set create, objective add, edit,
  retire, restore, publish, set delete, profile create and profile version.
  `test_a_failed_change_leaves_neither_the_change_nor_its_event` passes. The only write outside a
  recorded transaction is M2's.
- **No person in an event.** No event carries `created_by` or a name. Each content I checked is made
  only of ids, codes, set or profile names and descriptions, objective FIELDS, ratings and the
  assessor's comments. The objective FIELDS (`library.py:37`) hold no author. The names stay in the
  database beside `*_sub` for the pages.
- **No free error text.** `ai.mapping.failed.details.error` is `mapping_error` or `model_unreachable`.
  The test with a key and a name in the exception passes.
- **Run binding.** Every run event carries the start's request and run id, and the
  `completed`/`failed` item is the start's assessment (phase 5's m4 check). An AI event with no model
  is accepted (P6), unlike phase 5's internal route. In production the model is always
  `provider/model`.
- **Registry shapes.** The 20 cases of `test_ledger_step2.py` match what the handlers build. I
  compared each one with `api/app.py`, `library_routes.py` and `ledger_events.py`: details keys,
  `content_required`, items against `item` groups, `item_version` and `card_version` (a UUID, as the
  outbox column needs).
- **Action ids.** Every step 2 cause is `POST`, `PUT` or `DELETE`, never `ACTION`, so spec 4.5's
  binding can't reject a branch here.
- **`LEDGER_MODE` off.** `emit` returns before building anything. The suite is green
  (503 passed), and `test_with_the_ledger_off_nothing_is_written` catches the "always on" mutation.
  What differs from before, with nothing a person sees:
  - `mapping_archive` rows are written in every mode;
  - the mapper is shallow-copied and timed;
  - a failed run opens an empty transaction;
  - `retire` and `restore` are unchanged.
- **Compose.** `LEDGER_MODE: ${LEDGER_MODE:-off}` is on `control-objectives` (and on `controls-web`
  for phase 7).

## Mutations

Each mutation was applied to the checkout by `rev11_mut.py` in my scratchpad. The script copies the
original aside, runs the tests, copies the original back, and prints `git diff --stat`, which was empty
after every one.

| Mutation | Tests run | Result |
|---|---|---|
| routes pass `who_sub=""` | test_ledger, test_library, test_assessment_profile | **survived** |
| no `calls.recording` (no `ai.llm_call`) | same | **survived** |
| no archive on a profile switch | same | **survived** |
| run events in a second transaction after the save | same | **survived** |
| no `CREATE TRIGGER` on `mapping_archive` | test_ledger, test_migration_project_database, test_isolation_project_databases | **survived** |
| no `RequestId` middleware | same as the first | caught |
| no archive on an AI rerun | same as the first | caught |
| `ledger.on()` always true | same as the first | caught |

Cleanup: the probe file was deleted, and the env `aisc-t-rev9-0b7fc7` (Postgres with the scratch
`co_review` database, and immudb) was removed with `ledger-env-down.sh`. `git status` of
apps/control-objectives is clean. In the aisc repo, the only file this review adds is this one. The
other changes listed there (evidence, results, catalogue, phase 7 review) belong to other sessions and
were there before I started.
