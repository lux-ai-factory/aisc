# Part 2, fix round 2 (report run v2, the last fix round)

Status: done, 2026-09-25 11:27 to 11:47. Inputs: RULES.md, BRIEF-2.md, 15-fix-part2-round1.md, 16-reverify-part2.md
and the code. Findings 1 to 3 (outline cache) and 4 (English-only leftovers) of 16-reverify-part2.md fixed, test
first. The report's fixed cuts (checklist mean below 3, MLA-Reject 1.5) were not touched: user decision.
Nothing pushed. The live `aisc` stack was not touched (`report-composer` and `report-renderer` up 18 hours).
`env | grep -iE 'DATABASE|DSN|DB_URL'` printed nothing before each database run.

## Item 1: the outline's block-types cache (findings 1 to 3 of 16)

- Commits (aisc-install):
  - 9caeba0 (test only): the two round-1 route tests in `test_p2r1_outline_types.py` empty the cache after
    `new_layout`, since saving a layout now fills it (see (b)). Their assertions are unchanged (exactly 1 call;
    the quick call used once).
  - a11c894: `renderer_calls.py`, `renderer_client.py`, new `tests/test_p2r2_outline_cache.py`.
- (a) Single flight. `BlockTypesCache.get` starts a fetch only if none is in flight. While one runs, another
  caller takes the older list at once if there is one; on an empty cache it waits for the fetch, at most `wait`
  seconds (default 3, just above the 2 s deadline), then uses `[]` (the DV12-6 fixed prose list). A fetch never
  overwrites a fresher `put` that arrived while it ran.
- (b) A restarted renderer is seen at once. Chosen option: every uncached block-types call
  (`renderer_calls.block_types`, used by the palette `GET /api/block-types`, validate, save, preview, generate,
  presets and the editor page) puts its fresh answer into the outline cache (`put`, a new 60 s TTL).
  Why this one: it needs no change to the renderer or its contract (no registry version), no guessing from
  error texts, and it covers the only way a user reaches a new block type: the palette, which asks the renderer
  directly. The 60 s TTL remains only as a backstop when nothing else asks.
- (c) A deadline for the whole call. `block_types_quick()` now goes through `_call_within(quick_timeout, ...)`:
  the call runs in a helper thread and the caller gets the answer or `RendererTimeout` after at most 2 s. The
  helper streams the body and stops at the next piece after the deadline; a renderer dripping its headers ends
  the helper at the next per-step timeout or when the headers end (bounded by httpx's header size limit). All
  other calls keep `_call` with the 120 s timeout, unchanged in behaviour (status handling moved to `_answer`).
- Tests (10 new):
  - cache: 8 concurrent `get` on an empty cache make 1 fetch and all get its answer; during a refresh the
    others get the older list at once (under 0.5 s) with no second fetch; waiters give up after `wait` and use
    `[]`; a `put` is used without a fetch and starts a new TTL;
  - route (db): 6 concurrent outline requests on an empty cache make 1 block-types call; after a "restart" that
    adds a plugin block type, the palette call or a validate call makes the next outline flag the new block's
    placeholder (`[["notes"]]` instead of `[[]]`), 2 parametrised cases;
  - client: a local socket dripping the body one byte every 50 ms, and one dripping the headers, each raise
    `RendererTimeout` in under 1.5 s with `quick_timeout=0.5` (the whole answer would take over 15 s); a prompt
    answer still comes through.
- Seen failing first: 9 failed, 1 passed (the prompt-answer guard): `wait` and `put` missing, `6 == 1` calls,
  `[[]] != [["notes"]]` twice, `DID NOT RAISE RendererTimeout` twice (each call took about 16 s).
  After: 10 passed; composer 427 passed.

## Item 2: English-only leftovers (finding 4 of 16, section D)

- Commits: generator f632271, interface cd1b023, langbite 0885c46, strongreject 7d1d90e, promptfoo de15e17.
- Fixes:
  - `report_renderer/blocks/risk_classification.py:125`: dead branch `t(stated) if ctx.language != "en" else
    stated` becomes `stated` (same output, since the language is always "en").
  - `key_figures.py:143` comment, `languages.py` module docstring ("The report's language file, English only"),
    `tests/v2_core_helpers.py:10` (now names `en.json` only, no `REPORT_I18N_PATH`).
  - The `headline()` docstrings of langbite, strongreject and promptfoo and of the interface's `tools.py` now
    say values are formatted with `ctx`, not "in the report language".
- Kept as asked: `GET /v1/languages`, `/health`'s `languages`, the snapshot's language pattern, and every "fr"
  compatibility input in tests. Goldens byte-identical (`git status tests/golden` empty, golden tests pass).
- Tests: `tests/test_p2r2_english_only.py` in each of the 5 repos (generator: no `language ==/!=` branch and no
  "report language", fr.json, `{en,fr}`, `REPORT_I18N_PATH` or "French" in `report_renderer`, `report_service.py`
  and `tests/v2_core_helpers.py`; the others: no such wording in the package). Seen failing first in all 5
  (generator 2 failed, naming the 4 lines above; one failure in each other repo), then passing.

## Final run (after the last commit)

| suite | head | result | 16 |
|---|---|---|---|
| aisc-report-plugin-interface | dev cd1b023 | 141 passed | 140 |
| aisc-report-langbite | dev 0885c46 | 44 passed | 43 |
| aisc-report-strongreject | dev 7d1d90e | 27 passed | 26 |
| aisc-report-promptfoo | dev de15e17 | 30 passed | 29 |
| aisc-report-mlareject | dev 247a0d9 | 20 passed | 20 |
| aisc-report-generator (goldens, test_e2e_v2) | dev f632271 | 642 passed, 0 failed, 0 skipped (JUnit) | 640 |
| apps/report-composer (5 browser tests, 3 e2e) | aisc-install a11c894 | 427 passed, 0 failed, 0 skipped (JUnit) | 417 |
| scripts stack + grants + throwaway_rows | same | 94: 91 passed, 3 failed (the 3 known others' failures) | same |
| scripts/pipeline_chain/test_dashboard_queries.py (recorded only) | same | 3 passed | 3 |
| scripts/guard-frozen.sh | same | exit 1; G1 FAIL (238 lines), G2 PASS, G3 PASS (hashes), G3 PASS (tests/test_vendored.py), the three G4 FAIL lines, G5 PASS | equals 00-baseline.md |

The 3 scripts failures are the ones 16 attributes to other people's work: `test_d6_guard_init_files_...`,
`test_r4_1_2_launcher_card_seven`, `test_final_guard_frozen_passes`.

Leftovers: none. The scripts tests and the guard ran with `TMPDIR` and `GUARD_OUT` in my scratchpad, so no new
`/tmp/guard-*` folder (still 53, not mine); the scratchpad is emptied. No `aisc-t-*` container left, no image,
no worktree. Other people's changes in aisc-install (`apps/qualification`, `homepage/project.html`, untracked
docs and `__pycache__`) were not staged or touched.

## Deviations

- 9caeba0 changes two round-1 tests (an empty cache before the counted requests), because (b) lets a save fill
  the cache. No assertion was weakened.
- Item 1 is two commits (the test adjustment first, then the fix with its tests), item 2 one commit per repo.

## Questions for the user

- Still open: the report's fixed cuts (checklist mean below 3 in coverage, MLA-Reject 1.5 split).
- Deploy and push remain the user's decision; nothing of part 2 is deployed or pushed.
