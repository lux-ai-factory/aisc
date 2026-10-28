# Appendix 4: Collect evidence

Back to [How AISC works](../architecture.md).

## Purpose

Step 4 carries out the assessment and reports on it. People answer the checklists, the tests run on the system, the
results are shown, and the report puts it all together for one version of the AI card.

## Where

Project page, **4. Collect evidence**. The page (`homepage/evidence.html`, on the launcher's port) has an **AI card
version** selector and four columns: Answer checklists, Run tests, Results, Report. Each column's heading opens its
application; under it are tiles.

The version selector decides what the test tiles count, which results are shown and which reports are listed. The
checklist tiles always show the latest answers, and the runs on a local model file are listed whatever the version.

## Answer checklists

**Purpose:** record what people know about the system, question by question.

- One tile per installed checklist shows its latest answers: version, status, how many questions are answered, and a
  readiness percentage. **Open** goes to the controls app (`controls-web`, under `/controls`).
- Each question is scored 1 to 5 and may have a written answer; it counts as answered when it has either. Readiness
  is the mean score scaled from 0% (all 1) to 100% (all 5).
- A set of answers is a draft until closed; reopening it makes a new version. Each can be downloaded as PDF
  (`controls-pdf`).
- Every answer is stamped with the AI card version that was latest when it was given.
- Kept in schema `controls` of the project's database.

## Run tests

**Purpose:** measure the system's behaviour with the installed tests.

- One tile per installed test counts its completed, failed and running (or waiting) runs on the selected version. **Configure**
  and **Run** open the engine's pages (`aisc-webapp`).
- **Configure** holds a test's saved settings. They can be exported to a `.json` file and imported again (an import
  is checked against the test's form).
- **Run** sets up a run:
  - **What is assessed**: the system or one component of the AI card, or a local model file uploaded in the engine's
    Settings, never both. A test that calls the system needs a connection for it (Manage > Components and
    connections).
  - **Helper models**: for each role the test asks for (judge, attacker, grader, embedder or generator), one of the
    project's helper models allowed that role (Manage > Helper models), and the model name it runs.
  - **Datasets and models**: chosen from the project's components of the right type.
  - **The settings**: one of the test's saved configurations.
- `aisc-backend` records the run, stamps it with the latest AI card version, and queues it. `aisc-eval-worker`
  installs the test's package in a fresh environment (from `devpi`, or from its folder for a local one), runs it,
  and sends the measurements and the files the test writes back to `aisc-backend`, which keeps them in schema
  `engine` and in `minio` (bucket `artifacts`).
- When a test fails while it runs, the run is marked Failed: the run's other tests still running are stopped, and
  those not yet started do not start. A package that fails to install fails only its own tests.
- There is no resume. If the worker stops in the middle, the message broker hands each unfinished task (an install,
  or one test) to the worker again, and that task starts over from the beginning.

## Results

**Purpose:** see what the runs showed, per thing assessed.

- One tile per assessed item: the system, each component, and "No target" for runs without one. Items with runs on
  the selected version come first; the others are folded under "Not run yet", or marked when they are no longer in
  the latest AI card.
- A tile opens the Results page: per test, its counts, last run, how the system was reached (protocol and
  connection), the helper models used, and **Open charts** for its dashboard.
- Each test gets a Superset dashboard (`dashboard`, on its own port, 8188 by default) with the charts the plugin
  declares. Its data covers all the project's runs, of every AI card version, including local ones (marked as
  local); its Run filter starts on the test's latest run.
- **Local, not part of the assessment record**: under the Results tiles, the runs on a local model file. They are
  never counted with the AI card's results in the tiles, nor in the report's run and result blocks. A report's
  dashboard chart block shows the chart as Superset draws it, so local runs can appear there.

## Evidence links

An evidence link says that a test or a checklist is evidence for one of the objectives selected in step 2. Links are
kept per AI card version (table `evidence.link` of the project's database):

- Only the latest version's links can change.
- A new link must name an objective of that version's matrix and an installed test (enabled) or checklist.
- The objective's dimension must also be among the item's dimensions, read from the hosted public catalogue, even
  for a project with a private one. A local test that the public catalogue does not list therefore has no dimensions
  and cannot be linked (the dimensions an admin gives a local test are not used here). The rule is skipped when
  either catalogue does not answer.
- A link whose objective leaves the matrix, or whose item is disabled, uninstalled or deleted, is kept and marked
  stale.
- A latest version with no links of its own is offered the still-valid links of the nearest earlier version that has
  any.

Links are set through the platform's API (`PUT /api/projects/{slug}/evidence/links`). No page sets them yet, so the
report's coverage stays empty until something calls that API.

## Report

**Purpose:** turn the project's records for one AI card version into a document.

- The **Report** heading opens the report composer (`report-composer`, under `/report-composer`). The tile under it
  counts the reports of the selected version, and its **Open** downloads the latest.
- A **layout** is an ordered list of blocks, plus a template (the look), an index and numbering. Five layouts are
  built in and read-only (Summary, Management overview, Assessment report, EU AI Act conformity, Technical dossier);
  duplicate one to change it. Layouts move between projects by export and import.
- **Blocks** come in groups: AI card (including Risk classification, where you state the AI Act risk class);
  control objectives and checklists (including Summary and coverage); tests run; results (each bundled test, such as
  LangBiTe or StrongREJECT, has its own renderer, others get a table; dashboard charts; charts); summary; document
  (cover, chapter, free text, appendix); and Other, for blocks a report plugin adds.
- **Your own words:** every block has a commentary, before or after it, and the Free text block takes light
  formatting. A chapter groups the blocks that follow it.
- When generating you choose the AI card version, the format (**PDF or Word**), and optionally a period, other
  versions to include and a version to compare with. `report-renderer` draws it. A Word report also gets a PDF copy
  when the renderer can make one.
- Reports are kept in schema `report_composer` of the project's database, with a snapshot of the data they were made
  from and its checksum.
