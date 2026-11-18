# Appendix A — Draft: adapters executing in the eval runner (plugin → adapter → system)

> From `SCRATCH-platform-adapters-discussion.md` Appendix A. Draft of point 1 from an earlier pass.
> Scope here is **execution location only** — how an adapter is *defined*/authored stays in §5.
>
> **Superseded in part by §8/§9.** Read "execution location" below as *the door*: resource access is
> uniformly the loopback door, and data inputs stay on the local file (§9). The earlier notion of
> reaching an adapter in-process is dropped.

**Today (pilot).**
```
plugin ──(openai/aisc/a2a/oip + run key)──▶ platform door ──translate──▶ builtin client ─┐
                                                                       └▶ adapter.call() ─┼─▶ system
adapter is loaded + run by the `platform` service (platform_service/adapters.py)
```

**Proposed (runner-side).**
```
plugin ──(openai/aisc/a2a/oip, local)──▶ adapter runtime (in the eval worker, same run)
                                             └──network (project allowlist)──▶ system
platform: still owns the connection, secrets and allowlist, but issues the run a bound
          endpoint + short-lived secret instead of being the runtime proxy
```

**What stays the same.** The adapter contract from `adapters/README.md`: `PROTOCOL` (name/label/fields/capabilities/base_url/max_concurrent) and `call(connection, input, history, params, open)` returning the answer or raising a coded failure. `connection` still carries `base_url`, `timeout_s`, `settings`, `secrets`; `open()` still enforces the allowed hosts and no redirects.

**What moves.**
- Extract the loader in `platform/platform_service/adapters.py` into a shared runtime package (e.g. `aisc_adapter_runtime`), used by **both** the platform (validation / UI listing) and the worker (execution).
- The worker mounts the install's `adapters/` and loads them, exactly as the platform does today.
- The worker serves a **loopback door inside the run** (bind `127.0.0.1:<port>` for the run) and points the declared `AISC_TARGET_BASE_URL` (or the aisc `ask` env) at it — the same request/response shapes as `routes/facade.py`. The plugin reaches its resource only this way; there is no in-process plugin→adapter path (§9.1).
- The platform's role shrinks from *runtime proxy* to *issuer*: it returns the connection descriptor (endpoint + a short-lived, run-scoped secret + the allowlist rule) to the worker, which holds it for the run and scrubs it the way the platform does now (`connection_facade.scrub_answer`, `scrub_text`).

**Security note (the §2 trade, stated plainly).** The target secret then reaches the run — scoped to the run, short-lived, and redacted from artifacts/messages. That is the same trust level as the plugin, which already runs catalogue code and already receives config + helper secrets on pilot. The win is one fewer network hop and one fewer service that must hold every project's secrets in the hot path.

**Tests that encode today's proxy behaviour — the blast radius of this change.**
- **Platform → move/mirror to the worker:** `platform/tests/test_adapters_calling.py`, `test_adapters_loading.py`, `test_connection_adapter_calls.py`, `test_connection_adapters.py`, `test_connection_facade_translation.py`, `test_connection_facades.py`, `test_facade_ask_params.py`, `test_facade_capacity.py`, `test_facade_tools.py`, `test_run_key_revocation.py`, `test_run_pass_use.py`, `test_run_passes.py`, `test_run_pass_own_project.py`.
- **Plugin interface → keep the contract:** `shared/plugin-interface tests/test_connections.py`, `test_connection_kinds.py`, `test_connection_network.py`, `test_endpoint_client_facade.py`, `test_history_and_tools.py`, `test_system_under_test.py`, `test_assesses.py`, `test_targets.py`.
- **Eval worker → the new host:** `apps/eval tests/test_plugin_environment.py`, `test_run_pass_project.py`, `test_run_context.py`, `test_run_ticket.py`, `test_scrubbed_artifacts.py`, `test_scrubbed_failures.py`, `test_helper_resolution.py`.
- **Secrets → unchanged:** `platform/tests/test_secret_box.py`, `test_encoded_secrets.py`, `test_connection_secret_headers.py`.

**Still open (deliberately out of scope here):** how an adapter is defined/authored — folder vs UI, shipped library vs user-defined (§5).
