# 0003. Frozen unified-app integration and immediate worker environment boundary

**Status:** accepted
**Supersedes:** [ADR 0002](0002-unified-app-first-feature-port.md); retains its compatible
decisions, including deferring self-contained dispatch and the run-local door
**Invariant:** I1/I2 execution redesign deferred; I3/I5 one model and ORM access; I7 worker credentials must not enter plugin subprocesses now; I8 renderer-dependency decision required before new production dependencies
**Owner:** AISC project owner (implementation owners assigned per issue)
**Date:** 2026-11-16

## Context

The project owner approved the reviewed `feat/unified-app` commit pins as the freeze point; nobody has
deployed unified-app with data requiring preservation. Mainline deployments still require an upgrade.
Review found that unified-app's eval worker uses `os.environ.copy()` to spawn arbitrary catalogue
plugins: `DJANGO_SECRET_KEY`, `INTERNAL_API_KEY` and registry credentials can reach the plugin. Deferring
that exposure until a full run-local door exists would defeat project isolation. Review also found that
the unified-app parent deletes main's published compose, e2e tests and operational guides; merging it
wholesale would require rebuilding them. The owner wants to retain functionality, investigate it, and
strip only proven duplicates later. Pixel-perfect visual testing is not required.

## Decision

1. **Freeze sources.** Use the reviewed parent `256712ef2710a038fbdd86a6718d6d16aab766c4` and
   submodule pins in the plan as the **integration input**, not a moving branch tip. Coordinate further
   author work as explicit reviewed follow-up commits. Preserve the pilot launcher as UI reference.
2. **Main parent; selective merges.** Begin with main/master in the parent. Do **not** merge the parent
   unified-app tree wholesale: retain main's published compose, e2e suite, CI, developer guides and
   `env.example`. Merge the frozen unified-app branches into main in **backend, webapp, eval,
   plugin-interface and plugin-manager** only, reconcile mainline work, then pin those resulting
   commits in the parent. Qualification and controls branch tips (and their legacy Next.js/Prisma
   stacks) are reference material, not merge targets; the backend owns their retained features.
3. **Migrations.** Preserve mainline's migration history/data (backend `0001–0014` at the reviewed
   baseline) and provide a tested upgrade to the final model. Because no unified-app deployment has
   data to preserve, its unshipped compliance migrations `0015–0032` may be **replaced** with clean,
   ordered migrations in their destination table-owning Django apps. Do not rewrite shipped mainline
   history. Verify dependencies and table names with real PostgreSQL upgrade and fresh install;
   never assume the SQLite review proves deployment compatibility.
4. **Security gate now, not later.** The plugin subprocess gets a **closed, minimal allowlist** of
   non-secret environment entries, plus only the explicit per-run entries required for existing plugin
   behaviour. It must not inherit `DJANGO_SECRET_KEY`, `INTERNAL_API_KEY`, registry, database, Redis or
   unrelated host environment secrets. Adapt only `plugin_child_env` / subprocess creation and focused
   tests from `e05a231`; do **not** cherry-pick that commit wholesale (it also changes dispatch and
   scrub semantics). Verify installer/setup subprocesses and logs for the same exposure. Record the
   remaining limitation honestly: plugins may still receive assessed-target run credentials through
   the current interface until the post-port run-local door. Ported outbound paths must be scrubbed.
   Keep I1 self-contained dispatch and the I2 run-local door **deferred** as in ADR 0002. A runtime
   credential exception no longer covers worker-wide service secrets entering plugins.
5. **Deny-by-default project access.** Extend the merged backend's one ORM/access mechanism so every
   project-scoped public endpoint resolves the project and applies role/ownership checks, including
   related-object writes and file downloads. Add one small maintainable route-coverage guard (or
   equivalent registration test) with documented non-project and internal-only exemptions. A static
   guard is not proof of isolation: add two-project, multi-role behavioural tests. Internal APIs also
   need project/evaluation binding checks; the shared internal key alone is not tenancy.
6. **Preserve before removing.** Keep existing unified-app/mainline behaviour and supporting components;
   port missing pilot needs into the existing backend/webapp. Inventory and document duplicates before
   retiring old domain/platform stacks **after parity**. Avoid an early release promise or unreviewed
   deletion; a useful interim build can be demonstrated after the security/access gates, but full
   consolidation remains the release goal.
7. **UI and reports.** Aim for recognisably pilot-like branding, navigation and four-step workflow;
   no pixel-perfect, exhaustive screenshot matrix. Preserve real pilot PDF/Word report functionality.
   Inventory the renderer's production dependencies and browser/runtime costs before selecting a
   deployment approach. Existing dependencies may be reused; **any new top-level production
   dependency, service or container requires its own I8 ADR** with owner, cost and removal condition.
   Do not quietly drop PDF/Word or impose an unreviewed Chromium backend requirement.

## Consequences and exit

- The I1 named guard baseline may remain until the post-port execution milestone; the worker-wide
  environment leak is **not** baseline debt. Inherited run credentials remain a documented temporary
  I2/I7 exception until the run-local door is delivered. New secret paths are not permitted.
- Upgrades preserve mainline data, not disposable unified-app/pilot exploration data. Re-record
  source-specific architecture baselines after the selective merges; missing files must not appear
  to clear a guard falsely. Guards must never be silenced to make the port pass.
- The integration issue assigns a coordinator for submodule pins and cross-layer contracts; separate
  workers may build feature slices from that shared frozen base. Post-port execution hardening removes
  the remaining I1/I2 waiver; full feature parity, upgrades, isolation and lean-core checks close the
  consolidation milestone. Any proposed removal needs identified behaviour and parity evidence.
