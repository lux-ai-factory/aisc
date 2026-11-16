# 0003. Frozen unified-app port and the worker boundary

**Status:** accepted
**Invariant:** I1 — waived (named execution baseline) · I2 — waived (partial) · I7 — temporary exception
**Owner:** AISC security and architecture owners (SEC-01/DOC-01)
**Date:** 2026-11-16

## Context

The E0 baseline integrates the frozen `feat/unified-app` submodule pins onto main (see
[0001](0001-mainline-first-consolidation.md)). The frozen worker (`aisc_eval`) predates the consolidation
hardening and, on the merged tree, still:

- fetches inputs and calls the backend **inside the run path** (`run_plugin`), so a run is not yet
  self-contained (**I1**);
- builds the plugin child environment from `os.environ.copy()`, so a plugin can inherit the worker's
  service secrets — `DJANGO_SECRET_KEY`, `INTERNAL_API_KEY`, registry/database/Redis/Keycloak credentials
  (**I2**/I7);
- does not scrub every outbound run path (stdout/stderr, logs, artifacts, failure messages) (**I7**).

Fixing all three here would mean doing SEC-01 (#104), CORE-01 (#109) and EXEC-01 (#120) during integration
and would import the frozen branch's dispatch/scrub rewrite wholesale — which those tickets explicitly
forbid at integration time. The boundary itself, however, is not in question: the worker reaches the
backend over its API (never by import, **I3**), and a plugin reaches a system through a door, never a
credential (**I2**).

## Decision

Accept a **named, time-boxed execution baseline** while the port lands, and pin the worker boundary:

- **I1:** mid-run backend fetches may remain on the baseline until the self-contained dispatch and
  end-of-run posting land post-port (#120/#119). The run→backend call that posts results is allowed.
- **I2:** the plugin child environment is to be sandboxed to a closed allowlist by SEC-01 (#104). Per-run
  **target-key isolation is NOT yet asserted** — do not claim it until #120 retires this baseline.
- **I7:** a temporary exception applies to the run's outbound paths until #120 adds scrub-on-emit.
- The worker boundary is affirmed: `eval → backend` only through the HTTP API; `shared/*` ABIs stay acyclic;
  the core imports no optional domain (#109).

## Consequences

- **Cost:** during a run the worker holds service credentials a plugin could read, and unfiltered run paths
  can leak. The exposure is bounded to the consolidation window and tracked by #104/#120.
- **Guard:** the baseline is recorded as `xfail` in
  [`tests/architecture/test_invariants.py`](../../tests/architecture/test_invariants.py) —
  `test_i1_worker_does_not_fetch_from_backend_midrun`, `test_i2_plugin_environment_is_an_allowlist` and
  `test_i7_outbound_paths_scrub`.
- **Removal condition:** retire each `xfail` when #104 lands the allowlisted child environment, #120 lands
  self-contained dispatch, the run-local door and outbound scrubbing, and the corresponding guard turns
  `xpass`; #109 folds the optional domains so `test_i10_core_does_not_import_optional` passes. **All
  consolidation debt expires at the release (#119).**
