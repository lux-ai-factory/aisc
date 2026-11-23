# 0001. Mainline-first consolidation with one existing audit writer

**Status:** accepted; execution scope and execution-baseline expiry are governed by
[ADR 0003](0003-frozen-unified-app-port-and-worker-boundary.md) (superseding 0002). Audit, upgrade,
license and cache decisions remain accepted.
**Invariant:** I3/I6 — one audit implementation, best-effort delivery for this refactor;
I5 — existing immudb storage exception; I11 — retain isolated dashboard cache
**Owner:** AISC maintainers
**Date:** 2026-11-16

## Context

The project owner clarified the refactor scope on 2026-11-16: port the agreed features onto main,
keep the architecture simple, and improve resilience incrementally afterwards. Only installations on
current `master`/`main` need data-preserving upgrades. Exploration-branch data is disposable.
The owner explicitly chose to keep immudb for this refactor.

## Decision

- Extend main's `aisc_backend.audit` writer, API and activity UI into the **one** audit implementation.
  Keep its existing immudb store and history. Do not port the pilot's separate project ledger,
  gateway witness, identity store, outboxes or inter-service relays.
- Every governed mutation calls the one audit helper; preserve main's **best-effort** failure behaviour.
  An immudb outage can lose an audit event. There is no atomic Postgres + immudb transaction and no
  guaranteed-delivery claim. This is an explicit I6 delivery waiver, not a second audit path.
- Keep the existing immudb provisioning/schema mechanism as an I5 exception; Django owns the product's
  relational tables and migrations. Third-party service metadata retains its upstream migration tools.
- Retain Superset's password-protected, network-isolated `dashboard-redis`. I11 does not require
  sharing infrastructure across different trust boundaries.
- Agent instructions and review own architectural judgement. Keep a small pytest regression suite
  for concrete detectable violations; do not require a bespoke script for every invariant.
  Named existing violations may remain expected failures, but new detected violations fail normally.
- Deliver basic dispatch independence and the run-local door in this refactor. Durable result recovery,
  advanced dispatch/retry design, adapter sandboxing and a general session framework are follow-ups.

## Consequences

- **Cost:** one immudb service remains; auditing retains main's best-effort limitations. Pilot-specific
  cryptographic export, witness and identity-erasure semantics are not ported as a second ledger.
- **License:** the configured immudb 1.11.1 is BSL 1.1 with conditional commercial production permission;
  see `../immudb-license.md`. Keeping it does not promise unrestricted downstream SaaS use.
- **Guard:** existing-violation baselines in `tests/architecture/test_invariants.py` link here. They
  expire at completion of the consolidation and may only shrink without another decision.
- **Removal condition:** retire the baselines as their features land. Revisit audit delivery before
  promising lossless audit trails; revisit the immudb exception when stronger audit guarantees or
  unrestricted commercial distribution become a release requirement. Revisit the cache exception only
  if its replacement preserves the dashboard trust boundary.
