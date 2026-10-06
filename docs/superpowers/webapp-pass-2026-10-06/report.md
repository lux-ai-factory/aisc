# apps/webapp review pass, 2026-10-06 (the user's lines only)

Pushed 2026-10-06 as one squashed commit `8816eba`; the short hashes below are the pre-squash ones (kept on the local branch `backup/webapp-pass-2026-10-06-presquash`).


Branch `feat/unified-modules`, from origin `3990bf0`. Steps 1-3, 5 and 7 of the pass in
`~/aisc-review-continue.md`; steps 4 and 6 as a brief reading in this fork (the independent code-review
and security agents are run by the parent session). Commits are local, unpushed, not squashed.

## Scope

The lines `git blame` at HEAD credits to commits by alessiobuscemi / Alessio Buscemi (27 commits,
2026-06-07..2026-10-04): 60 files, 2,946 lines at the start, mostly tests and docs; the code is in
`src/platform/`, `src/api/projectHeader.ts`, `src/deployment.ts`, `DeploymentGate.tsx`,
`PluginInstallDialog.tsx`, `GlobalHome.tsx`, `OpenPluginFromUrl.tsx`, and a few lines in TopBar, Plugins,
MyApp, AuthContext, models. Others' lines (Mohammed Fellaji, Thibault Simonetto, Sean Blevins) were not
reviewed or changed. The files in `src/seansFilesUnchanged.test.ts` (equal to origin/master) were not
changed; the user's lines in them (e.g. api.tsx, SummaryTable.tsx) are on master too, report only.

## Findings

| Id | Sev | Where | Finding | Outcome | Commit |
|---|---|---|---|---|---|
| W1 | A (bug) | `GlobalHome.tsx` OpenTheProject, `PluginInstallDialog.tsx` after install | The engine's project name is the platform project's name (free text); it went unencoded into the route, so a name with `#`, `?`, `/` or spaces opened nothing | encoded; 2 tests (failed first) | `eaca30e` |
| W2 | A (bug) | `MyApp.tsx:58` (user's line in Thibault's wrapper) | Inside a project, `GET /projects/by-name/${name}` was unencoded: `#` `?` cut the path | `projectByNameUrl` encodes it; 2 tests | `4d633fb` |
| W3 | A (lint) | 2 tests, `GlobalHome.tsx`, `deployment.components.test.tsx` | `any`, `let` never reassigned, exhaustive-deps on ProjectContext setters | typed, const; the setters are new functions every render (Thibault's context), so listing them would rerun the effect in a loop: kept out with the reason | `62c6448` |
| W4 | A (docs) | README | names encoded; `/` limit | documented | `0e923d3` |
| W5 | B | backend `/projects/by-name/{name}` (not webapp) | a project name with `/` can never be opened: Django decodes `%2F` before routing, the route takes one segment | report: rename on the launcher, or the backend route takes a path / the pid | |
| W6 | B (deps) | `package.json` (not the user's lines) | npm audit --omit=dev: 5 high (axios, fast-uri, form-data, react-router...) | report; an upgrade touches Sean's dependency set | |
| W7 | report | `MyApp.tsx:56,69` (Thibault's lines) | `useEffect` after an early return (rules-of-hooks), missing deps | report only | |
| W8 | report | `PluginsConfig.tsx` (Sean's frozen file) | LangBiTe Configure opens the old disabled 0.2.4 row | report only (known) | |
| C1 | C | `PluginInstallContext.tsx:34`, `pluginCatalogue/testing.tsx:21` | react-refresh/only-export-components | dev hot-reload only; splitting files would change imports in others' code | |

"No project with the handle ." (user report today): every link from the engine to the launcher is
`projectPageUrl`, which gives `/p/<pid>` only for a validated pid and the launcher's root otherwise
(TopBar Back, GlobalHome, the install dialog's links); the launcher opens `/p/<pid>` correctly (checked in
a browser). No engine path produces an empty `/p/`; the cause is outside the engine (launcher pages, aisc
root). Not reproduced here.

Brief security reading: the install dialog only installs after a click, into a validated pid, with the
engine's admin check; `projectHeader` names only a validated pid and refuses project routes without one;
`gatewaySignIn` redirects to a same-origin path. Nothing found.

## Second round: independent code review (high) and security review

The parent session ran the `code-review` skill (high) and a security-review agent on the in-scope lines at
`3990bf0` (read through git, not the working tree). Security: nothing at high confidence.

| Id | Sev | Where | Finding | Outcome | Commit |
|---|---|---|---|---|---|
| R1 | A | `src/pages/Plugins.tsx:123` | In configurator mode a failed project query left "Loading..." for ever | the page's error is shown (a null `projectUUID` still waits: the same state as a lookup in progress) | `fd0817b` |
| R2 | A | `src/pages/PluginStartEvaluation.tsx:57-75,165` (Mohammed Fellaji's lines, triggered by the user's launcher links) | Saved selections under one key: switching projects in a tab restored project A's selections, component pids included, on B's page | one key per project, reloaded on a project change | `32583cc` |
| R3 | B | `src/components/PluginInstallDialog.tsx:241,329` | With no project in the tab, an install goes to the project last opened in any tab and says "the project you came from" | user decision |  |
| R4 | B | stale `projectUUID` vs the per-request header after the back-forward cache | errors (404), never leaks | user decision |  |
| R5 | report | `PluginStartEvaluation.tsx:49-50,148` | "Failed to launch evaluation" shown twice | others' line, cosmetic |  |

"No project with the handle .": the review found it is not the engine (every engine link gives `/p/<pid>` or the
launcher's home) but the launcher's step-4 card, which started without its project; fixed in the aisc root
(`homepage/`, `scripts/tests/test_launcher_empty_project.py`).

## Step 8, on the isolated stack

Rebuilt with `./scripts/start.sh` (exit 0). In a real browser, signed in: the engine loads at
`http://localhost/`; `http://localhost:8100/p/`, `/evidence.html`, `/results.html?project=`, `/logs.html` now
land on the launcher's list of projects, none shows "No project with the handle"; the step-4 card reads
`/evidence.html?project=<slug>` while the project request is still pending. `scripts/guard-frozen.sh`: GUARD
PASS (G1-G5), the intended list naming `src/pages/PluginStartEvaluation.test.tsx`.

## Third round: the user's decisions ("do all", 2026-10-06)

| Id | Change | Commit |
|---|---|---|
| R3 | The install dialog names the project it installs into; with no project in the tab and no list, Install is disabled with the reason (never the project last opened in another tab) | `caf662e` |
| W6 | Shipped dependencies patched within their majors: axios 1.20.0, fast-uri 3.1.8, form-data 4.0.6, react-router(-dom) 7.18.4; npm audit --omit=dev high 5 -> 0; a test checks the versions | `bd09b2b` |
| W5 | A project named with '/' opens: `projectByNameUrl` asks `/projects/by-name?name=` (the backend's new route) | `56de109` |
| backend R3 | The plugin switch says "Switching a test on or off takes the admin role." on a 403 and shows the engine's actual state | `28b2896` |
| R4 | (stale project after the back-forward cache) left as it is, by decision | |

vitest 99 -> 110 passed; eslint 115 -> 114; tsc, build, Sean-unchanged test pass. Checked live: the engine loads; `/api/v1/projects/by-name?name=` answers 200.

## Before / after

| Check | Before | After |
|---|---|---|
| vitest | 93 passed (15 files) | 97 passed (15 files) |
| `tsc -b` | clean | clean |
| eslint (whole repo) | 121 problems (8 on the user's lines) | 115 (on the user's lines: only C1) |
| `vite build` | ok | ok |
| npm audit --omit=dev | 5 high | 5 high (W6) |
| Sean's unchanged files | pass | pass |

## Follow-ups

- W5 (backend route for names with `/`), W6 (dependency upgrade), W7 (Thibault's lines).
- `scripts/guard-frozen.sh` G4 fails on `shared/plugin-interface` (2 commits after 3403cd8: today's
  percent-format change) and `shared/plugin-manager` (not at ac8d397): root, not webapp.
- Root changes needed: none for the webapp.
