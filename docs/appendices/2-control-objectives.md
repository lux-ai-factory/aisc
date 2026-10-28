# Appendix 2: Set control objectives

Back to [How AISC works](../architecture.md).

## Purpose

Step 2 decides what the system must be checked against. It takes the risks written in the AI card (step 1), has the
assessor rate them, and links each risk to the control objectives that mitigate it. The result, the **risk and
control matrix**, says which objectives the assessment must cover and which of them matter most.

## Where

Project page, **2. Set control objectives**. The application is `control-objectives` (`apps/control-objectives`),
under `/control-objectives` on port 80. Its menu has Assessments, Objective catalogue, Custom objective sets and
Objective profiles.

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
   chain of the card. When the card changes, reading it again keeps the ratings and links of risks whose text has not
   changed. An older version's assessment is read-only.
2. **Rate the risks.** Give each risk an impact and a likelihood from 1 to 5, and optionally a rationale. Its level is
   impact x likelihood: Low 1 to 4, Medium 5 to 9, High 10 to 16, Critical 17 to 25. An unrated risk counts as 0.
3. **Link objectives to risks.** Either by hand, risk by risk, or with **Suggest with AI**: the risk mapper (an AI
   assistant) proposes, for every risk nobody mapped by hand, the objectives of the profile that mitigate it, each
   with a quote from the risk's text. Wrong objective ids or quotes are rejected and asked again, up to three times.
   Links made by hand are kept unless you ask to replace them.
4. **Pick the key objectives.** An objective's score is the sum of the levels of the risks linked to it. By default
   the first seven objectives whose highest risk is High or Critical are key; voluntary objectives come last and are
   never key by default. You can switch any objective on or off, or reset.

## What it produces, and where it is kept

Schema `control_objectives` of the project's database: the assessment, the risks and their ratings, the links and
who made them (person or AI), every AI mapping run, the key choices, the sets and profiles, and the **objective
selection**: the objectives of the matrix, which step 4 works with. The score is computed on every read, never
stored.

## What later steps take from it

- **Step 3** filters the catalogue, by default, to tests and checklists tagged with the dimensions of the selected
  objectives.
- **Step 4** links tests and checklists to the selected objectives as evidence.
- **The report** shows the risks, the matrix and the coverage of the objectives.

## What it needs

The risk mapper needs a model: the project's own choice under Manage > AI assistants, or else the stack's setting
(`CONTROL_OBJECTIVES_LLM_*`; the default is a local Ollama `mistral` model, which needs no key). Rating and scoring
use no model.

## Who may do what

A viewer can read; rating, linking and choosing key objectives take the editor role (or owner, or admin).
