# Step 4 links belong to one AI card version (2026-10-02)

User decision: "just link it to the right card" (option A of three: per card version, not a change
history, not named snapshots). This reverses D3 of the evidence links plan (2026-09-30), which made
links per project.

## Rules
- A link is (card version, objective, test or control). Only the latest card version's links can
  change; an older version's step 4 is read-only, as its step 2 is.
- A version with no links of its own is offered the links of the nearest earlier version that has
  some, only for objectives in its own matrix and items still installed, pre-ticked and marked as
  carried ("taken from version n: save to keep them"). Nothing is written until the assessor saves.
- Deleting a card version deletes its links.
- Reports: the composer puts into a report's snapshot the links of the card version the report pins.

## Changes
- Platform template 0019: `evidence.link.system_id` (uuid, references project.system(pid) on delete
  cascade, not null), backfilled to the latest version; the primary key gains it.
- platform evidence.py: `view(pid, version=None)` (default latest; returns `version`, `versions`,
  `read_only`, `carried_from`), `replace(pid, wanted, who, version=None)` refuses an older version;
  the objectives are the selection of that version's assessment.
- platform app.py: `GET /projects/{slug}/evidence?version=<pid>`; `PUT .../evidence/links` takes an
  optional `version`; an older version is 409.
- composer evidence_links.coverage_links(conn, system_id) and its four callers.
- homepage evidence.html: the version shown, a version picker, read-only for older versions, the
  carried note.

TDD each: platform tests/test_evidence.py, composer tests/test_evidence_links.py and unit test,
scripts/tests/test_evidence_page.py.
