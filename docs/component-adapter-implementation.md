# Components, adapters and the run door — implementation plan

**Status:** draft, for review. Nothing here is implemented yet.
**Decision:** [ADR 0009](adr/0009-components-adapters-and-the-run-door.md) (proposed).
**Design and decision log:** [`component-adapter-plan.md`](component-adapter-plan.md) (D-1 to D-20).
**Branches:** `integration/int-01-frozen-unified-app` in every submodule. The parent bumps the gitlinks.

This is integration scaffolding, like `backend-app-split-plan.md`. When the work lands, fold what
survives into `ARCHITECTURE.md`, the plugin developer guide and the migration guide, then delete this
file.

---

## 0. Ground rules

- **Port the need, not the code** (AGENTS). The `poc/input-adapater-chain` branches are a reference for
  discovery, install and selection. Their ordered chain, `InputAdapter`/`EvaluationInputAdapter` tables
  and advisory glob hints are **not** ported (D-9).
- **No new service, container, datastore or top-level dependency** (I8, ADR 0009 consequences).
- **Core only** (I10). Components, adapters, plugins, evaluation and runs are core. The qualification
  card agent and the control-objectives risk mapper are optional domains that *call* the AI assistant
  resolver. They keep working through its signature, and core never imports them.
- **Every phase ends green:**
  - backend: `manage.py check`, `makemigrations --check`, and the full test suite (except the known
    compose failure);
  - the tests of each touched package;
  - the architecture guards (`uv run --no-project --with pytest python -m pytest tests/architecture -q`);
  - webapp `npm test` and `npm run build` when the webapp changes.
- **Contract first.** `aisc-plugin-interface` is published. Its new surface (phase 1) is reviewed and
  released before backend, eval or webapp depend on it. Local work uses the path dependency, as today.
- **Existing plugins must not break** (D-15, D-16). The example plugin and one catalogue LLM plugin are
  run end to end after phase 4.

## 1. Target shape (summary)

```
AIComponent (project, system?, kind, protocol|format, url, adapter, adapter_version, config, secret)
  file:      dataset | model | datashape  -- bytes / derived JSON (unchanged)
  reference: resource                     -- a string the plugin resolves (unchanged, D-20)
  endpoint:  protocol openai-chat | agent | oip-v2 | rest | url  -- reached via an endpoint adapter

Plugin slot  @evaluation_input(name, accepts=[...], role=subject|input|instrument,
                               adapter=?, adapter_required=?, env={...}?)
EvaluationInput (evaluation_plugin, slot name, component, adapter, adapter_version, adapter_config,
                 provenance{url, adapter, version, config_hash})

aisc_plugin_interface.adapters
  registry   formats + value types + protocols, compatibility rule
  data       csv tsv parquet jsonl json onnx  (readers -> table | records | json | onnx-session | file)
  endpoint   openai (passthrough)  oip (passthrough)  a2a (agent -> turn)  rest (rest -> turn)
  faces      openai-chat  oip-v2  agent  (+ ollama: candidate)
  presets    llm  agent  model-api  dataset  model-file

eval worker per run:  door subprocess on 127.0.0.1:<port>, holds secrets, one route per endpoint slot
plugin gets:          LLMConfig{endpoint_url=door URL, model, secret_key -> run token}  (+ declared env)
```

Removed: `Connection`, `Helper`, `RunBinding`, `ConnectionKind`, `HelperRole`, `aisc_backend/adapters/`,
`routers/connection.py`, `routers/helper.py`, `ConnectionsPage`, `HelpersPage`, `lib/connections.ts`,
`lib/helpers.ts`, and the `llm` component type (migrated).
Kept: `AllowedHost` and its router/page section, the secret store, `services/allowed_hosts.py`, and
`local_target.py` (the test mock).

---

## Phase 1 — the adapter contract in `aisc-plugin-interface` (0.5.0)

**Repo:** `shared/plugin-interface`. Additive only: every existing import keeps working.

1. **`aisc_plugin_interface/adapters/`**
   - `registry.py`: the vocabulary as **registered strings** (D-12).
     - Formats: `csv`, `tsv`, `parquet`, `jsonl`, `json`, `onnx`.
     - Value types: `table`, `records`, `json`, `onnx-session`, `file`.
     - Protocols: `openai-chat`, `agent`, `oip-v2`, `rest`, `url`.
     - `register_format()`, `register_protocol()`, and `ADAPTER_ABI_VERSION = "1"`.
   - `base.py`:
     - `DataAdapter`: `id`, `version`, `reads: list[format]`, `produces: list[value type]`, a pydantic
       `Config`, and `load(path, config, produce) -> value`.
     - `EndpointAdapter`: `id`, `version`, `speaks: protocol` (target side), `serves: list[protocol]`
       (the faces it can back), `capabilities`, a pydantic `Config`, `max_concurrency`, and
       `open(binding) / call(session, turn) -> Answer / close(session)`. A passthrough adapter
       implements `forward(request) -> response` instead of `call`.
     - `Turn` and `Answer`: ported from `aisc_backend/adapters/base.py` (`Request`, `Answer`, `Secret`,
       `render`, `json_path`, `context_of`, `secret_headers`).
   - `compat.py`: `fits(slot, component, adapter) -> bool` and `candidates(slot, component, installed)`.
     This is the one compatibility rule, used by both the backend and the worker.
   - `presets.py`: `Preset(id, label, kind, protocol|format, adapter, fields=[...])` plus the five
     standard presets (D-10). A preset field maps a form field to a component column or config key.
   - `data/`: the standard data adapters. They port `input_providers` (csv/parquet/json/onnx) and add
     tsv and jsonl. CSV and TSV share one delimited reader. pandas, pyarrow and onnxruntime are imported
     lazily, as `ParquetInputProvider` does today.
   - `endpoint/`: `openai` and `oip` (passthroughs), `a2a` and `rest` (ported from
     `aisc_backend/adapters/{a2a,rest}.py` with their tests). The A2A agent-card discovery helper comes
     too.
   - `faces/`: request/response translation between a face protocol and `Turn`/`Answer`, for
     `openai-chat` and `agent`. These are pure functions with no server; eval hosts them (phase 4).
2. **`@evaluation_input`** gains `accepts`, `role`, `adapter`, `adapter_required` and `env`.
   - **Shorthands (D-15):**
     - `input_type=LLM` → `accepts=["openai-chat"]`, `role="subject"`.
     - `DATASET` → `accepts=["records"]`, or the value type of the given `input_provider_class`.
     - `MODEL` → `["onnx-session"]`, or a provider's type.
     - `DATASHAPE` → `["json"]`.
     - `RESOURCE` → `["resource"]`.
   - An explicit `input_provider_class` still wins and runs unchanged (it is wrapped as a data adapter
     with id `provider:<module.Class>`).
   - `InputDefinition` gains the new fields, with defaults, so old serialized definitions still parse.
3. **`LLMConfig`** is unchanged (D-16). New: `EndpointConfig(url, protocol, model, token_key)` for
   non-LLM endpoint slots, and `get_endpoint(name)` on the base plugin. `get_llm_config` keeps working.
4. **Packaging:**
   - an `[endpoint]` extra adds `httpx`;
   - the data adapters keep their heavy imports lazy, so there is no new base dependency;
   - bump to `0.5.0`.
5. **Tests:**
   - the registry and the shorthand mapping (every existing `InputType` combination);
   - each data adapter against fixtures (CSV/TSV/parquet/JSONL produce the same `table`, and `records`);
   - endpoint adapters: port `aisc_backend/tests/test_adapters.py` and run the A2A/REST cases against
     an in-process mock;
   - `compat.candidates` for every preset;
   - the old `@evaluation_input(input_provider_class=CsvInputProvider, input_type=DATASET)` still
     produces the same data.
6. **Docs:** a new "Inputs and adapters" chapter in `PLUGIN_DEVELOPER_GUIDE.md`, covering slots,
   `accepts`/`role`, writing a data adapter and an endpoint adapter, shipping one with a plugin, presets
   and env injection.

**Gate:** 0.5.0 is reviewed. The package and its tests are green, and existing plugins' test suites
(the example plugin and one ML catalogue plugin) pass against it unchanged.

## Phase 2 — discovery in `aisc-plugin-manager` (0.4.0)

**Repo:** `shared/plugin-manager`. The POC (`d9b5ee3`, `f9e1c6c`) is the reference.

1. `Loader` classifies each scanned module into plugin classes and adapter classes. Adapter classes are
   non-abstract subclasses of `DataAdapter` or `EndpointAdapter`, and the same goes for presets an
   adapter module exports. They are found in plugin packages **and** adapter-only packages (D-17),
   from the same sources: local folder and devpi index.
2. `list_adapters()` returns `{package: {version: {adapters: [manifest], presets: [manifest]}}}`.
   A manifest holds `id`, `version`, `kind`, `reads`/`produces` or `speaks`/`serves`, `capabilities`,
   the `Config` JSON schema and `source`. `load_adapter(package, version, id)` returns the class.
   The standard library is listed as package `aisc-plugin-interface` with source `builtin`.
3. Same tolerance rules as plugins: a broken adapter is reported, not fatal; `+local` versions and
   digest caching work as for plugins.
4. **Tests:** a fixture package containing a plugin, a data adapter and an endpoint adapter; an
   adapter-only package; and a broken adapter.

**Gate:** released 0.4.0, with backend and eval lockfiles regenerated against 0.5.0/0.4.0. This is
also the existing blocker for the Docker image build: publishing 0.5.0 unblocks it.

## Phase 3 — backend model, migration and API

**Repo:** `apps/backend`. The component model is in `aisc_backend` (core) and the binding is in
`aisc_evaluation`.

1. **`AIComponent`** (`models/ai_system.py`):
   - `project` FK, non-null (backfilled from `system.project`), and `system` FK made **nullable**
     (null means a project-level instrument, D-8).
   - Replace the `component_type` choices with `kind` (`dataset|model|datashape|resource|endpoint`;
     plain `CharField` validated against a code list, not a DB enum, D-12).
   - Endpoint fields:
     - `url`;
     - `protocol` (a registry string);
     - `adapter` and `adapter_version` (empty means the default for the protocol);
     - `adapter_config` (JSON, validated by the adapter's `Config` at save);
     - `preset` (the id of the form that made it, for reopening);
     - `secret_key` (a reference into the existing `ProjectConfig` secret store; one secret per
       component; secret headers stay keyed `component:<pid>:header:<name>`).
   - The file fields (`HasData`) and `source_dataset` are unchanged. `format` for files is derived from
     the stored name's suffix and stored, so the evaluation form can filter without opening the file.
   - Keep `json_value` for `datashape` (the derived document) and `resource` (`ResourceConfig`) only.
2. **`EvaluationInput`** (`aisc_evaluation/models.py`):
   - Add `adapter`, `adapter_version`, `adapter_config`, and `provenance` (JSON: url, adapter, version,
     config_hash; filled at dispatch, never rewritten).
   - This replaces `RunBinding`'s snapshot.
3. **Migrations:**
   - `aisc_backend 0043`: the schema plus a data migration.
     - `llm` → `endpoint`, `openai-chat`, preset `llm`, `url=json_value.endpoint_url`,
       `secret_key=json_value.secret_key`. This is a **mainline type**, so the upgrade must preserve it,
       with a reverse that restores `llm`.
     - `resource` and the file types are untouched.
   - Unshipped unified-app data (ADR 0003):
     - `Connection` rows → endpoint components (`kind` → protocol and adapter, protocol columns →
       `adapter_config`, secrets re-keyed);
     - `Helper` rows → project-level `openai-chat` endpoints;
     - then drop `Connection`, `Helper` and `RunBinding`.
     - A best-effort conversion is enough here, because this data needs no preservation guarantee.
       It is done so a dev database does not lose its setup.
   - `aisc_evaluation 0002`: the `EvaluationInput` fields, with `provenance` backfilled empty.
   - Test both directions on SQLite **and** PostgreSQL. The test is a mainline 0014 database upgraded
     to head, run on the real PostgreSQL in compose (ADR 0003 #3).
4. **Services:**
   - `services/components.py` replaces `services/connections.py`: row shapes, preset apply/read, and
     adapter config validation via the registry.
   - `services/component_secrets.py` replaces `connection_secrets.py`, with the same store and new key
     names.
   - `services/ai_assistant.resolve_chat` keeps its signature. The model comes from:
     1. the project's `ai_assistant` setting (a component pid);
     2. else the first project-level `openai-chat` endpoint;
     3. else the stack setting.

     The call goes through `aisc_plugin_interface.adapters` **in-process**, with no door (D-8).
     `card_agent` and `risk_mapper` are not changed.
   - "Test connection" becomes `POST /components/{pid}/test`. Standard adapters run in-process in the
     backend (as `try_connection` does today, through the allowlist guard). A custom endpoint adapter
     that is not importable in the backend answers "test runs on the worker" (out of scope: a
     worker-side test task, §Later).
5. **API** (deny-by-default project scoping as for every route, ADR 0003 #5):
   - `GET /adapters` and `GET /presets`: the catalogue from `plugin_loader.list_adapters()`, plus the
     builtin manifests and their `Config` JSON schemas.
   - Components CRUD accepts a preset payload (`{preset, fields}`) **or** an advanced payload
     (`{kind, protocol, url, adapter, adapter_config, secret}`).
   - `GET /plugins/{pid}/slots/{name}/candidates`: components plus a default adapter per slot, computed
     with `compat.candidates`.
   - The evaluation create schema gains `adapter` and `adapter_config` per input, both optional and
     defaulted by the rule above. `adapter_required` is enforced.
   - Remove `/connections`, `/helpers` and `/run-bindings`. `/allowed-hosts` stays.
   - `internal.get_evaluation_inputs`: for an endpoint input, send the url, protocol, adapter, version,
     config and the **encrypted** secret, plus the adapter's install target when it lives in another
     package (POC `resolve_adapter_install_target`). Stop sending `LLMConfig` built from `json_value`.
6. **Results/report:** `results_dashboard` reads endpoint provenance from `EvaluationInput.provenance`
   instead of `RunBinding`. The report's "what was assessed" uses the same data.
7. **Tests:**
   - migrations (mainline `llm` round trip; a unified-app Connection/Helper conversion);
   - preset apply/read for each preset;
   - candidates per slot;
   - two-project isolation for components, adapters and candidates (the existing pattern);
   - `resolve_chat` order;
   - `/test` through the allowlist against `local_target.py`;
   - the evaluation-create default and required adapter;
   - the internal payload shape.

**Gate:** all backend checks are green, and the PostgreSQL upgrade from mainline 0014 works with an
`llm` component intact.

## Phase 4 — the run door in eval

**Repo:** `apps/eval`. This is ADR 0009 decision 4.

1. **Install:**
   - `install_package` (warm cache) and the per-run venv install add the adapter package targets for
     any non-builtin adapter (POC `resolve_adapter_chain` → one adapter per input).
   - The plugin interface is installed with `[endpoint]` when any input is an endpoint.
2. **Data inputs:**
   - `plugin_runtime.py` resolves the input's adapter. That is either an explicit `provider:` (today's
     path, unchanged) or a registry data adapter loaded by id, given `config` and the slot's `produces`.
   - It then calls `plugin.set_input_content(name, value)`.
   - No network, no secrets.
3. **The door** (`aisc_eval/door.py`, runtime script; standard library `http.server` in a thread pool):
   - **Process:**
     - started by `run_plugin` **before** the plugin, as a subprocess in the **same venv**, so adapters
       shipped with plugins import;
     - `env=plugin_child_env()`, so the worker's credentials never reach it;
     - the door receives its spec on **stdin** as JSON: per endpoint slot, the adapter id/version,
       config, the url, the decrypted secret and the allowlist entries;
     - it reports its port on stdout;
     - it is stopped (SIGTERM, then kill) in the same `finally` that stops the plugin.
   - **Routing:** `/<slot>/…`, one route prefix per endpoint slot. Each route is backed by its adapter:
     - passthrough (`openai`, `oip`): forward the path, method, body, query and **streaming** response
       unchanged under the prefix (`/v1/*`, including `/models` and `/embeddings`), replacing the
       `Authorization` header with the real key;
     - converting (`a2a`, `rest`, custom): the face for the slot's protocol parses the request into a
       `Turn`, calls `adapter.call`, and renders the `Answer` back. `openai-chat` supports
       `/v1/chat/completions` (non-streaming; streamed as one chunk if asked) and `/v1/models`.
   - **Auth:** each request must carry the run token (Bearer). Anything else gets a 401.
   - **Allowlist:** before every upstream call, the adapter's target host is checked against the
     project's entries plus the floor. The rule is ported from `services/allowed_hosts.refusal_for`
     into `aisc_plugin_interface.adapters.hosts` so backend and door share one implementation (I3).
     The backend's `allowed_hosts.py` then imports it.
   - **Timeout and concurrency:** the adapter's `timeout_s` config and `max_concurrency` semaphore.
   - **Scrubbing:** every response body and header, and the door's own log lines, are scrubbed of
     every secret value it holds, using the worker's existing scrub helper.
   - **Provenance:** the door writes `{slot, adapter, version, url, config_hash, calls, errors}` to the
     workspace. `post_results` sends it, and the backend stores it on `EvaluationInput.provenance`
     (dispatch fills url/adapter/version/hash, and the door adds counts).
4. **What the plugin receives** (D-16):
   - For an `openai-chat` slot, the input file is `LLMConfig(endpoint_url="http://127.0.0.1:<port>/<slot>/v1",
     model=<component or run model>, secret_key=<slot token key>)`.
   - The run token goes into the child env as `AISC_SECRET_<KEY>`, so `self.get_secret(llm.secret_key)`
     returns the **token**.
   - The slot's declared `env` mapping is rendered with `{base_url}`, `{api_key}` and `{model}` and
     added to the child env. The ollama case is `OLLAMA_HOST={origin}` via the face, which is a
     candidate.
   - The real key is **not** in `build_secret_environment` for endpoint inputs (it is withdrawn from
     `llm_secret_settings`).
5. **Tests** (eval suite):
   - a door unit test: passthrough to a mock OpenAI server, where the mock sees the real key and the
     client sees the scrubbed response; streaming passthrough; a wrong token gets 401; a disallowed
     host is refused; a `rest` adapter maps a nested response path;
   - an `a2a` adapter against a mock agent;
   - `run_plugin` end to end with the example LLM plugin: the plugin process env and its input file
     contain no real key, the mock target receives the real key, and the door stops when the plugin
     ends or fails;
   - a data-adapter run: a TSV dataset feeds a slot that accepts `records`.

**Gate:** the example `llm_example` plugin runs **unchanged** through the door against a mock, and the
ADR 0003 env test still passes.

## Phase 5 — webapp

**Repo:** `apps/webapp`. Keep the pilot look and the Manage grouping (refactor-plan §2.1). Forms are
rendered from JSON schema with the existing `PluginConfigForm` (rjsf) machinery.

1. **Manage → Components** (`AISystemSettings.tsx`):
   - "Add component" opens a preset chooser: **LLM**, **Agent**, **Model API**, **Dataset**,
     **Model file**, **Custom endpoint**.
   - A preset shows a single form with only its fields.
   - **Custom** shows: URL, secret, an adapter dropdown (from `/adapters`, filtered to endpoint
     adapters), then that adapter's config form, plus "Test".
   - Reopening a component shows the form it was made with, and offers "Open in advanced view".
   - Components are listed with a label from their preset or protocol (LLM / Agent / Model API / REST /
     Custom), never the raw kind.
2. **Manage → AI assistant and judge models** replaces `HelpersPage`:
   - the same LLM preset form, saved at project level (`system` null);
   - a radio to choose the AI assistant model.
3. **Manage → Allowed internal hosts:** the existing `AllowedHostsSection` moves here from
   `ConnectionsPage`.
4. Delete `ConnectionsPage`, `HelpersPage`, `lib/connections.ts`, `lib/helpers.ts` and their routes
   and `LeftBar` entries.
5. **Start evaluation** (`PluginStartEvaluation.tsx`):
   - Each slot's dropdown lists `/candidates`, with judge/instrument slots listing project-level
     endpoints.
   - The adapter is chosen automatically. An "Advanced" toggle per slot shows the adapter dropdown and
     config form, which is locked when `adapter_required`.
   - The slot label shows its role (Assessed / Input / Judge).
6. **Results:** the run detail page shows per-input provenance (adapter@version, url, calls).
7. **Tests:**
   - presets create the right payloads;
   - the custom form renders from a schema;
   - candidates filter and default;
   - the advanced toggle;
   - existing page tests are updated, and the removed pages' tests are deleted.

**Gate:** `npm test` and `npm run build` are green. A manual walk-through covers the three cases below.

## Phase 6 — acceptance, docs and cleanup

1. **End-to-end cases** against the stack, with mock targets from `local_target.py`:
   - **ML:** an ONNX model and a TSV test dataset, run by an ML plugin whose slot accepts `records`.
     Then re-run with another dataset by copying the evaluation and changing one binding.
   - **LLM:** an LLM preset feeds the example LLM plugin, plus a judge at project level. The run
     provenance shows both, and the target mock sees the real key.
   - **Custom:** a custom endpoint adapter shipped in a fixture plugin package turns a mock bespoke API
     (login plus a nested response) into `openai-chat` for an unchanged LLM plugin.
2. **Docs:**
   - `ARCHITECTURE.md` I2/I3 wording per ADR 0009, and AGENTS.md invariant lines;
   - an ADR README entry, with ADR 0009 accepted;
   - a pointer from brief D5;
   - `docs/refactor-plan.md` §3.1 and §7 (the door is no longer post-port for endpoint inputs);
   - `docs/migrations/v1.3.0-to-v1.4.0.md`: plugin authors (new slot fields, shorthands still valid,
     LLM plugins now get a door URL and token, how to ship an adapter), and platform agents (removed
     endpoints and tables, the new catalogue endpoints);
   - `docs/refactor-deviations.md` CON-01: "superseded by ADR 0009".
3. **Cleanup:**
   - delete `aisc_backend/adapters/` (moved), the connection/helper routers, schemas and services, and
     their tests (ported in phase 1/3);
   - remove `LLM`'s backend-only paths (`routers/project.py:277`, the internal `LLMConfig` assembly);
   - delete `component-adapter-plan.md` and this file once their content is folded in.

**Gate:** all suites and guards are green, the three end-to-end cases pass, and the docs are updated.

## Plugin catalogue follow-up (separate repos; not a gate)

The catalogue LLM plugins take the target URL and key **in their own plugin config** today. They keep
working, but without the door. Each is converted to declare an endpoint slot and read
`get_llm_config()`/declared env instead:

| plugin | today | conversion |
|---|---|---|
| promptfoo | `target_endpoint`/`target_credential` → `OPENAI_BASE_URL`/`OLLAMA_BASE_URL` env | slot `target` with `env={"OPENAI_BASE_URL": "{base_url}", "OPENAI_API_KEY": "{api_key}"}`, plus an optional judge slot |
| langbite | form credential → `API_KEY_OPENAI`/`OLLAMA_URL` env | slot plus env mapping |
| strongreject | LiteLLM env per provider | slot plus `OPENAI_API_BASE`/`OPENAI_API_KEY` mapping (LiteLLM `openai/` prefix) |
| ragas | `base_url=` from config | slot; read `get_llm_config()`; judge slot |
| agentdojo | `AISC_LOCAL_BASE_URL` sitecustomize patch | slot; set `AISC_LOCAL_BASE_URL` from the slot |
| MLA-BiTe | `configure(api_key, api_base)` | slot; pass the door URL and token |

Order: the example plugin first (phase 4 gate), then promptfoo (the most used), then the others.

## Sequencing and size

| phase | repos | depends on | rough size |
|---|---|---|---|
| 1 contract | plugin-interface | — | M |
| 2 discovery | plugin-manager | 1 | S |
| 3 model + API | backend | 1, 2 | L |
| 4 door | eval | 1, 2; payload from 3 | M–L |
| 5 UI | webapp | 3 | L |
| 6 acceptance | all + parent | 3–5 | M |

Phases 3 and 4 can proceed in parallel once the internal payload shape (3.5, last bullet) is fixed.
Do that first, in phase 3.

## Later (not in this plan)

- Stateful agent sessions (context id per run or row) in the `a2a` adapter.
- A first-class `web-chat`/playwright adapter and its form. HTTP job/poll mode.
- A worker-side "Test" for custom adapters that the backend cannot import.
- The `predictor` value type. Plugins that read a target URL from their own config.
- I1 self-contained dispatch (still deferred by ADR 0003).

## Risks

- **Passthrough fidelity.** Some libraries use streaming, `/responses` or odd headers. Mitigation:
  forward byte-for-byte under the prefix, and test with the openai SDK and LiteLLM clients.
- **Mainline upgrade.** `llm` components on real deployments. Mitigation: a reversible data migration,
  tested on PostgreSQL from 0014.
- **Published-interface churn.** Mitigation: phase 1 is additive with shorthands, and old plugins'
  tests run against 0.5.0 before release.
- **Door lifecycle leaks** (orphaned processes, ports). Mitigation: one `finally`, a process group,
  and a test that kills the plugin mid-run.
