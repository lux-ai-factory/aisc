# Who does what: staffing rules, functions, and the ledger's path for tasks

AISC knows who may write in a project (owner, editor, viewer). It does not know who is expected to do a step, who
checks it, or how many people that takes. This spec adds the first part of that: the rules a project sets, the
functions its members hold, who may change either, and the way the ledger accepts events the platform derives
from other events. Tasks, sign-offs and release build on it and have their own specs.

The number of people on a task is a setting. One person alone, two (four eyes), three, or "any 2 of these 5" are
the same rule with different numbers.

**Until sign-offs exist, a rule is shown and not enforced.** Every answer that returns rules says so
(`"enforced": false`), and the page that shows them carries "Shown, not enforced yet".

## Words

| Word | Meaning |
|---|---|
| **Task kind** | One of the kinds of work a project has (list below). |
| **Staffing rule** | For one task kind and one tier: how many people do it, and the check stages after it. |
| **Check stage** | One round of checking. A rule has 0 to 4, in order. |
| **Function** | What a member is to the project: system owner, risk, compliance. |
| **Line** | 1 (builds or owns the system), 2 (challenges), 3 (audits). Every function has one line. |
| **Tier** | `low`, `medium` or `high`: how much is at stake in the project. |
| **Floor** | What every rule of this installation must at least ask for. Set by the platform admin. |
| **Loosening** | A change that lowers control (section 4). |
| **Pending change** | A loosening that was proposed and waits for a second person. |

## 1. Task kinds

`platform_service/work/kinds.py`, `KINDS`, in this order:

`describe_system`, `correct_card`, `name_system`, `choose_objectives`, `rate_risks`, `choose_tests`,
`fill_checklist`, `amend_checklist`, `launch_run`, `review_results`, `map_evidence`, `compose_report`,
`release_report`.

Each has a label (`LABELS`) used on pages and in reports. The tiers are `TIERS = ("low", "medium", "high")`, in
the same module.

## 2. The staffing rule

A rule is a JSON object. `platform_service.work.staffing.validate(rule, functions=...)` returns it normalised
(every default filled in, the given object untouched) or raises `InvalidRule` with a `pointer` to the setting
(`/stages/0/needed`) and a `message` in words. `functions` maps the project's function names to their lines. A
setting the rule does not have is refused.

```json
{"doers": {"count": 1, "mode": "any_one", "from": {"kind": "any"}},
 "stages": [
   {"needed": 1, "from": {"kind": "functions", "functions": ["compliance"]}, "kind": "review",
    "other_line": false, "not_earlier_signer": false, "any_objection_sends_back": true, "due_days": 3},
   {"needed": 2, "from": {"kind": "functions", "functions": ["risk"]}, "kind": "approval",
    "other_line": true, "not_earlier_signer": true, "any_objection_sends_back": false, "due_days": null}],
 "sampled": null}
```

| Field | Values | Default |
|---|---|---|
| `doers.count` | 1 to 20 | 1 |
| `doers.mode` | `any_one` (one of them finishes it), `all` (each marks their part done) | `any_one` |
| `doers.from`, `stages[].from` | `{"kind": "any"}`, `{"kind": "functions", "functions": [...]}`, `{"kind": "people", "people": [subject, ...]}` | `any` |
| `stages` | 0 to 4 stages | none |
| `stages[].needed` | 1 to 20; with `people`, not more than the people named | 1 |
| `stages[].kind` | `review`, `approval` | `review` |
| `stages[].other_line` | the signer holds no function in a line a doer holds | false |
| `stages[].not_earlier_signer` | the signer signed no earlier stage of the same round | false |
| `stages[].any_objection_sends_back` | false: the stage is sent back only when `needed` can no longer be reached | true |
| `stages[].due_days` | working days, 1 to 60, or null | null |
| `sampled` | null (every task is checked), `{"one_in": n}` with n from 2 to 100, `{"when": [conditions]}` | null |

- "The signer is not a doer" is not a field. It always holds.
- A function named in a rule must exist for the project. `audit` can never be named.
- `sampled` with no stage is invalid: there is nothing to sample.
- Conditions: `test_failed`, `risk_above_3`, `risk_above_4`, `doer_asked`. `doer_asked` alone is invalid, because
  the doer would choose whether they are checked.

**Stored** in the project's database, one row per version, never updated or deleted:
`work.staffing_rule (kind, tier, version, rule jsonb, set_by_subject, set_by_name, set_at, confirmed_by_subject,
confirmed_by_name, reason)`, primary key `(kind, tier, version)`. The rule in force for a kind and tier is the
row with the highest version. Append-only by trigger; the platform's role has INSERT and SELECT only.

**Presets** (`platform_service/work/presets.py`): `NAMES = ("light", "four_eyes")`, and `rule(preset, kind, tier)`
gives the rule; an unknown preset is a `KeyError`.

| Kind | `light` | `four_eyes` |
|---|---|---|
| `launch_run`, `compose_report` | 1 doer, no stage | 1 doer, no stage |
| every other kind | 1 doer, no stage | 1 doer, one stage: 1 needed, from any member, review |

A project is created with `light` at tier `medium`. Applying a preset writes a new version of every rule that
differs.

## 3. Functions

**Catalogue.** `core.function (project_id, name, line, label)` in the platform database. `project_id` null means
the function exists in every project. The installation starts with:

| Line 1 | Line 2 | Line 3 |
|---|---|---|
| `system_owner`, `developer`, `tester` | `risk`, `compliance`, `legal`, `ethics`, `domain_expert` | `audit` |

An owner may add a function to their project with a name (`^[a-z][a-z0-9_]{1,39}$`), a label and a line of 1 or
2. Line 3 has `audit` only.

**Held by members.** `core.project_member_function (project_id, subject, function, granted_by, granted_at)`,
removed with the membership. Every grant and removal is also a row in `core.project_member_function_history`,
which is append-only.

`platform_service.work.functions` decides, and every refusal has a code. Each function returns the code, or
None when allowed:

- `grant_allowed(*, actor_subject, actor_role, actor_is_admin, member_subject, member_role, held, function,
  catalogue)`, where `held` is what the member holds now and `catalogue` maps function names to lines;
- `removal_allowed(*, actor_subject, actor_role, actor_is_admin, member_subject)`;
- `role_change_allowed(*, held, new_role)`.

Beside them: `grant_loosening(function, catalogue)` (the reasons a grant is a loosening, or an empty list),
`line_of(held, catalogue)`, `name_allowed(name)` and `line_allowed(line)` for a function a project adds.

| Rule | Code |
|---|---|
| Only an owner, or the platform admin, grants or removes | `owner_only` |
| Nobody changes their own functions | `own_functions` |
| The function exists for this project | `unknown_function` |
| All of a member's functions in one project have the same line | `mixed_lines` |
| `audit` is held alone | `audit_alone` |
| `audit` is held by a viewer, never by an editor or an owner | `audit_viewer_only` |
| A member who holds `audit` is not made editor or owner while holding it | `audit_viewer_only` (on the role change) |

Granting a function of line 2 or 3 is a loosening (section 4): it adds someone who may check. Granting a line 1
function, and removing any function, is not.

## 4. Who may change the controls

**Loosening.** `staffing.is_loosening(before, after)` returns the list of reasons, empty when the change is not
looser in any setting. Compared stage by stage, in order:

| Change | Reason code |
|---|---|
| Fewer stages | `fewer_stages` |
| A stage needs fewer people | `fewer_needed` |
| A stage's group got wider: people to functions or any; functions to any; a function or a person that was not named before | `wider_group` |
| `other_line`, `not_earlier_signer` or `any_objection_sends_back` switched off | `weaker_independence` |
| An approval stage became a review | `approval_to_review` |
| `sampled` went from null to anything; `one_in` got larger; a condition was removed from `when`; `one_in` became `when` | `more_sampling` |

Changes to doers and to due days are never a loosening. A change can tighten one setting and loosen another: it
is a loosening. Each reason is given once, in the order of the table.

The same word covers, outside the rule: a lower tier (`staffing.tier_change(before, after)` gives
`["lower_tier"]`), a lower floor (`staffing.is_lower_floor(before, after)`; reason `lower_floor`), and a grant of a
line 2 or line 3 function (`checker_added`).

**Rules.** `platform_service.work.controls.decide(*, actor_subject, actor_role, actor_is_admin, what, loosening,
reason)` returns `allowed`, `needs_second_person` or a refusal code. `what` is `rule`, `tier`, `function` or
`floor`; `loosening` is the list of reasons the change is one. `may_confirm(*, actor_subject, actor_role,
actor_is_admin, proposed_by, what)` and `may_reject(...)` return a refusal code or None; the proposer may reject
(withdraw) their own proposal. `acted_as(*, actor_role, actor_is_admin)` is `admin` for an admin with no role in
the project, else `owner`.

1. Only an owner or the platform admin changes a rule, the tier or a function. Only the admin changes the floor.
   Others: `owner_only` / `admin_only`.
2. A change that is not a loosening takes effect at once.
3. A loosening is stored as a pending change with its reason (a reason is required: `reason_required`) and takes
   effect when a second person confirms it. The second person is an owner of the project or the platform admin,
   and not the proposer (`same_person`). They may also reject it, with a reason. A lower floor is confirmed by
   another admin.
4. A project with one owner and no admin acting: the loosening waits. The page says who can confirm it.
5. A rule below the floor is refused at save, pending or not: `below_floor`, with what is missing.
6. An admin who is not a member of the project acts as admin: the stored row and the event say `acted_as: admin`.

Pending changes live in the project's database: `work.pending_change (id, what, target, before jsonb, after jsonb,
reasons text[], reason, proposed_by_subject, proposed_by_name, proposed_at, decided_by_subject, decided_by_name,
decided_at, decision)`. `what` is `rule`, `tier` or `function`. A row is inserted once and updated once, when it
is decided; a decided row is never changed (trigger). `id` is a uuid the database gives; `decision` is null while
it waits, then `confirmed` or `rejected`.

## 5. The tier

`work.tier_history (tier, reason, set_by_subject, set_by_name, set_at, confirmed_by_subject, confirmed_by_name)`,
append-only. The project's tier is the latest row. Raising it takes effect at once. Lowering it is a loosening.
The admin may set a lowest tier for a project (`core.project.lowest_tier`, null by default); a tier below it is
refused: `below_lowest_tier`.

## 6. The floor

`core.staffing_floor (kind, tier, floor jsonb, set_by_subject, set_by_name, set_at)`, `tier` null meaning every
tier. The floor for a kind and tier is the stricter, setting by setting, of the row for that tier and the row for
every tier (`staffing.combine_floors(for_tier, for_every_tier)`; either may be missing).

```json
{"min_stages": 1, "min_needed": 1, "require_other_line": false, "require_not_earlier_signer": false,
 "allowed_from": null, "sampling": "never"}
```

`staffing.meets_floor(rule, floor)` returns the list of what is missing, empty when the rule meets the floor:

| Floor setting | The rule fails it when | Code |
|---|---|---|
| `min_stages` | it has fewer stages, or it is sampled (a sampled rule counts as no stage) and `min_stages` is 1 or more, unless `sampling` allows it | `too_few_stages` |
| `min_needed` | any stage needs fewer | `too_few_needed` |
| `require_other_line` | any stage has it off | `other_line_required` |
| `require_not_earlier_signer` | any stage after the first has it off | `not_earlier_signer_required` |
| `allowed_from` (a list of functions) | any stage draws from `any`, from people, or from a function not listed | `group_not_allowed` |
| `sampling`: `never`, or `{"max_one_in": n}`, or null for no limit | the rule is sampled and it is `never`; `one_in` is above n; the rule samples by condition and a limit is set | `sampling_not_allowed` |

Without a floor a project is free, down to one person and no check.

## 7. Sampling

`staffing.draw_sample(key, subject_id, one_in)` returns whether a submitted task is checked.

- It is `int.from_bytes(HMAC-SHA256(key, subject_id), "big") % one_in == 0`.
- `key` is the project's ledger key, so nobody can compute the draw from the page, and an auditor with the key
  can recompute every draw.
- It depends on the subject and nothing else: submitting again, or cancelling and starting again, gives the same
  answer.

## 8. Routes

All under the launcher's `/api`, admitted through `aisc_identity.access`. Reads need a member, writes an owner.

| Route | Does |
|---|---|
| `GET /projects/{p}/functions` | the catalogue for this project |
| `POST /projects/{p}/functions` | add a project function |
| `GET /projects/{p}/members` | as today, plus `functions` and `line` per member |
| `PUT /projects/{p}/members/{subject}/functions` | body `{"functions": [...], "reason"}`: set a member's functions; answers 200 with the functions in force, and `pending` when a part of the change waits |
| `GET /projects/{p}/work/rules` | `{"enforced": false, "tier": ..., "preset": ..., "rules": {kind: rule}, "versions": {kind: n}, "floor": {kind: floor}, "needs": [...], "pending": [...]}` for the project's tier; `?tier=` for another |
| `PUT /projects/{p}/work/rules/{kind}` | body `{"tier", "rule", "reason"}`; 200 `{"version": n}` or 202 `{"pending": id, "reasons": [...]}` |
| `POST /projects/{p}/work/preset` | body `{"preset", "reason"}`; the rules that would loosen go pending, the others apply |
| `PUT /projects/{p}/work/tier` | body `{"tier", "reason"}` |
| `POST /projects/{p}/work/pending/{id}/confirm`, `.../reject` | body `{"reason"}` for reject |
| `GET /admin/work/floor`, `PUT /admin/work/floor/{kind}` | admin only; body `{"tier": tier or null, "floor": {...}, "reason"}` |

`needs` says what the rules ask for against what the project has: one entry per function a stage names, with the
count needed and the members who hold it, so a rule that cannot be met is seen when it is saved.

Refusals answer 409 with `{"detail": {"code": ..., "message": ...}}`, 403 for `owner_only` and `admin_only`, 422
for `InvalidRule` with its pointer.

## 9. Events

Made by a person through a platform route, recorded like the platform's other events (`core.outbox`, tied to the
witnessed request). The other person in an event is given by their actor reference, never by name; a reason is
content, never a detail.

| Event | Item | Details |
|---|---|---|
| `staffing.rule_changed` | `kind/tier` | `version`, `loosening` (reason codes), `acted_as` |
| `staffing.preset_applied` | preset name | `kinds_changed`, `kinds_pending` |
| `staffing.loosening_proposed` | pending id | `what`, `target`, `reasons` |
| `staffing.loosening_confirmed`, `staffing.loosening_rejected` | pending id | `what`, `target`, `proposed_by_ref` |
| `staffing.floor_changed` | kind | `tier`, `lower` (true when it is a loosening). The floor belongs to no project, so this one is in the platform's own log |
| `project.tier_changed` | the project's pid | `before`, `after` |
| `member.function_changed` | member subject | `added`, `removed`, `line` |

## 10. Events the platform derives from other events

The ledger accepts an event only when it is tied to a witnessed request, or to a run. A task will change state
because an app's event arrived (a checklist was closed), with no request of its own. That needs a third path.

**Rule.** An action may be registered with `origin="derived"` and `derived_from=(action names)`. The relay accepts
such an event when:

- its emitter is the platform and its `actor_kind` is `system`;
- it carries `caused_by_event` (in the outbox row's `extra`), the id of an event of the same log that the ledger
  **accepted** and whose action is in `derived_from`;
- no event of the same action and item was already derived from that cause.

It is then stored with `on_behalf_of_ref` taken from the cause, so the entry says for whom the system acted. An
event that fails any of the three is rejected like any other, with the reasons `no_cause`, `cause_not_accepted`,
`cause_not_allowed`, `already_derived`. A cause id that is in no log is `cause_not_accepted`. There is no time
window: a cause may be old.

`registry.check` refuses a derived event without `caused_by_event`, and refuses `caused_by_event` on an event of
any other origin (problems `caused_by_event_missing` and `caused_by_event_unexpected`).

## 11. Tests

| What | Where | Kind |
|---|---|---|
| `validate`: each field's limits, each invalid combination | `platform/tests/test_staffing_rule_shape.py` | pure |
| `is_loosening`: one test per reason code, and "tighten one, loosen another" | `platform/tests/test_staffing_loosening.py` | pure |
| `meets_floor`: one test per code; the stricter of two floor rows | `platform/tests/test_staffing_floor.py` | pure |
| `draw_sample`: same subject same answer; different key different draws; about one in n over many subjects | `platform/tests/test_staffing_sample.py` | pure |
| Presets cover every kind and tier and are valid rules | `platform/tests/test_staffing_presets.py` | pure |
| `grant_allowed`: one test per code | `platform/tests/test_member_function_rules.py` | pure |
| `controls.decide`: owner, admin, stranger; tightening at once; loosening waits; same person cannot confirm | `platform/tests/test_control_changes.py` | pure |
| The `work` tables exist in a new project's database; a rule row cannot be updated or deleted by the platform's role; a decided pending change cannot be changed | `platform/tests/test_work_schema.py` | database |
| Functions through the API: grant, own functions refused, mixed lines refused, a line 2 grant waits for a second owner | `platform/tests/test_api_member_functions.py` | API and database |
| Rules through the API: a new project has `light`; a tightening applies; a loosening answers 202 and applies after another owner confirms; the proposer cannot confirm; below the floor is refused; `enforced` is false | `platform/tests/test_api_staffing_rules.py` | API and database |
| Each event of section 9 is in the ledger with the person who made it | `platform/tests/ledger/test_ledger_staffing_events.py` | ledger |
| A derived event with an accepted cause is stored with the cause's person; each of the four rejections | `platform/tests/ledger/test_ledger_derived_events.py` | ledger |
| The rules page (`homepage/work-rules.html`) says "Shown, not enforced yet" | `scripts/tests/test_work_rules_page.py` | source text |
