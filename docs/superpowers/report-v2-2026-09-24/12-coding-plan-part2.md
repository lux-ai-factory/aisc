# Part 2, stage 3: Coding plan for D1 to D3 (report run v2)

Status: done. Inputs: `RULES.md`, `BRIEF-2.md`, `10-specs-part2.md`, `11-tests-part2.md`, `03-coding-plan.md` (for
the conventions, which still hold), the committed stage-2 tests and the code they target. Stage 4 follows this plan
group by group, in order. Where this plan names a file, function, constant or key, that is the name to use. No
implementation code was written in this stage. One plainly wrong test was fixed (section 3, DV12-1).

## 0. Failing counts, re-measured by stage 3 (2026-09-25, throwaway beds only)

`env | grep -iE 'DATABASE|DSN|DB_URL'` printed nothing. Database suites made their own `aisc-t-*` containers (report
bed, `aisc-t-rows-*`, `aisc-t-guard-*`); none was left. Other sessions' containers: none running at the time.

| suite | head | total | passed | failed | matches 11-tests-part2.md |
|---|---|---|---|---|---|
| aisc-report-plugin-interface | dev cd3cc1e | 139 | 137 | 2 | yes (test_p2_prose x2) |
| aisc-report-langbite | dev 5f0fe82 | 43 | 26 | 17 | yes |
| aisc-report-strongreject | dev 8fa948f | 26 | 24 | 2 | yes |
| aisc-report-promptfoo | dev 918bc36 | 29 | 17 | 12 | yes |
| aisc-report-mlareject | dev 247a0d9 | 20 | 20 | 0 | yes |
| aisc-report-generator (incl. goldens, e2e) | dev fe30ed2 | 640 | 581 | 59 | yes |
| apps/report-composer (incl. browser, e2e) | aisc-install 76fec03 | 409 | 345 | 64 | yes (60 new/changed + 4 `rows()`) |
| scripts/tests stack + grants + throwaway_rows | same | 94 | 77 | 17 | yes (3 others' + 4 `rows()` grants + 10 pin) |
| guard-frozen.sh | | | | | identical to 00-baseline.md (G1 FAIL 238 lines, G2 PASS, G3 PASS x2, G4 FAIL x3, G5 PASS) |

After the test fix of this stage (langbite f5c0caf) the langbite count is unchanged (43 / 26 / 17): the fixed test
still fails for the missing feature.

Failing tests per file: generator test_p2_english 26, test_p2_fixes 23, test_i18n 6, test_e2e_v2 1,
test_service_v2 1, test_snapshot_v2 1, test_v2_key_figures 1 (no helper failure left after the fixes of 11).
Composer test_p2_english_only 28, test_p2_presets 17, test_p2_unwritten 4, test_p2_browser 1, test_v2_presets 5,
test_v2_layout_settings 3, test_v2_draft_preview 1, test_e2e_v2 1, test_api_reports 4 (`rows()`). LangBiTe
test_p2_langbite 12, test_tool_renderer 4, test_packaging 1. promptfoo test_p2_promptfoo 6, test_tool_renderer 5,
test_packaging 1. StrongREJECT test_p2_strongreject 1, test_packaging 1. Interface test_p2_prose 2. Scripts
test_throwaway_rows 10, test_report_grants 4, test_report_stack 3 (others' work).

## 1. Ground rules for stage 4 (as 03-coding-plan.md section 1, with these part-2 points)

1. Before every run `env | grep -iE 'DATABASE|DSN|DB_URL'` prints nothing; afterwards
   `docker ps -a --filter name=aisc-t- --format '{{.Names}}'` shows none of yours (leave other sessions'
   `aisc-t-*` containers alone, for example `aisc-t-llmtok-*`). Never touch the live stack or 127.0.0.1:5432.
2. TDD: the failing tests exist. The only test edits allowed are the by-design commits of section 4 (each its own
   commit, message given) and plainly wrong tests (own commit, listed under Deviations in stage 4's report). Never weaken,
   skip or delete a stage-2 test.
3. Commits local only, no push, no new branch, stage by explicit path. In aisc-install other people's changes
   (`apps/qualification` pointer, `homepage/project.html`, `docs/superpowers/form-assembly-2026-09-24/`,
   `__pycache__` folders, anything else `git status` shows that is not yours) stay unstaged. Never
   `git reset --hard`, `git checkout -- .`, `git stash`, `git clean`.
4. The interface and the tool packages are editable path dependencies of the generator (`[tool.uv.sources]`), so
   code and data-file changes are seen without reinstalling. No `pyproject.toml` changes are planned; if one is made,
   `uv lock` and `uv sync --extra dev --reinstall-package <name>` in every dependent repo.
5. Word rules of 03 section 1.6 still hold (no `catalogue` under `report_renderer/`, no module names such as
   `qualification.` in composer `.py` files). New: `apps/report-composer/report_composer/static/composer.js` must not
   contain the substring `language` anywhere, comments included (R2-D1.9 test).
6. No em dashes; plain short sentences. Goldens are never re-captured.
7. After every aisc-install commit run `scripts/guard-frozen.sh`; it must print the 00-baseline.md lines.

## 2. Cross-cutting decisions

**P1. English is the only language, the plumbing stays.** `t()` calls stay; `en.json` gains `|one` entries only.
Every snapshot, context and document is English whatever `language` says, as long as it matches the pattern.

**P2. The renderer's placeholder constant** is `report_renderer.blocks.free_text.PLACEHOLDER = "Write this section."`
(the test imports it there, DV11-3). `document.py` and `chapter.py` import it from there. A text is "not written"
when `isinstance(text, str) and text.strip() == PLACEHOLDER`; one helper `free_text.is_placeholder(text) -> bool`.

**P3. The composer's prose rule lives in one new module** `report_composer/prose.py` (pure functions, no I/O).
`presets.py` and `pages.py` and `api.py` use it. `presets.PLACEHOLDER` stays importable (`from .prose import
PLACEHOLDER`), since the test pins it there.

**P4. Surrogate problems carry printable instance ids.** `snapshot._instance_id` returns `_printable(iid)` (the
backslash escape) whenever the id is a string, so every problem of a block with a bad id carries `"x\\ud800y"`; the
surrogate message becomes exactly `"holds a lone surrogate"` for every placement (one constant
`SURROGATE_MESSAGE`). The existing fix-round-2 tests check only pointers and ids, so they keep passing.

**P5. Outline items** (composer `POST .../outline` and the editor page) become
`{instance_id, depth, empty_chapter, unwritten, unwritten_hint}`: `unwritten` is the list of top-level option names
still holding the placeholder (R2-D3.8.3), `unwritten_hint` the text Python chose (or null), so the script only draws
it. This changes one old exact-equality test (section 4, B1).

## 3. Deviations and the test fix of this stage

- **DV12-1 (test fix, langbite f5c0caf).** `test_p2_langbite.py::test_r2_d2_10_pass_and_fail_appear_only_as_the_tool_stated_them`
  counted `\b(?:Pass|Fail)\b` in the whole section and expected stated cells + run line + 1. No correct section can
  meet it: the required header "Pass / Fail (LangBiTe tolerance check)" holds two such words, and the kept column
  "Pass rate" and chart title "Pass rate by concern" (LangBiTe's own measure, R-V2.11) hold one each. The fix counts
  `\b(?:Pass|Fail)\b(?! rate)` and expects + 2 for the header. It still fails today for the missing feature and still
  catches any extra Pass or Fail word. Own commit, nothing else changed.
- **DV12-2 (by-design test change for stage 4, B1).** `test_v2_pages.py::test_fix_outline_route_gives_depth_and_empty_chapter_for_any_order`
  compares the whole outline answer with `==`. R2-D3.8.3 adds `unwritten` to every item and this plan adds
  `unwritten_hint` (P5), so the expected dicts gain `"unwritten": [], "unwritten_hint": None`. Stage 2 did not list
  it; the assertion is not weakened.
- **DV12-3 (test data for stage 4, B2).** DV11-5 named the v2 fakes only. The 2026-09-23 fakes in
  `tests/conftest.py` (`BLOCK_TYPES`, used by the non-v2 client) also hold identifier strings that the new rule would
  treat as prose: `test_results.tools` items and `test_results.statuses` items (the real renderer has an enum
  there). B2 annotates all of them `x-aisc-prose: false`, so exports of fake layouts keep them as the real renderer
  would.
- **DV12-4 (R2-D3.1.1).** The test requires the message "holds a lone surrogate" exactly; the current message is
  "holds a lone surrogate, which is not a character". The shorter message is used for every placement (P4); no old
  test pins the long one.
- **DV12-5 (R2-D1.1).** `languages.language_files(env=None)` reads only `report_renderer/i18n/en.json` (not a glob
  of the folder): with `fr.json` gone the result is the same, and a stray file can never add a language. `env` stays
  as a parameter and is ignored.
- **DV12-6 (R2-D3.8.3, availability).** The outline route now needs the block types (for plugin prose options). When
  the renderer is unavailable it falls back to the fixed list (commentary, `free_text.text`, `chapter.intro`) instead
  of answering 502, so indentation keeps working without the renderer.
- **DV12-7 (R2-D3.6.2).** `notices` is present (a list, possibly empty) in the 201 answers of
  `POST /api/presets/import` and of `POST /api/p/{ref}/layouts` when `preset_file` is given; other layout answers do
  not gain the key (the layout view keys stay as they are). The `{option label}` is the schema property's `title`,
  else the option name (DV11-7).
- **DV12-8 (R2-D3.4.4).** Static scan done (all `t("...")` ids with a placeholder in `report_renderer/`, the three
  new packages and mlareject, `.py` and `.j2`; plus plural nouns after a `{{ }}` in templates). No counted plural noun
  beyond the nine of R2-D3.4.2 and LangBiTe's summary line: "and {count} more", "not rated: {count}",
  "{count} of {total}", "risk severity at least {n}", "requirement groups {groups}" (a list of ids), "{value} ms"
  and the new part-2 texts need no singular. `SINGULARS` in `test_p2_english.py` stays as it is; StrongREJECT and
  promptfoo ship no `en.json`.
- **DV12-9 (R2-D3.9.1, trace done by this stage).** Why the `nul` whole-renderer case passed before generator
  dfb3a51: at dfb3a51^, `docx.html_to_docx` parses the page with `lxml.html.document_fromstring(html)`
  (docx.py:514 at that commit). libxml2 2.14.6 (lxml 6.1.3) replaces a NUL in HTML input with U+FFFD, which XML
  allows: `lxml.html.fromstring('<p>a\x00b</p>').text_content() == 'a�b'`, while `'\x01'` stays. The markdown
  parts never held NUL at all: markdown-it replaces it with U+FFFD (`richtext.render('a\x00b') == '<p>a�b</p>\n'`).
  `ff`, `vt`, `us` passed because `str.split` and `\s` treat them as whitespace (`' a\x0bb\x0cc\x1fd\x00e'.split()`
  gives `['a', 'b', 'c', 'd\x00e']`), so `_collapse` removed them. The fifth,
  `test_fix_r2_1_a_character_reference_in_markdown_free_text_renders_as_docx`, passed because markdown-it turns
  `&#1;`, `&#x1b;` and `&#xFFFE;` into U+FFFD itself (checked with `richtext.render`). Group 6 writes this into 08.

No new question for the user. The part-2 questions Q2-1 to Q2-8 stand with their defaults.

## 4. Test-only commits stage 4 makes (before the code that needs them)

| id | repo | file | change | message |
|---|---|---|---|---|
| B1 | aisc-install | `apps/report-composer/tests/test_v2_pages.py` | `test_fix_outline_route_gives_depth_and_empty_chapter_for_any_order`: each expected item gains `"unwritten": [], "unwritten_hint": None` (DV12-2) | "The outline route test expects the unwritten list and hint that every outline item now carries (R2-D3.8.3, by design)" |
| B2 | aisc-install | `apps/report-composer/tests/v2_fakes.py`, `apps/report-composer/tests/conftest.py` | v2 fakes: `chart.dimension` and the items of `test_results.tools` (`ALL_OR_LIST` copy used there) get `"x-aisc-prose": False`; `COMMON_V2.commentary`, `free_text.text`, `chapter.intro` get `"x-aisc-prose": True` (mirror of the renderer, R2-D3.7.1/2). v1 fakes (`BLOCK_TYPES`): `test_results.tools` items and `test_results.statuses` items get `"x-aisc-prose": False` (DV11-5, DV12-3). Take care that `ALL_OR_LIST` is shared: give `tools` its own annotated copy, do not change `objectives` (a reference option) | "The fake block types carry the renderer's x-aisc-prose annotations, so the schema-driven prose rule treats their identifiers as the real renderer's (DV11-5, test data only)" |

B2 lands in Group 4 right before step 4.4 (the prose rule); B1 right before step 4.6 (outline). Both change no
assertion's meaning. If any other old test breaks, decide as 03 section 1.2: by design (own commit, report it) or a
regression (fix the code).

## Group 1: the interface (aisc-report-plugin-interface, dev)

Files: `vera_report_plugin_interface/blocks.py`.
- `COMMON_PROPERTIES["commentary"]` gains `"x-aisc-prose": True`. Nothing else in the dict changes.
- Module docstring: the list of annotations becomes "`title`, `description`, `x-aisc-enum-labels`, `x-aisc-more`,
  `x-aisc-show-if`, `x-aisc-reference` and `x-aisc-prose`", plus one sentence: "`x-aisc-prose` is true on a string
  option that holds prose written for one project (dropped from presets unless texts are kept) and false on a name,
  id or other identifier." No validation change (`validate_declaration` ignores `x-aisc-*`).
- `i18n.py` unchanged (DV2-4).

Tests green: `test_p2_prose.py` 2. Command: `cd ~/aisc-report-plugin-interface && uv run --extra dev pytest -q`
(expect 139 passed). Commit: "Common option commentary is marked x-aisc-prose, a schema annotation for prose written
for one project; the annotation is documented with the others (R2-D3.7.1)".

## Group 2: the renderer (aisc-report-generator, dev)

### 2.1 English only (R2-D1.1 to R2-D1.6, R2-C.1)
- Delete `report_renderer/i18n/fr.json` (`git rm`).
- `report_renderer/languages.py`: new docstring (English only; `en.json` may hold singular forms). Drop `_folders`
  and the `os` import. `language_files(env=None) -> {"en": read_language_file(BUILTIN_DIR / "en.json")}` (DV12-5).
  `ENGLISH` stays as the fallback when the file is unreadable (log a warning). `languages(env=None)` returns
  `[{"code": "en", "name": "English"}]`. `language_file(code, env=None)` and `translator(code, env=None)` ignore
  `code` and return the English file / `(make_translator(lf), lf)`.
- `report_renderer/context.py` `context_for(...)`: keep the `language` parameter (callers and tests pass it) but set
  `language = "en"` internally; `t, messages = languages.translator("en")`; `ReportInfo(language="en", ...)`;
  `translate_for(package)` returns `make_translator(package_language_file(package, "en"), messages)` (package
  `en.json` first, then the renderer's; `package_language_file` returns None when the package has none);
  `BlockContext(language="en", ...)`.
- `report_renderer/document.py` `render()`: delete the "not an offered language" check (the schema pattern still
  refuses `"French"` at `/language`); pass `language="en"` to `context_for`, to the template (`<html lang="en">`)
  and to `html_to_docx` (core property `en`). The fingerprint stays over the snapshot as received (R2-D1.4).
- `report_service.py`: no change (health and `/v1/languages` read `languages.languages()`).
- `report_renderer/i18n/en.json`: `_meta` unchanged (no `plural_one`), `messages` = the nine `"<msgid>|one"` entries
  of R2-D3.4.2, spelled exactly as in `SINGULARS` of `tests/test_p2_english.py`.

### 2.2 Lone surrogate in an instance id (R2-D3.1)
`report_renderer/snapshot.py`: `SURROGATE_MESSAGE = "holds a lone surrogate"`; `_surrogate_problem` uses it;
`_instance_id` returns `_printable(iid)` for a string id; the duplicate-id problem uses `_printable(iid)` for its
`instance_id` too (P4). No service change: `InvalidSnapshot` already maps to 422 and the answer now encodes.

### 2.3 Bad link addresses in Word (R2-D3.2)
`report_renderer/docx.py` `_Writer.inline`, the `a` branch: when `_NOT_XML.search(href)` the link text goes through
`self.run(p, child.text_content(), fmt)` (a normal run); else `self.hyperlink(...)` inside `try/except ValueError`,
falling back to the same run. Check before `relate_to`, so no relationship with a bad target is ever added (the
relationships part must stay valid XML). Clean addresses keep their hyperlink.

### 2.4 Placeholder left out (R2-D3.8.1)
- `blocks/free_text.py`: `PLACEHOLDER = "Write this section."` and `is_placeholder(text) -> bool` (P2).
- `document._render_block`: when `type_id == "free_text"`, the class exists, the options are valid and
  `is_placeholder(options.get("text"))`, return the section dict with `omit=True`, `status="empty"`,
  `notices=[t("Not written yet: left out of the report.")]`, `html=Markup("")`, no commentary. Every other section
  gets `omit=False`. The commentary rule becomes: printed only when it is a string, `strip()` is non-empty and it is
  not the placeholder.
- `document.render`: `sections` keeps every block (for `block_statuses`, same order as the snapshot);
  `shown = [s for s in sections if not s["omit"]]` feeds `has_cover`, `structure.plan`, the feature set and the
  template. So numbering, chapter grouping, the TOC and `toc="auto"` (more than 3 sections) behave as if the block
  were absent; PDF and DOCX follow from the HTML.
- `blocks/chapter.py` `ChapterBlock.render`: an intro that is the placeholder is treated as empty (`html=""`).

### 2.5 Built-in prose annotations (R2-D3.7.2)
- `blocks/free_text.py` `text` and `blocks/chapter.py` `intro`: `"x-aisc-prose": True`.
- `objective_filters.py` `REQUIREMENTS_PROPERTY` array branch `items`: `"x-aisc-prose": False` (used by
  `control_objectives` and `summary_coverage` via deepcopy).
- `blocks/test_results.py` `tools` array branch `items`: `"x-aisc-prose": False`.
- `blocks/chart.py` `dimension`: `"x-aisc-prose": False`.
- `cover.report_title` and `cover.subtitle` stay unannotated. Commentary comes from the interface (Group 1).

### 2.6 Tests that turn green in group 2
All 59 generator failures except 2 that need Group 3: `test_p2_fixes.py::test_r2_d2_5_the_promptfoo_key_figure_tile_is_labelled_pass`
(promptfoo label) and `test_p2_english.py::test_r2_d1_5_translate_for_uses_the_package_en_json_then_the_renderer`
(LangBiTe `en.json`). Expected after group 2: 640 total, 638 passed, 2 failed. The goldens (`test_compat_golden.py`)
must pass unchanged; `test_r2_c_3_*` proves the one singular change inside the Test results section.

Command: `cd ~/aisc-report-generator && uv run --extra dev pytest -q` (about 2 minutes, one bed).

### 2.7 Commits (generator, dev), one per step, in this order
1. "Reports are English only: fr.json is gone, only the built-in en.json is read, any language a snapshot names
   renders English with lang en and the decimal point (R2-D1.1 to R2-D1.5, R2-C.1)"
2. "English singular forms: en.json gives the singular of nine counted messages, so one observation, one evaluation
   and one byte read correctly (R2-D3.4.1, R2-D3.4.2, R2-C.3)"
3. "A lone surrogate in a block's instance id is a 422 problem whose instance id is shown as a backslash escape, so
   the answer can always be encoded (R2-D3.1)"
4. "A link whose address holds a character Word cannot store is written as plain text instead of failing the export
   (R2-D3.2)"
5. "A free text still holding Write this section. is left out of the report with a not-written notice, and such a
   commentary or chapter introduction is not printed (R2-D3.8.1, R2-D3.8.4)"
6. "Built-in options say whether they are prose or identifiers with x-aisc-prose (R2-D3.7.2)"

## Group 3: the tool packages, then the generator's last two tests

### 3.1 aisc-report-langbite (dev)
- `git rm vera_report_plugin_langbite/i18n/fr.json`; add `vera_report_plugin_langbite/i18n/en.json`:
  `{"_meta": {"code": "en", "name": "English", "decimal_separator": ".", "percent_format": "{value}%"}, "messages":
  {"Overall pass rate: {rate} across {groups} groups|one": "Overall pass rate: {rate} across {groups} group"}}`
  (exactly this one message, R2-D3.4.3).
- `renderer.py`: new constant `CHECK_LABELS = {"Passed": "Pass", "Failed": "Fail"}`. Group rows: `"check"` is
  `t(CHECK_LABELS.get(d["check"], d["check"]))` when parsed and non-empty, else `na` (so `Not evaluated`, `Unknown`
  and any other text stay as written). New helper `_run_result(summary, t)` returning the line of R2-D2.3 or None:
  measurement absent: None; `checks_passed(description)` is None or b == 0:
  `t("All tolerance checks: not evaluated ({description})", description=...)`; score 1 (>= 1):
  `t("All tolerance checks: Pass ({count} of {total} passed)", ...)`; else
  `t("All tolerance checks: Fail ({count} of {total} passed)", ...)`. It is computed whenever the section has its own
  measurements, for both `detail` values, and passed to the template as `result_line`.
- `templates/langbite.html.j2`: after the summary paragraph, `{%- if result_line %}<p class="summary">{{ result_line
  }}</p>{%- endif %}` (before the run line); the last header becomes `{{ t("Pass / Fail (LangBiTe tolerance check)")
  }}`. The "Tolerance set in LangBiTe", "Passed", "Failed" and "Pass rate" columns stay.
- `verdict()` stays None; `headline()` unchanged.
- Module docstring: "LangBiTe's own tolerance check is shown as Pass / Fail, as the tool states it; the report
  computes no verdict."

### 3.2 aisc-report-strongreject (dev)
`git rm vera_report_plugin_strongreject/i18n/fr.json`. No code change (R2-D2.6; `translate_for` falls back to the
renderer, no `en.json` needed, DV12-8).

### 3.3 aisc-report-promptfoo (dev)
- `git rm vera_report_plugin_promptfoo/i18n/fr.json`.
- `renderer.py`: `RATE_LABELS = {"pass_rate": "Pass", "fail_rate": "Fail", "refusal_rate": "Refusal rate"}`; table rows
  use `t("Pass")`, `t("Fail")`, `t("Refusal rate")` through the same `label()` helper (so "Pass (higher is
  better)"); the chart name map uses the same labels; chart title unchanged; `headline()` label "Pass". New
  `NOTE = "Pass and Fail are promptfoo's own results: a test passes when all of its assertions pass. The values are
  shares of the tests."`, passed as `pass_fail_note` when `pass_rate` or `fail_rate` has a score; no counts derived.
- `templates/promptfoo.html.j2`: `{%- if pass_fail_note %}<p class="note">{{ pass_fail_note }}</p>{%- endif %}`
  right after the table (before the refusal note).
- Module docstring: "pass_rate and fail_rate are promptfoo's own results and are labelled Pass and Fail."

### 3.4 Tests that turn green
LangBiTe 17 (43 passed), StrongREJECT 2 (26 passed), promptfoo 12 (29 passed), mlareject stays 20 passed. Then the
generator's last 2 (640 passed, 0 failed). The goldens pass unchanged (the LangBiTe cells in `m_v2_live_styled` lie
inside the Test results section, R2-C.3).

Commands:
```
cd ~/aisc-report-langbite     && uv run --extra dev pytest -q
cd ~/aisc-report-strongreject && uv run --extra dev pytest -q
cd ~/aisc-report-promptfoo    && uv run --extra dev pytest -q
cd ~/aisc-report-mlareject    && uv run --extra dev pytest -q
cd ~/aisc-report-generator    && uv run --extra dev pytest -q
```

### 3.5 Commits
- langbite: (1) "The package ships only en.json, with the singular of the summary line, since reports are English
  only (R2-D1.7, R2-D3.4.3)"; (2) "The LangBiTe section shows the tool's own tolerance check as Pass / Fail per group
  and for the run; an empty run is not evaluated, not failed (R2-D2.2, R2-D2.3, R2-D2.10)".
- strongreject: "The package ships no fr.json, since reports are English only (R2-D1.7)".
- promptfoo: (1) "The package ships no fr.json, since reports are English only (R2-D1.7)"; (2) "promptfoo's pass_rate
  and fail_rate are labelled Pass and Fail with a note that they are the tool's own results (R2-D2.5, R2-D2.10)".

## Group 4: the composer (aisc-install, apps/report-composer)

### 4.1 English only, data layer (R2-D1.10 to R2-D1.13, R2-C.1)
- `report_composer/db.py`: `DEFAULT_SETTINGS = {"toc": "auto", "numbering": False, "coverage": []}`. `list_layouts`
  and `get_layout` stop selecting `l.language`. `insert_layout` and `update_layout` stop writing `language` (new rows
  get the column default `'en'`; an existing `'fr'` stays untouched). `_PRESET` stops selecting `language`;
  `insert_preset(conn, *, name, description, toc, numbering, blocks, source_project_id, who, now)` stops writing it
  (the column has no default, so new rows hold NULL).
- `report_composer/settings.py`: `document_settings(body, current) -> dict` (no `languages` parameter); a `language`
  key in the body is ignored; module docstring updated (toc, numbering, coverage).
- `report_composer/api.py`: `layout_view` drops `"language"`. `from .renderer_calls import ...` drops `languages`.
  `_preset_settings(preset) -> dict` returns only `toc` and `numbering` (no notices, no language). `post_layout`,
  `put_layout`, `_draft_preview` call `document_settings(body, base_or_current)`. `duplicate_layout` copies
  `toc`, `numbering`, `coverage` only. `_insert_preset` passes no language. Remove the old `view["details"]` language
  notice.
- `report_composer/reports.py` `snapshot_of`: no `language` key; docstring line 3 updated.
- `report_composer/presets.py`: `Preset` loses `language`; `_preset_of`, `from_file`, `from_layout` and
  `export_doc` no longer read or write it (file keys: format, version, name, description, toc, numbering, blocks);
  module docstring updated. The four `presets/*.json` files drop `"language": "en"`.
- `report_composer/renderer_calls.py`: delete `languages()` and `ENGLISH_ONLY`. `renderer_client.py`: delete
  `HttpRendererClient.languages`.
- `report_composer/pages.py`: stop importing and passing `languages`.

### 4.2 English only, screens and script (R2-D1.9)
- `templates/editor.html.j2`: delete the Language `<label>` (line 25).
- `static/composer.js`: `editorState()` drops the language pick; no other occurrence of the substring may remain.

### 4.3 Imported presets lose references, with notices (R2-D3.6)
- `presets.py`: new `reset_references(blocks, block_types) -> (blocks, changed)` where, for each block with a known
  type, the options become `_without_references(options, t)` (file options only, defaults not merged, as the file is
  stored) and `changed` lists `(i, option, label)` for every reference option present in the file whose value differs
  from what is stored; `label` is the schema property's `title`, else the option name. New
  `reference_notices(changed, where) -> list[dict]` building
  `{"pointer": f"/blocks/{i}/{option}", "message": f"The {label} of block {i + 1} pointed at {where}; it was reset to
  its default."}` with `where` = "data of another project or platform" (import) or "data that is not in this project"
  (layout from a file).
- `from_file(doc, block_types)` returns the preset with the references already reset and keeps the changes on the
  object (`Preset.reset: list`, default empty; not exported, not stored).
- `api.import_preset`: answer `{**presets.summary(p), "notices": reference_notices(p.reset, "data of another project or platform")}`.
- `api.post_layout` with `preset_file`: after insert, `view["notices"] = reference_notices(preset.reset, "data that is
  not in this project")` (DV12-7). Built-in and saved presets: unchanged, no key.
- `static/composer.js`, layouts page, `import-preset` branch: when `res.data.notices` is non-empty, keep their
  messages for the next page (`sessionStorage`, key `rc-notices`, every access in `try/catch`) before
  `location.href = ...`; on the editor page load, read and remove the key and show the joined messages with
  `say(text, true)` (information style, the region's `ok` class). No logic beyond drawing Python's messages.

### 4.4 Schema-driven prose rule (R2-D3.7.3 to R2-D3.7.5), new `report_composer/prose.py`
Commit B2 first (section 4). Then:
- `PLACEHOLDER = "Write this section."`; `FIXED = {"commentary": False}` plus per type
  `{"free_text": {"text": True}, "chapter": {"intro": False}}` (name: required), used when the renderer does not
  describe the block type (today's fallback).
- `is_string(node)`: `type == "string"` or a list holding `"string"`. `is_prose(node, blocked)`: `x-aisc-prose` true,
  or (not blocked, no `x-aisc-prose`, none of `enum`, `const`, `pattern`, `format`, and no `maxLength <= 300`).
  `blocked` becomes true below any node carrying `x-aisc-prose: false` or `x-aisc-reference`.
- `blank(value, node, *, required, blocked)`: returns the replacement for one value, walking the schema:
  - string leaf that is prose: required (name in parent's `required`, or `minLength >= 1`) gives
    `PLACEHOLDER[:maxLength]`; nullable (type list holds `"null"`, or a sibling `{"type": "null"}` branch of the
    enclosing `oneOf`/`anyOf`) gives None; else "". Non-prose leaf: unchanged.
  - object (`properties`, `additionalProperties` as a schema): a dict value is walked key by key (`required` from
    that node); a non-dict value is left as it is.
  - array: a list value; with `prefixItems` each position uses its own schema, the rest `items`. If the items are
    prose strings, the result is `[]`, or `minItems` placeholders when `minItems > 0`; object items are walked one by
    one.
  - `oneOf` / `anyOf`: the branches the value is valid against (jsonschema `Draft202012Validator(branch).is_valid`)
    are found; the value is replaced only when every matching branch is a prose string leaf (then as a leaf, with
    nullability from a null branch), or walked in the single matching array / object branch; otherwise unchanged.
    `allOf`: walked with the first branch that describes a type.
  - anything that does not fit (wrong shape) is returned unchanged.
- `strip_options(type_id, options, block_type) -> dict`: for a known type, every option present in `options` is
  replaced by `blank(...)` against `options_schema.properties[name]` (`required` from the top schema); titles stay
  because their `maxLength` is 200 and cover title/subtitle because theirs are at most 300. For an unknown type, only
  `FIXED` names present in `options` change (placeholder if required else "").
- `unwritten(type_id, options, block_type) -> list[str]`: top-level option names whose value holds, at any prose leaf
  found by the same walk (or a `FIXED` name for unknown types), a string with `strip() == PLACEHOLDER`, in schema
  order. `LEFT_OUT = {"commentary"} | {("free_text", "text"), ("chapter", "intro")}`.
  `unwritten_hint(type_id, names) -> str | None`: None when `names` is empty; `"Not written yet: this text still
  holds the placeholder and is left out of the report."` when every name is left out by the renderer (commentary of
  any block, `free_text.text`, `chapter.intro`); else `"Not written yet: this text still holds the placeholder."`.
- `presets.from_layout`: replace the `_free_text_options` loop by `prose.strip_options(b["block_type"], options, t)`
  when `keep_text` is false. Delete `KNOWN_FREE_TEXT`, `TITLE_MAX`, `_free_text_options`. `presets.PLACEHOLDER` is
  re-exported from `prose`.

### 4.5 Unwritten hints (R2-D3.8.3)
- `layouts.outline(blocks, block_types=())`: each item gains `unwritten` and `unwritten_hint` from `prose` (block type
  looked up by id; unknown gives the `FIXED` rule). Keys in P5 order.
- `api.outline`: gets the block types with a local helper that returns `[]` on `ApiError` from the renderer
  (DV12-6), then `layouts.outline(blocks, types)`.
- `pages._outline_entry` gains `unwritten_hint`; `editor_page` computes it with `prose.unwritten`/`unwritten_hint`
  from `by_type`.
- `templates/editor.html.j2`: after the empty-chapter hint, `{% if b.unwritten_hint %}<p class="hint"
  data-unwritten>{{ b.unwritten_hint }}</p>{% endif %}`.
- `static/composer.js` `redrawOutline()`: the request sends `options: optionsOf(li)` with each block (DV11-4); on the
  answer, the `[data-unwritten]` hint is added, updated or removed from `o.unwritten_hint`, like the empty-chapter
  hint. `redrawOutline()` is also called after option edits (the debounced path that refreshes the preview), so the
  hint follows edits. Save, Validate and Generate are not changed (a hint, not a problem).

### 4.6 A failed outline request (R2-D3.3)
Commit B1 first (section 4). Then:
- `templates/_ui.html.j2` `message_region`: add `<button type="button" class="small" data-control="message-action"
  hidden></button>` before Close.
- `static/composer.js`: `say(text, ok, action)`: when `action` (`{label, run}`) is given the action button shows its
  label and runs it once; otherwise it is hidden. `const OUTLINE_FAILED = "The chapter outline could not be updated.";`
  In `redrawOutline()`: `if (mine !== outlineAsked) return;` first (older answers still ignored); then if `!res.ok`:
  every `li` of the list gets `data-depth="0"`, every `[data-empty-chapter]` and `[data-unwritten]` hint is removed,
  and `say(OUTLINE_FAILED, false, {label: "Try again", run: redrawOutline})`; on success, if the region shows
  `OUTLINE_FAILED`, clear it with `say("")`, then draw as today.

### 4.7 Commands
```
cd ~/aisc-install/apps/report-composer && uv run --extra dev pytest -q     # about 3 minutes; browser tests need /usr/bin/google-chrome
cd ~/aisc-install && scripts/guard-frozen.sh
```
After Group 4 the composer shows 409 total, 405 passed, 4 failed (the `test_api_reports.py` tests that wait for
`Throwaway.rows()`, Group 5). The composer e2e (`tests/test_e2e_v2.py`) runs the real renderer, so Groups 2 and 3
must be done first.

### 4.8 Commits (aisc-install, feat/unified-modules; only `apps/report-composer/**`)
1. B2 (test data), 2. B1 (by design), then in this order:
3. "The composer has no language choice: no Language control, no languages call, a language sent by an older client
   is ignored, nothing reads or writes the language columns, and snapshots and preset files carry no language
   (R2-D1.9 to R2-D1.13, R2-C.1)"
4. "Imported presets and layouts made from a preset file lose the source's references and the answer names each one
   that was reset (R2-D3.6)"
5. "Keep texts recognises the prose options of any block from its schema: x-aisc-prose, nested objects, arrays,
   nullable strings and oneOf branches (R2-D3.7.3 to R2-D3.7.5)"
6. "The editor flags blocks still holding Write this section., on the page and in the outline answer (R2-D3.8.3)"
7. "When the latest outline request fails, the editor clears the indentation and hints and offers Try again
   (R2-D3.3)"
(B1 goes right before commit 6 if stage 4 prefers the strict "test change just before the code" order; either way
it is its own commit.) Run the guard after each.

## Group 5: `Throwaway.rows()` (aisc-install, scripts; authorised by the user, BRIEF-2 D3.5)

File: `scripts/pipeline_chain/throwaway.py`, method `Throwaway.rows(self, db, sql, role=None)` only.
- Build the same `json_agg` wrapper as today (keep `.replace("\n", " ")` so multi-line queries behave as before).
- Run psql like `psql()` does (same `docker exec -i -e PGPASSWORD=... <name> psql -X -q -v ON_ERROR_STOP=1 -h
  127.0.0.1 -U <role> -d <db>`), adding `-t -A` (tuples only, unaligned) and `-f -` with the SQL on stdin; same
  password rule (`self.password` for the superuser, else the role name).
- Non-zero exit: `AssertionError(f"query failed as {role or SU} on {db}: {stderr.strip()}")` (unchanged text).
- Parse the whole stdout: `json.loads(out) if (out := r.stdout.strip()) else []`. Never look at a footer.
- Signature, docstring intent, every other function unchanged. Do not touch `report_bed.py` or the callers;
  `v2_fakes.scalar_json` may stay (R2-D3.5.6).

Tests green: `scripts/tests/test_throwaway_rows.py` 10 (12 passed), `test_report_grants.py` d6a, r6_5, d13 x2, and
composer `test_api_reports.py` r4_2_5, r3_12, r4_3_5, r7_2_5 (the 8 hidden tests of R2-D3.5.4).

Commands:
```
cd ~/aisc-install && uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider \
    scripts/tests/test_report_stack.py scripts/tests/test_report_grants.py scripts/tests/test_throwaway_rows.py
cd ~/aisc-install/apps/report-composer && uv run --extra dev pytest -q tests/test_api_reports.py
cd ~/aisc-install && uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider \
    scripts/pipeline_chain/test_dashboard_queries.py        # other people's suite: record the result only (R2-D3.5.5)
```
Commit (stage only `scripts/pipeline_chain/throwaway.py`): "Throwaway.rows() reads psql's tuples-only unaligned
output as one JSON value, so it returns the rows for any number of rows and never reads the row-count footer
(R2-D3.5.1)". If a hidden test now fails for a real reason, fix our code (R2-D3.5.4), not the test.

## Group 6: the document correction (R2-D3.9)

File: `docs/superpowers/report-v2-2026-09-24/08-fix-round-2.md`, item 1 row only. Replace the clause "the 5 that
passed are whitespace-like characters that the old folding already removed" in place by the text below, and put
"Corrected in part 2 (2026-09-25):" right before it. Nothing else in 08 changes. Text to use (facts traced in DV12-9):

"Corrected in part 2 (2026-09-25): the 5 that passed were the whole-renderer cases `ff`, `vt` and `us` (whitespace
for Python's `str.split` and `\s`, so the old `_collapse` folding removed them), `nul` (not whitespace: the HTML
parser of `html_to_docx`, `lxml.html.document_fromstring` on libxml2 2.14.6, turns a NUL into U+FFFD, which XML
allows, and markdown-it does the same for the markdown parts), and
`test_fix_r2_1_a_character_reference_in_markdown_free_text_renders_as_docx`, which already passed because
markdown-it turns `&#1;`, `&#x1b;` and `&#xFFFE;` into U+FFFD; it is a guard, not a regression test."

Commit (stage only that file): "08-fix-round-2.md says correctly why 5 of the new Word tests passed before the fix
(R2-D3.9)".

## Group 7: final verification at the end of stage 4

Run every suite after the last commit, in this order, each on its own beds, then the guard. Expected:

| suite | expected |
|---|---|
| aisc-report-plugin-interface | 139 passed, 0 failed |
| aisc-report-langbite | 43 passed |
| aisc-report-strongreject | 26 passed |
| aisc-report-promptfoo | 29 passed |
| aisc-report-mlareject | 20 passed |
| aisc-report-generator (goldens, e2e `tests/test_e2e_v2.py` and `tests/test_e2e.py` included) | 640 passed, 0 failed |
| apps/report-composer (browser tests and e2e `tests/test_e2e_v2.py`, `tests/test_e2e.py` included) | 409 passed, 0 failed |
| scripts stack + grants + throwaway_rows | 94 total: 91 passed, exactly 3 failed: `test_report_stack.py::test_d6_guard_init_files_do_not_mention_report_roles`, `::test_r4_1_2_launcher_card_seven`, `::test_final_guard_frozen_passes` (other people's work, 10-specs-part2 section 4) |
| scripts/pipeline_chain/test_dashboard_queries.py | recorded only; expected 3 passed with the fixed helper (11 section 1) |
| scripts/guard-frozen.sh | the 00-baseline.md lines: G1 FAIL (238 lines), G2 PASS, G3 PASS (hashes), G3 PASS (tests/test_vendored.py), the three G4 FAIL lines, G5 PASS |

Also check and write in stage 4's report (`13-code-report-part2.md`):
- Both e2e green: generator `test_e2e_v2_preview_pdf_and_docx` (snapshot says fr, output English) and composer
  `test_e2e_v2_preset_coverage_draft_pdf_and_docx` (no "Write this section." in PDF and DOCX).
- Goldens untouched: `git -C ~/aisc-report-generator diff fe30ed2 -- tests/golden` prints nothing.
- No stage-2 test weakened: `git diff <stage-2 head>..HEAD -- tests` in each repo shows only B1, B2 and
  nothing else (plus DV12-1, already committed at f5c0caf).
- `grep -rn "language" apps/report-composer/report_composer/static/composer.js` prints nothing;
  `ls ~/aisc-report-*/vera_report_plugin_*/i18n ~/aisc-report-generator/report_renderer/i18n` shows no `fr.json`.
- No `aisc-t-*` container of this run left, no `*:report-v2-test` image, no headless Chrome; nothing pushed
  (`git status -sb` shows no push); live stack start times unchanged (`docker ps --format '{{.Names}} {{.Status}}'`
  for project `aisc` before and after).
- If one of the 3 excluded stack tests changes outcome because of other people's work, record it, do not touch it.

## 8. Questions for the user

None new.
