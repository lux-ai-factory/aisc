# Appendix 3: Choose tests and checklists

Back to [How AISC works](../architecture.md).

## Purpose

Step 3 is where a project picks the checks that will produce its evidence: **tests**, which run on the system (for
example fairness, robustness, performance and jailbreak tests), and **checklists** (controls), which people answer.
Both come from a catalogue, and each installs in one click into the application of step 4 that runs it.

## Where

Project page, **3. Choose tests and checklists**. The catalogue's pages are served by `catalogue-private`
(`apps/catalogue`) under `/project-catalogue/` on the launcher's port; the data comes through the platform.

## Public or private catalogue

The first time, an owner or editor chooses the project's catalogue. **The choice is made once and cannot be changed.**

- **Public**: the hosted catalogue (https://sandboxconfigurator.aifactory.lu/catalogue), read live. It shows the
  public entries and this stack's own checklists (`local_controls/`).
- **Private**: a copy of the public catalogue kept in the project's database, plus this stack's own tests (from
  `local_plugins/`) and checklists (from `local_controls/`), shown as Local. An admin can **Update from public**,
  which adds, updates and removes the public entries and keeps the local ones. An admin can also tag a local test
  with its dimensions.

**For this project** (on by default) shows only entries tagged with the dimensions of the objectives selected in
step 2. A project with no dimensions yet sees everything. Further filters: plugin available, AI system type, source
and licence.

## Installing a test

Installing a test takes the realm role `admin`.

1. The dialog shows the version it will install. A public test is built from its repository on
   github.com/lux-ai-factory (branch `feat/unified-modules` where it has one), a local one from its folder in
   `local_plugins/`. The first install takes about a minute.
2. The platform asks `plugin-publisher` to build the package. It clones (or copies, leaving out git, virtual
   environments, old builds and every `.env` file), builds as an unprivileged user with no secrets, and uploads the
   result to `devpi`. A version already on the index with the same content is not uploaded again.
3. The platform checks that the engine sees that version, and asks the engine to install it.

A test already installed shows **Installed**: the catalogue does not upgrade it. Private repositories need a
`GITHUB_TOKEN` in `env.secrets`. When something fails, the dialog names it and ends with "nothing was installed".

## Installing a checklist

An editor (or owner, or admin) can install a checklist: **Install into a project** asks the controls app, which gets
the checklist's package from the project's catalogue through the platform and installs it. A checklist already
installed is left as it is.

## What it produces, and where it is kept

- The catalogue choice and a private copy: schema `catalogue` of the project's database.
- Installed tests: the engine (schema `engine`). Installed checklists: the controls app (schema `controls`).
- Built packages: `devpi`, which keeps them across restarts. A fresh install starts with an empty index.

## Your own tests and checklists

- A test: put its source in a folder under `local_plugins/` (see its README). It appears as Local in a private
  catalogue and installs like any other.
- A checklist: put its JSON file in `local_controls/` (see its README).
- How to write a plugin: `PLUGIN_DEVELOPER_GUIDE.md` in `shared/plugin-interface`.
