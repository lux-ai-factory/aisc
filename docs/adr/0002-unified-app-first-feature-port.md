# 0002. Merge unified-app first, complete the feature port, then improve execution

**Status:** superseded by [ADR 0003](0003-frozen-unified-app-port-and-worker-boundary.md)
**Invariant:** I1/I2 and the existing plugin-execution aspect of I7 temporarily waived;
I3/I5 project isolation enforced in the ORM; I9/I11 consolidation retained
**Owner:** AISC maintainers
**Date:** 2026-11-16
**Supersedes:** ADR 0001's execution delivery scope and execution-baseline expiry only;
its audit, mainline-upgrade, license and isolated-cache decisions remain accepted.

## Context

Review of `feat/unified-app` found substantial reusable backend/webapp consolidation on mainline
ancestry. The owner chose to start from main/dev, merge that work, then port the remaining pilot
features into the agreed architecture. The owner explicitly deferred improvements to how plugins
execute until after the merge/port, accepted ORM-level project isolation, retained the versioning
corrections, and selected pilot as the source of reporting features.

## Decision

- Cut integration branches from current `master`/`main`, or `dev` containing that mainline baseline,
  in the parent and affected layer/shared repositories. Merge `feat/unified-app` there, reconcile
  mainline changes, and pin the resulting submodule commits. Then port the remaining pilot features.
  Pilot/unified-modules remain feature references, not wholesale merge sources.
- Only existing mainline installations require data-preserving upgrades. No exploration-branch
  database importer is required, including for `feat/unified-app`.
- Preserve the working main/unified-app plugin runtime during the merge/port. Self-contained
  dispatch, backend-down completion, a run-local credential-withholding door, runtime environment
  isolation and broader execution hardening are **post-port work**, not consolidation exit gates.
  I1/I2 remain the destination design. The I7 exception covers inherited runtime credential exposure;
  it does not permit new secret exposure in the feature port's APIs, logs, artifacts or reports.
- Port required connection/adapter functionality through the existing execution/interface mechanisms.
  Relocate only what is needed for feature parity and removal of duplicate platform/domain services;
  do not make an execution redesign a prerequisite. Do not transplant the separate platform stack.
- Enforce project ownership and permissions through the **one Django ORM/access mechanism**, covering
  old core endpoints as well as new domains. PostgreSQL RLS is not required for this refactor. Project
  isolation itself remains required, including related-object writes and downloads.
- Keep explicit publish and immutable published snapshots, one assessed-system identity, and one audit
  writer. Repair unified-app's membership/versioning gaps before relying on those contracts.
- Use **pilot reporting** as the functional source: composer/layouts, blocks, PDF/Word, version and
  evidence selection, stored documents and provenance. Extend/reconcile unified-app's report models
  and UI into one backend/webapp feature. Fold data access into ORM-owned snapshot assembly; retain
  useful renderer/plugin code without a second report database, API, UI or audit path.
- Preserve the agreed layer/published-artifact boundaries, optional-domain flags, Superset analytics
  and isolated cache, simple deployment and main's best-effort immudb auditing.

## Consequences and removal conditions

- **Cost:** runs continue to depend on the backend and may expose credentials through the inherited
  plugin environment. ORM isolation relies on every public entry point applying the shared access
  rules. Document these limits; do not claim backend-down execution or database-enforced tenancy.
- **Guard allowlist:** the named calls in
  `tests/architecture/test_invariants.py::test_i1_worker_does_not_fetch_from_backend_midrun` remain
  expected failures under this ADR **until the post-port execution milestone**, rather than expiring
  at consolidation completion. New detected findings still fail. When landing the suite on the
  merged tree, explicitly reconcile the reviewed main/unified-app call locations with the old pilot
  baseline; do not blindly copy the pilot baseline or add blanket skips.
- **Other baselines:** duplicate database paths, deployment modes, domain stacks and step containers
  still expire at consolidation completion. Intermediate integration debt must be named and linked;
  a merge is not a claim that the feature branch already meets all target invariants.
- **Removal condition:** retire the execution waiver when a real run completes with backend/platform
  unavailable after dispatch, uses the run-local door without plugin-held target credentials, and
  passes environment/scrub checks. Revisit RLS only if later isolation requirements call for it.
- No new service, datastore or top-level dependency is authorised by this decision. Any such addition
  still needs its own cost/owner/removal decision under I8.
