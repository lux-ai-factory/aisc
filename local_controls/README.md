# Local controls

Checklists this stack adds to every project catalogue, **public or private**, next to the public catalogue's entries.

- Each `*.json` file holds one control or a list of them, in the public catalogue's seed format
  (catalogue branch `dev`, `backend/controls_seed.json`): `name`, `slug`, `description`, `dimension_slug`,
  `controls_subdim_slugs`, `metadata` (provider, link, control_topic, scientific_reference) and `questions`
  (`order`, `text`, `article`, `category`). Put an `article` only on EU AI Act questions: any article marks
  the checklist as AI Act when it is installed.
- The platform reads this folder (mounted read-only at `/app/local_controls`): a private catalogue copies it when
  the project chooses it and each time an admin presses **Update**; a public project reads it with every catalogue
  page. A file that cannot be read is skipped and logged.
- They show under Source = Local and install like any control. The evidence page takes their dimension from
  `dimension_slug`, so they link to that dimension's objectives.
- When the public catalogue publishes a control with the same slug, the public one wins: delete the local file.

## The organisation folder

A second folder holds the organisation's own controls, published from the **add-controls** service
(`apps/add-controls-catalogue`, compose profile `add-controls`, served at `/add-controls/`): an admin uploads a
checklist document, reviews the questions an LLM extracts, and presses Publish.

- The service writes one `{slug}.json` per control into the `org_controls` volume, with an extra key
  `"_published_by": "aisc-add-controls-catalogue"`; it only overwrites or deletes files that carry that key.
  Unpublish deletes the file.
- The platform mounts that volume read-only at `/app/org_controls` (`ORG_CONTROLS_DIR`) and reads it **after**
  this folder, with the same rules; the `_published_by` key is ignored. A slug is taken once, this folder
  first, so a file here wins over the organisation's control with the same slug.
- A stack without the profile has an empty volume: nothing changes.
- Public projects see a published control at once; a private catalogue gets it when an admin presses **Update**.
- To start the service: `scripts/secrets.sh` makes `ADD_CONTROLS_DJANGO_SECRET_KEY`; add by hand to
  `env.secrets` the admin's `ADD_CONTROLS_ADMIN_USERNAME`, `ADD_CONTROLS_ADMIN_PASSWORD_HASH` (from
  `python manage.py hash_password` in the app, written in single quotes because it holds `$`),
  `ADD_CONTROLS_LLM_MODEL` (for example `mistral-large-latest`) and that provider's key
  (`ADD_CONTROLS_LLM_MISTRAL_KEY`, `ADD_CONTROLS_OPENAI_API_KEY` or `ADD_CONTROLS_ANTHROPIC_API_KEY`). Run
  `scripts/secrets.sh` again (it keeps them, `--rotate` too, and rebuilds `env.runtime`), then add
  `--profile add-controls` to the stack's compose command and `up -d add-controls`. Open
  `http://localhost:8100/add-controls/`.

`fairness.json`: ALTAI requirement 5, FRAIA, NIST AI RMF fairness and bias, and AI Verify fairness process
checks, the same entries as the catalogue's `controls_seed.json` (catalogue c1d992e) until the hosted
catalogue is redeployed with them.
