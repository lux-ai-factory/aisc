# Phase 9 review (steps 5 dashboard, 6 report composer), 2026-10-03

Reviewed: aisc 14ec076 (composer, registry, witness, head route, checker, Caddyfile, compose, tests),
apps/report-generator ec42a4e (the anchor in the footer), apps/results-dashboard c3fa7a9 (outbox,
comments, reviews). Against 02-spec.md 3.4, 4.1-4.5, 6.4, 6.5, 7; 03-coding-plan.md row 9 (D1-D2,
M1-M3, the drill); 04-test-plan.md; the kinds of problems found in reviews 19-21.

Counts: **1 blocker, 5 majors, 10 minors.**

## Blocker

### B1. Downloads are never witnessed: the protect-reads paths can't match inside `handle_path`

`Caddyfile:180`: `import protect-reads report_composer /report-composer/api/p/*/reports/*/pdf ...`
sits inside `handle_path /report-composer*`. `handle_path` strips the prefix before the `route` runs,
so the `path` matcher of `witness-reads-on` sees `/api/p/<slug>/reports/<id>/pdf`, never
`/report-composer/...`. The writes are unaffected (they match on method and pass `orig_uri`).

Proved in a throwaway `caddy:2.10.2` container (own port, no compose, removed after) with the same
nesting: `GET /report-composer/api/p/demo/reports/abc/pdf` answered
`stripped-only /api/p/demo/reports/abc/pdf orig=/report-composer/...`; the prefixed matcher did not
fire for `/pdf` nor `/download`.

Failure: with `LEDGER_GATEWAY=on` and `LEDGER_MODE=record|enforce`, every PDF or DOCX download reaches
the composer with no `X-AISC-Request-Id` (the strip removed any client one), `report.downloaded` is
emitted with `request_id: null`, and the relay turns each into `ledger.rejected` (`missing_request`).
No download of a report is ever accepted, the step-6 "read that matters" is uncovered (I7), and no
test notices: the platform test fabricates the witness record directly (`witnessed(...)`), and the
composer test sends the header itself.

Fix: write the matcher paths as the stripped app sees them (`/api/p/*/reports/*/pdf`,
`/api/p/*/reports/*/download`), or change this block to `handle /report-composer*` plus an explicit
`uri strip_prefix` after the route. Add a Caddyfile test (the repo already parses it for the
coverage test) that every protect-reads path inside a `handle_path` block does not start with that
block's prefix, or better, a container check like the one above in the gateway tests.

## Majors

### M1. Deleting a template silently changes its layouts: item-chain break and a false "kept revision"

`migrations/project/0001_project_database.sql:45`: `layout.template_id ... ON DELETE SET NULL`.
`api.py:522` `delete_template` deletes the row; Postgres nulls `template_id` on every layout using it,
with no `report.layout.updated`, no revision bump and no `layout_revision` row.

Reproduced on the bed (a temporary test file, removed): template T, layout L (revision 1, template T),
delete T. Then `layout_revision(L, 1).state.template_id = T` while L at revision 1 now has `null`; the
next PUT of L emits `before.template_id = null` against the previous `after.template_id = T`:

```
REV 1 now template None kept template 36938580-...
CHAIN created.after.template_id 36938580-... updated.before.template_id None
```

So every layout that used a deleted template raises a broken-chain alarm (I11) on its next save, and
M1's claim "every revision of a layout is kept" is false for it: revision 1 as kept is not revision 1
as it stands. Deleted (hidden) layouts are hit too.

Fix (pick one): refuse the delete while a live layout uses the template (409 `template_in_use`,
the simplest and consistent with "the user decides"); or in the same transaction, for each live
layout using it, null the key explicitly, bump `revision`, `keep_revision` and emit
`report.layout.updated` (`details.revision`, `before`/`after`). Test: the scenario above, asserting
no chain break and a matching `layout_revision`.

### M2. Dashboard events delivered late are rejected as stale; they are only retried on the next write

`core.outbox.occurred_at` is set by the platform when the internal route inserts the row
(`app.py` `_queue_internal` -> `outbox.emit`, database default), and the relay requires
`occurred_at - witness.at <= WINDOW` (5 min, `relay.py` `_judge_request`). The dashboard queues in
its own outbox and posts later (`aisc_ext/ledger.py:134` `deliver`), and `deliver` is only called at
the end of another comment or review write (`comments/api.py:26` `_send_queued`): there is no
background pass.

Failure: the default compose (`PLATFORM_URL: ${DASHBOARD_PLATFORM_URL:-http://172.17.0.1:8000}`, the
platform port not published, declared item 1) queues every event. On the day the address is fixed,
the backlog leaves at the next write, minutes to weeks later, and every event becomes
`ledger.rejected` (`stale_request`). Same for any platform outage longer than 5 minutes followed by a
quiet dashboard. So the outbox's promise ("a silent platform leaves them queued", I6: no event is
lost) holds only for the first 5 minutes; after that the queue preserves events only to have them
rejected. The declared item 1 is therefore not just a deploy decision: it turns into permanent
rejections, not a delay.

Fix: the platform can't trust a dashboard-supplied time (T7), so (a) keep the outbox small and
deliver synchronously, and in `enforce` fail the write when the event can't be queued at the
platform (the witness already needs the platform up for the write to pass at all); or (b) have the
internal route accept a `queued_at` and judge the window on it only for the dashboard caller, with a
bound (`queued_at >= witness.at - skew` and `recorded - queued_at <= DASHBOARD_BACKLOG`), recorded
as such. Either way add a periodic delivery (a Superset Celery beat task or a thread) so a backlog
does not wait for the next human write, and fix the deploy address (publish the platform on the host
loopback for the host-networked dashboard) before LEDGER_MODE is turned on.

### M3. A recoverable misconfiguration permanently refuses dashboard events

`aisc_ext/ledger.py:151-156`: every non-2xx status below 500 is a final refusal, kept and never resent.
But the platform answers 401 for a wrong or rotated `PLATFORM_LEDGER_DASHBOARD_TOKEN`
(`_ledger_caller`), 404 when the request carries `X-Forwarded-For`/`X-Forwarded-Host` (a proxy in
between), and a `DASHBOARD_PLATFORM_URL` pointed at the gateway gets 302/401/404 from Caddy or
oauth2-proxy. It also answers 422 for an event whose `request_id` is null (`_malformed` requires a
UUID), which happens for any write that did not come through the witness (the gateway off while
`LEDGER_MODE` is on, a script calling the API directly).

Failure: one wrong token in `.env` and every comment and review event from then on is marked
`refused=401` and never sent, with only a log line. The existing test
(`test_an_event_the_platform_refuses_is_not_sent_again`, 422) blesses the behaviour for every 4xx.

Fix: treat 401, 403, 404, 405, 408, 429 and any 3xx as "not delivered, try again" (like 5xx: stop the
pass); keep only 409 and 422 (and 413) as final, and only when the body is the platform's JSON
(`detail`). Do not queue an event with no `request_id` at all while the gateway is expected (refuse
the write in `enforce`, or skip queuing in `record` with a log line), since the platform will reject
it anyway.

### M4. The bridge reads the project from a client-chosen query, and nothing checks it names the written dashboard

`witness.py:51-63` `_bridge` takes the first `aisc-<hex>` found in the path or in **any** query value
(`?anything=aisc-<hex>`, `?next=/x/aisc-<hex>`). Spec 3.4 and plan row D1-D2 say "the dashboard
bridge table (dashboard id to project)". The comment and review APIs never compare the query with the
dashboard they actually write to (`comments/api.py` post/delete, `reviews/api.py:74,101`).

Failures:
- Review requests: nothing in the repo calls `/api/v1/aisc_review_request` with `?dashboard=` (the
  Review page's `call()` only targets the comment API; reviews are made by API clients such as
  `scripts/verify_review.py`, or the FAB view of M5). Every `dashboard.review.requested` and
  `dashboard.review.resolved` event therefore cites a request filed in no project and is rejected
  (`project_mismatch`). The platform test passes only because it writes the query into the URI itself.
- A member of projects A and B posts a comment on B's dashboard with `?dashboard=aisc-<A>`: the
  request is recorded in A's log (a `request.witnessed` in A about B's dashboard), and the comment's
  event in B is rejected (`project_mismatch`). A comment then exists in B with no accepted event,
  chosen by the client. The relay's check keeps I9 (nothing of B is accepted in A), but the ledger's
  claim "for every event a person caused, the ledger names a person" is defeated at will, and A's
  log holds a record about another project.

Fix: in both APIs, while the ledger is on, refuse (400) a write whose `request.args["dashboard"]`
is missing or differs from the target dashboard's slug; restrict `_bridge` to the key `dashboard`
in the query (and the dashboard path forms), not any value; give the review requests a client that
sends the slug, or derive the project server-side as the plan says (the platform resolving the
dashboard id through the bridge it already provisions). Test the refusal and the review route
without the query.

### M5. D1-D2's "no viewer edit view" is not met: `AiscReviewRequestView` writes review requests with no event

`aisc_ext/reviews/views.py` is a full FAB `ModelView` (add, edit `status` and `message`, delete), and
the coverage test lists it (`dashboard apps/results-dashboard/aisc_ext/reviews/views.py
AiscReviewRequestView` among the uncovered routes). Whether viewers hold `can_add`/`can_edit` on it
depends on its view-menu name against `security.py:53` `VIEWER_WRITABLE_VIEWS = ("AiscComment",
"AiscReview")` and `NEVER_FOR_A_VIEWER` (which refuses `can_add`/`can_edit`/`can_delete` outside the
`can_write` exception); I could not run Superset to settle the author's declared item 2. Either way,
editors and admins can create, resolve, edit and delete review requests there with no ledger event,
and a hard delete removes the row the `dashboard.review.*` chain describes. The plan's done-when for
row 9 includes this item, so phase 9 is not done while it stays.

Fix: make it read-only like `AiscCommentView` (`base_permissions = ["can_list", "can_show"]`), so
review requests change only through the API; add a test like the comment view's.

## Minors

- **m1. Events outside the write's transaction are not caught by any test.** Mutations that moved
  `report.generated` into a separate `projects.connect` after `finish_report`
  (`reports.py:210-216`) and `report.layout.deleted` into a second `_project_db` after the soft
  delete (`api.py:215`) both survived the composer ledger, soft-delete and layouts suites (40 passed).
  Only `report.layout.created` has the "failure after the event leaves neither" test. Add that test
  for update, delete, the template writes and the finished report (make `ledger.emit` raise after
  the real call and assert the row is unchanged).
- **m2. Template before-states are read without a lock.** `api.py:464` and `api.py:524` read the
  template with a plain SELECT, then update or delete it; two concurrent PUTs both send the same
  `before` and the second breaks the chain (false I11 alarm). The layout routes use `for_update=True`;
  add `FOR UPDATE` to `get_template` for these two callers. The same applies to
  `reviews/api.py:112` (`status_before` from an unlocked `query.get`; use `with_for_update()`).
- **m3. The anchor fetch is never exercised for real.** Every composer test monkeypatches
  `anchor.fetch`; a mutation reading the wrong header for the token (`anchor.py:35` `_token`)
  survived. Add a test with a stub platform (httpx MockTransport or a local server) for 200, 404
  (no ledger yet), 403, timeout and a malformed body, and that the person's token is the one sent.
- **m4. The printed anchor is not what the checker takes.** The renderer prints
  `Ledger entry 42 · 0123456789abcdef` (`document.py:182`); `verify-ledger-export.py --anchor` takes
  only `42:0123...` (`anchor_problems`, line 285), and the commit message says "takes as printed".
  Accept the printed form too (parse `Ledger entry (\d+) · ([0-9a-f]{16,})`), or print `42:0123...`.
- **m5. The checker's ordering checks are untested.** Mutations turning `head < entry["seq"]` into
  `<=` and dropping the `head != anchor_seq` comparison (`document_problems`) both survived the drill:
  its `later` case (`test_ledger_step6_composer.py:160`) fails on the anchor digest, never on the
  document's entry naming another head. Add a case with a real, older entry as the printed anchor.
- **m6. What the anchor proves is overstated.** The anchor shows only that the report was recorded
  after entry N (any older real entry also passes, and the composer chooses it); the checker's
  "the report was not made under this log's entry" message and the docs imply it was the head at the
  time. Say "generated after entry N, recorded by entry M" and print M's seq as the proof. 16 hex
  digits (64 bits) are enough: a second preimage at that length is out of reach, and the export's
  chain and signature are checked first.
- **m7. `layout_names` filter untested.** Dropping `WHERE deleted_at IS NULL` from `db.layout_names`
  survived; a duplicate or import then gets "Copy of X (2)" because of a hidden layout. Add a test:
  delete "X", duplicate a layout named "X"... and expect the plain copy name.
- **m8. Deleted comments still count, and can be replied to.** `review/views.py:47` counts every
  comment, deleted or not, on the Review list; `comments/api.py:80` accepts a `parent_id` of a
  deleted comment, which then hangs under a hidden parent. Filter `deleted_at IS NULL` in both.
- **m9. Concurrent `deliver` passes.** `_send_queued` runs in each request thread (gthread), with no
  claim on rows: two threads send the same rows (harmless, the platform answers a replay 202) and
  can interleave two events of one comment (created and deleted in quick succession) out of order,
  so the relay sees `before` before its `after` (false I11 alarm). Claim rows with
  `SELECT ... FOR UPDATE SKIP LOCKED` in one transaction per pass, or a process-wide lock.
- **m10. Startup DDL races and assumes Postgres.** `superset_config.py:245` runs
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` and `create_all` in every worker at start; concurrent
  workers can fail with a duplicate pg_attribute or pg_type error, and SQLite (used in some local
  runs) has no `IF NOT EXISTS` for columns. Move them to the `dashboard-migrate` one-shot service.

## Judged: the author's declared items

1. Platform port not published, outbox stays queued: not only a deploy decision, see M2 (late
   delivery is rejected as stale) and M3 (a wrong address can make it a permanent refusal).
2. `AiscReviewRequestView` writable: agreed it is open, and it is a done-when item of row 9 (M5).
   Whether viewers in particular can write through it could not be confirmed without Superset.
3. `dashboard.viewed` not sent: acceptable, it is best effort (spec 3.5, D6) and declared in the
   registry comment.
4. The Superset runtime code is not run: accepted as a limit, but it is where M3, M4, m2, m8 and m9
   live; the platform tests stand in for it by writing the URIs the code is supposed to produce.
5. Composer pre-existing failures: confirmed for `test_i8_2_i1_7` (it fails identically on an
   archive of 983bcae, `git archive` into the scratchpad); `test_e2e` was not rerun.
6. Anchor best effort with the person's token: sound (the platform checks membership through
   `_ledger_project`, a stranger gets 404, so it can't fetch another project's head; the slug is the
   guarded project's), but untested for real (m3).

## What I verified, and how

- Read the three commits whole, the registry entries against the real URLs (composer API under
  `/report-composer/api/p/<slug>/`, pages under `/report-composer/p/<slug>/`, `generate`, item groups,
  details keys, `content_required`, `per_request`), the relay's request checks and the internal
  route.
- Every composer write emits on the connection of its own `with` block: post, put (before read
  `FOR UPDATE` inside), delete (soft, layout locked), duplicate, template create, import, update,
  delete, report finish and failure. The download event is in its own short transaction, which is
  right for a read. No event names a person: layout and template states leave out `created_by` and
  `updated_by`; dashboard events leave out `author_sub`, `author_name` and the assignee's sub
  (`user`); failures carry only the error code (the renderer's URL with a secret stays out, tested).
- Soft delete: every layout read goes through `get_layout` or `list_layouts`, both filtered; get,
  put, duplicate, generate, list reports and delete of a deleted layout answer 404 (tested); its
  reports stay downloadable (`get_report` does not join the layout); the name index is partial; the
  reports' key is RESTRICT. Nothing else in the repo (platform evidence, renderer, report_ro) reads
  `report_composer.layout`.
- The 0004 backfill builds the same shape as `layout_state` (description and options are NOT NULL,
  template id as text), so a backfilled revision matches the next event's `before`.
- `report.generated` always comes after its anchor in the same log (the anchor is a committed head,
  the event is relayed later), and the checker rejects a digest of another project's entry at the
  same seq.
- The witness bridge: a stranger gets no project (tested), `aisc-0...0` resolves to no project, the
  pid must exist.
- Tests run: composer `test_ledger.py`, `test_layout_soft_delete.py`, `test_api_layouts.py`,
  `test_isolation_project_databases.py` (63 passed, 1 pre-existing failure); renderer
  `test_ledger_anchor.py` (6 passed); dashboard suite (163 passed, 21 skipped); platform ledger
  `test_ledger_step6_composer.py`, `test_ledger_step5_dashboard.py`, `test_ledger_relay.py`,
  `test_ledger_relay_review.py` on a throwaway Postgres 14 + immudb (78 passed; env torn down, no
  container left); `test_ledger_credentials.py` passes; `test_ledger_coverage.py` fails on routes of
  later phases and on `AiscReviewRequestView` (M5), none of the composer's.
- Mutations (each restored by copying the original back; `git diff` afterwards shows only the files
  another session had already changed):
  - composer, all survived (40 passed): `report.generated` in a separate transaction; the
    `report.layout.deleted` emit in a separate transaction; `layout_names` without the deleted filter;
    the anchor's token read from a wrong header.
  - platform and checker, all survived (28 passed): `head < seq` to `<=`; the `head != anchor_seq`
    check removed; the bridge searching the query before the path (last match wins); the head
    route's 404 for an empty log removed.
- Reproductions: the Caddy matcher inside `handle_path` (B1, throwaway container `caddy:2.10.2`
  on 127.0.0.1:18999, removed) and the template delete chain break (M1, a temporary test file in
  `apps/report-composer/tests/`, removed).
