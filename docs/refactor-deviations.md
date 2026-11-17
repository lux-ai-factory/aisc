# Refactor status and deviations — integration branch

**Branch:** `integration/int-01-frozen-unified-app`
**Date:** 2026-11-17 · **Owner:** coordinator (INT-01 #103); baseline/docs: DOC-01 #121

This branch is the **main-based selective integration** of the frozen `feat/unified-app` commits. It is
a **working branch for local testing**, not a release. For this phase the architecture guards and ADRs
are treated as **guidelines**: where the merged tree does not satisfy an invariant, the deviation is
recorded here and owned by a later issue instead of blocking the merge. Refinement happens after the
branch is testable end to end.

## What is on this branch

- Parent cut from `master` @ `58c1861c3839aa500e67795ad3b64a8561593371` (not the `feat/unified-app`
  parent tree `256712e`, which is reference only).
- Five frozen merges pinned:
  - `apps/backend` `37d4e733b94de89811296c9e5b22979aea83c587`
  - `apps/webapp` `7fd5e8ce2ef265559e241d4ce8598e220f9b45d5`
  - `apps/eval` `b0171dbd555f7b8095d77bc3703c31d4e4fd20e1`
  - `shared/plugin-interface` `30282a337c74e2f1781dc80bbeb8adf5a7dc7a86`
  - `shared/plugin-manager` `9ae73b27644af81f62a1f98ad77e3ee942073bd4`
- `apps/controls` `432301ce…` and `apps/qualification` `7253966…` stay at their **mainline** pins; their
  legacy stacks are reference-only and their retained features live in `backend`/`webapp`.
- Preserved byte-identical to `master`: published compose, local-build overlay, compose-validation CI,
  `e2e/`, `DEVELOPER_GUIDE.md`, `env.example`. No `e2e` file disappeared; no file was deleted by the merges.

## Verified in the build sandbox (no Docker available here)

- **Backend:** `uv run python manage.py migrate` on SQLite applies cleanly, including the compliance
  migrations `0020`–`0032`; `uv run uvicorn config.asgi:application` serves 130 API paths and
  create/list project works. The app **must run under ASGI** (uvicorn) — the Ninja logging hook reads
  `request.scope`, so Django's WSGI `runserver` 500s. The backend image already runs uvicorn.
- **Webapp:** `npm ci && npm run build` succeeds; `npm run preview` serves the app. API base is injected
  at container start (`VITE_API_URL=APP_API_URL` → `env.sh` substitutes `APP_API_URL`).
- **Compose:** `docker compose config -q` passes for the published / build / development files.

## Architecture guard / ADR deviations (recorded, not blocking)

Run: `uv run --no-project --with pytest python -m pytest tests/architecture -q -rxX`

| invariant | state | why / owner |
|---|---|---|
| **I10** core does not import optional domains | **RED** | the frozen unified-app optional domains are present and imported by core; the sanctioned fold is **CORE-01 #109** |
| **I9 / I5 / I3** domain slices | xfail | `qualification`/`controls` remain separate slices (ARCHITECTURE.md I9/I5) |
| **I1** self-contained dispatch | satisfied on this branch | the eval `refactor/architecture-consolidation` conformance was folded in. **Deviates from ADR 0003**, which defers I1 to EXEC-01 #120 — kept deliberately so the merged worker is functional and safer |
| **I2** plugin child env allowlist | satisfied on this branch | same fold; ADR 0003 preferred the narrow **SEC-01 #104** patch over folding the whole eval conformance |
| **I7** outbound scrub | satisfied on this branch | same fold |
| **I11** one container per deployable process | satisfied | dev-overlay migration folded into the app process |

## Deviations to revisit later

1. The binding ADRs `docs/adr/0001-mainline-first-consolidation.md` and
   `docs/adr/0003-frozen-unified-app-port-and-worker-boundary.md`, and the starting patch
   `docs/patches/eval-plugin-child-environment.patch`, are **not** on this branch — they exist only in
   the handover zip. Land them and reconcile the v1 docs currently carried on this branch with the v2
   `refactor-plan.md` / `unified-modules-and-pilot-brief.md` (**DOC-01 #121**).
2. `apps/eval` carries the `refactor/architecture-consolidation` conformance merge in addition to the
   frozen pin (see I1/I2/I7 above). Re-confirm ADR 0003 scope, or keep it and retire the SEC-01 patch.
3. Optional-domain feature parity (connections/adapters, evidence map, report composer, catalogue) is
   **not** on this branch yet; that is the E3–E5 feature port.

## Run it locally

```bash
git clone --recurse-submodules -b integration/int-01-frozen-unified-app \
  https://github.com/lux-ai-factory/aisc.git aisc-int
cd aisc-int
cp env.example .env            # then edit secrets; for a no-SSO local run set AUTH_ENABLED=false
docker compose -f docker-compose.yml -f docker-compose.build.yml up --build
# open http://localhost:8080
```

The build overlay builds `aisc-backend`, `aisc-webapp` and `aisc-eval` from the checked-out submodules;
the base file pulls released images. Submodule URLs are `git@github.com:`; without an SSH key, rewrite
them to HTTPS first:

```bash
git config --global url."https://github.com/".insteadOf "git@github.com:"
```

_This document was created by an AI agent (OpenHands) on behalf of the requester._
