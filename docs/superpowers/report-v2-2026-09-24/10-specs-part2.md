# Part 2, stage 1: Specs for the user's decisions D1 to D3 (report run v2)

Status: stage 1 of part 2. Binding inputs: `RULES.md` (still applies), `BRIEF-2.md` (scope), and for context
`01-specs.md`, `04-code-report.md`, `05-verify.md`, `06-fix-round-1.md`, `07-reverify.md`, `08-fix-round-2.md`,
`09-final-verify.md`. Everything in `01-specs.md` and in the fix rounds still holds unless a requirement below
replaces or removes it. Where a requirement lands uses the tags of `01-specs.md`: [RG] renderer, [IF] interface,
[RC] composer, [LB] [SR] [PF] the three tool packages, plus [ML] `aisc-report-mlareject` and [SC]
`aisc-install/scripts` (test helpers only).

Every requirement has an id `R2-D<n>.<m>` and is phrased so that a test can check it. Each says which earlier ids
it replaces (`replaces`), removes (`removes`) or leaves untouched, and which existing tests must be removed or
changed because the user's decision changes scope (sections 5 and 6 collect them per repo).

## 0. Facts this file relies on (read in the code on 2026-09-25, nothing changed)

- Repo heads: generator dev f211e16, interface dev 7999876, langbite dev 4bbf943, strongreject dev 8611f44,
  promptfoo dev 2dcd7c1, mlareject dev 4942594, aisc-install feat/unified-modules f7fd0f0. Other people's
  uncommitted files in aisc-install: `apps/qualification` (pointer), `homepage/project.html`,
  `docs/superpowers/form-assembly-2026-09-24/`, `__pycache__` folders.
- French lives in: `report_renderer/i18n/fr.json` (235 messages, 12 `|one` forms, `plural_one [0, 1]`), the
  packages' `vera_report_plugin_{langbite,strongreject,promptfoo}/i18n/fr.json`, the renderer's
  `languages.language_files()` (built-in folder plus `REPORT_I18N_PATH`), `document.render` (422 when the
  language is not offered, `document.py:203-206`), `context.context_for` (`translate_for` loads a package file
  only when the language is not `en`, `context.py:187-188`), the composer's Language select
  (`templates/editor.html.j2:25`, `static/composer.js:287`), `settings.document_settings` (`unknown_language`),
  `api.py:117-126` (preset language notice), `presets.py` (`language` in presets and files), `reports.py:69`
  (snapshot `language`), `db.py` (`layout.language`, `preset.language` columns written and read),
  `renderer_client.languages()` and `renderer_calls.languages()`.
- `en.json` is `{"_meta": {code en, name English, ".", "{value}%"}, "messages": {}}`; the stage-2 test
  `test_i18n.py::test_r_v8_2_en_and_fr_catalogues_have_the_format` pins its messages to `{}`.
- Live stack: migration 0005 never ran on the live DB (05-verify F), so no live layout or preset carries a
  language. Layouts, presets and stored snapshots with `"fr"` exist only in local or test databases and in
  preset files people may have exported.
- Verdicts: `BaseToolRenderer.verdict()` returns None in all four tool renderers and the legacy adapter. Its only
  reader is `report_renderer/coverage.py:62`: a `"fail"` verdict turns a linked objective into
  `evidence, attention`.
- The 13 hidden tests and the 3 failures caused by other people's work were re-run by this stage for the scripts
  suites (`test_report_stack.py` + `test_report_grants.py`: 75 passed, 7 failed, the same 7 ids as 09-final-verify);
  the generator and composer numbers are taken from 09-final-verify (589 + 2, 331 + 8) and are re-measured in
  stage 2.

## 1. D1: all reports in English

### 1.1 Renderer [RG]

R2-D1.1 The renderer ships exactly one language file, `report_renderer/i18n/en.json`. `fr.json` is deleted.
`languages.language_files()` reads only the built-in folder; `REPORT_I18N_PATH` is no longer read (a `de.json` or
`fr.json` in a folder named by it does not add a language). Replaces R-V8.2 (built-in folder only), removes
R-V8.4 and R-V8.6. DEFAULT (user to confirm), question Q2-1.

R2-D1.2 `GET /v1/languages` stays and returns exactly `[{"code": "en", "name": "English"}]`; `GET /health` field
`languages` holds only English. Replaces R-V8.5 (first sentence) and the `languages` part of R-S.7.

R2-D1.3 Snapshot key `language` stays optional in `snapshot.SCHEMA` with its pattern `^[a-z]{2}(-[A-Z]{2})?$`.
Any value that matches the pattern (`"en"`, `"fr"`, `"de"`, `"xx"`, `"fr-BE"`) is accepted and the document is
rendered in English: every text is the English message id, the decimal separator is `.`, percentages are
`{value}%`, `<html lang="en">`, the DOCX core property language is `en`. A value that does not match the pattern
(for example `"French"`) is still 422 `invalid_snapshot` at `/language`. Replaces R-V8.5 (second sentence),
R-V8.7 and R-V8.11 (language property). Test: the same blocks rendered with `language` absent, `"en"` and `"fr"`
give byte-identical HTML and identical DOCX text.

R2-D1.4 The fingerprint (R-V5.15) is unchanged in definition: it is computed over the snapshot as received, so a
stored snapshot with `"language": "fr"` keeps the fingerprint it had. (Re-rendering it gives an English document
with that same fingerprint; see question Q2-8 for documents already generated in French.)

R2-D1.5 `BlockContext.language` is always `"en"` and `BlockContext.t` is the English translator built from
`en.json` (which may hold only singular forms, R2-D3.4.1). `ctx.translate_for(package)` returns a translator over
the package's own `i18n/en.json` when the package ships one, then the renderer's `en.json`, else the identity.
Replaces R-V8.8 for the renderer side (the interface helpers stay, R2-D1.10).

R2-D1.6 The `t()` plumbing stays (message ids are the English texts). The one message `"{label}: {value}"`
added in fix round 2 stays; its English output is unchanged. `risk_classification.py:125` keeps printing the
stated class as written. No English output changes because of D1 (the goldens are the proof, R2-C.2).

### 1.2 Tool packages [LB] [SR] [PF]

R2-D1.7 Each package deletes `i18n/fr.json`. A package ships `i18n/en.json` only when it needs English singular
forms (LangBiTe does, R2-D3.4.3; StrongREJECT and promptfoo do not unless stage 3 finds a counted noun). The
`package-data` glob `i18n/*.json` stays. Replaces R-V2.24 ("i18n catalogues under i18n/*.json") and R-V8.8 for
the packages.

R2-D1.8 `headline(run, ctx=None)` keeps its signature (fix round 1, finding 2). With the English context its
values are identical to the values without a context. No behaviour depends on a language other than English.

### 1.3 Composer [RC]

R2-D1.9 The editor has no Language control: `editor.html.j2` renders no `select[data-control="language"]`, and
`composer.js` neither reads nor sends `language`. The composer no longer calls `GET /v1/languages`
(`renderer_calls.languages`, `renderer_client.languages` and the fakes' `LANGUAGES` go). Removes R-V8.13 and the
Language part of R-V8.1, R-U3.1 (`language` in the draft body) and R-D.4 (`unknown_language`).

R2-D1.10 Layout API: a `language` key in `POST /api/p/{ref}/layouts`, `PUT .../layouts/{id}` and
`POST .../layouts/{id}/preview` is accepted and ignored (never 422, never stored, so an older client keeps
working). Layout views (single layout, list, duplicate answer) carry no `language` key. Replaces R-D.3 (the
`language` part), removes R-D.4 `unknown_language`.

R2-D1.11 Storage: the column `report_composer.layout.language` stays (no migration drops it, question Q2-2); the
composer never writes it on insert or update (the column default `'en'` applies to new rows) and never reads it.
An existing row holding `'fr'` keeps that value untouched and has no effect. Same for
`report_composer.preset.language`: new saved presets store NULL, stored values are ignored. `db.DEFAULT_SETTINGS`
loses `language`. Replaces R-V8.1, R-D.1 (layout.language is kept but unused).

R2-D1.12 Snapshots sent by the composer (preview, draft preview, generate) carry no `language` key, whatever the
layout row holds. Replaces the `language` line of 16.1 for the composer and R-S.3's "now including the new keys"
for this key. A layout whose row holds `'fr'` previews and generates in English.

R2-D1.13 Presets: the four built-in preset files drop `"language": "en"`. `GET .../layouts/{id}/export` and
`GET /api/presets/{id}/export` write no `language` key (the file keys become `format, version, name,
description, toc, numbering, blocks`; format version stays 1, since `language` was always optional on import).
Importing a file or saving a preset with any `language` value (`"fr"`, `"de"`, `"xx"`) is accepted; the value is
ignored and no notice is given. Creating a layout from a preset never sets a language and gives no language
notice. Duplicating copies no language. Replaces R-V1.1 (`language=en`), R-V1.3 ("document settings are the
preset's": now `toc` and `numbering` only), R-V1.6 (language), R-V1.7 (file keys), 2.1 vocabulary, and removes
the language edge case of 2.5.

R2-D1.14 The composer's own screens stay English (R-V8.16 unchanged).

### 1.4 Interface [IF]

R2-D1.15 `vera_report_plugin_interface.i18n` (loader, translator,
`|one` forms, `format_number`, `format_percent`, `translator_for`) stays as it is, with its tests. It is a
generic mechanism; D1 allows it to stay, and the renderer now feeds it English only. No interface change is
needed for D1. (See deviation DV2-4.)

### 1.5 Backward compatibility for D1

R2-C.1 A layout row with `language = 'fr'`, a saved preset row with `language = 'fr'`, a preset file with
`"language": "fr"` or `"de"`, and a snapshot with `"language": "fr"` each load without error (200 or 201) and
render in English (R2-D1.3, R2-D1.11 to R2-D1.13). Tests: a composer test writes `'fr'` into a layout row of the
throwaway bed and checks preview and generate succeed with no `language` in the sent snapshot; a renderer test
posts a v2 snapshot with `"language": "fr"` and checks `lang="en"`, "Contents", "Page ... of ...".

R2-C.2 The goldens stay byte-identical for English output: `test_compat_golden.py` passes unchanged (Delta v1
cases byte for byte; the Alpha and Mike cases unchanged outside the Test results section). The only intended
changes inside the Test results section are R2-D2 labels and the English singular form of R2-D3.4 (R2-C.3).

R2-C.3 R-C.4 gains two allowed differences, both inside the Test results section, which the golden tests already
allow: item 5, the LangBiTe and promptfoo Pass / Fail labels (R2-D2.2, R2-D2.5); item 6, the notice
"1 observations could not be tied to a tool." becomes "1 observation could not be tied to a tool." (it appears in
the a_v2_live, a_v2_live_styled and a_v2_legacy_links goldens, inside block `...a005`, the Test results block).

R2-C.4 Documents already generated keep their stored bytes (R-C.3 unchanged): a French PDF or DOCX generated
before part 2 is downloaded as it was. DEFAULT (user to confirm), question Q2-8.

## 2. D2: Pass / Fail when the tool itself reports it

### 2.1 What each tool's own output says (plugin sources and fixtures)

| tool | own pass/fail in its measurements? | where it comes from |
|---|---|---|
| LangBiTe (`aisc-plugin-langbite` 0.1.1, `~/aisc-virgin/plugins/aisc-plugin-langbite/aisc_plugin_langbite/plugin.py`) | **Yes, per group and per run.** Per group: the description starts `Tolerance Evaluation: {Passed \| Failed \| Not evaluated}` (plugin.py:165, value from LangBiTe's `GlobalEvaluator.__evaluate`, `langbite/controllers/global_evaluation.py:125-128`: `Not evaluated` when passed + failed prompts = 0, `Passed` when the passed share is at least the concern's tolerance, else `Failed`; `Unknown` when the row has no value). Per run: `All Tolerances Passed` = 1.0 when there is at least one group and every group is `Passed`, else 0.0, description `"{a}/{b} tolerance checks passed"` (plugin.py:184-194). The per-group `Passed: p/n`, `Failed: f/n` are prompt counts the tool judged passed or failed. | measurements |
| promptfoo (`aisc-plugin-promptfoo` 0.1.0, `.../aisc_plugin_promptfoo/plugin.py`) | **Yes, as shares.** `pass_rate` = share of tests whose `success` is true, i.e. that passed all of their assertions (description "Share of tests that passed all of their assertions.", unit "rate (higher is better)", plugin.py:1076-1082); `fail_rate` = 1 - pass_rate ("Share of tests that failed at least one assertion.", plugin.py:1084-1090). Both absent when no test has a success value. The per-test pass/fail and the per-category tested/failed counts exist only in the plugin's output dict and in the artifacts `promptfoo_per_test.csv` / `promptfoo_results.json` (plugin.py:626-702, 729-815); they are not measurements. | measurements (shares); per test only in artifacts |
| StrongREJECT (`aisc-plugin-strongreject` 0.1.0, `.../aisc_plugin_strongreject/plugin.py:359-404`) | **No.** Every measurement is a harmfulness score 0..1 (or 1 - harmfulness) with a "lower/higher is safer" description. The `jailbroken_binary` evaluator's 0/1 per-prompt judgement is averaged into the harmfulness score; per prompt it exists only in `strongreject_per_prompt.csv`. | none |
| MLA-Reject (`aisc-report-mlareject`, measurements `score` with dimensions) | **No.** The tool writes scores per case. The renderer's split into "harmful" and "empty" cases at 1.5 (`statistics.py:10`, `THD`, "the threshold of the legacy loader") is a fixed cut made by the report module of 2026-09-23, not the tool's output and not set by a user. | none (report-side cut, question Q2-5) |

Fixtures that carry the tool's own results (used by stage 2): `aisc-install/scripts/tests/fixtures/report/seed_tools.sql`
rows 7003, 7004 (`Failed`), 7006 (`All Tolerances Passed` 0.0, "0/2 tolerance checks passed"), 7201 (`Passed`),
7202, 7203 (`Failed`), 7204 (`Not evaluated`), 7206 (0.0, "1/4 tolerance checks passed"), 7400 (`pass_rate` 0.85),
7401 (`fail_rate` 0.15); package fixtures `aisc-report-langbite/tests/fixtures.py` (GROUPS: Passed, Not evaluated,
Failed, Failed; SUMMARY: All Tolerances Passed 0.0 "1/4") and `aisc-report-promptfoo/tests/fixtures.py` (FULL:
0.85 / 0.15; LATENCY_COST_TESTS: no rates). Note for stage 2: row 7204 and the package fixture's religion group
say `Not evaluated` with 1 passed and 1 failed prompt, which the real LangBiTe never writes (it says
`Not evaluated` only when both are 0); a realistic `Not evaluated` row has `Passed: 0/n | Failed: 0/n`.

### 2.2 Requirements

R2-D2.1 [LB][SR][PF][ML] The report shows a Pass / Fail value only where the tool's own measurement states it
(table 2.1). The report never compares a number with a threshold of its own or of a user to make a Pass / Fail,
and no threshold option is added (thresholds stay out of scope). Replaces R-V2.12 and the first bullet of
01-specs section 18 ("Pass/fail thresholds, verdicts ... on test measurements") by: "No threshold, verdict of
the report, colour band or better/worse wording; a tool's own Pass / Fail is shown as the tool states it."

R2-D2.2 [LB] Group table (R-V2.11 b): the last column is headed "Pass / Fail (LangBiTe tolerance check)". Its
cell is "Pass" when the description says `Passed`, "Fail" when it says `Failed`, "Not evaluated" when it says
`Not evaluated`, and any other parsed text as written (for example `Unknown`); "n/a" when the description does
not parse (R-V2.13 unchanged). The column "Tolerance set in LangBiTe" stays next to it, so the reader sees the
tool's own bar. The Passed and Failed prompt-count columns stay as they are ("9 of 10"). Replaces R-V2.11 (b)
last column.

R2-D2.3 [LB] Run result (R-V2.11 a gains a line): under the summary line, "All tolerance checks: Pass ({a} of {b}
passed)" when `All Tolerances Passed` has score 1 and its description parses with b > 0; "All tolerance checks:
Fail ({a} of {b} passed)" when the score is 0 and b > 0; "All tolerance checks: not evaluated ({description})"
when b = 0 or the description does not parse (the plugin writes 0.0 with "0/0" when the run produced no group;
see deviation DV2-2). No line when the measurement is absent. The line is also shown with `detail = "summary"`
(R-V2.15 gains it).

R2-D2.4 [LB] `headline(run, ctx)` keeps "Overall pass rate", "Tolerance checks passed" ("{a} of {b}") and
"Groups" (R-V2.14 unchanged; at most 4 items, so key figures still take the first 2).

R2-D2.5 [PF] Table (R-V2.21): the rows `pass_rate` and `fail_rate` are labelled "Pass" and "Fail" (followed by
the unit's direction words as today: "Pass (higher is better)", "Fail (lower is better)"), values unchanged
(shares as %, "not reported" when absent). Under the table, when either is present, the note: "Pass and Fail are
promptfoo's own results: a test passes when all of its assertions pass. The values are shares of the tests." The
chart (`rates`) series labels become "Pass", "Fail", "Refusal rate"; its title stays. `headline()` label
"Pass rate" becomes "Pass" (key figures tile "Promptfoo: Pass"). No counts are derived from the shares
(question Q2-4). Replaces R-V2.21 labels and R-V2.23 label.

R2-D2.6 [SR] StrongREJECT writes no pass or fail, so its section shows none: no text "Pass" or "Fail" as a
result word appears in its section, and R-V2.17 to R-V2.19 stay as they are ("not scored" is not a verdict).
A test pins that no Pass / Fail word appears in a scored and a failed run.

R2-D2.7 [ML] MLA-Reject writes no pass or fail; its section is unchanged (R-C.5, contract 1). The harmful /
empty split at 1.5 stays as it is (question Q2-5).

R2-D2.8 [LB][SR][PF] `verdict()` still returns None in all three packages, so the coverage rule
(`coverage.py:62`) is unchanged and no objective becomes `evidence, attention` because of a tool's Fail. The
Pass / Fail is shown only in the tool section. DEFAULT (user to confirm), question Q2-3. R-V2.7's "(no
pass/fail, BRIEF)" reads "(the tool's own Pass / Fail is shown in its section, not used as a verdict)".

R2-D2.9 Artifacts are still never read (R-V2.9 unchanged). So per-test Pass / Fail of promptfoo and per-prompt
results of LangBiTe and StrongREJECT, which live only in artifacts holding prompts and responses, are not shown
(deviation DV2-3).

R2-D2.10 [LB][PF] Wording rule: the words "Pass" and "Fail" appear only as a value the tool stated or as the
header naming it; the words "verdict", "compliant", "safe", "unsafe", "better", "worse" are not added by these
renderers (the unit's own "(higher is better)" stays, as today).

## 3. D3: fix every remaining bug

### D3.1 Lone surrogate in a block's instance id [RG]

R2-D3.1.1 When a snapshot block's `instance_id` holds a lone surrogate, then `POST /v1/render` answers 422
`invalid_snapshot` (never 500), the body is valid UTF-8 JSON, every problem of that block carries the instance id
with each lone surrogate written as a backslash escape (as `_printable` does for pointers, for example
`"x\\ud800y"`), and one problem has pointer `/blocks/{i}/instance_id` and message "holds a lone surrogate".
Applies to preview, pdf and docx. Source: 09-final-verify finding 1, `snapshot.py:74-79`.

R2-D3.1.2 A problem list can always be encoded as UTF-8: a test serialises every problem produced for 13
placements of `"\ud800"` (those of 09 section 1, item 2) with `json.dumps(..., ensure_ascii=False).encode()`.

### D3.2 Character reference inside a link address in the DOCX export [RG]

R2-D3.2.1 When `html_to_docx` meets an `<a href>` whose address (after lxml resolves character references)
holds a character XML 1.0 forbids (C0 controls except tab, LF, CR; lone surrogates; U+FFFE, U+FFFF), or that
python-docx refuses to store, then the link text is written as a normal run (not a hyperlink, not dropped) and
the export succeeds. Addresses without such characters keep their hyperlink. Source: 09 note 2, `docx.py:127`.
Test: the hrefs `https://e.org/&#1;`, `&#00001;`, `&#x1F;`, `&#65534;`, `&#55296;` (in `https:` and `mailto:`),
each gives a DOCX whose text holds the link text and whose relationships part is valid XML.

### D3.3 Outline request that fails [RC]

R2-D3.3.1 When the latest outline request (`POST .../layouts/{id}/outline`) fails (network error, status 0, or a
non-2xx answer), then the editor removes every indentation and outline hint (all blocks `data-depth="0"`, no
"This chapter is empty.", no "not written yet" hint of R2-D3.8.3) and shows in the message region (R-U7.2)
"The chapter outline could not be updated." with a "Try again" button that sends a new outline request. An
older answer arriving afterwards is still ignored (fix round 2 item 5 unchanged). The next successful answer
redraws depth and hints. Source: 09 note 3. Test: Playwright, as `test_v2_browser.py` (latest request aborted,
earlier one released later: depth "0" everywhere and the message shown; Try again redraws).

### D3.4 English singular forms [RG][LB]

R2-D3.4.1 `en.json` may hold `messages` entries whose key is `"<msgid>|one"` and only such entries; its
`_meta.plural_one` is absent (default `[1]`), so 0 stays plural ("0 evaluations"). Every `|one` key's msgid is
used by a `t("...")` call. Replaces R-V8.3's "English needs no messages" and the stage-2 pin in
`test_i18n.py::test_r_v8_2_en_and_fr_catalogues_have_the_format`.

R2-D3.4.2 `en.json` holds the singular form of exactly these renderer messages (the count is the first
whole-number placeholder, so the rule of the interface picks it):

| msgid | singular (count 1) |
|---|---|
| `{count} evaluations` | `{count} evaluation` |
| `in {count} requirement groups` | `in {count} requirement group` |
| `{count} answers were given for other versions and are not shown.` | `{count} answer was given for another version and is not shown.` |
| `{count} evaluations are not tied to a version and are not shown.` | `{count} evaluation is not tied to a version and is not shown.` |
| `{count} more groups are not shown.` | `{count} more group is not shown.` |
| `{count} observations could not be tied to a tool.` | `{count} observation could not be tied to a tool.` |
| `{count} selected checklists are not in this project and are not shown.` | `{count} selected checklist is not in this project and is not shown.` |
| `{count} selected evaluations are not of this project and version and are not shown.` | `{count} selected evaluation is not of this project and version and is not shown.` |
| `{name} ({size} bytes)` | `{name} ({size} byte)` |

Not given a singular, because the English noun follows the total and is already right: `{count} of {total}
objectives with evidence`, `{answered} of {total} questions answered`, `answered {answered} of {total}`,
`{tools}, +{count} more`. Test: each message with 1 gives the singular and with 0 and 3 gives the plural text.

R2-D3.4.3 [LB] The package ships `i18n/en.json` with `"Overall pass rate: {rate} across {groups} groups|one":
"Overall pass rate: {rate} across {groups} group"` (the `rate` placeholder is a string, so `groups` decides).
Through `translate_for` (R2-D1.5) a run with one group reads "across 1 group", with four "across 4 groups".

R2-D3.4.4 Stage 3 checks every other English message with a count placeholder in the renderer and the three
packages (static scan of `t("...")` ids holding `{count}`, `{groups}` or another whole-number placeholder
followed by a plural noun) and adds any missing singular to this list; a test asserts the list of `|one` keys
equals the list in R2-D3.4.2 plus any addition stage 3 records in its plan.

### D3.5 Test-helper defects that hide 13 tests [SC][RG][RC]

R2-D3.5.1 [SC] `scripts/pipeline_chain/throwaway.py` `Throwaway.rows()` (authorised by the user in BRIEF-2) runs
psql with tuples-only unaligned output (`-t -A`, or equivalent) and parses the whole of its standard output as
one JSON value, so it returns the rows for 0, 1 and many rows, and for values holding newlines, quotes and
non-ASCII text (json_agg spreads several rows over several lines). It never reads psql's row-count footer. Its
signature, its errors (AssertionError with the psql message on failure) and every other function of the file are
unchanged. A new unit test `scripts/tests/test_throwaway_rows.py` pins these cases on a throwaway container.

R2-D3.5.2 [RG] `tests/test_service.py::test_r5_4_1_no_token_no_answer` passes `json={}` only to POST routes; for
the GET route it sends no body. The assertions (401 without and with a wrong token) are unchanged.

R2-D3.5.3 [RC] `tests/test_api_access.py::test_r4_4_3_a_stranger_gets_404` passes `json=` only for `post`; the
assertion (404) is unchanged.

R2-D3.5.4 These 13 tests, hidden today, must run and pass afterwards (no assertion weakened, none skipped):
1. aisc-report-generator `tests/test_service.py::test_r5_4_1_no_token_no_answer[get-/v1/block-types]`
2. apps/report-composer `tests/test_api_access.py::test_r4_4_3_a_stranger_gets_404[get-/api/p/alpha/systems]`
3. `...::test_r4_4_3_a_stranger_gets_404[get-/api/p/alpha/layouts]`
4. `...::test_r4_4_3_a_stranger_gets_404[get-/api/p/alpha/choices?block_type=test_results&system_id=<A_V2 id>]`
5. `...::test_r4_4_3_a_stranger_gets_404[get-/p/alpha/]`
6. apps/report-composer `tests/test_api_reports.py::test_r4_2_5_generate_stores_the_snapshot_and_the_pdf`
7. `tests/test_api_reports.py::test_r3_12_the_snapshot_survives_edits`
8. `tests/test_api_reports.py::test_r4_3_5_the_renderer_failing_is_502_and_failed`
9. `tests/test_api_reports.py::test_r7_2_5_a_pdf_over_25_mb_is_not_stored`
10. aisc-install `scripts/tests/test_report_grants.py::test_d6a_report_ro_logs_in_read_only`
11. `scripts/tests/test_report_grants.py::test_r6_5_report_ro_never_reads_the_catalogue`
12. `scripts/tests/test_report_grants.py::test_d13_composer_role_owns_its_schema`
13. `scripts/tests/test_report_grants.py::test_d13_composer_role_search_path`

(05-verify showed with in-memory fixes that the behaviour behind them is right: 34 composer and 79 scripts
passed.) If one of them fails for a real reason once visible, that is a bug in our code to fix in part 2, not a
reason to change the test.

R2-D3.5.5 Other users of `Throwaway.rows()` outside the report run (`scripts/pipeline_chain/test_dashboard_queries.py`
through `ctx.t.rows`) start to really parse results too. Their outcome is other people's work; part 2 records it
in the stage-2 baseline and does not change those tests.

R2-D3.5.6 [RC] The workaround helper in `apps/report-composer/tests/v2_fakes.py:325` ("bed.rows() cannot parse
psql's footer") may stay; replacing it by `bed.rows()` is optional and mechanical.

### D3.6 Imported presets keep another platform's reference ids [RC]

R2-D3.6.1 `POST /api/presets/import` stores the preset with every reference option (`x-aisc-reference`, per the
renderer's schema of that block type) set to its type default or left out, exactly as R-V1.4 does for layouts
(`presets._without_references`). The saved preset and its export then hold no evaluation pid, chart id, metric
pair, checklist id, objective id, legacy links or compare_to of the source. Replaces R-V1.10 (adds the step) and
fixes 05 note 7.

R2-D3.6.2 The 201 answer of `POST /api/presets/import` and of `POST /api/p/{ref}/layouts` with `preset_file`
carries `notices`: one item per reference option whose value in the file differed from what was stored,
`{"pointer": "/blocks/{i}/{option}", "message": "The {option label} of block {i + 1} pointed at data that is not
in this project; it was reset to its default."}` (for the platform-wide import: "... pointed at data of another
project or platform; ..."). The composer shows the notices in the message region (R-U7.2) as information, not as
an error. No notice when nothing was reset.

R2-D3.6.3 Built-in and saved presets already hold no references; creating a layout from them is unchanged
(R-V1.4). Why "every reference" and not "only the ones missing in the target project": deviation DV2-1.

### D3.7 "Keep texts" recognises prose options of any block from the schema [IF][RG][RC]

R2-D3.7.1 [IF] A new schema annotation `x-aisc-prose` (boolean) marks a string option as prose written for one
project (`true`) or as a name, id or other identifier (`false`). It does not change validation. The interface's
`COMMON_PROPERTIES.commentary` carries `x-aisc-prose: true`. `blocks.py`'s docstring documents it next to the
other `x-aisc-*` annotations.

R2-D3.7.2 [RG] Built-in annotations: `free_text.text` and `chapter.intro` carry `x-aisc-prose: true`; the item
schemas of `control_objectives.requirements`, `summary_coverage.requirements`, `test_results.tools` and the
option `chart.dimension` carry `x-aisc-prose: false` (identifiers without `maxLength`, not references). Titles,
`cover.report_title` and `cover.subtitle` stay without annotation (their `maxLength` is at most 300). A test over
`GET /v1/block-types` asserts that every string leaf of every built-in schema is either annotated, has a
`maxLength` of at most 300, has `enum`/`const`/`pattern`/`format`, or lies under an `x-aisc-reference` option.

R2-D3.7.3 [RC] Prose rule (replaces `presets._free_text_options` and the "string with maxLength above 300" rule
of fix round 1, finding 4). Walking a block type's options schema (as `GET /v1/block-types` returns it) through
`properties`, `items`, `prefixItems`, `additionalProperties` and every `oneOf` / `anyOf` / `allOf` branch, a
string leaf (a node whose `type` is `"string"` or a list containing `"string"`, for example
`["string", "null"]`) is prose when:
1. it carries `x-aisc-prose: true`; or
2. it carries no `x-aisc-prose`, no ancestor carries `x-aisc-prose: false` or `x-aisc-reference`, and it has none
   of `enum`, `const`, `pattern`, `format`, or a `maxLength` of 300 or less.
It is never prose when it or an ancestor carries `x-aisc-prose: false`. Under `oneOf` / `anyOf`, a value is
replaced only when every string branch it could match is prose. When the renderer does not describe the block
type, the fixed list stays: commentary, `free_text.text`, `chapter.intro`.

R2-D3.7.4 [RC] Replacement when `keep_text` is false (R-V1.9 otherwise unchanged): a prose value that is required
(its name is in the parent's `required`, or `minLength` is at least 1) becomes the placeholder "Write this
section." (cut to `maxLength` if shorter); a nullable one becomes null; any other becomes "". An array whose
items are prose strings becomes `[]` (or `minItems` placeholders). Objects inside arrays are walked item by item.
A value whose shape does not match the schema (for example a string where an object is expected) is left as it
is. Titles, the cover title and subtitle stay.

R2-D3.7.5 Tests (composer, with fake block types): a plugin block whose prose option has no `maxLength`, one typed
`["string", "null"]`, one nested in an object, one inside array items, one under `oneOf`; each is dropped
without "Keep texts" and kept with it; identifiers marked `x-aisc-prose: false`, enum strings, pattern strings
and reference options are kept (references are reset by R-V1.4 anyway). The three tests
`test_fix4_*` of `test_v2_presets.py` keep passing unchanged.

### D3.8 The placeholder "Write this section." in generated reports [RG][RC]

R2-D3.8.1 [RG] The renderer treats a text whose trimmed value is exactly "Write this section." as not written:
- a `free_text` block whose `text` is the placeholder is left out of the document (no section, no TOC entry, no
  number; numbering and the chapter grouping continue as if the block were absent) in preview, PDF and DOCX; its
  entry in `block_statuses` stays (same order as the snapshot's blocks) with status `empty` and the notice
  "Not written yet: left out of the report.";
- a `commentary` or a `chapter.intro` equal to the placeholder is not printed (the section is exactly as with an
  empty value).
DEFAULT (user to confirm), question Q2-6. The placeholder text is one constant in the renderer and one in the
composer; a test in each repo pins both to "Write this section.".

R2-D3.8.2 [RG] Plugin blocks are drawn by their own code, so the renderer does not look into their options; the
composer flags them (R2-D3.8.3). Deviation DV2-5.

R2-D3.8.3 [RC] The editor flags every block holding the placeholder in a prose option (rule R2-D3.7.3) with the
hint "Not written yet: this text still holds the placeholder and is left out of the report." (built-in blocks) or
"Not written yet: this text still holds the placeholder." (plugin blocks), computed in Python: on page render and
in the outline route's answer (each outline item gains `unwritten: [option names]`), so the hint follows edits
like the empty-chapter hint. It is a hint, not a problem: Save and Generate are not refused.

R2-D3.8.4 A layout made from the built-in preset `eu-ai-act` or `internal-audit` and generated at once gives a
PDF and a DOCX whose text holds no "Write this section." (composer e2e and a renderer test).

### D3.9 Correct 08-fix-round-2.md

R2-D3.9.1 In `08-fix-round-2.md` item 1, the sentence "the 5 that passed are whitespace-like characters that the
old folding already removed" is corrected in place, followed by a line "Corrected in part 2 (2026-09-25):". The
corrected text says: the 5 were the whole-renderer cases `ff`, `vt`, `us` (whitespace for Python's `str.split`,
which the old folding removed), `nul` (not whitespace; removed earlier by the layer stage 3 names after tracing
it, with the evidence), and `test_fix_r2_1_a_character_reference_in_markdown_free_text_renders_as_docx`, which
already passed before the fix and is a guard, not a regression test. Nothing else in 08 changes.

### D3.10 The two generator failures listed as pre-existing

R2-D3.10.1 [RG] `tests/test_block_ai_card.py::test_r2_2_2_tags` contradicts R2.2.1 (the target use case "Credit
scoring" of the fixture holds "scoring" and must be shown). Its hidden-tags assertion is aimed at the tag list
only: with `show_tags=False` the section has no tag list element and neither "b2b" nor "eu" appears in the text
where the tags were; with tags shown the four tags appear in the tag list. The behaviour tested is the same.
Test change, own commit, listed under Deviations of stage 2.

R2-D3.10.2 The `TestClient.get(..., json=...)` defect is R2-D3.5.2 and R2-D3.5.3. After both, the generator suite
has 0 failures.

## 4. What "fully green" means at the end of part 2

`env | grep -iE 'DATABASE|DSN|DB_URL'` empty; every database suite on its own `aisc-t-*` container; Chrome at
`/usr/bin/google-chrome` for the composer's browser tests.

| suite | fully green means |
|---|---|
| aisc-report-plugin-interface | 0 failed |
| aisc-report-langbite, -strongreject, -promptfoo, aisc-report-mlareject | 0 failed each |
| aisc-report-generator (incl. goldens and e2e) | 0 failed (today 589 + 2 known; the 2 are fixed by R2-D3.10) |
| apps/report-composer (incl. browser tests and e2e) | 0 failed (today 331 + 8; the 8 are items 2 to 9 of R2-D3.5.4) |
| scripts/tests/test_report_stack.py + test_report_grants.py | 0 failed **except exactly these 3**, caused by other people's work and not ours to fix: `test_report_stack.py::test_d6_guard_init_files_do_not_mention_report_roles` (`init/project-databases.sql` last changed by 3e20ffb "A card version belongs to its project", 2026-09-24 19:34, another pipeline); `test_report_stack.py::test_r4_1_2_launcher_card_seven` (`homepage/project.html`, another session's uncommitted change); `test_report_stack.py::test_final_guard_frozen_passes` (guard-frozen.sh FAILs at baseline because of the gateway-login work, 00-baseline.md). Today 75 passed, 7 failed; afterwards the 4 grants tests pass: 79 passed, 3 failed |
| scripts/guard-frozen.sh | prints the same lines as 00-baseline.md (G1 FAIL 238 lines, G2 PASS, G3 PASS x2, the three G4 FAIL lines, G5 PASS) |
| other suites that use `Throwaway.rows()` (for example `scripts/pipeline_chain/test_dashboard_queries.py`) | not part of the definition; their result is recorded, not fixed (R2-D3.5.5) |

If one of the 3 excluded tests changes outcome because of other people's work, the stage that sees it records it
and does not touch it.

## 5. Earlier requirement ids replaced or removed (summary)

| earlier id | fate | by |
|---|---|---|
| R-V8.1 | removed (no language per layout; column kept unused) | R2-D1.9, R2-D1.11 |
| R-V8.2 | replaced: built-in `en.json` only, no `REPORT_I18N_PATH` | R2-D1.1 |
| R-V8.3 | replaced: `en.json` may hold `|one` entries only | R2-D3.4.1 |
| R-V8.4 | removed (no fr.json, no French completeness test) | R2-D1.1 |
| R-V8.5 | replaced: `/v1/languages` is English only; any pattern-valid language renders English | R2-D1.2, R2-D1.3 |
| R-V8.6 | removed | R2-D1.1 |
| R-V8.7 | replaced: nothing is translated; `.` decimals; `lang="en"` | R2-D1.3 |
| R-V8.8 | replaced: context English only; packages may ship en.json; interface unchanged | R2-D1.5, R2-D1.7 |
| R-V8.11 | language property is always `en` | R2-D1.3 |
| R-V8.13 | removed (no Language select) | R2-D1.9 |
| R-V1.1, R-V1.3, R-V1.6, R-V1.7, 2.1, 2.5 (language edge) | language parts removed | R2-D1.13 |
| R-V1.9 | prose recognition becomes schema-driven | R2-D3.7.3, R2-D3.7.4 |
| R-V1.10 | import resets references and tells the user | R2-D3.6.1, R2-D3.6.2 |
| R-U3.1 | `language` in the draft body accepted and ignored | R2-D1.10 |
| R-D.1, R-D.3, R-D.4 | language parts removed (column kept) | R2-D1.10, R2-D1.11 |
| R-S (16.1 `language`), R-S.3, R-S.7 | composer sends no language; renderer accepts and ignores it; health English only | R2-D1.2, R2-D1.3, R2-D1.12 |
| R-V2.7 (parenthetical), R-V2.11 (a, b), R-V2.12, R-V2.15, R-V2.21, R-V2.23, section 18 bullet 1 | tool's own Pass / Fail shown | R2-D2.1 to R2-D2.5 |
| R-V2.24 | `i18n/*.json` optional (en.json when needed) | R2-D1.7 |
| R-C.4 | gains items 5 and 6 | R2-C.3 |
| Q1, Q9, Q4-1 (01 section 20, 04) | closed by D1 | BRIEF-2 D1 |
| Q3 | replaced by D2 | BRIEF-2 D2 |
| 01 section 19 item 8 (French completeness last) | removed | R2-D1.1 |

The words "(translated, V8)" in R-V3.9, R-V5.4, R-V5.5, R-V5.11 and R-V5.13 now mean "through `t()`, English".

## 6. Existing tests to remove or change because of the decisions

"Remove" means the requirement is gone; "change" means the test stays with the assertion named. Each removal and
change is a by-design commit of its own in stage 2 (RULES: tests change in stage 2, not stage 4).

### 6.1 aisc-report-generator

| test | action |
|---|---|
| `tests/test_i18n.py::test_r_v8_2_en_and_fr_catalogues_have_the_format` | change: en.json only, `|one` keys only (R2-D3.4.1); no fr.json exists |
| `tests/test_i18n.py::test_r_v8_4_every_msgid_has_a_french_entry` | remove |
| `tests/test_i18n.py::test_r_v8_4_the_core_texts_are_translated` | remove |
| `tests/test_i18n.py::test_r_v8_3_t_in_french` | remove |
| `tests/test_i18n.py::test_r_v8_5_languages_route_lists_english_first` | change: the route returns exactly `[{"code": "en", "name": "English"}]` |
| `tests/test_i18n.py::test_r_v8_6_a_catalogue_in_report_i18n_path_adds_a_language` | change: a `de.json` in `REPORT_I18N_PATH` is ignored; `/v1/languages` stays English only and `language="de"` renders English |
| `tests/test_i18n.py::test_r_v8_2_a_bad_file_name_in_the_path_is_ignored` | remove (the path is no longer read) |
| `tests/test_i18n.py::test_r_v8_7_fixed_texts_are_french_data_is_not` | change: with `language="fr"` every fixed text is English and `lang="en"` (R2-C.1) |
| `tests/test_i18n.py::test_r_v8_7_dates_stay_iso_numbers_use_the_decimal_comma` | change: with `language="fr"`, "0.125" and not "0,125"; dates ISO |
| `tests/test_i18n.py::test_r_v8_7_page_x_of_y_is_translated_in_the_pdf_css` | change: with `language="fr"` the CSS holds `"Page " counter(page) " of "` |
| `tests/test_i18n.py::test_fix_french_singular_forms` (12 cases) | replace by the English singular test of R2-D3.4.2 |
| `tests/test_i18n.py::test_fix_every_singular_form_belongs_to_a_used_message` | change: over en.json |
| `tests/test_i18n.py` helper `fr()` | remove |
| `tests/test_commentary.py::test_r_v3_9_the_caption_is_translated` | remove (`test_r_v3_9_the_commentary_has_a_small_caption` stays) |
| `tests/test_e2e_v2.py::test_e2e_v2_preview_pdf_and_docx` | change: snapshot keeps `language="fr"` to prove compatibility; asserts `lang="en"`, TOC heading "Contents", "INTERNAL" marking, DOCX language `en` |
| `tests/test_service_v2.py::test_r_s_7_health_gains_interface_version_and_languages` | change: `languages` is English only |
| `tests/test_snapshot_v2.py::test_r_v8_5_an_unknown_language_is_invalid_snapshot_at_language` | change: `"xx"` renders 200 in English; `"French"` (pattern mismatch) is 422 at `/language` |
| `tests/test_v2_key_figures.py::test_fix2_french_tool_tiles_use_french_numbers_and_words` | remove |
| `tests/test_v2_key_figures.py::test_fix2_a_contract_2_renderer_whose_headline_takes_only_the_run_still_gets_tiles` | change: English, asserts "Overall pass rate" |
| `tests/test_v2_key_figures.py::test_fix_r2_3_french_label_value_texts_use_the_french_colon` | remove (the English twin stays) |
| any test asserting the promptfoo tile label "Promptfoo: Pass rate" | change to "Promptfoo: Pass" (R2-D2.5) |
| `tests/test_service.py::test_r5_4_1_no_token_no_answer` | change (helper defect, R2-D3.5.2) |
| `tests/test_block_ai_card.py::test_r2_2_2_tags` | change (R2-D3.10.1) |
| `tests/test_compat_golden.py` | unchanged; the "Sommaire" alternative in `_without_toc_page_numbers` may be dropped (mechanical) |

### 6.2 aisc-report-plugin-interface

No test removed or changed for D1 (mechanism tests with sample data stay, DV2-4). New tests for
`x-aisc-prose` on `COMMON_PROPERTIES.commentary` (R2-D3.7.1).

### 6.3 aisc-report-langbite, -strongreject, -promptfoo

| test | action |
|---|---|
| each `tests/conftest.py` helper `french_ctx` | remove |
| each `tests/test_packaging.py::test_r_v2_24_templates_and_catalogues_ship_with_the_package` | change: no `i18n/fr.json`; LangBiTe ships `i18n/en.json`; package-data glob kept |
| each `tests/test_packaging.py::test_r_v8_4_every_msgid_has_a_french_entry` | remove |
| each `tests/test_tool_renderer.py::test_r_v8_8_french_uses_the_package_catalogue` | remove |
| each `tests/test_tool_renderer.py::test_fix2_headline_values_follow_the_report_language` | remove (`test_fix2_headline_without_a_context_stays_english` stays; add: an English ctx gives the same values) |
| langbite `test_fix_french_one_group_is_singular` | replace by the English "across 1 group" test (R2-D3.4.3) |
| langbite `test_r_v2_11_group_table_columns` | change: last header "Pass / Fail (LangBiTe tolerance check)" |
| langbite `test_r_v2_11_group_cells` | change: "Pass", "Fail", "Not evaluated" |
| langbite `test_r_v2_12_no_verdict_words_of_the_report` | change: "tolerance set in langbite" and the new header; no "verdict" |
| langbite `test_r_v2_15_summary_detail_shows_line_and_chart_only` | change: the run result line of R2-D2.3 is also shown |
| promptfoo `test_r_v2_21_table_of_the_six_measurements`, `test_r_v2_21_direction_words_come_from_the_unit`, `test_r_v2_21_absent_rates_are_not_reported`, `test_r_v2_21_chart_of_the_rates_present`, `test_r_v2_23_headline` | change: labels "Pass" and "Fail" (R2-D2.5) |
| strongreject | no change for D2 (new test R2-D2.6) |

### 6.4 aisc-report-mlareject

No change (its "fr" is a language dimension in test data, not a report language).

### 6.5 apps/report-composer

| test | action |
|---|---|
| `tests/test_v2_layout_settings.py::test_r_c_6_new_fields_default_to_todays_behaviour` | change: no `language` key in the view |
| `tests/test_v2_layout_settings.py::test_r_d_3_post_and_put_accept_the_new_fields` | change: `language` accepted and ignored, absent from the answer |
| `tests/test_v2_layout_settings.py::test_r_d_3_absent_on_put_keeps_the_current_value` | change: without `language` |
| `tests/test_v2_layout_settings.py::test_r_d_3_the_layouts_list_carries_the_language` | remove |
| `tests/test_v2_layout_settings.py::test_r_d_4_bad_settings_are_refused` | change: drop the two `language` cases (`xx`, `de`), keep `toc` and `numbering` |
| `tests/test_v2_layout_settings.py::test_r_s_3_the_stored_snapshot_is_version_2_with_the_new_keys` | change: no `language` key sent or stored |
| `tests/test_v2_layout_settings.py::test_r_v8_1_the_language_is_sent_in_the_preview_snapshot` | replace: a layout row holding `'fr'` sends no `language` (R2-C.1) |
| `tests/test_v2_pages.py::test_r_v8_13_the_language_select` | replace: the editor has no language control |
| `tests/test_v2_pages.py::test_r_v8_16_the_composer_screens_stay_in_english` | change: no `language` argument |
| `tests/test_v2_presets.py::test_r_v1_1_built_in_preset_document_settings` | change: no `language` in the files |
| `tests/test_v2_presets.py::test_r_v1_2_no_preset_and_no_blocks_is_the_full_assessment` | check; change only if it asserts `language` |
| `tests/test_v2_presets.py::test_r_v1_6_a_copy_keeps_everything_but_ids_revision_and_reports` | change: `language` dropped from body and compared keys |
| `tests/test_v2_presets.py::test_r_v1_7_export_is_a_preset_file` | change: file keys without `language` |
| `tests/test_v2_presets.py::test_r_v1_edge_a_language_no_longer_offered_falls_back_to_english_with_a_notice` | change: 201, no language in the answer, no language notice |
| `tests/test_v2_draft_preview.py::test_r_u3_1_the_draft_is_rendered_and_nothing_is_stored` | change: the sent snapshot has no `language` |
| `tests/test_v2_renderer_client_unit.py::test_r_s_7_languages_is_get_v1_languages` | remove (with the client method) |
| `tests/test_e2e_v2.py::test_e2e_v2_preset_french_coverage_draft_pdf_and_docx` | change: renamed without "french"; keeps `language="fr"` in the PUT body to prove it is ignored; asserts `lang="en"`, no "Write this section." in PDF and DOCX (R2-D3.8.4) |
| `tests/v2_fakes.py` `LANGUAGES`, `languages()` | remove |
| `tests/test_v2_migration.py::test_r_d_1_new_columns_with_their_defaults`, `::test_r_c_3_an_old_layout_previews_with_the_same_snapshot_apart_from_new_keys` | unchanged (the column stays; `language` absent passes the existing `get("language", "en")`) |
| `tests/test_api_access.py::test_r4_4_3_a_stranger_gets_404` | change (helper defect, R2-D3.5.3) |

### 6.6 aisc-install scripts

`scripts/pipeline_chain/throwaway.py` changes (R2-D3.5.1); no scripts test is removed; new
`scripts/tests/test_throwaway_rows.py`.

## 7. Order and dependencies

1. [SC] `Throwaway.rows()` and the two `json=` test defects first (R2-D3.5): the hidden tests become visible, so
   the stage-2 baseline is measured with them (05 showed the 8 composer and 4 grants tests pass with repaired
   helpers, so stage 2 expects them green before part 2's own changes).
2. [IF] `x-aisc-prose` (R2-D3.7.1).
3. [RG] D1 (R2-D1.1 to R2-D1.6), English singular forms (R2-D3.4), surrogate id (R2-D3.1), DOCX link (R2-D3.2),
   placeholder (R2-D3.8.1), built-in annotations (R2-D3.7.2), `test_r2_2_2_tags` (R2-D3.10).
4. [LB][SR][PF] D1 package files (R2-D1.7), D2 (R2-D2.2 to R2-D2.6), LangBiTe en.json (R2-D3.4.3).
5. [RC] D1 (R2-D1.9 to R2-D1.13), import references (R2-D3.6), prose rule (R2-D3.7.3), placeholder hint and
   outline (R2-D3.8.3, R2-D3.3), e2e.
6. Docs: 08 correction (R2-D3.9).

## 8. Deviations

- DV2-1 (D3.6) The brief says references "that do not exist in the target project" reset. A saved preset is
  platform-wide (no target project), and R-V1.4 already resets every reference when a layout is made from any
  preset, because evaluation pids, checklist ids and chart ids belong to one project. So import resets every
  reference and names each one that held a value; the result for a layout is the same as today, and the saved
  preset no longer carries foreign ids. Keeping references that happen to exist in the target project would
  contradict R-V1.4 and BRIEF V1 ("no project-specific references").
- DV2-2 (D2) LangBiTe writes `All Tolerances Passed` = 0.0 with "0/0 tolerance checks passed" when a run produced
  no group. Printing "Fail" there would present an empty run as a failed check, so the line says "not evaluated"
  with the tool's description (R2-D2.3). With at least one group the tool's 1 or 0 is shown as Pass or Fail.
- DV2-3 (D2) Per-test Pass / Fail of promptfoo and per-prompt results of LangBiTe and StrongREJECT exist only in
  artifacts that also hold prompts and model responses, some harmful. R-V2.9 (never read artifacts) stands, so
  the report shows the tools' aggregate Pass / Fail only.
- DV2-4 (D1) The interface's i18n module and its tests stay unchanged (generic loader; French appears there only
  as sample data of the tests). The renderer stops reading `REPORT_I18N_PATH`, so no second language can be added
  by configuration.
- DV2-5 (D3.8) Plugin blocks draw their own options, so the renderer leaves out only the built-in placeholders
  (free text, commentary, chapter intro); for a plugin block the composer shows the "not written yet" hint.
- DV2-6 (D1) The columns `layout.language` and `preset.language` stay in the schema, unused: migrations are
  additive and a drop needs the user's yes.
- DV2-7 (D3.7) The prose rule treats an unannotated free string with no `maxLength` as prose (removed from a
  preset), because a saved preset is visible platform-wide and the safe side is to drop text. Built-in
  identifiers of that shape are annotated `x-aisc-prose: false`; plugin authors can do the same.
- DV2-8 (compatibility) English singular forms change one sentence inside the Test results section of three
  goldens (R2-C.3 item 6). The golden tests already allow changes in that section, so they pass unchanged and the
  Delta goldens stay byte-identical.

## 9. Questions for the user

- Q2-1 Remove `REPORT_I18N_PATH`, so no other language can be added by dropping a file? `DEFAULT (user to
  confirm)`: removed (R2-D1.1).
- Q2-2 Drop the unused columns `layout.language` and `preset.language` later? `DEFAULT (user to confirm)`: kept,
  unused; no drop in part 2.
- Q2-3 Should a tool's own Fail (for example LangBiTe "All tolerance checks: Fail") also mark the linked
  objectives "evidence, attention" in the coverage map? `DEFAULT (user to confirm)`: no; Pass / Fail is shown in
  the tool section only and `verdict()` stays None (R2-D2.8).
- Q2-4 promptfoo gives Pass / Fail as shares. Show counts ("34 of 40 tests passed") computed from the share and
  the number of tests? They can be wrong when some tests have no result. `DEFAULT (user to confirm)`: shares only
  (R2-D2.5).
- Q2-5 MLA-Reject's section splits cases into "harmful" and "empty" at a fixed score of 1.5, inherited from the old
  report module (not a user threshold, not the tool's output). `DEFAULT (user to confirm)`: kept as it is
  (R2-D2.7).
- Q2-6 A free text still holding "Write this section.": leave the whole section out, or print its heading with no
  text? `DEFAULT (user to confirm)`: the whole section is left out and the editor flags it (R2-D3.8.1).
- Q2-7 Built-in presets have English chapter and cover titles (05 note 9); with D1 this is no longer a mismatch.
  `DEFAULT (user to confirm)`: nothing to do.
- Q2-8 Documents already generated in French stay stored and downloadable as they were. `DEFAULT (user to
  confirm)`: kept unchanged (R2-C.4).

The other open questions (01-specs Q2, Q4 to Q8, Q10, Q2-1, Q3-1, Q3-2) stand with their defaults, as BRIEF-2
says; Q1, Q3, Q9 and Q4-1 are closed by D1 and D2.
