# Appendix 1: Qualify the AI system

Back to [How AISC works](../architecture.md).

## Purpose

Step 1 writes down what the AI system is: what it is for, who uses it, how it is built, what it is made of and what
can go wrong with it. The answers follow what Annex IV (points 1 and 2) of the AI Act asks a provider to document.
They become the system's **AI card**, which every later step reads.

The step decides nothing about the system. In particular it does not determine the AI Act risk class: Annex III
classification is a legal judgement. The questionnaire offers an optional tag field for the Annex III areas that
apply, to be left empty when none does.

## Where

Project page, **1. Qualify the AI system**. The application is `qualification-web` (`apps/qualification`), under
`/qualification` on port 80.

## What you do

The questionnaire has a left menu and shows one part at a time:

1. **Identification and use**: name, version, provider, provider type, system type, purpose, description, use case,
   users, deployers, sector, market and locality.
2. **Annex IV questions**, five to a page. Questions marked "where applicable" may stay empty.
3. **System components**: one row per component (a model, a dataset, a service, an interface...), with its type,
   its role and whether it is built in-house or by a third party. Component types use the VAIR vocabulary first.
4. **Risk identification**: one row per risk, written as a chain: what could go wrong, its source, the weakness it
   exploits, the consequence, the kind of harm, who and what is affected, the control, and the follow-up control.
   Most fields have a VAIR term beside the free text.

To save typing, **upload a document** (.pdf, .docx, .txt or .md) describing the system: the prefill reads it and
proposes answers, and you choose whether it fills only the empty fields or replaces your answers. The file itself is
not stored.

After saving, the card page opens. It lists the answered parts and shows the **AI card** as a diagram or a list.
From there you can:

- **Let AI suggest additions**: the card agent (an AI assistant) drafts more nodes from your prose, a second model
  reviews them, and you review what they propose. It runs only when you press the button, never on save.
- **Correct a node** by hand, with the VAIR vocabularies, and undo your corrections.
- **Download** the card as PDF, JSON or JSON-LD.
- **Update the answers**, which makes the next version.

## What it produces, and where it is kept

- **AI card versions.** Every save makes the next version (v1, v2, ...). Only the latest can change; earlier ones are
  read-only, so a result or report made on v2 keeps meaning what it meant. The versions are rows of `project.system`
  in the project's database; only the platform writes them, and making one takes the editor role.
- **The answers, components, risks and the card graph**: schema `qualification` of the project's database.
- Each component keeps a stable key from one version to the next, so a test run on a component can be followed
  across versions.

## What later steps take from it

- **Step 2** reads the risk chains of the latest card version and turns each into a risk to rate.
- **Step 4** offers the system and each of its components as **what is assessed** by a test. A component dropped from
  the latest card is shown as "not in card vN".
- **The report** reads the card for its AI card blocks.

## The services behind it

| Service | What it does | Needs |
|---|---|---|
| `qualification-web` | the questionnaire and the card pages | the project database |
| `qualification-prefill` | turns an uploaded document into proposed answers, with text rules only (no model) | nothing beyond its token |
| `qualification-agents` | the card agent and its reviewer | a model and key: the project's choice under Manage > AI assistants, or the stack's own setting |
| `qualification-ontology` | builds the card graph (AIRO, typed with VAIR) from the answers; no card can be built without it | nothing beyond its tokens |
| `qualification-pdf` | renders the card as PDF | nothing beyond its token |
| `qualification-migrate` | updates every project database's schema at start, then exits | |

The tokens between these services are made by `scripts/secrets.sh`.

## Who may do what

A viewer can read the card and its versions. Saving answers, making a version and running the card agent take the
editor role (or owner, or admin).
