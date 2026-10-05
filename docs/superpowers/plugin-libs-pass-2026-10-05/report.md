# Plugin manager and plugin interface: pass on this month's commits (2026-10-05)

All 8 steps, limited to the changes in Alessio's own commits since 2026-09-05 (5 in plugin-manager, 17
in plugin-interface); Sean's and Méril's code was not reviewed or changed. A fix went outside those
lines only where a bug in them needed it (noted below). On `feat/unified-modules`; the engine and the
platform run the result.

Before the push, the pass's commits were squashed into one per repo: plugin-manager `a73b443` (3
commits) and plugin-interface `fc37ae3` (8, plus `uv.lock` carrying 0.2.7). The originals are on the
local branches `backup/pm-pass-2026-10-05-presquash` and `backup/pi-pass-2026-10-05-presquash`; the
short hashes in the tables are theirs.

## Before and after

| Check | Before | After |
|---|---|---|
| plugin-manager tests | 31 passed | 35 passed |
| plugin-interface tests (README command) | stopped at collection (pandas) | 145 passed (121 + 1 module skipped without pandas) |
| ruff on this month's lines | 1 + 10 findings | clean (one in Sean's `datashape.py` left) |
| platform connection tests | — | 137 passed |

## Security (plugin-interface)

| # | Finding | Outcome |
|---|---|---|
| F1 | High: IPv4-mapped addresses (`::ffff:169.254.169.254`) passed the denied list | Fixed `4798370` |
| F2 | High: DNS rebinding between the check and the connection | Fixed `4798370`: the peer the socket reached is checked before sending |
| F3 | Answers read whole into memory | Fixed `2ac4d87`: 10 MiB cap |
| F4 | `target_calls_at_once` unbounded | Fixed `b853fc4`: at most 16 |
| F5 | A key across the 300-character cut survived | Fixed `d1adbaa` |
| V | Cross-project references through the platform's internal routes; formulas in `target-answers-*.csv`; package names from devpi into `uv pip install` | Follow-ups: outside these commits |

plugin-manager: no high-confidence finding; `git status` now runs with `core.fsmonitor` off (`b027dd2`).

## Code review

| # | Finding | Outcome |
|---|---|---|
| 1 | `@dataset_through_target` fed CSV back to any provider (Parquet/JSON crashed) | Fixed `33d21da` (adds `BaseEvaluationPlugin._replace_input_data`, a new method in a file that is partly Sean's) |
| 2 | A dropped connection escaped unretried and aborted a dataset run | Fixed `d1adbaa` |
| 3 | Rebinding / mapped addresses | = F1, F2 |
| 4 | Local plugins stored under their declared version stopped loading | Fixed `b027dd2` |
| 5 | A digest or git failure dropped a local plugin | Fixed `b027dd2` |
| 6 | Any 404 skipped an optional target | Fixed `b853fc4` + platform `reason: no_endpoint` (aisc) |
| 7 | `connection:` references and unbound inputs in `@dataset_through_target` | Fixed `b853fc4` |
| 8 | Key across the excerpt's cut | = F5 |
| 9 | `_issue_run_key` followed redirects with the service token | Fixed `b853fc4` |
| 10 | git status and a file walk on every listing | Fixed `b027dd2`: cached |

Also: the README's test command (`81b277c`), lint (`3a2570e`, `5ad373a`), docs (`148e2f2`, `cc43635`).

## Deployed on the local stack

`aisc-backend` and `aisc-eval-worker` restarted (they run `shared/` from the mount); `platform`
rebuilt (its no-endpoint answer). The engine lists every devpi version and loads LangBiTe 0.2.6.
