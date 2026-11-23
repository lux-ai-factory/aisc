# Exploration branches (pilot projects)

> **Agreed in the platform/adapters meeting, 2026-11-11.** This is a policy, not a description: it says how
> the project treats branches such as `origin/pilot` and `origin/feat/unified-modules`.

## The concept

Branches like `origin/pilot` and `origin/feat/unified-modules` are **exploration branches**. They existed to
explore features for **short-lived pilots**. They are **not release lines, and they are not merge sources**.

Think of them as **scratch projects at the scale of the entire application** — the same role a scratch file
plays for one design question, but spanning the app instead of a single note:

- A pilot is a **discussion point**. It shows *what a feature could be*, with a real (if rough)
  implementation you can click through. It communicates **behaviour and requirements**, not architecture.
- When a pilot feature is folded into a main release, **the implementation and the architecture may change
  completely.** "Folding in" means *deliver this behaviour*, not *merge this code*.
- Therefore: **do not fast-forward or merge a release to a pilot branch.** Extract features one at a time
  and implement each against the release's own architecture ([`../ARCHITECTURE.md`](../ARCHITECTURE.md)).

## How to use a pilot

1. **Read it for what it does** — the screens, flows and behaviour it enables. That is the specification.
2. **Treat its code as evidence of feasibility**, not a design to preserve.
3. **Re-implement inside the main architecture.** If the pilot's approach conflicts with an invariant, the
   invariant wins — or write an [ADR](adr/README.md).
4. **Record the feature, not the branch.** The deliverable of a pilot is a validated feature and a lesson,
   not a second architecture.

## Why this matters

- It resolves the "big merge / reset" question: a reset to a pilot branch is a **rewrite**, to be judged
  **feature by feature** against this policy (see [`SCRATCH-platform-adapters/01-background.md`](../SCRATCH-platform-adapters/01-background.md) §0).
- It keeps the main line coherent: a pilot contributes behaviour, never a parallel architecture to keep in
  step. This is the branch-scale form of the "one implementation per concern" invariant
  ([`../ARCHITECTURE.md`](../ARCHITECTURE.md) I3).
- It tells a contributor (or an agent) the right reflex when reading a pilot: **learn the feature, then
  build it properly here** — do not copy the pilot's structure.
- It applies to **module boundaries too**: a pilot's submodule split is not a design to preserve either. A
  boundary kept "so the service can be replaced" must be justified by *real* independence — an **architectural
  axis** (a layer), a **published artifact** (an ABI, a public site, a registry), or the **composition root**
  — not a business domain (see [`unified-modules-and-pilot-brief.md`](unified-modules-and-pilot-brief.md) D8).

## Frozen pilot reference (pinned 2026-11-16)

The pilot is a **moving branch**: it has kept changing since this refactor began. This work is pinned to the
pilot snapshot it started from and **ignores later pilot changes**:

- pilot reference commit: **`6197dc1aff55a582f5bdb39b10b0910b81b7a07b`** — "The audit's design changes: one way
  to call a service, open a project database, decide who the caller is, keep a secret, write a ledger event,
  run a plugin, build a launcher page and run a suite";
- `feat/unified-app` frozen pins: see [the plan](refactor-plan.md) §3 (backend, webapp, eval,
  plugin-interface, plugin-manager).

Read that snapshot for behaviour; do **not** follow `origin/pilot` HEAD. Any later pilot work is a separate
proposal, reviewed on its own.

## Upgrade scope (2026-11-16)

Only existing `master`/`main` installations need data-preserving upgrades. Pilot/unified-modules/unified-app
data requires no importer. Implement on main's existing schema and migration history. See
[ADR 0001](adr/0001-mainline-first-consolidation.md).

## Unified-app is the frozen selective integration source (ADR 0003)

`feat/unified-app` is explicitly selected as a **frozen merge source** for backend, webapp, eval,
plugin-interface and plugin-manager at the pinned snapshot in the plan. Start from main in these
repositories and pin their resulting commits from a main-based parent; do **not** merge unified-app's
parent tree or the qualification/controls legacy app histories. The latter, pilot and unified-modules
are behaviour references, not wholesale merge sources. Review later changes explicitly.

Then compare the merged product against pilot and port the missing retained behaviours, including the
full reporting/composer flow, evidence and analytics. Extend the merged backend/webapp/ORM mechanisms;
preserve the pilot launcher's visual design, navigation and four-step assessment flow in React as
specified in the plan §2.1. Reuse unified-app functionality beneath that presentation;
do not copy pilot's platform, per-project databases or separate audit stack. Execution improvements
follow the feature port except for the immediate plugin child-environment allowlist; project isolation
is ORM-enforced and deny-by-default. Preserve mainline data, not unshipped unified-app migration history.
The feature matrix and acceptance gates are in [the plan](refactor-plan.md), under
[ADR 0003](adr/0003-frozen-unified-app-port-and-worker-boundary.md).
