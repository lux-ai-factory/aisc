# Versions and revisions of an AI system

Status: draft for review. Nothing built.

## 1. Problem

Today every save of the AI card creates a new **version** of the system (`project.system`, number
1, 2, ...). Tests, checklist answers and the control-objectives assessment are stamped with the
version that was the latest when they happened, and a report is generated for one version.

So a correction to the *description* (a wrong provider name, an overclaimed checklist answer, a
risk worded inaccurately) produces Version 2. Every piece of evidence stays on Version 1, and a
report of Version 2 shows the corrected text with no evidence beside it. AISC cannot tell
"the system changed" from "we described the same system more accurately".

Trigger case: the Mijke team (10 Nov 2026) asked for four corrections to a report already sent
(provider name, description, Risk 5 wording, two FRAIA answers). The system did not change; the
official version must stay 1.

## 2. Terms

| Term | Means | Identity | Evidence |
|---|---|---|---|
| **Version** (1, 2, ...) | The system itself changed: model, back-end, prompt, data, organisation list, deployment | a new `project.system` row (new `pid`) | evidence made afterwards belongs to the new version |
| **Revision** (1.1, 1.2, ...) | The description of the same system was corrected | same `pid` | every test, answer and assessment of the version still counts |

Revision 1 of a version is the card saved when the version was created. Shown as "Version 1,
revision 2" (short: 1.2). A version with one revision shows as "Version 1" everywhere, as today.

The person saving decides which one it is. AISC never infers it from the fields that changed (a
new back-end name is a system change; a mistyped back-end name is a correction).

## 3. What can be revised

A revision covers the AI card as a whole, including its risks (`qualification.qualification_risk`
belongs to the card) and its components. Checklist submissions are amended separately (section 6),
because they live in another module and have their own version chain already.

Only the **latest version** can be revised. Correcting an older version is out of scope (the
platform already refuses changes to a non-latest `project.system` row).

## 4. Data model

### 4.1 Qualification (the card)

Today: one `qualification.qualification` row per version (`system_id` unique, index
`qualification_system_id_key`).

Change:

- Add `revision integer NOT NULL DEFAULT 1` and replace the unique index on `system_id` with a
  unique index on `(system_id, revision)`.
- Add `amends_id text NULL` (FK to the card it corrects), `amend_reason text NULL`,
  `amend_requested_by text NULL`. All three are set on every revision > 1 and NULL on revision 1
  (CHECK constraint).
- A revision is a **new row**, a full copy of the card with its risks, components, answers and
  knowledge-graph inputs, made by the same code path as a save today, except that it does not ask
  the platform for a new version. Earlier rows are never updated again (trigger, as
  `project.system` has today).
- Existing rows get `revision = 1` through the default: the migration needs no backfill and does
  not touch existing ids.

"The card of version V" now means "the row of V with the highest revision", unless a revision is
named. Readers that need "the card of version V" select the highest revision directly (qualification,
report renderer, consistency check C6); there is no separate view.

### 4.2 Platform (`project.system`)

`project.system` keeps one row per version. Its mirror columns (`name`, `version`, `provider`,
`description`) follow the latest revision: a new route
`PATCH /projects/{project}/system-versions/{pid}` updates them. The existing trigger already allows
changes to the latest version only, and never to `number`.

It also gains `card_revision integer NOT NULL DEFAULT 1`: the number of the card's latest revision,
set by the same route. The report composer already reads `project.system`, so this is how it learns
which revision to pin.

The route takes `expected_card_revision`, the revision the correction started from, and answers 409
when the version has moved on (a newer version, or another correction first). Qualification stores
the new card revision, its history and its ledger event first, then calls this route inside that
same transaction as its last step before commit (at most 10 s, inside a 20 s transaction), so a
refusal or failure rolls the card back. A commit that fails after the route answered would leave a
count with no card behind it; consistency check C3 reports that case. No new platform table. Engine stamps (`system_stamp.py`), checklist stamps and the dashboard keep
reading `pid` and are unaffected.

### 4.3 Controls (checklist submissions)

Submissions already have a version chain (`version`, `previousVersionId`), and new answers are
stamped with the latest system `pid`, which stays the same under a revision. Add to
`controls.submission`:

- `amend_reason text NULL`, `amend_requested_by text NULL`, set when a new submission version is
  made from a **closed** one as an amendment.

Closed submissions stay unchanged (as the ledger already recorded them). The existing "Amend"
action (`reopenForAmendment`) gains the two fields, which become required.

## 5. Saving the card

On `/p/<project>/system/edit`, the save button opens one question, with no option preselected:

- **The system changed** → new version (today's behaviour).
- **Correcting the description of Version N** → revision N.(r+1). Requires *Reason* (free text) and
  *Requested by* (free text, e.g. "Eindhoven Engine, email of 10 Nov 2026").

The second option is offered only when the card being edited is the latest version's latest
revision. The system page and the version history list show revisions under their version, each
with reason, requested by, author and date.

## 6. Ledger

- A card revision writes a ledger event `qualification.amended`, carrying the new card's content
  (as a save does today), `revision`, `amends` (the previous card id; the ledger finds its entry by item id),
  `reason` and `requested_by`. Written in the save's own transaction through the outbox, as card
  saves are now.
- A submission amendment keeps its existing event `controls.submission.reopened`, whose details
  gain `reason` and `requested_by`.
- The platform's `card_version.revised` event records the new `card_revision` on the version.
- An auditor can follow `amends` back to the entry that was corrected (for Mijke: entry 1299 for
  the FRAIA answers).

## 7. Report

- **Pinning.** A report is generated for a version, as today, and by default uses that version's
  latest revision and latest submission versions. The snapshot records the revision used
  (`card_revision` next to `system_id`), so the card text and the amendments of a report can be rendered again exactly as they were. A report that was sent is kept and downloaded as stored bytes; other evidence blocks (checklist answers, test runs) read current data when a snapshot is rendered again. A
snapshot without `card_revision` (made before this change) reads revision 1, which is exactly what
it showed. Readers take the highest card revision not above the pinned one.
  The composer pins the version's current revision; the renderer renders whatever revision a snapshot names, so a stored report keeps its own pin.
- **Readers.** `report_renderer/data/qualification.py` reads `qualification.qualification` by
  `system_id`; every query there gains "and the chosen revision" (the latest unless pinned).
  `newest_newer_card` compares versions only (unchanged meaning).
- **Cover.** "Version 1, revision 2" when the revision is above 1; unchanged otherwise.
- **Amendments block.** New block "Amendments", for the appendix, beside the existing
  "Changes since" block (which compares versions and stays as is). One row per card revision and
  submission amendment of the pinned version up to the pinned revision: date, what (card or which
  checklist), reason, requested by, ledger entry. Added to the built-in layouts' appendix; empty
  block is omitted.

## 8. Not affected

Engine data model, evaluations and their stamps, eval worker, plugins, Superset dashboards,
catalogue, Keycloak. The control-objectives assessment stays tied to one version (`pid`).

## 9. Deployment

- Built and tested in a separate checkout, never in `~/aisc` (the live stack aisc-063319 mounts
  `platform/project-template`, `platform/migrations`, `adapters`, `shared` and `local_plugins`
  from it).
- Tests run on throwaway databases (`PLATFORM_TEST_DATABASE_URL` and each module's own).
- Deploy only between test runs: rebuilding the platform restarts the Mijke adapter. Before
  rebuilding, compare each container's files with the code it will be built from.
- Rollback: project database dump before migrating, image tags `:pre-revisions`. The added
  columns and view are ignored by the old code.

Deploy order (each step checked before the next):
1. platform with project template `0032` applied to every project database (`project.system.card_revision` exists);
2. qualification and controls, each running its per-project migrations (`qualification.revision`,
   `controls.submission.amend_reason` exist in every project database);
3. report renderer and report composer last (they read the new columns).

Rebuilt containers: platform, qualification-web, controls-web, report-renderer,
report-composer.

## 10. Acceptance

1. Saving with "the system changed" behaves exactly as today (existing tests unchanged).
2. Saving a correction of Version 1 gives card revision 2 with the same `system_id`; revision 1 is
   still readable and cannot be changed; `project.system` row 1 shows the new provider/description.
3. An evaluation started after the correction is stamped with the same `pid` as before it.
4. A correction without a reason or a requested-by is refused.
5. A correction is refused for a version that is not the latest.
6. Amending a closed submission creates its next version with reason and requested-by; the closed
   one is unchanged.
7. The ledger holds `qualification.amended` and amended `controls.submission.reopened` entries pointing to what they correct.
8. A report of Version 1 shows revision 2 content, "Version 1, revision 2" on the cover and an
   Amendments block; rendering a snapshot pinned to revision 1 again reproduces the earlier card text (provider, description, risks) and amendments.
9. Mijke check: the corrections entered as card revision 2 (card + Risk 5) and an amended FRAIA
   submission; the regenerated PDF no longer contains "TU/e", "Municipality of Eindhoven
   (Gemeente Eindhoven, programme Inclusive Society)" as provider, "learning Dutch" among the
   main areas, or "do not fix the answer language".

## 11. Open decisions

- **Sign-off.** Assumed: reason + requested-by + ledger entry are enough; no approval step and no
  "pending" state. If the provider must confirm, a revision needs a pending state hidden from
  reports until confirmed.
- **Older versions.** Assumed: only the latest version can be revised.
- **Numbering shown.** Assumed "Version 1, revision 2". Alternative: "Version 1.2".
