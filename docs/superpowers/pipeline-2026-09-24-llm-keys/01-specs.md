# 01 Specs: per-project LLM keys and model choice for the two agentic systems

Stage 1 of the pipeline in this folder. Read RULES.md first. Every requirement has an ID (S<section>.<n>)
and names the suite that proves it (section 8). "MUST" is a requirement; anything under "Note" is context.

## 0. What the code does today (read-only findings)

- A, card agent (`apps/qualification/services/agents`). `service.py` exposes `POST /fill/{qualification_id}`
  (202, runs `agent.fill_one` in a background task, state in memory at `GET /fill/{id}`).
  `fill_one` calls `completer(build_llm())`; `fill/llm.py::build_llm(provider, model, agent)` reads
  `BAF_LLM_PROVIDER`, `BAF_LLM_MODEL`, `BAF_LLM_BASE_URL` and the provider's own key variable from the
  environment, sets the key as a BAF property on a fresh `baf.core.agent.Agent`, builds the wrapper from the
  13-entry `PROVIDERS` table and calls `llm.initialize()`. `fill/workflow.py` (`--serve`, A2A mode) does not
  build a model per request. A does NOT know its project: qualification-web
  (`src/server/services/FillerClient.ts`, called from `src/app/p/[project]/qualify/new/actions.ts`) posts only
  the qualification id. The action knows the project: `QualificationService.createFromForm` gets
  `version.project_id` (the platform pid) back from the platform.
- B, risk mapper (`apps/control-objectives`). `llm.py` is a near copy of A's (same `PROVIDERS`,
  `build_llm(provider, model, agent)`, `completer`, plus JSON helpers `json_object`, `parse_into`).
  `server.build_app` builds ONE completer at startup from `RunConfig` (env `BAF_LLM_*`, set in compose from
  `CONTROL_OBJECTIVES_LLM_*`), hands it to `RiskMapper`, and `Projects(model="provider/model")` records that
  string on every mapping run. The agentic step is `Projects.map_risks_of(assessment_id)`, reached by
  `POST /api/projects/{id}/map` and `POST /p/{project}/projects/{id}/map`. Each assessment record carries
  `project` = the platform pid (FK to `core.project.pid`), so B knows the project at map time.
- Platform (`platform/`). FastAPI, psycopg, no ORM. Admin = realm role `admin`
  (`caller.has_role("admin")`). A project database `project_<pid without hyphens>` is made by
  `projectdb.provision`, which applies `platform/project-template/*.sql` in order and records them in
  `provision.template_migration`; `db.provision_all` re-runs provision for every project at the first query
  after start, so a new template file reaches existing project databases automatically. The platform
  (`platform_rw`) creates, therefore owns, each project database. Other roles get CONNECT and USAGE on
  named schemas only; `inspector_ro` has `pg_read_all_data` (reads every table).
- Launcher. `homepage/` is served by Caddy on `:8100`: `handle_path /api/*` strips `/api` and proxies to
  `platform:8000` behind `protect` (oauth2-proxy forward_auth, which copies the access token in);
  `/p/*` is rewritten to `project.html`; any other path is a static file behind `protect`. No CSP header is
  set on this site today; the pages use inline `<script>` blocks, property handlers set from JS
  (`el.onclick = ...`), `textContent`, and `fetch('/api/...', {credentials:'same-origin'})`.
  The Manage menu (`#manage` in `project.html`) is unhidden only when `/api/authz/projects/{slug}` says
  `admin: true`. `project.html` has an uncommitted user edit (RULES.md).
- The platform has no published port; it is on the `backend` and `frontend` networks. A and B are on
  `backend`, so they can reach `http://platform:8000` without Caddy. There is no service-to-service auth in
  the platform today (the engine's `INTERNAL_API_KEY` is a different service's secret).
- Vault pattern: `apps/connectors/aisc_connectors/vault.py`: `MultiFernet` over a comma list in
  `CONNECTOR_SECRETS_KEY` (newest first), `VaultMisconfigured` when unset or malformed, `SecretUnreadable`
  when no key decrypts, `rotate()` re-encrypts every row. Secrets come from `scripts/secrets.sh`, which
  writes `env.secrets` once and appends later-added names without replacing existing ones, then rebuilds
  `env.runtime` (the live stack's env file).
- Frozen reference: `shared/plugin-interface/.../model_listing.py::list_openai_models` (used by the engine)
  returns `{"models": [...], "error": str|None}` to the page with HTTP 200. We copy the response shape, not
  the code (it echoes the upstream body into the error, which we must not do).
- Tests: platform suite needs `PLATFORM_TEST_DATABASE_URL` (defaults to LIVE otherwise). BAF 4.5.1 is
  installed in `apps/control-objectives/.venv` (uv); A's tests `importorskip("baf")` and install from
  `requirements.txt`.

## 1. Data model (project database)

New file `platform/project-template/0005_llm.sql`. It is applied by the existing `projectdb.provision`
path; no new mechanism.

- S1.1 The file creates schema `llm` owned by the database owner (`platform_rw`), with no USAGE for any
  other role, and `REVOKE ALL ON SCHEMA llm FROM PUBLIC`.
- S1.2 Table `llm.provider`: one row per provider configured in this project.
  `provider text PRIMARY KEY` (CHECK `provider ~ '^[a-z]{2,20}$'`), `ciphertext text NULL` (Fernet token of
  the API key; NULL for a keyless provider), `base_url text NULL` (only for `ollama` and `compatible`),
  `updated_at timestamptz NOT NULL DEFAULT now()`, `updated_by text NULL` (Keycloak subject). There is no
  plaintext, masked or partial form of the key anywhere in the schema.
- S1.3 Table `llm.system_choice`: one row per agentic system that has a choice.
  `system text PRIMARY KEY` (CHECK `system IN ('card_agent','risk_mapper')`),
  `provider text NOT NULL REFERENCES llm.provider(provider) ON DELETE RESTRICT`,
  `model text NOT NULL` (CHECK `length(model) BETWEEN 1 AND 200`), `updated_at`, `updated_by` as above.
  Note: a keyless `ollama` choice therefore needs an `llm.provider` row; the API creates it (S2.7).
- S1.4 The file is idempotent (`IF NOT EXISTS` everywhere) and runs inside the migrate transaction.
- S1.5 A project database made before this file (0001-0004 applied) gets 0005 on the next `provision`
  call, which `provision_all` makes at the first query after the platform starts; a new project gets it at
  creation. Deleting a project drops its database and so its keys (no extra code).
- S1.6 `controls_rw`, `dashboard_ro`, `report_ro` cannot read `llm.*` (permission denied). `inspector_ro`
  can, through `pg_read_all_data`; it only ever sees ciphertext (accepted, see section 7).

## 2. Platform API

New modules (names binding for stage 2): `platform_service/llm_catalogue.py` (provider table and live
listers, no DB), `platform_service/llm_store.py` (per-project DB access and Fernet), routes in `app.py`.
Public paths are relative to the platform; the launcher reaches them under `/api`.

### 2.1 Access

- S2.1 Every `/projects/{slug}/llm...` route is admin-only: a caller without the `admin` role who is a
  member gets 403, a non-member gets 404 (same order as `DELETE /projects/{slug}`: `role_or_404` first),
  an unknown project gets 404. `{slug}` accepts a slug or a pid, like the other routes.
- S2.2 Unauthenticated calls get 401, as for every other route (`caller_dependency`).

### 2.2 Provider catalogue

- S2.3 `llm_catalogue.PROVIDERS` lists exactly the 13 ids of the agents' table: anthropic, compatible,
  deepseek, google, groq, meta, mistral, ollama, openai, openrouter, qwen, together, xai. Each entry has
  `label`, `key_required` (false only for `ollama`, `compatible`), `base_url_editable` (true only for
  `ollama`, `compatible`), the listing URL and lister kind (table in 2.4).
- S2.4 `GET /projects/{slug}/llm` returns `{"providers": [...], "systems": [...]}`.
  Each provider: `id, label, key_required, has_key (bool), base_url (str|null; the stored one, else the
  default for ollama, else null), base_url_editable, usable (bool), updated_at (str|null)`.
  Each system: `id` (`card_agent`, `risk_mapper`), `label` ("Card agent (Qualification)",
  "Risk mapper (Control objectives)"), `choice` (`{"provider","model"}` or null; null means the service
  uses its own environment configuration).
- S2.5 `usable` is: `has_key` for a key-required provider; always true for `ollama` (default base URL
  from env `PLATFORM_OLLAMA_BASE_URL`, default `http://host.docker.internal:11434`); true for `compatible`
  only when a `base_url` is stored.
- S2.6 No response body of any route contains a stored key, its ciphertext, or any part of either.

### 2.3 Keys and endpoints

- S2.7 `PUT /projects/{slug}/llm/providers/{provider}` with JSON `{"api_key"?: str, "base_url"?: str}`.
  `api_key` absent means "keep the stored key"; present means replace it. `base_url` is accepted only for
  `ollama` and `compatible` (422 otherwise); an empty string clears it. At least one field must be present
  (422). Response 200: the provider entry of S2.4. Unknown provider: 404.
- S2.8 Key validation, with fixed messages that never contain the value: string, 1 to 4096 characters
  after stripping surrounding whitespace, no whitespace or control characters inside. Else 422
  `"the key is not a valid API key string"`.
- S2.9 Base URL validation: `http` or `https` scheme, a host, no userinfo (`user:pass@`), no query or
  fragment, at most 500 characters. Else 422.
- S2.10 `DELETE /projects/{slug}/llm/providers/{provider}` removes the key and base URL (the row). If a
  system choice uses the provider: 409 naming the system(s), nothing removed. If nothing is stored: 404.
  Success: 204.
- S2.11 The key is encrypted with Fernet before it is written. Env `PLATFORM_SECRETS_KEY` is a comma list
  of Fernet keys, newest first (`MultiFernet`, the connectors vault pattern). Unset or malformed: key writes
  and key-dependent resolves answer 503 `"PLATFORM_SECRETS_KEY is not set"` (or "...is not a list of
  Fernet keys"); the catalogue GET still answers (has_key comes from the row).
- S2.12 A stored key that no configured key decrypts makes the models route and resolve answer with
  `"the stored key for <provider> cannot be decrypted; enter it again"` (models: in `error`, S2.15;
  resolve: 409). It is never a 500.
- S2.13 Rotation: `python -m platform_service.llm_store rotate` re-encrypts every stored key of every
  project under the newest key and prints counts only; after it, the old key can be removed from
  `PLATFORM_SECRETS_KEY` and every key still resolves.
- S2.14 Any 422 caused by request validation (including FastAPI's own `RequestValidationError`, e.g.
  `api_key` sent as a number or a non-JSON body) contains neither the submitted value nor pydantic's
  `input`/`ctx` fields. Implemented as an app-wide RequestValidationError handler that drops them.

### 2.4 Live model list

- S2.15 `GET /projects/{slug}/llm/providers/{provider}/models` returns 200
  `{"models": [str, ...], "error": null}` on success, and 200 `{"models": [], "error": "<message>"}` on
  any failure of the provider call. 409 when the provider is not usable (no key / no base URL), 404 for an
  unknown provider. Never 500 because of the provider.
- S2.16 Errors map to fixed messages: HTTP 401/403 -> `"<label> refused the key (HTTP 401)"`; other HTTP
  status -> `"<label> answered HTTP <code>"`; timeout -> `"<label> did not answer within <n> s"`;
  connection failure -> `"could not reach <label>"`; not JSON, unexpected shape, or over the size cap ->
  `"<label> did not send a model list"`. The provider's response body is never included.
- S2.17 Bounds: per-request timeout from `PLATFORM_LLM_LIST_TIMEOUT` (default 10 s; connect 5 s), at most
  10 pages, response at most 5 MB per page, at most 5000 ids kept. Redirects are NOT followed (the key must
  not travel to another host). Model ids are deduplicated and sorted; each is a string of 1 to 200 chars
  (others dropped).
- S2.18 A hosted provider's URL is a constant in `llm_catalogue` (no env override; tests monkeypatch the
  constant). Only `ollama` and `compatible` use a stored base URL.
- S2.19 Listers (from provider docs and BAF 4.5.1's wrapper base URLs; items marked * are believed
  OpenAI-compatible but not verified against live docs, see 7):

| provider | request | auth header | ids from |
|---|---|---|---|
| openai | GET https://api.openai.com/v1/models | Authorization: Bearer K | `data[].id` |
| anthropic | GET https://api.anthropic.com/v1/models?limit=1000, then `&after_id=<last_id>` while `has_more` | `x-api-key: K`, `anthropic-version: 2023-06-01` | `data[].id` |
| mistral | GET https://api.mistral.ai/v1/models | Bearer | `data[].id`, keeping only items whose `capabilities.completion_chat` is true when `capabilities` is present |
| deepseek | GET https://api.deepseek.com/models | Bearer | `data[].id` |
| google | GET https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000, then `&pageToken=<nextPageToken>` | `x-goog-api-key: K` (never `?key=`, which would put the key in logged URLs) | `models[].name` without the `models/` prefix, keeping those whose `supportedGenerationMethods` contains `generateContent` |
| groq | GET https://api.groq.com/openai/v1/models | Bearer | `data[].id` |
| meta* | GET https://api.llama.com/compat/v1/models | Bearer | `data[].id` |
| openrouter | GET https://openrouter.ai/api/v1/models | Bearer | `data[].id` (this endpoint is public: a bad key is not detected here) |
| qwen* | GET https://dashscope-intl.aliyuncs.com/compatible-mode/v1/models | Bearer | `data[].id` |
| together | GET https://api.together.xyz/v1/models | Bearer | top-level list `[].id`, keeping `type` in {chat, language} when `type` is present |
| xai | GET https://api.x.ai/v1/models | Bearer | `data[].id` |
| ollama | GET {base_url without a trailing `/v1`}/api/tags | none | `models[].name` |
| compatible | GET {base_url}/models (the stored URL already ends where BAF's OpenAI client expects, usually `/v1`) | Bearer when a key is stored | `data[].id`, or top-level list `[].id` |

### 2.5 Per-system choice

- S2.20 `PUT /projects/{slug}/llm/systems/{system}` with `{"provider": str, "model": str}`. 404 for an
  unknown system. 422 when the provider is unknown or not usable (S2.5), or the model is empty after strip,
  longer than 200 characters, or contains control characters. For `ollama` without a row, a row with
  `ciphertext NULL, base_url NULL` is created. The model does NOT have to be in the live list (decision D6).
  Response 200: `{"system","provider","model"}`.
- S2.21 `DELETE /projects/{slug}/llm/systems/{system}` removes the choice (the system goes back to its
  environment configuration). 204; 404 when there was none.

### 2.6 Internal resolve endpoint

- S2.22 `GET /internal/projects/{pid}/llm/{system}`: `{pid}` must be a pid (422 otherwise), `{system}`
  one of the two ids (404 otherwise), project unknown 404.
- S2.23 Service auth: header `X-AISC-Service-Token` compared in constant time (`hmac.compare_digest`) with
  env `PLATFORM_INTERNAL_TOKEN`. Missing or wrong: 401. Env unset or empty: 503 for every call (the route
  is closed, like the dashboard bridge without its token).
- S2.24 A request carrying `X-Forwarded-For` or `X-Forwarded-Host` (i.e. one that came through Caddy)
  gets 404, whatever its token. Caddy additionally blocks the path (S6.4).
- S2.25 Answers: no choice -> 200 `{"configured": false}`. Choice -> 200 `{"configured": true, "provider",
  "model", "base_url" (stored, or the ollama default, or null), "api_key" (decrypted, or null for a
  keyless provider)}`. Choice whose key is missing or unreadable -> 409 with a message naming the provider,
  never the key. Missing `PLATFORM_SECRETS_KEY` while a key is needed -> 503.
- S2.26 The response carries `Cache-Control: no-store`.

## 3. Shared LLM building for A and B

- S3.1 One module, `baf_llm.py`, byte-identical in both places:
  `apps/qualification/services/agents/fill/baf_llm.py` and
  `apps/control-objectives/src/aisc_control_objectives/baf_llm.py`. It imports only the standard library
  and BAF (no httpx, no package-relative imports), so the same bytes work in both.
  Decision D3: identical copy plus a parity test, not a shared package. Justification: both submodules
  build their images from their own directory and run their tests standalone; a package outside them
  would need new build contexts, mounts and a new repository, and neither module has one today. The
  parity test makes drift a failing test instead of a silent difference.
- S3.2 It defines: `PROVIDERS` and `OPTIONAL_KEY` (moved from the two `llm.py`, unchanged content);
  `SYSTEMS = ("card_agent", "risk_mapper")`; frozen dataclass `LlmConfig(provider, model, api_key=None,
  base_url=None)` whose `repr`/`str` never shows `api_key` (shows `api_key=<set>` or `None`);
  `config_from_env(env, provider=None, model=None) -> LlmConfig` (today's precedence: argument, then
  `BAF_LLM_PROVIDER`/`BAF_LLM_MODEL`, then default mistral/mistral-large-latest; key from the provider's
  env var; `BAF_LLM_BASE_URL`); `ResolveError(RuntimeError)`;
  `resolve(project, system, env=os.environ, timeout=None) -> LlmConfig | None`;
  `config_for(project, system, env=os.environ, fallback=None) -> LlmConfig`;
  `build_llm(config, agent=None, agent_name="llm")`; `completer(llm)`.
- S3.3 `build_llm(config)` keeps today's behaviour for the same inputs: unknown provider -> ValueError
  listing providers; key-required provider without key -> ValueError naming the env var; `ollama` with a
  base URL sets `nlp.OLLAMA_BASE_URL`; `compatible` needs a base URL and passes `base_url` and
  `api_key or "not-needed"` as parameters; `llm.initialize()` is called. It builds on a NEW BAF `Agent`
  when none is given (a key set for one project can never be read by a build for another) and never writes
  to `os.environ`.
- S3.4 `resolve`: returns None (caller uses env) when `project` is empty, or `PLATFORM_URL` or
  `PLATFORM_INTERNAL_TOKEN` is unset. Otherwise GETs `{PLATFORM_URL}/internal/projects/{project}/llm/{system}`
  with the token header and a timeout (`LLM_RESOLVE_TIMEOUT`, default 5 s). 200 configured false -> None;
  200 configured true -> LlmConfig from the body. Anything else (404, 409, 401, 503, timeout, connection
  error, bad JSON) -> `ResolveError` with a message naming the project and the platform's `detail` when
  there is one; never the token or a key. Decision D4: fail closed, no env fallback once a project is known
  and the platform is configured, so a project that chose a local model never silently goes to a hosted
  one.
- S3.5 `config_for(project, system, env, fallback)` = `resolve(...)` or `fallback` or `config_from_env(env)`.
- S3.6 The existing module APIs stay: A's `fill/llm.py::build_llm(provider=None, model=None, agent=None)`
  and `completer`, B's `llm.py::build_llm(provider, model, agent=None)`, `completer`, `json_object`,
  `parse_into`, `PROVIDERS`, `OPTIONAL_KEY`, `DEFAULT_*` keep working (re-exported or thin wrappers over
  `baf_llm`), so today's tests pass unchanged.
- S3.7 A obtains its project from the request: `POST /fill/{qualification_id}?project=<pid>`. `project`
  is optional (absent = env config, as today); present and not a UUID -> 422. `fill_one(qualification_id,
  dry_run=False, project=None)` builds its completer from `config_for(project, "card_agent")`. The run
  state records `project` and the result records `"model": "<provider>/<model>"`. A `ResolveError` or a
  build error fails the run (`state: failed`, `error` = the message) without a key in it.
- S3.8 qualification-web passes the pid: `FillerClient.request(qualificationId, projectId?)` posts to
  `${AGENT_SERVICE_URL}/fill/${id}?project=${encodeURIComponent(projectId)}` when given;
  `createFromForm` returns `{id, projectId}` (from `version.project_id`) and the action passes it. The
  other FillerClient behaviours (never throws, false on refusal, no call without a URL) stay.
- S3.9 B obtains its project from the assessment record (`record.project`, a pid). `Projects` takes an
  optional `mapper_for(project_pid) -> (Mapper, model_label)`; when given, `map_risks_of` uses it for that
  record and stores `model_label` (`"<provider>/<model>"` of the config actually used) on the mapping run;
  when not given, today's fixed mapper and label are used. `server.build_app` wires `mapper_for` with
  `config_for(pid, "risk_mapper", fallback=<the startup RunConfig as LlmConfig>)` and still builds the env
  completer at startup as today (startup behaviour unchanged, decision D8).
- S3.10 In B, a `ResolveError` or build error during a map makes `POST /api/projects/{id}/map` answer 502
  `{"detail": <message>}` and the form route answer 502 plain text; nothing is saved.
- S3.11 A resolved config reaches the model: with `compatible` pointed at a fake OpenAI-compatible server,
  a `predict` sends `Authorization: Bearer <the resolved key>` and `model: <the resolved model>`; the
  environment's key is not sent.

## 4. The page

- S4.1 New static page `homepage/llm.html`, opened as `/llm.html?project=<slug>`. Same look as
  `project.html` (its CSS variables, fonts, header and session line), one inline `<script>`, no framework,
  no external script.
- S4.2 The Manage menu of `project.html` gets a link "Models and API keys" (`id="llm-settings"`), its
  `href` set to `/llm.html?project=<slug>` inside the existing admin-only block. Note: `project.html` has
  an uncommitted user edit; stage 4 edits on top of it and does NOT commit that file (RULES.md).
- S4.3 On load the page reads `/api/projects/{slug}` and `/api/authz/projects/{slug}`; if not admin it
  shows only "Only a platform admin manages models and keys." and makes no llm call.
- S4.4 Providers section: one row per catalogue provider with label, status ("key stored" with date,
  "no key", or "no key needed"), and for key-required providers a key form: `<input type="password"
  autocomplete="new-password">`, never prefilled, cleared after every submit, Save and (when stored)
  Remove. For `ollama`/`compatible` a base URL text field (prefilled with the stored or default URL, which
  is not secret) and an optional key field for `compatible`.
- S4.5 Systems section: for each system, a provider `<select>` offering only `usable` providers plus
  "Service default (environment)"; choosing a provider loads its models live (S2.15) into a model
  `<select>`; while loading it says so; on `error` it shows the message and offers a free-text model field
  instead. Save calls S2.20; "Service default" calls S2.21. The current choice is preselected.
- S4.6 Every refusal or error is shown next to the control that caused it, from the response's `detail`
  or `error`; a failed fetch shows "The platform is not answering. Nothing was saved."
- S4.7 CSP-safe and injection-safe: no inline event-handler attributes (`on...=` in markup), listeners via
  `addEventListener`, all API text (provider labels, model ids, errors) inserted with `textContent` or
  `option.value/text`, never `innerHTML`; only same-origin `/api/...` requests with
  `credentials: 'same-origin'`; writes send `Content-Type: application/json`.
- S4.8 The page never reads a key back: no script assigns anything but `''` to a key input's value, and
  no response field holds a key (S2.6).

## 5. Security requirements (collected; each is also proven where listed in 8)

- S5.1 Write-only: no route (public or page-facing) returns a key or ciphertext (S2.6); the internal
  route is the only one that returns a decrypted key (S2.25).
- S5.2 At rest: only Fernet ciphertext is stored; the plaintext is not a substring of any stored column.
- S5.3 Never logged: during PUT key, models listing (success and every error path), resolve, and a build in
  A and B, captured logs at DEBUG (platform, httpx, urllib, BAF) contain no key; error messages and A's
  run `error` field contain no key; `LlmConfig` repr hides it.
- S5.4 Admin-only (S2.1) and cross-project isolation: a key stored for project P is not `has_key` in
  project Q, Q's models route answers 409, and resolve for Q never returns P's key or choice.
- S5.5 The internal route is unreachable from outside: token required (S2.23), forwarded requests refused
  (S2.24), Caddy blocks `/api/internal/*` on the launcher site (S6.4), the platform publishes no port.
- S5.6 A stored hosted-provider key is only ever sent to that provider's constant URL (S2.18), and
  redirects are not followed (S2.17).
- S5.7 CSRF: all writes are PUT/DELETE with a JSON body; the platform has no CORS middleware, so a
  cross-site page cannot make them. A PUT with a non-JSON content type is refused (4xx) and changes nothing.
- S5.8 SSRF bound: the only admin-controlled URLs the platform fetches are the `ollama`/`compatible` base
  URLs, validated by S2.9, fetched with the same bounds and no redirects, and their bodies are never
  reflected (S2.16).

## 6. Compose, env and proxy wiring (written by stage 4, NEVER applied to the running stack)

- S6.1 `docker-compose.development.yml`, service `platform`: `PLATFORM_SECRETS_KEY:
  ${PLATFORM_SECRETS_KEY:?run scripts/secrets.sh first}`, `PLATFORM_INTERNAL_TOKEN:
  ${PLATFORM_INTERNAL_TOKEN:?run scripts/secrets.sh first}`, `PLATFORM_OLLAMA_BASE_URL:
  ${PLATFORM_OLLAMA_BASE_URL:-http://host.docker.internal:11434}` (it already has `host-gateway`).
- S6.2 Service `qualification-agents`: `PLATFORM_URL: http://platform:8000`, `PLATFORM_INTERNAL_TOKEN`
  as above, `extra_hosts: host.docker.internal:host-gateway` (for an ollama choice). Service
  `control-objectives`: `PLATFORM_INTERNAL_TOKEN` as above (it already has `PLATFORM_URL` and
  host-gateway). No network changes: all three are on `backend`.
- S6.3 `scripts/secrets.sh` writes `PLATFORM_INTERNAL_TOKEN` (hex, `rand`) and `PLATFORM_SECRETS_KEY`
  (a Fernet key: `openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n'`, 44 chars with padding) for a new
  install, and appends either one to an existing `env.secrets` only when missing, never replacing a value.
  Tests run it on a scratch copy only: running it in the repo rewrites `env.runtime`, the live stack's env.
- S6.4 `Caddyfile`, launcher site (`{$CADDY_DOMAIN}:{$HOMEPAGE_PORT}`): inside the `route`, before
  `handle_path /api/*`, `handle /api/internal/* { respond 404 }`.
- S6.5 `platform/pyproject.toml` runtime dependencies gain `httpx>=0.27` and `cryptography>=43`
  (uv.lock updated). A's `requirements.txt` and B's `pyproject.toml` need nothing new (stdlib only).
- S6.6 `env.development`/`env.staging` get a comment line saying the two secrets come from
  `env.secrets`, as for `INTERNAL_API_KEY`.
- S6.7 `docker compose config` on copies of the compose files (existing `scripts/tests/test_compose.py`
  fixture) is valid and shows the variables of S6.1 and S6.2.

## 7. Out of scope, decisions, open questions, risks

Out of scope: the LiteLLM sidecar `qualification-llm` and other qualification LLM features, the
catalogue's LLM, the engine (frozen), per-user keys, more than one key per provider per project, testing a
key on save (listing does that), usage or cost tracking, caching model lists, BAF's A2A `--serve` mode
(stays env-configured), deploying anything to the live stack.

Decisions made instead of asking:
- D1 System ids `card_agent` (A) and `risk_mapper` (B).
- D2 The base URL belongs to the provider row, not the system choice: the live listing needs it, and a
  `compatible` key belongs to that endpoint.
- D3 Shared code is an identical file with a parity test (S3.1).
- D4 Fail closed once a project is known and the platform is configured (S3.4).
- D5 Models route answers 200 with `error`, the engine's shape, so the page has one path (S2.15).
- D6 The chosen model need not be in the live list: listings fail or omit models (openrouter, compatible)
  and an outage must not block saving; the page still steers to the list.
- D7 Deleting a key that a system uses is refused (409) instead of leaving a broken choice.
- D8 B still builds its env completer at startup (behaviour and tests unchanged); per-project configs are
  built per map call. A builds per run, as today.
- D9 Secrets `PLATFORM_SECRETS_KEY` and `PLATFORM_INTERNAL_TOKEN` are required (`:?`) in compose, like
  `REPORT_SERVICE_TOKEN`; the user must run `scripts/secrets.sh` (which only appends) before the next `up`.
- D10 Resolve per run or per map call, no cache: a changed key or choice applies to the next run.
- D11 The agent trusts the `project` it is given by qualification-web on the internal network (no
  published port). Someone already inside `backend` could make A spend another project's key without ever
  seeing it; accepted and recorded.

Risks:
- R1 Listing endpoints marked * (meta, qwen) are unverified; Google model ids are used without the
  `models/` prefix through BAF's OpenAI-compatible Gemini endpoint, believed accepted but not verified.
  Tests use fakes only, so a live check after deployment is needed.
- R2 BAF may log properties (and so a key) at DEBUG; S5.3 tests the build path, and if BAF leaks, stage 4
  must lower BAF's logger level around the build rather than patch BAF.
- R3 Pre-existing and out of scope: A reads and publishes through qualification-web's
  `/api/qualifications/{id}/extracted` without a caller token, which `qualificationForCaller` answers 404;
  A may fail end to end regardless of this feature.
- R4 `inspector_ro` (admin pgAdmin) can read the ciphertext table (S1.6).
- R5 Stage 4's `project.html` link cannot be committed (user's uncommitted edit); its test passes on the
  working tree only.

## 8. Test map and how tests run

Throwaway Postgres (never the live one), as in pipeline-2026-09-23:

```
NAME=aisc-t-$(openssl rand -hex 4); PW=$(openssl rand -hex 12)
PORT=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')
docker run --rm -d --name $NAME -p 127.0.0.1:$PORT:5432 -e POSTGRES_USER=aisc-postgres-user \
  -e POSTGRES_PASSWORD=$PW -e POSTGRES_DB=platform postgres:14-alpine
docker exec -i $NAME psql -U aisc-postgres-user -d platform -v ON_ERROR_STOP=1 < init/platform-db.sql
docker exec -i $NAME psql -U aisc-postgres-user -d platform -v ON_ERROR_STOP=1 < init/project-databases.sql
[ "$PORT" != 5432 ] || exit 1      # and docker rm -f $NAME afterwards
```

Fake providers and fake platform: a `http.server.ThreadingHTTPServer` on `127.0.0.1:0` in a thread,
per test module, recording requests (path, headers) and serving canned bodies; a "slow" handler sleeps
past a timeout set low by monkeypatch; "down" is a closed port. Catalogue URL constants and
`PLATFORM_URL` are monkeypatched to it. No test reaches the internet or uses a real key; test keys are
strings like `sk-test-<uuid>` so a leak is greppable.

| suite and command | proves |
|---|---|
| platform: from `platform/`, `PLATFORM_TEST_DATABASE_URL=postgresql://platform_rw:platform_rw@127.0.0.1:$PORT/platform PLATFORM_TEST_SUPERUSER_URL=postgresql://aisc-postgres-user:$PW@127.0.0.1:$PORT/platform uv run --extra dev pytest -q -p no:cacheprovider` | `tests/test_llm_catalogue.py` (no DB, fake HTTP): S2.3, S2.15-S2.19, S5.3 (listing), S5.6, S5.8. `tests/test_llm_store.py` (DB): S1.1-S1.6, S2.11-S2.13, S5.2. `tests/test_api_llm.py` (DB + TestClient, `client`/`as_user` fixtures, admin via `roles=("admin",)`): S2.1, S2.2, S2.4-S2.10, S2.14, S2.20-S2.26, S5.1, S5.3 (API), S5.4, S5.5 (token, forwarded), S5.7 |
| A: from `apps/qualification/services/agents`, `uv run --no-project --with-requirements requirements.txt --with pytest --with httpx python -m pytest -q -p no:cacheprovider` (or the python:3.12-slim `docker run` form) | `tests/test_baf_llm.py`: S3.2-S3.5, S3.11, S5.3 (build, repr). `tests/test_llm.py` unchanged: S3.6. `tests/test_service.py` + `tests/test_project_llm.py` (fake platform, fake OpenAI-compatible server, `clients` monkeypatched): S3.7 |
| B: from `apps/control-objectives`, `CONTROL_OBJECTIVES_TEST_DATABASE_URL=postgresql+psycopg://aisc-postgres-user:$PW@127.0.0.1:$PORT/control_objectives_test uv run --extra dev pytest -q -p no:cacheprovider` | `tests/test_baf_llm.py` (same cases as A's, importing B's copy): S3.2-S3.5, S3.11. existing `test_llm.py`, `test_server.py`, `test_config.py` unchanged: S3.6, D8. `tests/test_project_llm.py`: S3.9, S3.10 |
| qualification-web: from `apps/qualification`, `npx vitest run test/unit/FillerTrigger.test.ts test/unit/cardVersionsInCoreSystem.test.ts && npx tsc --noEmit` | S3.8 |
| top-level: from the repo root, `uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests/test_llm_keys.py scripts/tests/test_compose.py` | `test_llm_keys.py`: S3.1 parity (both `baf_llm.py` byte-identical; their `PROVIDERS` keys, read with `ast`, equal `llm_catalogue.PROVIDERS` ids), S4.1-S4.8 static checks on `homepage/llm.html` and the Manage link in `project.html` (regex, as `test_report_stack.py` does), S6.3 (secrets.sh on a scratch copy: both names written, the Fernet key decodes to 32 bytes, a second run keeps both values), S6.4 (Caddyfile: the block exists in the launcher site and precedes `handle_path /api/*`), S6.5, S6.6. `test_compose.py` additions: S6.1, S6.2, S6.7 |
| after a deployment only, by the user (not run by this pipeline): `scripts/verify-llm-keys.sh`, read-only curl checks: `:8100/api/internal/...` answers 404, a non-admin gets 403 on `/api/projects/<slug>/llm` | S5.5 on the live stack |
