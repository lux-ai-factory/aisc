# Follow-ups of the VAIR form (2026-09-30)

## 1. Reports name VAIR choices by their labels

Since the form speaks VAIR (01-plan.md) the qualification tables hold VAIR local names
(`PrivateService`, `RightToNondiscrimination`), and new columns (`system_type`, `purpose`, each risk
field's `*_term`). The report renderer printed tags raw and looked areas up in `airo_vocab.json`'s
`impactArea`, which is gone, so a report showed ids.

- **Vocabulary:** new optional `REPORT_VAIR_VOCAB_PATH`, the generated
  `apps/qualification/src/data/vair_vocab.json`, bind-mounted read-only like `airo_vocab.json`.
  `ctx.data.vocab` gains `vair: {class: {id: label}}`; `impactArea` labels come from VAIR's
  AreaOfImpact, with the old list as fallback. Unset, or an unknown value: the value itself, so the
  old test beds and golden outputs keep their bytes.
- **Readers:** `card()` also reads `system_type`, `purpose`; `risks()` reads the five `*_term` columns.
  The report beds build the qualification schema from `scripts/tests/fixtures/report/schema_qualification.sql`
  (a pre-isolation dump), which gets the migration's `ADD COLUMN` lines.
- **ai_card:** tags as VAIR labels by their class (capabilities, domains, market form, locality);
  rows "Type of AI system" and "Intended purpose" when set; tag rows renamed as on the form
  ("Capabilities", "Application domains").
- **risk_classification:** each text field followed by "(VAIR: label)" when it has a term; a
  "Kind of harm" row.
- **changes_since:** tag values compared as before, shown by their labels.

Tests: unit, with a fake context (no database): the loader, each block's render. The existing DB
suite must keep passing unchanged.

## 2. `scripts/seed_examples.mjs`

It creates cards with no `system_id`, which the schema requires since the project databases
(2026-09-25): it cannot run. A project holds one AI system, so its three example systems have no
place to go, and `seed_mcas.mjs` seeds the worked example the right way. Deleted, with its
`db:seed` npm script.

## Out of scope

The upload filling system type, purpose and the four tag sets (they are chosen on the form).

## Done (2026-09-30), uncommitted

- Built as planned, with one change: the report keeps its headings ("Target system", "Sector") so the
  golden outputs keep their bytes; only the values are VAIR labels.
- Live: report-renderer rebuilt, `/data/vair_vocab.json` mounted, `REPORT_VAIR_VOCAB_PATH` set.
- `scripts/tests/fixtures/report/schema_qualification.sql` has the migration's columns appended.

## Found on the way: the frozen guard (needs a decision)

`scripts/guard-frozen.sh` freezes, since the report run of 2026-09-23, `qualification_risk` and the
`QualificationRisk` model (G2) and pins `airo_vocab.json` by hash (G3). The VAIR form changes all
three on purpose. G3 fails now; G2 cannot run because G1's reference build already fails (as does
G4, on the shared submodules): both older than this work.
