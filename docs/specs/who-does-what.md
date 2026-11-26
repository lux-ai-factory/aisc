# Who does what: one person per part at a time

Several people work on one project. AISC avoids conflicts between them by design rather than by detecting them:
every piece of work is a task, a task is split into parts, and each part is held by one person at a time. Only
the holder saves on it. A part is checked by as many other people as the project chooses, on content that no
longer changes.

## What this version guarantees

1. Every step of a project is a task, split into parts where its content splits naturally.
2. A part is held by at most one person at a time, and only that person can save on it. The tool enforces this in
   every save path, not only on the page.
3. A holder who is away does not block the work: an owner can take a part over or give it to someone else.
4. Every record says which state of the AI card it was made on, and a page says when the card changed since.
5. A project chooses, per kind of task, how many people check it: 0, 1, 2 or more.
6. Nobody checks a part they held. A sign-off is given on fixed content.
7. Each person sees one list of what they hold, what waits for them to check, and what was sent back to them.
8. Every take, hand-over, take-over, submit, sign-off and refusal is in the project's ledger, and the report says
   who did and who checked each part.

## Not in this version

- Several people drafting the same part separately and one person consolidating. Added for a kind of task only
  when its content cannot be split.
- The engine's own pages (test settings, launches) and the admin-only pages (connections, installs): they are not
  held. The engine is upstream code, and the admin pages have one writer in practice.
- One person overwriting themselves from two browser tabs.
- Functions and lines, several check stages, committees, sampling, tiers, an installation floor, changes that
  wait for a second person, deputies, a release sheet for reports.

## Words

| Word | Meaning |
|---|---|
| **Task** | One piece of work on one subject: the AI card of a version, one checklist submission, the risk register. |
| **Part** | A piece of a task that one person can do alone: a section of the card, a section of a checklist. A task that does not split has one part. |
| **Holder** | The person who holds a part now. Nobody, or one person. |
| **Doers** | Everyone who held a part of the task and saved on it. |
| **Checker** | A person who signs off a submitted task. |
| **Card state** | The pair (card version, revision number). A correction changes the revision, a new version both. |

## 1. Tasks and parts

- The kinds of task are `KINDS` in `platform_service/work/kinds.py` (thirteen, in the order of the steps).
- A task is created from the project's state, one per subject: the card when a version is saved, a checklist
  task when a submission is started, and so on. Which event or page action creates and completes each kind is one
  table, `platform_service/work/mapping.py`, with a test per row.
- **Parts.** The AI card splits into the sections of its form, and a checklist into its sections, as their apps
  already show them. Every other kind has one part. `work.part (task, key, label)`.
- `work.task (id, kind, subject, state, created_at, checkers_needed)`, states `open`, `in_check`, `done`.

## 2. Holding a part

`work.hold (task, part, holder_subject, holder_name, since)`, one row per held part.

- **Take.** Any editor or owner takes a part nobody holds.
- **Release.** The holder lets it go.
- **Hand over.** The holder gives it to another editor or owner, who accepts or declines.
- **Take over.** An owner takes a part from its holder, or gives it to someone else, with a reason. The former
  holder is told.
- Take, hand over and take over are platform routes. Each runs under a row lock on the part, so two people taking
  the same part at once get one holder and one refusal.

**The first save takes the part.** Saving on a part nobody holds makes the person saving its holder, and creates
the task and the part when they do not exist yet. Nobody has to press Take before starting, and a part is never
in a state where nobody can save on it.

**Only the holder saves.** Every save on the content of a part checks, in the same transaction as the write, that
the person saving holds that part (taking it when nobody does). The database function is
`work.claim_for_save(kind, subject, part, label, person_subject, person_name)`; apps call it through:

| Language | Helper |
|---|---|
| Python | `aisc_identity.holds.claim_for_save(conn, kind, subject, part, label, person_subject, person_name)` |
| TypeScript | `claimForSave(tx, kind, subject, part, label, personSubject, personName)` in `shared/access-ts/holds.ts`, vendored into qualification and controls |

The helper reads `work.hold` with `FOR SHARE`, so a take-over waits for a save in progress and the next save sees
the new holder. A save by someone else is refused with the refusal object (section 5), code `not_holder`: "Maria
Rossi holds this section since 10:40. Your text is kept below; ask her to hand it over, or an owner to give it to
you." The page keeps the typed text.

A save on a task in check is refused with `not_final`: the content of a submitted task does not change.

**A switch per project.** Holding is on or off per project, in `work.setting`. While it is off,
`claim_for_save` neither takes nor refuses, so the project works as before. It is off for existing projects and,
in this version, for new ones; an owner turns it on (`PUT /projects/{p}/work/holds` with `{"on": true}`, event
`work.holds_switched`). It becomes on by default once the pages show who holds a part.

**Automatic writers** (the card's AI refinement, sync jobs) write only for the person holding the part when they
started, and only while that person still holds it. Otherwise their result is dropped, the holder is told, and an
event records it.

A static test lists every save path of qualification, controls and control-objectives and fails when one of them
does not call the helper.

## 3. The card state

The card state moves when qualification stores a card. Every other record that depends on the card stores the
card state it was made on.

- **One lock.** Advisory key `hashtext('project.system')` in the project's database: exclusive in the transaction
  that stores a card, shared in every writer that stamps or compares a card state. A save takes it as its first
  statement. A correction takes it right after the platform has counted the revision (the platform's count takes
  the same lock in its own transaction, so taking it earlier would make the correction wait on itself), and still
  before it commits, so no stamping writer reads the card in between.
  Helpers `aisc_identity.card_lock.exclusive(conn)` / `shared(conn)` and `cardLockExclusive(tx)` /
  `cardLockShared(tx)` in `shared/access-ts/cardLock.ts`. They refuse to run outside a transaction. A static test
  lists the stamping writers and fails when one does not take the lock.
- **Versions a person can open.** `project.carded_system`, the versions of `project.saved_system` that have a
  stored card (template migration `0042_carded_system.sql`). In this version the readers stay on `saved_system`,
  which already leaves out abandoned versions; moving a reader to `carded_system` is done when a page shows a
  version with no card, together with the tests that name `saved_system` today.
- **The page says when the card moved.** A page drawn on one card state shows "The AI card changed since you
  started (Maria Rossi, 11:02: intended purpose)" when it is no longer the latest.
- **Committing actions ask once.** Submitting a task, launching a run and generating a report, when only the card
  state moved, answer `upstream_moved_confirm` with one question and one button. They are refused with
  `upstream_moved` when something they depend on changed.

## 4. Checkers and sign-offs

- **The rule** is one number per kind of task, `checkers`, from 0 to 5, in `work.staffing_rule (kind, checkers,
  set_by_subject, set_by_name, set_at)`, one row per change. Two presets: `light` (0 everywhere) and `four_eyes`
  (1 everywhere, except 0 for launching a run and composing a report). New projects start with `light`. Owners
  change it; each change is an event. `GET /projects/{p}/work/rules`, `PUT /projects/{p}/work/rules/{kind}` with
  `{"checkers": n}`, `POST /projects/{p}/work/preset` with `{"preset": name}`.
- **Submit.** When every part is released, a doer submits the task: the step's own completing action where one
  exists (closing a checklist submission, generating a report), else a "Submit for check" button. The platform
  stores the content hash and the card state, and copies `checkers_needed` from the rule.
- **Sign-off.** Agree, or send back with a reason. Nobody who held a part of the task can sign. The page sends the
  content hash it showed and the platform compares it in the same transaction.
- **Send back** returns the task to `open` and gives each part back to its last holder.
- **Done** when the agreeing sign-offs on the submitted content reach `checkers_needed`; with 0, at submit.
- `work.sign_off (task, signer_subject, signer_name, answer, reason, content_hash, card_state, at)`, never
  updated.

## 5. The refusal

Each app keeps its own error envelope; inside it a refusal carries the same object, defined once in
`shared/identity/refusal-cases.json` and read by the Python and the TypeScript tests.

```json
{"code": "not_holder", "what": "Intended purpose",
 "message": "Maria Rossi holds this section since 10:40. Your text is kept below.",
 "current": {"holder": "Maria Rossi", "since": "2026-01-20T10:40:00Z"}}
```

Codes: `not_holder`, `not_final`, `upstream_moved`, `upstream_moved_confirm`, `already_exists`, `cited_by_report`,
`syncing`, `token_required`, `changed_since_opened` (kept for the pages not held in this version). The message
names the thing as the page labels it, the person and the time; never a generic error. Every refusal is an event
`write.refused`, without the refused values. Helpers: `aisc_identity.refusal.Refusal` and
`shared/access-ts/refusal.ts`; the platform answers it as `detail`.

## 6. What a report may claim

1. **A built-in layout can be generated.** On the page's form, "no revision" is accepted for a built-in layout
   only; a stored layout's form without one generates nothing and the page says why. The JSON route asks for the
   layout as it is now when it names no revision, and stays accepted.
2. **An amendment is a submission that follows another one**, listed whether or not a reason was given; reason and
   requester print when present, "no reason given" when not. Shared contract file
   `apps/controls/test/fixtures/amended-submission.json`.
3. **"The latest submission" is the latest closed one.** A draft prints only with the block option `drafts: true`,
   under "Draft, not final", and is never counted in coverage. A block with no closed submission is `empty`. A
   newer draft is mentioned in one line. "Newer results exist for version n" counts closed submissions only.
4. **Until reports list the records they were built from,** every report prints: "This report does not list the
   records it was built from."
5. **Who did what.** One block: per task and part, the doers, the checkers with their dates, "no check required"
   where the rule was 0, and parts taken over, with the reason.

## 7. Pages

- **My tasks** (launcher): parts I hold, tasks waiting for my sign-off, tasks sent back to me, parts nobody holds
  that I could take.
- **Work board** per project: each task and part, its holder and since when, its state; for owners, take over and
  give to.
- **Who does what**: the number of checkers per kind, editable by owners.
- **Sign-off**: the submitted content, the doers, earlier sign-offs and send-backs, Agree / Send back.
- On every held page: who holds this part, a Take button when nobody does, and the card banner of section 3.

## 8. Events

`hold.taken`, `hold.released`, `hold.offered`, `hold.handed_over` (the offer accepted), `hold.offer_declined`,
`hold.taken_over` (with the reason as content), `task.submitted`,
`task.signed`, `task.sent_back`, `task.done`, `staffing.rule_changed`, `staffing.preset_applied`, `write.refused`,
`automatic.result_dropped`. The person in an event is given by their actor reference. A task change the platform
makes because an app's event arrived is recorded as an event derived from it.

## 9. Tests

Written a few at a time, right before the code they drive.

| What | Kind |
|---|---|
| Two people take the same part at once: one holder, one refusal | two database sessions |
| A save by someone who does not hold the part is refused with `not_holder`, and nothing is written | per app, real database |
| A take-over waits for a save in progress; the next save by the former holder is refused | two database sessions |
| Every save path calls the holder helper | source text |
| A save on a task in check is refused with `not_final` | per app |
| An automatic result for a former holder is dropped and recorded | platform |
| The card lock and `carded_system` | database |
| A committing action after a card correction asks once | API |
| 0, 1 and 2 checkers: done at the right moment; a holder cannot sign; a changed hash is refused | API |
| The refusal object, in Python and TypeScript, from one case file | pure |
| The four report corrections and the "Who did what" block | render and database |
