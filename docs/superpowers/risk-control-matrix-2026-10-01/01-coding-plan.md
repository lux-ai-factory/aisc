# Risk and control matrix, round 1 (2026-10-01): coding plan

Decided: a risk is rated impact x likelihood (1-25, bands Low 1-4, Medium 5-9, High 10-16, Critical
17-25; an unrated part counts 3). Step 2 becomes the profile line, a risk register and the matrix
(one row per risk -> objective). Key replaces the tiers; the matrix replaces the separate selection.
Later rounds: step 4's tests and controls as matrix columns, residual risk, Excel export/import.

Tests written first: control-objectives tests/test_prioritising.py (rewritten: rating, bands, score,
rank, key), tests/test_matrix.py (register, matrix, key, scope), tests/test_migration_project_database.py
(the new revision). Renderer tests: by a separate agent (see section 5).

## 1. Storage (alembic 20261002100000_risk_control_matrix)
- `risk.severity` renamed `rating_impact`; `risk.rating_likelihood` added (int, nullable). The text
  column `risk.impact` (the AIRO chain) is unrelated and stays.
- `objective_key` (project_id fk cascade, objective_id, key bool, pk both): the assessor's key choices;
  readers granted.
- Scope backfill: every `objective_selection` becomes the assessment's mapped objectives, in
  catalogue order (O2 before O10, sets after the built-in one).

## 2. Model and score (prioritising.py)
- `Severity(impact, likelihood, comments)`; `of(risk)` = impact x likelihood with 3 for a missing
  part; `band(rating)`.
- `prioritise(..., keys=None)`: score = sum of ratings; `top_rating`; rank by (voluntary last, -score,
  -top_rating, not binding, catalogue order); `key_default` = first `KEY_BUDGET` (7) ranked objectives
  with score > 0, top_rating >= 10 and not voluntary; `key` = the assessor's choice if any, else the
  default. Tiers are removed.

## 3. Service and routes
- Repository: `rate(project_id, impact, likelihood, comments)`; `save_keys`; every write that changes
  the mapping (AI map, a person's map, a profile switch) rewrites the scope to the mapped objectives.
- Projects: `rate(...)`, `set_keys(project_id, {oid: bool})` (unknown id -> ValueError); the selection
  carry rule (D1, D2) is gone with the selection step.
- Routes: form POST .../severity takes `impact:<risk>`, `likelihood:<risk>`, `comment:<risk>`; API POST
  .../ratings `{risk: {impact, likelihood}}`, POST .../key `{objective: bool}`; form POST .../key
  (`key` = the ticked ones; every objective in the matrix not ticked is set off). The selection routes
  are removed. Payload: `severity.impact`, `severity.likelihood`, `severity.comments`; priorities carry
  `score`, `top_rating`, `rank`, `key`, `key_default`.

## 4. The page (project.html.j2)
Profile line; **risk register** table `co-register` (row `risk-<id>`, short label + folded AIRO chain
`co-chain`, impact and likelihood selects, rating chip `co-rating co-rating--<band>`, rationale);
**matrix** table `co-matrix` (rows `co-mrow` with data-risk/data-objective, sorted by risk rating then
objective rank; risk cell with its rating; objective chip with dimension tag; source AI / by hand;
score; key tick on the objective's first row only, `form="keys"`); an empty row `co-mrow--empty`
"No objective yet" per unmapped risk; each risk's mapping editor (the existing picker) folds under
its rows; "Suggest with AI" with the "?" pop-up above the matrix.

## 5. Renderer (separate agent, report-generator + shared SQL fixtures)
Reads `rating_impact`, `rating_likelihood`; text "Impact 5, likelihood 4: rating 20 (Critical)";
`min_severity` filters on impact (name and range kept for stored layouts); key figures by band;
changes-since reports the rating.

## 6. Done when
control-objectives, platform, composer and renderer suites green on throwaway databases;
screenshots of step 2; then commit, and deploy on a yes.
