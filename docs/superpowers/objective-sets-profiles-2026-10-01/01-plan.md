# Objective sets and objective profiles (2026-10-01)

User decisions: two levels like qualification's question sets and questionnaires. An **objective set**
is where objectives are written and versioned; an **objective profile** is a customised subset picked
from one or more sets, and an assessment runs on one. Identity is permanent: code + number, never
reused. The user chooses a set's code at creation. Defaults accepted: versions like qualification
(draft, publish, pinned, "update available"), switching an assessment's profile is allowed with a
warning and drops what falls outside, export/import later.

## Rules

- Code: 2 to 6 capital letters (`^[A-Z]{2,6}$`), unique in the project, fixed. `O` is the built-in
  AI Act set, so a user code can never be `O` (one letter) or look like a dimension (`R1`).
- An objective id is code + number (`BNK3`); numbers run 1, 2, ... per set and are never reused, a
  retired objective keeps its number.
- Every objective has a dimension `R1` ... `R11` (required), a short label and the objective text;
  legal basis, assessment mode (Control / Test / Control + Test), target, standards grounding,
  grounding tier and notes as in the built-in CSV. A legal basis outside the AI Act and the GDPR is
  regime `other` (only allowed outside the built-in set).

## Storage (project database, schema control_objectives, one alembic revision)

- `objective_set` (id, code unique, name, description, next_number, created_at, created_by)
- `objective_draft` (set_id, number, objective_id unique, fields, retired): the editable working copy
- `objective_set_version` (id, set_id, number, published_at, published_by): immutable
- `objective_set_version_item` (set_version_id, objective_id, position, fields): immutable; a
  retired objective is left out
- `objective_profile` (id, name, description, created_at, created_by)
- `objective_profile_version` (id, profile_id, number, created_at, created_by): saving a profile
  makes its next version (profiles have no draft)
- `objective_profile_version_item` (profile_version_id, objective_id, position, set_code,
  set_version_number): `set_version_number` null for the built-in set
- `project.profile_version_id`: the assessment's pinned profile version; null = the built-in
  "Full AI Act" (all 50). Existing assessments are therefore on Full AI Act with no data change.
- The readers (report_ro, dashboard_ro) may read the new tables.

The built-in set (O1 ... O50) and the Full AI Act profile are not stored: they are the packaged
CSV, read-only and the same for every project.

## Behaviour

- A set: create (code, name, description); add, edit, retire, restore objectives in the draft;
  publish makes version n+1 when the draft differs from the last version. Delete only a set never
  published.
- A profile: pick objectives from the built-in set and from each set's latest published version;
  save makes version n+1 pinned to those set versions. "Update available" when a pinned set has a
  newer version; saving again (accept) repins, dropping objectives the newer version retired.
- Step 2: an assessment pins a profile version. Starting one inherits the previous card version's
  profile. Switching profile (or accepting an update) asks first, then drops mappings and selected
  objectives outside the new profile. Mapper, editor, score, tiers and selection see only the
  profile's objectives. An older version's assessment stays read-only.
- Order of objectives everywhere: built-in set first by number, then each set by code, by number.

## Downstream

- Platform step 4: titles and dimensions of custom objectives from the project database (report_ro);
  template 0018 widens the evidence.link id check to `^[A-Z]{1,6}[1-9][0-9]*$`; the order rule above.
- Renderer: labels of custom objectives from the project database; the order rule above.
- Composer: the order rule above.

## Order of work (TDD each)

A model + storage + library service; B Sets and Profiles pages and API; C step 2 on a profile;
D platform, renderer, composer; E full suites, screenshots, commit and deploy on a yes.
