# Rules for every stage (read this first, then PROGRESS.md)

## Goal (the user's words, 2026-09-24)
"1) find how they call llms, 2) extract this mechanism so that I provide one API key and they both
use it, 3) create a page in the manage menu to 3.1) show the available providers, 3.2) securely store
a key for each provider (at least one, optional more than 1), 3.3) for each agentic system indicate
which among the options where the key is available, you want to use."
Then: "keys and choices apply per project. You also need to specify the model. So find a way to
retrieve all available models live."
Pipeline asked for: write specs -> write tests -> write development plan -> code -> test until green.
Each stage is done by a fresh agent. Do not stop until done.

## The two agentic systems ("they both")
- A. Card agent: `apps/qualification/services/agents/` (container `qualification-agents`), builds its
  model in `fill/llm.py::build_llm` via BAF (besser-agentic-framework), env `BAF_LLM_PROVIDER`,
  `BAF_LLM_MODEL`, `BAF_LLM_BASE_URL`, per-provider key env vars (e.g. MISTRAL_API_KEY).
  Note: in `docker-compose.development.yml` this container gets NO provider and NO key today
  (only BAF_LLM_BASE_URL pointing at the LiteLLM sidecar), so it probably cannot reach a model.
- B. Control-objectives risk mapper: `apps/control-objectives/src/aisc_control_objectives/llm.py`
  (a near copy of A's llm.py, same PROVIDERS table), env via CONTROL_OBJECTIVES_LLM_* in compose.
Out of scope: the LiteLLM sidecar `qualification-llm` used by other qualification features, the
catalogue's LLM, the engine's LLM components.

## Confirmed by the user
- Keys and choices are PER PROJECT.
- Page lists the available providers; stores a key per provider (one or more, one per provider);
  for each agentic system, the admin picks a provider among those usable (key stored, or keyless:
  ollama / self-hosted compatible endpoint) AND a model.
- The model list is retrieved LIVE from the provider with the stored key (server side).
- "Securely": a key is write-only (never returned by any API or shown after saving; it may be
  replaced or deleted), encrypted at rest.
- The page is admin-only, like the rest of the Manage menu (homepage/project.html, `#manage`,
  shown only when the caller is a platform admin).

## Decided by the orchestrator (taste calls; keep unless impossible)
- The platform service (`platform/`, Python FastAPI) owns this: storage, encryption, provider catalogue,
  live model listing, and an internal resolve endpoint the two agents call. Storage lives in each
  project's own database (`project_<pid>`), via a new file in `platform/project-template/` (and
  whatever brings existing project databases up to date, following how 0001-0004 are applied).
- Encryption: Fernet with a key from the environment (see how `apps/connectors` vault does it,
  incl. rotation, and how `scripts/secrets.sh` / env.secrets provide secrets). Never log a key.
- One shared LLM-building code path for A and B, fed by the platform's resolved config
  (provider, model, key, base_url). How to share it across the two submodules is the spec's call
  (both already copy the same PROVIDERS table).
- Backwards compatible: a project with no saved choice for a system keeps today's env-based config.
- Keep logic in Python; the page is a thin static page in `homepage/` (the user reads Python, not JS),
  linked from the Manage menu. Follow the existing homepage look and its CSP-safe patterns.
- The agents must know which project they work for; find how each already knows it.

## FROZEN: must not change
- The engine: apps/backend, apps/webapp, apps/eval data model and Sean's code (see
  docs/superpowers/pipeline-2026-09-23/RULES.md "FROZEN"). AIRO files. shared/plugin-manager.

## Safety
- Branch `feat/unified-modules` in every repo (submodules too). Local commits allowed; NEVER push.
- NEVER run `docker compose` up/down/build/restart against the running stack (compose project `aisc`),
  never migrate, write to or drop anything in its live databases, never exec into live containers to
  change them. Reading the live DB or container logs is OK.
- Tests use throwaway databases only (`docker run --rm -d` postgres under a unique name, removed
  afterwards). Platform tests default to the LIVE DB, so always set `PLATFORM_TEST_DATABASE_URL`
  (and each module's equivalent) to the throwaway one. Provider calls in tests hit fake local HTTP
  servers, never the real internet, never real keys.
- `homepage/project.html` has an UNCOMMITTED edit by the user. Never revert it. If you must edit that
  file, edit on top and do NOT commit it (report it instead). Commit other files by explicit path.
- TDD: tests before implementation.
- Prose in docs: no em dashes.
- Record progress in PROGRESS.md at the end of your stage (what you did, files, commits, open items).
