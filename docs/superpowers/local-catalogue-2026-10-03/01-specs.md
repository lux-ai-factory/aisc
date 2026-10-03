# A project's catalogue: public or private, chosen once (2026-10-03)

## Decisions (the user, 2026-10-03)

- D1 Each project chooses, on its first visit to the catalogue: the **public** catalogue (the hosted
  one, as today) or a **private** copy. The choice is final: no switching, so nothing ever moves
  between the two.
- D2 Nothing is created at stack start and no migration runs then. A project's catalogue data is
  created when it chooses, in that project's own database, and is deleted with the project.
- D3 "Update from public" on a private copy: entries that came from the public catalogue take the
  public version again; entries that exist only locally are always kept.
- D4 Install packages come from where they come from today; only the listing is copied.
- D5 The private catalogue **looks exactly like the public one**: it is the catalogue's own frontend,
  not an imitation.
- D6 Sean's code (engine, webapp, plugin manager) is not changed. Meril's catalogue frontend gains one
  feature on our branch (`feat/unified-modules`, as the one-click install did), behind a build switch
  that is off by default, so the public catalogue stays as it is; it is then offered to Meril as a
  pull request to their `dev`. Meril's catalogue backend is not changed. **Open: Meril's agreement
  before the frontend code is written (the user arranges it).**
- D7 In the private catalogue the person is already signed in (the stack's gateway): no password
  pop-up; the admin actions show for the Keycloak `admin` role only.

## Who does what

| Part | Owner | Change |
|---|---|---|
| Platform (Python) | us | the choice, the private copy, its update, catalogue-shaped read endpoints, the project's dimensions, the local plugins |
| Launcher (homepage) | us | the choice page; the catalogue card opens the chosen catalogue |
| Catalogue frontend | Meril | one switched-off feature (F1) |
| Catalogue backend | Meril | none |
| Engine, webapp, plugin manager | Sean | none: used through what exists (plugin list, install link) |
| Controls app | us | none: installs through its existing page |

## P1 The choice (platform)

- P1.1 `GET /projects/{slug}/catalogue` → `{"mode": null|"public"|"private", "updated_at", "can_update"}`;
  any member. `can_update` is true for the Keycloak `admin` role.
- P1.2 `POST /projects/{slug}/catalogue {"mode"}`; owner or editor; 409 once a mode is recorded (D1).
- P1.3 Recording a mode creates schema `catalogue` in the project's database (as platform_rw, which
  already applies every module's templates there) with `catalogue.mode (mode, chosen_by, chosen_at)`
  and its row. For `private` it also creates the copy's tables (P2) and fills them from the public
  catalogue in the same request. Only the platform reads and writes the schema, so no other role
  gets a grant. Any failure drops the schema again and answers 503: no half-made
  copy, and the project can choose again.
- P1.4 A project that never chose has no `catalogue` schema.

## P2 The private copy (platform)

- P2.1 Tables in the project's `catalogue` schema: `entry (slug primary key, origin 'public'|'local',
  data jsonb, synced_at)`, holding each tool or control as the public `GET /tool/?detailed=true`
  returns it; `tag (slug, data jsonb)` and `metric (id, data jsonb)` likewise; `local_dimension
  (package_name, dimension)` for P4.
- P2.2 `POST /projects/{slug}/catalogue/update` (Keycloak admin only): reads the public catalogue's
  read API (the address already configured, `CATALOGUE_API_URL`) and upserts by slug: public entries
  are replaced (D3), local ones untouched, a public entry gone from the public catalogue is removed.
  Answers `{added, updated, unchanged, removed, local_kept}`. The public catalogue not answering
  changes nothing and says so.

## P3 Catalogue-shaped read endpoints (platform)

- P3.1 Under `/projects/{slug}/catalogue/api/`, the four reads the catalogue frontend makes, with the
  public backend's JSON shapes: `tool/` (with `?detailed=true`), `tags/`, `metric/`, `metadata/`,
  served from the private copy, plus the local entries (P4). Any member may read; writes are refused.
- P3.2 Each entry carries two fields the public shapes do not have and the public frontend ignores:
  `aisc_local: bool` and `aisc_installed: bool` (installed in this project's engine or controls).
- P3.3 `GET /projects/{slug}/catalogue/api/project-dimensions` → the catalogue's dimension tag slugs of
  the project's selected control objectives (the mapping evidence.py already has), latest card version.
- P3.4 A contract test compares these answers' shapes with the public catalogue's own, so a change on
  Meril's side is caught.

## P4 Local plugins (platform)

- P4.1 The engine's existing `GET /api/v1/plugins` (called with the signed-in person's token, as the
  platform's other engine calls are) lists the packages available in this stack: `local` (the
  `local_plugins/` folder) and `registry` (the stack's package index). Those whose package is not in
  the public catalogue are the **Local** entries, `origin: local`, named and described from the
  engine's answer.
- P4.2 Their dimensions are set by an admin (`PUT /projects/{slug}/catalogue/local/{package}/dimensions`)
  and kept in `local_dimension`; until set, a local entry has none and is shown as not classified.
- P4.3 Installing one uses the engine's existing install link with its package and version, unchanged.

## F1 The catalogue frontend feature (Meril's repo, our branch, switch `VITE_ENABLE_PROJECT_CATALOGUE`)

- F1.1 Off (the default, and the public catalogue): nothing changes.
- F1.2 On, opened as `/catalogue?project=<slug>`: the frontend reads from the platform's P3 endpoints of
  that project instead of its own backend. Without `?project`, it says to open it from a project.
- F1.3 A **For this project** switch in the existing filter panel, on by default, showing the entries
  tagged with the project's dimensions (P3.3, a sub-dimension counting as its parent); off shows all.
- F1.4 **Local** appears in the existing Source filter; a local entry's card carries a "Local" badge.
- F1.5 An **Update from public** button for `can_update` people (P1.1), calling P2.2 and showing its
  counts; and the copy's "updated on" date.
- F1.6 No password pop-up in this mode; add and delete stay hidden (the copy is read-only, D3 keeps
  authoring on the public catalogue); the existing Install button is on and installs into this
  project: tests through the engine's install link, controls through the controls app's
  `/controls/install?slug=` page (D4: it fetches the export from the public catalogue).

## L1 The launcher

- L1.1 The plan block's "Identify tests and controls" card asks P1.1: no mode → a choice page
  (`/catalogue.html?project=<slug>`) explaining both options and that the choice is final, offering
  **both** (a public-only first phase would lock projects out of private for good); public → the
  hosted catalogue as today; private → until F1 exists, the same page showing the copy's state
  (updated on, counts) and, for admins, Update from public; once F1 exists, the catalogue frontend
  served in this stack, `?project=<slug>`. The platform not answering → the hosted catalogue, as today.
- L1.2 The catalogue frontend is served in this stack on its own site behind the gateway (it cannot
  live under a path prefix), built from our branch with `VITE_ENABLE_PROJECT_CATALOGUE=true` and the
  platform as its data source. No catalogue backend and no catalogue database run in the stack.

## C1 (dropped 2026-10-03)

The "package name never returned" bug was read from the old catalogue checkout; the public catalogue
the stack uses does return `package_name` (sample of 2026-10-03), so evidence.py's fallback works.

## Out of scope

Switching a project's mode (D1); copying install packages (D4); authoring entries in a private copy;
the hosted catalogue's own password pop-up (its operators' call).

## Phases (each: tests first, then code, then tested; live only when asked)

1. P1 + L1.1 with "public" only: the choice page and its record; public works as today.
2. P2 + P3 + P4 (platform): the private copy, its update, the catalogue-shaped reads, local plugins.
3. F1 + L1.2: the frontend feature and serving it (after Meril's agreement, D6).
(C1 dropped.)
