# Report generator and report plugin interface: pass (2026-10-05)

All 8 steps. report-generator: the whole repo (every commit is Alessio's). report-plugin-interface: only
the changes of Alessio's 16 commits; Tom Deckenbrunnen's 3 were not reviewed or changed. One fix lives in
the aisc repo's report composer. On `feat/unified-modules`; the local stack runs the result.

Before the push, each repo's commits were squashed into one: report-generator `831f319` (9 commits) and
report-plugin-interface `a3b2109` (4). The originals are on the local branches
`backup/rg-pass-2026-10-05-presquash` and `backup/rpi-pass-2026-10-05-presquash`; the short hashes in
the tables are theirs.

## Before and after

| Check | Before | After |
|---|---|---|
| report-generator tests | 771 passed, 14 skipped (optional tool renderers) | 787 passed, 14 skipped; about 3.5 min instead of 4.3 |
| report-plugin-interface tests | 149 passed | 153 passed |
| ruff | 32 findings (report-generator) | clean; Tom's one finding in the library left |
| WeasyPrint / Pillow | 68.1 / 12.1.1 | 70.0 / 12.3.0; golden outputs unchanged |
| Composer e2e (real renderer) | — | 3 passed |
| Live renderer | — | 200 for a mcas report, 404 for an unknown project, 422 for a PSD saved as a PNG logo |

## Security

| # | Finding | Outcome |
|---|---|---|
| F1 | A template logo (any bytes) reached Pillow 12.1.1, which reads PSD, EPS, JPEG 2000, FITS whatever the declared type; a 1 MB PNG can decode to hundreds of MB; the image ran as root | Fixed: `validate()` checks base64, real type and 16 MP (`8b1502a`); Pillow 12.3.0, non-root image (`97fa6ed`); the composer refuses at save (aisc `8b3e8bd`) |
| F2 | WeasyPrint 68.1 advisories (not reachable) | 70.0 (`97fa6ed`), its new fetcher interface adapted |
| V | Third-party tool renderers' HTML inserted as trusted; no size or concurrency limit on `/v1/render`; base image not pinned to a digest | Follow-ups (no plugin installed today; composer-side limits to decide) |

## Code review

| # | Finding | Outcome |
|---|---|---|
| R1 | Periods not format-checked ("yesterday" gave 500; naive values broke comparisons) | Fixed `8b1502a` |
| R2 | A bad logo base64 gave 500 | Fixed `8b1502a` |
| R3 | The Superset token was kept until a restart; after it expired every chart vanished | Fixed `3e248ef` |
| R4 | An unknown project rendered an empty 200 report | Fixed `66fdc38` |
| R5 | One-file and package plugins could not find their templates (library, Alessio's lines) | Fixed `3f55f3b`; Tom's copy in `base_report_plugin.py` left |
| R6 | With other versions on, other versions' runs counted as evidence | Fixed `9b1de43` |
| R7 | DOCX: a chart inside a list item or table cell shifted every later chart | Fixed `2e1c34d` |
| R8 | Negative values drew as empty bars on a 0..1 axis (library) | Fixed `46229fe` |
| R9 | Two connections per read | Fixed `6693881` (the database lookup remembered 30 s) |
| R10 | Metric choices load every measurement | Follow-up: an SQL `DISTINCT` must reproduce the tool naming exactly; not worth the risk now |

Also: lint (`9ca36f0`, `743018a`), READMEs (`1bd15f9`, `6da8e0b`).

## Found on the way, not in scope

- report-composer: `tests/test_isolation_project_databases.py::test_i8_2_i1_7_...` fails before and
  after this pass: no foreign key from `report_composer.generated_report` to `project.system`.

## Deployed on the local stack

`report-renderer` and `report-composer` rebuilt and restarted; the renderer runs as `renderer` on
WeasyPrint 70.0 and Pillow 12.3.0.
