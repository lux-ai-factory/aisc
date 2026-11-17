# CAT-01 catalogue parity record (#122)

*Owner-reviewed record of the catalogue's pilot capabilities, what the unified app does with each, and
what is deliberately left out. Companion to [refactor-deviations.md](refactor-deviations.md); the
catalogue's shape is asserted by `apps/backend/aisc_backend/tests/test_catalogue_surface.py` and
`apps/webapp/src/lib/catalogue.surface.test.ts`.*

Reference for the pilot's behaviour: `homepage/catalogue.html` (the pilot launcher's catalogue page,
landed by DOC-01) plus the pilot's `apps/catalogue`.

**Reviewed by:** AISC project owner (CAT-01 / #122), 2026-11-17. **Outcome:** parity accepted as
stated below. Exclusion 1 (the public/private catalogue choice) is deliberate and carries its reason;
exclusion 2 (the step-3 filter by the project's objectives' dimensions) was the one real parity gap and
**is now ported** — the heading is kept so the record of the gap and of how it closed survives.

| Pilot capability (`homepage/catalogue.html`) | Unified app | State |
|---|---|---|
| One page where a project finds both kinds — tests (plugins) and checklists — and installs from it | `GET /catalogue` answers both kinds (`kind=all\|plugin\|control`), one install endpoint `POST /projects/{pid}/catalogue/installs`, one page `CataloguePage` with one reusable `CatalogueExploreDialog` | **ported** |
| "Filtered by this project's control objectives" | `GET /catalogue` carries each item's dimension tags and the dimension vocabulary; `GET /projects/{pid}/control-objectives/dimensions` says which dimensions the project's selected objectives are; the listing page's "For this project" switch (on by default) keeps the items carrying one of them, with a note and "show everything" when the project has selected nothing — see [exclusion 2](#exclusion-2--the-filters-are-in-the-one-listing) | **ported** |
| "Public catalogue: read live, always current, nothing stored for this project" | `GET /catalogue` reads through to the hosted catalogue on each listing (`services/controls_catalogue`, briefly cached), nothing is stored until an item is installed | **ported** |
| "Also lists the tests kept on this installation" | the plugin side of the same listing comes from the installation's loader (`source == "local"`, expanded per base-plugin class), alongside registry packages | **ported** |
| Install into the project (idempotent, repeatable) | `POST /projects/{pid}/catalogue/installs` copies a checklist template into the project's own library (`ProjectChecklist`), installs the requested plugin class(es) (`Plugin`), and re-enables rather than duplicating on reinstall | **ported** |
| An install that the reference's own UI consumed | `GET /projects/{pid}/catalogue/control/{slug}/export` keeps the reference `{meta, questions}` package shape, so outside tooling still works | **ported** |
| The published catalogue site itself (independently published artifact) | linked, never fetched or stored (`app_catalog_url`, I9) | **ported (as a link)** |
| Sign out, "back to the project", the "…" menus | the app's own shell (Keycloak/`AuthContext`, project nav) | **not applicable** |
| "Which catalogue does this project use?" — a once-and-final choice per project between the public catalogue and a private copy, with an admin "Update from public" refresh | not ported — see exclusion 1 | **excluded** (reason recorded) |

## Exclusion 1 — the public/private catalogue choice (and its per-project copy)

The pilot's page asks each project to choose, once and irreversibly, between the public catalogue (read
live, nothing stored) and a private catalogue (a copy of the public one kept for that project,
refreshed by an admin pressing *Update from public*).

**Not ported, deliberately.** The unified app already gives a project its own copy where it matters:
installing a catalogue item materially copies it into the project's own tables (`ProjectChecklist`,
`Plugin`), and the project's copy is then the project's to edit — which is what a private catalogue was
for. Adding a second, whole-catalogue copy per project would be exactly the second catalogue path CAT-01
exists to prevent: two places a project's catalogue lives, two refresh stories, two things to reconcile.
The unified app's answer to "which catalogue does this project use?" is therefore *the one catalogue*,
live, plus anything the project installed for itself.

What that costs, stated plainly: a project cannot pin the catalogue as it stood on a date, and there is
no admin "refresh my project's copy" action (an install is already idempotent, so re-installing picks up
an updated template). If a deployment needs version-pinned catalogue snapshots, that is a new
requirement, not a port — it would go through the versioning mechanism (I6), not through a private
catalogue table.

## Exclusion 2 — the filters are in the one listing

**This gap is closed; the heading is kept so the record of it is not lost.** The pilot filters the
catalogue to what the selected objectives imply, and Appendix 2 says how: "Step 3 filters the catalogue, by
default, to tests and checklists tagged with **the dimensions** of the selected objectives"
(`docs/appendices/2-control-objectives.md`). A dimension is the catalogue's own vocabulary, and our
objectives carry it in `ControlObjective.macro_requirement`.

**Both sides of that mapping now exist, in one place each.**

* **The vocabulary.** `services/dimensions.py` is the single table: `REQ1..REQ11` → the catalogue's eleven
  dimension slugs, with the catalogue's own labels (`diversity-non-discrimination-fairness`, not our
  "Fairness"). `services/evidence_map` reads `dimension_of` from it, the catalogue surface serves
  `vocabulary()` as `CatalogueOut.dimensions`, and the objective side serves `dimensions_of` per project.
  Nothing else may invent a dimension; `tests/test_dimensions.py` pins every slug and checks that every
  seeded requirement has one.
* **The tag.** The section name that was the blocker is confirmed against the live catalogue, not guessed:
  items carry `{"section": "dimension", "slug": …}` and their sub-dimensions under
  `controls_subdim`/`testing_subdim` with the dimension in `parent_dimension_slug`.
  `services/controls_catalogue._dimension_slugs` reads all three sections and folds a sub-dimension into its
  parent — the catalogue's own site rule, so an item tagged only `purpose-limitation` is still a
  `privacy-data-governance` item — into `CatalogueControlOut.dimensions`. Measured on the live catalogue
  (2026-11-17, 68 items / 44 checklists): **every checklist carries a dimension tag**, across nine of the
  eleven slugs.
* **The read.** `GET /projects/{pid}/control-objectives/dimensions` answers the selected objectives'
  dimensions (the profile's `objectives`; a project that only ever flagged key objectives is read from
  those), `[]` meaning "nothing selected yet".
* **The filter.** One listing, not a second one: `CatalogueExploreDialog` gained a "For this project"
  switch (on by default, as the pilot's sidebar has it), a note — "No control objectives selected yet:
  showing everything." — when the project has selected nothing, and the dimension chips that the pilot's
  sidebar offers (built from the served vocabulary). Both narrow the same `filterCatalogue` call, matching
  *any* of their slugs, which is the catalogue site's own rule.

**What is still different, and why.** Only checklists are narrowed. The pilot's "tests" tab is filtered by
the same dimensions because its tests come from the hosted catalogue (`type: test` items, which do carry
dimension tags); our plugin side of the listing comes from this installation's plugin loader
(`source == "local"` plus registry packages), which carries no dimension tag at all, so a project filter
would hide every plugin rather than narrow them. `filterCatalogue` therefore leaves plugins alone — the
switch is not offered on the plugin-only dialog — and the plugin side of the listing is unchanged. Closing
*that* needs the hosted catalogue's test dimension tags to reach the loader path, which is the same
question the plugin listing already has (which catalogue is authoritative for a plugin package), not a
dimension-table question.

## No duplicate surface (the second CAT-01 criterion)

Asserted, not asserted-by-eye:

* **Backend** (`tests/test_catalogue_surface.py`): every catalogue route is declared in
  `routers/catalogue.py` and no other router module declares one (`control-objectives/catalogue` is the
  *objectives* catalogue and is named as the one exception); installs are declared in that one module;
  the paths the server actually registers match that module; the only model carrying a catalogue id is
  the read-through `ControlTemplate`; and no model holds a per-project catalogue copy.
* **Webapp** (`src/lib/catalogue.surface.test.ts`): one module reads the listing (`lib/checklists.ts`),
  one module installs (`lib/checklists.ts` + the dialog), one route renders a catalogue, one component
  implements the exploration UI, and the pages that open it are the known three (`CataloguePage`,
  `ChecklistsPage`, `Plugins`) — a fourth, or a second listing call, fails the test.

The dimension filter did not add a surface: the *vocabulary and tag* live in the services above, the
project's dimensions are one more read of the project's own objectives
(`routers/control_objectives.py`, alongside the objectives catalogue it belongs to — not a route under
`/catalogue`, so it is not a listing), and the narrowing happens inside the same `filterCatalogue` call the
dialog already used. Asserted from both sides:
`apps/backend/aisc_backend/tests/test_dimensions.py` (the table), `.../tests/routers/test_control_objectives_router.py`
(what a project's dimensions are), `.../tests/routers/test_controls_catalogue_sync.py` (the items' tags and
the served vocabulary), `apps/webapp/src/lib/catalogue.test.ts` (the narrowing), and
`apps/webapp/src/components/CatalogueExploreDialog.test.tsx` + `src/pages/CataloguePage.test.tsx` (the
switch, the note, and the page wiring end to end).
