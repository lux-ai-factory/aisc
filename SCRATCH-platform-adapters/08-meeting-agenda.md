# §7. What I want out of the meeting

> From `SCRATCH-platform-adapters-discussion.md` §7, extended with the 2026-11-11 items
> (consolidation, feature flags, code smells, development plan).

- [ ] Agree the direction: **single DB + row/role-based project scoping** (or accept the per-project-DB costs explicitly).
- [ ] Agree **adapters execute with the plugin in the eval runner**, and plugins may hold the secrets they need (scoped/rotated per run).
- [ ] Agree **versioning lives in the Django/ORM model layer**, with one place that cuts a version and enforces immutability.
- [ ] Agree to **extend webapp/backend** as the platform app, **fold controls/qualification in**, and **retire raw-SQL cross-app access** in favour of versioned models/ORM.
- [ ] Agree the **adapter interface + authoring/shipping model** (shipped exhaustive list + supported bespoke path; no user catalogue).
- [ ] Agree to **retire the `platform` app** — fold connections/adapters/membership/secrets/ledger into backend + webapp (§11) — or justify its runtime role after §8/§9 remove the facade.
- [ ] Agree to **replace the `scripts/` control plane** (env generation + compose assembly, ~25k lines) with a committed compose file + a short Makefile (§11.6).
- [ ] Agree to **replace the binary `AISC_DEPLOYMENT` mode with feature flags** (one app, composable; §12) and pick the v1 flag set.
- [ ] Confirm what, if anything, we drop from `master` in the reset (e2e suite, published compose stack).
- [ ] Decide how **multi-turn / agent** evaluation is delivered (adapter `history` capability + an agent-style plugin), because no shipped evaluator drives a conversation today (§2A).

## Decisions to force (one line each)

| decision | section | the question |
|---|---|---|
| Project isolation | §1 | single DB + RLS vs one DB per project |
| Adapter execution | §2 | in the eval runner vs on the platform |
| Versioning | §3 | who cuts a version; where immutability lives |
| Platform app | §4, §11 | a new codebase vs modules in webapp/backend; retire or justify |
| Adapter contract | §5, §8 | interface + authoring/shipping model |
| Control plane | §11.6 | committed compose + Makefile vs `scripts/` |
| Deployment mode | §12 | feature flags vs `AISC_DEPLOYMENT` |
| Native door | §9.4 | keep the door always vs point straight at the endpoint |

## The one-sentence ask

**Consolidate onto the backend + webapp we already have (one DB, one auth, one test story, feature
flags not a mode), and make adapters a first-class, selectable concept at the plugin level** — sequenced
so the first use cases are visible in the UI before the placement changes land.
