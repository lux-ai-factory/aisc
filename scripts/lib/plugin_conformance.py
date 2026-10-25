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
identifier (name, id, url, key, path); a dataset's column roles and run settings end in another word.

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
#: target_row_limit, model_temperature, judge_threshold) end in another word and do not match
TARGET_FIELD = re.compile(r"(^|_)(target_(model|model_id|api_key|key|base_url|url|endpoint|credentials?|provider)"
                          r"(?![a-z0-9_]*_(column|feature|field)s?(_|$))"
                          r"|model_under_test|model_credentials?)(_|$)"
                          r"|(^|_)(model|model_name|model_id|endpoint|endpoint_url|provider|api_key|base_url"
                          r"|credential)s?$"
                          r"|(^|_)(model|llm|provider|judge|attacker|grader|embedder|embeddings?|generator)"
                          r"_(name|id|url|key|path)s?$")
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
