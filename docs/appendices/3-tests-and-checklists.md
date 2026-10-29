# Appendix 3: Choose tests and checklists

Back to [How AISC works](../architecture.md).

## Purpose

Step 3 is where a project picks the checks that will produce its evidence: **tests**, which run on the system (for
example fairness, robustness, performance and jailbreak tests), and **checklists** (controls), which people answer.
Both come from a catalogue, and each is installed from its catalogue entry into the step 4 application that runs it.

## Where

Project page, **3. Choose tests and checklists**. The catalogue's pages are served by `catalogue-private`
(`apps/catalogue`) under `/project-catalogue/` on the launcher's port (8100 by default); the data comes from the
platform.

## Public or private catalogue

The first time, an owner or editor chooses the project's catalogue. **The choice is made once and cannot be changed.**

- **Public**: the hosted catalogue (https://sandboxconfigurator.aifactory.lu/catalogue), read live (cached for a
  minute by default, `CATALOGUE_LIVE_TTL_S`), plus this stack's own checklists from `local_controls/`.
- **Private**: a copy of the public catalogue taken when it is chosen and kept in the project's database, plus this
  stack's own entries, shown with the source Local:
  - **local tests**: every package the engine offers that no public entry names, which includes your folders in
    `local_plugins/`;
  - **local checklists**: the files in `local_controls/`.

  An admin can **Update from public**: it adds, updates and removes the public entries, replaces the tags, metrics
  and metadata, and writes the local checklists again from `local_controls/` (a public entry with the same slug
  wins). Local tests are not stored in the copy, so an update does not touch them. An admin gives a local test its
  dimensions in its entry (**Dimensions**, REQ1 to REQ11): they put it under "For this project" and let the Evidence
  map link it.

**For this project** (on by default) shows only the entries tagged with the dimensions of the objectives selected in
step 2; a project with none yet sees everything. The sidebar also filters by trustworthiness dimension, by "Plugin
available" (tests whose plugin can be installed), by source, by the AI system under assessment and by licence.

## Installing a test

Installing a test takes the realm role `admin`. "Install into this project" opens a dialog with the version, then
**Install**:

1. The platform works out what to install. For a public test it reads the version at the head of its repository on
   github.com/lux-ai-factory (branch `pilot` where it has one, else `feat/unified-modules`, else the default branch). If `devpi`
   already has that version, that is what is installed; if not, it will be fetched and built first. A test from
   `local_plugins/` is always built again from its folder.
2. When a build is needed, `plugin-publisher` clones the repository (or copies the folder, leaving out git, virtual
   environments, caches, old build output and every `.env` file, and refusing links), builds the package as an
   unprivileged user with no secrets, and uploads it to `devpi`. An upload is skipped when the index already holds
   the same content. The dialog warns that this "can take a minute"; the platform waits up to 10 minutes.
3. After a build, the platform checks that the engine now sees that version; then it asks the engine to install it.

A test already installed shows **Installed**: the catalogue does not upgrade it. A private repository needs a
`GITHUB_TOKEN` in `env.secrets`. A failure to fetch, build or install is shown in the dialog with its reason and
"nothing was installed"; a missing admin role, with "Installing a test takes the admin role."

## Installing a checklist

An editor (or owner, or admin) can install a checklist: **Install into a project** lets you pick the project, then
the controls app gets the checklist's package from that project's catalogue through the platform and installs it. A
checklist already installed is left exactly as it is.

## What it produces, and where it is kept

- The catalogue choice and a private copy: schema `catalogue` of the project's database, created when the choice is
  made.
- Installed tests: the engine (schema `engine`). Installed checklists: the controls app (schema `controls`).
- Built packages: `devpi`, which keeps them across restarts (volume `devpi_data`). At every start the publisher puts
  the shared plugin interface on it; tests arrive only when installed.

## Your own tests and checklists

- A test: put its source in a folder under `local_plugins/` (see its README). It appears as Local in a private
  catalogue and installs like any other.
- A checklist: put its JSON file in `local_controls/` (see its README).
- How to write a plugin: `PLUGIN_DEVELOPER_GUIDE.md` in `shared/plugin-interface`.
