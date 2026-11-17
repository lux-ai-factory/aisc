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

Two passes are on this branch: the first landed EVD-01 and CON-01
(`apps/backend` EVD-01 `0eed571`; `apps/webapp` EVD-01 `94f5ddb`), the second
answered audit iteration 2's verdict that CON-01 parity was incomplete: the
pilot's allowed-hosts guard was missing, and the plugin-environment gate (ADR
0003 §4) had only been checked for the run, not for the installer. Second pass:
`apps/backend` `f3b1dd7`, `apps/webapp` `dbad518`, `apps/eval` `a5ecbb4`.

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

**CON-01 — connections, adapters and helpers (done).** Rewritten against the pilot's
own contract instead of the frozen `AIComponent` fields:

- Models `Connection`, `Helper` and `RunBinding` (migration `0034`), a connection
  being a protocol the adapter registry dispatches on (`rest`, `openai`, `a2a`,
  `oip`), an endpoint, the protocol's own fields, and the component it targets.
- `apps/backend/aisc_backend/adapters/` ports the pilot's request builders and
  response parsers: `rest` (templated body, JSON-path answer, refusal match),
  `openai` (chat completions, tool-call/logprob capabilities), `a2a` (JSON-RPC
  `message/send`, artifacts, `.well-known/agent-card.json` discovery) and `oip`
  (KServe v2 infer). `services/connections.py` describes an adapter for the UI.
- `GET/PUT/DELETE /projects/{pid}/connections[/{name}]`, `POST …/{name}/target`,
  `POST …/{name}/test` (one real call through the adapter, as a test would make it)
  and `POST …/{name}/discover`; `GET/PUT/DELETE /projects/{pid}/helpers[/{name}]`
  with `POST …/{name}/test`; `GET/PUT /projects/{pid}/runs/{plugin_pid}/bindings`
  snapshots the adapter/version and the helper a run used.
- Keys and secret header values live **per project** in the existing encrypted
  `ProjectConfig` secret store (`category=secrets`, keys `connection:<name>:key`,
  `connection:<name>:header:<header>`, `helper:<name>:key`). Every response reports
  only *that* a key is stored and the header *names*; the value never leaves the
  backend. `AIComponent.json_value` no longer holds connection keys.
- React: `/projects/:name/connections` is the full editor (the protocol's fields,
  key, secret headers, advanced headers/timeout, Try, agent card, target link,
  remove) and `/projects/:name/helpers` the helper models (endpoint, roles, key,
  Test), both in the Project menu; Try/Test call the real endpoints.

**CON-01, second pass — the allowed-hosts guard (done).** A connection may call any
public address; an internal one — a private network, the Docker host, a machine on
the LAN — is refused unless the project lists it or the stack allows it for every
project. Ported from the pilot as a *door* rule, read immediately before every call
out (so a change applies to the next call with no restart):

- `aisc_backend/services/allowed_hosts.py`: the rules, pure and database-free
  (`normalize_entry`, `is_loopback`, `is_metadata`, `is_internal`, `refusal_for`,
  `is_never_allowed`), plus `project_entries`, `floor_hosts` and `guard_url`.
  `CONNECTIONS_ALLOWED_HOSTS` is the stack-wide floor (the pilot's `floor` rows);
  `CONNECTIONS_STACK_HOSTS` names the deployment's own services.
- `AllowedHost` (project, host, note, `updated_at`, `updated_by`; unique per
  project) with `GET/PUT/DELETE /projects/{pid}/allowed-hosts[/{host}]`: a viewer
  reads, an editor writes, every change is audited, and an entry that names a class
  which can never be reached is returned `denied` with the reason instead of being
  quietly usable. Loopback, cloud metadata and the deployment's own services can
  never be listed, and saving a connection or helper refuses them where they are
  typed.
- The guard is consulted by `POST …/connections/{name}/test`, `…/{name}/discover`
  and the helper test; a refusal is answered in the same shape as a failed Try, and
  it never opens a socket.
- React: the pilot's `#allowed-hosts` section is an accordion at the foot of
  Components and connections (`src/components/AllowedHostsSection.tsx`,
  `src/lib/allowedHosts.ts`).
- `RunBinding.adapter_version` now records the revision of the adapter a run used
  (`adapters.BUILTIN_VERSION`, or an installed adapter's own version) instead of an
  empty string.
- Evidence: `test_allowed_hosts.py` (the rules, 19 cases),
  `tests/routers/test_allowed_host_router.py` (CRUD, roles, audit, denied rows),
  the connection/helper router suites routed through the guard,
  `tests/integration/test_mock_targets_smoke.py` with `tests/local_target.py` (a
  native REST target and a bespoke A2A target on the machine's own address: the
  recorded request bodies, a file-shaped input recorded by sha256, the adapter
  version in the run binding, and a refusal before any request leaves), and
  `apps/eval/tests/test_installer_under_allowlist.py` (the installer's own
  subprocesses take the allowlist, and a real install and run succeed with nothing
  but the allowlist).

### Left undone / deviating (E4)

1. **Helper bindings are recorded, not shown.** `RunBinding` is written and read over
   the API, and its snapshot is proven not to follow later connection edits, but no
   page yet displays "what this run used" — that belongs with the run/execution UI.
   Owner: E5.
2. **ADR 0003 §4, one spawn point left.** The eval worker's installer and run
   subprocesses now take the plugin allowlist. The *plugin-manager* keeps its own
   installer (`shared/plugin-manager/src/aisc_plugin_manager/uv_client.py`,
   `uv_install`), reached from the backend's plugin/catalogue routers when a
   registry-sourced plugin is loaded; it still inherits its calling process's
   environment. Closing it needs a `child_env` hook through `AiscPluginLoader` — a
   third submodule — so it is recorded here rather than half-done. Owner: SEC-01
   #104 or the plugin-manager owner.
3. **Deviation from ADR 0003, recorded:** `RunBinding.adapter_version` was defined
   but always written empty; it now carries the built-in revision (`1`). This
   extends a snapshot the ADRs treat as frozen, so it is called out explicitly.
4. **`0034`/`0035` collapsed.** The first pass committed `0034_aicomponent_adapter_*`
   (added `AIComponent.adapter`/`adapter_version`/`helper_role`) and
   `0035_remove_aicomponent_adapter_*` (removed them again). Both are gone:
   `0034_connections_helpers_bindings_and_allowed_hosts` is the single migration.
   Django records migration *names*, so a database that applied the old pair must be
   rebuilt, or the old names `migrate --fake`d.
5. **The pilot launcher stays a reference.** `homepage/*.html` (connections,
   evidence map, `theme/brand.json`) is the look/feel reference for the port and is
   never shipped as the app; the React pages are the product.
6. **UI-02 and the report composer are untouched.** This note covers E4 (EVD-01 and
   CON-01); the four-column hub (UI-02) and the report composer remain as previously
   landed.

**Guards:** `5 passed, 3 xfailed, 0 failed` — **no baseline grew** for any of the
above (`uv run --no-project --with pytest python -m pytest tests/architecture -q -rxX`).

**Verified on this tree:** backend `uv run python manage.py test` → 270 passed (was
249); eval `uv run pytest` → 28 passed (was 25); `migrate` on a fresh SQLite applies
`0001..0034`; `makemigrations --check` clean; `npm run build` clean; `npx vitest run`
→ 177 passed (was 164).

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
