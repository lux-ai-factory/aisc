# Several people on one project: the shared parts, and what a report may claim

A project is worked on by 2 to 5 people at once. Two things must then hold everywhere: nobody's saved work is
replaced without that person being told, and every record says which state of the AI card it was made on. This
spec covers the parts every later change stands on, and four corrections to reports. The per-page changes (the AI
card form, checklists, connections, settings, launches) each get their own spec and use what is defined here.

## Words

| Word | Meaning |
|---|---|
| **Card state** | The pair (card version pid, revision number). A correction changes the revision, a new version changes both. |
| **Opened-on token** | A value a page receives when it is drawn, naming the state of what it shows. The page sends it back with every save. |
| **Refusal** | The answer to a save that would replace something the person has not seen. Nothing in conflict is written, and the answer says what changed, who changed it and when. |
| **Stamp** | The card state a record stores about itself. |
| **Stamping writer** | Code that reads "the latest card" in order to store it on a record or to compare it with what a page sent. |
| **Session** | One signed-in person in one browser. Tests speak of session A and session B. |

## 1. One lock for the card state

The card state moves when the qualification app stores a card, in a transaction that takes no lock another app can
see. A writer that reads "the latest card" a moment earlier stamps a state that is no longer the latest.

**Rule.** The card state of a project is guarded by one advisory lock in the project's database, key
`hashtext('project.system')` (the key the platform's version counter already uses).

- The writer that stores a card (a save or a correction) takes it **exclusive**, as the first statement of the
  transaction that inserts the card.
- Every stamping writer takes it **shared**, in its own transaction, before it reads the latest card.
- Both are transaction locks: they end with the transaction and need no release.

**Helpers.** One per language, and nothing else may spell the key.

| Language | Where | Calls |
|---|---|---|
| Python | `shared/identity/aisc_identity/card_lock.py` | `card_lock.exclusive(conn)`, `card_lock.shared(conn)`, `card_lock.KEY_SQL` |
| TypeScript | `shared/access-ts/cardLock.ts`, vendored into qualification and controls like the rest of that package | `cardLockExclusive(tx)`, `cardLockShared(tx)` |

`conn` is a psycopg connection inside a transaction; `tx` is a Prisma transaction client. Both raise when called
outside a transaction, because a transaction lock taken in autocommit is released at once and guards nothing.

**Static test.** `scripts/tests/test_card_lock_use.py` reads the source of every file that queries
`project.saved_system`, `project.carded_system` or `project.system` and fails when a file on its list of stamping
writers does not call the helper, and when a file not on any list (stamping writer, the lock's owner, or a reader
that only displays) reads one of the three. A new reader therefore has to be classified.

## 2. Two views of "the versions of this project"

`project.saved_system` lists every version that was not withdrawn, including one whose card is not stored yet
(the platform numbers the version first, qualification stores the card after). The platform's create, revise and
withdraw need exactly that list. Everyone else wants "the versions a person can open".

**Rule.** A second view, `project.carded_system`, holds the rows of `project.saved_system` that have at least one
stored card. It has the same columns. `saved_system` keeps its meaning.

- Project template migration `0042_carded_system.sql`, applied to existing project databases like every other.
- Stamping writers and every list shown to people read `carded_system`. The platform's `create_version`,
  `revise_version` and `withdraw` keep reading `saved_system` under their lock.

## 3. The refusal

Each app keeps its own error envelope, because its pages already read it. Inside the envelope, a refusal carries
the same object everywhere. Its shape is one file, `shared/identity/refusal-cases.json`, read by the Python and
the TypeScript tests. The TypeScript side reads a vendored copy in each app's `test/fixtures/`, as it does for
`projectdb-cases.json`, and a test fails when a copy differs from the original.

```json
{"code": "changed_since_opened",
 "what": "connection",
 "message": "Maria Rossi changed the timeout and the model of this connection at 14:32. Your changes were not saved.",
 "changed": ["timeout", "model"],
 "saved": [],
 "not_saved": ["timeout"],
 "current": {"token": "8", "changed_by": "Maria Rossi", "changed_at": "2026-01-20T14:32:10Z",
             "values": {"timeout": 300}}}
```

| Field | Rule |
|---|---|
| `code` | One of the codes below. |
| `what` | The thing, in the word the page uses for it. |
| `message` | One or two sentences a person can act on. Names the fields as the screen labels them, the person and the time. Never a generic error. When the earlier save was the same person's, it says "you, in another tab or window". |
| `changed` | Labels of what the other save changed. May be empty when the app cannot tell. |
| `saved`, `not_saved` | For a form of independent items: which of this person's items were written and which were not. For a single thing: `saved` is empty. |
| `current.token` | The token to send with the next save. Always a string. |
| `current.changed_by`, `current.changed_at` | The display name and the time (UTC, seconds) of the save that caused the refusal. The display name is the token's `name` claim, or `preferred_username` when there is none; the platform's `Caller` gains it as `name`, and every write that can later cause a refusal stores it beside the subject. |
| `current.values` | The stored values of the items in `not_saved`, so the page can show both. Never a secret: a secret field is given as `{"secret": true}`. |

| Code | Meaning | HTTP |
|---|---|---|
| `changed_since_opened` | Someone saved this since the page was drawn | 409 |
| `upstream_moved` | Something the action depends on changed | 409 |
| `upstream_moved_confirm` | Only the card state moved; the person may confirm and go on | 409 |
| `already_exists` | The thing to create is there, with other content | 409 |
| `cited_by_report` | A stored report names this record | 409 |
| `syncing` | The card is being synchronised; try again in a moment | 409 |
| `not_final` | The action marks something complete and it is not | 409 |
| `token_required` | A save without a token, on a write that needs one | 400 |

| App | Where the object sits |
|---|---|
| platform, engine | `detail` |
| report composer | `error.details[0]`, with `error.code` and `error.message` copied from it |
| qualification, controls (server actions) | the action's state: `ok: false`, `refusal: {...}`, and the posted values returned |
| control-objectives | the page comes back with status 409 and the object rendered: the message on top, both values beside each field in conflict |

**Helpers.** `aisc_identity.refusal.Refusal` (a frozen dataclass with `as_dict()`, and `Refusal.from_dict()` for
tests; it raises `ValueError` on a shape the table does not allow) and `shared/access-ts/refusal.ts` (the type
and `isRefusal(value)`). The platform gets
`platform_service.refusals.raise_refusal(refusal)`, which raises the HTTP error with the object as `detail`.

**A missing token.** A write that needs a token and gets none answers `token_required` and writes nothing. For
one release after a page starts sending tokens, a browser save without one is answered through the page's
existing error path with "This page was opened before an update. Copy your text, reload, and save again."

**Every refusal is recorded**: one event `write.refused` in the project's ledger, with the code, what, the item,
the token sent, the current token, who changed it and when. Never the refused values.

## 4. Two sessions in a test

Races between people are not reachable by a test with one client. Every app gets the means to act as two.

**Platform** (`platform/tests/two_sessions.py`, fixture `two_editors`): a project with two members who are both
editors, and two callers `a` and `b`. Each caller has `get`, `post`, `put`, `patch`, `delete` that send that
person's token through the gateway path, and `name`. The two share nothing but the project. A second fixture,
`two_editors_who_administer`, gives the same two people the realm role `admin`, for the pages only an admin may
write (connections, installs).

**The other apps** get the same pair on their own harness: qualification and controls on their real-Postgres
test setup (two Prisma-backed callers), control-objectives and the report composer on their test clients.

**In order, not at once.** A lost update needs no true concurrency: A opens, B opens, B saves, A saves. Tests are
written as that sequence, which is deterministic. Only the card lock itself is tested with two real connections
and a held transaction.

**The first acceptance tests** are the reproductions of lost work, turned around: each asserts that the second
save is refused with `changed_since_opened` and that the first person's work is still stored. They fail today.
Each is closed by the spec of the page it belongs to and carries a strict expected-failure mark naming that page
until then, so the suite stays green and turns red the day one of them starts passing without its mark removed.

## 5. What a report may claim

Four corrections. They stand alone and come first, because they reach a client.

1. **A built-in layout can be generated.** A built-in layout has no revision. Its generate form sends none, and
   "no revision" is accepted for a built-in layout only: a stored layout without one is refused with
   `token_required`. Today the form sends `revision=0` and every generation of a built-in layout is refused with
   "revision must be a whole number from 1", while a stored layout without a revision is accepted. The second
   half changes behaviour that `tests/test_download_report.py` asserts: those requests gain a revision.
2. **An amendment is a submission that follows another one.** The report lists as amendments the submissions
   that have a previous version, whether or not a reason was given. Reason and requester print when present, and
   "no reason given" when not. Today an amendment without a reason is missing from the report. The controls app
   and the renderer share one contract file for what an amended submission looks like,
   `apps/controls/test/fixtures/amended-submission.json`.
3. **"The latest submission" is the latest closed one.** A draft prints only when the layout asks for drafts
   (the control answers block's option `drafts: true`, off by default), under the heading "Draft, not final", and
   is never counted in coverage. When a draft newer than the printed submission exists, the report says so in one
   line. This changes behaviour that `test_block_control_answers.py` and `test_block_summary_coverage.py` assert
   (a draft printed and counted): those expectations change with the rule.
4. **A report does not yet say what it was built from.** Until reports store the list of the records they read,
   every generated report prints one fixed line near its first page: "This report does not list the records it
   was built from."

## 6. Tests

| What | Where | Kind |
|---|---|---|
| The shared lock is taken by a stamping writer and waits for a card being stored | `platform/tests/test_card_lock.py` | two real connections |
| The helper refuses to run outside a transaction | the same | database |
| No file reads the card views without being classified | `scripts/tests/test_card_lock_use.py` | source text |
| `carded_system` leaves out a version with no card; `saved_system` still has it | `platform/tests/test_carded_system_view.py` | database |
| The refusal object, Python | `shared/identity/tests/test_refusal.py` reading `refusal-cases.json` | pure |
| The refusal object, TypeScript | `shared/access-ts/test/refusal.test.ts`, run from its vendored copy in each app's `test/vendor/` | pure |
| The platform answers a refusal as `detail` with status 409 | `platform/tests/test_refusal_answer.py` | API |
| Two editors are two people who can both write | `platform/tests/test_two_sessions.py` | API |
| A connection saved from a page opened earlier does not replace a colleague's change | `platform/tests/test_two_people_one_connection.py`, with `two_editors_who_administer` | API, expected failure until the connections spec |
| A built-in layout's own form produces a report | `apps/report-composer/tests/test_builtin_generate_without_revision.py` | API |
| A stored layout without a revision is still refused | the same | API |
| An amendment without a reason is listed | `apps/report-generator/tests/test_amendments_without_a_reason.py` | database |
| A newer draft is not printed as the submission | `apps/report-generator/tests/test_latest_submission_is_closed.py` | database |
| A draft prints under "Draft, not final" when the layout asks for drafts | the same | database |
| A refusal leaves a `write.refused` event without the refused values | `platform/tests/ledger/test_ledger_refusals.py` (to be written with the first page that refuses) | ledger |
| The fixed line is in every generated document | `apps/report-generator/tests/test_report_says_it_lists_no_records.py` | render |
