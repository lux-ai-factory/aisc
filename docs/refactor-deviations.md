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

The **v2** guard suite (`tests/architecture/`, landed by DOC-01) uses *named baselines*: a known finding is
recorded under its ADR and reported as `xfail`; a **new** finding fails. Run:
`uv run --no-project --with pytest python -m pytest tests/architecture -q -rxX` → **5 passed, 3 xfailed,
0 failed** on this tree.

| invariant | state | evidence / owner |
|---|---|---|
| **I1** worker fetch mid-run | xfail (baseline) | the 5 findings are the **dispatcher** (`run_evaluation`) and `_embed_input_files` attaching inputs/settings **before** dispatch, plus status reconciliation in `finalize_evaluation`. `run_plugin` is self-contained, so I1 holds; the AST heuristic cannot tell dispatcher from runner. ADR 0003 / EXEC-01 #120 |
| **I9** domain-slice module | xfail (baseline) | `apps/qualification`, `apps/controls` are still full-stack slices (ADR 0001) |
| **I11** no step containers | xfail (baseline) | main's compose keeps one-shot `make_buckets` steps in `docker-compose.yml` and `docker-compose-infra*.yml`; the docs tree renamed these to `engine-standalone` (ADR 0001). REL-01/REL-02 |
| **I2** plugin child env allowlist | satisfied | `plugin_child_env()` allowlist (eval conformance fold) |
| **I7** outbound scrub | satisfied | `aisc_eval/utils/scrub.py` on stdout/stderr/artifacts |
| **I3 / I4** plugin-interface independence, one deployment contract | pass | — |

Baselines were **re-recorded for this merged tree** (DOC-01), replacing the docs-branch function/file
names with the ones this tree actually has; the sets shrank, and each entry carries source evidence in
`tests/architecture/test_invariants.py`.

## Deviations to revisit later

1. `apps/eval` carries the `refactor/architecture-consolidation` conformance merge in addition to the
   frozen pin (this satisfies I2/I7 and the I1 dispatch pattern). **Deviates from ADR 0003**, which
   deferred I1 to EXEC-01 #120 and preferred the narrow **SEC-01 #104** patch — kept so the merged worker
   is functional and safer. Re-confirm scope, or keep it and retire the SEC-01 patch.
2. `docs/patches/eval-plugin-child-environment.patch` is now on the branch; SEC-01 #104 should confirm it
   is already applied by the eval fold.
3. Optional-domain feature parity (connections/adapters, evidence map, report composer, catalogue) and the
   pilot look/feel launcher (landed as the `homepage/` reference) are the E3–E5 port.

## E4 feature parity — evidence map and connections (EVD-01 #114, CON-01 #112)

Landed on this branch: `apps/backend` `0eed571`, `apps/webapp` `94f5ddb`.

**EVD-01 — versioned evidence map (done).** The pilot's `homepage/evidence-map.html`
is re-expressed as a React page (`apps/webapp/src/pages/EvidenceMapPage.tsx`,
`/projects/:name/evidence-map`, linked from the Collect evidence hub), backed by
real endpoints the frozen backend did not have:

- `GET /projects/{pid}/evidence` (latest AI-card version, or `?version=<pid>`),
  `PUT /projects/{pid}/evidence/links` (whole-set replace), `POST
  /projects/{pid}/evidence/review`. Model `EvidenceLink` + `EvidenceReview`
  (migration `0033`); the matrix itself is computed on read and never stored.
- Tests come from the version's evaluation plugins, controls from the checklist
  submissions, objectives from step 2's selection; coverage/gaps/readiness reuse
  `scoring.py`. Project-scoped: stranger 404, viewer reads, editor writes.
- Older versions are read-only; carry-forward *offers* the previous version's links
  and writes them only on an explicit copy; a review must be by someone who made
  none of the version's links and is invalidated by any link change.

**CON-01 — connections and adapters (partial).** `AIComponent` gains `adapter`,
`adapter_version`, `helper_role` (migration `0034`); `GET/PUT
/projects/{pid}/connections[/{component_pid}]` list connection components (adapter,
endpoint, key presence) and let an editor choose the adapter/helper role. React page
`/projects/:name/connections`, linked from the Project menu.

### Left undone / deviating (CON-01)

1. **Only the connection/adapter *record* is ported, not the adapter protocols.**
   There is no OpenAI/A2A/REST request builder, no A2A agent card discovery and no
   live "test connection" — the pilot's `connections.html` adapters. The adapter
   kind is data a test can read; nothing dispatches on it yet. Owner: the E5
   execution/plugin port.
2. **Keys stay in `AIComponent.json_value`, not a per-project encrypted secret.**
   The frozen backend already stores an LLM `secret_key` there; CON-01 does not move
   it to the pilot's encrypted project-scoped store. The connections listing reports
   presence only and never reads the value back, so it cannot leak, but the pilot's
   separation of key from connection is **not** implemented. Deviates from the pilot;
   follows from the frozen backend it was ported onto. Owner: the secrets/SEC work.
3. **Helper *role* only, no helper model binding.** `helper_role` marks a component;
   binding a helper to a run is not ported.
4. **UI-02 and the report composer are untouched.** This note covers only EVD-01 and
   CON-01; the four-column hub (UI-02) and report composer remain as previously
   landed.

**Guards:** `5 passed, 3 xfailed, 0 failed` — **no baseline grew** for any of the
above (`uv run --no-project --with pytest python -m pytest tests/architecture -q -rxX`).

**Verified on this tree:** `uv run python manage.py test` → 221 passed (was 208);
`migrate` on SQLite applies `0033`/`0034`; `npm run build` clean; `npx vitest run` →
147 passed (was 132).

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
