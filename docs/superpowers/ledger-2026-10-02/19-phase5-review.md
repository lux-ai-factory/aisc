# Ledger: phase 5 review, step 1 (qualification and its card agent) (2026-10-03)

**Verdict: 1 blocker, 7 majors, 9 minors. Phase 5 is not done yet.**

The building blocks hold up. `ledger.emit` really runs in the change's transaction for every Prisma
write of step 1 I could find. A rolled-back change leaves no event. `card_history` keeps what links,
corrections, discards and drafts overwrite. The TypeScript canonical twin matches the platform on the
shared vectors. The agent never names a person, and the platform takes the person from the run's start.
What keeps the phase open is that the events are accepted only for the URLs the tests made up. The
registry's `caused_by` regexes don't match the pages the server actions really post from, so the card's
creation (and the platform's card version and target sync on that submit) are rejected every time (B1).
Several more events are rejected by the relay or flagged by `verify` in normal use (M1 to M3). The agent
loses its failure event in the most common failure case, and can put a key or personal data into
immudb (M4, M5). The forms events put the person's name into frozen content (M6).

## What I checked, and how

Commits: aisc a776645 and apps/qualification 3a2b537, both on `feat/unified-modules`. I read the whole
diff of both, the spec sections 4.2 to 4.5, 6.4 and 6.5, the coding plan's phase 5 row, test plan Q1-Q4,
the phase 3-4 report, and the relay's `_judge`, `_judge_request`, `_judge_run`, `_check_action` and
`verify.verify`. I made no commits, pushed nothing, never touched the live stack, never used port 5432
and never ran docker compose. Every temporary file was removed and every mutation restored by copying
the original back (last section).

| Suite | Result |
|---|---|
| qualification unit (`npx vitest run`) | 1649 passed, **1 failed**: `test/unit/secrets.test.ts`, caused by this phase (M7 below) |
| qualification db (`THROWAWAY_PREFIX=aisc-t-rev5 bash test/db/throwaway-db.sh`) | 135 passed |
| agent (`services/agents`) | 239 passed |
| `platform/tests/ledger/test_ledger_step1.py` (own env `aisc-t-rev5p-*`, `LEDGER_TESTS_REQUIRED=1`) | 18 passed |
| `platform/tests/ledger` (whole) | see the last line of this file |
| `scripts/tests/test_ledger_{caddy,caddy_equivalence,credentials,gateway}.py` (real Caddy) | 91 passed |
| `scripts/tests/test_ledger_coverage.py` | C4 green for all 7 apps (qualification included); C1 red only for other apps' routes, as expected before their phases |

**Probes.** I wrote 8 probe tests in a temporary file next to the platform's ledger tests (removed
afterwards), against the real registry and relay. Each one asserts the behaviour a finding describes,
and all of them passed, so B1, M1, M2, M3, M4 and M5 are reproduced, not inferred.

**Prisma writes reached from a route or a server action** (all of `src/`, not only the listed ones):
`qualification.create` (in the card's transaction, with `qualification.created`), `cardComponent.upsert`
and `deleteMany` (links), `qualification.update` for `ontologyPatch` and `ontologyExtracted` (each in a
transaction with its history row and event), the forms' creates and retirements (each in the forms
transaction with its event), and `knowledgeGraph.upsert` (outside any transaction; a derived cache,
covered by the `loadOntology` exception and rebuilt from logged inputs). `saveSystemCard` has no caller.
I found no other write.

## Blocker

**B1. The card's creation, and the platform's card version and target sync, are always rejected.**
`registry.py:121-127` and `registry.py:176` bind `card_version.created`, `targets.synced` and
`qualification.created` to `("qualification", "ACTION", _QU + "/qualify/new$")`. But
`src/app/p/[project]/qualify/new/page.tsx:11` redirects to `/system/edit`, and the only mount of
`QualifyForm` (the `submitQualification` server action) is `src/app/p/[project]/system/edit/page.tsx:125`.
A server action POSTs to the page it is on, so the witness records
`route_path = /qualification/p/<slug>/system/edit`.
- *Reproduced:* a witnessed POST to `/system/edit` with a `qualification.created` row as
  `qualification_rw`, then the relay. The result is `ledger.rejected`, reason `cause`, and nothing accepted.
- The same holds for `card_version.created` and `targets.synced`, which the platform now cites on that
  same request because `PlatformClient` forwards its id (spec 4.3): same regex, same mismatch.
- So every card version made in step 1 has no accepted event, in `record` and in `enforce`. This is
  step 1's main event.
- `test_ledger_step1.py` passes because its case posts to `/qualify/new`, a path no browser sends.

*Fix:* change the three `caused_by` entries to `_QU + r"/system/edit$"` (keep `/qualify/new$` only if an
old page can still post there). In `test_ledger_step1.py`, take the page of each case from where the
component that calls the action is really mounted. Better still, add a test that finds each server
action's caller page in `src/app` and checks it against the action's `caused_by`, so a moved form fails
a test.

## Majors

**M1. Two more events are rejected whenever their branch runs (cause).** Same kind of problem as B1:
- `importSelfContained` (`questionnaires/import/actions.ts`) emits `question_set.created`, whose
  `caused_by` (`registry.py:153`) is `/question-sets(/.*)?$`. The import page is
  `/questionnaires/import`. *Reproduced:* `cause`. So every import's question set goes unrecorded,
  while its questionnaire is accepted.
- `saveQuestionSet` with "also make a questionnaire" (`QuestionSetEditor.tsx:77`) emits
  `questionnaire.created` from `/question-sets/new`, but `registry.py:163` wants `/questionnaires(/.*)?$`.
  *Reproduced:* `cause`.
- The db test (`ledger.db.test.ts`, "a new set and its questionnaire") only checks the outbox rows,
  never the relay, so it passes.

*Fix:* add the second page to each `caused_by` (`question_set.created` also from
`_QU + "/questionnaires/import$"`; `questionnaire.created` also from `_QU + r"/question-sets(/.*)?$"`).
Then add a step-1 case for each.

**M2. `qualification.opened` is emitted inside every card server action, and rejected each time.**
`page.tsx:43-56` emits on every render of the card page. Next.js 15.0.3 re-renders the page in the same
POST whenever a server action called `revalidatePath`
(`node_modules/next/dist/server/app-render/action-handler.js:337`, `skipFlight:
!workStore.pathWasRevalidated`). `linkComponent`, `unlinkComponent`, `patchOntologyNode`,
`resetOntology` and `rerunFill` all do. So each of those writes a second event,
`qualification.opened`, citing the POST.
- `registry.py:173` allows only `GET`, so the relay rejects it (*reproduced:* `cause`).
- Every edit on a card therefore adds a `ledger.rejected` to the log, and reconciliation has a stream of
  near-misses to explain.
- It also records an "opened" that no person did. `router.refresh()` in `FillStatus.tsx` adds another one
  after each refinement.

*Fix:* emit only on a real page view: skip when `headers().get("next-action")` is set (and, if wanted,
when `rsc` is set without a navigation). Add a test: a card action with `next-action` set writes no
`qualification.opened`.

**M3. The forms events are rejected after each build for whichever branch runs second (action id).**
`saveQuestionSet` makes both `question_set.created` (new set) and `question_set.version_created` (next
version). `saveQuestionnaire` makes both `questionnaire.created` and `questionnaire.version_created`.
Spec 4.5 binds a `Next-Action` id to the actions of the first request with accepted events.
- After a deploy, if the first save is a new set, every later "save next version" is rejected with
  `action_id` and raises an alarm, and the other way round. This lasts until the next build.
- *Reproduced:* the same `next_action` on `/question-sets/new`, then on `/question-sets/s1/edit`, gives
  `['action_id']`.
- Spec 4.5 states this as a limit for a "conditional branch". Here it hits the two main branches of the
  two main forms actions, so in practice about half of the forms events would be rejected.
- `test_ledger_step1.py` gives each case its own project, so each binding starts fresh and this never
  shows.

*Fix:* give each event its own server action: `createQuestionSet` and `saveQuestionSetVersion` (likewise
for questionnaires), and register each. Or emit one action per server action (for example
`question_set.saved` with `created: bool`). Add a step-1 test that makes two requests with one action id
in one project.

**M4. A run that fails before its model is known loses its `agent.run_failed`.** The internal route
requires a model on every AI event (`422 model: an AI event names its model`, reproduced).
`fill/ledger.py:86` adds `model` only once `fill_one` has set it (`agent.py:51-53`), which happens after
`clients.qualification(...)`, `baf_llm.config_for(...)` and `build_llm(...)`.
- Those three steps are where runs most often fail: the app is down, the project has no model, or the
  key is wrong.
- In that case `service.py:68` posts `agent.run_failed` with no model, gets 422, logs "refused" and gives
  up (`ledger.py:96-98`). `agent.run_started` was never sent either.
- The ledger then shows `card.ai_refinement_requested` and nothing after it, and `verify.open_runs` can't
  see it, since it counts only runs that have an `agent.run_started`.
- `test_a_failed_run_records_why` passes because its fake platform answers 202 to anything. That is a
  fake hiding the real behaviour.

*Fix:* send a model on every run event. Use the configured one when known, and a fixed placeholder such
as `"unknown"` before that, or relax the route for `agent.run_failed`. Make the test's fake answer 422
when `model` is missing, as the real route does. Also make `open_runs` count starts
(`card.ai_refinement_requested`) that have no `agent.run_finished` or `agent.run_failed` after
`RUN_WINDOW`, which also covers the cases in m3.

**M5. `agent.run_failed` puts free exception text into immudb (I8, I10).** `service.py:68` sends
`str(exc)[:500]`. The relay's `secret_in` catches some shapes but not others. I posted three
realistic error texts (reproduced):
- an OpenAI-style `sk-proj-...` key: rejected (`secret_in:error`). So the failure event itself is
  lost, and it lands only as a rejection.
- a Google-style key in a URL query string (`...:generate?key=AIza...`): **accepted, and stored in
  immudb**, which can't be edited or erased. requests-style HTTP errors and user-set `base_url` values
  carry URLs like this.
- a parse error quoting the model's answer ("the answer was 'The system scores Jane Doe, born
  1980...'"): accepted. Personal data from the card ends up in the immutable log, outside any
  minimisation.
- `clients.ServiceError` texts carry URLs and up to 200 bytes of response bodies (`clients.py:47`).

*Fix:* never send `str(exc)`. Send a fixed category (`exc.__class__.__name__` plus a code from a closed
list: `app_unreachable`, `no_model`, `llm_error`, `parse_error`, `publish_refused`). If the text is
wanted, keep it in the agent's own log, or as `fingerprint(...)` only. Add a test that a run failing
with a key in its message sends no part of the key.

**M6. The forms events name the person in their frozen content.** `QuestionSetService.ts:340,347`,
`QuestionnaireService.ts:231,259,261,403,410,420,422` put `createdBy` into the plan, and the plan is the
event's `content` (`QuestionSetService.ts` `content: plan`, and `questionnaireSaved` line 66).
`createdBy` is `callerName()`: the token's `preferred_username`, email or subject.
- The relay freezes `content` in `ledger.content` (`relay.py:528`), and the export ships it to
  auditors.
- `content_sha256` in immudb is a keyed digest over a value holding the name. The content key is
  exported, so anyone with an export can confirm a guessed name against an immutable entry.
- This breaks "the app never names a person" (I2) and the minimisation of I10: `actors.erase` can't cut
  this link.

*Fix:* strip `createdBy` (and any other who-did-it field) from `content` before emitting. The witness
already says who acted. Add a test that no step 1 event's content carries `callerName()`'s value.

**M7. The qualification unit suite is red because of this phase.** `test/unit/secrets.test.ts` flags
`services/agents/tests/test_drill_agent_killed.py:52` (`"PLATFORM_LEDGER_AGENTS_TOKEN":
"agents-drill-token"`) as an inline credential. The definition of done asks for every touched suite
to be green. *Fix:* use values the guard ignores (`test-` prefix, under 16 characters), or build them at
run time, as `test_ledger.py` does for its own values.

## Minors

- **m1. The item chain (I11) breaks on every card.** All the card's events use
  `item = (qualification, <card id>)`, the item group the `caused_by` regex binds. But their
  `before`/`after` describe different parts of the card: one link (`component-actions.ts:98,105`), one
  node's patch (`ontology-actions.ts:68`), or the whole patch (`ontology-actions.ts:95`). `verify`
  compares each `before` with the previous `after` of the same item, so mixing them breaks the chain.
  *Reproduced:* link A, correct n1, relink A, correct n1 again gives `chain_breaks == 2` with nothing
  wrong. *Fix:* send the whole card state that matters (the link set plus the patch) as before/after, or
  move the part states into `content` and keep before/after for whole-item states only.
- **m2. A correction's `before` is read outside its transaction.** `OntologyService.patchNode` reads
  `q` in `findChangeable`, then saves the whole patch in a later transaction. Two concurrent corrections
  of different nodes lose one in the database (this was already so), while the ledger and the history
  record both as done. *Fix:* read the patch inside the transaction with `SELECT ... FOR UPDATE`, or
  update with `jsonb_set`.
- **m3. Starts with no run.** `rerunFill` commits `card.ai_refinement_requested` before asking the
  agent. That order is right, but when the agent is down (`requestFill` false), or already has a run in
  flight for the card (`service.py` returns the old run and never uses the new id), the start has no
  run, and nothing reports it. Covered by the `open_runs` change in M4.
- **m4. Run events aren't bound to the start's item.** `_judge_run` checks the run and the request, but
  not that `card.augmented_by_ai.item_id` equals the start's card. A run opened on card A can be
  recorded as augmenting card B. *Fix:* for run events with the start's `item_type`, require the same
  `item_id`.
- **m5. `card.augmented_by_ai` names `program = qualification`.** The app emits it, so `_judge_run`
  records the app as the AI program. Accepted by the test (`source_app == "qualification"`), but an
  auditor reading the entry sees the app, not the agent. Consider adding `details.agent =
  "qualification_agents"`, or state it in the registry's comment.
- **m6. The agent blocks on the ledger.** `ledger.emit` is synchronous: 4 tries with a 10 s timeout and
  0.5 + 1 + 2 s sleeps, on every `ai.llm_call`. With the platform unreachable mid-run, each model call
  can wait up to about 43 s, so a 30-call run gains up to about 20 minutes. *Fix:* a background queue
  with a bounded wait, or one try per call and retries at the end of the run.
- **m7. `ledgerSafe` refuses `undefined`, which the written JSON drops.** `canonical.ts` throws on an
  object key whose value is `undefined`, but `JSON.stringify` (what is actually sent) drops it. Today's
  plans have no such keys (I checked the card input, the forms plans and the import plan), but the first
  optional field added later will make that save fail with `LEDGER_MODE` on, and only then. *Fix:* run
  `ledgerSafe` on `JSON.parse(JSON.stringify(body))`.
- **m8. `card_history` is append-only against DML only.** The app runs `prisma migrate deploy` with its
  own URL (`projectDb.ts:89`), so `qualification_rw` owns the table. It can `TRUNCATE` it, or
  `DISABLE TRIGGER`. The trigger doesn't cover TRUNCATE. The ledger's digests still reveal any
  rewrite, so this is stated, not urgent. *Fix:* add a `BEFORE TRUNCATE` statement trigger, and note
  the owner limit in the migration's comment.
- **m9. Writes with no event raise `witness_without_event`.** The exception routes `readDocument`,
  `readQuestionSetFile` and `readQuestionnaireFile` are witnessed POSTs, and so is every refused or
  no-op action (an unlink with no link, a reset with no corrections). `verify` counts each of them as a
  witnessed write with no event. *Owner:* phase 10's reconciliation should take the exception list into
  account, or the witness should mark these pages.

**Test gaps found by mutation** (each survived, and is not a finding of its own; the fix is a test):
the platform client's forwarding of `X-AISC-Request-Id` (Q4 names it, and no test covers it);
`FillerClient` sending `X-AISC-Run-Id`; the run opened *before* the agent is asked (moving it after
`requestFill` passes every test); and "in the same transaction" for drafts, links and corrections
(moving the draft's event to a second transaction passes; only card creation has a failure-after-event
test).

## What holds (checked, no finding)

- **Same transaction, none on rollback.** Every card and forms write calls `emitEvent(tx, ...)` with the
  interactive transaction's client, after the change, so the event and its history row commit or roll
  back with the change. Card creation's db test injects a failure after the event, and neither stays.
  An old card refused by the only-latest trigger leaves neither change nor event (db test).
- **No person named by the app.** `eventBody` never sets actor fields, and the agent's events carry only
  ids, the model and counts. `ai.llm_call` details carry the purpose, the property name, the round and
  the latency, never a prompt or an answer.
- **Request id.** Caddy strips client `X-AISC-Request-Id` (`strip-and-sign-in`) and the witness sets it.
  The emitter reads it from `next/headers`. The agent only accepts uuids (`_uuid_or_none`, tested).
- **Forgery of run events.** Only the holder of `QUALIFICATION_AGENTS_TO_WEB_TOKEN` reaches the
  `card.augmented_by_ai` branch. A person's PUT is always `card.extracted_replaced_by_user`, whatever
  run headers it sends. The internal route takes the emitter from the token. The run check finds the
  start by run id and request id, so the person comes from the start (apart from m4).
- **LEDGER_MODE off.** No outbox row is written (db test, and the mutation is caught). What differs from
  before: history rows are written, the card page and the PDF route open an empty transaction per
  request, `resetPatch` with no corrections no longer rewrites `{}` (so `ontologyAt` isn't bumped), and
  `unlinkComponent` with no link no longer issues a delete. None of these changes behaviour a person
  sees.
- **Canonical twin.** `canonical.ts` passes both shared vector files (fixed and random). The copies are
  byte-equal to the platform's (`test_the_typescript_twin_checks_the_platforms_own_vectors`). Integers
  beyond 2^53 are refused before the write, which matches what the relay would do with jsonb.
- **Registry shapes.** The details keys, `content_required`, item ids against the `item` groups, and
  `per_request` all pass the real registry for the shapes `emit.ts` builds (step 1 test and probes), on
  the right pages.
- **Caddy.** `/qualification/p/*/qualify/*` is witnessed on GET; the real-Caddy test hits that path
  first. The reasoned exceptions are correct: each one writes nothing, or (`loadOntology`) only the
  derived graph, which has no caller today.
- **Compose and tokens.** `PLATFORM_LEDGER_AGENTS_TOKEN` is held by `platform` and
  `qualification-agents` only (credentials test). Both qualification services default to
  `LEDGER_MODE=off`.

## Mutations (each applied in the checkout, the tests run, then the file restored by copying the original back from my scratchpad and checked with `git diff`)

| Mutation | Tests run | Result |
|---|---|---|
| `PlatformClient` no longer forwards `X-AISC-Request-Id` | unit | **survived** |
| `FillerClient` no longer sends `X-AISC-Run-Id` | unit | **survived** |
| `rerunFill` opens the run after asking the agent | unit + db | **survived** |
| draft event moved to a second transaction (`extracted/route.ts`) | db | **survived** |
| relink writes no history row | db | caught |
| `ledgerOn()` always true | db | caught ("nothing is written while the ledger is off") |
| agent: `agent.run_failed` not sent | agent | caught |
| agent: published draft without `X-AISC-Request-Id` | agent | caught |

After each mutation `git diff --stat` on the qualification repo was empty. The probe file
(`platform/tests/ledger/test_zz_rev5_probe.py`) was deleted, and the only file this review leaves is
this one. My own throwaway Postgres and immudb (`aisc-t-rev5p-*`) and the db-test containers
(`aisc-t-rev5-*`) were removed.

**Whole `platform/tests/ledger` run** (own env, `LEDGER_TESTS_REQUIRED=1`, my probe file excluded): 602
passed, 3 skipped (the opt-in drills), 1 failed: `test_ledger_platform_events.py::test_pending_platform_database_rows_never_block_a_delete`.
It passed when run again on its own. It looks like the known delete-while-a-session-is-open race
(open item 3 of the phase 3-4 report), in code phase 5 doesn't touch.
