# Scratch — Platform, Connections, Adapters (meeting prep)

> **Scratch/working docs, not repo documents.** They hold the discussion and the evidence so I can
> drive my points in the next meeting. Everything under "Evidence" was read out of the
> `origin/pilot`, `origin/master`, `origin/dev`, `origin/feat/unified-modules` refs on **2026-11-09**.
> This folder replaces the single `SCRATCH-platform-adapters-discussion.md` (split 2026-11-11).

---

## The through-line (one paragraph)

The `pilot` branch grew a **second control plane**: a `platform` service (~12.5k lines, ~21.5k lines
of tests), a ~25k-line `scripts/` launcher, a binary `AISC_DEPLOYMENT` mode, per-project databases, and
a parallel `connection`/`target` domain next to the backend's existing `AIComponent`. Most of it
**re-implements things the Django backend + webapp already do**, and the parts that don't are either
**raw-SQL coupling** into other apps' tables or **runtime work that belongs in the eval worker**. The
coherent shape is **one backend (Django) + one webapp + one database with project-scoped access**,
holding `AIComponent`, `connection` and `adapters` together, with **adapters as a first-class,
selectable concept at the plugin level** and **feature flags instead of a deployment mode**. This
folder argues that case and lays out how to build it in a way you can *see* in the UI.

## Binding architecture rules (separate from this scratch set)

The invariants these notes argue for now have a **binding** home: **[`../ARCHITECTURE.md`](../ARCHITECTURE.md)**
(+ **[`../AGENTS.md`](../AGENTS.md)** for agents, and guards in **[`../tests/architecture/`](../tests/architecture/README.md)**).
Notably **I1 — a run is self-contained** (the worker must finish with the backend/platform down), which
`pilot` breaks (see §2/§9 below and `03-code-smells.md`).

And the framing that governs the whole set: **[`../docs/exploration-branches.md`](../docs/exploration-branches.md)**
— `pilot`/`feat/unified-modules` are **scratch projects at app scale**, used as discussion points; we fold in
their **features**, not their code.

**The shareable single-file synthesis** of everything below is
**[`../docs/unified-modules-and-pilot-brief.md`](../docs/unified-modules-and-pilot-brief.md)** — the
two-phase roadmap (`unified-modules` then `pilot`) and the five-step method. Share that one file.

## How to read it

1. **[`01-background.md`](01-background.md)** — where the branches stand (2 minutes).
2. **[`02-consolidation.md`](02-consolidation.md)** — the capstone: retire the platform app; one DB;
   feature flags not a mode.
3. **[`03-code-smells.md`](03-code-smells.md)** — the bad code smells, evidence-backed, with the fix.
4. **[`04-plugin-calls-and-execution.md`](04-plugin-calls-and-execution.md)** — don't proxy plugin
   calls back to the backend; where adapters run.
5. **[`05-versioning.md`](05-versioning.md)** — versioning: yes, but in the model layer.
6. **[`06-adapters.md`](06-adapters.md)** — adapters as a first-class, shipped concept; kinds and the
   door (the current design).
7. **[`07-development-plan.md`](07-development-plan.md)** — the use cases, mock kit and tests that make
   it click in the UI.
8. **[`08-meeting-agenda.md`](08-meeting-agenda.md)** — what I want out of the meeting.

Appendices: **[A — execution location draft](appendix-a-execution-location.md)** ·
**[B — adapter spec (ours)](appendix-b-adapter-spec.md)** ·
**[C — evidence index](appendix-c-evidence-index.md)**.

## Section → file map

The split keeps the **original section numbers** (so cross-references like "§8/§9" still work).

| original | title | file |
|---|---|---|
| §0 | Where the branches stand | `01-background.md` |
| §1 | One database per project | `02-consolidation.md` |
| §2, §2A | LLM calls / how pilot proxies | `04-plugin-calls-and-execution.md` |
| §3 | Versioning | `05-versioning.md` |
| §4 | Platform app vs extending webapp/backend | `02-consolidation.md` |
| §5 | Adapters — a first-class, shipped concept | `06-adapters.md` |
| §6 | Specific changes in `pilot` to call out | `04-plugin-calls-and-execution.md` |
| §7 | What I want out of the meeting | `08-meeting-agenda.md` |
| §8 | Adapters: kinds, boundaries, placement | `06-adapters.md` |
| §9 | The boundary: the door vs the local file | `06-adapters.md` |
| §10 | Development plan: use cases, mock kit, tests | `07-development-plan.md` |
| §11 | Consolidation: retire the platform app | `02-consolidation.md` |
| §12 | Configuration: feature flags, not a mode | `02-consolidation.md` |
| — | Bad code smells (new) | `03-code-smells.md` |
| App. A | Adapters executing in the eval runner | `appendix-a-execution-location.md` |
| App. B | Alternative adapter specification | `appendix-b-adapter-spec.md` |
| App. evidence | Evidence index (file:line) | `appendix-c-evidence-index.md` |

## Status of the decisions

**Agreed (2026-11-10, surface revised 2026-11-11)** — §8.7:

- Two adapter kinds (`data`/`resource`); "agent" = resource + session.
- No `surface` axis: `data` = local file (plugin process); `resource` = loopback HTTP door (worker).
- Session scope declared per adapter (run vs row).
- A `produces`/input-type registry; a shared loader so the UI can enumerate adapters.
- An adapter is needed **iff** the target is non-native.

**Under discussion (2026-11-11)** — the multi-repo premise:

- Whether to keep the "replaceable services / own implementation" boundaries or fold them: the layer repos
  (`backend`, `webapp`, `eval`, `results-dashboard`) and the published ABIs (`shared/*`) are independently
  justified; the domain slices (`qualification`, `controls`, `control-objectives`, `catalogue`) are not
  (see brief D8, under discussion).

**Proposed here (to drive the meeting)** — §1, §4, §11, §12, §3:

- One database + project-scoped access (RLS / `project_id`), not one DB per project.
- Retire the `platform` app; fold connections/adapters/membership/secrets/ledger into backend + webapp.
- Replace the `scripts/` control plane with a committed compose file + a Makefile.
- **Feature flags instead of the binary `AISC_DEPLOYMENT` mode.**
- Version in the Django/ORM model layer, one place that cuts a version.

**Open** — §9.4, §B.9:

- For a **native** target, keep the door always, or point the plugin straight at the endpoint? (rec: keep it.)
- A `produces`/input-type id registry.
- Resource-adapter state model (`open`/`call`/`close`; who owns the session lifetime).
- Validating/testing a user-authored adapter.

## Conventions

- "Today / pilot" evidence is `file:line` against the refs named above; the full list is
  [`appendix-c-evidence-index.md`](appendix-c-evidence-index.md).
- Prices/numbers are approximate and labelled as such.
- These files are **untracked**; treat them as notes, not source.
