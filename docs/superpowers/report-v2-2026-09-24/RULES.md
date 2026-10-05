# Rules for every stage of report run v2 (read this first; binding)

You are one stage of a five-stage pipeline: 1 specs, 2 tests, 3 coding plan, 4 code, 5 verify.
Each stage is done by a fresh agent that has NOT seen the conversation with the user. Your only
inputs are the files in this folder and the code. Do your stage only, write its output file, add a
row to PROGRESS.md, and stop. Do not do the next stage's work.

## Inputs
- BRIEF.md: what the user asked for (the requirements). It is the source of truth for scope.
- 00-baseline.md: repo heads, guard-frozen output and test counts before the run.
- The previous report run, for context on how the system was built:
  /home/listuser/aisc-install/docs/superpowers/report-2026-09-23/ (RULES, 01-specs, 02-architecture,
  03-tests, 04-coding-plan, 05-report). Its decisions still hold unless BRIEF.md changes them.
- The outputs of the stages before yours (01-specs.md, 02-tests.md, 03-coding-plan.md, 04-code-report.md).

## If you disagree with an earlier stage
Earlier stages are not sacred, but you are not free to silently rewrite them. If a spec is wrong,
contradictory or impossible, write it in your output under "Deviations" with the reason and what you
did instead. If the question can only be answered by the user (a business decision, not a technical
one), write it under "Questions for the user", pick the least surprising default, mark it
`DEFAULT (user to confirm)`, and continue. Stop the whole stage only if no reasonable default exists.

## Repos and branches (local commits only, NEVER push, no new GitHub repos, no new branches)
- /home/listuser/aisc-report-generator, branch dev (the renderer)
- /home/listuser/aisc-report-plugin-interface, branch dev (block and tool renderer contracts)
- /home/listuser/aisc-report-mlareject, branch dev (the one existing tool renderer, an example)
- /home/listuser/aisc-install, branch feat/unified-modules; the composer is apps/report-composer
  (a plain folder, not a submodule). Run docs live in docs/superpowers/report-v2-2026-09-24/.
- New tool renderer packages (for LangBiTe, StrongREJECT, promptfoo) are new LOCAL folders next to
  aisc-report-mlareject (for example /home/listuser/aisc-report-langbite), each its own local git repo
  on branch dev, modelled on aisc-report-mlareject. No GitHub repo is created for them.

Other people work in aisc-install at the same time. Their uncommitted files (see 00-baseline.md, and
check `git status` yourself) stay untouched and unstaged. Commit only your own files; for a file you
share with them, stage only your hunks (`git apply --cached` with a filtered patch). NEVER run
`git reset --hard`, `git checkout -- .`, `git stash`, `git clean` or anything that touches other
people's working-tree changes. Commit messages are plain sentences saying what the change does.

## FROZEN / out of bounds (read, never change)
1. The engine: apps/backend (models, tables, migrations), apps/eval, shared/plugin-interface,
   shared/plugin-manager. The report only READS engine data.
2. AIRO: the vendored AIRO/VAIR files, qualification's knowledge_graph and QualificationRisk.
3. The catalogue (apps/catalogue and its DB schema).
4. Other modules' code (qualification, controls, control-objectives, webapp, platform, results-dashboard).
   If a requirement truly needs a change there, write it under "Questions for the user" instead.
`/home/listuser/aisc-install/scripts/guard-frozen.sh` must print the same lines as in 00-baseline.md.

## Safety
- The running stack (compose project `aisc`) is the user's live demo: NEVER docker compose up/down/build/
  restart/run/exec-that-writes against it, NEVER write to its databases (live postgres is the `postgres`
  container on 127.0.0.1:5432). Reading the live DB to learn the real schema or real measurement shapes is OK.
- Tests use throwaway postgres:14-alpine containers named `aisc-t-*` on free ports, removed afterwards
  (helper: aisc-install/scripts/lib/throwaway-pg.sh). Check every DB URL env var before running tests.
- Building a NEW image for a smoke test is fine if tagged `*:report-v2-test` and removed afterwards;
  never rebuild or retag the stack's own images. No deploy to the live stack in this run.
- TDD: tests are written in stage 2, before any implementation. Stage 4 does not weaken, skip or delete
  a stage-2 test to get green; if a test is wrong, fix it in a separate commit and list it under Deviations.
- Business logic in Python (the user reads Python, not JS/TS). The composer's JS stays thin: it draws
  what Python returns and sends user input back.
- Every new option must default to today's behaviour: an existing saved layout renders the same output
  after the run as before it (apart from bug fixes listed in the spec).
- Docs and UI text: no em dashes. Plain, short sentences.

## Output of every stage
- Your file in this folder (01-specs.md, 02-tests.md, 03-coding-plan.md, 04-code-report.md, 05-verify.md).
- A row in PROGRESS.md: stage, start and end time, output, status, one line of result.
- Your final message to the orchestrator: what you did, what is left, any Questions for the user,
  in at most 25 lines.
