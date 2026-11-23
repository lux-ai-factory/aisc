# 0006. Qualification agents, objective sets and the document reader

**Status:** accepted
**Invariant:** I8 — no new moving part; the one new dependency (`pypdf`) decided here, and I6 (versioning) and I5 (the domain lives in the model layer) referenced
**Owner:** AISC project owner (qualification/objectives workstream, epic E4)
**Date:** 2026-11-17

## Context

QUAL-01 (#113) is the last E4 port: the pilot's qualification steps (risk mapper, built-in objective
profiles, custom objective sets, document pre-fill, the card agent, the card-component snapshot
against the engine). Four of those need a decision before they can land:

1. **They call a model.** The pilot's "Suggest with AI", the pre-fill and the card agent all speak to
   an OpenAI-compatible chat endpoint. The unified backend already stores a project's *helper* models
   (CON-01, encrypted `ProjectConfig` secret store) and the reporting workstream already talks to
   HTTP services, but there was no shared way to resolve "which model does this feature use".
2. **Reading an uploaded document** (.pdf/.docx/.txt/.md) needs a PDF text extractor; `.docx` is
   already covered by `python-docx`, `.txt`/`.md` need nothing.
3. **Custom objective sets are versioned** (a draft, then fixed numbered versions) which touches I6
   ("every governed change is versioned from one place, and ledgered") — the question is whether they
   version through the existing mechanisms or get a private one.
4. **The card-component snapshot** stores, per card component, which engine component it stood for and
   what that component said at the time, so the card page can flag drift. That is new state.

## Decision

1. **One model-resolution seam, in the backend, that decides and then stops.** A single module
   (`aisc_backend/services/ai_assistant.py`) resolves a feature's model — the project's own helper
   model first (by role), else the stack settings (`CONTROL_OBJECTIVES_LLM_*`, `CARD_AGENT_LLM_*`), else
   a refusal — and makes one OpenAI-compatible chat call. The risk mapper's proposer is now that same
   helper (`services/risk_mapper.resolve_proposer`). **With no model configured the endpoints answer
   `503` and change nothing**: no proposal is ever invented locally to look like a model's answer.
   A helper is the *project's* endpoint, so it is read through CON-01's allowed-hosts door immediately
   before the call (`guard_url`) and refused as `400` when the door closes — the assistants cannot be
   used to reach a machine the project may not reach. The stack setting is the deployment's own
   configuration rather than project input, so it is not put through the project's allowlist.
2. **The features live in the domain, not in the page.** `services/risk_mapper.py`,
   `services/qualification_prefill.py` and `services/card_agent.py` are pure decision functions (the
   risk mapper's own module never touches the database); the routers validate, authorise, audit and
   write, through the **existing** endpoints (a card correction still goes through the node-correction
   path, which rebuilds the card and versions it — no second write path). This keeps I5 and I3.
3. **A document reader with no new service:** `pypdf` reads `.pdf` text in-process. It is the only new
   top-level production dependency; no container, no browser, no external reader. The uploaded file is
   read, its text matched against the questionnaire's own questions with plain rules, and **nothing is
   stored** — the answer is a list of proposals the person accepts field by field.
4. **Objective sets version through their own numbered rows and are ledgered like everything else.**
   `ObjectiveSet` holds the editable draft; `ObjectiveSetVersion` holds each published, immutable
   version (`1..n`); publishing and applying are audited (`log_action`). Applying copies a published
   version into the project's own catalogue rows and selects them in the profile, so the matrix, the
   evidence map and the report read them like any other objective (I5's "domain in the model layer").
5. **The built-in profiles are derived, not hard-coded.** "Full AI Act" is the project's visible
   catalogue; "Fairness and oversight" is the objectives of the catalogue's own macro requirements
   REQ1/REQ5/REQ7. If the catalogue changes, the profiles follow it.
6. **The card-component snapshot is a link row, not a copy of the engine.** `CardComponentLink`
   records the engine component's identity plus a snapshot of what it said when the card was saved,
   and reports `changed`/`missing` by comparing the two on read. It is written on every card save
   (one line in the existing write path).

## Consequences

- **Cost:** one new dependency (`pypdf`), two new tables (`ObjectiveSet`, `ObjectiveSetVersion`) and one
  (`CardComponentLink`), plus a `profile_key` column on `ObjectiveProfile`; migrations `0037`–`0039`.
  No new container, service or port.
- **I8:** no new moving part. The model call is an outbound HTTP call to the endpoint the project
  already declared as a helper (or to the operator's stack setting), and the helper path takes
  CON-01's allowed-hosts door like every other call out. Nothing is added to the deployment.
- **Reversibility:** the two stack settings default to unset, so a deployment that configures nothing
  gets the same behaviour as before with an honest `503` on the three AI features.
- **Not decided here:** the eval/qualification worker boundary (ADR 0003) is untouched — nothing in
  this ADR moves work out of the worker.
