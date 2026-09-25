# Part 2, re-verification of fix round 1 (report run v2)

Status: done, 2026-09-25 11:19 to 11:31. Inputs: RULES.md, 00-baseline.md, BRIEF-2.md, 14-verify-part2.md,
15-fix-part2-round1.md and the code. Nothing was fixed. Parent-commit and mutation runs used temporary git worktrees
in the scratchpad (`git worktree add --detach`), removed afterwards; I checked that the package under test was
imported from the worktree. `env | grep -iE 'DATABASE|DSN|DB_URL'` printed nothing before the database runs.

## Verdict: PASS WITH NOTES

The 3 fixes of 15 hold. Each new test fails on its parent commit for the stated reason (items 1 and 3), and the
item 2 browser test fails under 5 different breakages of the notice feature. Every suite count equals 15, with 0
skips, and the only failures are the 3 attributed to other people's work. The guard output equals 00-baseline.md.
No test was weakened, nothing was pushed, and the live report containers are untouched. The outline cache can
still be pushed past its intent in 3 narrow ways (findings 1 to 3, all low). D1 leaves a few English-only
leftovers in code comments, a dead branch and a stale docstring (finding 4). None blocks.

## A. The 3 fixes

### Item 1: outline block types cached, short timeout (aisc-install 08f0581)

- Read: `renderer_calls.BlockTypesCache` (60 s TTL, failure gives `[]` kept 10 s, a lock around the read and write
  but not around the fetch), `outline_block_types()` (one cache per app on `app.state`), and
  `HttpRendererClient.block_types_quick()` with `quick_timeout=2.0`. Only the outline route uses it.
- Parent run (08f0581^ with the new test file): **8 failed**. The 4 cache tests fail on the missing
  `BlockTypesCache`; `TypeError: ... unexpected keyword argument 'quick_timeout'`; `AttributeError: ... no attribute
  'quick_timeout'`; the route test `assert 5 == 1` (5 block-types calls for 5 outline requests); the hung-renderer
  test "the outline used the call with the long timeout". This is the reason 15 states.
- Break attempts (script against the real classes, composer venv):
  - Renderer restarted with a new block type within the TTL: at +30 s the cache still returns the old list; at
    +61 s it returns the new one. See finding 2.
  - 8 concurrent requests on an empty cache with a renderer that hangs 2 s: **8 fetches**, wall time 2.0 s. The
    next request within 10 s makes 0 fetches. See finding 1.
  - 10 s back-off: a fetch that takes 2 s and fails is not repeated 9.9 s after it ended (the back-off counts
    from the end of the fetch). Holds.
  - A renderer that answers 200 and then sends the body one byte every 0.3 s, `quick_timeout=0.5`: the call
    returns after **9.3 s**, not 0.5 s. See finding 3.

### Item 2: the notices test is a browser test (aisc-install 31e37b4)

- Read: the old grep test in test_p2_presets.py is removed; the new Playwright test imports a preset file with a
  foreign chart id and evaluation ids on the layouts page, then checks the editor's message region, the `ok` class
  and that a reload clears it.
- At HEAD in a worktree: 1 passed. Five breakages, each run separately and reverted:

| breakage | result |
|---|---|
| composer.js `keepNotices` stores nothing | failed: timeout waiting for the notice |
| composer.js shows only the first notice | failed: block 3's evaluations text missing |
| composer.js never removes `rc-notices` | failed: notice still shown after reload |
| api.py:168 returns `notices = []` (Python side) | failed: timeout waiting for the notice |
| composer.js shows the notice as an error | failed: `assert 'ok' in ''` |

  The test catches the feature breaking at both the Python and the JS end.

### Item 3: English sample data in the interface's i18n tests (interface 777303f)

- Read: fr.json becomes en.json with English texts; the bad-code list (english, EN, en_GB, en-gb, "") and the
  region code (en-GB) keep the same shapes as before; the plural tests keep the rule `[0, 1]` as sample data, so they
  still prove that the rule decides. No assertion was weakened. i18n.py changes only a docstring and an error text.
- Parent run (777303f^): with only the new test added, **1 failed, 25 passed**
  (`['fr.json'] == ['en.json']`), as 15 states. With the whole new test file, 3 failed: the new test plus the two
  package-catalogue tests that ask for `en`, which the parent's sample package did not have. Both are expected.

## B. Suites (re-run by this stage)

| suite | head | result | 15 |
|---|---|---|---|
| aisc-report-plugin-interface | dev 777303f | 140 passed, 0 skipped | 140 |
| aisc-report-langbite | dev ab01898 | 43 passed | 43 |
| aisc-report-strongreject | dev 00517cd | 26 passed | 26 |
| aisc-report-promptfoo | dev 1f4cb73 | 29 passed | 29 |
| aisc-report-mlareject | dev 247a0d9 | 20 passed | 20 |
| aisc-report-generator (goldens, test_e2e_v2) | dev 51a9b29 | 640 passed, 0 failed, 0 skipped (JUnit), 119 s | 640 |
| apps/report-composer (5 browser tests, 3 e2e tests) | aisc-install bfcb4c8 | 417 passed, 0 failed, 0 skipped (JUnit), 192 s | 417 |
| scripts stack + grants + throwaway_rows | same | 94: 91 passed, 3 failed | same |
| scripts/pipeline_chain/test_dashboard_queries.py (recorded only) | same | 3 passed | 3 |
| scripts/guard-frozen.sh | same | exit 1; G1 FAIL (238 lines), G2 PASS, G3 PASS (hashes), G3 PASS (tests/test_vendored.py), the three G4 FAIL lines, G5 PASS | equals 00-baseline.md |

Browser tests seen in the composer JUnit: test_p2_browser `test_r2_d3_3_1_...` and
`test_r2_d3_6_2_the_composer_shows_notices_as_information`; test_v2_browser `test_fix_the_preview_recovers...`,
`test_fix_chapter_indentation_follows_a_move`, `test_fix_r2_5_an_older_outline_answer_arriving_last_is_ignored`.
E2e: generator `test_e2e_v2_preview_pdf_and_docx`; composer `test_e2e_compose_preview_and_generate`,
`test_e2e_pinned_to_version_1`, `test_e2e_v2_preset_coverage_draft_pdf_and_docx`.

The 3 scripts failures, with the reason read from the output:
- `test_d6_guard_init_files_do_not_mention_report_roles`: `report_ro` in `init/project-databases.sql`, last changed
  by 3e20ffb (another session's commit).
- `test_r4_1_2_launcher_card_seven`: the composer card shows 6. `homepage/project.html` has another session's
  uncommitted change (62+/44- now).
- `test_final_guard_frozen_passes`: guard exit 1 with the baseline lines.

## C. Test integrity since the 14 commit (f2f00c0)

- Test changes in the range: composer `test_p2r1_outline_types.py` (new, 8 tests), `test_p2_browser.py` (1 test
  added), `test_p2_presets.py` (the grep-only notices test removed, replaced by the browser test of the same name);
  interface `test_v2_i18n.py` (data changed to English, one test renamed from `..._in_french` to
  `..._for_the_counts_the_rule_names` with the same assertions, one test added). Nothing else in the report repos
  changed (generator, the three tool packages and mlareject have the same heads as 14).
- `scripts/tests/test_schema_docs.py` (63523a5) is another session's test, not a report file.
- Skip, xfail, importorskip or flaky added: none in the diffs; JUnit skipped = 0 in every suite.

## D. English only (BRIEF-2 D1): leftovers with file:line

Grep over every tracked file of the 6 report repos and apps/report-composer, plus scripts/tests/test_report_*.py,
for accented letters, French words, `fr` codes, `fr.json`, `French`, `REPORT_I18N_PATH` and `language`. No
`fr*.json` file exists on disk. No French reaches the output or the UI.

Production code (all harmless, but not English-only in spirit):
- `aisc-report-generator/report_renderer/blocks/risk_classification.py:125`:
  `risk_class=t(stated) if ctx.language != "en" else stated`. Dead branch, since `ctx.language` is always "en".
- `aisc-report-generator/report_renderer/blocks/key_figures.py:143`: comment "values in the report language".
- `aisc-report-generator/report_service.py:55` and `:57-59`: `/health` lists `languages` and `GET /v1/languages`
  still exists (returns English only). Allowed by D1 ("the mechanism may stay").
- Docstrings saying values "follow the report language":
  `aisc-report-langbite/vera_report_plugin_langbite/renderer.py:87`,
  `aisc-report-strongreject/vera_report_plugin_strongreject/renderer.py:68`,
  `aisc-report-promptfoo/vera_report_plugin_promptfoo/renderer.py:64`,
  `aisc-report-plugin-interface/vera_report_plugin_interface/tools.py:53-56`.
- Kept by design (compatibility): `report_renderer/snapshot.py:43` (language pattern in the snapshot schema),
  `report_renderer/document.py:223` and `context.py:181` (force "en"), composer migration `0005...sql:6,7,34`
  (unused language columns, Q2-2).

Tests and fixtures:
- Stale docstring: `aisc-report-generator/tests/v2_core_helpers.py:10` (`report_renderer/i18n/{en,fr}.json;
  REPORT_I18N_PATH read ...`). Named in 14 and 15, still there.
- French user text as compatibility input: `aisc-report-generator/tests/test_e2e_v2.py:22,24,25,30,78` ("Rapport
  Mijke", "Les outils de test.", "Trois outils ont tourné.", "Réponses complètes."), `tests/test_i18n.py:113,124`
  ("Rapport Mijke", "Mon titre"), `tests/test_header_footer.py:165` ("Réponses aux contrôles" as a Unicode sample).
- `language="fr"` / `"fr"` as compatibility input that must render English (R2-C.1): generator
  `test_e2e_v2.py:4,38,66`, `test_i18n.py:112,117,135,144`, `test_p2_english.py:35,72,77,88,96,105,117,119,132,142,152,156`,
  `test_snapshot_v2.py:54,82,92`, `test_v2_key_figures.py:150`; interface `test_v2_contracts.py:179,201,215,216,227`;
  composer `test_e2e_v2.py:9,107,118`, `test_p2_english_only.py:5,66,75,127,130,179,196,200,213,215`,
  `test_v2_draft_preview.py:40`, `test_v2_layout_settings.py:43`.
- Guards that fr.json is gone: langbite `test_p2_langbite.py:138-139`, `test_packaging.py:68`; strongreject
  `test_p2_strongreject.py:4-5,45-46`, `test_packaging.py:68`; promptfoo `test_p2_promptfoo.py:94-95`,
  `test_packaging.py:68`; generator `test_i18n.py:34`.
- Tool data, not language choice: `fr_fr` in `aisc-report-langbite/tests/fixtures.py:35`,
  `tests/test_tool_renderer.py:69` and generator `tests/golden/m_v2_live_styled.html:712`; `language: "fr"` as a
  measurement dimension in `aisc-report-mlareject/tests/test_statistics.py:21,40,60`,
  `tests/test_tool_renderer.py:19` and `aisc-report-plugin-interface/tests/test_tools.py:102`.

## E. Boundaries

- Nothing pushed: aisc-install 177 ahead, generator 53, interface 12, mlareject 4, 0 behind; `git branch -r
  --contains` is empty for 08f0581 and 777303f. The 3 new packages have no remote and one branch (dev).
- Fix-round commits: 08f0581 (composer code + new test), 31e37b4 (composer tests), 0894033 (15 + PROGRESS),
  interface 777303f. No frozen area, no other person's file. 63523a5 and bfcb4c8 (Caddyfile, inspector/schema-docs,
  platform, test_schema_docs) are another session's work.
- Other people's working-tree changes (`apps/qualification`, `homepage/project.html`, untracked docs) are still
  unstaged.
- Live stack: `report-composer` and `report-renderer` started 2026-09-24 16:02:31-32 UTC, `report-grants` exited 17
  h ago, unchanged. No `*:report-v2-test` image.
- Leftovers of this stage: none. Worktrees removed (`git worktree list` shows only the main trees), no `aisc-t-*`
  container, guard output kept in my scratchpad. Not mine: 53 `/tmp/guard-frozen.*` / `guard-work.*` folders
  (9.4 MB, 2026-09-23 to 10:52 today) left by earlier runs of `test_final_guard_frozen_passes`, which runs the guard
  without `GUARD_OUT` (note 5). Disk: 99 GB free at the start.

## Findings

1. **Low**, `apps/report-composer/report_composer/renderer_calls.py:62-71` (`BlockTypesCache.get`). The fetch runs
   outside the lock, so there is no single flight. Failure scenario: the renderer hangs while several editors
   (or one editor's queued edits) hit the outline route at the moment the cache is empty or expired; every request
   fetches and holds a worker for the quick timeout. Measured: 8 concurrent requests made 8 fetches of 2 s each.
   Bounded (2 s, then 10 s of back-off), so far better than the 120 s of before.
2. **Low**, same file, line 57 (`ttl=60.0`). After a renderer restart that adds a plugin block type, the outline keeps the
   old list for up to 60 s. Failure scenario: a user adds the new block (the palette uses the uncached
   `block_types`) and fills it; for up to a minute the "not written yet" hint uses the fixed prose list, so a
   placeholder in the new block's own prose options is not flagged. Generation is unaffected.
3. **Low**, `apps/report-composer/report_composer/renderer_client.py:44-45`. `httpx.Client(timeout=2.0)` limits
   each read, not the whole call. Failure scenario: a renderer (or proxy) that sends the answer slowly holds the
   outline worker far past 2 s; measured 9.3 s with a 0.5 s quick timeout, and it grows with the body. Unlikely
   with the real renderer; a total deadline would close it.
4. **Note** (D1), leftovers listed in section D: the dead branch at `risk_classification.py:125`, the "report
   language" comment and docstrings, `GET /v1/languages`, and the stale docstring at
   `aisc-report-generator/tests/v2_core_helpers.py:10`. No French text in output, UI, language files or production
   code. French user text in tests is compatibility input.
5. **Note** (environment), `scripts/tests/test_report_stack.py` `test_final_guard_frozen_passes` runs the guard
   without `GUARD_OUT`, so each run leaves a `/tmp/guard-frozen.*` folder (53 so far). Not from this fix round.
6. **Note** (carried from 14), `POST /api/presets/import` still has no caller in the UI; its notices reach API users
   only. The page's import path is covered by the new browser test.

## State of the run

Part-2 commits (all local, none pushed):

| repo | commits |
|---|---|
| aisc-report-plugin-interface | cd3cc1e (tests), 7ba6120, 777303f (fix round 1, item 3) |
| aisc-report-generator | d213334, 8410eac, 73c43ea, 8167003, fe30ed2 (tests); a13fe49, 8ed9c65, 74fd5b4, 90fac3d, 005b2d2, 84b7903; 51a9b29 (test, D13-1) |
| aisc-report-langbite | 8389157, 8c5d646, 5f0fe82 (tests), f5c0caf (test fix), 1a58eff, ab01898 |
| aisc-report-strongreject | 440c697, 60a03fe, 8fa948f (tests), 00517cd |
| aisc-report-promptfoo | b5fc3a6, b33df81, 918bc36 (tests), 20cec8c, 1f4cb73 |
| aisc-report-mlareject | 247a0d9 (test) |
| aisc-install | f7fd0f0 (BRIEF-2), dc7bf07 (10), 43bb723, b162d16, 3041352, d446ee2 (tests), 29b65e4 (11), b52751b (12), 22653b0, 4741bee, 7cf5f71, 718100d, 5b87788, 89db07e, 6598b29, 7853afb, 8d42698, 343b1fe, d4e4c62, 196e62f (13), f2f00c0 (14), 08f0581, 31e37b4 (fix round 1), 0894033 (15), and this file's commit |

Questions still open for the user (defaults in force):
- Finding 4 of 14 (untouched by 15): the report's own fixed cuts, a checklist mean below 3 marks coverage
  "attention" (`report_renderer/coverage.py:5-6`) and the MLA-Reject 1.5 harmful/empty split
  (`vera_report_plugin_mlareject/statistics.py:10`). Acceptable under "no thresholds"?
- Q2-1 to Q2-8 of 10-specs-part2.md (REPORT_I18N_PATH removed; language columns kept unused; a tool's Fail does
  not mark coverage; promptfoo shares only; MLA-Reject 1.5 split kept; an unwritten free text left out whole;
  built-in preset titles as they are; French documents already generated stay stored).
- The earlier defaults of 01-specs section 20 that BRIEF-2 keeps (Q2, Q4 to Q8, Q10, Q2-1, Q3-2).
- New and optional: findings 1 to 3 (single flight, a shorter TTL or a refresh on unknown block types, a total
  deadline) and the D1 clean-up of finding 4. Whether `GET /v1/languages` should stay.
- Deploy and push remain the user's decision; nothing of part 2 is deployed or pushed.
