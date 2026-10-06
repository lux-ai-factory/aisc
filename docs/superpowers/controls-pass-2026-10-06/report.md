# apps/controls review pass, 2026-10-06

Pushed 2026-10-06 as one squashed commit `2590779`; the short hashes below are the pre-squash ones (kept on the local branch `backup/controls-pass-2026-10-06-presquash`).


Scope: the whole repo (every commit is the user's). Branch `feat/unified-modules`, from origin `a49987e`.
Steps 1-7 of the pass in `~/aisc-review-continue.md`; step 8 (deploy and live check) is done by the parent
session. Commits are local, unpushed, not squashed.

Steps 4 and 6 were first done by the pass's own reading (a fork may not start sub-agents); the parent session
then ran the `code-review` skill at high and a separate security-review agent on the whole repo: their
findings are R1-R11 below. Step 8 was done on an isolated stack (Docker-in-Docker from `~/aisc-macfix`), not
the live `~/aisc`, while the workshop ran.

## Findings

| Id | Sev | Where | Finding | Outcome | Commit |
|---|---|---|---|---|---|
| F1 | S | `package.json` | Next 15.5.15: npm audit critical (Server Components DoS, middleware bypass via segment-prefetch routes); sharp 0.34.5 with libvips/libheif CVEs; postcss, nanoid, source-map-js highs | Next 15.5.27, sharp 0.35.5 (npm audit --omit=dev: 0); test checks the installed versions | `5b34f96` |
| F2 | S | `services/pdf_renderer/requirements.txt` | 58 pip-audit advisories: starlette 0.41.3 (via fastapi 0.115.5), jinja2 3.1.4, pillow 10.4.0, weasyprint 63.0 | fastapi 0.142.2, starlette 1.7.0, jinja2 3.1.6, weasyprint 70.0, pillow 12.3.0, uvicorn 0.54.0, pydantic 2.13.5; pip-audit clean; image rebuilt locally and renders a PDF; test checks versions | `50dfa36` |
| F3 | A | `src/lib/installChecklist.ts:62` | A package's `meta.sourceUrl` was stored as given and rendered as a link (`SourceCitation`); the source form allows only http(s). React 19 blocks `javascript:` hrefs, so defence in depth, not an exploitable XSS | only http(s) kept, else null | `af85894` |
| F4 | A (bug) | `src/app/p/[project]/checklists/[id]/fill/actions.ts` | The first fill created answers without the card-version stamp (saveDraft stamps new/changed ones), so an answer given at the first fill and never changed stayed unstamped, against the README's "each answer is stamped" | stamped with the latest version (unstamped when the platform is down); 2 integration tests | `81f465e` |
| F5 | A | `env.development` | `controls_rw:controls_rw` still in the template although the stack sets the generated password (compose override) | template kept without a password; test | `96149db` |
| F6 | A (test bug) | `test/integration/isolation-answer-fk.test.ts:58` | `text || "char"` is ambiguous on Postgres 15: the test failed whatever the schema | `confdeltype::text` | `c8debd4` |
| F7 | A (doc bug) | `README.md` Tests | The integration recipe did not load `init/report-roles.sql`, so the documented command failed the dashboard-grants test (`role report_ro does not exist`) | recipe line added | `40a24da` |
| F8 | A (dev) | `package.json` devDependencies | vitest 2 pulled tinypool / @vitest/mocker with critical advisories | vitest 4.1.11; config also sets oxc JSX automatic (vitest 4 compiles with oxc); npm audit (all): 1 low left (esbuild dev server on Windows) | `e79d059` |
| F9 | A | `.gitignore` | Python caches of the renderer's tests showed as untracked | ignored | `f79dc0f` |
| F10 | A (fixed after "fix all") | `src/lib/installControl.ts:105` `installedIn` | The install dialog opens (and migrates, with `npx prisma migrate deploy`) every project database the person may write, all at once: for an admin with many projects, N processes and N clients, and the LRU (20) evicts clients other requests may be using | the list opens and migrates no database: an access check and one read-only SELECT each; the install migrates only the project it goes into; 4 tests | `2d91134`, `700886b` |
| F11 | A (fixed after "fix all") | `src/lib/projectDb.ts:173` | LRU eviction disconnects the least recently used client even if a request is mid-query on it (Prisma reconnects on the next query, but the in-flight one can fail) | each client counts its work in progress; only an idle one is closed, never the newest; over the cap for a moment when all are busy; 3 tests | `c3a9723` |
| F12 | B (user) | `src/lib/scoring.ts:31` | Readiness = mean/5: a question scored 1 "Not started" counts as 20% readiness | user decision (scale 0-4, or 1 = 0%) |  |
| C1 | C | `src/middleware.ts` | Server actions are global by id, so a POST could target an action under another project's URL | judged wrong: every action re-asks the platform for the project it writes (`writableProject` / `projectDbFor(..., {write: true})`), not the URL's |  |
| C2 | C | `src/lib/access/callerToken.ts` | The app accepts a client-sent `Authorization: Bearer` | judged wrong: the token is only passed on to the platform, which verifies it; Caddy strips the gateway headers |  |
| C3 | C | `controls_rw` password (handoff "Left" note) | Role password equal to its name | already fixed in the aisc root before this pass (`init/controls-role.sql`, `CONTROLS_RW_PASSWORD` in `scripts/secrets.sh`, compose override); only F5 remained |  |

Also checked, no finding: every server action and the report route check access with the platform for the
project they touch; no page reads a project database without `projectDbFor`; no `dangerouslySetInnerHTML`;
the `/api/install` route checks the Origin and is reached only behind the
gateway; scripts use `execFile`/`spawn` without a shell.

## Second round: independent code review (high) and security review

The security-review agent reported nothing at high confidence (it assumed the PDF template autoescapes); the
code review proved it does not, so R1 is a security finding.

| Id | Sev | Where | Finding | Outcome | Commit |
|---|---|---|---|---|---|
| R1 | S | `services/pdf_renderer/app.py:33` | `select_autoescape(["html","xml"])` returns False for `document.html.j2`: nothing an editor typed was escaped, and WeasyPrint fetched any URL. An answer `<a rel="attachment" href="file:///proc/self/environ">` attached the renderer's environment (its service token) to the PDF; `<img src="http://...">` called internal services | autoescape on, and a `URLFetcher` that serves only files inside `templates/`; 8 tests; checked live: the attack returns a plain PDF, no embedded file | `469fe00` |
| R2 | B | `checklists/[id]/review/actions.ts:102` | Changing one question in a review deletes all questions, and by cascade every answer, closed submissions included | not changed: user decision |  |
| R3 | A | `submissions/[id]/actions.ts:149` | `reopenForAmendment` checked outside the transaction: a double click hit P2002 | checks under a row lock; a second reopen lands on the same amendment | `514d2c7` |
| R4 | A | `src/lib/installChecklist.ts:155` | Install created a source with a taken or empty slug and failed every time | shared `freeSourceSlug` (suffix, `source` fallback) | `3d8da5f` |
| R5 | A | `review/actions.ts:69` | The review's `FOR UPDATE` did not hold off answer writers | saves and new submissions take `FOR SHARE` on the checklist; comment corrected | `514d2c7`, `6ef79c3` |
| R6 | A | `src/lib/installControl.ts:87` | Every install error reported as "cannot read" (502), 404 and DB errors included | only parse errors are 502 | `b232ad1` |
| R7 | B | `installChecklist.ts:154` | Install overwrites an existing source's URL, unrecorded | not changed: user decision |  |
| R8 | A | `submissions/[id]/actions.ts:200` | `archiveSubmission` could write two events | conditional `updateMany` | `514d2c7` |
| R9 | A | `submissions/[id]/actions.ts:69` | `saveDraft` compared with answers read before its lock | read under the lock | `514d2c7` |
| R10 | A | `sources/new/actions.ts:41` | Duplicate source registration raced into an error page | checks in the transaction, P2002 caught | `514d2c7` |
| R11 | A | `installChecklist.ts:70` | Unknown country / regulation ids from a package broke a later review save | dropped at install, as the review form accepts | `058941e` |

## Third round: the user's decisions ("do all", 2026-10-06)

| Id | Change | Commit |
|---|---|---|
| F12 | Readiness runs from "Not started" 0% to 100%: mean of (score - 1) / 4, rounded half up (Math.round); one formula in `src/lib/scoring.ts`; the platform's `services/evidence.py` copy changed the same way (root) | `d1fcc98` |
| R2 | A review keeps every kept question (same id, reworded or moved) with its answers, closed submissions included; a removed question takes only its own answers; the ledger counts added / reworded / moved / removed | `d72b914` |
| R7 | An install keeps a source's link and only fills an empty one | `ce2f0db` |

Integration 101 -> 108 passed; unit 201 passed; tsc and build clean.

## Before / after

| Check | Before | After |
|---|---|---|
| Unit (`npx vitest run`) | 188 passed, 91 skipped | 201 passed |
| Integration (throwaway Postgres, README recipe) | 87 passed, 2 failed (report_ro missing; I6.2 SQL) | 101 passed |
| PDF renderer pytest | 15 passed | 27 passed |
| `tsc --noEmit` | clean | clean |
| ruff (renderer, E4,E7,E9,F) | clean | clean |
| `npm run build` | ok | ok |
| npm audit --omit=dev | 1 critical, 4 high | 0 |
| npm audit (dev too) | + 2 critical, 1 high, 3 moderate | 1 low (esbuild, Windows dev server) |
| pip-audit (renderer) | 58 | 0 |
| TS lint | no lint config in the repo | (unchanged) |

## Step 8, on the isolated stack

`./scripts/start.sh` rebuilt and restarted everything that changed (exit 0, sign-in page answered).
- `controls_rw` (and `catalogue_rw`): the old password, the role's name, is refused ("password authentication
  failed"); the generated one works; `scripts/verify-db-access.sh` 82 passed, 0 failed.
- R1 live: the attack payload sent to the running renderer returns a 200 PDF with no embedded file and no
  `/etc/passwd` content.
- In a real browser (headless Chromium), signed in: `/controls/p/<pid>/checklists` and `/submissions` 200.

## Root changes (made in the aisc root, same commit as this report)

- `controls_rw` gets a generated password: `init/controls-role.sql`, `CONTROLS_RW_PASSWORD` in
  `scripts/secrets.sh`, applied by `postgres-setup`, `PROJECT_DATABASE_URL` of `controls-web` and
  `controls-migrate` in compose, `scripts/verify-db-access.sh`; `scripts/tests/test_controls_catalogue_role_passwords.py`.

## Root changes suggested (not made)

- None for `controls_rw`: already done in the root (C3).
- `scripts/lib/throwaway-pg.sh`: `tpg_init_platform` could also load `init/report-roles.sql`, so module
  integration recipes need not add it (F7 fixed the README instead).

## Follow-ups

- F12, R2, R7 (user decisions).
- The answered-checklists page loads every submission with all its answers and pages in memory; fine at
  workshop scale, a DB-side count/skip/take later.
- `parseScore` accepts "4abc" as 4 (parseInt); harmless (the form sends radio values).
