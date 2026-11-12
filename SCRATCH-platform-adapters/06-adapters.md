# Adapters — the concept, the kinds, and the door

> From `SCRATCH-platform-adapters-discussion.md` §5, §8 and §9. §5 is the original "adapters are a
> first-class shipped concept" argument; §8 and §9 are the current, agreed design (kinds, boundaries,
> the door). The spec draft is [`appendix-b-adapter-spec.md`](appendix-b-adapter-spec.md); the plan to
> build/see it is [`07-development-plan.md`](07-development-plan.md).

---

## §5. Adapters — a first-class, shipped concept (not a user catalogue)

**My position.** Adapters belong at a **similar level to plugins**. There should be **no catalogue of user-defined adapters**. Instead:
- the app **ships with an exhaustive, steadily-expanding list** of adapters;
- a genuinely bespoke system (like the pilot's) can't use a pre-made adapter, so the user **defines one** — either through a **UI** or by dropping a **Python implementation of a predefined interface into a specific folder**;
- optionally, a UI to help author/test that adapter.

**What pilot does (evidence).**
- Adapters are **platform-level** folders: `adapters/<folder>/adapter.py` defining a `PROTOCOL` dict and `call()`; the platform loads them (`platform/platform_service/adapters.py:1-16`).
- Shipped in the tree: **only `adapters/README.md`**; built-in protocols are just `openai, rest, a2a, oip` (`adapters.py:24`; `platform/project-template/0026_connection_adapter_kinds.sql`).
- Adding an adapter is **manual**: copy a folder in, then `docker restart platform`; a removed adapter leaves connections that fail until it returns.
- The wrapper is thin: the plugin calls `client.ask()` through the platform, which dispatches to the adapter's `call()`.

**Contrast with what I want.** I'd have the adapter run with the plugin (see §2) and expose a **stable, versioned adapter interface**, with a shipped library and a supported authoring path (UI and/or a folder), not run-as-platform-plugin + restart.

**Decision to force:** adapter execution location (§2), adapter interface contract, and authoring/shipping model (shipped library + supported bespoke path).

---

## §8. Adapters: kinds, boundaries, and placement (agreed 2026-11-10; surface revised 2026-11-11)

**Agreed direction.** Adapters are **first-class at the plugin level**; they run **in the eval worker beside the plugin**; they are **not plugins** (no assessment logic) and are **not run by the platform**. There are **two kinds** — `data` and `resource`. An "agent" is a **resource adapter that holds a session**, not a third kind. There is **no separate `surface` axis**: the boundary an adapter runs behind follows from its kind (§8.2, §9). The platform/backend only *lists* and *selects* adapters; the worker *executes* them.

> History: the earlier version of this section proposed a `http` vs `python` *surface*. §9 supersedes it. The short reason: plugins built on existing open-source projects (langbite, strongreject, promptfoo) reach a resource over HTTP and cannot be handed a Python object — so the only mechanism worth building for resources is a loopback HTTP door, and "in-process" is not a runtime mode but ordinary Python for first-party code.

### 8.1 Two questions, two kinds

Every adapter answers two questions, and those answers are what distinguish the kinds:

1. **When does it act?** once at run start, or on every call/row?
2. **What does it transform?** a data format → a value, or a protocol → a system?

(The earlier "third question" — *what state does it hold?* — is a **capability** of a resource adapter, not a kind; see §8.5.)

| kind | acts | transforms | input types |
|---|---|---|---|
| `data` | once, at run start | a file/format → the value the plugin expects | `dataset`, `model`, `datashape` |
| `resource` | per call / per row | a protocol ↔ a bespoke system | `resource`, `llm` |

### 8.2 Where they run — two boundaries, one rule

The boundary an adapter runs behind is fixed by **how the plugin consumes the input**. There are exactly two cases:

```
data / model inputs  (once, at run start)
  worker ──fetch bytes──▶ input/<file> ──▶ (plugin process) provider ──▶ get_input_data()
  boundary = a local file in the run workspace.            NO server.

resource inputs      (per call)
  plugin ──HTTP──▶ worker door (the plugin's protocol) ──▶ { built-in client | adapter } ──▶ target
  boundary = a loopback HTTP endpoint ("the door").
```

- **data** is a pure transform of the run's own input → it stays in the plugin process, exactly where `input_providers` run today (`plugin_runtime.py: set_input_content → get_input_data`).
- **resource** is per call → the door is a **loopback endpoint in the worker**, not a round-trip to the backend, so it does not carry the cost §2 objected to.
- The platform/backend owns the connection (url + secret), the allowlist, and the adapter **listing/compatibility** for the UI; it is no longer the runtime proxy.

### 8.3 `data` adapters, concretely

`file bytes (+ filename/content-type/params) → the value the plugin's input expects`. No network, no secrets, ideally pure and cacheable. **This generalizes today's `input_providers`** (`csv/parquet/json/onnx`), which are currently *hard-wired* on the plugin via `@evaluation_input(input_provider_class=…)` and are **not selectable**.

What changes is only **selection**: the plugin stops pinning a concrete file class and declares an abstract **`produces`** id; the **data adapter** chosen from the dropdown (matched to the file's format) converts the actual file → that shape. The provider mechanism is **kept** — it *is* the data adapter, and it still runs in the plugin process.

### 8.4 `resource` adapters, concretely

Presents a bespoke system as a protocol the plugin speaks. Holds the binding (url + secret fields + allowlist/timeout). Three distinct things, worth naming:

| thing | what it is |
|---|---|
| **connection** | the binding behind the door — url + secret + protocol; a *native* protocol has a built-in client |
| **adapter** | a protocol implementation for a **non-native** target (installed code) |
| **door** | the worker's per-run endpoint the plugin always calls |

**An adapter is needed iff the target does not speak a protocol the runtime supports natively.** A standard OpenAI or REST endpoint is native: the door is backed by the built-in client and the plugin is unchanged; only a bespoke target needs an adapter behind the door. See §9.

### 8.5 "Agent" = a resource adapter with a session

"A multistage process that feeds itself" describes *how the adapter talks to the target*, not what the plugin sees. Two independent things can be agentic:

- **the target is an agent** (black box, remembers, runs tool loops internally): the plugin sends one turn per call; the adapter handles submit→poll→collect and/or holds the conversation. The built-in `a2a` client already does exactly this.
- **the plugin is the agent** (drives the loop): the plugin sends `history` and gets `tool_calls` back; the adapter just needs `history`+`tools` and stays stateless.

So a resource adapter declares `protocol` (what the plugin sees), `capabilities` (`text`/`history`/`tools`/`logprobs`; the engine already computes `needs ⊆ capabilities`), and an optional **lifecycle** `open()`/`close()` with a **session scope**: for a stateful target, one session per **run** (conversation testing) or per **row** (table-scoring). Declare it; default **per run** for conversation testing, **per row** for table-scoring (answers B.9's open question).

### 8.6 How they connect to the rest of the app

| Concern | Where it lives | Who reads it |
|---|---|---|
| Adapter code | `aisc-adapter-interface` + adapter packages | loader |
| Find/load | `aisc_plugin_manager.Loader` (+ `list_adapters`/`load_adapter`) | worker (execute) · backend/platform (list for UI) |
| Binding (url + secrets) | the connection / AiComponent | secret store → worker at run start |
| Compatibility | plugin declaration (`protocols`, `needs`, input type) ∩ adapter manifest (`protocol`, `capabilities`, `accepts`/`produces`) | engine, to build the dropdown |
| Selection | stored on the evaluation/input binding | engine; recorded on the run |
| Allowlist / timeout | project settings | adapter runtime, enforced at call time |
| Run record | adapter name+version actually used | engine / report |

The engine only ever *lists* and *selects* adapters; the worker *executes* them.

### 8.7 Decisions (all agreed 2026-11-10; #2 revised 2026-11-11)

1. **Two kinds, not three** — `data`/`resource`; "agent" = resource + session/capabilities.
2. **No `surface` axis.** The boundary follows the kind: `data` = in-process local file; `resource` = loopback HTTP door. (Supersedes the earlier "`http`-first / `python` escape hatch" framing; see §9.)
3. **Session scope** declared per adapter (run vs row).
4. **A registry of `produces`/input type ids**, so data adapters and plugins agree on names.
5. **Shared loader** so the backend/UI can enumerate adapters without importing the worker runtime.
6. **An adapter is needed iff the target is non-native**; a native target uses the built-in client behind the door (see §9.4).

---

## §9. The boundary: the door (resource) vs the local file (data)

This replaces the earlier "`http` vs `python`" section. There is **one mechanism** for reaching a resource and **one** for feeding data, and neither is a per-adapter choice.

### 9.1 The door (resource adapters)

The **runtime** — not the adapter author — runs a per-run **loopback HTTP server** in the worker that speaks the protocol the plugin declared. The plugin is an ordinary HTTP client pointed at it by environment variables; **nothing in the plugin changes**. The adapter is only the **handler** (`open`/`call`/`close`); it never implements HTTP. So "does the adapter run a server?" — no: **the runtime runs one server for the run; the adapter is what it dispatches to**.

```
today:  plugin ──HTTP──▶ platform door ──▶ connection / adapters.call()
new:    plugin ──HTTP──▶ worker door   ──▶ { built-in client | adapter }
```

The door reuses the existing `connection_facade` / `routes/facade.py` translation (`openai`/`rest`/`a2a`/`oip` ↔ the core shape `{input, history, params} → Answer`), now **inside the worker**. The plugin stays a **client subprocess** connecting to loopback (today it connects to `PLATFORM_URL`); only the host and the thing behind it change.

### 9.2 Example — a resource adapter behind the door (website chat)

The pilot case: a website chat with no API, presented to an **unmodified** OpenAI-style plugin. The adapter core is protocol-agnostic; the door does the translation:

```python
MANIFEST = {
    "name": "website-chat", "version": "0.1.0", "kind": "resource",
    "protocol": "openai", "capabilities": ["text", "history"],
    "session": "run",                                    # one session for the whole run
    "config": [{"name": "url", "required": True}, {"name": "login", "secret": True}],
}

class Adapter(ResourceAdapter):
    def open(self, binding):                       # once per run
        return WebsiteSession(binding.config["url"], binding.config["login"])
    def call(self, session, req):                  # per turn; core shape
        session.send(req["input"])
        return Answer(text=session.read_reply())
    def close(self, session):
        session.quit()
```

The worker's door serves `POST http://127.0.0.1:<port>/chat/completions` (translating OpenAI ↔ core) and sets for the plugin:

```
AISC_TARGET_BASE_URL=http://127.0.0.1:<port>
AISC_TARGET_API_KEY=<run token>
AISC_TARGET_MODEL=website
```

Plugin: **unchanged** (e.g. langbite).

```
langbite ──OpenAI JSON──▶ 127.0.0.1:<port> (door) ──core──▶ Adapter.call ──▶ website
                          ◀── OpenAI JSON ───────────── Answer ◀──
```

`WebsiteSession` is where the website is actually driven — a browser, an HTTP session, whatever the adapter wants. §10 UC2/UC3 build a mockable version (see [`07-development-plan.md`](07-development-plan.md)).

### 9.3 The local file (data adapters)

No server. The worker fetches the bytes, writes them into the run workspace, and the plugin process reads the file and builds the value via its provider — exactly as `plugin_runtime.py` does today:

```
worker ──get_dataset_file_content──▶ input/<file> ──▶ plugin.set_input_content(bytes)
                                                       └─▶ provider.get_data()   (in the plugin process)
```

The **data adapter** is the selectable, `produces`-typed generalization of that provider. It never touches HTTP. This is why data keeps working for unmodified file-based plugins: they already read local inputs, so there is nothing to route.

### 9.4 Shared runtime rules, and the one open policy

In both cases the runtime owns the lifecycle (`open`/`close`), the binding (url + secrets), the allowlist/timeout and secret scrubbing.

**Open policy question:** for a **native** target, do we (a) keep the door always — hides the key, enforces the allowlist, matches today's `@system_under_test` env injection — or (b) point the plugin straight at the endpoint with a run-scoped key and drop the hop? Recommendation: **(a) keep the door always** (loopback-cheap, plugin unchanged, key never enters the plugin process). Not forced by adapters; decide explicitly.

---

*The spec draft (manifest fields, loader changes, compatibility rules) is
[`appendix-b-adapter-spec.md`](appendix-b-adapter-spec.md); the usage cases and mocks that make it
visible are [`07-development-plan.md`](07-development-plan.md).*
