# Plugin calls and execution location

> From `SCRATCH-platform-adapters-discussion.md` §2, §2A and §6. The argument: a plugin should not have
> to bounce its calls back through the backend, and adapters should run beside the plugin. Related:
> [`06-adapters.md`](06-adapters.md) (the door) and [`02-consolidation.md`](02-consolidation.md) §11.4.

---

## §2. LLM calls from a plugin should not be proxied back to the backend

**My position.** Requiring the eval plugin to bounce its LLM calls back through the platform/backend is **very tight coupling**, and I don't see the problem it solves: plugins should make their own calls and be given the secrets to do it. Adapters are needed, but an adapter should run **in the same place as the plugin** (the eval runner), not on the platform. (How an adapter is *defined* is a separate point — see §5.)

**What master does (evidence).**
- The plugin process inherits the worker env **plus decrypted secrets**: `child_env = os.environ.copy(); child_env.update(build_secret_environment(project_settings + llm_secret_settings))` (`apps/eval aisc_eval/celery_tasks.py:395`).
- The target `llm` AIComponent's key is decrypted and injected (`celery_tasks.py:319-330`), so the plugin calls the model itself.

**What pilot does (evidence).**
- Plugin env is **whitelisted** (`PLUGIN_ENV_NAMES`); the worker's own credentials (broker/Redis, `INTERNAL_API_KEY`, `DJANGO_SECRET_KEY`, registry login) and `PLATFORM_CONNECTIONS_TOKEN` are **withheld** (`apps/eval aisc_eval/celery_tasks.py:110-165`).
- The plugin gets a scoped **`PLATFORM_RUN_PASS`** (default 12 h) and must call the platform's doors; the platform holds the connection secret and forwards.
- The plugin-facing facade is `aisc_plugin_interface.connections` — `EndpointClient.for_input(...)` / `client.ask(...)` (`shared/plugin-interface src/aisc_plugin_interface/connections.py:1-30`).
- **Adapters run on the platform**: `platform/platform_service/adapters.py` loads `adapters/<folder>/adapter.py` and the platform calls `call()` for every request to that connection; "Tests keep calling the platform as always and need no change" (`adapters/README.md`).

**Nuance (be precise).** Declared config secrets and resolved **helper-model** keys *still* go into the plugin env on pilot (`celery_tasks.py:64-104`, `545-572`, `672-673`). The change is specifically that the **target connection's secret** is withheld and reached only via the run pass, and the whole worker env is no longer inherited.

**What I want.**
- Keep plugins able to reach the system under test (and models) directly, with the secrets they need, when the deployment allows it.
- Run adapters **in the eval runner alongside the plugin** (same process group / same trust boundary as the plugin), so the call path is plugin → adapter → system, not plugin → platform → adapter → system.
- Adapter *definition* interface is out of scope here (see §5), but their **execution location** is not.

**The other side will say.** Security: a plugin is catalogue code; giving it the target key means it can exfiltrate it, and the run key scopes/expires and keeps the key in one place; the platform is the only thing that should hold secrets. Rebut: plugins already execute arbitrary code (and already receive config + helper secrets), so proxying the target key is a partial measure; we can scope/rotate the key to the run instead.

**Decision to force:** where adapters execute (platform vs eval runner) and whether target keys reach the plugin.

---

## §2A. Mechanism: how pilot proxies a plugin's call to the target (and the multi-turn gap)

**Path today (pilot), end to end.**
1. The plugin declares its target access, e.g. langbite and strongreject both do:
   `@assesses(card=system_under_test_access(("openai",), env={"AISC_TARGET_BASE_URL": "base_url", "AISC_TARGET_API_KEY": "api_key", "AISC_TARGET_MODEL": "model"}))` (langbite `feat/unified-modules` `plugin.py:103-108`; strongreject `plugin.py:192-193`).
2. At run time the interface's `system_under_test` decorator asks the platform for the connection and an issued **run key**, then sets the declared config fields **and environment variables** to that endpoint + key for the length of the run (`system_under_test.py:150-190`). It also writes a `connection-<name>.json` artifact (never the key).
3. The plugin then makes an ordinary call — langbite an OpenAI `chat.completions.create` (`langbite/llm_services/llm_openai_factory.py`), or any plugin `client.ask()` via `aisc_plugin_interface.connections`.
4. That endpoint is the **platform's door** (`routes/facade.py`): it resolves the connection from the URL, validates the run key, translates the request (`connection_facade.openai_to_core`), and calls the system — the built-in client for `openai/rest/a2a/oip`, or `call_adapter()` → `adapters.call(adapter, …)` for an adapter's kind.
5. The answer is scrubbed and translated back.

So the adapter never sees the plugin: **plugin → platform door → (translation) → adapter → system**. The adapter is loaded and run by the `platform` service.

**Multi-turn / agent — what actually works.**
- The interface carries history and tools: `check_history` accepts OpenAI chat messages, assistant tool calls and tool results, capped (`MAX_HISTORY_MESSAGES`/`MAX_HISTORY_BYTES`); a call may omit `input` when the history ends in tool results, giving a tool loop (`connections.py:205-299`). Both the `aisc/ask` and OpenAI doors take history; `test_history_and_tools.py` and `test_facade_tools.py` encode it.
- An adapter takes a history only if it declares `"history"` in `capabilities`; otherwise a history is refused 400 (`facade.py` → `_history_refused`).
- **The plugins, not the interface, are the weak link.** langbite / strongreject / MLA-BiTe are single-prompt evaluators: one `execute_prompt`/completion per prompt in a flat loop. langbite's `feat/conversation-history` adds a *fixed* history (`resources/histories.json`: faq / rejected applicant / pressure) prepended before the test prompt — enough to speak to a persona / system-prompt chatbot, **not** to hold a conversation.
- Real multi-turn / agent testing needs an agent-style plugin: **agentdojo** (`agent_pipeline.query`, tool loops) or promptfoo (multi-turn / red-team). Neither has a pilot branch yet (local `main` only).
- **Gap to raise:** the pilot can *reach* a bespoke chat system through an adapter, but no shipped evaluator drives a multi-turn conversation, so "test a chatbot / agent with multi-turn passes" is only partly served. This is also the sharpest reason the adapter should run beside the plugin (§2): multi-turn/agent loops are exactly where a per-call hop to the platform hurts.

---

## §6. Specific changes in `pilot` to call out

1. **Plugin interface grew new modules** vs master: `aisc_plugin_interface/{connections,helpers,targets,assesses,system_under_test,model_session}.py` (master had none of these; `shared/plugin-interface` tree diff). The plugin now calls systems through `connections.EndpointClient` with a run pass.
2. **Plugins are now run with a whitelisted env** and a `PLATFORM_RUN_PASS`, instead of inheriting the worker env + secrets (`apps/eval aisc_eval/celery_tasks.py:100-165`). Any plugin that talked to a model/target directly must change. New tests exist for this (`tests/test_plugin_environment.py`, `test_run_pass_project.py`, …).
3. **`AIComponent` still exists in the backend** on pilot (`apps/backend aisc_backend/models/ai_system.py`), while the platform introduces **`connection`/`target`** — the duplication in §4.
4. **The pilot's bespoke case:** the system only exposed a **website chat app, no API**. A plugin's normal "LLM call" had to be translated into the bespoke project resource. pilot solved this with a **platform adapter** (`adapters/<folder>/adapter.py`), because "tests keep calling the platform as always." My view: this translation belongs **at the plugin/adapter layer run by the eval worker**, and this exact case is why we need a supported way for the user to define an adapter.
5. **`build_secret_environment` still runs on pilot** — config secrets and helper-model keys still reach the plugin; it's the *target connection* secret and the worker env that are withheld. Worth saying precisely so the discussion doesn't drift.

---

*See [`06-adapters.md`](06-adapters.md) §8/§9 for where these calls go (the door), and
[`02-consolidation.md`](02-consolidation.md) §11.4 for the platform's loss of its last runtime role.*
