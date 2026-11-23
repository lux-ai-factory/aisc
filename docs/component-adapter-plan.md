# Components, inputs and adapters — design plan

**Status:** under discussion — **not ready to implement**. Started 2026-11-20.
**Scope:** `AIComponent`, `Connection`, `Helper`, `RunBinding`, the AI assistant, plugin inputs and
adapters across backend, webapp, eval, plugin-interface and plugin-manager.

This is integration scaffolding, not a binding document. When the design is agreed it becomes an ADR
(it changes the brief's D5 wording "one connection/adapter model beside `AIComponent`") plus a
`docs/refactor-plan.md` step. Delete this file once the ADR and the docs it feeds are written.

Keep this file current while the discussion runs: record each answer under §7 and move it into §2.

---

## 1. The use cases the model must cover

**ML / tabular.** A custom plugin with its own config tests an ONNX model file. Its inputs are training
data, test data and datashapes derived from the training data. A researcher re-runs the same evaluation
with another test dataset, another config or another model. The model may instead be served behind an
API (it then needs an adapter, unless a custom plugin takes the URL in its config). The user's data
may not be in the format the plugin reads (TSV or parquet where the plugin reads CSV), so it must be
converted for them instead of by hand.

**LLM.** Plugins wrap open-source benchmark, testing and jailbreak libraries. They reach one or more LLMs
in different ways:
- through a local ollama;
- through env vars that configure an LLM proxy library;
- by calling an OpenAI-compatible endpoint directly over HTTP.

The target may also be:
- an agent (not a plain chat model);
- a custom REST endpoint, possibly returning the answer in a non-standard field;
- only the URL of a web app with no API.

An assessed chatbot (for example a public body's web UI) is the assessed component. Datasets drive the
evaluation. A second LLM can serve as a judge.

**Goal:** reuse plugins as much as possible. One adapter layer turns whatever the user has into what the
plugin expects. A standard library covers the common cases, and a custom Python adapter covers the rest.
It must be easy to load into the running stack and then appear in the UI for selection.

## 2. Decisions so far

- **D-1 — The assessed thing can be an endpoint.** `AIComponent` is not limited to files. (This corrects
  the earlier idea of dropping `llm`/`resource` component types.)
- **D-2 — `Connection` gets a purpose discriminator and `Helper` folds into it.** This is agreed, but it
  may be superseded by §4, which removes `Connection` altogether.
- **D-3 — The core concept is the adapter, not the "connection".** A connection model cannot capture
  every case.
- **D-4 — Out of scope for now:**
  - a first-class `web-chat` (playwright) adapter and its UI;
  - job-id/poll mode for HTTP endpoints.

  Web UIs are covered by **custom** adapters the user writes. Revisit after a few exist.
- **D-5 — Chat models and agents are different types, and the existing `a2a` adapter is ported as is
  (was Q5).** `agent` is a type and `a2a` (`agent → turn`) is a standard adapter, ported with its current
  behaviour: one `message/send` per turn, with no context id carried between calls. The door serves an
  agent component through the `openai-chat` face (one turn per call; the plugin's history is not
  forwarded, as today) and through an `a2a` passthrough face for plugins that speak A2A. Stateful agent
  sessions (a context id per run or per row) are a later extension of this adapter, not new machinery.
- **D-6 — An adapter converts exactly one type into one other type** (§5).
- **D-7 — Every endpoint input goes through the run-scoped door (was Q3).** The worker starts a
  loopback server for the run. The plugin only ever gets `http://127.0.0.1:<port>` and a run token,
  never the real URL or key, even for a standard OpenAI endpoint (which uses the `openai` passthrough
  adapter). Judges and other instrument endpoints go through the door too. This brings the I2 door
  forward from ADR 0003, so the ADR must say so. File inputs have no server: their adapter is the
  reader, and a default one is chosen when it is the only fit.
- **D-8 — Judges, helpers and the AI assistant's model are project-level endpoint components (was Q1).**
  They belong to the project, not to an AISystem. They become instruments by the slot they are bound to.
  The AI assistant setting names one of them. The backend calls it in-process through the same adapter
  code, with no door, because that call is not part of a run.
- **D-9 — No user-built chains (was Q8).** A binding selects **one** adapter (id, version, config).
  The POC's ordered `EvaluationInputAdapter` M2M is not ported. Preprocessing such as decompressing,
  renaming columns or filtering belongs in an adapter's config or a custom adapter. A standard adapter
  can reuse another in code, and a custom adapter can call standard ones. Composition happens in code,
  not in the UI or the DB.
- **D-10 — The UI is task-shaped, not table-shaped (was Q2).** "Add an LLM" is one form: name, base
  URL, model and API key. It creates an endpoint component with the `openai` adapter behind the scenes.
  The user never sees "endpoint", "type" or "adapter" on the common path. A **Custom** option opens
  the advanced form: pick any adapter, then its config form. The UI does not have to mirror the tables
  (§4.1).
- **D-11 — Out of scope for now:** plugins that read a target URL from their own config (was Q4), and
  `predictor` (was Q6; ML plugins keep reading the ONNX file or call an `oip-v2` door face).
- **D-14 — Adapters live in `aisc_plugin_interface.adapters` (was Q7).** That subpackage holds the base
  classes, the type registry, the presets and the standard library, with its own
  `ADAPTER_ABI_VERSION`. The door server is runtime code in `eval`. No new package.
- **D-15 — Existing plugins keep working (was Q11).** `input_type=LLM/RESOURCE/…` and
  `input_provider_class=…` stay as shorthands for `accepts` and the reader. The new form is documented
  in the migration guide.
- **D-16 — An LLM input keeps today's `LLMConfig` shape (was Q12).** `endpoint_url` is the door URL,
  the key is the run token, and `model` is unchanged. Declared env vars are optional. Existing LLM
  plugins run behind the door unchanged.
- **D-17 — A plugin package may ship adapters (§6.1).** Plugin-manager discovers adapter classes in
  any package, plugin or adapter-only. This is what the POC already does.
- **D-18 — Adapters and plugins are trusted code.** We write and control them, so the design adds no
  sandboxing, trust warnings or review gates for them. The door (D-7) stays, for uniformity,
  the allowlist, scrubbing of what third-party libraries log, and provenance, not because the plugin is
  distrusted. It also keeps I2 satisfied at no extra cost. Handing a plugin the real key instead would
  need an ADR that changes I2, which is not proposed.
- **D-19 — Shipped adapters are visible to every plugin they fit (was Q13).** They are matched by type,
  not by owner. When one is selected for another plugin's slot, the worker also installs its package.
- **D-20 — `resource` stays as a plain reference.** It is a string such as a HuggingFace model id,
  which the plugin resolves itself. It is not an endpoint, has no adapter, and does not go through the
  door. `llm` becomes `endpoint` with protocol `openai-chat`.
- **D-12 — Extensible by registration, not by migration (was Q9).** The §5 vocabulary is enough for now.
  Adding a type, adapter or preset must not need a schema migration or a change to the plugin
  contract (§4.2).
- **D-13 — Endpoint provenance (was Q10).** A run records the endpoint URL, the adapter id and version,
  and a hash of the adapter config. Secrets are excluded from the hash input.

## 3. What exists today (four overlapping implementations)

| # | Where | What it does | State |
|---|---|---|---|
| A | `plugin-interface` `input_providers/` (`Csv`, `Parquet`, `Json`, `Onnx`) | Turn the input file's bytes into a value; the plugin hard-wires one per input via `@evaluation_input(input_provider_class=…)` | on the frozen pins, used by plugins |
| B | `poc/input-adapater-chain` across plugin-interface, plugin-manager, eval, backend and webapp | `BaseInputAdapter.adapt(data)` is a **user-selected, ordered chain** per evaluation input. It declares advisory `input_types` (globs like `*.csv`) and an `output_type` (`pd.dataframe`). Plugin-manager discovers adapter classes alongside plugins. The worker installs adapter packages and applies the chain before the provider. The backend stores `InputAdapter` and `EvaluationInputAdapter` (an ordered M2M) and serves `GET /plugins/adapters`. The webapp has an adapter picker on the evaluation form | **unmerged POC branch** |
| C | `apps/backend/aisc_backend/adapters/` (`openai`, `rest`, `a2a`, `oip`) with `Connection`, `Helper` and `RunBinding` | `build_request` / `parse_response` for one call to a target in the shape `{input, history, params} → Answer`. Runs in the **backend** (`try_connection`, "Test connection"). The run does **not** use it; the worker receives the `llm` component's URL and secret directly | on the frozen pins (CON-01) |
| D | `pilot` / `feat/unified-modules` `model_session.py` (`self.assessed_model()`) | Gives an ML plugin one `predict` / `predict_proba` object, built from either a local ONNX file or an endpoint target | exploration branch only |

B is the file-conversion adapter work: it converts a format the user has into the format a plugin
reads. C is the endpoint adapter: it reaches a target that speaks some protocol. **They are the same
concept** (convert type X into type Y so the plugin is reused), split by *when* the conversion runs:

| kind | runs | converts | runs where |
|---|---|---|---|
| **data** | once, at run start | a file/format → the value the plugin reads | in the plugin process (where providers run today) |
| **endpoint** | per call | a target's protocol → the protocol the plugin speaks | behind a loopback endpoint in the worker (the I2 door) |

This matches `SCRATCH-platform-adapters/06-adapters.md` §8–9, which already agreed on these two kinds.
Note that "agent" there was a capability, not a kind. Here it is a **type** served by the ported `a2a` adapter (D-5).

**Merge proposal:**
- One adapter base, one discovery path (plugin-manager, as B already does) and one selection record
  (on the evaluation's input binding).
- One catalogue endpoint for the UI.
- A's providers become the standard-library data adapters.
- C's four classes become the standard-library endpoint adapters.
- From B we keep discovery, install and selection, but not its ordered chain (D-9).
- D is not ported (D-11).

## 4. Proposed model (draft)

Three questions, one home each:

1. **What is the thing?** → `AIComponent`, with a **type** from the vocabulary in §5:
   - a file (`dataset`, `model`, `datashape`);
   - or an `endpoint` with a URL, a secret in the existing secret store, the protocol it natively
     speaks, and that protocol's config (for example the REST body template and response path).

   `Connection` and `Helper` dissolve into endpoint components. A judge LLM is a project-level endpoint
   component (D-8).
2. **What part does it play in this run?** → the plugin's input **slot**: `@evaluation_input` gains
   `accepts=[type…]` and `role=subject|input|instrument`. An evaluation binds one component to each
   slot (`EvaluationInput`, which already exists). `RunBinding` duplicates this and goes.
3. **How does the plugin get it?** → **one adapter** from the component's type to a type the slot
   accepts (D-9). It is recorded on the binding and picked automatically when only one fits.

Config placement:
- Config that describes **the target** (a REST template, a response path, auth headers) lives on the
  endpoint component.
- Config that describes **the conversion** (a delimiter, a sheet, a session scope) lives on the binding.

### 4.1 Presets: the UI's simple forms (D-10)

A **preset** is a named, simple form that fills in a component and its adapter. Presets are declared
in code next to the standard adapters. They are not stored in the DB.

| preset ("Add …") | fields shown | creates |
|---|---|---|
| **LLM** (OpenAI-compatible) | name, base URL, model, API key | endpoint · `openai-chat` · adapter `openai` · config `{model}` |
| **Agent** (A2A) | name, base URL (the agent card fills in the rest, as "Test" does today), API key | endpoint · `agent` · adapter `a2a` |
| **Model API** (OIP v2) | name, base URL, model name, API key | endpoint · `oip-v2` · adapter `oip` |
| **Dataset** | name, file (and an optional delimiter or sheet when it can't be inferred) | dataset · format inferred from the file |
| **Model file** | name, file | model · `onnx` |
| **Custom endpoint** | URL, secret, then **adapter** (any installed one, standard or custom) and that adapter's config form | endpoint · chosen adapter |

- The LLM preset is the first choice in the "Add component" dialog and on the judge/helper page.
  A judge is the same LLM form saved at project level (D-8).
- Reopening a component shows the form it was made with. A component made with a preset can be opened
  in the advanced view; one made in the advanced view stays there.
- A custom adapter can ship its own preset (a list of which `Config` fields to show, plus labels). It
  then gets a simple form too, without any webapp change.
- The **evaluation form** stays simple: each plugin slot lists only the components that fit it. The
  adapter is picked automatically when one fits, and an "Advanced" toggle shows the choice and its
  conversion config.

### 4.2 Shape that stays extensible (D-12)

What forced this refactor was protocol detail baked into schema columns (`Connection.model`,
`.path`, `.method`, `.body_template` …) and type enums duplicated across backend, plugin-interface,
worker and webapp. Instead:

- **Types, protocols and adapter ids are strings resolved against a registry in code**, not Django
  `choices` that need a migration to grow. The registry lives in `aisc_plugin_interface.adapters` and
  is served to the webapp by a catalogue endpoint, so the webapp has no hard-coded list.
- **Adapter config is JSON on the component or binding**, validated by the adapter's pydantic
  `Config`. The webapp renders its forms from the `Config` JSON schema (as plugin config forms are today).
  Adding a protocol field is a code change in one adapter, with no migration.
- **Few, stable columns:** the component keeps the kind of thing (`file` or `endpoint`), its type
  string, the URL, the secret reference, the adapter id and version, and the config JSON. Bytes and
  storage stay as they are.
- **Adding something new is a registration:** a new data format is a reader, a new protocol is an
  adapter plus perhaps a door face, and a new simple form is a preset. None of them touch the schema,
  the plugin decorator or the UI code.

## 5. Types and the standard library (draft)

Each adapter declares `from` → `to`. To avoid N×M adapters, each family has one **hub** type:
- **data:** files are read into `table`, and a slot that needs another shape gets one more step;
- **endpoints:** every target is driven into a common **turn** (`{input, history, params, tools} →
  Answer`, the shape C already uses), and the door serves that turn in the protocol the plugin speaks.

### 5.1 Data types and data adapters

Source types (what a dataset/model component holds): `csv`, `tsv`, `parquet`, `jsonl`, `json`, `onnx`.
Value types (what a slot accepts): `table` (pandas DataFrame), `records` (`list[dict]`), `json`
(any JSON value), `onnx-session` (onnxruntime session), `file` (a path; no conversion).

| adapter | from → to | replaces |
|---|---|---|
| `csv` | csv → table | part of `CsvInputProvider` |
| `tsv` | tsv → table | new (the motivating case) |
| `parquet` | parquet → table | `ParquetInputProvider` |
| `jsonl` | jsonl → table | new |
| `table-records` | table → records | the rest of `CsvInputProvider` (which returns records) |
| `json` | json → json | `JsonInputProvider` (also datashapes) |
| `onnx` | onnx → onnx-session | `OnnxInputProvider` |
| *(identity)* | any → file | for plugins that read the file themselves |

Per D-9 the user selects one adapter. A CSV for a `records` slot uses a `csv` adapter that produces
`records`. That adapter may reuse the `table` reader internally, but this is an implementation detail,
not a chain the user builds. Each reader therefore declares which value types it can produce
(`csv → table | records`), and the slot picks one.

### 5.2 Endpoint (protocol) types and endpoint adapters

Protocol types are what an endpoint component speaks, or what a slot accepts:

| type | meaning |
|---|---|
| `openai-chat` | Stateless chat completions. The **client** owns the history; tools and logprobs are optional capabilities |
| `agent` (A2A) | The **server** owns the conversation and may run tool loops itself. One turn per call (D-5) |
| `oip-v2` | Open Inference Protocol: a served ML model (tensor in, tensor out). Passthrough, like `openai` |
| `rest` | A bespoke JSON API, described by config: method, path, body template, the response path (which covers "answer in an altered field"), auth header and refusal rule |
| `url` | Only an address (for example a web app). No standard adapter; custom adapters only (D-4) |

Endpoint adapters (target side, into the turn):

| adapter | from → turn | replaces |
|---|---|---|
| `openai` | openai-chat → turn | C `openai` (passes through and adds the key) |
| `oip` | oip-v2 → oip-v2 (passthrough; adds the key, allowlist, scrub) | C `oip` |
| `a2a` | agent → turn (one `message/send` per turn, ported as is; D-5) | C `a2a` |
| `rest` | rest → turn | C `rest` |
| *(custom)* | url / anything → turn | user-authored, e.g. playwright |

Door faces (turn → the protocol the plugin speaks):

| face | serves | how the plugin is pointed at it |
|---|---|---|
| `openai-chat` | `POST /v1/chat/completions` | a URL in the input value, **or** declared env vars (`OPENAI_BASE_URL`, `OPENAI_API_KEY`, `LITELLM_*` …) |
| `oip-v2` | `/v2/models/...` passthrough | URL or env var |
| `agent` | A2A `message/send` passthrough | URL or env var |
| `ollama` | `/api/chat` (candidate; ollama also serves `/v1`) | `OLLAMA_HOST` |

The user picks only the **target-side** adapter. The door face follows from the protocol the slot
accepts, so it is never a user choice and never a chain (D-9).

Env vars, a URL in the input value, and ollama are **ways the plugin is handed the door**, not adapters.
The plugin declares on the slot which one it needs.

An agent bound to an `openai-chat` slot gets one turn per call, and the plugin's history is not
forwarded (D-5). A chat model bound to an `agent` slot is not offered. Deferred: stateful agent
sessions (D-5) and the `predictor` value type (D-11).

## 6. Custom adapters

- A Python package depending on the adapter base class. It declares `id`, `version`, `kind`
  (data/endpoint), `from`, `to`, a pydantic `Config` (which becomes the UI form) and, for endpoint
  adapters, `capabilities`, `session` scope and `max_concurrency`. It implements `adapt(value)` (data)
  or `open` / `call` / `close` (endpoint).
- It is discovered and installed **the same way plugins are**, through plugin-manager: local folder or
  devpi index. The POC (B) already does this. There is no new service, so no I8 ADR is needed for this.
- Once installed it appears in the catalogue and in the dropdowns wherever its `from`/`to` fit.
- **Trust (D-18):** adapters and plugins are first-party code, so they are trusted. There is no trust
  warning, no adapter review step and no sandbox. An endpoint adapter holds the target's real secret.
- **Where the door runs:** one subprocess per run, in the same uv environment as the plugin (so
  adapters shipped with a plugin, and their dependencies, are importable). This is for dependencies,
  not trust. Its environment is the ADR 0003 allowlist plus that run's target secrets. The worker's
  own credentials (`INTERNAL_API_KEY`, DB/S3) never enter it. This is the existing ADR 0003 gate, not
  extra machinery.
- System dependencies (playwright, a browser) are the adapter's concern. A shared worker image that
  ships them would need an I8 ADR. This is not needed while web adapters stay custom (D-4).

### 6.1 Adapters shipped with a plugin (D-17)

A plugin package may contain adapter classes next to its plugin classes, registered with the same
entry point. Plugin-manager finds both in one scan. The POC already does this: an adapter in the
plugin's own package needs no separate install.

- **Version:** a shipped adapter has the plugin package's version, and the worker installs it with the
  plugin. It needs no separate pin.
- **Default for its slot:** the plugin can name it on the input,
  `@evaluation_input("target", accepts=["openai-chat"], adapter="my_pkg:BankPortalAdapter")`. The
  evaluation form then preselects it for that slot, and the user can still change it.
- **Required:** `adapter_required=True` marks the shipped adapter as the only choice. This is for a
  plugin written for one bespoke system.
- **Visibility:** offered for any slot it fits (D-19).
- **Where it runs:** a shipped endpoint adapter still runs in the door subprocess, not in the plugin
  process. A shipped data adapter runs in the plugin process. Shipping an adapter with a plugin changes
  only how it is distributed, not where it runs or what it can see.

## 7. Open questions

1. ~~Judges and helper LLMs~~: decided, D-8.
2. ~~Component type label~~: decided, D-10 (presets).
3. ~~The door now or later~~: now, for every endpoint input (D-7). Still to settle: the passthrough must
   forward everything under `/v1` (streaming, embeddings, `/models`, the Responses API) unchanged, not
   only `/chat/completions`.
4. ~~Plugins with their own URL~~: ignored for now, D-11.
5. ~~Lossy conversions~~: an agent serves `openai-chat` slots one turn per call; chat models are not
   offered to agent slots (D-5).
6. ~~`predictor`~~: not now, D-11.
7. ~~Where the adapter base lives~~: decided, D-14.
8. ~~Chains~~: decided, D-9.
9. ~~Type names~~: complete for now, extensible by registration (D-12).
10. ~~Endpoint provenance~~: decided, D-13.
11. ~~Existing plugins~~: decided, D-15.
12. ~~LLM input value~~: decided, D-16.
13. ~~Visibility of a plugin-shipped adapter~~: decided, D-19.

All design questions are answered. What remains is the ADR and the implementation plan (§8).

## 8. Next steps

- The decision record is [ADR 0009](adr/0009-components-adapters-and-the-run-door.md) (proposed).
- The implementation plan is [`component-adapter-implementation.md`](component-adapter-implementation.md).
