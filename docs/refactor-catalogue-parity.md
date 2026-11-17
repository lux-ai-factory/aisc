# CAT-01 catalogue parity record (#122)

*Owner-reviewed record of the catalogue's pilot capabilities, what the unified app does with each, and
what is deliberately left out. Companion to [refactor-deviations.md](refactor-deviations.md); the
catalogue's shape is asserted by `apps/backend/aisc_backend/tests/test_catalogue_surface.py` and
`apps/webapp/src/lib/catalogue.surface.test.ts`.*

Reference for the pilot's behaviour: `homepage/catalogue.html` (the pilot launcher's catalogue page,
landed by DOC-01) plus the pilot's `apps/catalogue`.

**Reviewed by:** AISC project owner (CAT-01 / #122), 2026-11-17. **Outcome:** parity accepted as
stated below; the two exclusions are deliberate and carry their reason.

| Pilot capability (`homepage/catalogue.html`) | Unified app | State |
|---|---|---|
| One page where a project finds both kinds — tests (plugins) and checklists — and installs from it | `GET /catalogue` answers both kinds (`kind=all\|plugin\|control`), one install endpoint `POST /projects/{pid}/catalogue/installs`, one page `CataloguePage` with one reusable `CatalogueExploreDialog` | **ported** |
| "Filtered by this project's control objectives" | not filtered — see exclusion 2 | **excluded** (reason recorded) |
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

## Exclusion 2 — filtering the catalogue by the project's control objectives

The pilot filters the catalogue to what the selected objectives imply. **Appendix 2** says exactly how:
"Step 3 filters the catalogue, by default, to tests and checklists tagged with **the dimensions** of the
selected objectives" (`docs/appendices/2-control-objectives.md`, "What later steps take from it"), and a
dimension is the objectives' macro requirement — `REQ1 Human Agency and Oversight` … `REQ11`, which our
own catalogue rows carry in `ControlObjective.macro_requirement` (seeded from
`aisc_backend/data/ai_act_control_objectives.csv`). So the mapping on the objective side exists.

**Not ported, and this is the one catalogue parity gap.** The other side of that mapping is missing: the
surface's catalogue items carry `control_topic`, regulation ids, country ids and a provider
(`services/controls_catalogue._mapped`) — no dimension. The hosted catalogue's raw items do carry tags in
sections (`item["tags"]`, each `{section, slug}`; `_is_control` already reads the `type` section), so a
dimension tag may well be there, but the hosted API is not reachable from this sandbox
(`CONTROLS_CATALOG_URL` answers nothing), and a filter keyed on a guessed section name would be a guess
presented as a mapping — it would silently show the wrong list. The listing is therefore shown whole and
the objectives page stands on its own.

Closing it is small and mechanical once the section name is confirmed against the live catalogue: read the
dimension tag in `_mapped` (into `CatalogueControlOut.dimensions`), and filter the one listing by the
dimensions of the project's selected objectives, keeping "show everything" as the escape hatch — in the
same listing, not a second one. Until then the gap is recorded here rather than papered over.

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
