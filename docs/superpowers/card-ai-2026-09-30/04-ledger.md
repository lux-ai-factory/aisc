# SDD ledger — plan: /home/listuser/aisc-fresh-2026-09-30/aisc/docs/superpowers/card-ai-2026-09-30/01-plan.md

Spec: conversation 2026-09-30 (user: "do 1, 2, 4 ... follow all your recommendations and implement"). D1-D4 = recommended.
Repos: apps/qualification (branch feat/unified-modules, all tasks except 6), apps/report-generator (branch feat/unified-modules, task 6). Pre-work commit 18ebf27 (no-VAIR wording from earlier today).

## Preflight scan
| Pair / task | Produces -> consumes | Found |
|---|---|---|
| T1 -> T2 | VairClass incl AIOperator/AISubject -> parser this.term(...,"AIOperator") | ok |
| T2 -> T3 | form names providerTerm/deployerTerm, isAffected -> selects | ok |
| T2 -> T4 | export providerTerm/deployerTerm/affected -> builder | ok |
| T2 -> T5 | picks keys providerTerm/deployerTerm -> web upload applies picks | GAP: plan only edits Python prefill; web applies a fixed pick list (useDocumentPrefill/prefillChoice/PrefillClient) |
| T4, T7, T10 share build.py | _add_risk / named() / notes loop | sequential, no overlap |
| T7 -> T8 | names {name, of} | ok |
| T8, T11 -> app PUT /extracted | payload keys names, notes | RISK: app route/type OntologyExtracted may drop unknown keys |
| T10 -> T11 | notes {why, quote, of}; guard label/fullLabel vs of=fullText or label | ok |
| T11 -> T12 | record.notes count | fixed in plan before start |
| T9, T12 share NodeChip/NodeEditor/OntologyView | badge / flag text | sequential ok |
| T1..T12 self-consistency | tests vs code per task | T2 message matches /who is affected/; T4 is_term_for arg order to verify; T7 build_graph patch kw to verify; T5 entry-point names to verify (plan says so) |

Ruling: T5 scope includes the web side applying the two new picks (useDocumentPrefill / prefillChoice / PrefillClient types) with a test — the spec says upload fills the form; costs one more file set if the web was already generic.
Ruling: T8 and T11 must check the app's extracted PUT route and OntologyExtracted type and extend them (with a test) if names/notes would be dropped — otherwise the AI output never reaches the card; costs nothing if already pass-through.
Ruling: Task 0 (venvs + baselines) run by the controller, no dispatch — pure environment setup, no code; costs nothing if wrong beyond a rerun.
Ruling: the earlier no-VAIR wording (uncommitted) committed locally as 18ebf27 before Task 1 so task diffs stay clean — local only; costs a squash if the user wanted it elsewhere.

Task 0: complete (controller; venvs made; baselines: ontology 322 passed, agents 188 passed, prefill 457 passed (needs PYTHONPATH=.), web unit 1591 passed; report-generator 731 passed 14 skipped)
Task 1: dispatched (base 18ebf27, sonnet)
Task 1: implementer DONE_WITH_CONCERNS (7db636c). Carry to Task 4: remove the temporary hasAISubject exclusions in test_mapping/test_roundtrip/test_example_mcas/test_build, and add a FORM_MAPPING entry for hasAISubject with its Art/Annex reference (test_mapping requires one).
Task 1: review approved. Ruling: the one Important (test_mapping exclusion would survive silently) is a Task 4 obligation, carried in Task 4's dispatch — costs a stale exclusion if forgotten.
Task 1: minor (deferred): long single-line exclusion comments; test_build failure message; test name "all_nineteen_properties" stale; docstring date 2026-10-01 (kept: matches migration date ordering).
Task 1: complete (commits 18ebf27..7db636c, review clean)
Task 2: dispatched (base 7db636c)
Task 2: implementer DONE_WITH_CONCERNS (d67b53b). db suite not run (no test DB). Carry to Task 3: pass providerTerm/deployerTerm through qualify/[id]/page.tsx to AnsweredForm; fix tsc error at test/unit/vairFormUi.test.tsx:208 (purpose: null, from controller's pre-work commit 18ebf27).
Task 2: review approved.
Task 2: minor (deferred): test title "outside operator/user" stale (QualificationFormParser.test.ts:221); export filters provider/deployer terms but not systemType/purpose (asymmetry); db suite unrun, live migration in Task 13 is the SQL check.
Task 2: complete (commits 7db636c..d67b53b, review clean)
Task 3: dispatched (base d67b53b)
Task 3: implementer DONE (d4fcb41)
Task 3: review approved.
Task 3: minor (deferred): MetadataFieldId cast in VairSelect; hard-coded help text in VairSelect; no test preselecting affected "user" on a saved risk; provider select placement after the row.
Task 3: complete (commits d67b53b..d4fcb41, review clean)
Task 4: dispatched (base d4fcb41)
Task 4: implementer DONE (15ea8f8); mcas example risk0 affected -> NaturalPerson in Python example only
Task 4: review approved; Ruling: fix the MCAS example divergence now (affected in mcas.ts + seed + agreement test) rather than defer — the form already accepts subjects and the examples promise to agree; costs one small round.
Task 4: minor (deferred): long ValueError line; deployerTerm without deployer text silently dropped (no test); citation for hasAISubject copied from hasImpactOnStakeholder.
Task 4: fix round 1/5 dispatched (FIX_BASE 15ea8f8)
Task 4: fix round 1/5 (2 addressed, 0 open; commits 15ea8f8..447f63d)
Task 4: complete (commits d4fcb41..447f63d, review clean)
Task 5: dispatched (base 447f63d)
Task 5: implementer DONE (44f4236); subject match before our ids (whole-value), plural only trailing s
Task 5: review approved. Ruling: VAIR subject matched before our words (whole value only) accepted over the brief's "ours first" — required for "job applicants" -> JobApplicant; MCAS doc resolves identically; costs: a document writing exactly a VAIR group name now gets that group instead of "user".
Task 5: minor (deferred): plural strip only trailing "s" (Families, Vulnerable Persons don't match); no test pinning old-user -> VAIR change; ask-before-replace counts only text fields (pre-existing).
Task 5: complete (commits 447f63d..44f4236, review clean)
Task 6: dispatched (report-generator, base 099f941)
Task 6: implementer DONE (report-generator 1641c5b)
Task 6: complete (report-generator 099f941..1641c5b, review clean)
Checkpoint: Part A (tasks 1-6) done. qualification 18ebf27..44f4236, report-generator 099f941..1641c5b.
Task 7: dispatched (base 44f4236)
Task 7: implementer DONE (bac7a80)
Task 7: review approved.
Task 7: minor (deferred): _name_for returns (None, True) for matching dict with empty name; import order in test_build.py.
Task 7: complete (commits 44f4236..bac7a80, review clean)
Carry to Task 9: "keeps it" path of D4 — NodeEditor must send the label even when unchanged so apply_patch removes nameDrafted.
Task 8: dispatched (base bac7a80)
Task 8: implementer DONE (6bf3109); ExtractedParser extended for {name,of}; old run_fill tests now hit real ontology URL (fallback)
Task 8: review needs fixes (2 Important: unguarded naming errors lose techniques; UTF-16 length vs zod max -> 422). fix round 1/5 dispatched (FIX_BASE 6bf3109), with minor network-stub bundled
Task 8: fix round 1/5 (3 addressed, 0 open; commits 6bf3109..d59d997)
Task 8: minor (deferred): 200-with-non-JSON etc now caught; two except blocks could merge; "uncovered" flag used for a missing name.
Task 8: complete (commits bac7a80..d59d997, review clean)
Task 9: dispatched (base d59d997)
Task 9: implementer DONE (589ebdf)
Task 9: complete (commits d59d997..589ebdf, review clean)
Checkpoint: Part B (tasks 7-9) done.
Task 10: dispatched (base 589ebdf)
Task 10: implementer DONE (3f30b21); concern: ' | ' delimiter splits a why containing ' | ' (plan-mandated encoding)
Task 10: review needs fixes. Ruling: qual:flagNote stores a JSON literal {why, quote} instead of the plan's "<why> | <quote>" — model text and verbatim quotes can contain " | ", so the plan's encoding corrupts both fields; costs nothing outside the ontology service (internal literal).
Task 10: fix round 1/5 dispatched (FIX_BASE 3f30b21), minors bundled (AI-named node test, ValueError on missing keys)
Task 10: fix round 1 implemented (4882f98); note: fix tests not seen RED first
Task 10: fix round 1/5 (3 addressed, 0 open; commits 3f30b21..4882f98)
Task 10: minor (deferred): view.py json.loads has no fallback — the " | " form never shipped (unpushed, undeployed), so no stored graph carries it.
Task 10: complete (commits 589ebdf..4882f98, review clean)
Task 11: dispatched (base 4882f98)
Task 11: implementer DONE (f2fe75e)
Task 11: review approved; ⚠️ resolved by controller: both prompt headings match the test's routing substrings.
Task 11: minor (deferred): unhashable `node` from model raises TypeError -> whole pass lost (guard isinstance str); empty why reported as "quote not in the answers"; MAX_NOTES untested; stray code in test_the_payload_carries...; notes_failed unbounded.
Task 11: complete (commits 4882f98..f2fe75e, review clean)
Task 12: dispatched (base f2fe75e)
Task 12: implementer DONE (dddec5d); fill_one returns notes (agent.py, outside brief); count only while agents service holds the run
Task 12: review approved; ⚠️ resolved: flagNotes declared in OntologyView.ts by Task 10 (commit 3f30b21); record.notes set by Task 11 publish_all.
Task 12: minor (deferred): count from in-memory run result (lost on agents restart, stale after reviewer clears; could count nodes with flagNotes); FLAG_LABEL object lookup; no CSS for flag notes; notes_failed not shown; agent.py notes assertion not seen red.
Task 12: complete (commits f2fe75e..dddec5d, review clean)
Checkpoint: Part C (tasks 10-12) done. Final whole-branch review next, then Task 13 deploy.
Final review: NOT READY (2 Critical: filler reads nonexistent view.nodes; app.py pydantic drops providerTerm/deployerTerm). Ruling: I1 mark AI names in the PDF card with '(AI name)'; CO short_label + report changes_since parked for user (other repos). Fix wave dispatched with C1,C2,I1,M1-M5.
Final fix wave: DONE (3c6bf35 C2, 4638176 C1, 3b9671e I1+M1-M5); agents 232, ontology 344, web 1626, renderer 55
Final fix wave re-review: all 8 addressed, no new Critical/Important.
Final: minor (deferred): FillStatus count stale until page reload after a reviewer patch; renderer/web tests read the agents fixture across service dirs (single-service Docker test run would miss it).
Task 13: started (controller: deploy)
Task 13: complete (migration live, services rebuilt, filler pipeline checked live without AI); browser acceptance left to user
