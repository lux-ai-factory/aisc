# Objective ids O1..O50, manual risk mapping, severity score (2026-10-01)

User decisions (2026-10-01):

1. The mapping between a risk and its control objectives is made either by the AI (the risk mapper,
   as today) or by a person. Both stay; Manage -> Keys keeps the risk mapper entry.
2. Objectives are ranked by S(o) = sum of the severities of the risks mapping to o (linear).
3. The objective ids become O1, O2, ... O50 everywhere, stored data included (real id change, not a
   label).

## The score

    S(o) = sum over risks r of M(r,o) * s_r  =  n(o) * mean severity
    s_r  = the assessor's 1-5, 3 when not rated; M(r,o) = 1 when r maps to o

Order: S desc, then the worst single severity desc, then directly binding before standards-grounded
only, then catalogue order. The binding bonus (+1) is no longer added to the score: it is a tiebreak.
Tiers as before: Tier 1 = the first 7 with S > 0 whose worst risk is rated 3 or more; Tier 2 = every
other S > 0; Tier 3 = S = 0, and every voluntary objective.

## The ids

O-numbers run in catalogue order: R1.1=O1 ... R11.4=O50 (the table is in
`apps/control-objectives/src/aisc_control_objectives/data/objective_id_renames.csv`). The
macro-requirements (R1..R11) keep their ids: they are the trustworthiness dimensions. An objective's
dimension is now its catalogue `macro_id`, never parsed from its id.

Stored ids migrated in every project database:
- control-objectives alembic revision: `mapped_objective.objective_id`,
  `objective_selection.objective_ids`.
- platform project template 0017: `evidence.link.objective_id`, and its CHECK becomes `^O[0-9]+$`.
- Issued reports keep their frozen snapshot as issued.

## Manual mapping

- `mapped_objective` gains `source` ('ai' | 'person'); the AI's rows are 'ai', existing rows backfill
  to 'ai'.
- Step 2 lists each risk with the objectives it maps to (source shown) and an editor (objectives
  grouped by dimension) that saves that risk's mapping. A row kept from the AI stays 'ai' with its
  quote; an added one is 'person' with no quote.
- A manual save works with no AI run: the assessment counts as mapped once any risk has a mapping or
  a run exists. The selection follows the mapping change by the existing carry rule (D1, D2).
- "Map with AI" replaces the whole mapping, edits included; the button says so.

## Order of work (TDD each)

A. Catalogue ids (CSV, model pattern, sort, dimension from macro_id) + rename table + CO migration.
B. Score in prioritising.
C. Manual mapping (repository, service, route, template, `source` column).
D. Platform: objective dimension from the catalogue's macro_id, numeric O order, template 0017.
E. Report composer and renderer: numeric O order.
F. Risk-mapper skill example, docs.
