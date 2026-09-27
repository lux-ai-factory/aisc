# 04 Code notes: per-project LLM keys and model choice

Stage 4 of the pipeline in this folder. The 13 tasks of 03-coding-plan.md were implemented in
order, test first (the stage 2 tests were the contract; no test was edited). Every run used the
throwaway Postgres `aisc-t-llmkeys-s4-ee41f7cc` (127.0.0.1:56549, removed at the end); nothing
touched the running stack, its databases or its containers; nothing was pushed; scripts/secrets.sh
only ran inside the test's scratch copy.

## 1. Commits (local, branch feat/unified-modules)

| repo | commit | task |
|---|---|---|
| top-level | 7e97a5a | 1 platform runtime deps httpx + cryptography, uv.lock |
| top-level | ee82188 | 2 `platform_service/llm_catalogue.py` |
| top-level | d803d4e | 3 `project-template/0005_llm.sql`, `platform_service/llm_store.py` |
| top-level | 7a228d4 | 4 llm routes, internal resolve route, validation handler in `app.py` |
| apps/qualification | 82322a8 | 5 `fill/baf_llm.py`, `fill/llm.py` as a thin wrapper |
| apps/qualification | 80eb53b | 6 `service.py` `?project=`, `agent.fill_one(project=)` |
| apps/control-objectives | 442fa7f | 7 `baf_llm.py` (byte copy), `llm.py` as a thin wrapper |
| apps/control-objectives | 351f41c | 8 `Projects(mapper_for=)`, 502 routes, `server.build_app` wiring |
| apps/qualification | 91beaa8 | 9 FillerClient `projectId`, createFromForm `{id, projectId}`, action |
| top-level | 09a7cb2 | 10 compose, secrets.sh, Caddyfile, env comments, `scripts/verify-llm-keys.sh` |
| top-level | 31de564 | 11 `homepage/llm.html` |
| top-level | 6754e6f | 13 submodule pointers (apps/qualification 91beaa8, apps/control-objectives 351f41c) |
| top-level | (this commit) | 04-code-notes.md, PROGRESS.md |

Not committed: `homepage/project.html` (task 12). It carries the Manage link on top of the user's
uncommitted edit; the user's hunks are unchanged (checked with `git diff` before and after). The
user commits it with their change.

## 2. Full-suite results (final run, after every commit)

| suite | command (02-tests.md section 3) | result |
|---|---|---|
| platform | from `platform/`, with PLATFORM_TEST_DATABASE_URL / PLATFORM_TEST_SUPERUSER_URL on the throwaway | 258 passed, 0 failed, 2 skipped (tests/test_chain.py, CHAIN_JSON unset, pre-existing) |
| A (agents) | from a scratch dir, `uv run --no-project --with-requirements $A/requirements.txt --with pytest --with httpx --with rdflib python -m pytest ... $A/tests` | 146 passed, 0 failed, 0 skipped |
| B (control-objectives) | from `apps/control-objectives`, CONTROL_OBJECTIVES_TEST_DATABASE_URL on the throwaway | 297 passed, 0 failed, 1 skipped (tests/test_chain.py, CHAIN_JSON unset, pre-existing) |
| qualification-web (2 files) | `npx vitest run test/unit/FillerTrigger.test.ts test/unit/cardVersionsInCoreSystem.test.ts && npx tsc --noEmit` | 25 passed, 0 failed; tsc clean |
| qualification-web (whole vitest) | `npx vitest run` | 420 passed, 1 failed, 20 skipped (51 files: 47 passed, 1 failed, 3 skipped) |
| top-level | `uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests/test_llm_keys.py scripts/tests/test_compose.py` | 26 passed, 0 failed |

These match the plan's expected end state (platform 258 + 2 skipped, A 146, B 297 + 1 skipped,
qualification-web 25 in the two files, top-level 26). No S1.6 role was skipped: the throwaway has
report_ro and inspector_ro.

## 3. Still red

One test, outside the suites 02-tests.md names, found by the whole-vitest regression run:

- `apps/qualification/test/unit/secrets.test.ts > nothing committed carries a credential > holds
  for every file git would publish`:
  `AssertionError: expected [ ...(2) ] to deeply equal []`, received
  `["services/agents/tests/test_baf_llm.py: inline credential",
  "services/agents/tests/test_project_llm.py: inline credential"]`.
  Cause: line 32 of test_baf_llm.py and line 25 of test_project_llm.py,
  `TOKEN = "pytest-internal-" + uuid.uuid4().hex`, match the scanner's "inline credential" regex
  (`token = "<16+ chars>"`; "pytest-internal-" is exactly 16). Both files are stage 2 test files
  (commit 226618c); the test was already red before stage 4 (checked with the stage 4 changes
  stashed) and no product code trips it. Left red because RULES.md forbids editing tests. The fix
  for stage 5 or the user: build the literal so it does not match, e.g.
  `TOKEN = "pytest-" + "internal-" + uuid.uuid4().hex`, in both files (same value, same meaning).

## 4. Deviations from the plan, with the reason

- D-a (task 8 run order): B's full-suite run for task 7 was still going when the task 8 files were
  edited. Its result (289 passed, 8 failed, all 8 in tests/test_project_llm.py) is the task 7
  state; task 7 was committed with its two files only, and task 8 was then run on its own
  (297 passed, 1 skipped) before its commit.
- D-b (task 10, Caddyfile): the new `handle /api/internal/*` block and its comment sit above the
  existing comment of `handle_path /api/*` ("The platform's projects, on the launcher's own
  origin..."), so that comment still describes the block under it.
- D-c (task 10, secrets.sh): besides the plan's changes, the header explains how to rotate
  PLATFORM_SECRETS_KEY (prepend, restart, `python -m platform_service.llm_store rotate`, drop the
  old one), and `--rotate` carries the existing value over (P9).
- D-d (task 11, page): the page keeps its sections hidden until the admin gate passes and shows
  "No project with the handle ..." for an unknown slug. The Remove button shows whenever a provider
  row exists (`updated_at` is set), which covers a stored key and a stored base URL (the plan said
  "when has_key, or a compatible/ollama row with a stored base URL"; the listing cannot tell a
  stored ollama URL from the default, `updated_at` can). A 404 on "Service default" says "Already
  the service default." A provider that is the current choice but no longer usable stays in the
  select so the current choice is still shown.
- D-e (task 12): the link sits under a small group label "Agentic systems" with its own separator,
  in the same style as the existing "Inspect database" group; the link text and the href wiring are
  exactly the plan's.
- D-f (task 7): B's legacy `llm.build_llm(provider, model)` now goes through
  `config_from_env(os.environ, provider, model)`, so an empty `provider` argument falls back to
  BAF_LLM_PROVIDER before the default (before, it went straight to the default). `RunConfig`
  always passes a provider, so nothing observable changes; B's tests are unchanged and green. B's
  BAF agent name is now `control_objectives_llm` (was `control objectives_llm`, with a space), as
  the plan says.
- D-g (task 4): the 422 detail for a base URL sent to a hosted provider is
  "<label> is called at its own address; it takes no base URL"; the model 422 is
  "the model must be 1 to 200 characters, without control characters"; a key-required provider
  without a key on the models route is 409 "<label> has no key in this project" (compatible: "...
  no base URL ..."). The plan fixed the status codes but not these texts.

No R2 contingency was needed: `test_s5_3_building_and_predicting_log_no_key` passed in A and B
without touching any logger level.

## 5. Open items (unchanged from the plan unless said)

- `docker-compose.staging.yml` is not wired (P11, spec scope is development).
- Before the next `up` of the live stack, the user runs `scripts/secrets.sh` once: it appends
  PLATFORM_INTERNAL_TOKEN and PLATFORM_SECRETS_KEY to env.secrets and rebuilds env.runtime. The
  compose file now requires both (`:?`), so `up` refuses to start without them (D9).
- After a deployment: `scripts/verify-llm-keys.sh [slug]` (read-only curl checks; the non-admin
  check needs `AISC_COOKIE`).
- R1 (meta, qwen listing URLs and Google ids unverified live) and R3 (A's publish path through
  qualification-web without a caller token) stand.
- The secrets.test.ts red of section 3.
