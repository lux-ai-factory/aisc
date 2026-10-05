# The form speaks VAIR (2026-09-30)

Rule (user, 2026-09-30): one control per thing, VAIR always has precedence, our own list only where
VAIR has no vocabulary for the concept. Risk text fields keep their text and get ONE VAIR dropdown.
The card is built from the form alone; Refine with AI only reads the question answers.

## What each field becomes

| Field | Control | List | Stored as |
|---|---|---|---|
| System type (new, every form) | one select, optional | VAIR `AISystem` (13) | `qualification.system_type` |
| Purpose (new, every form) | one select, optional (the Purpose node is one node: one type) | VAIR `Purpose` (122) | `qualification.purpose` |
| Capabilities (`targetSystemTags`) | add-from-list + chips | VAIR `AICapability` (35), replaces our 14 groups / 50 tags | same column, VAIR names |
| Sectors (`sectorTags`) | chips | VAIR `Domain` (11), replaces our 23 | same column, VAIR names |
| Market form (`marketFormTags`) | chips | VAIR `Modality` (4) | same column, VAIR names |
| Locality (`localityTags`) | chips | VAIR `LocalityOfUse` (3); our "Other" goes | same column, VAIR names |
| Component type | ONE select (replaces "kind") | VAIR `AIComponent` (22) + ours only for: LLM, rule engine, training / validation / other data, pipeline, interface, other | `kind` (platform contract, derived) + new `vair_type` |
| Risk: what could go wrong, weakness | text | none in VAIR | unchanged |
| Risk: cause / result / measure / follow-up | text + one VAIR select | `RiskSource` 44, `Consequence` 7, `RiskControl` 20 | text unchanged + `source_term`, `consequence_term`, `control_term`, `follow_up_control_term` |
| Risk: harm (new) | one select | VAIR `Impact` (9) | `impact_term` |
| Risk: areas | chips | VAIR `AreaOfImpact` (7), replaces our 4 | same column, VAIR names |
| Risk: who is affected | select | ours (VAIR has no stakeholder terms) | unchanged |

A VAIR `Model` term (Model, DecisionTree, BayesianNetwork, MachineLearningModel, TrainedModel) gives
kind `model` (node `AIModel`, `hasModel`); any other VAIR term gives kind `other` (`AIComponent`).

## Phases (each test-first)

1. `src/data/vair_vocab.json`, generated from `vair.ttl` by `airo_min/vair_vocab.py`; a test fails on drift.
2. Builder: tags, system type, purpose, component type, risk terms, impact; labels from VAIR.
3. Web: vocab module, parser, migration + Prisma schema, exporter, repository, card-as-form-start.
4. Web: form controls; card view labels; methodology counts; SystemCard payload.
5. Prefill: `Type:` for components, `... term:` lines for risks, matched by VAIR id or label.
6. Agents: draft techniques only.
7. MCAS: delete card (backup), update the .md with terms, rebuild images, upload, check the graph.

Out of scope: report-generator (prints tag values raw; follow-up), platform `targets.py` (kind unchanged).

## Done (2026-09-30), uncommitted

All seven phases built test-first and live. Deviations from the table above, decided while building:
- A VAIR field is required only where VAIR can always answer: market form, component type, risk
  source / harm / control / follow-up (when there is one), areas. Optional: system type, purpose,
  capabilities, sectors, locality, consequence.
- A component of one of our own types carries qual:termNotApplicable, so the card does not show it as
  waiting for a term.
- The PDF renderer shows a capability without a category as its label alone; rows renamed
  "Capabilities" and "Application domains".

Follow-ups: apps/report-generator reads airo_vocab.json's impactArea (now gone) and prints tags raw,
so reports show VAIR ids until it reads vair_vocab.json; scripts/seed_examples.mjs was already broken
(no systemId) and only had its ids converted.
