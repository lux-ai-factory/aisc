# Part 2, final verification of fix round 2 (report run v2)

Status: done, 2026-09-25 11:47 to 11:58. Inputs: RULES.md, 00-baseline.md, BRIEF-2.md, 16-reverify-part2.md,
17-fix-part2-round2.md and the code. Nothing was fixed. Parent-commit runs and break attempts used temporary
worktrees in my scratchpad (`git worktree add --detach`), removed afterwards; the package under test was imported
from the worktree (checked with `__file__`). `env | grep -iE 'DATABASE|DSN|DB_URL'` printed nothing before the
database runs. Every database test ran on its own `aisc-t-*` container, none left.

## Verdict: PASS WITH NOTES

Both items of 17 hold. Every new test fails on its parent commit for the reason 17 states and passes at HEAD. The
cache survived 20 parallel requests, a hung renderer, a renderer dripping its body or its headers, a restart with a
new block type and a renderer that is down. The two round-1 tests changed in 9caeba0 kept their assertions, and
without that change they fail at HEAD for the reason 17 gives. Every suite count equals 17, with 0 skips; the only
failures are the 3 attributed to other people's work. The guard output equals 00-baseline.md. No French or
report-language wording is left beyond what BRIEF-2 allows, and the goldens are byte-identical. No test was
weakened, nothing was pushed, and the live report containers are untouched. One low finding (helper threads can
pile up behind a renderer that drips its headers) and five notes, none blocking.

## 1. The two items of 17

### Item 1: outline block-types cache (aisc-install 9caeba0, a11c894)

Read: `BlockTypesCache.get` (single flight with an Event, `wait` 3 s, `put` counter so a fetch never overwrites a
fresher put), `renderer_calls.block_types` now calls `put` (used by the palette, validate, save, preview, generate,
presets and the editor page, `pages.py:121`; no other code path fetches block types), and
`HttpRendererClient._call_within` (helper thread, whole-call deadline, streamed body checked against the deadline).
All other client calls keep `_call` with 120 s, status handling moved unchanged to `_answer`.

Parent run (worktree at 9caeba0 = a11c894^, new test file copied in): **9 failed, 1 passed** (the prompt-answer
guard). Reasons: `unexpected keyword argument 'wait'` (3 cache tests), route `assert 6 == 1`,
`no attribute 'put'`, `[[]] == [['notes']]` twice (palette, validate), `DID NOT RAISE RendererTimeout` twice (body,
headers). Exactly as 17 states. At HEAD: 10 passed.

9caeba0 adds only one line per test (`client.app.state.outline_block_types = None`); no assertion changed (`exactly
1 call`, `the quick call used once` are intact). Check of the justification: at a11c894 with those two lines removed,
both tests fail (`assert 0 == 1` for `type_calls` and `quick_calls`), because saving the layout now fills the cache.

Break attempts (real `BlockTypesCache` + `HttpRendererClient` against a local socket server; route level through
the composer app on a throwaway bed):

| attempt | result |
|---|---|
| 20 parallel `get` on an empty cache, renderer answers in 1 s | 1 renderer hit, all 20 get the list, 1.04 s max |
| 20 parallel `get` on an empty cache, renderer hangs 5 s | 1 hit, all 20 get `[]` after 2.0 s max; 20 more within 10 s: 0 hits, 0.0 s |
| 20 parallel on an expired cache holding an older list, renderer hangs | 1 hit; 19 get the older list at 0.0 s, the fetching one gets `[]` at 2.0 s (note 2) |
| 20 parallel `POST .../outline` through the app, slow fake (0.5 s) | 20 x 200, 1 block-types call |
| body dripped 1 byte every 0.3 s | `RendererTimeout` at 2.0 s |
| headers dripped 1 byte every 0.5 s | `RendererTimeout` at 2.0 s; the helper thread stays alive (finding 1) |
| renderer restarted with a new block type, outline asked right after | old list (no other call yet); after `GET /p/alpha/layouts/{id}` (editor page) the next outline flags `[["notes"]]` (note 3) |
| renderer down entirely (closed port), 20 parallel `get` | all `[]` in 0.02 s |
| renderer down, 20 parallel outline requests through the app | 20 x 200 in 0.2 s; the palette answers 502, the next outline still 200 |
| renderer answers 200 with a non-JSON body | the fetching call raises `JSONDecodeError` (500 for that request), then `[]` for 10 s (note 4, same as before 08f0581) |

### Item 2: English-only leftovers (generator f632271, interface cd1b023, langbite 0885c46, strongreject 7d1d90e, promptfoo de15e17)

Read: each commit changes only the lines 16 named plus a new `tests/test_p2r2_english_only.py`. The
`risk_classification.py:125` change keeps the output, since `context.py:181` and `document.py:223` force "en".

Parent runs (worktree at each commit's parent, new test copied in): generator **2 failed** (the `language !=`
branch at `risk_classification.py:125`; 3 stale lines: `key_figures.py:143`, `languages.py:1`,
`tests/v2_core_helpers.py:10`); interface, langbite, strongreject, promptfoo **1 failed** each (`tools.py:54`,
`renderer.py` headline docstring). At HEAD all pass.

## 2. Suites (re-run by this stage)

| suite | head | result | 17 |
|---|---|---|---|
| aisc-report-plugin-interface | dev cd1b023 | 141 passed, 0 skipped (JUnit) | 141 |
| aisc-report-langbite | dev 0885c46 | 44 passed, 0 skipped | 44 |
| aisc-report-strongreject | dev 7d1d90e | 27 passed, 0 skipped | 27 |
| aisc-report-promptfoo | dev de15e17 | 30 passed, 0 skipped | 30 |
| aisc-report-mlareject | dev 247a0d9 | 20 passed, 0 skipped | 20 |
| aisc-report-generator (12 golden tests, 4 e2e incl. test_e2e_v2_preview_pdf_and_docx) | dev f632271 | 642 passed, 0 failed, 0 skipped (JUnit), 115 s | 642 |
| apps/report-composer (5 browser tests, 3 e2e) | aisc-install 606d2a1 | 427 passed, 0 failed, 0 skipped (JUnit), 200 s | 427 |
| scripts test_report_stack + test_report_grants + test_throwaway_rows | same | 94: 91 passed, 3 failed | same |
| scripts/pipeline_chain/test_dashboard_queries.py (recorded only) | same | 3 passed | 3 |
| scripts/guard-frozen.sh | same | exit 1; G1 FAIL (238 lines), G2 PASS, G3 PASS (hashes), G3 PASS (tests/test_vendored.py), the three G4 FAIL lines, G5 PASS | equals 00-baseline.md |

Composer browser tests seen in the JUnit: `test_r2_d3_3_1_...`, `test_r2_d3_6_2_...`, `test_fix_the_preview_recovers...`,
`test_fix_chapter_indentation_follows_a_move`, `test_fix_r2_5_...`.
E2e: `test_e2e_compose_preview_and_generate`, `test_e2e_pinned_to_version_1`, `test_e2e_v2_preset_coverage_draft_pdf_and_docx`.
My first composer run used a long `TMPDIR` in the scratchpad; Chrome then refused to start ("Socket path too long"),
giving 6 errors (the 5 browser tests and `test_r_u1_1`, which then hit Playwright's "use the Async API" error). Re-run with the default temp dir: 427
passed. Environment only (note 5).

The 3 scripts failures, reason read from the output:
- `test_d6_guard_init_files_do_not_mention_report_roles`: `report_ro` and `report_composer` in
  `init/project-databases.sql`, last changed by 3e20ffb (another session, 2026-09-24 19:34).
- `test_r4_1_2_launcher_card_seven`: `homepage/project.html` has another session's uncommitted change (62+/44-).
- `test_final_guard_frozen_passes`: guard exit 1 with the baseline lines.

## 3. English only

- Grep over every tracked non-test file of the 6 report repos and `apps/report-composer` for `fr.json`, French,
  français, "report language", "report's language", `language ==/!=`, `"fr"`, `REPORT_I18N_PATH` and accented
  letters: one hit, `report_renderer/languages.py:1` "The report's language file, English only" (accurate wording).
  No `fr*.json` is tracked; `report_renderer/i18n/` holds only `en.json` (no accented letter).
- Remaining `language` mentions are the allowed ones: `GET /v1/languages` and `/health`'s `languages`
  (`report_service.py:55-58`), the snapshot pattern (`snapshot.py:43`), the forced "en" (`context.py:181`,
  `document.py:223`), `<html lang>`, the DOCX core property, and composer docstrings saying a sent `language` is
  ignored, plus the unused columns of migration 0005 (Q2-2). No language control in the composer UI.
- "fr" in tests is compatibility input or tool data, as listed in section D of 16.
- Goldens: no commit touches `aisc-report-generator/tests/golden` after 8611de9 (their capture), `git status
  tests/golden` is empty, the 12 golden tests pass.

## 4. Test integrity and boundaries

- Test changes since the 16 commit (fc7e001, and generator 51a9b29, interface 777303f, langbite ab01898,
  strongreject 00517cd, promptfoo 1f4cb73): composer `test_p2r1_outline_types.py` (+2 lines, above),
  `test_p2r2_outline_cache.py` (new, 10 tests), and one new `test_p2r2_english_only.py` per repo. No line removed
  from any test; no skip, xfail, importorskip or flaky mark added (only `db`, `usefixtures`, `parametrize`).
  mlareject unchanged.
- Nothing pushed: aisc-install 181 ahead / 0 behind, generator 54/0, interface 13/0, mlareject 4/0; `git branch -r
  --contains` is empty for a11c894, 606d2a1 and each report repo's HEAD. The 3 new packages have no remote and the
  single branch dev.
- Commits since fc7e001 in aisc-install: 9caeba0, a11c894 (only `apps/report-composer/**`), 606d2a1 (17 and
  PROGRESS). No frozen area, no other person's file. All 52 run commits in aisc-install touch only
  `apps/report-composer`, the run docs, `scripts/pipeline_chain/throwaway.py`, `scripts/tests/test_throwaway_rows.py`
  and the report bed; the other 15 commits since 09a7cb2 are other sessions' (LLM keys, API auth, database diagrams).
- Other people's working-tree changes (`apps/qualification`, `homepage/project.html`, untracked docs and
  `__pycache__`) are still unstaged. A worktree `/home/listuser/aisc-isolation` (branch isolation/2026-09-25,
  created 11:49) belongs to another session; left alone.
- Live stack: `report-composer` started 2026-09-24T16:02:32Z and `report-renderer` 16:02:31Z, same image ids as
  before, unchanged. No `*:report-v2-test` image.
- Leftovers of this stage: none. Worktrees removed (each repo lists only its main tree), no `aisc-t-*` container,
  guard output in my scratchpad (then emptied), `/tmp/guard-*` still 53 (not mine). My composer run left 6
  `/tmp/com.google.Chrome.chrome_chrome_url_fetcher_.*` folders; removed (`/tmp` back to its 579 entries). Disk: 94 GB free.

## Findings

1. **Low**, `apps/report-composer/report_composer/renderer_client.py:99` (`_call_within`). The caller is freed after
   2 s, but the helper thread lives until the renderer's headers end or a single read waits longer than 2 s.
   Failure scenario: a renderer (or proxy) that drips its headers with gaps under 2 s. Each expiry of the 10 s
   failure TTL starts one more helper thread and socket while the old ones still read. Measured: 5 cycles with
   `failure_ttl=0.5` left 6 helper threads alive. At the real 10 s TTL that is about 6 threads a minute, each up to
   the header size limit. Requests are never delayed; only threads and sockets accumulate. Pathological renderer only.
2. **Note**, `renderer_calls.py:94-103`. A refresh that fails replaces the older good list with `[]` for 10 s. Failure
   scenario: after the 60 s TTL the renderer is briefly slow; for 10 s the "not written yet" hint of a plugin
   block falls back to the fixed prose list. Measured (table row 3). Keeping the older list on failure would avoid it.
3. **Note** (by design, 17 (b)), after a renderer restart with a new block type, an outline call with no uncached
   block-types call in between still uses the old list for up to 60 s. The editor page, palette, save and validate
   refresh it at once (measured), so the normal path is covered.
4. **Note** (pre-existing), a 200 answer with a non-JSON body raises `JSONDecodeError` from the fetch: that one
   outline request answers 500 instead of the fallback, then `[]` is used for 10 s. Same as before 08f0581.
5. **Note** (environment), the composer's Playwright tests fail to start Chrome when `TMPDIR` is a long path, and each
   run leaves about 6 `com.google.Chrome.chrome_chrome_url_fetcher_.*` folders in `/tmp` (179 from earlier runs,
   not mine). `test_final_guard_frozen_passes` still leaves a `/tmp/guard-frozen.*` folder when `GUARD_OUT` is unset.
6. **Note** (carried from 14 and 16), `POST /api/presets/import` still has no caller in the UI.

## State of the run

All commits of run v2, parts 1 and 2 (local only, none pushed, nothing deployed):

| repo | part 1 | part 2 |
|---|---|---|
| aisc-report-generator (41) | 8611de9, 29c54cc, c2382fe, d71ead9, 539fef5, 03688d0, 8473143, ac65a02, ead5924, 6c8da28, 617acf3, 52702df, 50b38ae, 5bb6f13, 800276d, 4c6e453, 5f1fd3c, 38d818e, a92502f, 7585b3b, 2047eea, 27e868f, 057e2df, 7bc92ca, 7e7024e, dfb3a51, 69a9046, f211e16 | d213334, 8410eac, 73c43ea, 8167003, fe30ed2, a13fe49, 8ed9c65, 74fd5b4, 90fac3d, 005b2d2, 84b7903, 51a9b29, f632271 |
| aisc-report-plugin-interface (11) | 7d93a31, f44fbd7, c77fc0b, 69549e8, 1193ab2, e9755a2, 7999876 | cd3cc1e, 7ba6120, 777303f, cd1b023 |
| aisc-report-mlareject (2) | 4942594 | 247a0d9 |
| aisc-report-langbite (11, new local repo) | f4af1d0, 4db2bf4, db7adbf, 4bbf943 | 8389157, 8c5d646, 5f0fe82, f5c0caf, 1a58eff, ab01898, 0885c46 |
| aisc-report-strongreject (8, new local repo) | 34cad23, 4af9b42, 8611f44 | 440c697, 60a03fe, 8fa948f, 00517cd, 7d1d90e |
| aisc-report-promptfoo (9, new local repo) | d7b8a4f, 41c4ab8, 2dcd7c1 | b5fc3a6, b33df81, 918bc36, 20cec8c, 1f4cb73, de15e17 |
| aisc-install (52 + this file's commit) | 9edb1e2, 1752778, 5f47cf2, b25b464, c0cabf8, e5fefde, bee8ff2, d24527d, 2689256, 1af887f, e664b2b, 57f2491, d884c52, 2815ddb, 8cf13ef, f03e6d5, 576b157, 80508ba, 2ae7778, 9e9be22, f6ceb16, 6515735, ab668a9, 7c6ebe0 | f7fd0f0, dc7bf07, 43bb723, b162d16, 3041352, d446ee2, 29b65e4, b52751b, 22653b0, 4741bee, 7cf5f71, 718100d, 5b87788, 89db07e, 6598b29, 7853afb, 8d42698, 343b1fe, d4e4c62, 196e62f, f2f00c0, 08f0581, 31e37b4, 0894033, fc7e001, 9caeba0, a11c894, 606d2a1, and this file's commit |

Final counts: interface 141, LangBiTe 44, StrongREJECT 27, promptfoo 30, MLA-Reject 20, generator 642/0 failed,
composer 427/0 failed, scripts 91 + the 3 others' failures, dashboard queries 3, 0 skips everywhere; guard = baseline.

Questions still open for the user (defaults in force):
- The report's own fixed cuts: a checklist mean below 3 marks coverage "attention" (`report_renderer/coverage.py:5-6`),
  and the MLA-Reject 1.5 harmful/empty split (`vera_report_plugin_mlareject/statistics.py:10`). Acceptable under
  "no thresholds"?
- Q2-1 to Q2-8 of 10-specs-part2.md: REPORT_I18N_PATH removed; language columns kept unused; a tool's Fail does not
  mark coverage; promptfoo shows shares only; MLA-Reject 1.5 split kept; an unwritten free text left out whole;
  built-in preset titles as they are; French documents already generated stay stored.
- The earlier defaults of 01-specs section 20 that BRIEF-2 keeps (Q2, Q4 to Q8, Q10, Q2-1, Q3-2).
- Whether `GET /v1/languages` (English only) should stay.
- Optional: finding 1 (bound the helper threads) and note 2 (keep the older list on a failed refresh).
- Deploy and push: the user's decision. Nothing of the run is deployed or pushed; the 3 new packages have no remote.
