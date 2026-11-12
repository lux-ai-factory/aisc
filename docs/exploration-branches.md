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
  — not a business domain. Whether the pilot's boundaries should stay is **under discussion** (see
  [`unified-modules-and-pilot-brief.md`](unified-modules-and-pilot-brief.md) D8).
