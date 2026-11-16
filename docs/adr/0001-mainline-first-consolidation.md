# 0001. Mainline-first consolidation

**Status:** proposed
**Invariant:** I9 — changed (process decision; the layer/domain split is unchanged)
**Owner:** DOC-01 (#121) — drafted by INT-01 as a placeholder for the missing mandated input; NOT accepted
**Date:** 2026-11-16

## Context

The unified-app work has grown on a parallel route (`feat/unified-app`), with the parent tree held at
`256712e`. The architecture says business domains are *features inside the layers* (I9), and the
consolidation must not create a second route to main. Two routes were possible: merge the unified-app
**parent** tree wholesale, or land the layer changes on the current mainline.

## Decision

Consolidate **mainline-first**. Every change lands by cutting a short-lived integration branch from the
current `master`/`main` in each submodule repo, deliberately merging the frozen layer commit (never
`submodule update --remote`), resolving conflicts in favour of mainline fixes, and pinning the resulting
merge commits in a **main-based** parent. The unified-app parent tree (`256712e`) is a **reference**, never
a merge instruction. `apps/qualification` and `apps/controls` are read for behaviour only and their branch
history is not merged.

## Consequences

- **Cost:** conflicts are resolved per-repo rather than once; the main-based parent must keep main's
  published compose, local-build overlay, compose-validation CI, e2e and `DEVELOPER_GUIDE.md`.
- **Guard:** none directly — the mechanics are asserted by the integration ledger on #103, not by a
  `tests/architecture/` guard.
- **Removal condition:** standing decision; superseded only by a later ADR that changes the consolidation
  strategy.
