# Amendment round (report run v2, part 2, 2026-09-25)

The user reviewed the run's results (09-final-verify.md) and decided:

D1. **All reports in English.** French is removed: fr.json, the French texts, the language choice in the
composer and the French-specific tests go. The language-file mechanism may stay (English only), but with a
single language no language picker is shown and no language option is stored or sent as a user choice.
Existing layouts and presets that carry `language: "fr"` must still load and render (in English).

D2. **Pass/fail columns are allowed when the tool itself reports them.** The user's words: "the columns can
have pass or fail, this is objective, but it is not a threshold that someone sets." So: wherever a tool's own
output states pass or fail (LangBiTe's tolerance check; promptfoo's assertion results; check StrongREJECT and
mlareject), the report shows it, labelled plainly as Pass / Fail. The report never computes a verdict of its
own against a threshold a user sets (thresholds remain out of scope). Revisit R-V2.12 and the promptfoo and
StrongREJECT renderers accordingly.

D3. **Fix every remaining bug.** From 05-verify.md, 07-reverify.md, 09-final-verify.md and the "left for the
user" lists in 06 and 08:
1. A lone surrogate in a block's instance_id makes the renderer service answer 500, not 422 (snapshot.py:74-79).
2. A character reference inside a link address in the DOCX export (docx.py:127) crashes the export.
3. When the latest outline request fails, the editor keeps the older chapter indentation.
4. English singular forms ("1 evaluations"): allow singular/plural entries in the English language file
   (R-V8.3 changes accordingly).
5. The test-helper defects `Throwaway.rows()` (aisc-install scripts/pipeline_chain/throwaway.py, marked
   DO-NOT-EDIT for earlier pipeline agents: the user has now authorised fixing it) and
   `TestClient.get(..., json=None)`, which hide 13 tests per run. Those 13 tests must then really pass.
6. Imported presets keep another platform's reference ids (evaluation pids, chart ids): on import, references
   that do not exist in the target project reset to their defaults, as the composer already does for invalid
   references, and the user is told.
7. The preset "Keep texts" rule misses prose options of future plugin blocks (no maxLength, nullable, nested):
   make it schema-driven so any block's prose options are recognised.
8. A report generated straight from a built-in preset prints the placeholder "Write this section.": an
   unwritten placeholder is left out of the generated report (preview, PDF, DOCX) and the composer flags the
   block as not written yet.
9. 08-fix-round-2.md's explanation of the 5 tests that passed before the fix is wrong (NUL is not whitespace,
   one Word test was already passing): correct the document.
The pre-existing generator failure test_r2_2_2_tags (contradicts the spec) and the TestClient json= test
defect are bugs too: fix them so the generator suite is fully green.

Other defaults from 01-specs.md section 20 stand as they are (Q2, Q4, Q5, Q6, Q7, Q8, Q10, Q2-1, Q3-2).
No deploy and no push.
