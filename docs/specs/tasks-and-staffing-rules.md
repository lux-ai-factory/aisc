# Who does what: tasks, checkers and sign-offs (first version)

AISC knows who may write in a project (owner, editor, viewer). It does not know who is expected to do a step,
who checks it, or how many people that takes. This first version adds exactly that, and nothing more.

The number of checkers is a setting per kind of task: 0 (one person alone), 1 (four eyes), 2 or more.

## What this version guarantees

1. Every step of a project is a task that shows who did it and who has to check it.
2. A project chooses, per kind of task, how many people must check it.
3. Nobody counts as a checker of content they wrote.
4. A sign-off is given on fixed content. If the content changes afterwards, the sign-off stops counting and the
   task goes back for checking.
5. Each person sees one list of what waits for them.
6. Every rule change, submit, sign-off and send-back is in the project's ledger, and the report says who did and
   who checked each part.

## Not in this version

Each of these can be added later on top, without changing what is here: functions and lines (risk, compliance),
several check stages in order, committees ("2 of these 5"), sampling, project tiers, an installation floor,
changes that wait for a second person, deputies and hand-over, a release sheet for reports, a fresh sign-in
before signing. The fuller design is in this file's history.

## 1. Kinds of task

`platform_service/work/kinds.py`: `KINDS` and `LABELS`, as built (thirteen kinds, in the order of the steps).

## 2. The rule

One number per kind of task: `checkers`, from 0 to 5. That is the whole rule.

- Stored in the project's database: `work.staffing_rule (kind, checkers, set_by_subject, set_by_name, set_at)`,
  one row per change, never updated. The rule in force is the latest row for the kind.
- Two presets: `light` (0 everywhere) and `four_eyes` (1 everywhere, except 0 for launching a run and composing a
  report). New projects start with `light`.
- Owners change the rule. Each change is an event `staffing.rule_changed` (kind, before, after).
- `GET /projects/{p}/work/rules` answers `{kind: checkers}`. `PUT /projects/{p}/work/rules/{kind}` with
  `{"checkers": n}` sets one. `POST /projects/{p}/work/preset` with `{"preset": name}` sets all.

## 3. Tasks

`work.task (id, kind, subject, state, created_at, checkers_needed)`. `checkers_needed` is copied from the rule
when the task is submitted, so a later rule change does not move a task already in check.

| State | Means |
|---|---|
| `open` | not submitted yet |
| `in_check` | submitted, waiting for sign-offs |
| `done` | enough sign-offs, or none were needed |

- **Created** from the project's state, one open task per subject (a checklist submission, the card, the risk
  register, a run marked for the report). Which event or page action creates and submits each kind is one table,
  `platform_service/work/mapping.py`, with a test per row.
- **Doers** are the people who wrote to the subject while the task was open, read from the write events the
  apps already record. Nobody is assigned by hand in this version.
- **Submit** is the step's own completing action where one exists (closing a checklist submission, generating a
  report), else a "Submit for check" button. At submit the platform stores the content hash of the subject.
- **Sign-off**: agree, or send back with a reason. The page sends the content hash it showed; the platform
  compares it with the stored content in the same transaction and refuses the sign-off when it changed.
- **A doer cannot sign.** The refusal says why: "You changed this on 2 Dec, so you cannot check it."
- **Send back** returns the task to `open`; its sign-offs no longer count.
- **A content change while in check** returns the task to `open` the same way.
- **Done** when the agreeing sign-offs on the current content reach `checkers_needed`. With 0, at submit.

`work.sign_off (task, signer subject, signer name, answer, reason, content hash, at)`, never updated.

## 4. Pages

- **My tasks**, in the launcher: what waits for me to check, and what was sent back to me.
- **The project's work board**: each step, its state, who did it, who checked it.
- **Who does what**: the number of checkers per kind, editable by owners.
- **Sign-off**: the submitted content, the doers, earlier sign-offs and send-backs, Agree / Send back.

## 5. The report

One block, "Who did what": per part, the doers, the checkers with their dates, and "no check required" where the
rule was 0.

## 6. Events

`staffing.rule_changed`, `staffing.preset_applied`, `task.submitted`, `task.signed`, `task.sent_back`,
`task.done`, `task.reopened`. The person in an event is given by their actor reference; a reason is content,
never a detail. A task change the platform makes because an app's event arrived is recorded as an event derived
from that event (the ledger's derived-event path).

## 7. Tests

Written a few at a time, right before the code they drive.

| What | Kind |
|---|---|
| The rule: 0 to 5, the two presets, the latest row wins | pure and database |
| Only owners change the rule; each change is an event | API and ledger |
| Each row of the mapping creates and submits its task | database |
| A doer cannot sign | API |
| A sign-off on changed content is refused | API |
| A content change while in check reopens the task | API |
| 0, 1 and 2 checkers: done at the right moment | API |
| My tasks lists what waits for me, and nothing else | API |
| The report's block names doers and checkers | render |
