# Appendix 1: Qualify the AI system

Back to [How AISC works](../architecture.md).

## Purpose

Step 1 writes down what the AI system is: what it is for, who uses it, how it is built, what it is made of and what
can go wrong with it. The default questionnaire follows what Annex IV of the AI Act (points 1 and 2) asks a provider
to document; a project can set up its own questionnaires. The answers become the system's **AI card**, which every
later step reads.

The step decides nothing about the system. In particular it does not determine the AI Act risk class: Annex III
classification is a legal judgement. The form's Application domains field tags the Annex III areas that apply, and
the class is stated by whoever composes the report (step 4, Risk classification block).

## Where

Project page, **1. Qualify the AI system**. The application is `qualification-web` (`apps/qualification`), under
`/qualification` on the engine's port (80 by default).

## What you do

The form has a left menu and shows one part at a time. Which parts and fields appear depends on the questionnaire;
with the default one:

1. **Identification and use**: name, version, provider, provider type, system type and purpose (always there),
   then, as the questionnaire includes them: description, use case, users, deployers (with their type),
   capabilities, application domains, market and locality. The application domains are the Annex III areas, to be
   left empty when none applies.
2. **One part per question group**, named after the group: by default "General description" and "Development and
   design". The questions are shown five to a page; those marked "where applicable" may stay empty.
3. **System components** (always there): one row per component, with its type (VAIR terms first, then AISC's own
   kinds), its role and whether it is built in-house or by a third party.
4. **Risk identification** (when the questionnaire has it): one row per risk, written as a chain: what could go
   wrong, its source, the weakness, the consequence, the kind of harm, who is affected, what is affected, the control
   and the follow-up control. The source, the consequence and both controls have a VAIR term beside the free text;
   the kind of harm and what is affected are chosen from VAIR terms; who is affected is chosen from a list.

To save typing, **upload a document** (.pdf, .docx, .txt, .md or .markdown) describing the system: the prefill reads
it with text rules (no model) and proposes answers. If the form already has answers, you choose whether it fills only
the empty fields or replaces your answers. The file itself is not sent with the form.

Saving opens the card page. It lists the answered parts and shows the **AI card** as a diagram or a list. From there
you can:

- **Let AI suggest additions**: the card agent (an AI assistant) drafts more nodes from your prose and, in a second
  role, critiques its own draft; you review what it proposes. Both roles use the same model. It runs only when you
  press the button, never on save.
- **Correct a node** by hand, with the VAIR vocabularies, and undo your corrections.
- **Download** the card as PDF, JSON or JSON-LD.
- **Update the answers**, which makes the next version.

## What it produces, and where it is kept

- **AI card versions.** Every save makes the next version (v1, v2, ...). Only the latest can change, which database
  triggers enforce; earlier ones are read-only, so a result or report made on v2 keeps meaning what it meant. The
  versions are rows of `project.system` in the project's database. Only the platform writes them: a save asks the
  platform to make the version, and if the platform does not answer, nothing is saved.
- **The answers, components, risks, the agent's additions and your corrections**: schema `qualification` of the
  project's database. The card graph is built from them every time it is read.
- Each component keeps a stable key from one version to the next, so tests on a component can be followed across
  versions.
- Every save also records which of the engine's components (datasets, models) the card's components are, with a
  snapshot of each, so the system page can flag a component that changed in the engine since.

## What later steps take from it

- **Step 2** reads the card of the latest version as JSON-LD and turns each risk chain into a risk to rate.
- **Step 4** offers the system and each of its components as **what is assessed** by a test. A component dropped
  from the latest card is shown as "not in AI card vN".
- **The report** reads the card for its AI card and Risk classification blocks.

## The services behind it

| Service | What it does |
|---|---|
| `qualification-web` | the form and the card pages; it needs the platform (to make versions), `qualification-ontology` and `qualification-pdf` |
| `qualification-prefill` | turns an uploaded document into proposed answers, with text rules only; stores nothing |
| `qualification-agents` | the card agent; it uses the model and key chosen for the project under Manage > AI assistants, or else the stack's own setting |
| `qualification-ontology` | builds the card graph (AIRO, typed with VAIR) from the answers, the agent's additions and your corrections; no card can be built or downloaded without it |
| `qualification-pdf` | renders the card as PDF |
| `qualification-migrate` | brings every project database's `qualification` schema up to date at start, then exits |

The tokens between these services are made by `scripts/secrets.sh`.

## Who may do what

A viewer can read the card and its versions. Saving answers, making a version and running the card agent take the
editor role (or owner, or admin).
