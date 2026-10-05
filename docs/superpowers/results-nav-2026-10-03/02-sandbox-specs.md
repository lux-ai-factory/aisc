# The project page: plan, then the AI Assessment Sandbox (2026-10-03)

The user: steps 4, 5 and 6 become one place, the AI Assessment Sandbox; the report is a button on it;
the numbers go; the project page shows two blocks, the three planning steps on top and the sandbox
below, joined by an arrow. The top block's name was left to us: **Plan the assessment** (its steps
decide what is assessed and with which tests and controls, before the sandbox carries it out).

## S1 Project page (homepage/project.html)

- S1.1 A block `#plan-block` titled "Plan the assessment" holds, in order, the Qualify, Set control
  objectives and Identify tests and controls cards with an arrow between each, as today.
- S1.2 No card carries a step number (`.n`), and the number's CSS goes.
- S1.3 Below it, a downward arrow (`.down`), then one full-width card `#sandbox-card`, "AI Assessment
  Sandbox", opening `/evidence.html?project=<slug>`, with the pink accent the last step had.
- S1.4 Steps 5 (Analyse results, the Superset root) and 6 (Compose the report) are gone from the page,
  and so is the report card's entry in the in-project link map. The catalogue still learns where the
  controls app is, now from the sandbox card's `data-controls`.

## S2 The sandbox page (homepage/evidence.html)

- S2.1 Its title is "AI Assessment Sandbox": the `<title>`, the subtitle under the project name (in
  place of "Step 4 · Collect evidence") and the tab title set once the project is known.
- S2.2 A **Reports** button at the top right, level with the project name, opens the project's report
  composer, `http://localhost/report-composer/p/<pid>` (the link the old step 6 card had).

## S3 The results page (homepage/results.html)

- S3.1 Its breadcrumb and back button name the sandbox ("AI Assessment Sandbox · Visualisation",
  "← Sandbox") instead of step 4.

## Out of scope

Other modules' own words that say "step 4, Collect evidence" (the report composer's coverage note,
the control objectives page) are theirs; listed in the report, unchanged here.
