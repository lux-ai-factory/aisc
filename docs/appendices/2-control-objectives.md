# Appendix 2: Set control objectives

Back to [How AISC works](../architecture.md).

## Purpose

Step 2 decides what the system must be checked against. It takes the risks written in the AI card (step 1), has the
assessor rate them, and links each risk to the control objectives that mitigate it. The result, the **risk and
control matrix**, says which objectives the assessment must cover and which of them matter most (the priority objectives).

## Where

Project page, **2. Set control objectives**. The application is `control-objectives` (`apps/control-objectives`),
under `/control-objectives` on the engine's port (80 by default). Its menu has Assessments, Objective catalogue,
Custom objective sets and Objective profiles.

## The objectives

- **The built-in objectives** are O1 to O50, the AI Act control objectives. Each belongs to one of eleven
  trustworthiness dimensions, REQ1 to REQ11, and says whether it is met by a control, a test, or both.
- **A custom objective set** holds objectives a project writes itself, with its own code prefix. It is edited as a
  draft and published as fixed, numbered versions.
- **An objective profile** is a choice of objectives, from the built-in ones and from published sets. It is
  versioned. Two profiles are built in: "Full AI Act" (all 50) and "Fairness and oversight" (10); a first assessment
  starts on the latter, and **Change profile** switches.

## What you do

1. **Assess the latest AI card.** This starts one assessment for the card's latest version, with one risk per risk
   of the card. When the card changes, reading it again keeps the ratings and links of the risks whose text has not
   changed. An older version's assessment is read-only.
2. **Rate the risks.** Give each risk an impact and a likelihood from 1 to 5, and optionally a rationale (up to 1000
   characters). Its level is impact x likelihood: Low 1 to 4, Medium 5 to 9, High 10 to 16, Critical 17 to 25. A risk
   counts as 0 here until both are rated.
3. **Link objectives to risks.** Either by hand, risk by risk, or with **Suggest with AI**: the risk mapper (an AI
   assistant) proposes, for each risk nobody linked by hand, the objectives of the profile that mitigate it. Each
   proposal must quote the risk's chain (the risk, its source, weakness, consequence, impact and controls). Unknown
   or repeated objectives and wrong quotes are sent back, for at most three attempts in all; what still fails is
   dropped. Links made by hand are replaced only if you tick **Also replace objectives I linked by hand**.
4. **Pick the priority objectives.** An objective's priority score is the sum of the levels of the risks linked to it. The
   objectives are ranked by score (voluntary ones last); by default the first seven whose highest risk is High or
   Critical are priority objectives, and a voluntary objective never is by default. You can tick or untick
   **Priority objective** on any objective, or undo your choices.

## What it produces, and where it is kept

Schema `control_objectives` of the project's database: the assessment, the risks and their ratings, the links and
whether a person or the AI made them, the last AI mapping run (earlier mappings are archived when replaced), the priority
choices, the sets and profiles, and the **objective selection**: the objectives of the matrix, which evidence links
and the report work with. The score is computed on every read, never stored.

## What later steps take from it

- **Step 3** filters the catalogue, by default, to tests and checklists tagged with the dimensions of the selected
  objectives.
- **Step 4**: the Evidence map has one row per selected objective, and links it only to tests and checklists that
  carry its dimension.
- **The report** (Control objectives block) shows the links between risks and objectives, optionally with each
  risk's rating, and marks the priority objectives with their priority score.

Step 2 and the report rate a risk the same way: until both its impact and its likelihood are set it is "Not rated",
counts 0 towards any score, and is never given a value it was not given.

## What it needs

The risk mapper needs a model: the one chosen for the project under Manage > AI assistants (an admin's setting), or
else the stack's setting (`CONTROL_OBJECTIVES_LLM_*`; the default is a local Ollama `mistral` model, which needs no
key). Rating and scoring use no model.

## Who may do what

A viewer can read; rating, linking and choosing priority objectives take the editor role (or owner, or admin).
