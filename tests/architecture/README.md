# Architectural guards

One test per invariant in [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md), where it can be checked
mechanically. These are the part of the architecture that **fails a build**, so that the shortest path to
a feature is also the compliant one.

Run them from the repository root:

```bash
uv run --no-project --with pytest python -m pytest tests/architecture -q
```

The tests use the standard library only (AST import scanning and file checks), so they need no module
`venv` and run anywhere. Wire this into CI as a **required** check (the repository-checks job is the
natural home).

## The guards

| invariant | test | state today |
|---|---|---|
| I1 run independence | `test_i1_worker_does_not_fetch_from_backend_midrun` | passing — the run path consumes what it was dispatched with |
| I2 door not credential | `test_i2_plugin_environment_is_an_allowlist` | passing — the plugin gets an allowlisted env |
| I3 one implementation | `test_i3_plugin_interface_is_independent` | passing |
| I3 one implementation | `test_i3_eval_worker_has_no_backend_import` | passing |
| I3 one implementation | `test_i3_one_project_database_module` | passing |
| I3 one implementation | `test_i3_no_second_ledger` | passing |
| I3/I9 one UI | `test_i3_no_product_ui_outside_webapp` | **xfail** — `qualification`, `controls` carry their own UI |
| I3 shared ABIs | `test_i3_shared_artifacts_are_acyclic` | passing |
| I4 flags not modes | `test_i4_one_deployment_contract` | passing |
| I4 app graph | `test_i4_app_graph_is_static`, `test_i4_urlconf_is_static` | passing |
| I5 one migration tool | `test_i5_one_migration_tool` | **xfail** — Prisma under `qualification`/`controls` |
| I5 app owns tables | `test_i5_installed_app_owns_tables` | passing |
| I7 no secret leaves use | `test_i7_outbound_paths_scrub` | passing — the run path scrubs stdout, stderr, logs, artifacts, errors |
| I9 boundaries on the axis | `test_i9_no_domain_slice_module` | **xfail** — `qualification`, `controls` are domain slices |
| I10 core first | `test_i10_core_does_not_import_optional` | passing |
| I11 one container per process | `test_i11_no_step_containers` | passing — migrations are steps of the app process |
| I8 process | `test_allowlist_entries_are_adr_backed` | passing |

An `xfail` guard is an invariant the current code does **not** yet meet. It documents the gap; it starts
passing (`xpass`) once the code is fixed — at which point remove the marker, do not delete the test. Do not
relax or delete a guard to make a change merge; add an allowlist entry plus the ADR instead.

**I9 is a heuristic.** `test_i9_no_domain_slice_module` flags a module that carries a frontend **and** an API
**and** its own database/migrations — the full vertical slice. Today that is `qualification` and `controls`;
the partial slice `control-objectives` (API + its own Alembic) is named in
[`../../ARCHITECTURE.md`](../../ARCHITECTURE.md) I9 but is not caught by the heuristic. (`catalogue`, which
also has a frontend, is **allowed** — it is a published public site, not a domain slice.) When the slices are
folded, the test `xpass`es — remove the marker.

## Allowlist

`allowlist.json` is the only sanctioned way to waive a guard: an entry is `{path, adr, reason}` and the
named ADR must exist and be **accepted**. `test_allowlist_entries_are_adr_backed` enforces that, so a PR
that adds a waiver without an ADR fails. The allowlist is **empty by design** — the refactor removes the
smells rather than waiving them.

## Layering

The layer contracts are enforced as static AST guards in this suite
(`test_i3_plugin_interface_is_independent`, `test_i3_eval_worker_has_no_backend_import`,
`test_i3_shared_artifacts_are_acyclic`, `test_i10_core_does_not_import_optional`) rather than as
`import-linter` contracts. The apps live in separate repositories with separate venvs, so a static scan
runs in one job with no install step and no extra top-level dependency (I8). The contracts are the same:
`plugins → plugin-interface`; `eval → not backend internals`; `shared/*` acyclic; `core → no optional domain`.

## Guards still to write

These need a running system rather than an AST scan:

- **I1 acceptance test (the flagship):** run the mock kit with the backend and platform unreachable;
  assert the run completes and produces measures; then restore and assert the results post. This is the
  guard that actually prevents a re-introduced mid-run call. It belongs in `apps/eval/tests/`, not here.
- **I10 core-alone:** the I1 acceptance test with the compliance features off.
