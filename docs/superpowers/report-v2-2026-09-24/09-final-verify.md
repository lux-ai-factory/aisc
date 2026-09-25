# Stage 9: Final verification of fix round 2 (report run v2)

Status: done. Inputs: RULES.md, 00-baseline.md, 07-reverify.md, 08-fix-round-2.md and the code. I changed no code and
no test. Every number below is my own measurement. Pre-fix runs and scratch probe tests ran in temporary git worktrees
of all seven repos under the session scratchpad (sibling layout, so the `../aisc-report-*` path sources resolved to
the worktrees; `AISC_INSTALL_DIR` pointed at aisc-install only to read `scripts/lib`). All worktrees were removed and
pruned afterwards.

## Verdict: PASS WITH NOTES

The five items of 08 do what 08 says. Each new test fails on the parent commit for the reason of the finding and
passes at HEAD. Suite counts match 08 exactly, and the remaining failures are the known 2 + 8 + 7. Both e2e pass. No
test was weakened, skipped or deleted since the 07 commit. The goldens are unchanged and pass, and the English
output is byte-identical before and after the colon change. The guard equals the baseline, nothing was pushed,
nothing is left over, and the live stack's start times did not change. No blocker. One should-fix (low, same
reachability as 07 note 6): a lone surrogate inside a block's instance id still crashes the service. Plus three notes.

## 1. Each item: commit, test, pre-fix run, break attempts

| item | commit read | test run on the parent commit | break attempts |
|---|---|---|---|
| 1 DOCX XML-safe text | generator dfb3a51 (`docx._xml_text`, applied to the whole HTML before parsing, runs, hyperlink text, TOC entries, nested-block holders, the chart notice, page-number pieces and core properties) | `test_docx.py -k fix_r2_1` with docx.py from 7e7024e: **23 failed, 5 passed** (`ValueError: All strings must be XML compatible` x21, `UnicodeEncodeError` for the two surrogates, ExpatError from cairosvg). At dfb3a51: 28 passed | Character references `&#0;` `&#00001;` `&#x0;` `&#55296;` `&#xDFFF;` `&#x1F;` `&#65534;` `&#x10FFFF;` `&#x7f;` `&#x85;` `&#1114112;` in the TOC, headings, paragraph, code, em, nested list, table header, definition term, alt text, figure caption, blockquote, pre, title and margins: every text path is safe. The one unsafe path is the hyperlink **target** (note 2): `&#1;`, `&#00001;`, `&#x1F;`, `&#65534;` in an `https://` or `mailto:` href make `html_to_docx` raise. Through the renderer it cannot be reached: 7 markdown forms (autolink, reference link, `<...>` destination, raw `<a href>`, mailto) come out as `&amp;#..` or are dropped by the sanitiser. Four markdown/plain free texts holding raw controls, ` `, `﻿`, char refs in code, fences, quotes, nested lists, table cells and image alt: every XML part of the package is clean |
| 2 lone surrogate = 422 | generator 69a9046 (`_surrogate_problems` walks every key and string; pointers print surrogates as backslash escapes) | `test_snapshot_v2.py -k fix_r2_2` with snapshot.py from dfb3a51: **9 failed** (5 x `assert []`, 4 x `UnicodeEncodeError`), the surrogate-pair guard passed. At 69a9046: 10 passed | 13 placements: enum value, type mismatch in a list, block type, top-level key, language, mode, coverage links, a list nested four deep, style font, document id, lone low surrogate, reversed pair, instance id. All give an `invalid_snapshot` problem and `InvalidSnapshot` in preview, pdf and docx. **Instance id fails at the service** (finding 1) |
| 3 French " : " | generator f211e16 (one message `{label}: {value}`, fr.json `{label} : {value}`, at key_figures.py:92, :118, :151, summary_coverage.html.j2, control_objectives.html.j2) | `test_v2_key_figures.py -k fix_r2_3` with report_renderer from 69a9046: French test **FAILS** (`'5: '` found; "par gravité : 5: 1", "attention: 0", "StrongREJECT: Nocivité"), English passes. With only key_figures.py and fr.json fixed it still FAILS on the templates (`'s: '` at 326). At f211e16: 2 passed | A wide French layout (cover, key figures with all figures, chapter, AI card with all shows, risk classification with chains and impact areas, summary, control objectives by objective with rationale, quotes, severity, status and by risk, full test results with measurements, artifacts and charts, two charts with tables, control answers with all shows, changes since with unchanged, appendix, free text), in preview, PDF and DOCX: **0** places matching `\S: ` (the parent commit had 16). `t()` fills placeholders in one pass and returns a plain `str`, so autoescape still applies to risk ids, texts and rationales, and braces in data are not re-filled |
| 4 outline limit | aisc-install f6ceb16 (`api.outline` refuses more than `layouts.MAX_BLOCKS`) | `test_v2_pages.py -k fix_r2_4` with api.py from f6ceb16^: **FAILS** (`200 == 422`). At HEAD: passes | 0, 1, 49, 50 blocks: 200. 51 and 100 000 blocks: 422 `too_many_blocks` (0.2 s for 100 000). 51 non-dict items: 422 `invalid_request`. 51 items without block_type: 422 `too_many_blocks`. Stranger with 51: 403 (access checked first). Same bound (`> 50`) as layout save (layouts.py:141) |
| 5 out-of-order guard | aisc-install 6515735 (`outlineAsked` counter, composer.js:201-208) | `test_v2_browser.py -k fix_r2_5` with composer.js from 6515735^: **FAILS** (`assert '0' == '1'`). At HEAD: passes | Every caller (add, move up/down, remove via `moved()` at composer.js:399-405, drop at :475) goes through `redrawOutline`, so all get the guard. Browser probe: first answer held, second aborted, first released, then one more move: final depth follows the last order. Note 3 |

## 2. Suites (re-run at HEAD after 08's last commit, `env | grep -iE 'DATABASE|DSN|DB_URL'` empty)

| suite | stage 9 | 08 claim | remaining failures |
|---|---|---|---|
| aisc-report-plugin-interface | 135 passed | 135 | none |
| aisc-report-langbite | 31 passed | 31 | none |
| aisc-report-strongreject | 24 passed | 24 | none |
| aisc-report-promptfoo | 22 passed | 22 | none |
| aisc-report-mlareject | 19 passed | 19 | none |
| aisc-report-generator | 589 passed, 2 failed (94.9 s) | 589 + 2 | test_block_ai_card.py::test_r2_2_2_tags; test_service.py::test_r5_4_1_no_token_no_answer[get-/v1/block-types] |
| apps/report-composer (incl. the 3 browser tests in test_v2_browser.py and the browser test_r_u1_1) | 331 passed, 8 failed (164.0 s) | 331 + 8 | test_api_access.py::test_r4_4_3_a_stranger_gets_404 x4; test_api_reports.py r4_2_5, r3_12, r4_3_5, r7_2_5 |
| scripts/tests test_report_stack + test_report_grants | 75 passed, 7 failed | 75 + 7 | stack: d6_guard_init_files, r4_1_2_launcher_card_seven, final_guard_frozen_passes; grants: d6a, r6_5, d13 x2 |
| generator e2e (test_e2e_v2.py, test_e2e.py) | 4 passed | 4 | none |
| composer e2e (test_e2e_v2.py, test_e2e.py) | 3 passed | 3 | none |

The failing ids are exactly the ones 05 and 07 traced to test-helper defects, other people's work and the baseline
guard FAIL. No test was skipped or xfailed (`-rs` reported none).

## 3. Test integrity (07 commit to HEAD)

- generator `git diff 7e7024e HEAD -- tests conftest.py pyproject.toml`: additions only (test_docx.py +108,
  test_snapshot_v2.py +71, test_v2_key_figures.py +32), no removed line.
- aisc-install `git diff 9e9be22 HEAD -- apps/report-composer/tests scripts`: additions only (test_v2_browser.py +31,
  test_v2_pages.py +15), no removed line.
- No `skip`, `xfail` or `importorskip` added in either repo. Interface, mlareject and the three packages have no
  commit since before stage 7.

## 4. Compatibility

- `git log 7e7024e..HEAD -- tests/golden tests/golden_cases.py report_renderer/css/report.css` is empty;
  `test_compat_golden.py` passed within the generator suite.
- The wide layout rendered in English with the renderer of 69a9046 and of f211e16: HTML **byte-identical**; the
  `x: ` texts of the English PDF and DOCX are identical too. The French HTML differs only in the colon texts.
- Behaviour changes of the round, all intended: DOCX core title and subject turn line breaks into a space; a
  forbidden character becomes a space in the Word file (the PDF path is unchanged).

## 5. Boundaries

- guard-frozen.sh: G1 FAIL (238 lines), G2 PASS, G3 PASS (hashes), G3 PASS (tests/test_vendored.py), the three G4
  FAIL lines (Sean's files; files outside the allowed set; Dockerfile), G5 PASS, GUARD FAIL. Same lines as
  00-baseline.md apart from the temp path. Its `aisc-t-guard-*` container was removed by its helper.
- Round commits touch only `report_renderer/**` and `tests/**` (generator) and `apps/report-composer/**` plus this
  folder (aisc-install). Other people's working-tree changes (apps/qualification pointer, homepage/project.html,
  form-assembly docs, `__pycache__` folders) are still modified or untracked and unstaged.
- Nothing pushed: `git ls-remote origin` gives generator e0a3ec4, interface e9420af, mlareject ac84039, aisc-install
  0b94640 (as in 05 and 07); `git branch -r --contains HEAD` is empty everywhere; ahead 41, 9, 3, 142 (07: 38, 9, 3,
  138; the difference is the 3 generator commits and 07's docs commit plus f6ceb16, 6515735, ab668a9). The three new
  packages have no remote.
- Leftovers: no `aisc-t-*` container, no `*:report-v2-test` image, no headless Chrome, `git worktree list` shows only
  the main checkout in all seven repos.
- Live stack: `docker inspect .State.StartedAt` of all 46 running containers identical at 03:08 and 03:20.

## 6. Regressions in the round's diff

I read the whole diff. None found. `_xml_text` only changes characters Word cannot store; the whole-HTML pass runs in
docx mode only. `_printable` leaves every pointer without surrogates unchanged. The colon message keeps the English
text identical (checked byte for byte). The outline limit is checked after the access check and before the
block-type check. The JS guard only drops answers that are older than the latest request.

## Findings

1. **should fix** (low; reachable only by a direct caller with the service token, as 07 note 6): a lone surrogate
   **inside a block's instance id** still makes the service fail. `report_renderer/snapshot.py:74-79`
   (`_instance_id`) copies the raw instance id into every problem of that block, so the problem list holds
   `'x\ud800y'`. `render()` raises `InvalidSnapshot` correctly, but encoding the 422 answer at
   `report_service.py:31-32` raises `UnicodeEncodeError: 'utf-8' codec can't encode character '\ud800'`, which is a
   500. Verified at HEAD by POSTing `/v1/render` with `"instance_id": "x\ud800y"`. 08 says the instance id "can be
   encoded"; its test only covers a block whose *other* field holds the surrogate. Scenario: a script calling the
   renderer with a malformed id gets a 500 with no problem list. Fix: pass the instance id through `_printable` (or
   set it to None when it holds a surrogate), with a test.
2. **note**: the DOCX hyperlink target is not made XML-safe. `report_renderer/docx.py:127`
   (`p.part.relate_to(url, ...)`): an href holding a character reference such as `&#1;`, `&#x1F;` or `&#65534;`
   makes `html_to_docx` raise `ValueError`. It cannot be reached today: markdown turns `&` in link destinations into
   `&amp;` and the sanitiser drops raw anchors with such hrefs (7 forms tried). A future block or tool template that
   emits an unescaped href as Markup could reach it. 08's "every hyperlink" covers the link text only.
3. **note**: 08 item 1 says the 5 tests that passed before the fix "are whitespace-like characters that the old
   folding already removed". They are the whole-renderer cases `ff`, `vt`, `us` and `nul` (NUL is not whitespace;
   an earlier layer removes it before the DOCX writer, I did not trace which) and `test_fix_r2_1_a_character_reference_in_markdown_free_text_renders_as_docx`,
   which also passed before the fix, so it is a guard rather than a regression test. The claim is inaccurate. The
   code is not affected. Also (composer.js:208): when the latest outline request fails, an older answer arriving
   later is still ignored, so the page keeps the indentation from before both moves until the next change.
   Cosmetic, and safer than showing the older answer.

## Questions for the user

None new from this stage.

## State of the run

### Commits of the run (all local, nothing pushed)

- **aisc-report-plugin-interface** (dev, from 631b62b): 7d93a31, f44fbd7, c77fc0b, 69549e8, 1193ab2, e9755a2, 7999876 (7).
- **aisc-report-generator** (dev, from 26e235d): 8611de9, 29c54cc, c2382fe, d71ead9, 539fef5, 03688d0, 8473143,
  ac65a02, ead5924, 6c8da28, 617acf3, 52702df, 50b38ae, 5bb6f13, 800276d, 4c6e453, 5f1fd3c, 38d818e, a92502f, 7585b3b,
  2047eea, 27e868f, 057e2df, 7bc92ca, 7e7024e, dfb3a51, 69a9046, f211e16 (28).
- **aisc-report-mlareject** (dev, from 2dd5649): 4942594 (1).
- **aisc-report-langbite** (dev, new local repo): f4af1d0, 4db2bf4, db7adbf, 4bbf943 (4).
- **aisc-report-strongreject** (dev, new local repo): 34cad23, 4af9b42, 8611f44 (3).
- **aisc-report-promptfoo** (dev, new local repo): d7b8a4f, 41c4ab8, 2dcd7c1 (3).
- **aisc-install** (feat/unified-modules, from 09a7cb2; the LLM keys commits 31de564, 6754e6f, b21e17f, 3f040ee,
  1ed8fed in the same range belong to another session): 9edb1e2 (stage 1), 1752778, 5f47cf2, b25b464 (stage 2),
  c0cabf8 (brief, rules, baseline), e5fefde (stage 3), bee8ff2, d24527d, 2689256, 1af887f, e664b2b, 57f2491,
  d884c52 (stage 4), 2815ddb (stage 5), 8cf13ef, f03e6d5, 576b157, 80508ba, 2ae7778 (fix round 1), 9e9be22
  (stage 7), f6ceb16, 6515735, ab668a9 (fix round 2), and this stage's docs commit (24).

### Open questions for the user (each has a default the code follows)

From 01-specs.md section 20:
- Q1 Language chosen per layout; the template is only a look.
- Q2 Saved presets visible to every signed-in user; free texts and commentaries removed unless "Keep texts" is
  ticked; deleted by their creator or an admin.
- Q3 LangBiTe's own tolerance check shown, labelled as the tool's result, with no verdict from the report (the
  alternative is to hide the column).
- Q4 The four built-in presets are shipped as listed in R-V1.1.
- Q5 TOC page numbers on for every layout (changes existing PDFs), with no option to turn them off.
- Q6 Evaluation names of the form "Evaluation {k}: {tools}".
- Q7 The Word TOC fills its page numbers when Word updates fields on opening (Word asks the reader).
- Q8 A small "Commentary" caption above each commentary.
- Q9 French texts written by the coding stage, not a native speaker; the user reviews `fr.json`.
- Q10 Marking levels Public, Internal, Confidential, Strictly confidential; document id and fingerprint off by default.

From 02-tests.md:
- Q2-1 A layout made from a preset file with no name in the request takes the file's name, with " (2)" when taken.

From 03-coding-plan.md and 04-code-report.md:
- Q3-1 Before the next deploy, the renderer service in the compose file needs the build contexts `langbite`,
  `strongreject`, `promptfoo`; not changed in this run.
- Q3-2 composer.js may grow up to 500 lines (now 486); all decisions stay in Python.
- Q4-1 French marking label for "Public" is "Diffusion libre".

From 06-fix-round-1.md and 08-fix-round-2.md (left for the user):
- Imported presets keep another platform's reference ids (evaluation pids, chart ids) in the saved preset and its
  export (05 note 7).
- A report generated straight from a built-in preset prints "Write this section." (05 note 8).
- Built-in presets have English chapter and cover titles, also in a French layout (05 note 9).
- English singular forms ("1 evaluations"): needs R-V8.3 changed to allow `|one` entries in en.json.
- Fix the test-helper defects `Throwaway.rows()` and `TestClient.get(json=None)` that hide 13 tests per run (05 note 10).
- The preset free-text rule for future plugin blocks (prose options without maxLength, nullable or nested) (07 note 5).
- The composer suite needs `/usr/bin/google-chrome` for 3 browser tests (07 note 7).
