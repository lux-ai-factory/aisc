# Ledger: phase 9 report, the dashboard and the report composer (2026-10-03)

Phase 9 of `03-coding-plan.md` (steps 5 and 6), its independent review (`23-phase9-review.md`) and the
fixes. Every commit is on `feat/unified-modules`, local, **not pushed**:

| Repo | Commits |
|---|---|
| aisc (the composer lives here; platform, scripts, Caddyfile, compose) | 14ec076 (phase 9), the commit with this report (review fixes) |
| apps/report-generator (the renderer) | ec42a4e |
| apps/results-dashboard | c3fa7a9 (phase 9), 1c06a16 (review fixes). The repo was on a detached HEAD at `origin/feat/unified-modules`; the local branch was made there. Another session's uncommitted edits (`aisc_ext/projects.py`, two tests) are left as they were. |

**Nothing is deployed.** With `LEDGER_MODE` off (the default) no app writes an event and reports print
no anchor. Two things do change while it is off, both decided by you:
- a deleted layout is hidden and keeps its reports;
- a deleted comment is hidden rather than removed.

## What was built

| Part | What |
|---|---|
| composer events | <ul><li>layouts created, updated, deleted</li><li>a layout leaving a deleted template (`report.layout.template_removed`)</li><li>templates created, updated, deleted (a logo as its sha256)</li><li>reports generated or failed</li><li>downloads (now witnessed)</li></ul>Each event is in the write's own transaction, cites the witnessed request and names nobody. |
| layout revisions (M1) | `layout_revision`, append-only, TRUNCATE refused. Every save, and every template removal, keeps the revision it made; the layouts stored before are backfilled. |
| deleted layouts (M2) | <ul><li>soft delete (`deleted_at`); its name is free again</li><li>the reports' key is RESTRICT, so the database refuses a hard delete that would take them</li><li>the reports stay downloadable under "Reports of deleted layouts" on the layouts page</li></ul> |
| anchoring (M3) | <ul><li>at generation, the composer asks `GET /projects/{slug}/ledger/head` as the person</li><li>the report prints "Ledger entry N · <16 hex digits>" at the foot of every page</li><li>`report.generated` records the anchor and the document's sha256</li><li>`verify-ledger-export.py --anchor "<as printed>" --document report.pdf` proves offline that the report was generated after entry N and that entry M recorded this very document under that anchor</li></ul> |
| witness | <ul><li>the composer's project is found under `/report-composer/api/p/` too</li><li>the dashboard's bridge rule: the project from the dashboard's slug `aisc-<pid hex>`, in the path or, for a write, in `?dashboard=`</li></ul> |
| dashboard events (D1, D2) | <ul><li>comments created and deleted; review requests made and resolved</li><li>each queued in an outbox in Superset's own database, in the change's transaction, then posted to the internal route with the dashboard's token</li><li>only 409, 413 and 422 are final; any other answer keeps the event for the next pass</li><li>a write whose hint names another dashboard is refused</li></ul> |

## Tests (throwaway databases only)

| Suite | Result |
|---|---|
| composer, whole | 562 passed, 1 failed (`test_i8_2_i1_7`), 2 errors (`test_e2e`, FileNotFound), all three also at 983bcae (the commit before phase 9: 523 passed, 2 failed, 2 errors) |
| renderer, whole | 771 passed, 14 skipped |
| dashboard (without `test_sso_login`, which needs Superset itself) | 177 passed, 21 skipped (DB tests needing their bed, skipped before too) |
| platform `tests/ledger`, whole (on 14ec076) | 674 passed, 3 skipped (the opt-in drills) |
| platform ledger files touched by the fixes | 299 passed |
| `test_ledger_caddy`, gateway, equivalence (real Caddy) | 84 passed |
| `test_ledger_coverage.py` | C4 green for the composer and the dashboard. C1 lists `AiscReviewRequestView` (decision 2) and the engine's route (phase 8). |

**Mutations.** The reviewer's survivors are each caught now:
- in the composer, events moved out of their write's transaction, and the deleted-layout filter on copy names;
- the anchor's token header;
- the checker's ordering checks;
- the bridge's path-before-query order;
- the empty-log answer of the head route.

**Not run here.** The dashboard's code inside Superset (`comments/api.py`, `reviews/api.py`,
`superset_config.py`) can't run without Superset; only `aisc_ext/ledger.py` behind it is tested. It needs
a check on the real stack before `record`.

## Drill: a report verified offline

On the platform, through the real routes and relay (`test_ledger_step6_composer.py`):
- a report's printed anchor and its PDF, checked against an export, pass;
- a wrong digest, another document, an anchor newer than the one the document's entry names, and a document entry that names an older real entry all fail.

## Review (`23`, 1B/5M/10m) and what was done

- **B1 fixed.** The read paths were written with the prefix `handle_path` strips, so downloads were never witnessed. A static Caddy test now checks every read path against its handle.
- **M1 fixed.** Deleting a template now gives each of its layouts a recorded, kept revision.
- **M3, M4 fixed** in the dashboard.
- **M2 and M5** are decisions 1 and 2.
- **Minors.**
  - Fixed: m1, m2, m3, m5, m7, m8, m9.
  - m4 and m6: the checker takes the anchor as printed, and says what it proves ("generated after entry N").
  - m10: the startup schema changes tolerate a racing worker; moving them into the migrate service is left for later.

## Open decisions

1. **Dashboard events after a platform outage (review M2).** The platform stamps an event when it
   receives it, and the relay refuses an event more than 5 minutes after its witnessed request. A
   dashboard event that waits longer (the platform down, or decision 3 not yet taken) is rejected as
   stale, not merely late. The options:
   - (a) the relay gives queued events from service callers (the dashboard, later the engine) the run
     window (24 hours) instead of 5 minutes. **I recommend this:** the witnessed request still proves
     who, and only a token holder can send.
   - (b) the dashboard sends the time of the change, and the relay trusts it within the run window.
   - (c) keep 5 minutes, and accept the loss after a long outage.
2. **`AiscReviewRequestView` (review M5).** Superset's "Review Requests" screen is a full edit view.
   Anyone holding write on it can add, edit or delete review requests without the API, and so without
   the ledger; the viewer role holds that write today. The options:
   - make it read-only: nothing in the repo calls the API, so nobody could resolve a request from a screen until one exists;
   - record its writes from the view's own hooks: that also needs a project for the witness, which its URLs don't name;
   - keep it, and take it out of the viewer role.
3. **The dashboard can't reach the platform.** The dashboard runs host-networked and the platform's
   port isn't published, so the outbox would stay queued. One way is to publish the platform on the
   Docker host address (`DASHBOARD_PLATFORM_URL`, default `http://172.17.0.1:8000`); that exposes the
   platform to everything on that address.
4. **Still open from phases 4 to 7:**
   - the controls question review that deletes answers;
   - the install paths that carry the project in the form;
   - answers that look like tokens;
   - the C4 rule for the platform's own events;
   - `evidence.links.saved`;
   - deleting a project while the apps hold connections.

## To deploy, when you say so

After the earlier phases' steps:
1. Rebuild and recreate:
   - the report composer (migrations 0004 and 0005: `layout_revision`, the soft delete and the RESTRICT key; 0005 replaces the layout name constraint by a partial index);
   - the renderer;
   - the dashboard, with `PLATFORM_LEDGER_DASHBOARD_TOKEN` (already in `env.secrets`). Its first start adds `aisc_comment.deleted_at` and the outbox table.
2. Reload Caddy: the composer's downloads are then witnessed.
3. Decide 1 to 3 above before `LEDGER_MODE=record`.
