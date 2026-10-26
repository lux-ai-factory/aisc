"""What an installed test declares it assesses, and its helper models: does it follow the plugin interface?

verify-plugins.sh gives `check` one entry of the engine's GET /api/v1/plugins/declarations (what the
plugin interface reads from the plugin: target_kinds, adopted, helper_roles, config_fields,
hidden_config_fields) and the names of the config fields its form asks a person for. It answers a list
of (level, message), empty when the test conforms:

  FAIL  a test that adopted @assesses declares no target kind
  FAIL  a helper role the interface does not know (HELPER_ROLES of aisc_plugin_interface.helpers)
  FAIL  a test that adopted @assesses asks a person for a model in its config form (a model field,
        TARGET_FIELD: one that selects or keys the model under test or a helper model), whatever it
        declares it assesses: the platform reaches the model under test and gives each helper model
  FAIL  a test that adopted @assesses hides a model field with a default of its own (a silent fallback to
        the plugin's own model); a hidden model field with an empty default passes (the platform fills it)
  WARN  a test that has not adopted @assesses: what it is missing, and the same two model field findings
  WARN  a config form the engine could not build (config_fields_unreadable): its fields are not checked

A name is a model field when its snake_case words hold the old target words (target_model, target_api_key,
model_under_test and the like, not followed by a column, feature or field word), or end with a selector
(model, model_name, model_id, endpoint, endpoint_url, provider, api_key, base_url, credential), or end with
a model word (model, llm, provider, judge, attacker, grader, embedder, embedding(s), generator) and an
identifier (name, id, url, key, path); a dataset's column roles and run settings end in another word. It is
also a model field when it is the model called an LLM (llm, target_llm), a provider's key or token (openai_key,
hf_token, anthropic_api_key), a model's or model server's address (a name that starts with a model or
server word and ends in an address word, with any words between: ollama_url, inference_server_url,
litellm_proxy_url, sut_url, api_base), a deployment, repo, checkpoint, weights, folder or version of a model
(azure_deployment, deployment_name, endpoint_name, hf_repo_id, model_checkpoint, onnx_path, weights_path,
model_dir, model_version), a model file (model_file, model_path), the target by name (target_name,
target_system) or the system under test.

Name rules are never complete. These gaps are left to the integrator's code review of the plugin's form: a
bare or generic token (token, api_token, access_token, hf_access_token), a bare address (url, host), a bare
deployment or engine, a service's api address (dataset_api_url, webhook_api_url), and a helper word alone
(attacker, generator, embedder, evaluator_llm), which the integrator's helper rule catches.

Field names only: the route never sends a value, and nothing here prints one.
"""
import re

#: as aisc_plugin_interface.helpers.HELPER_ROLES (the interface is not installed where the check runs)
HELPER_ROLES = ("judge", "attacker", "grader", "embedder", "generator")
#: config field names that select or key a model (the model under test, or a helper model written the old
#: way), searched on the snake_case name (camelCase split, acronyms too, dots read as underscores). Three
#: rules: the old target words anywhere (target_model_id, targetAPIKey, llm.target_api_key, unless a later
#: word is column, feature or field), a selector at the end (model, model_name, endpoint, provider, api_key,
#: evaluator_llm_model, judgeModel), or a model word and an identifier at the end (model_judge_name,
#: judge_id, model_path). A dataset's column roles and settings (target_feature, target_column,
#: target_row_limit, model_temperature, judge_threshold) end in another word and do not match. Further
#: names that pick a model: llm alone or target_llm (a helper's llm, judge_llm, is the integrator's helper
#: rule; use_llm is a setting), a provider's key or token with the provider word right before it (openai_key,
#: hf_token, groq_api_key; anthropic_max_tokens is a setting), a model's or model server's address
#: (ollama_url, litellm_url, model_uri, target_host, and with words between: inference_server_url,
#: llm_server_url, model_server_host, sut_url; api counts only as the first word, api_base, api_server_url,
#: so a service's dataset_api_url or results_api_base does not match), a model's deployment, repo,
#: checkpoint, weights, folder or version (azure_deployment, deployment_name, endpoint_name, model_repo,
#: hf_repo_id, model_checkpoint, onnx_path, weights_path, model_dir, model_version), a model file, the target
#: by name (target_name, target_system) and the system under test. Gaps left to the integrator's code review:
#: token, api_token, access_token, hf_access_token, url, host, deployment and engine are too generic and do
#: not match. Accepted over-matches, renamed when they occur: a name ending in model that is not a model
#: (threat_model), one ending in provider, endpoint, credential(s), api_key or base_url that keys no model
#: (data_provider), and an address under a model or server word that is not a model's
TARGET_FIELD = re.compile(r"(^|_)(target_(model|model_id|api_key|key|base_url|url|endpoint|credentials?|provider)"
                          r"(?![a-z0-9_]*_(column|feature|field)s?(_|$))"
                          r"|model_under_test|model_credentials?|system_under_test)(_|$)"
                          r"|(^|_)(model|model_name|model_id|endpoint|endpoint_url|provider|api_key|base_url"
                          r"|credential|model_file)s?$"
                          r"|(^|_)(model|llm|provider|judge|attacker|grader|embedder|embeddings?|generator)"
                          r"_(name|id|url|key|path)s?$"
                          r"|^llms?$|(^|_)target_llms?$"
                          r"|(^|_)(openai|anthropic|azure|hf|huggingface|mistral|cohere|google|gemini|groq|together"
                          r"|ollama|litellm|vllm)_(api_)?(key|token)s?$"
                          r"|(^(model|llm|api|ollama|litellm|vllm|openai|inference|target|sut)(_[a-z0-9]+)*"
                          r"|(^|_)(model|llm|ollama|litellm|vllm|openai|inference|target|sut))"
                          r"_(url|uri|base|host|endpoint)s?$"
                          r"|(^|_)(azure_deployment|deployment_name|endpoint_name|model_repo|hf_repo_id"
                          r"|model_checkpoint|onnx_path|weights_path|model_dir|model_version|target_name"
                          r"|target_system)s?$")
#: what the engine adds to each declaration for this check
CHECKED_KEYS = ("adopted", "helper_roles", "config_fields", "hidden_config_fields", "config_fields_unreadable")


def _snake(name):
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", name)    # targetAPIKey: target_API_Key
    return re.sub(r"[^a-z0-9]+", "_", name.lower())


def _target_fields(config_fields):
    """The fields whose name selects or keys a model (TARGET_FIELD), in the order given."""
    return [f for f in config_fields if TARGET_FIELD.search(_snake(f))]


def check(declaration: dict, config_fields: list[str]) -> list[tuple[str, str]]:
    missing = [k for k in CHECKED_KEYS if k not in declaration]
    if missing:
        return [("WARN", f"the engine's declarations do not say {', '.join(missing)}: an engine older than the"
                         " check, so the test is not checked")]
    kinds = list(declaration.get("target_kinds") or [])
    findings = []
    unknown = [r for r in declaration["helper_roles"] if r not in HELPER_ROLES]
    if unknown:
        findings.append(("FAIL", f"declares the helper role {', '.join(unknown)}, which the interface does not know"
                                 f" (known: {', '.join(HELPER_ROLES)})"))
    asked = _target_fields(config_fields)
    if declaration["config_fields_unreadable"]:
        findings.append(("WARN", "the engine could not build its config form, so its config fields were not checked"
                                 " (the engine's log names the error)"))
    # hidden fields the platform fills: {name: whether its default is empty}
    fallbacks = _target_fields([f for f, empty in declaration["hidden_config_fields"].items() if not empty])
    # the same two model field findings: FAIL in a test that adopted @assesses, WARN in one that has not
    model_findings = []
    if asked:
        model_findings.append(("WARN", f"asks a person for a model in its config form ({', '.join(asked)}): the"
                                       " platform reaches the model under test and gives each helper model, so"
                                       " remove the field (a helper model is declared with @helper_model(role,"
                                       " label, required) and read with self.helper(role)), or, for the model"
                                       " under test of an AI card, hide it with an empty default so the platform"
                                       " fills it (@assesses(card=...) fields=)"))
    if fallbacks:
        model_findings.append(("WARN", f"hides {', '.join(fallbacks)} in its config form with a default of its own:"
                                       " a run the platform does not fill would silently fall back to the plugin's"
                                       " own model; give it an empty default so the platform fills it, or remove"
                                       " it"))
    if declaration["adopted"]:
        if not kinds:
            findings.append(("FAIL", "adopted @assesses but declares no target kind: declare card=, local_model="
                                     " or both"))
        findings.extend(("FAIL", message) for _, message in model_findings)
        return findings
    if kinds:
        findings.append(("WARN", "reads as an AI card target through an older declaration: it has not adopted"
                                 " @assesses (card=, local_model=)"))
    else:
        findings.append(("WARN", "declares nothing it assesses: no @assesses (card=, local_model=), so the form"
                                 " asks for a target as before"))
    findings.extend(model_findings)
    return findings
