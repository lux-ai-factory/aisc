# apps/eval review pass, 2026-10-07 (the user's code only)

Pushed 2026-10-07 as one squashed commit `651dc66`; the short hashes below are the pre-squash ones (kept on the local branch `backup/eval-pass-2026-10-07-presquash`).

Branch `feat/unified-modules`, from origin `59de0de`. All 8 steps of `~/aisc-review-continue.md`, worked
in `~/aisc` (the `~/aisc-macfix` clone of the handoff no longer exists). Commits are local, unpushed,
not squashed: `eaa7702` (lint), `08aa7c6` (refactor, A items), `2df09e8` (B items), `b510340` (README).
The engine is frozen by default; the user lifted that for their own eval commits for this pass.

## Scope

`git blame --line-porcelain HEAD`, author `alessiobuscemi`: code in `aisc_eval/run_context.py`,
`aisc_eval/deployment.py`, `aisc_eval/service/api_client.py` (`headers()`, `fit_measure`,
`post_measures`), 9 lines of `aisc_eval/celery_tasks.py`, and the tests `test_run_ticket.py`,
`test_run_context.py`, `test_run_context_broker.py`, `test_deployment_mode.py`,
`services/test_post_measures_fit.py`. Code commits 7f7de02, e0d6d42, 3a2df2f, f06e448, 0302352,
03b2103, 59de0de; the rest are docs and merges. Others' code was read for context only, except S1
(below), which the user decided to change.

## Before / after

| Check | Before | After |
|---|---|---|
| `uv run pytest tests/` (documented) | stops at collection: `tests/conftest.py` imports `onnxruntime` and the removed `Dataset` (not the user's) | same (not the user's; README now says so and gives the working command) |
| pytest `--noconftest --ignore=tests/test_basic_integration.py`, standalone, throwaway broker | 27 passed, 8 skipped, 1 failed, 1 error | 38 passed, 8 skipped, 1 failed, 1 error |
| same, `AISC_DEPLOYMENT=configurator` | 30 passed, 5 skipped, 1 failed, 1 error | 41 passed, 5 skipped, 1 failed, 1 error |
| the failure and the error | Sean's: `test_project_settings_runtime` (KeyError `plugin_config_key`), `services/test_api_client.py::test_get_evaluation` (KeyError `feature_type`) | unchanged |
| ruff check | 4 F401, all others' lines | same 4 |
| mypy | 43 errors, 18 on the user's lines | 32 errors, 7 on the user's lines (Sean's restored task signatures, see C2) |
| ruff format | 15 files | the user's 7 files formatted; mixed files left |

## Findings

| Id | Class | Where | Finding | Outcome | Commit |
|---|---|---|---|---|---|
| S1 | B (security) | `celery_tasks.py:402` (Mohammed Fellaji's line) with `run_context._forward` and `api_client.headers` (user's) | A plugin ran with a copy of the worker's environment: broker URL with password, `INTERNAL_API_KEY`, `DJANGO_SECRET_KEY`, `PACKAGE_REGISTRY_PASSWORD` (verified live). A plugin could read other runs' queued tasks from the broker, lift their `aisc_run` ticket and call the internal API as another project for the ticket's 24 h | user: fix. `plugin_environment()` allowlist; on the live worker a plugin now sees `PATH HOME LANG PLATFORM_URL PLATFORM_CONNECTIONS_TOKEN API_KEY_OPENAI` (+ proxies, CA, `AISC_TARGET_*`, `AISC_SECRET_*` when set) | `2df09e8` |
| R1 | A | `run_context.run_of` | A run header missing one of project/evaluation/ticket raised KeyError in every internal call, including `mark_plugin_failed` in an `except`, hiding the real error | a partial header counts as no run; test | `08aa7c6` |
| R2 | A | `api_client.fit_measure` | A cut text was not logged | warning with field and original length; test | `08aa7c6` |
| R3 | A | `api_client.headers` | Compared `deployment.MODE` by hand; `is_configurator()` exists | uses it | `08aa7c6` |
| R4 | A | `run_context.py`, `api_client.py` | 11 mypy errors (untyped defs, bare `dict`, `str | None` header values) | annotated | `08aa7c6` |
| R5 | B | `api_client.fit_measure` (`name`) | The engine finds a metric by exact name; two long names sharing 254 characters were stored as one metric, their scores mixed (before 59de0de the batch failed loudly) | user: fix. A cut name ends with `…[` + 8 hex of sha256 of the whole name `]`; tests | `2df09e8` |
| R6 | B | `api_client.fit_measure` | NUL in a text makes Postgres refuse the whole batch, the same failure 59de0de fixed for length | user: fix. NUL removed; test | `2df09e8` |
| R7 | B | `deployment.check_environment` | The worker started without `INTERNAL_API_KEY` and had every call refused with warnings only; `check_environment` was never called | user: fix. Required in both modes, checked on `worker_init` (flower imports the same app and has no key, so it is not checked); tests | `2df09e8` |
| R8 | B | `tests/test_run_context_broker.py` | The only proof that children inherit the run used a simpler workflow than production and skips without a broker | user: fix. Workflow now `group(chain(install, group(chain(plugin, post)...)) x2) | finalize`, asserting every task; test worker uses `pool="threads", concurrency=4`. With `pool="solo"` that shape stalls after 2 of 4 `post` (not production's pool; not investigated further). CI wiring not done | `2df09e8` |
| R9 | B -> C | `run_context._enter` | An eager task (`.apply()`) inside a task runs with no run | not changed: a header-less task never inheriting a run is a property the security review relies on; nothing calls `.apply()`. Comment that claimed the case was covered made true | `2df09e8` |
| C1 | C | review points 9-14 | `_leave` without token, redelivery path, grapheme split, `headers(run=)` test hook, 255 limit duplicated, empty `AISC_DEPLOYMENT` | rejected by the reviewer with reasons (cannot happen here, cosmetic, deliberate) | |
| C2 | C | `celery_tasks.py:137,193,272,488` | mypy on task signatures blamed on the user | not changed: they are Sean's master signatures restored verbatim (0302352); typing them would diverge from master | |

## Not the user's (report only)

- `tests/conftest.py` (onnxruntime, `Dataset`) and `tests/test_basic_integration.py` (`Feature`, `FeatureType`) are stale: the documented test command cannot run.
- Sean's failing `test_project_settings_runtime` and erroring `test_get_evaluation`.
- `celery_app.py:8` logs the Redis URL with its password at debug level.
- 4 unused imports in `celery_tasks.py` (Sean, Mohammed).

## Follow-ups

- `PLATFORM_CONNECTIONS_TOKEN` still reaches plugins by design (the connection resolver needs it); check its scope (per project or global) in the platform pass.
- Ticket lifetime: 24 h and not revoked at finalize (backend side).
- Broker test in CI with a throwaway broker.

## Deploy

`aisc-eval:latest` rebuilt from `b510340`; `aisc-eval-worker` and `aisc-eval-flower` recreated on the local
stack (`--no-deps`), both healthy; worker `ready`. Live evaluation 2026-10-07 15:02 UTC: LangBiTe on mcas (evaluation 5, `b791bba1`) through the new worker, all five tasks ran, measures posted (201), status Done; the plugin reached MCAS through the platform with the allowlisted environment.
