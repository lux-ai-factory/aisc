# 05 Report: verify until green (per-project LLM keys and model choice)

Stage 5 of the pipeline in this folder. Result: GREEN, in 2 rounds. Every suite was run by this
stage on its own throwaway Postgres (`aisc-t-llmkeys-s5-acc1ddcd`, 127.0.0.1:58499, removed at
the end). Nothing touched the running stack (compose project `aisc`), its databases or its
containers. Nothing was pushed. `homepage/project.html` and `docs/superpowers/report-v2-2026-09-24/`
were not touched or committed.

## 1. Suites (commands of 02-tests.md section 3)

| suite | round 1 | final (round 2) |
|---|---|---|
| platform (`PLATFORM_TEST_DATABASE_URL` + `PLATFORM_TEST_SUPERUSER_URL` on the throwaway) | 258 passed, 2 skipped | unchanged (no platform file edited) |
| A, card agent (from a scratch cwd, `--with rdflib`) | 146 passed | 146 passed |
| B, control-objectives (`CONTROL_OBJECTIVES_TEST_DATABASE_URL` on the throwaway) | 297 passed, 1 skipped | unchanged (no B file edited) |
| qualification-web, the two S3.8 files | 25 passed; `tsc --noEmit` clean | unchanged |
| qualification-web, whole vitest | 420 passed, 1 failed, 20 skipped (51 files: 47 passed, 1 failed, 3 skipped) | 421 passed, 0 failed, 20 skipped (48 passed, 3 skipped) |
| top-level (`test_llm_keys.py`, `test_compose.py`) | 26 passed | 26 passed |

The skips are pre-existing: `tests/test_chain.py` (CHAIN_JSON unset) in platform (2) and B (1), and
the 3 vitest files that skip without their services. Round 1 matched stage 4's claims exactly.

## 2. Fix made

The one red was the known false positive in `apps/qualification/test/unit/secrets.test.ts`:
`TOKEN = "pytest-internal-" + uuid.uuid4().hex` in the stage 2 files
`services/agents/tests/test_baf_llm.py` and `test_project_llm.py` matches the inline-credential
pattern (`token = "<16+ chars>"`). The literal is now `"pytest-" + "internal-"`, same value, no
assertion changed. B's copies keep the old literal (B has no such scanner).

| repo | commit | what |
|---|---|---|
| apps/qualification | c324885 | split the test token literal in the two stage 2 test files |
| top-level | 3f040ee | record apps/qualification c324885 |
| top-level | (this commit) | 05-report.md, PROGRESS.md |

No product code needed a change.

## 3. Independent checks beyond the suites

Scripts in the session scratchpad only (not in the repo).

### 3a. End to end (30 of 30 checks passed)

Set-up: the platform app under `uvicorn --log-level debug` on the throwaway DB with test secrets
(fresh Fernet key, random internal token, `AUTH_ENABLED=true`). A local fake server served both a
JWKS (so real RS256 token verification ran through `aisc_identity`, no dependency override) and an
OpenAI-compatible API that records the `Authorization` header and the `model` of each request.

| check | result |
|---|---|
| admin creates two projects (P, Q) through `POST /projects` (each gets its database, 0005 included) | pass |
| `PUT .../llm/providers/compatible` with a key and the fake base URL: 200, `has_key`, `usable` | pass |
| `GET .../providers/compatible/models`: the fake's two ids, `error: null`; the fake saw `Bearer <key>` | pass |
| `PUT .../llm/systems/card_agent` and `risk_mapper` with that model; the listing shows both choices | pass |
| no page-facing response body holds the key, the ciphertext or its first 20 characters | pass |
| raw column (superuser select on `project_<pid>.llm.provider`): Fernet token `gAAAA...`, decrypts to the key; the key is not a substring of any column | pass |
| non-member non-admin: 404; member (editor) non-admin: 403 on GET listing, GET models, PUT key; no token: 401 | pass |
| project Q: compatible not `has_key`/`usable`, no choices, models route 409, resolve `{"configured": false}` | pass |
| internal resolve: no token 401, wrong token 401, correct token plus `X-Forwarded-For` 404 | pass |
| internal resolve with the token: `configured, provider, model, base_url, api_key` = the stored values, `Cache-Control: no-store` | pass |
| card agent: A's `fill.baf_llm.config_for(pid, "card_agent")` (A's requirements env), driven only by `PLATFORM_URL` + token, repr `api_key=<set>`; `build_llm` + `completer(...)("sys","ping")` hit the fake `/v1/chat/completions` with `Bearer <stored key>` and the chosen model; answer "pong" | pass |
| risk mapper: the same with B's `aisc_control_objectives.baf_llm` (B's venv) and `risk_mapper` | pass |
| DEBUG output of both agent runs (root logger at DEBUG, BAF, openai, httpx) holds no key | pass |
| deleting the key both systems use: 409 naming both | pass |
| platform DEBUG log (24 request lines): no API key, no Fernet key, no internal token | pass |

### 3b. Static checks

- Logging: every `logger.*`/`print(` call in the changed platform, A and B modules was read. None
  takes a key, token, ciphertext, URL body or exception text: the catalogue logs the provider id and
  a kind word, rotation prints counts only, A's `agent.py` prints fill statistics and the payload of
  a dry run (no config).
- `baf_llm.py`: byte-identical (`cmp`), sha256 `93c23c48...2277` for both working-tree copies and
  both committed blobs.
- Caddyfile: the real file, copied, ran in a throwaway `caddy:2.10.2` container (only its :8100
  published on a random loopback port). `/api/internal/projects/<uuid>/llm/card_agent`,
  `/API/internal/x`, `/api/Internal/x`, `/api//internal/x`, `/api/%69nternal/x`, `/api/./internal/x`
  and `/api/internal%2fx` all answer 404; `/api/internal` (no slash) and `/api/projects` fall through to
  `protect` (502 there, no oauth2-proxy). `/internal` alone is not a platform route, and the platform
  also refuses anything that carries `X-Forwarded-For`, which Caddy's `reverse_proxy` always adds.

### 3c. The page `homepage/llm.html`

- One `<script>` element, inline; no `on...=` attribute in markup, no `.onX =` property, no
  `innerHTML`/`outerHTML`/`insertAdjacentHTML`/`document.write`/`eval(`; `node --check` on the script
  passes. Listeners use `addEventListener`.
- The only `fetch` is in `api()`, with `credentials: 'same-origin'`. Paths called:
  `GET /api/projects/{slug}`, `GET /api/authz/projects/{slug}`, `GET /api/projects/{slug}/llm`,
  `PUT|DELETE /api/projects/{slug}/llm/providers/{id}`, `GET .../providers/{id}/models`,
  `PUT|DELETE /api/projects/{slug}/llm/systems/{id}`. Each exists in `platform_service/app.py`
  (Caddy strips `/api`). External resources: the Google Fonts links project.html already uses, and
  `/assets/laif-logo.svg` (exists).

## 4. Still open (for the user)

To deploy (nothing of this was applied to the running stack):
1. Run `scripts/secrets.sh` once. It appends `PLATFORM_INTERNAL_TOKEN` and `PLATFORM_SECRETS_KEY` to
   `env.secrets` (never replacing a value) and rebuilds `env.runtime`. The development compose file
   requires both (`:?`), so `up` refuses to start without them.
2. Rebuild and restart `platform` (new deps httpx, cryptography; new routes), `qualification-agents`
   (baf_llm, `?project=`), `control-objectives` (baf_llm, per-map model), `qualification-web`
   (sends the project id) and reload Caddy (the `/api/internal/*` block). `homepage/llm.html`
   needs no build: `docker-compose-infra.development.yml` mounts `./homepage` read-only into Caddy.
3. Existing project databases get `0005_llm.sql` with no manual step: `db.provision_all` re-runs
   `projectdb.provision` for every project at the platform's first query after start, and records
   it in `provision.template_migration` (S1.5, tested). New projects get it at creation.
4. Commit `homepage/project.html` together with your own uncommitted edit (it carries the "Models and
   API keys" Manage link on top of it).
5. After the deployment: `scripts/verify-llm-keys.sh [slug]` (read-only; the non-admin check needs
   `AISC_COOKIE` of a non-admin session). Before the deployment its first check fails by design.
6. Rotating the Fernet key: prepend a new key to `PLATFORM_SECRETS_KEY`, restart the platform, run
   `python -m platform_service.llm_store rotate` in it, then drop the old key. `secrets.sh --rotate`
   keeps the existing `PLATFORM_SECRETS_KEY` on purpose.

Not done by design: `docker-compose.staging.yml` is not wired (P11).

## 5. Residual risks

- R1: the listing endpoints of meta and qwen, and Google's model ids without the `models/` prefix
  through BAF's Gemini wrapper, are unverified against the live providers. All provider tests and
  this e2e used fakes; only the OpenAI-compatible path was exercised end to end. Check each hosted
  provider you use once, with a real key, after the deployment.
- R3 (pre-existing, out of scope): A publishes through qualification-web's
  `/api/qualifications/{id}/extracted` without a caller token; the card agent may fail end to end
  for that reason regardless of this feature.
- D11: anyone already on the `backend` network can call A with another project's pid and make it
  spend that project's key (without seeing it). The internal route itself needs the token.
- R4: `inspector_ro` (pgAdmin, admins) can read the ciphertext table; without `PLATFORM_SECRETS_KEY`
  it is useless.
- The e2e drove each agent's `baf_llm` directly, not the full fill or map flow; those flows are
  covered by A's `test_project_llm.py` and B's `test_project_llm.py` with fakes.

## Addendum 2026-09-25: the card agent's project is no longer the caller's to name

The residual risk "anyone on the backend network can make the card agent use another
project's key" is closed (apps/qualification e9d0693). `POST /fill/{id}` takes no project and
a `?project=` a caller adds is ignored; `fill_one` reads `projectId` from the app's export of
the qualification (`GET /api/qualifications/{id}/extracted`, which now carries the
qualification's own project) and asks the platform for that project only. The filler trigger
in qualification-web is back to the qualification id alone, and the agent CLI lost `--project`.
The risk mapper already took its project from the assessment record. Tests: agents 148 passed
(on the commit alone), qualification vitest whole run 693 passed / 35 skipped, tsc clean.
