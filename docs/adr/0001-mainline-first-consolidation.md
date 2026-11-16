# 0001. Mainline-first consolidation

**Status:** accepted
**Invariant:** I3 — one implementation per concern (affirmed)
**Owner:** AISC architecture owners
**Date:** 2026-11-16

## Context

The repository carries exploration branches — `pilot`, `feat/unified-modules` and `feat/unified-app` —
plus a `feat/unified-app` parent tree that would collapse the composition root into a single branch. They
were built to prove *behaviour*, not to become a release line. Treating any of them as a merge source
imports a second architecture: two deployment contracts, two ledgers, two project-DB paths (**I3**, **I4**,
**I5**). The main line is the only line that ships.

## Decision

Consolidate on the main line, first, one concern at a time:

- The frozen unified-app **submodule pins** are accepted as *inputs* to integration; they are merged onto
  the current `master` of each submodule, and the result is pinned in a **main-based** parent.
- The unified-app **parent tree** is reference only; it is never merged.
- `pilot` and `feat/unified-modules` are never merged; their features are **ported** — behaviour, not code
  — against the main architecture (see `unified-modules-and-pilot-brief.md`).
- A working `master` is never fast-forwarded or reset to a pilot/exploration branch.

## Consequences

- **Cost:** each feature is re-implemented against main rather than merged, so consolidation is slower than
  a merge and needs per-feature tickets and tests.
- **Guard:** the `tests/architecture/` I3 guards (`plugin-interface` independence, no backend import in the
  worker, one project-DB module, one ledger, acyclic shared ABIs).
- **Removal condition:** none — this is a standing policy, not a waiver.
