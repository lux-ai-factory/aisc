# WP2 notes: qualification-web writes, the card agent's token, service tokens per caller edge

Date 2026-09-25. Branch feat/unified-modules in every repo, local commits only, nothing pushed,
nothing deployed, the running stack not touched. The top-level submodule pointers are NOT bumped
(the orchestrator does it).

## Commits

| repo | commit | what |
|---|---|---|
| apps/qualification | `8f0ab50` | F6, F7, F9 in qualification-web; the door on agents, ontology, prefill, llm, qualification-pdf; every caller sends its token |
| apps/controls | `b3b4a57` | the door on controls-pdf; the report route sends its token |
| top-level | see `git log` (this file's commit) | compose wiring, secrets.sh, env comments, scripts/tests/test_service_tokens.py, these notes |

The qualification commit was built as HEAD plus my patch only: the index was clean, the patch was
applied with `git apply --cached`, the staged diff was compared byte for byte with the patch, and
committed from the index. The other session's uncommitted work was not reverted, stashed or
committed; four files carry both (services/ontology/app.py, services/prefill/app.py,
src/app/api/qualifications/[id]/extracted/route.ts, src/server/services/PrefillClient.ts) and their
working copies now hold their hunks on top of mine. The commit was then checked alone in a clean
detached worktree (node_modules symlinked): vitest, tsc and every Python suite, counts below.

## Changes

qualification-web
- `PUT /api/qualifications/{id}/extracted` needs an editor, owner or platform admin (the platform
  answers an admin as owner) of the qualification's own project: viewer 403, stranger or missing 404
  (`qualificationForWriter`, src/server/access/qualificationAccess.ts). F6.
- Server actions read the project from the object they act on and ignore the browser's value
  (argument renamed `_clientProject`, signatures unchanged so the client components are untouched):
  `patchOntologyNode`, `resetOntology` (write), `loadOntology` (read, `qualificationForCaller`),
  `linkComponent`, `unlinkComponent` (write). `submitQualification` has no object yet, so it checks
  write access to the project it is bound to (`projectForWriter`; a silent platform keeps its old
  message "The platform did not answer; nothing was saved"). F7.
- Reviewed and left alone: `readDocument`, `readFormFile` (no project); the other session's
  `forms/actions.ts` (untracked, theirs): forms are a global library, the project there only builds
  the redirect, and `setDefaultForm` already requires a platform admin.
- The card agent's token on GET and PUT `/extracted` only (`QUALIFICATION_AGENTS_TO_WEB_TOKEN`, header
  `X-AISC-Service-Token`, sha256 digests compared with `timingSafeEqual`, src/server/access/serviceToken.ts).
  No header: the user rules as before. Header and no token set here: 503. Wrong: 401. Right: the
  qualification must exist (404 otherwise) and its own project is used. The latest-version check for
  the agent asks the database (`qualification.card_is_latest`, the rule the only-latest triggers
  enforce), because the platform's `/system-versions/latest` needs a user token the agent does not
  have. Decision recorded here: that is the same rule, not a weaker one. F9.
- Clients send their edge's token through one helper (`serviceTokenHeaders`, src/server/services/http.ts):
  FillerClient and the `/fill` proxy route, OntologyClient (build, vocabularies), PrefillClient,
  SystemCardRendererClient.

Sidecars
- One ASGI middleware, `service_token.py`, the same bytes in agents, ontology, prefill, llm,
  system_card_renderer and controls pdf_renderer (each image is built from its own directory, so it is
  copied; scripts/tests checks the copies are identical and that each Dockerfile copies it; prefill's
  Dockerfile gained it on its COPY line). `/health` open; every other path, `/docs` and
  `/openapi.json` included, needs one of the service's callers' tokens: 401 without or wrong, 503 when
  one of its tokens is unset or two are equal. All tokens are compared (`hmac.compare_digest`), not
  only until the first match. F8, F11.
- The agent sends `QUALIFICATION_AGENTS_TO_WEB_TOKEN` to the app and
  `QUALIFICATION_AGENTS_TO_ONTOLOGY_TOKEN` to the ontology service (fill/clients.py). Its platform
  token (`PLATFORM_INTERNAL_TOKEN` = `PLATFORM_CARD_AGENT_TOKEN`) is untouched.
- controls-web's report route sends `CONTROLS_WEB_TO_PDF_TOKEN`.

Top-level
- scripts/secrets.sh: the eight tokens in the new-install heredoc (22 secrets) and in an append-only
  loop for existing installs (never replaces a value; `--rotate` makes new ones like every other
  token there).
- docker-compose.development.yml: each token as `${NAME:?run scripts/secrets.sh first}`, on exactly
  its two services.
- env.development, env.staging: one comment line per token, saying it comes from env.secrets.

Tests changed rather than added (design changes the behaviour they pin): onlyLatestCardChanges.test.ts
gains `qualificationForWriter` in its access mock, because the writes it pins now ask for write
access. The Python suites' endpoint tests are unchanged: each service's tests/conftest.py (new, or
appended to ontology's) sets the tokens and adds a caller's header on `TestClient.request`, and the
door is tested in test_service_token.py where that is switched off (`DOOR_TEST = True`).

## Token matrix

| token | holders (callee, caller) | opens |
|---|---|---|
| `QUALIFICATION_AGENTS_TO_WEB_TOKEN` | qualification-web, qualification-agents | `GET` and `PUT /qualification/api/qualifications/{id}/extracted` only |
| `QUALIFICATION_WEB_TO_AGENTS_TOKEN` | qualification-agents, qualification-web | agents: `POST /fill/{id}`, `GET /fill/{id}`, `/docs`, `/openapi.json` |
| `QUALIFICATION_WEB_TO_ONTOLOGY_TOKEN` | qualification-ontology, qualification-web | ontology: `POST /build`, `GET /vocabularies`, docs |
| `QUALIFICATION_AGENTS_TO_ONTOLOGY_TOKEN` | qualification-ontology, qualification-agents | same routes as the line above |
| `QUALIFICATION_WEB_TO_PREFILL_TOKEN` | qualification-prefill, qualification-web | prefill: `POST /prefill`, `POST /forms/import` (and whatever the other session adds), docs |
| `QUALIFICATION_WEB_TO_LLM_TOKEN` | qualification-llm, qualification-web | llm: `POST /generate`, docs |
| `QUALIFICATION_WEB_TO_PDF_TOKEN` | qualification-pdf, qualification-web | qualification-pdf: `POST /render/pdf`, `POST /render/html`, docs |
| `CONTROLS_WEB_TO_PDF_TOKEN` | controls-pdf, controls-web | controls-pdf: `POST /render/pdf`, `POST /render/html`, docs |

Header everywhere: `X-AISC-Service-Token` (the platform's internal route uses the same one). Unchanged:
`PLATFORM_CARD_AGENT_TOKEN` (platform, qualification-agents as `PLATFORM_INTERNAL_TOKEN`),
`PLATFORM_RISK_MAPPER_TOKEN` (platform, control-objectives).

## Test counts (red, then green)

| suite | before (HEAD e9d0693 / ee7625b) | red (new tests, old code) | green (commit alone, clean worktree) |
|---|---|---|---|
| qualification vitest, whole run | 418 passed, 20 skipped, 1 failed (see note a) | new files: 30 failed, 3 passed | 453 passed, 20 skipped (473), 0 failed |
| qualification tsc --noEmit | clean | clean | clean |
| agents pytest (scratch dir recipe) | 148 passed | 11 failed, 153 passed | 164 passed |
| ontology pytest | 182 passed, 3 failed (note b) | 15 failed, 191 passed | 203 passed, 3 failed (the same 3) |
| prefill pytest | 73 passed | 10 failed, 78 passed | 88 passed |
| qualification-pdf (system_card_renderer) pytest | 9 passed | 10 failed, 14 passed | 24 passed |
| llm pytest (new suite) | none | 8 failed, 4 passed | 12 passed |
| controls vitest, whole run | 127 passed, 64 skipped | new file: 1 failed, 1 passed | 129 passed, 64 skipped |
| controls tsc --noEmit | clean | clean | clean |
| controls-pdf pytest (new suite) | none | 10 failed, 5 passed | 15 passed |
| top-level test_service_tokens.py (new) | none | 17 failed, 6 passed | 23 passed |
| top-level test_compose.py + test_llm_keys.py | 27 passed | | 27 passed (50 with the new file) |
| top-level scripts/tests, whole (with psycopg) | not run separately (note c) | | 200 passed, 25 failed (note c) |

Notes.
a. In a detached worktree with node_modules symlinked, secrets.test.ts fails with EISDIR on the
   symlink (it is not matched by the `node_modules/` ignore). Run with a core.excludesFile holding
   `node_modules` it passes; the counts in the green column are from that run (3 of 3).
b. test_build.py, test_example_mcas.py, test_roundtrip.py "nineteen properties" fail at HEAD already,
   unrelated to this work.
c. The 25 failures are in suites that none of this work touches: test_guard_frozen and
   test_report_stack's final guard (G1 engine schema and G4 backend files differ from e34fca3, which
   is the engine's own work in progress), test_throwaway_rows and test_db_consistency (JSONDecodeError
   reading the throwaway container's output), test_report_grants (role checks on a throwaway DB),
   test_report_stack's init-file and launcher-card checks (init/*.sql, homepage/project.html, the
   latter holding the user's uncommitted edit), test_pipeline_chain. Every test that reads the compose
   file, secrets.sh or the env files passes (test_compose, test_llm_keys, test_service_tokens and the
   compose checks of test_report_stack). No baseline run without my edits was made, since that would
   mean reverting files in the shared tree; the attribution is by what each failing test reads.

In the shared working tree (other session's work plus mine) the whole vitest run is 3 failed, 907
passed: FormService R61 (theirs, in progress), and serviceTokens.test.ts's guard "every caller of a
sidecar sends that sidecar's token", which flags their untracked FormImportClient.ts and
FormExportClient.ts (see open items). Their Python suites with my conftests: agents 168, ontology 261
(+ the 3 pre-existing), prefill 298, renderer 50, llm 12, all passing.

## Live probes for after the deploy (the orchestrator runs them)

The images of qualification-web, -agents, -ontology, -prefill, -llm, -pdf, controls-web and
controls-pdf must be rebuilt, and `scripts/secrets.sh` run first (it appends the eight tokens to
env.secrets and rewrites env.runtime). No probe prints a token: each reads it from the container's own
environment.

```bash
# 1. From the plugin-running container, with no token: /health 200, everything else 401.
docker exec aisc-eval-worker python - <<'PY'
import urllib.request as u, urllib.error as e
for url in ["http://qualification-agents:8012/health", "http://qualification-agents:8012/fill/x",
            "http://qualification-agents:8012/openapi.json",
            "http://qualification-ontology:8011/health", "http://qualification-ontology:8011/vocabularies",
            "http://qualification-prefill:8012/health", "http://qualification-prefill:8012/docs",
            "http://qualification-llm:4000/health", "http://qualification-llm:4000/openapi.json",
            "http://qualification-pdf:8005/health", "http://qualification-pdf:8005/openapi.json",
            "http://controls-pdf:8005/health", "http://controls-pdf:8005/openapi.json",
            "http://qualification-web:3000/qualification/api/qualifications/cmue7pq23000mpv7zew2fghpg/extracted"]:
    try: print(u.urlopen(url, timeout=5).status, url)
    except e.HTTPError as x: print(x.code, url)
PY
# expected: 200 on the six /health, 401 on the rest, 404 on the last (no user, no agent token)

# 2. A wrong token is 401 (from the same container)
docker exec aisc-eval-worker python -c 'import urllib.request as u,urllib.error as e
try: u.urlopen(u.Request("http://qualification-ontology:8011/vocabularies", headers={"X-AISC-Service-Token": "wrong"}), timeout=5)
except e.HTTPError as x: print(x.code)'
# expected: 401

# 3. The card agent reads its qualification with its own token (F9: was 404)
docker exec qualification-agents python -c 'import os,urllib.request as u
r=u.Request("http://qualification-web:3000/qualification/api/qualifications/cmue7pq23000mpv7zew2fghpg/extracted",
            headers={"X-AISC-Service-Token": os.environ["QUALIFICATION_AGENTS_TO_WEB_TOKEN"]})
print(u.urlopen(r, timeout=10).status)'
# expected: 200.  The agent's ontology token on the web route is 401:
docker exec qualification-agents python -c 'import os,urllib.request as u,urllib.error as e
r=u.Request("http://qualification-web:3000/qualification/api/qualifications/cmue7pq23000mpv7zew2fghpg/extracted",
            headers={"X-AISC-Service-Token": os.environ["QUALIFICATION_AGENTS_TO_ONTOLOGY_TOKEN"]})
try: u.urlopen(r, timeout=10)
except e.HTTPError as x: print(x.code)'
# expected: 401

# 4. The agent reaches the ontology service with its own token
docker exec qualification-agents python -c 'import os,urllib.request as u
r=u.Request("http://qualification-ontology:8011/vocabularies", headers={"X-AISC-Service-Token": os.environ["QUALIFICATION_AGENTS_TO_ONTOLOGY_TOKEN"]})
print(u.urlopen(r, timeout=10).status)'
# expected: 200

# 5. qualification-web reaches each sidecar with its own token
docker exec qualification-web node -e '
const t = process.env, h = (n) => ({ headers: { "X-AISC-Service-Token": t[n] } });
Promise.all([
  fetch("http://qualification-agents:8012/openapi.json", h("QUALIFICATION_WEB_TO_AGENTS_TOKEN")),
  fetch("http://qualification-ontology:8011/vocabularies", h("QUALIFICATION_WEB_TO_ONTOLOGY_TOKEN")),
  fetch("http://qualification-prefill:8012/openapi.json", h("QUALIFICATION_WEB_TO_PREFILL_TOKEN")),
  fetch("http://qualification-llm:4000/openapi.json", h("QUALIFICATION_WEB_TO_LLM_TOKEN")),
  fetch("http://qualification-pdf:8005/openapi.json", h("QUALIFICATION_WEB_TO_PDF_TOKEN")),
  fetch("http://qualification-pdf:8005/openapi.json", h("QUALIFICATION_WEB_TO_ONTOLOGY_TOKEN")),
]).then((rs) => console.log(rs.map((r) => r.status).join(" ")));'
# expected: 200 200 200 200 200 401  (the last: another edge's token)

# 6. controls-web reaches controls-pdf with its token
docker exec controls-web node -e 'fetch("http://controls-pdf:8005/openapi.json",
  { headers: { "X-AISC-Service-Token": process.env.CONTROLS_WEB_TO_PDF_TOKEN } }).then((r) => console.log(r.status))'
# expected: 200

# 7. End to end in the browser: save a card (the agent run publishes its draft; GET
#    /qualification/api/qualifications/<id>/fill shows state "done", not a 404 in "error"),
#    download the AI-card PDF, open a checklist submission's report PDF.
```

## Open items

1. The other session's untracked `src/server/services/FormImportClient.ts` and
   `FormExportClient.ts` call qualification-prefill (`/forms/import`, `/forms/export`) without the
   token, so after the deploy they will get 401. Not edited here (their files, being written as this
   ran). Fix: add `headers: serviceTokenHeaders(process.env.QUALIFICATION_WEB_TO_PREFILL_TOKEN)` (or a
   constructor default like PrefillClient's). The guard test in serviceTokens.test.ts fails until
   they do, which is on purpose.
2. qualification-llm has no caller in code today (`LLM_SERVICE_URL` is set on qualification-web and
   the agents but read by nothing; the agents' `BAF_LLM_BASE_URL` points at it, and the wrapper is not
   an ollama or OpenAI-compatible endpoint, so BAF cannot have used it). Its token is given to
   qualification-web as the intended caller. If BAF is ever pointed at it, that edge needs its own
   token and BAF a way to send a header.
3. The submodules' standalone compose files (apps/qualification/docker-compose*.yml,
   apps/controls/docker-compose*.yml) do not set the tokens, so their sidecars now answer 503 (fail
   closed). The platform stack is the supported one; set the variables there if the standalone stacks
   are still used.
4. `/docs` and `/openapi.json` of the sidecars are behind the door now (F14 for these six services).
5. Tokens are not bound to a caller identity beyond possession; a container that holds one token (for
   example qualification-web holds five) can call each of those services. That is the per-edge
   design; the backend network still cannot reach a sidecar without one.
