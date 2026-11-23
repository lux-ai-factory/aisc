# 0009. One component model, one adapter mechanism, and the run door now

**Status:** accepted
**Supersedes:** in part [ADR 0003](0003-frozen-unified-app-port-and-worker-boundary.md) decision 4 (the
deferral of the I2 run-local door for **assessed and instrument endpoints**). I1 self-contained dispatch
stays deferred.
**Invariant:** I3 — wording changed ("one connection/adapter model beside `AIComponent`" → "one component
model and one adapter mechanism"); I2 — delivery brought forward for endpoint inputs; I7 — target
credentials leave the plugin environment.
**Owner:** AISC project owner (implementation owners assigned per phase)
**Date:** 2026-11-20

## Context

The frozen integration branch has four overlapping ways to turn "what the user has" into "what a plugin
can use":

1. `aisc_plugin_interface.input_providers`: a plugin hard-wires one file reader per input.
2. `poc/input-adapater-chain` (unmerged, across five repos): user-selected, ordered chains of
   `BaseInputAdapter`s that convert file formats. Plugin-manager discovers them.
3. `aisc_backend/adapters` (CON-01) with `Connection`, `Helper` and `RunBinding`: protocol adapters that
   run **only in the backend** ("Test connection"). The run does not use them. The worker receives the
   `llm` component's URL and decrypted key and hands both to the plugin.
4. `model_session` on the exploration branches: a parallel session API for ML models.

As a result, an LLM is represented both as an `llm` component and as an `openai` connection, a judge is
a third thing (`Helper`), and a run records its target twice (`EvaluationInput` and `RunBinding`). Every
new protocol needs new schema columns (`Connection.model`, `.path`, `.body_template` …). Plugins that
wrap open-source LLM libraries are handed the real target key, which those libraries may log.

The use cases (tabular ML on files or served models, LLM benchmarks against OpenAI-compatible APIs,
agents, bespoke REST APIs and web UIs, with judges) are recorded in
[`../component-adapter-plan.md`](../component-adapter-plan.md) §1, along with the decisions D-1 to D-20
taken in discussion.

## Decision

1. **One component model.** `AIComponent` is every thing a run can use. Its kinds are file
   (`dataset`, `model`), derived (`datashape`), reference (`resource`: a plain string the plugin
   resolves itself, unchanged), and **`endpoint`**: a URL, a secret in the existing secret store, a
   protocol, an adapter id and version, and that adapter's config as JSON. `llm` becomes an `endpoint`
   with protocol `openai-chat`. A component belongs to a project, and optionally to its `AISystem`.
   Judges, helpers and the AI assistant's model are project-level endpoint components.
   **`Connection`, `Helper` and `RunBinding` are removed.** `AllowedHost` stays.
2. **One adapter mechanism**, in `aisc_plugin_interface.adapters`. That subpackage holds the base
   classes, the format/protocol registry, the compatibility rule, the presets and the standard library.
   It has its own `ADAPTER_ABI_VERSION`. There are two kinds:
   - **data**: a file format → the value a slot accepts. Runs once, in the plugin process.
   - **endpoint**: a target's protocol → the protocol the plugin speaks. Runs per call, behind the door.

   Formats, protocols and adapter ids are **registry strings, not schema choices**. Adding one is a code
   registration, not a migration. Plugin-manager discovers adapters in any package, including plugin
   packages (a plugin may ship its own), and every adapter is offered wherever its types fit. One
   adapter per binding: no user-built chains. The input providers become the standard data adapters,
   the CON-01 `openai`, `oip`, `rest` and `a2a` adapters become the standard endpoint adapters, and
   `model_session` is not ported.
3. **The role is on the slot, not on the thing.** `@evaluation_input` gains `accepts`, `role`
   (subject/input/instrument), an optional default or required `adapter`, and how the plugin is handed
   an endpoint (in its input value and/or declared env vars). `EvaluationInput` is the single binding,
   and it records the chosen data adapter and the endpoint's provenance (URL, adapter id and version,
   and a config hash with secrets excluded). The existing `input_type=` and `input_provider_class=`
   declarations stay valid as shorthands.
4. **The run door, now.** For every endpoint bound to a run, the worker starts a loopback door
   (`127.0.0.1`) in a subprocess inside the run's plugin environment. The door holds the real secret,
   enforces the allowlist and timeouts, and scrubs responses. The plugin receives the door URL and a
   per-run token **in place of** the real URL and key, in today's `LLMConfig` shape and the same
   `AISC_SECRET_*` name. Existing LLM plugins therefore run unchanged. A standard OpenAI-compatible
   endpoint uses a passthrough adapter: the door adds no conversion, only the key swap, the allowlist,
   scrubbing and provenance.
5. **Trust stays as it is.** Plugins and adapters are first-party code. No sandbox, review gate or trust
   warning is added. The door exists for uniformity, the allowlist, provenance and keeping keys out of
   third-party libraries' logs. The door subprocess gets the ADR 0003 child-environment allowlist; the
   target secrets reach it on stdin, and worker credentials never do.
6. **The UI follows the task, not the tables.** Simple preset forms ("Add LLM", "Add agent",
   "Add model API", dataset and model file) cover the common cases, and "Custom" opens the
   adapter-plus-config form. Forms are rendered from each adapter's pydantic `Config` schema.
7. **Out of scope:** a first-class web-chat/playwright adapter (web UIs are custom adapters), HTTP
   job/poll mode, stateful agent sessions, the `predictor` value type, plugins that read a target URL
   from their own config, adapter sandboxing, and I1 self-contained dispatch.

On acceptance:
- I3 in `ARCHITECTURE.md` and AGENTS.md read "one component model and one adapter mechanism".
- The I2 delivery-scope paragraph names this ADR and drops the target-credential exception for endpoint
  inputs.
- Brief D5's "connections and adapters … beside `AIComponent`" is annotated with a pointer to this ADR.

## Consequences

- **Cost:** a model change in core (an `AIComponent` field set and an `EvaluationInput` binding, three
  tables dropped), one mainline data migration (`llm` → `endpoint`), a published-interface minor
  release (`aisc-plugin-interface` 0.5.0, plus a plugin-manager release), a new door runtime script in
  eval, and reworked webapp pages. There is no new service, container or datastore. The endpoint
  adapters need `httpx` (already used by backend and plugin-manager). It goes in an optional
  `aisc-plugin-interface[endpoint]` extra, following the `[report]` precedent, so the base install stays
  pydantic-only. The door uses the standard library's `http.server`. The stack therefore gains no new
  top-level dependency (I8).
- **Catalogue LLM plugins** that take the target URL and key in their own plugin config (promptfoo,
  langbite, strongreject, ragas, agentdojo, MLA-BiTe) keep working as they do today. They gain the door
  only once they are converted to declare an endpoint slot. That conversion is plugin-repo work tracked
  in the implementation plan, not a gate for this ADR.
- **Guard:** none added to `tests/architecture` (AGENTS: no checker per invariant). Behavioural tests
  replace one: a run against a mock target asserts that the target sees the real key and the plugin
  environment and input do not.
- **Removal condition:** this ADR is not a waiver. Revisit it if a target cannot be expressed as one
  endpoint adapter behind the door (for example, stateful agent sessions need door-side state the
  adapter API cannot hold). Extend the adapter API in that case; do not add a parallel model.
