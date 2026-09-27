# Rules for every stage (binding)

You are one stage of a pipeline (1 specs, 2 tests, 3 coding plan, 4 code, 5 verify), each done by a fresh
agent that has not seen the conversation with the user. Inputs: BRIEF.md, this file, earlier stages' outputs,
the code. Do your stage only, write its output, add a PROGRESS.md row, stop.

- If an earlier stage or the brief is wrong, write it under "Deviations" with the reason. A business decision
  only the user can make goes under "Questions for the user" with a default marked `DEFAULT (user to confirm)`.
- Repos: /home/listuser/aisc-install (branch feat/unified-modules; apps/control-objectives is a submodule),
  /home/listuser/aisc-report-generator (dev); the isolation worktree /home/listuser/aisc-isolation is READ-ONLY
  for you (another session owns it). Local commits only, NEVER push, no new branches.
- Other sessions work in aisc-install at the same time: never stage, reset, stash, clean or checkout their
  files; commit only your own files (by path).
- Out of bounds: the engine (apps/backend, apps/eval, shared/*), AIRO files, the catalogue app.
- Never write to the live stack or its databases (live postgres = container `postgres`); SELECT is fine.
  Tests use throwaway `aisc-t-*` postgres containers, removed afterwards; leave other sessions' containers alone.
  Disk is tight: check `df -h`, remove only what you create.
- TDD from stage 2 on. Business logic in Python; UI thin. No em dashes in docs or UI text.
