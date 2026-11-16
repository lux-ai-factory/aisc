# 0003. Frozen unified-app port and worker boundary

**Status:** proposed
**Invariant:** I10 — waived (time-boxed, named files only); I1/I2/I7 — enforced by the frozen merge
**Owner:** Platform architecture — drafted by INT-01 as a placeholder for the missing mandated input; NOT accepted. The I10 fold is CORE-01 (#109)
**Date:** 2026-11-16

## Context

INT-01 pins the frozen unified-app layer work onto main (see ADR 0001). Two things follow.

**The worker boundary is enforced.** The frozen merge carries the eval conformance: dispatch is
self-contained (input bytes are embedded at dispatch; the run makes no mid-run fetch — I1), the plugin
child process gets an allowlisted environment rather than `os.environ.copy()` (I2), and outbound stdout /
stderr / artifacts are scrubbed (I7). These were resolved during the merge and are **not** waivers.

**The optional domains are still coupled to the core.** The frozen work adds the qualification,
control-objectives, controls and report features, and some core files in `aisc_backend` and
`webapp/src` still import them (I10). I10 says the core must run with the optional domains **absent**;
folding them into the core behind a flag is CORE-01 (#109) and is outside the E0 freeze window. The
frozen optional domains are the E4/E5 scope (#110/#113/#117).

## Decision

Accept the frozen optional-domain files in the E0 baseline as a **time-boxed waiver of I10 for the named
files only**, recorded as ADR-backed entries in `tests/architecture/allowlist.json`. Every other guard
stays enforced and unmodified. The core→optional coupling listed there is frozen as-is until CORE-01; no
new core→optional import may be added (a new one is not on the allowlist and still fails the guard).

## Consequences

- **Cost:** the core cannot yet run alone with the optional domains absent — the allowlist masks a real
  coupling until the fold. Intended benefit: E0 delivers a reproducible main-based checkout now instead of
  blocking on the #109 fold.
- **Guard:** `tests/architecture/allowlist.json` → `"I10": [...]`, checked by
  `test_allowlist_entries_are_adr_backed`; the I10 guard consults the allowlist and still flags every
  non-listed file.
- **Removal condition:** CORE-01 (#109) folds `qualification` / `control_objectives` / `controls` /
  `report` into the core behind a flag and **deletes these allowlist entries**. Expiry: 2026-12-31.
