# Local controls

Checklists this stack adds to every project catalogue, **public or private**, next to the public catalogue's entries.

- Each `*.json` file holds one control or a list of them, in the public catalogue's seed format
  (`apps/catalogue/backend/controls_seed.json`): `name`, `slug`, `description`, `dimension_slug`,
  `controls_subdim_slugs`, `metadata` (provider, link, control_topic, scientific_reference) and `questions`
  (`order`, `text`, `article`, `category`). Put an `article` only on EU AI Act questions: any article marks
  the checklist as AI Act when it is installed.
- The platform reads this folder (mounted read-only at `/app/local_controls`): a private catalogue copies it when
  the project chooses it and each time an admin presses **Update**; a public project reads it with every catalogue
  page. A file that cannot be read is skipped and logged.
- They show under Source = Local and install like any control. The evidence page takes their dimension from
  `dimension_slug`, so they link to that dimension's objectives.
- When the public catalogue publishes a control with the same slug, the public one wins: delete the local file.

`fairness.json`: ALTAI requirement 5, FRAIA, NIST AI RMF fairness and bias, and AI Verify fairness process
checks, the same entries as the catalogue's `controls_seed.json` (catalogue c1d992e) until the hosted
catalogue is redeployed with them.
