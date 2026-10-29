# Local controls

Checklists this stack adds to every project catalogue, **public or private**, next to the public catalogue's
entries. In step 3 (Choose tests and checklists) they show with Source = **Local** and install like any other
checklist; in step 4 people answer them in the controls app (`controls-web`).

## How it works

The platform (service `platform`) reads this folder, mounted read-only at `/app/local_controls`:

- a **public** catalogue reads it with every catalogue page;
- a **private** catalogue copies it into the project's catalogue when the project chooses it, and again each time
  an admin presses **Update from public**.

A file or an entry that cannot be read is skipped, with a warning in the platform's log. `uv run scripts/aisc.py
start` lists the local controls it finds at the end of a start. When the public catalogue publishes a control with
the same slug, the public one wins: delete the local file.

On step 4's Evidence map, a local checklist carries the dimension of its `dimension_slug`, read from the project's
catalogue, so it can be linked to the control objectives of that dimension.
[docs/architecture.md](../docs/architecture.md) shows where the catalogue and the controls app sit in AISC.

## Writing one

Each `*.json` file holds one control or a list of them, in the public catalogue's seed format (catalogue branch
`dev`, `backend/controls_seed.json`):

| Key | What it is |
|---|---|
| `name`, `slug`, `description` | the checklist's name, its unique id and what it checks; `slug`, `name` and `questions` are required |
| `dimension_slug` | its trustworthiness dimension |
| `controls_subdim_slugs` | its sub-dimensions |
| `metadata` | `provider`, `link`, `control_topic`, `scientific_reference` |
| `questions` | each with `order`, `text`, `article`, `category` |

Put an `article` only on EU AI Act questions: any article marks the checklist as AI Act when it is installed.
Files are read in name order; a slug is taken once, from the first file that has it.

## What is here

`fairness.json`: four checklists (ALTAI requirement 5, FRAIA, NIST AI RMF fairness and bias, and AI Verify
fairness process checks), the same entries as the catalogue's `controls_seed.json` on branch `dev`. Once the
hosted catalogue publishes them, its entries win and this file can be deleted.

The loader is `platform/platform_service/local_controls.py` (setting `LOCAL_CONTROLS_DIR`, default
`/app/local_controls`).
