# Appendix 4: Collect evidence

Back to [How AISC works](../architecture.md).

## Purpose

Step 4 carries out the assessment and reports on it. People answer the checklists, the tests run on the system, the
results are shown, and the report puts it all together for one version of the AI card.

## Where

Project page, **4. Collect evidence**. The page (`homepage/evidence.html`) has an **AI card version** selector and
four columns: Answer checklists, Run tests, Results, Report. Below them, a separate section lists runs on a local
model file, which are not part of the assessment record.

The AI card version selector decides what the test counts, the results, the links and the reports refer to. The
checklist tiles always show the latest answers, and local runs are listed whatever the version.

## Answer checklists

**Purpose:** record what people know about the system, question by question.

- One tile per installed checklist shows its latest answers: version, status, how many questions are answered, and a
  readiness percentage. **Open** goes to the controls app (`controls-web`, under `/controls`).
- Each question is scored 1 to 5 and may have a written answer. A question counts as answered when it has either.
  Readiness is the mean score scaled from 0% (all 1) to 100% (all 5).
- A set of answers is a draft until closed; reopening it makes a new version. Each can be downloaded as PDF
  (`controls-pdf`).
- Every answer is stamped with the AI card version that was latest when it was given.
- Kept in schema `controls` of the project's database.

## Run tests

**Purpose:** measure the system's behaviour with the installed tests.

- One tile per installed test counts its completed, failed and running runs on the selected version. **Configure**
  and **Run** open the engine's pages (`aisc-webapp`).
- A run is set up in a form:
  - **What is assessed**: the system or one component of the AI card, or a local model file uploaded in the engine's
    Settings. Never both. A test that calls the system needs a connection for it (Manage > Components and
    connections).
  - **Helper models**: for each role the test asks for (judge, attacker, grader, embedder, generator), one of the
    project's helper models (Manage > Helper models), and the model name it runs.
  - **Datasets and models**: chosen from the project's components of the right type.
  - **The test's own settings**, which can be exported to a `.json` file and imported again.
- `aisc-backend` queues the run and `aisc-eval-worker` carries it out: it installs the test's package from `devpi`,
  runs it, and stores the measurements in schema `engine` and the files the test writes in `minio` (bucket
  `artifacts`). If one test of a run fails, the others of that run are stopped.
- A run interrupted by a restart is started again from the beginning: there is no resume.
- Every run is stamped with the AI card version that was latest when it started.

## Results

**Purpose:** see what the runs showed, per thing assessed.

- One tile per assessed item: the system, each component, and Unassigned for runs without one. Items with runs on
  the selected version come first.
- A tile opens the results page: per test, its counts, last run, how the system was reached (protocol and
  connection), the helper models used, and **Open charts** for its dashboard.
- Each test gets a Superset dashboard (`dashboard`, port 8188) built from the default charts the plugin declares,
  for its latest finished run.
- Runs on a local model file are listed apart and never counted with the AI card's results or put in its reports.

## Evidence links

An evidence link says that a test or a checklist is evidence for one of the objectives selected in step 2. Links are
kept per AI card version (table `evidence.link`):

- Only the latest version's links can change.
- The objective must be in that version's matrix, and the test or checklist installed and enabled.
- The objective's dimension must be among the item's catalogue dimensions (when the catalogue answers).
- A new version with no links of its own is offered the still-valid links of the version before it.

Links are set through the platform's API (`PUT /api/projects/{slug}/evidence/links`); no page sets them yet.

## Report

**Purpose:** turn the project's records for one AI card version into a document.

- The Report tile counts the reports of the selected version and downloads the latest. **Open** goes to the report
  composer (`report-composer`, under `/report-composer`).
- A **layout** is an ordered list of blocks, plus a template (the look), an index and numbering. Five layouts are
  built in and read-only (Summary, Management overview, Assessment report, EU AI Act conformity, Technical dossier);
  duplicate one to change it. Layouts move between projects by export and import.
- **Blocks** come in groups: AI card; control objectives and checklists (including Summary and coverage); test runs;
  results (each bundled test, such as LangBiTe or StrongREJECT, has its own renderer, others get a table); summary;
  and document blocks (cover, chapter, free text, appendix).
- **Your own words:** every block has a commentary, before or after it, and the Free text block takes light
  formatting. Chapters group the blocks that follow.
- When generating you choose the AI card version and the format, **PDF or Word** (a Word report comes with a PDF).
  `report-renderer` draws it.
- Reports are kept in schema `report_composer` of the project's database, with a snapshot of the data they were made
  from and a checksum.
