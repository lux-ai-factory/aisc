# Appendix B — Alternative adapter specification (ours)

> From `SCRATCH-platform-adapters-discussion.md` Appendix B. Alternative to pilot's platform-level
> adapters (§5, Appendix A). Scope: the spec only. Loaded by the **plugin manager**, **separate from
> the plugin interface**, two kinds (data vs resource), selectable per plugin+input, versioned.

### B.1 Shape

- New spec package **`aisc-adapter-interface`** — independent of `aisc-plugin-interface`. Adapters are packages that depend on it, found and imported by the **plugin manager** (`aisc_plugin_manager.Loader`), from the same two sources as plugins: local folders (an `adapters/` / `local_adapters/` dir) and the devpi index.
- An adapter is a **Python class + a `MANIFEST`** (name, version, kind, …). The plugin manager gains `list_adapters()` / `load_adapter(name, version)`, requiring a dependency on `aisc-adapter-interface` and at least one concrete adapter class — mirroring how it already finds `BaseEvaluationPlugin` subclasses.
- **Two kinds**, because the two jobs are genuinely different (your point):
  - **`data`** — convert one data format into the type the plugin expects. Runs **once, at run start**.
  - **`resource`** — present a bespoke external resource as a protocol the plugin speaks. Runs **repeatedly, per row / per call**.

### B.2 Data adapters (ML plugins)

The existing `input_providers` (`csv_input_provider.py`, `parquet_input_provider.py`, …) are the seed: they turn bytes into `list[dict]` / `pandas.DataFrame`. Generalize that into a versioned, selectable adapter.

```python
class DataAdapter(ABC):
    MANIFEST = {
        "name": "tsv-to-dataframe", "version": "1.0.0", "kind": "data",
        "title": "TSV → DataFrame",
        "accepts": ["text/tab-separated-values", ".tsv"],   # content types / extensions it reads
        "produces": "pandas.DataFrame",                      # the plugin's declared input type
        "params": [],                                        # optional (delimiter, sheet, …)
    }
    def load(self, source: Source) -> Any: ...   # source = bytes + filename + content type + params
```

- The user uploads whatever format works for them; the engine offers only adapters whose `accepts` match the file **and** whose `produces` matches the plugin's declared input type.
- Versioned so the user picks an adapter version, and the plugin manifest can record which it was validated against.
- Lifecycle: the worker (or a prep step) runs it **once** at run start to materialize the plugin's input.

### B.3 Resource adapters (LLM / external-resource plugins)

The plugin speaks a protocol; the adapter adapts the company's resource **to** that protocol. This absorbs the whole variety you listed without the plugin knowing.

```python
class ResourceAdapter(ABC):
    MANIFEST = {
        "name": "website-chat", "version": "0.1.0", "kind": "resource",
        "title": "Website chat (browser harness)",
        "protocol": "openai",         # what the plugin sees: openai | aisc | rest
        "capabilities": ["text", "history"],   # multi-turn / tools the adapter supports
        "session": "run",             # run | row — session scope for a stateful target
        "config": [{"name": "url", "required": True}, {"name": "token", "secret": True}],
        "params": [],
    }
    def open(self, binding: Binding) -> Session | None: ...       # optional; agent/stateful targets
    def call(self, session: Session | None, req: Request) -> Answer: ...   # per row/call
    def close(self, session: Session) -> None: ...                # optional
```

- `binding` = the AiComponent's `url` + secret fields + the project's allowlist/timeout.
- `req` = `{input, history, params, tools}`; `Answer` = `{answer, refused?, tool_calls?}` — the same shapes the interface already defines (`connections.check_history`, tool loops).
- **No `surface` field** (§9). There is one mechanism: the runtime runs a per-run **loopback door** serving the declared `protocol`, and points the plugin's declared env at it (`base_url`/`api_key`/`model`) — exactly how langbite/strongreject/promptfoo already configure OpenAI-compatible calls via env. The adapter is only the handler; it never implements HTTP. An adapter is needed **iff the target is non-native**.
- **Lifecycle:** `open`/`close` bound to the **session scope** (`run` or `row`), `call` per row — so an agent target can hold a session across turns.

### B.4 AiComponent mapping

| Resource | AiComponent | Adapter |
|---|---|---|
| OpenAI-compatible endpoint | `model`/endpoint: **url + api key** | none (identity `openai`) |
| Custom REST, with/without auth | `resource`: url (+ secret fields) | shipped `rest` / `rest-auth` |
| Job id + poll | `resource`: url | shipped `poll` |
| gRPC | `resource`: url | shipped `grpc` |
| **Website, no API (pilot)** | `resource`: **just the url** | **user-authored** class that drives a browser harness and presents `openai` to the plugin |

This is your pilot case exactly: one generic resource component (the website url), plus a Python class adapting it to an OpenAI-compatible **protocol** behind the door.

### B.5 Compatibility + the dropdown

A plugin's declaration already gives the needs: `@assesses` → `protocols` (resource) and the inputs' types (`@evaluation_input`). The engine computes the set of installed adapters that satisfy them:

- resource: `adapter.kind == resource` ∧ `adapter.protocol ∈ plugin.protocols` ∧ `plugin.needs ⊆ adapter.capabilities`;
- data: `adapter.kind == data` ∧ `adapter.produces == plugin.input.type` ∧ `adapter.accepts ∋ uploaded file`.

The UI shows that set as a dropdown, filtered by both the selected plugin and (for data) the chosen file. The choice is stored on the evaluation/input binding and recorded with the run.

### B.6 Distribution & authoring

- **Shipped library** (exhaustive, expanding): data adapters (csv/tsv/parquet/json → dataframe/list[dict]); resource adapters (openai, rest, a2a, oip, grpc, poll, and a browser-harness base).
- **User-defined bespoke**: a Python class dropped into a folder loaded by the manager (pilot-style), optionally with a UI to author/test it. **No user catalogue** of adapters.

### B.7 Loader changes (`aisc-plugin-manager`)

```python
Loader(...).list_adapters()                 # {name: {version: manifest}}
Loader(...).load_adapter(name, version)     # the adapter class/instance
```

Same scanning rules as plugins (local `adapters/` + devpi, digest/caching, `+local` versions), same "never dropped for a missing optional field" tolerance.

### B.8 Contrast with pilot

| | pilot | ours |
|---|---|---|
| Loaded by | `platform` service, `adapters/` folder, restart to load | **plugin manager** (local + devpi), like plugins |
| Spec package | folded into `platform_service/adapters.py` | **`aisc-adapter-interface`**, separate from the plugin interface |
| Kinds | one flat `call()` | **`data` (once) + `resource` (per row)** |
| Selection | one adapter per connection kind | **dropdown by plugin + input file** |
| Versioning | none | **versioned, plugin pins a range** |
| Runs in | platform process | **eval worker, beside the plugin** (Appendix A) |

### B.9 Open questions

- For a **native** target, keep the door always (hide the key / enforce the allowlist) or point the plugin straight at the endpoint with a run-scoped key? (§9.4; recommendation: keep the door.)
- A registry of `produces`/`input` type ids (so data adapters and plugins agree on names).
- Resource-adapter state: is `open`/`call`/`close` enough for an agent session across rows, and who owns its lifetime (the run or the row)?
- Validating/testing a user-authored adapter (UI wizard, a conformance test suite like `test_connection_adapter_calls.py`).
