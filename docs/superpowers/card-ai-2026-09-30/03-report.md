# Card AI and people terms: report (2026-09-30)

Built from 01-plan.md, subagent-driven (task review after each task, final whole-branch review, one fix wave, scoped re-review). D1-D4 as recommended.

## Commits (local, feat/unified-modules, NOT pushed)
- apps/qualification: 18ebf27 (pre-work: no-VAIR wording) then 7db636c..3b9671e (17 commits)
- apps/report-generator: 1641c5b
- aisc root: submodule pins and these docs NOT committed

## Suites (baseline -> after)
- ontology 322 -> 344 passed
- agents 188 -> 232 passed
- prefill 457 -> 466 passed
- web unit 1591 -> 1626 passed (formUpload.test.tsx flaky under load, pre-existing)
- report-generator 731 -> 732 passed, 14 skipped
- system card renderer 53 -> 55 passed
- db suite not run (no test database); migration 20261001000000_people_terms applied live instead

## Live (compose project aisc, ~/aisc-fresh-2026-09-30)
- migration applied (provider_term, deployer_term exist in the project DB); qualification-ontology/prefill/agents/pdf/web and report-renderer rebuilt
- filler pipeline on the MCAS card, no AI call: 55 nodes found in the real view, 32 long texts to name
- not yet done by a person: new selects in the browser, upload, Refine with AI run, AI names / "check" chips, PDF

## What the final review caught (per-task reviews could not)
- the filler read a `view.nodes` list the real view does not have: names and notes would never have been produced live (fixed, pinned by a real-view fixture with a drift test)
- the ontology service's HTTP model dropped providerTerm/deployerTerm (fixed, HTTP test)
- AI names printed unmarked in the PDF card (fixed: "(AI name)")

## Parked for the user
- control-objectives stores a drafted risk label as short_label, and the report's changes-since block prints it: AI names there are unmarked (other repos)
