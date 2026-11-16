# Development plan — visible use cases, a mock kit, and tests

> From `SCRATCH-platform-adapters-discussion.md` §10. The goal is to make the adapter design
> *understandable* by building a small covering set of use cases through the real UI, driven by mocks
> that serve as both manual fixtures and automated tests. Related: [`06-adapters.md`](06-adapters.md)
> (the design).

---

## §10. Development plan: visible use cases, a mock kit, and tests

### 10.1 Goal & principles

- Build the idea the way it will be *understood*: **a small set of use cases that together cover every combination** of plugin type × input type × adapter kind × target type, each set up through the **real UI** and run for real.
- **Mocks drive the real UI.** Every target and every input is a tiny mock that records what it received, so the same fixture is (a) clickable by a human in the UI and (b) assertable by an automated e2e test — no divergence between the two.
- **Ship understanding early.** Prove the *UI concept* — a compatible adapter appears in a dropdown, selecting it changes the run, the run records which adapter was used — on the pilot's existing mechanism first, then migrate execution to the agreed worker placement.

### 10.2 The coverage matrix

Axes: plugin (`ML` / `LLM`) × input (`dataset`/`model`/`datashape`/`llm`/`resource`) × adapter (`—`/data/resource) × target (`—`/native-openai/native-rest/bespoke/agent).

Not every cell is meaningful. This minimal covering set exercises them all:

| UC | plugin | input | data adapter | resource adapter | target | boundary proved |
|---|---|---|---|---|---|---|
| 1 | LLM | resource | — | none | native openai | door + built-in client (no adapter) |
| 2 | LLM | resource | — | http | bespoke website | resource adapter behind the door |
| 3 | LLM | resource | — | http + session | agent (submit/poll) | session scope, multistage target |
| 4 | ML | dataset | csv→rows | — | — | data adapter, selectable |
| 5 | ML | model | onnx | — | local | model input, local target |
| 6 | ML | datashape | — | none | native rest | datashape input, card target |
| 7 | ML | dataset | json→rows | none | native openai | data + resource per row (`@dataset_through_target`) |
| 8 | LLM | dataset | csv→rows | http | bespoke website | all four at once |

### 10.3 The mock kit

Three families, all tiny and transparent; they live in the repo's example/fixture area and ship with a compose profile so they are reachable from the stack.

**Mock plugins** (one per shape):
- `mock-llm` — LLM plugin: `@system_under_test`; sends one prompt; trivial metric (e.g. `reply_len > 0`).
- `mock-table` — ML plugin: `@dataset_through_target`; sends each row; trivial metric (e.g. `all_rows_answered`).
- `mock-model` — ML plugin: reads a model + a dataset; predicts; trivial metric (e.g. `rows_scored`).

**Mock adapters** (one per kind / capability):
- `rows-csv`, `rows-json` — data adapters (`kind: data`), `produces: table.rows`.
- `website-chat` — resource adapter (`protocol: openai`, `session: run`).
- `agent-run` — resource adapter (`protocol: openai`, `session: run`, `capabilities: [text, history]`; drives submit→poll→collect internally).

**Mock targets** (one per target type), each recording requests and returning a deterministic, identifiable answer:
- `mock-openai` — native OpenAI-compatible.
- `mock-rest` — native REST.
- `mock-website` — a JSON endpoint deliberately **not** OpenAI-shaped (forces an adapter).
- `mock-agent` — submit → `202 {job}`, poll → `running`/`done`.

### 10.4 User flow (identical shape for every UC)

1. **Adapter present** — put the adapter package where the loader sees it; it appears in the adapter list. (Initially a folder + restart, matching today's `adapters/README.md`; later install from the catalogue.)
2. **Connection** — Manage → Components and connections → pick the protocol (or the adapter's protocol); enter url + secret pointing at the mock target.
3. **Evaluation** — pick the plugin; the form shows its inputs (and its declared `protocols`/`needs`); bind each input (dataset/model from storage, or a connection/resource) and, where a compatible adapter exists, **pick it from the dropdown**.
4. **Run** — watch progress; view results.
5. **Inspect** — the run record names the adapter + version actually used.

Only steps 2–3 vary per UC (target type, whether a dropdown appears, which adapter).

### 10.5 Test plan

For each UC, three levels, all driven by the same mocks:

- **Unit** — adapter contract: the loader lists it with the right manifest; `call()` with a fake binding returns the expected `Answer`; a data adapter maps the fixture file → the expected `produces` shape.
- **Compatibility** — the dropdown shows the adapter for a plugin whose declaration it satisfies, and hides it otherwise (protocol ∩ capabilities; `produces` ∩ input type).
- **Manual + e2e (same fixture)** — run the UC in the UI; assert the metric and, crucially, that **the mock target recorded the call the adapter should have made** (so we prove the adapter actually drove the target, not just that the run passed). The e2e automates exactly the clickthrough.

### 10.6 Build order (each step shippable and demonstrable)

- **Phase 0 — see it in the UI (pilot mechanism).** Stand on the pilot's existing platform-level adapter path (`platform/platform_service/adapters.py` + the adapter dropdown) to get UC1–UC2 visible end-to-end with the mocks. Goal: the UI concept, before any placement change.
- **Phase 1 — the door, native only.** Relocate the facade into the worker; the door serves a native connection with the built-in client (UC1). Prove the plugin is unchanged.
- **Phase 2 — resource adapter behind the door.** UC2 (`website-chat`, no session), then UC3 (`agent-run`, session scope).
- **Phase 3 — data adapters selectable.** Generalize `input_providers`; `list_adapters`/`load_adapter`; the `produces` registry; the dropdown (UC4–UC5).
- **Phase 4 — combine.** UC6–UC7 (datashape, per-row resource), then UC8 (all four).
- **Phase 5 — polish.** Compatibility filtering in the dropdown, run-record of adapter+version, the adapter install path, docs.

Each phase ends with the mock kit green: unit + compatibility tests pass, and the UC is clickable in the UI.

---

## Interaction with the consolidation plan (§11/§12)

These phases are deliberately **backend/webapp-shaped** (§11): Phase 0–2 touch the same adapter path that
§11.6 step 1 moves into the backend beside `AIComponent`, and the UI work lands in the webapp. Where a
phase would otherwise add platform-only code, prefer the backend/webapp seam so the phase does not have
to be re-done when the platform app retires.

*See [`08-meeting-agenda.md`](08-meeting-agenda.md) for the decisions these phases need.*
