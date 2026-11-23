# Handover — `integration/int-01-frozen-unified-app`

**This file is temporary.** It documents the integration work so the next agent can pick it up, and
it is on the list to delete before the branch merges (see §5).

- **Branch:** `integration/int-01-frozen-unified-app` (tip at handover: `f432417`)
- **PR:** [#125](https://github.com/lux-ai-factory/aisc/pull/125) — **draft**, `integration/… → master`
- **Base:** `origin/master`
- **Commits on the branch:** 44 (parent repo) + the submodule commits they pin

---

## 0. TL;DR

The frozen `feat/unified-app` is ported onto `master` as **one testable branch**. Everything agreed
for the port is on it and the acceptance sweep is green from a fresh clone. What is **not** done:
the release itself (no tag) and the post-port execution milestone (E7). The I9 consolidation is now
**done**: the `apps/controls` / `apps/qualification` submodules, the static `homepage/` launcher and
the per-app DB init files have been removed (guards now **8 passed, 0 xfailed**). GitHub issues are
labelled `status: doing` and linked to PR #125, but not closed.

Verified at handover (fresh clone, `--recurse-submodules`):

| check | result |
|---|---|
| architecture guards (`pytest tests/architecture -q`) | **7 passed, 1 xfailed, 0 failed** |
| backend (`uv run python manage.py test`) | **482 passed, OK** |
| `makemigrations --check` | **No changes detected** |
| fresh `migrate` on empty SQLite | **clean, 60 tables** |
| webapp (`npx vitest run`) / `npm run build` | **273 passed / clean** |
| `docker compose config -q` (all 5 layers) | **OK** |

---

## 1. Get it and verify

```bash
git clone --recurse-submodules -b integration/int-01-frozen-unified-app \
  https://github.com/lux-ai-factory/aisc.git
cd aisc

# guards (fast)
uv run --no-project --with pytest python -m pytest tests/architecture -q     # 7 passed, 1 xfailed

# backend
cd apps/backend && uv run python manage.py test                              # 482 OK
uv run python manage.py makemigrations --check --dry-run                     # No changes

# webapp
cd ../webapp && npm ci && npx vitest run && npm run build                    # 273 passed / clean

# deployment
cd ../.. && cp env.example .env && docker compose up -d                      # uvicorn; see gotchas
```

Submodule pins on the branch: `apps/backend 7926e7e`, `apps/eval f6f4996`, `apps/webapp 347ec00`,
`shared/plugin-interface d69b593`, `shared/plugin-manager 9ae73b2`. The `apps/controls` and
`apps/qualification` submodules were removed (I9 consolidation).

---

## 2. What was done

Every issue below is on the branch. "Done" means the code is there and the whole-branch sweep is
green; it does **not** mean the issue is closed on GitHub.

**Integration (INT-01 #103, DOC-01 #121)**
- Cut from `master`, pinned the frozen merges, landed the v2 binding docs (`ARCHITECTURE.md`,
  `AGENTS.md`, `docs/adr/0000–0007`), the refactor plan/brief, and the architecture guard suite with
  honest named baselines (`13dc00b`, `b4586f5`).
- Guard suite re-pointed at the **merged** sources: guards now **fail on an empty source set**
  instead of silently passing (`5e4f384`).

**E0 baseline / E1 security**
- **SEC-01 #104** — the eval plugin child gets a **closed environment allowlist** (`3aef9c6`).
- **SEC-02 #105** — project-scoped routes **deny by default** + a route-coverage guard (`f98416f`).
- **SEC-03 #106** — evaluation and stored-file reads bound to the owning project (`c7a1231`).

**E2 ownership / versioning / migrations**
- **MIG-01 #107** — the unshipped compliance chain `0015–0032` squashed into one migration; shipped
  `0001–0014` untouched (`fe289dc`).
- **VER-01 #108** — one assessed-system identity (core `AISystem`, qualification links through it)
  and **explicit immutable publication** (a publish cuts a version; edits build a draft/successor;
  published snapshots refuse update/delete) (`36cc911`, `21d964b`).

**E3 / E4 / E5 features**
- **UI-01/UI-02 #110/#111** — pilot-styled shell, four-step landing, project cards, four-column
  Collect-evidence hub (`dd2682e`, `f21e152`, `a2d3a63`, `9036df9`).
- **CON-01 #112** — connections/adapters/helpers + the **allowed-hosts guard** (`1a0f76c`,
  `417e885`, `f48dd1d`).
- **QUAL-01 #113**, **EVD-01 #114**, **ANA-01 #115**, **CAT-01 #122** — objectives/checklists/agents,
  versioned evidence map with coverage/review/carry-forward, scoped results + Superset bridge with
  an isolated cache, catalogue parity (`7b9c9bd`, `3625e44`, `4e13722`, `8a355fc`, `bc483c4`).
- **REP-00/01/02 #116–#118** — pilot WeasyPrint/Jinja renderer + plugin ABI, layouts/immutable
  snapshot, real PDF/Word + composer (ADR 0005) (`cbab369`, `970d081`).

**CORE-01 #109 / EXEC-01 #120 / REL-02 #123**
- One **feature-flag registry** gating optional features at runtime (`b7a9c85`).
- One **audit writer** extended to the newly governed mutations (`45503db`).
- **Self-contained dispatch** — the worker fetches nothing mid-run (I1 now **passes**) (`207aea8`).
- **Run-local door** withholding target credentials (`d7c6ee6`).
- One-shot `make_buckets` **step containers retired** (I11 now **passes**) (`46d07e9`).

**REL-01 #119** — consolidation acceptance: the sweep above, plus the two defects it found and fixed
(`33e1d3e`): optional features had shipped defaulting **OFF** (full profile now the default), and
`env.example` shipped `DASHBOARD_REDIS_PASSWORD` empty so the documented flow could not start.

**Docs** — `docs/migrations/v1.3.0-to-v1.4.0.md` (plugin upgrade guide) + `docs/migrations/README.md`
(`f432417`).

---

## 3. What was NOT done

1. **No release.** No `v1.4.0` tag, PR is still a **draft**, and the GitHub issues are `status: doing`
   — not closed. Convert the issue references in PR #125 to `Closes #…` (or close them by hand) when
   you are ready to merge.
2. **E7 / post-port (deliberately out of this release).** Self-contained dispatch and the run-local
   door **are** done; still open: the real **backend/platform-down acceptance test**, durable recovery
   after worker loss, retries/dedup, credential expiry, adapter sandboxing, stronger audit
   verification, PostgreSQL RLS. See `docs/refactor-plan.md` §7.
3. **I9 consolidation — DONE.** `apps/controls` and `apps/qualification` (full-stack domain slices,
   ADR 0001) were removed along with the static `homepage/` launcher and the per-app `init/*-db.sql`
   files; their retained behaviour is served from `backend`/`webapp`. The I9 guard passes with an
   empty baseline (suite: **8 passed, 0 xfailed**). Recorded in `docs/refactor-deviations.md`.
4. **Legacy retirement partly done.** `homepage/` and the controls/qualification submodules are
   removed; what remains of **#123** is the spent exploration branches and any `scripts/` cleanup
   (both `scripts/make-buckets.sh` and `scripts/verify-dashboard-redis.sh` are kept — they are
   documented steps, not leftovers).
5. **Plugin-manager installer env** — one ADR 0003 §4 spawn point remains open
   (`shared/plugin-manager/src/aisc_plugin_manager/uv_client.py`); recorded in
   `docs/refactor-deviations.md` (§"Left undone (E4)").
6. **Not verified here:** real PostgreSQL upgrade (only SQLite fresh migrate), a live Keycloak login,
   and the browser/visual acceptance of the pilot look.

---

## 4. Gotchas when working here

- **Submodules are in detached HEAD.** A plain `git push origin <branch>` fails ("does not match
  any"). Push the commit explicitly: `git push origin HEAD:integration/int-01-frozen-unified-app`.
  After a submodule commit, bump the gitlink in the parent and push that too.
- **`env.example` leaks into your shell.** It sets `AUTH_ENABLED=true` and the Postgres `DB_*` vars.
  The backend test suite assumes **auth off / SQLite** — unset them before `manage.py test`, or you
  get ~100 spurious failures. (This bit the sweep; it is a shell issue, not a repo one.)
- **Run the API under uvicorn**, not `runserver`. The Ninja logging hook reads `request.scope`, so
  Django's WSGI `runserver` 500s. The image already runs uvicorn.
- **Feature flags default ON** (full profile). `FEATURE_QUALIFICATION/OBJECTIVES/CONTROLS/REPORTING=false`
  gives the lean profile. Never gate by editing `INSTALLED_APPS`/`MIDDLEWARE`/URLconf.
- **Workers/thrash:** the whole-branch sweep is what catches cross-cutting regressions; per-issue
  green tests did not catch the flag-default bug. Re-run the sweep after any cross-cutting change.

---

## 5. Before you merge — cleanup

### 5.1 Delete the integration scaffolding

These were created **for** the integration and should not reach `master` as-is. (Everything under
`docs/` except `DEVELOPER_GUIDE.md` was added by this branch — verify with
`git ls-tree -r --name-only origin/master docs`.)

| path | why it is scaffolding | action |
|---|---|---|
| `HANDOVER.md` | this file | delete |
| `docs/refactor-plan.md` | the phased plan for the port | delete (fold any surviving rule into `ARCHITECTURE.md`) |
| `docs/refactor-deviations.md` | running status/deviations log | delete |
| `docs/refactor-issues.json` | the issue manifest used to publish GitHub issues | delete |
| `docs/handover-claude.md` | the previous handover | delete |
| `docs/unified-modules-and-pilot-brief.md` | the decisions brief for the port | delete |
| `docs/refactor-catalogue-parity.md` | port-era parity analysis | delete |
| `docs/exploration-branches.md` | how pilot branches are treated | delete |
| `docs/patches/` | the only file is the SEC-01 patch, now applied by the eval fold | delete the directory |
| `SCRATCH-platform-adapters/` | scratch design notes (explicitly "not binding") | delete |
| `homepage/` | the static launcher kept as a look/feel reference | **deleted** |
| `scripts/` | **keep** — `make-buckets.sh` is the documented bucket-init path (REL-02, `README.md`) and `verify-dashboard-redis.sh` is referenced by `docs/ops/results-dashboard.md` | keep both |

### 5.2 Fix the links in the docs that stay

Deleting the above breaks references in the **permanent** docs. Update these before deleting:

- `AGENTS.md` — its "Map of the docs" links to `docs/refactor-plan.md`, `SCRATCH-platform-adapters/`,
  `docs/exploration-branches.md` and `docs/unified-modules-and-pilot-brief.md`; also the
  "Refactor scope (2026-11-16 …)" section.
- `ARCHITECTURE.md` — links to `docs/refactor-plan.md` and `SCRATCH-platform-adapters/`.
- `docs/architecture.md` — links to `docs/refactor-plan.md`.
- `docs/adr/0004`, `docs/adr/0005`, `docs/adr/0007` — reference `docs/refactor-deviations.md`.
- `docs/adr/README.md` — references `docs/refactor-issues.json`.
- `docs/appendices/4-collect-evidence.md`, `docs/appendices/manage.md` — reference `docs/refactor-plan.md`.

`docs/appendices/` is port-era per-concern detail: **keep what documents shipped behaviour** (it is
useful product documentation) or fold it into `docs/architecture.md`; don't keep it as "the plan".

### 5.3 Other pre-merge steps

1. **Close the issues.** Turn the references in PR #125 into `Closes #95 … #123` (or close by hand),
   and drop the `status: doing` label as each closes.
2. **Retire the consolidation baseline.** With I1 and I11 now passing, only **I9** remains as an
   `xfail`; re-run the guards and confirm the baseline set matches reality (the guard fails on a new
   finding, and on an empty source set).
3. **Re-run the full sweep** on the exact merge candidate (§0 table), from a fresh clone.
4. **Tag and release** `v1.4.0` (the migration guide is written against that name) — and update
   `docs/migrations/README.md` to drop the "provisional" note.
5. **Decide #123** (launcher/exploration retirement) — it is explicitly *not* part of this release.

---

## 6. Where things live

- Invariants / how to work here: `ARCHITECTURE.md`, `AGENTS.md`, `docs/adr/`
- How the product works: `docs/architecture.md`, `docs/appendices/`
- Plugin upgrades between releases: `docs/migrations/`
- Verification: `tests/architecture/` (guards), `apps/backend/aisc_backend/tests/`,
  `apps/webapp/src/**/*.test.tsx`, `apps/eval/tests/`
- Status log of the integration (local, not in git): `.openhands/coord/STATUS.md`
