# Stage 7: Re-verification of fix round 1 (report run v2)

Status: done. Inputs: RULES.md, 00-baseline.md, 05-verify.md, 06-fix-round-1.md and the code. I changed no code and
no test. Every number below is my own measurement. Pre-fix checks ran in temporary git worktrees under the session
scratchpad (sibling layout, so the `../aisc-report-*` path sources resolved to the worktrees). Scratch probe tests
lived only in those worktrees, and all worktrees were removed and pruned afterwards.

## Verdict: PASS WITH NOTES

The round's four fixes and five notes do what 06-fix-round-1.md says. Each new test fails on the parent commit for
the reason of the finding, and passes at HEAD. The suite counts match 06 exactly, and the remaining failures are the
known 2 + 8 + 7. Both e2e tests pass. No test was weakened, skipped or deleted. The goldens are unchanged and pass
(12 with the new PDF comparison). Guard output equals the baseline, nothing was pushed, nothing is left over, and the
live stack's start times did not change. No blocker. One should-fix (low) that the round did not introduce: the Word
file still fails on rare control characters in body text, the same class as finding 3. Plus six notes.

## 1. Each claimed fix: commit, test, pre-fix run, break attempts

| item | commit(s) read | test run on the parent commit | result at parent | break attempts |
|---|---|---|---|---|
| F1 TOC double numbers | generator 2047eea (`css/numbering.css`, added only when numbering is on and a TOC exists) | `test_document_structure.py -k fix1` on 7585b3b | `test_fix1_pdf_toc_shows_each_number_once` FAILS: `markers ['1.', '2.', '1.', '3.', '4.']`. The no-numbering test and the DOCX test pass, as 06 says ("DOCX already had one number") | I rendered the French Mike v2 e2e PDF at HEAD and viewed page 1: "1 Chiffres clés", "2.1 ...", "Annexe" and "A Réponses aux contrôles", each number once and no markers. Without numbering the markers stay (golden-safe) |
| F2 French tool tiles | interface e9755a2 (`headline(run, ctx=None)`, `headline_items`), langbite db7adbf, strongreject 8611f44, promptfoo 2dcd7c1, generator 057e2df | interface `-k fix2` on 1193ab2: 4 FAIL (`headline() got an unexpected keyword argument 'ctx'`). Each package `-k fix2` on its parent with the fixed interface: FAIL, same TypeError | fails for the finding | French PDF page 2 at HEAD: "0,2", "0,8", "68,8 %", "1 sur 4", "85 %", "40"; labels and notes French from the package catalogues (all 11 label/note msgids checked present). `headline()` is called in only one place (key_figures). Chart values were already localised through `svg(decimal_separator, percent_format)`. Residue: see note 2 (punctuation built outside `t()`) |
| F3 CSS injection | generator 27e868f (`_css_escape_char`: every non-printable character and `<` hex-escaped; DOCX margins through `_xml_safe`) | `test_header_footer.py -k fix3` on 2047eea: 5 of 9 token cases FAIL (form feed, controls, newlines, separators, unicode NBSP/ZWSP), the PDF case FAILS (body paragraph hidden), the DOCX case FAILS (`ValueError: All strings must be XML compatible`) | fails for the finding | Fuzz: 20 000 random strings mixing all code points with `\f \\ " ' \r\n < } { ; \x00 \x1b \x7f \x85 U+2028 U+2029 U+FEFF U+00AD U+200B </style> <!--`, each parsed with tinycss2 as `p{content:<escaped>}`: 0 failures (always one rule, one declaration, one string token equal to the input with CR/LF as a space). No output ever contains `<`. Placeholders are filled before escaping. The other CSS inputs (colours, font stack, size) are schema-checked and re-checked with `fullmatch`. Two gaps outside the margin path: findings 1 and 6 |
| F4 chapter intro in presets | aisc-install 8cf13ef (`_free_text_options`: commentary, `free_text.text`, `chapter.intro` and every string option with maxLength > 300) | `test_v2_presets.py -k fix4` on 2815ddb: all 3 FAIL (`'Findings for Bank X show a gap.' == ''`, `'Client X' == ''`) | fails for the finding | I listed every free string option of all 14 built-in block types from the registry: only title (200), cover report_title (200) and subtitle (300), and the three prose fields exist; the prose fields are all dropped, titles stay (by design, R-V1.9). A saved preset takes its name and description from the request body, not the layout. Gap for future plugin blocks: note 5 |
| N5 preview stall | aisc-install f03e6d5 (`call()` catches the failed fetch as status 0; `inFlight` reset in `finally`) | `test_v2_browser.py` at f03e6d5 with composer.js from its parent: FAILS (`JavaScript errors: ['Failed to fetch']`, label never shows "could not be reached") | fails for the finding | Read the diff: the error label path and the "older answer ignored" guard are unchanged. The composer image installs no dev extras (`uv export --no-dev`), so playwright does not reach the image |
| N6 stale outline | aisc-install 576b157 (depth rule moved to `layouts.outline_depths`, new editor route `POST .../outline`, JS redraws after add, move, remove, drag) | `test_v2_browser.py` + `test_v2_pages.py -k fix_` at 576b157 with api.py, layouts.py, pages.py, composer.js and editor.html.j2 from its parent: browser test FAILS (timeout waiting for the new depth), route tests FAIL (404) | fails for the finding | Bad bodies (`blocks: "x"`, non-dict items, missing block_type) give 422. Notes 3 and 4 (no block limit, answer order) |
| N11 weak test | aisc-install 80508ba (word check replaced by a browser test: PUT carries exactly the ticks, page count unchanged until Python redraws) | not a bug fix, so no pre-fix failure is expected; it passes at HEAD | n/a | It asserts strictly more than the old test did. It now needs Chrome (note 7) |
| N12 unused golden | generator 7e7024e (PDF text flow of `a_v2_live_styled` compared outside Test results) | compat test, passes at parent and HEAD by design | n/a | Mutation: changing `"Topic: {topic}"` in control_answers.html.j2 makes it FAIL, so it is not vacuous. It asserts that the golden contains "Control objectives" and "Mean score 2.5, answered 2 of 4", so a missing section cannot pass silently |
| N13 French singular | interface 7999876 (`<msgid>\|one`, first whole-number parameter, `_meta.plural_one`), generator 7bc92ca (12 forms, `plural_one [0, 1]`), langbite 4bbf943 | interface `-k fix_plural` on e9755a2: 8 of 10 FAIL. Generator `test_i18n.py -k fix_` on 057e2df with the fixed interface: 12 FAIL (the "every singular belongs to a used message" guard passes, as a guard should). Langbite on db7adbf: FAIL | fails for the finding | Every call site of the 12 messages passes an `int` (`len(...)`, counts), including `{tools}, +{count} more` where the first placeholder is a string and is correctly skipped. I found no remaining French count message with a plural noun and no `\|one`. French PDF: "1 objectif sur 4 avec éléments probants". English "1 evaluations" remains (06 deviation, needs R-V8.3 changed) |

## 2. Suites (re-run after the last commit, `env | grep -iE 'DATABASE|DSN|DB_URL'` empty)

| suite | stage 7 | 06 claim | remaining failures |
|---|---|---|---|
| aisc-report-plugin-interface | 135 passed | 135 | none |
| aisc-report-langbite | 31 passed | 31 | none |
| aisc-report-strongreject | 24 passed | 24 | none |
| aisc-report-promptfoo | 22 passed | 22 | none |
| aisc-report-mlareject | 19 passed | 19 | none |
| aisc-report-generator | 549 passed, 2 failed (92.9 s) | 549 + 2 | test_block_ai_card.py::test_r2_2_2_tags; test_service.py::test_r5_4_1_no_token_no_answer[get-/v1/block-types] |
| apps/report-composer (incl. the 2 playwright browser tests and the browser-based test_r_u1_1) | 329 passed, 8 failed (161.9 s) | 329 + 8 | test_api_access.py::test_r4_4_3_a_stranger_gets_404 x4 (`get(json=...)`); test_api_reports.py r4_2_5, r3_12, r4_3_5, r7_2_5 (`Throwaway.rows()`) |
| scripts/tests test_report_stack + test_report_grants | 75 passed, 7 failed | 75 + 7 | stack: d6_guard_init_files, r4_1_2_launcher_card_seven, final_guard_frozen_passes; grants: d6a, r6_5, d13 x2 |
| generator e2e (test_e2e_v2.py, test_e2e.py) | 4 passed | 4 | none |
| composer e2e (test_e2e_v2.py, test_e2e.py) | 3 passed | 3 | none |

The failing test ids are exactly the ones 05-verify.md section A traced to helper defects, other people's work and
the baseline guard FAIL. No test was skipped or xfailed in any run.

## 3. Test integrity (pre-round commit to HEAD)

`git diff <pre-round> HEAD` on tests, conftest, pyproject and pytest config in every repo (generator 7585b3b,
interface 1193ab2, langbite 4db2bf4, strongreject 4af9b42, promptfoo 41c4ab8, mlareject 4942594, aisc-install
2815ddb incl. scripts/tests, scripts/lib, scripts/pipeline_chain): additions only (generator +268, interface +99,
packages +28/+10/+10, composer +205). The only removed lines are the old body of
`test_v2_pages.py::test_r_u1_1_python_computes_the_grid_and_js_only_collects`, replaced by the stricter browser
version (justified: 05 note 11). No `skip`, `xfail` or `importorskip` was added. No conftest or golden change. The
composer's pyproject gains `playwright>=1.40` in dev extras only (uv.lock updated).

## 4. Compatibility

`git log 8611de9..HEAD -- tests/golden tests/golden_cases.py` is empty; `report.css` unchanged since 7585b3b; the
round's renderer changes are key_figures.py (3 lines), document.py, docx.py, fr.json and the new feature CSS
numbering.css, which is emitted only when numbering is on. `tests/test_compat_golden.py`: 12 passed (the 11 golden
tests plus the new PDF comparison). One accepted behaviour change for existing templates: CRLF inside a header or
footer text now gives one space instead of two (06 deviation).

## 5. Boundaries

- guard-frozen.sh: G1 FAIL (238 lines), G2 PASS, G3 PASS (hashes), G3 PASS (tests/test_vendored.py), the three G4
  FAIL lines (Sean's files; files outside the allowed set; Dockerfile), G5 PASS, GUARD FAIL. Same lines as
  00-baseline.md apart from the temp path.
- aisc-install commits of the round (8cf13ef, f03e6d5, 576b157, 80508ba, 2ae7778) touch only
  `apps/report-composer/**` and this folder. Report repos: only renderer, interface and package files. No engine,
  AIRO, catalogue or other-module file. Other people's uncommitted files (apps/qualification pointer,
  homepage/project.html, form-assembly docs, caches) are still modified or untracked and unstaged.
- Nothing pushed: `git ls-remote origin` gives generator e0a3ec4, interface e9420af, mlareject ac84039,
  aisc-install 0b94640 (as in 05); `git branch -r --contains HEAD` is empty; local branches are ahead 38, 9, 3, 138
  (05: 33, 7, 3, 132; the difference is the round's 5 + 2 commits and the stage-5, round and docs commits in
  aisc-install). The three new packages have no remote.
- Leftovers: no `aisc-t-*` container (the ones my runs and the guard created were removed by their helpers), no
  `*:report-v2-test` image, `git worktree list` shows only the main checkout in all seven repos.
- Live stack: `docker inspect .State.StartedAt` of all 46 running containers is identical before (02:26) and after
  (02:38) this stage.

## 6. Regressions introduced by the round

I read the full diff of the round in each repo. No regression of existing behaviour found: numbering.css only
appears with numbering on; `headline_items` keeps renderers whose `headline(self, run)` takes no context (tested);
`_css_string` output is identical for printable text; the `|one` lookup only changes messages that have a `|one`
entry; the presets rule only blanks prose fields; the composer.js changes keep the single-flight and
ignore-older-answer logic. The new code has the minor issues listed as notes 3 to 5.

## Findings

1. **should fix** (low, not introduced by the round): a Word file cannot be made when body text holds a C0 control
   character other than tab, LF, CR, VT and FF. `aisc-report-generator/report_renderer/docx.py:100-107`
   (`_Writer.run`) only folds whitespace (`_collapse`), and `_xml_safe` (docx.py:59) is applied only to the margins
   (docx.py:490). Verified at HEAD: free text `"a\x01b"`, cover subtitle `"s\x01"` or commentary `"c\x1b"` in
   mode docx raises `ValueError: All strings must be XML compatible` in python-docx, so the service answers 500 and
   the composer marks the report failed with "The report renderer failed." The PDF of the same layout renders.
   Scenario: an editor pastes text containing an escape or SOH character from a terminal or a legacy export into a
   free text; PDF works, Word fails with no hint why. Fix: pass every text written by the DOCX writer (runs,
   `tel.text`, `holder.text`, lines 138, 346, 358, 436, 456) through `_xml_safe`, with a test per field.
2. **note**: French texts still assembled outside `t()` with English punctuation.
   `report_renderer/blocks/key_figures.py:92` (`f"{level}: {n}"`), `:118` (`f"{ctx.t(st)}: {counts[st]}"`), `:151`
   (`f"{name}: {label}"`). French PDF page 2 shows "par gravité : 5: 1, 4: 1", "attention: 0, aucun élément probant:
   0", "StrongREJECT: Nocivité" (French typography wants " : "). Present since stage 4; same class as finding 2 of
   05, which the static msgid scan cannot see.
3. **note**: the new outline route has no block limit and is quadratic. `apps/report-composer/report_composer/api.py:296`
   does not apply the layouts' `MAX_BLOCKS = 50`, and `layouts.outline_depths` slices the rest of the list for every
   chapter. Measured: 20 000 chapter blocks 0.5 s, 40 000 blocks 2.4 s of one worker. Only a project editor can call
   it. Fix: refuse more than MAX_BLOCKS blocks with 422.
4. **note**: `redrawOutline` (`composer.js:201`) has no ordering guard. Two quick moves whose answers arrive out of
   order leave the older indentation and empty-chapter hint on screen until the next change. Cosmetic.
5. **note**: the preset free-text rule (`presets.py:175-178`) sees only options typed exactly `"string"` with a
   maxLength above 300. A future plugin block's prose option without maxLength, typed `["string", "null"]`, or
   nested in an object or array would still be saved into a preset. No such block exists today.
6. **note**: a lone surrogate (`"\ud800"`) anywhere in a snapshot makes both the PDF and the DOCX render fail with
   `UnicodeEncodeError` at `report_renderer/snapshot.py:138` (fingerprint), so the header escape `\d800 ` never
   gets used. Reachable only by a direct caller with the service token; the composer's jsonb storage refuses lone
   surrogates. Pre-existing.
7. **note**: the composer suite now needs `/usr/bin/google-chrome` for 3 tests (the 2 in test_v2_browser.py and
   test_r_u1_1 in test_v2_pages.py, which imports the `live` fixture). Without Chrome they fail rather than skip;
   that is honest, but a CI runner needs Chrome installed.

## Questions for the user

None new. The open questions of earlier stages and the items 06 left for the user (notes 7 to 10 of 05, English
singular forms) still stand.
