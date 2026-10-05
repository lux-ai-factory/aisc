# Ledger: phase 7 review, step 4 (the controls app) (2026-10-03)

**Verdict: 0 blockers, 4 majors, 10 minors. Phase 7 is not done yet.**

The emitter itself is sound. It is byte for byte the qualification one (`emit.ts` and `canonical.ts`
diff empty against `apps/qualification/src/server/ledger/`). Every Prisma write reachable from a route or
a server action now runs in an interactive transaction with its `ledger.emit`. Each in-app event fits the
real registry on the page its form is really mounted on. The app names no person, and none of the
phase 5 traps came back: there is no page-view emit (so no re-render events), every server action has
its own export (so no action-id clash; the draft's save and close share one through `same_action`),
and `createdBy`-style fields can't reach content.

What keeps the phase open:
- the plan's own K1 ("a question review keeps closed answers") is not met. A review still deletes every
  answer of the checklist, closed ones included, and that now happens even when only the title changes
  (M1);
- two of the three install paths are always rejected (M2);
- the events that are meant to keep what a review deletes are lost whenever one answer looks like a
  token (M3);
- the suites that exercise the changed actions were not run (M4).

## What I checked, and how

Commits: aisc cbd1f2f (the controls registry entries) and 9fd6984; apps/controls 8c4c2b5, all on
`feat/unified-modules`. I read the whole diff of each, apart from the 6012-line vectors file, which a
test checks byte for byte. I also read spec 4.2 to 4.5, 6.4 and 6.5, the coding plan's phase 7 row,
test plan K1-K3, `19-phase5-review.md`, the relay's `_judge`, `_cause`, `_check_action` and
`_learn_action`, and `verify.verify`'s chain check. I made no commits, pushed nothing, never touched the
live stack, never used port 5432, never ran docker compose, and never ran a controls test that uses
`docker exec postgres`.

| Suite | Result |
|---|---|
| controls unit (`npx vitest run test/unit`) | 183 passed |
| controls throwaway integration (ledger, install-once-throwaway, dashboard-grants, answer-stamps, isolation-answer-fk, isolation-routes-by-id), own env `aisc-t-rev10-ba2b0d` | 31 passed, 0 skipped (`ledger.test.ts` ran its 5 tests) |
| `platform/tests/ledger/test_ledger_step4_controls.py` + `test_ledger_step1.py` (`LEDGER_TESTS_REQUIRED=1`) | 36 passed |
| `scripts/tests/test_ledger_coverage.py` + `test_ledger_action_pages.py` | C4[controls] green, C5 green; C1 red only for other apps' routes (connectors, report composer, renderer), none of them controls |

**Probes.** I wrote 4 probe tests in a temporary file next to the platform's ledger tests (removed
afterwards). They run against the real registry, witness and relay in `enforce`, and all 4 passed, so
M2 (both paths), M3 and m2 are reproduced, not inferred.

**Every Prisma write reached from a route or a server action** (all of `src/`, found by grep for
create/update/upsert/delete/`$executeRaw`/`$transaction`):

| Write | Where | Event | Same transaction |
|---|---|---|---|
| source upsert, checklist and questions create | `installChecklist.ts:123-146` | `control.installed` (through the recorder) | yes, both attempts (lines 106, 115) |
| submission and answers create | `fill/actions.ts:36` | `controls.submission.created` | yes |
| submission update, answers delete and create | `submissions/[id]/actions.ts:106` | `draft_saved` or `closed` | yes, but `before` is read outside it (m1) |
| amendment create | `submissions/[id]/actions.ts:153` | `reopened` (on the closed one) | yes |
| archive / restore | `submissions/[id]/actions.ts:201,210` | `archived` / `restored` | yes |
| source create | `sources/new/actions.ts:54` | `controls.source.created` | yes |
| questions delete and create, checklist update | `review/actions.ts:58` | `questions_revised` | yes |

There is no other write: `projectDb.ts` only migrates, the report route only reads, and the PDF renderer
is stateless (route exceptions file).

**Mount pages** (where each server action POSTs from): `installHere` from `/p/[project]/catalogue`,
`submitForm` from `/checklists/[id]/fill`, `saveDraft`/`reopenForAmendment`/`archiveSubmission`/`restoreSubmission`
from `/submissions/[id]`, `createSource` from `/sources/new`, `saveReviewedQuestions` from
`/checklists/[id]/review`, and `installChosen` (which calls `installFromCatalogue`) from `/install`.
`/p/[project]/install` has no `page.tsx`, so the registry's `_CT + "/(install|catalogue)$"` matches only
the catalogue half. Every item group (`/submissions/(?P<item>)`, `/checklists/(?P<item>)/review`) equals
the item id the action sends, and the details keys and `content_required` match what the code builds.

## Majors

**M1. A question review still deletes every answer of the checklist, closed ones included, on any save of
the edit page. The plan's K1 is not met (declared item 1).**
`review/actions.ts:69` deletes every question and recreates them from the form. `ReviewForm.tsx:126`
posts only `q.<idx>.text/article/category` and no ids, so even an unchanged question gets a new row.
`SubmissionAnswer.question` is `onDelete: Cascade` (`prisma/schema.prisma`), so every answer goes with
its question.
- *Failure scenario:* an editor opens "Edit checklist" to fix a typo in the title and saves. Every
  submission of that checklist loses all its answers, closed and archived ones too. The page gives no
  warning.
- *What the person then sees:* the closed submission's PDF (`report/route.ts:64` uses the checklist's
  *current* questions) shows the new questions with no answers. The platform's evidence page
  (`evidence.py:93-98` counts answers per submission) shows that closed evidence as unanswered. Nothing
  in the app reads the ledger back.
- What phase 7 adds is the deleted questions and answers frozen in the review event's content, plus
  `questions_version`. The ledger now proves what was lost, but the loss itself stays.
  `ledger.test.ts:143` ("K1") asserts that the closed answer *is removed* and found in the event. That is
  the opposite of the plan's K1 ("a question review keeps closed answers"), so the test now pins the
  data loss as correct behaviour.
- The event-registry gap list (`01-event-registry.md`, gap 2) names this cascade as something to fix
  "with or before the ledger". Phase 7's drill ("question review with closed submissions") can't pass.

*Is the interim acceptable?* Only as a short-lived state while `LEDGER_MODE=off`, decided by the user,
and only with two cheap guards landed now:
1. When the parsed questions equal the current ones (same text, article and category, in order), don't
   touch the question rows at all, and update only the checklist's metadata. That stops the most common
   loss (a metadata edit) at no cost.
2. When the review would remove answers of a Closed submission, refuse with a message ("N closed
   submissions answer these questions: amend them, or confirm"), or require an explicit confirmation
   field that the event records.

With M3 open, the frozen copy can't be relied on as the only copy, so the interim as built is not
acceptable for `record`.

*The right fix:* soft-retired questions, diffed by id.
- `Question.retiredAt`. The unique `[checklistId, order]` becomes a partial unique index
  `WHERE retired_at IS NULL`, and the cascade on `SubmissionAnswer.question` becomes `Restrict`, so no
  hard delete can silently take answers again.
- `ReviewForm` posts each question's id. The action keeps an unchanged question, retires a removed or
  reworded one (a reworded question is a new question: an old answer answered the old wording), and
  creates new ones.
- The fill and draft forms show active questions. A closed submission's page and PDF render the
  questions it answered, joined through its answers, retired ones included.
- The platform's `evidence.py` and the report generator count active questions for "N questions", and
  join answers to their own questions for closed submissions.
- The review event then needs only before/after question lists with ids, and nothing is deleted.
- Test K1 becomes: a review keeps a closed submission's answers and its PDF unchanged.

**M2. Installs from the catalogue's API and from the install dialog are always rejected (declared item
2, reproduced).**
`api/install/route.ts:45` takes the project from the form body. `installChosen` (`app/install/actions.ts`)
takes it from the form on `/controls/install`. The witness finds a controls project only in
`^/controls/p/<project>` (`registry.py:56`), so both requests are witnessed with no project, and the
relay rejects the event at `relay.py:357`.
- *Reproduced:* a witnessed POST to `/controls/install` (with a `Next-Action`) and one to
  `/controls/api/install`, each followed by `control.installed` from `controls_rw`, give
  `['project_mismatch']` each, and nothing is accepted.
- Two of the three install paths, the catalogue's own dialog (the API) and its fallback page, therefore
  make installs with no accepted event in every mode. Only the in-app catalogue page is recorded.
- The two causes `("controls", "ACTION", r"^/controls/install$")` and
  `("controls", "POST", r"^/controls/api/install$")` (`registry.py:299-300`) can never pass. The first
  one exists so C5 (`test_ledger_action_pages.py`) passes for `installFromCatalogue`, which hides the
  problem: C5 checks the cause regex, not that the page can name a project.
- *Fix:* put the project in the path.
  - Serve the API as a route handler at `src/app/p/[project]/api/install/route.ts`
    (`/controls/p/<slug>/api/install`), with the catalogue posting there.
  - Have the dialog's project choice navigate to `/controls/p/<slug>/install`. Give that path a
    `page.tsx` that mounts the confirm form calling `installFromCatalogue`, which the existing
    `_CT + "/(install|catalogue)$"` cause already covers.
  - Drop the two dead causes.
  - Add a step-4 platform case per install path, and extend C5: every `ACTION` cause of a
    project-scoped action must match a path the app's project rule resolves.

**M3. One answer that looks like a token loses the save's event, and the review's record of what it
deleted (reproduced).**
The relay refuses content that matches `_SECRET` (`registry.py:384`: `bearer <x>`, `sk-...`, `eyJ...`).
Submission events put every answer of the submission in `content`/`before`/`after`, and the review event
puts every removed answer of every submission in `content`.
- *Reproduced:* a `questions_revised` whose removed answers include "We send Authorization: Bearer
  abc.def.ghi on each call" gives `['secret_in:content']`, and no `questions_revised` entry is kept.
- That answer is plausible on a security checklist ("how are API calls authenticated?"). Then:
  - each later save of that submission is rejected the same way, so its item has no accepted events;
  - a review of its checklist loses the frozen copy of every removed answer, all submissions' alike. The
    database has already cascaded them away, so they now exist nowhere. Only the rejection's row digest
    remains.
- This is what makes M1's interim unsafe. *Fix:* M1's soft retire removes the deletion, so nothing
  depends on the frozen copy. Until then, check the same pattern in the app (mirror `_SECRET` next to
  `ledgerSafe`). With the ledger on, refuse the save or the review with a message ("this answer looks
  like it contains a token; remove it"), since a live token in an answer is also a problem in the
  database. Add a step-4 case for it.

**M4. The suites that cover the changed actions were not run (declared item 4).**
`submission-lifecycle`, `project-scope`, `action-access` and `install` exercise exactly the code this
phase rewrote. That is `saveDraft`, `reopenForAmendment`, `archiveSubmission`, `restoreSubmission`
(whose not-found logic changed), `submitForm` and `installHere`, now in interactive transactions.
- They use `docker exec postgres`, the live container, so not running them was right.
- But the definition of done asks for every suite of every touched app to be green, and today nobody
  knows whether they are. For example, `project-scope.test.ts:208` expects `restoreSubmission` on another
  project's submission to throw, which now depends on the new `count` fallback.
- *Fix:* point those files at `throwawayDb.su` / `CONTROLS_TEST_PG_CONTAINER` (the helper and its guard
  exist; the change is mechanical), run them, and state the result.

## Minors

- **m1. The draft's `before` and its status check are read outside its transaction** (a repeat of phase
  5 m2). `submissions/[id]/actions.ts:63-65,79` read the submission, its status and its answers before
  the transaction at line 106.
  - *Scenario:* two tabs on one draft, one closes while the other saves. Both pass the `Draft` check, and
    the second rewrites the closed submission's answers.
  - Its event says `draft_saved`, with a `before` that is the pre-close state, so the chain breaks and
    the ledger describes a change that didn't happen that way.
  - This race existed before the ledger. *Fix:* inside the transaction,
    `updateMany({ where: { id, status: "Draft" } })`, then return the refusal on count 0, and read the
    old answers there.
- **m2. Every question review breaks the chain of every draft of that checklist (reproduced).** After a
  review the cascade has emptied the draft's answers, so its next save's `before` (no answers) differs
  from its last `after`. *Reproduced:* created, review, draft saved gives `chain_breaks == 1`. Reconciliation
  then has a false alarm per draft per review. M1's soft retire removes it.
- **m3. `submitForm`'s `after` is not built the way saves build `before`.** `fill/actions.ts:45` keeps
  the form's order. `stateOf` (`submissions/[id]/actions.ts:13`) sorts by `questionId` with
  `localeCompare`.
  - The two agree today only because cuids happen to be created in question order and the form renders
    in that order.
  - A reorder that keeps ids (which M1's fix will do) breaks the chain on every first save.
  - *Fix:* move `stateOf` to `src/lib/ledger/` and use it in `submitForm`. Test: a submission whose
    questions are answered out of id order keeps its chain.
- **m4. A review doesn't lock what it reads.** `review/actions.ts:59-69` reads the questions, the answers
  and `questionsVersion` without a lock.
  - An answer committed between the read and the delete is cascaded, but it isn't listed in
    `removed_answers`.
  - Two concurrent reviews both write version N+1, giving two events with the same `item_version`.
  - *Fix:* `SELECT ... FROM controls.checklist WHERE id = $1 FOR UPDATE` first, via `tx.$queryRaw`.
- **m5. What was installed isn't in the ledger.** `control.installed` carries only the catalogue id and
  a count, while the event registry asks for "package sha256". It has no content, so the question texts
  and ids are recorded nowhere. A source created by the install (`installChecklist.ts:124`) has no event
  of its own. The review's `after` (`review/actions.ts:88`) has no ids either, because `createMany`
  returns none.
  - So until a later review freezes them, nothing in the ledger ties a submission's `questionId` to the
    question it answered.
  - *Fix:* give `control.installed` content (package version and digest, source, questions with ids).
    Build the review's `after` with `createManyAndReturn` (Prisma 5.14 and later).
- **m6. An amendment's new submission has no creation event.** `reopened` is recorded on the closed item
  (`submissions/[id]/actions.ts:176`). The new item's first state appears only as the `before` of its
  first save. *Fix:* put the copied state in `reopened`'s content (or a new
  `controls.submission.amended`), and say in its comment that `next` starts from it.
- **m7. `controls.report.downloaded` and `controls.page.opened` were dropped without saying so.** Both
  are in `01-event-registry.md` section 4, and neither is in `registry.py` or the app. The PDF route
  isn't witnessed (`Caddyfile:153` uses `protect controls`, not `protect-reads`). Qualification's
  equivalent, `card.pdf_downloaded`, was done in phase 5. *Owner:* declare the move (phase 9 or 10) or
  add them.
- **m8. Behaviour with `LEDGER_MODE=off`.** No outbox row is written (tested, and the mutation is
  caught). What still changes:
  - Each write now runs in an interactive transaction, under Prisma's default 5 s timeout. Before, these
    were batch transactions, which have no timeout.
  - A review loads every answer of the checklist, joined to its submission, inside that transaction even
    with the ledger off. On a large project, a review that used to work can fail with P2028.
  - `questions_version` increments (nobody sees it).
  - `restoreSubmission` no longer bumps `updatedAt` on a submission that wasn't archived.
  - *Fix:* skip the removed-answers read when `!ledgerOn()`, and pass `{ timeout }` to the review's
    transaction.
- **m9. Test gaps.** These mutations survived (see below):
  - the draft's event in a second transaction;
  - the archive's event in a second transaction;
  - the API install with no event;
  - the dialog install with no event;
  - the race retry dropping the recorder.

  Also:
  - `ledger.test.ts` only reads outbox rows and never relays them;
  - `test_ledger_step4_controls.py` uses shapes written by hand (a minimal review content, one answer),
    so M3 and m2 can't show;
  - K3 ("the AI ingest call is logged") is dropped as "no AI ingest in the controls app" (declared item
    3). That's true, but the ingest exists in the catalogue (`catalogue.control.ingested`, event
    registry section 3), so K3 needs an owner phase rather than silence.
- **m10. No-op branches are witnessed writes with no event.** The reopen whose amendment already exists
  (a redirect), archiving an archived submission, restoring one that isn't archived, installing an
  installed control, and every refused save each leave a witness record and no event, so `verify` counts
  `witness_without_event`. That is the same as phase 5 m9, owner phase 10. (`isServerAction` in `emit.ts:55`
  is unused here; harmless.)

## What holds (checked, no finding)

- **Same transaction, none on rollback.** Every event is written on the interactive transaction's
  client, after the change. The failure-after-event test leaves neither the submission nor its event.
  The install's recorder runs inside `createChecklist`'s transaction on both attempts, so a raced install
  that rolls back leaves no event.
- **Registry fit.** Causes, item groups, details keys, `content_required` and `per_request` match what
  each action sends, on its real mount page. The exceptions are the two install paths of M2.
- **Action ids.** One export per event, apart from `saveDraft`, whose two branches are tied by
  `same_action` both ways (`relay.py` `_check_action`).
- **No person, no platform fields.** `eventBody` sends no actor field, and `withoutAuthors` strips
  `createdBy`-style keys. The content is the answers, labels, question texts and source fields: the
  evidence itself, never who wrote it.
- **Canonical twin.** `canonical.ts` is the qualification file. Both shared vector files are
  byte-equal to the platform's (the parametrized `test_the_typescript_twin_checks_the_platforms_own_vectors`).
- **Request id.** It is read from `next/headers` in server actions and in the route handler alike.
- **Migration.** `20261003000000_checklist_versions` only adds a defaulted column. `dashboard-grants`
  still passes, so `dashboard_ro`'s reads cover it.

## Mutations (each applied in the checkout, unit + `ledger.test.ts` + `install-once-throwaway` run, then the file restored by copying the original back from my scratchpad)

| Mutation | Result |
|---|---|
| `saveDraft`'s event moved to a second transaction | **survived** |
| `archiveSubmission`'s event moved to a second transaction | **survived** |
| `/api/install` records no event | **survived** |
| `installFromCatalogue` records no event | **survived** |
| the install's retry after a source collision drops the recorder | **survived** |
| the review's removed answers exclude closed submissions | caught (K1 test) |

(Two first attempts at the install mutations failed to compile and were redone. Only the valid runs are
listed.) After the mutations, `git status` and `git diff --stat` in `apps/controls` were empty. The probe
file `platform/tests/ledger/test_zz_rev12_probe.py` was deleted, and my env `aisc-t-rev10-ba2b0d` (pg and
immudb) was torn down. This file is the only one the review leaves. I didn't touch
`test_zz_rev11_probe.py` or the evidence/results files of the other session.
