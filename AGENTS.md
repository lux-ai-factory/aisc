# AGENTS.md

**Read [`ARCHITECTURE.md`](ARCHITECTURE.md) before changing anything structural.** It is binding. When a
task can be done by adding a second path or by extending the existing mechanism, **extend the existing
mechanism** — even if the second path is shorter.

If you believe an invariant must change, **stop and write an ADR** in [`docs/adr/`](docs/adr/) (template in
`ARCHITECTURE.md`). Do not implement against an invariant "to be sorted out later".

## The invariants (one line each)

- **I1 — a run is self-contained.** Hand the worker everything at dispatch; it must finish with the
  backend and platform **down**; the backend observes status by id; results are posted at the end.
  *Never add a mid-run call from the run path to a backend/platform endpoint.*
- **I2 — a door, not a credential.** A plugin never receives the assessed system's secret; it calls a
  door that lives **with the run**, withholds the key, enforces the allowlist, and scrubs.
- **I3 — one implementation per concern.** One project/identity model, one membership, one secret store,
  one project-DB path, one connection/adapter model (beside `AIComponent`). Extend backend/webapp; do not
  add a parallel model or app.
- **I4 — one app graph; features are flags, not modes.** No configuration may change `INSTALLED_APPS`,
  `MIDDLEWARE` or the URLconf. Toggle behaviour with a registered feature flag.
- **I5 — the domain is the model layer.** Own your tables via ORM models/migrations in your app; never
  query another app's tables with raw SQL; one migration tool.
- **I6 — one place cuts a version, and governed changes are ledgered.** Immutability is enforced in app
  code, not only in a DB trigger.
- **I7 — no secret leaves the point of use.** Scrub every outbound path (plugin, artifact, log, message).
- **I8 — new moving part ⇒ ADR.** A new service, database, datastore or top-level dependency needs an ADR
  with an owner, a cost, and a removal condition.
- **I9 — boundaries on the architectural axis, not the business domain.** A repo/app/service boundary is
  justified by a **layer** (presentation, API/domain, execution, analytics), a **published artifact** (an ABI,
  a public site, a registry), or the **composition root** (the parent repo — orchestration only, **no app
  logic**) — never a business domain. A domain is a *feature inside* `backend`/`webapp`/`eval`, not its own
  stack (no own frontend + API + DB + migrations).
- **I10 — the core never depends on the optional domains.** The core (projects, components/connections,
  plugins, evaluation, runs, results) MUST run with qualification / control-objectives / controls **absent**.
  Optional domains depend on the core; never the reverse. A lean install is a **profile** of flags, not a fork.
- **I11 — one container per deployable process.** A container is one long-lived service (layer, published, or
  infra). Migrations/init are **steps**, dev tools are **profiles**, a domain is **never** split across
  containers. (The deployment view of I9.)

## Before you propose a change

```bash
uv run --no-project --with pytest python -m pytest tests/architecture -q   # the architectural guards
```

A red guard is a **stop**, not a warning. If your change legitimately requires breaking an invariant,
the guard's allowlist entry plus the linking ADR is the only acceptable form.

## Map of the docs

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — **binding** invariants, enforcement, ADR process.
- [`docs/refactor-plan.md`](docs/refactor-plan.md) — **the phased implementation plan** and the
  invariant → guard → step spine. Start here to do the work.
- [`docs/unified-modules-and-pilot-brief.md`](docs/unified-modules-and-pilot-brief.md) — **the decisions**
  (D1–D12): the two-phase roadmap (`unified-modules` then `pilot`) and the five-step method.
- [`docs/architecture.md`](docs/architecture.md) — how AISC works (descriptive; subordinate to the above).
- [`docs/exploration-branches.md`](docs/exploration-branches.md) — how pilot branches are treated (features,
  not code).
- [`tests/architecture/`](tests/architecture/README.md) — **the gates**: one guard per invariant, and what is
  still to write.
- [`docs/adr/`](docs/adr/) — **the exceptions**: the only sanctioned way to change an invariant.
- [`docs/appendices/`](docs/appendices/) — per-step and per-concern detail.
- [`SCRATCH-platform-adapters/`](SCRATCH-platform-adapters/README.md) — **scratch design notes** (not
  binding): the case for consolidating the platform app, feature flags, and the adapter design.

## Working rules for agents here

The full loop is [`docs/refactor-plan.md`](docs/refactor-plan.md) §6. In short:

- **Port the need, not the code.** Don't port something because it exists — ask if it's needed, if it
  duplicates or overlaps existing code, and if an existing mechanism can be extended instead. Basic
  assumptions are fine; when the need is genuinely ambiguous, **ask a human** rather than port it.
- Prefer editing an existing module over adding a new one; prefer a model over a query; prefer a flag over
  a mode; prefer a local call over a network hop; prefer a step over a container.
- Do not silence or delete a guard to make a change pass; when a guard `xpass`es, remove its marker.
- Keep changes inside the app that owns the concern. If you are not sure which app owns it, ask.
- Update the nearest `README`/doc when you change behaviour — but never edit an invariant to match code;
  change the code or write the ADR.
