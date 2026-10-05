# Control checklists installed from the catalogue (2026-10-04)

## Goal

A project installs a control checklist from the catalogue it chose, public or private, with the
catalogue's own Install button, the same way it installs a test. Once that works on a fresh stack,
the controls app's own way of adding checklists ("Add from catalogue", its in-app catalogue page) is
removed.

## Where it stands

- A checklist is data (title, source, questions), not code: no package index is involved. The
  catalogue serves a control as a package (`GET /control/{slug}/export`, `meta` + `questions`,
  apps/catalogue/backend/controls_export.py); the controls app stores it in the project's database.
- The controls app fetches that package from the online catalogue only (`CATALOGUE_URL`), whatever
  catalogue the project chose. A private project's checklists therefore come from the online site,
  not from its copy.
- The catalogue pages have the Install button for controls (`crossSite/ControlInstall.tsx`, on
  feat/unified-modules). The online site at sandboxconfigurator.aifactory.lu runs an older build
  without it (checked 2026-10-04: its bundle has the test handover, no control install), so a
  public project has no Install button for controls.
- The install API of the controls app (`/controls/api/install`) answers only the online catalogue's
  origin (`CATALOGUE_ORIGIN`). The stack's catalogue pages are on the launcher's origin
  (`http://localhost:8100`), so it refuses them.
- The controls app has its own way in: the library's "Add from catalogue" button opens
  `/controls/p/{pid}/catalogue`, a list of the online catalogue's controls with Install buttons.

## Decisions

- D1 (user, 2026-10-04): public projects also use the catalogue pages served by the stack, reading
  the online catalogue live through the platform. The online site is not redeployed.
- D2: the platform decides where a project's catalogue comes from, in one place (Python):
  private reads the project's copy, public reads the online catalogue live. Everything else
  (catalogue pages, controls app) asks the platform and never names a catalogue URL.
- D3: a private copy builds a control's package from the copy itself (the questions and metadata it
  already holds), with the catalogue's own rules ported to the platform. A test holds the port to
  the online catalogue's exports for every control (fixture taken 2026-10-04). A public project
  gets the online export as it is.
- D4: the catalogue pages move from `/private-catalogue/` to `/project-catalogue/`, since they
  now serve both modes; the old address redirects.
- D5: in public mode the pages show the online catalogue's entries only (no Local entries, no
  Update button: they are live). Tests are blue when the stack's package index has them, as in
  private mode, since the engine installs from that index in both modes.

## Work

### P1 platform: a project's catalogue, either mode

- `catalogue.py`:
  - the reads (`tools`, `tool_tags`, `tags`, `metrics`, `metadata`, `install_info`) take their
    entries from the copy (private) or the online catalogue (public, fetched live with a short
    cache);
  - local entries and updates stay private only;
  - `control_package(pid, slug)`: private builds it from the copy (`checklist_package(entry)`),
    public fetches the online export (with `CATALOGUE_BRIDGE_TOKEN` when set);
  - errors: a project that has not chosen gets 409, an entry that is not a control gets 404.
- `app.py`: `GET /projects/{project}/catalogue/control/{slug}/export` (viewer, slug or pid), and
  the reads no longer refuse a public project.
- compose: the platform gets `CATALOGUE_TOKEN` (the bridge token).

### P2 controls app: packages from the platform

- `cataloguePackage.ts` fetches `{PLATFORM_URL}/projects/{pid}/catalogue/control/{slug}/export`
  with the caller's token:
  - the dialog's preview uses the preselected project;
  - the install uses the chosen project.
- The install API also answers the launcher's origin (from `LAUNCHER_URL`), besides
  `CATALOGUE_ORIGIN`.
- compose: controls-web loses `CATALOGUE_URL` and `CATALOGUE_TOKEN`, and gains `LAUNCHER_URL`.

### P3 catalogue pages: both modes

- `Catalogue.tsx` loads for a public or a private project:
  - private: "Private catalogue · updated on ..." with Update;
  - public: "Public catalogue · live".
- `CATALOGUE_BASE` becomes `/project-catalogue/`; Caddy serves it there and redirects
  `/private-catalogue/*` to it.
- `project.html` opens `/project-catalogue/catalogue?project=...#env=...` for both modes, with the
  controls app's address in the handover as today; the online site is no longer opened from a
  project.

### P4 proof on a fresh stack

- A fresh clone, README setup.
- Two projects, one private and one public. In each, open the catalogue, Install a checklist
  (Accuracy, AESIA), then fill it.
- The sandbox's Address controls shows its tile.
- A test installs as before in both.

### P5 cleanup, once P4 passes

- Remove from the controls app:
  - `/p/[project]/catalogue` (page, InstallButton, actions);
  - `/p/[project]/install/actions.ts`;
  - `lib/catalogueControls.ts`;
  - the "Add from catalogue" buttons;
  - their tests.
- The library's empty state says where checklists come from now: the project page's catalogue.
- Kept: `/install` (the page the catalogue's button falls back to) and `/api/install`.
- READMEs and compose comments follow.

## Tests first

- platform:
  - the export for a private project equals the online export, for all 44 controls (fixture);
  - a public project proxies;
  - a project with no choice gets 409; a test entry gets 404; a stranger gets 404;
  - the reads answer a public project live, with no Local entries;
  - Update refuses a public project.
- controls app:
  - the package comes from the platform with the caller's token, per project;
  - the install API accepts the launcher's origin and `CATALOGUE_ORIGIN`, and refuses any other.
- catalogue pages: a public project loads with the public label and no Update.
- repo:
  - `project.html` opens `/project-catalogue/` for both modes;
  - Caddy serves it and redirects the old path;
  - compose has the env changes.
- after P5: no `/catalogue` route in the controls app, no "Add from catalogue".

## Not in this

- Redeploying the online catalogue.
- The controls app's Sources pages.
- The engine (frozen).

## Outcome (2026-10-04)

- P1 to P3 built test-first. The platform's packages for a private copy equal the online catalogue's
  exports for all 44 controls (checked live once; a four-control subset is the committed fixture).
- P4 passed on a fresh clone (`~/aisc-proof-2026-10-04`, compose project `aisc-proof`), in a browser:
  - for a private and a public project: chosen on the choice page, opened from the project page;
  - AESIA's Accuracy checklist installed with the catalogue's own Install button (40 questions),
    landing on its fill page;
  - the catalogue card said installed, and the sandbox showed its tile;
  - LangBiTe 0.2.4 installed from the public project's pages;
  - `/private-catalogue/...` redirected to `/project-catalogue/...`.
- P5 done: the controls app's catalogue page, its list of the catalogue's controls and the "Add
  from catalogue" buttons are gone; the ledger tests install through the install API.
- Left as they were: the catalogue pages ask for `/favicon.ico` at the launcher's root (a 404 in the
  console, harmless, already so before); two controls integration tests (I2.6 grants, I6.2 foreign
  key) fail with or without this change.
