# Handover — frozen unified-app integration and pilot feature port

Updated 2026-11-16. This handover is a snapshot for an agent server, not a replacement for the
repository's current instructions. **No merge, code port, migration rewrite or GitHub issue publication
has been performed by this documentation pass.** Do not assume a working tree matches the ZIP without
checking it. Source commit pins and the pilot visual reference are in `docs/refactor-plan.md` §3/§2.1
and `docs/refactor-issues.json`.

## Read order

1. `AGENTS.md`, then binding `ARCHITECTURE.md` and accepted `docs/adr/0001-mainline-first-consolidation.md`
   plus `docs/adr/0003-frozen-unified-app-port-and-worker-boundary.md`. ADR 0002 is superseded history.
2. `docs/refactor-plan.md` (sequencing and map) and `docs/refactor-issues.json` (8 epics, 18 issue
   drafts with local IDs, dependencies, owned paths, detailed bodies and acceptance criteria).
3. `docs/unified-modules-and-pilot-brief.md` D11/D12 and `docs/appendices/` for pilot behaviour.
4. Included `homepage/` and `shared/theme/brand.json` for pilot UI look/flow. These are **references**,
   not a second product UI. The code to modify is in the checked-out submodules, not the ZIP.
5. `tests/architecture/README.md`: architecture checks supplement feature tests, not a substitute.

## Execution for parallel workers

- Assign a single integration coordinator (INT-01) to preserve main's parent compose/e2e/guides and
  selectively merge **frozen** backend/webapp/eval/plugin-interface/plugin-manager commits. The
  unified-app parent and qualification/controls app tips are reference-only. Freeze means no implicit
  pulls from moving branch tips; new author commits require deliberate review and pin changes.
- Security gate E1 and backend contracts E2 can start after INT-01. SEC-01 is the small immediate
  fix: closed plugin child environment; do not cherry-pick the broader `e05a231` dispatch change.
  `docs/patches/eval-plugin-child-environment.patch` is an applyable **starting patch** against the
  clean frozen eval pin: test with `git apply --check` in the eval submodule after integration, review,
  apply and complete SEC-01's installer/logging/security checks. The patch was trialled in a disposable
  frozen eval checkout (12 tests passed); it has **not** been merged into the main integration.
  SEC-02 denies project access by default; SEC-03 checks internal project/evaluation binding.
  Schema migrations have **one owner** (MIG-01); no two workers should independently write competing
  migration sequences. Mainline data needs a real PostgreSQL upgrade. Unshipped unified-app compliance
  migrations may be rewritten because nobody deployed that data.
- UI shell, evidence, analytics, compliance, adapters and reporting proceed at their issue dependency
  gates. Concurrent workers should use separate worktrees/branches or disjoint files; coordinate
  frontend route/context, schema, version/publish, audit/access and report snapshot contracts before
  merging. The manifest's `parallel_group` is a scheduling hint, **not** permission to concurrently
  edit a shared module. The coordinator integrates and retests across groups.
- Keep existing functionality until replacement parity is demonstrated and reviewed. Pilot full
  PDF/Word reporting stays in scope; first inventory runtime/test dependencies (REP-00). New top-level
  production dependencies/services/stores require an I8 ADR and owner decision, not automatic deletion
  or automatic Chromium installation. Superset Redis stays isolated. Existing audit remains best-effort.
- Pilot UI is a pragmatic, recognisable React adaptation: branded shell, numbered four-step flow,
  role-aware Manage and four-column/versioned evidence hub. Targeted desktop/mobile review is enough;
  no pixel-perfect, exhaustive screenshot matrix. Preserve React routes/deep links and feature logic.
- No interim release is promised at the security checkpoint. Full consolidation, upgrade, pilot
  features and lean core are the release exit. Self-contained dispatch and run-local doors remain
  **post-port**; worker-wide secret inheritance is **not** deferred.

## Important limits and checks

The reviewed frozen sources previously passed 132 frontend tests/build, 70 backend focused tests, 10
worker tests and a representative SQLite upgrade; this is **not** a live mainline PostgreSQL/full-stack
result. The pilot workspace architecture checks returned 3 passed/5 expected failures before the
integration. Re-record merged-source-specific baselines: old pilot file names disappearing is not a
genuine fix. Run from the full checkout before proposing structural changes:

```bash
uv run --no-project --with pytest python -m pytest tests/architecture -q
```

The issue manifest is a **JSON draft**, not a set of existing GitHub issues. Create epics first, then
replace local `epic_id`/`depends_on` references with real GitHub links. Do not run issue publishing or
destructive source-tree commands implicitly. Treat any user/untracked files as existing work.
