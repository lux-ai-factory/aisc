# Architectural regression checks

**Architecture is primarily agent instructions and human review.** These small pytest checks catch
concrete repeatable mistakes; a green result does not prove the architecture is correct. There is no
requirement for one script per invariant or an up-front import-linter project.

Read [`AGENTS.md`](../../AGENTS.md), [`ARCHITECTURE.md`](../../ARCHITECTURE.md), and the
[mainline-first plan](../../docs/refactor-plan.md). Scope is recorded in
[ADR 0001](../../docs/adr/0001-mainline-first-consolidation.md) and
[ADR 0003](../../docs/adr/0003-frozen-unified-app-port-and-worker-boundary.md).

```bash
uv run --no-project --with pytest python -m pytest tests/architecture -q -rxX
```

## What the suite checks

- Required Python source trees exist, so missing submodules do not silently pass.
- The plugin interface and eval worker do not import backend/platform internals.
- Named backend-fetch calls in worker task functions.
- Deployment-contract files and duplicate project-DB modules.
- A heuristic for full domain stacks (frontend + API + migrations).
- Step-container names in top-level compose files.

## Baselines, not blanket expected failures

The current pilot checkout already violates several destination rules. Each check lists its known
findings under ADR 0001. **New findings fail before existing findings are marked `xfail`.** A cleared
baseline passes automatically; remove retired entries as its implementation lands. Consolidation
baselines expire at completion; ADR 0003 extends **only the execution baseline** to the post-port
execution milestone. That named expected failure may remain when the feature port ships. The later
execution milestone clears it. Baselines cannot grow without a reviewed decision.

When landing these guards on main + frozen unified-app layers, review each source-specific finding. The current
pilot function/file names are not a ready-made merged-tree allowlist. Document any reconciliation with
its source evidence and linking ADR; do not use blanket skips to make the merge pass.
Add one small deny-by-default project-route coverage guard during SEC-02 (issue manifest in
`../../docs/refactor-issues.json`) with named public/global/internal exceptions. It complements
two-project role/related-object/download tests. The eval child environment must have a closed allowlist;
do not permit inherited worker-wide credentials as an expected failure.

The helpers do not detect arbitrary renamed networking, dynamic imports, semantic duplication or all
domain layouts. For example, `control-objectives` is not a full-stack match for the layout heuristic.
Review still covers these. The suite intentionally does not count Redis instances: Superset's isolated
cache is required by the current trust boundary.

## Behavioural evidence

Add checks with the feature that owns them: mainline upgrade and clean install; ORM tenant read/write,
related-object and download isolation; same app graph across flags; immutable published versions and
reopen/history behaviour; one audit writer; core evaluation with compliance disabled; pilot reporting
with real PDF/Word outputs and version/evidence provenance. PostgreSQL RLS is not required.

Keep real execution smoke tests for functional parity. Backend-down completion, run-local doors,
plugin environment/credential isolation, worker-crash recovery and general adapter sandbox/session
frameworks belong to the post-port milestone (ADR 0003). Worker-wide secrets in plugin children are
an **immediate gate**; add a small deny-by-default route-coverage guard and two-project role tests.
Ported outbound paths still require scrub
checks. Do not assert lossless audit delivery: main's immudb writer remains best-effort.

Run the small suite in existing CI when landing it on main. Use appropriate frontend tools/review for
TypeScript dependencies; Python import checks do not cover them.
