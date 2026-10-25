"""scripts/lib/plugin_conformance.py: what each installed test declares it assesses, and its helper models.

verify-plugins.sh reads the engine's GET /api/v1/plugins/declarations in its own project and checks each
test: one that adopted @assesses must declare a target kind, may not ask a person for a model in its config
form (the model under test or a helper model, under any name that selects or keys one), may not hide such a
field with a default of its own, and every helper role must be one the interface knows. A test that has not
adopted yet is a WARN naming what is missing, and a WARN for each of the two model-field findings.
"""
import ast
import importlib.util
import re

import pytest

from conftest import ROOT

LIB = ROOT / "scripts/lib/plugin_conformance.py"
HELPERS = ROOT / "shared/plugin-interface/src/aisc_plugin_interface/helpers.py"


def conformance():
    spec = importlib.util.spec_from_file_location("plugin_conformance", LIB)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def declared(**changes):
    out = {"name": "chat", "package_name": "aisc-chat", "target_kinds": ["card"], "card_protocols": ["openai"],
           "card_needs_connection": True, "adopted": True, "helper_roles": ["judge"], "config_fields": ["rounds"],
           "hidden_config_fields": {}, "config_fields_unreadable": False}
    return {**out, **changes}


def check(decl):
    return conformance().check(decl, decl.get("config_fields", []))


def test_an_adopted_test_with_known_helpers_and_no_target_fields_passes():
    assert check(declared()) == []
    assert check(declared(target_kinds=["local_model"], helper_roles=[])) == []


def test_an_adopted_test_that_declares_no_target_kind_fails():
    [(level, text)] = check(declared(target_kinds=[]))
    assert level == "FAIL" and "no target kind" in text


def test_an_unknown_helper_role_fails_naming_it_and_the_known_ones():
    [(level, text)] = check(declared(helper_roles=["judge", "critic"]))
    assert level == "FAIL" and "critic" in text and "judge, attacker, grader, embedder, generator" in text


#: names that select or key the model under test, in the spellings plugins use (camelCase too)
TARGET_NAMED = ("target_model", "target_model_id", "target.model", "target_api_key", "target.api_key", "target_key",
                "target_base_url", "target_url", "target_endpoint", "target_credential", "target_provider",
                "model_under_test", "Model_Under_Test", "model_credential", "targetModel", "targetApiKey",
                "targetBaseUrl", "modelUnderTest", "aisc_target_model", "llm.target_api_key",
                "targetAPIKey", "targetURL", "TargetBaseURL", "modelUnderTestAPIKey")
#: a dataset's column roles and other names that only start like one
NOT_TARGET_NAMED = ("target_feature", "target_column", "target_probability_field", "targetFeature",
                    "target_row_limit", "target_calls_at_once", "target_label",
                    "target", "target_models_dir",
                    "target_key_column", "target_key_columns", "target_model_feature", "target_url_field",
                    "targetKeyColumn", "targetAPIKeyColumn", "target_endpoint_fields",
                    "target_model_id_column", "target_key_column_name")


def test_asking_for_the_target_in_the_config_while_declaring_card_fails_naming_the_fields():
    for field in TARGET_NAMED:
        [(level, text)] = check(declared(config_fields=["rounds", field]))
        assert level == "FAIL" and field in text, field
    # only a local model file: the model is the ONNX input, so a model field is wrong there too
    assert check(declared(target_kinds=["local_model"], config_fields=["target_model"])) == [
        ("FAIL", m1("target_model"))]


def test_column_roles_and_other_target_words_are_not_the_model_under_test():
    for field in NOT_TARGET_NAMED:
        assert check(declared(config_fields=["rounds", field])) == [], field


def test_the_failure_says_on_its_own_what_to_do():
    [(_, text)] = check(declared(config_fields=["target_model_id"]))
    assert "remove the field" in text and "hide it with an empty default" in text and "platform fills it" in text
    assert "target_model_id" in text and "@helper_model" in text


def test_a_hidden_target_field_with_an_empty_default_passes_the_platform_fills_it():
    assert check(declared(hidden_config_fields={"target_model_id": True, "target_api_key": True})) == []


def test_a_hidden_target_field_with_a_default_of_its_own_fails_as_a_silent_fallback():
    [(level, text)] = check(declared(hidden_config_fields={"target_model_id": False, "target_api_key": True}))
    assert level == "FAIL" and "target_model_id" in text and "target_api_key" not in text
    assert "own model" in text and "empty default" in text
    # a hidden field that is not the model under test may keep its default
    assert check(declared(hidden_config_fields={"page_size": False})) == []


def test_a_config_form_the_engine_could_not_build_warns_that_its_fields_were_not_checked():
    [(level, text)] = check(declared(config_fields=[], config_fields_unreadable=True))
    assert level == "WARN" and "config form" in text and "not checked" in text


def test_a_test_that_has_not_adopted_warns_naming_what_is_missing():
    [(level, text)] = check(declared(adopted=False, target_kinds=[], card_protocols=[], helper_roles=[]))
    assert level == "WARN" and "@assesses" in text and "nothing" in text
    [(level, text)] = check(declared(adopted=False, helper_roles=[]))
    assert level == "WARN" and "@assesses" in text and "older declaration" in text


def test_a_test_that_has_not_adopted_still_fails_on_an_unknown_helper_role():
    levels = sorted(level for level, _ in check(declared(adopted=False, helper_roles=["critic"])))
    assert levels == ["FAIL", "WARN"]


def test_an_engine_whose_declarations_lack_the_new_keys_is_a_warn_not_a_guess():
    old = {k: v for k, v in declared().items()
           if k not in ("adopted", "helper_roles", "config_fields", "hidden_config_fields",
                        "config_fields_unreadable")}
    [(level, text)] = check(old)
    assert level == "WARN" and "engine" in text


def test_the_known_helper_roles_are_the_interface_s():
    tree = ast.parse(HELPERS.read_text())
    roles = next(ast.literal_eval(node.value) for node in tree.body
                 if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "HELPER_ROLES")
    assert tuple(conformance().HELPER_ROLES) == roles



# what each model field finding says, as the check writes it

def m1(fields):
    return (f"asks a person for a model in its config form ({fields}): the platform reaches the model under test"
            " and gives each helper model, so remove the field (a helper model is declared with"
            " @helper_model(role, label, required) and read with self.helper(role)), or, for the model under"
            " test of an AI card, hide it with an empty default so the platform fills it"
            " (@assesses(card=...) fields=)")


def m2(fields):
    return (f"hides {fields} in its config form with a default of its own: a run the platform does not fill"
            " would silently fall back to the plugin's own model; give it an empty default so the platform"
            " fills it, or remove it")


NOTHING = ("WARN", "declares nothing it assesses: no @assesses (card=, local_model=), so the form asks for a"
                   " target as before")
NO_KIND = ("FAIL", "adopted @assesses but declares no target kind: declare card=, local_model= or both")


def unadopted(**changes):
    return declared(**{"adopted": False, "target_kinds": [], "helper_roles": [], **changes})


#: bare selectors and the local model's name
BARE_MODEL_FIELDS = ("model", "model_name", "model_id", "endpoint", "provider", "local_model_name")
#: helper models written the old way, in the config
OLD_HELPER_FIELDS = ("evaluator_llm_model", "evaluator_llm_api_key", "evaluator_llm_provider",
                     "evaluator_llm_base_url", "embeddings_model", "embeddings_api_key", "embeddings_provider",
                     "model_judge_name")
#: other spellings that end with a selector, or with a model word and an identifier
OTHER_MODEL_FIELDS = ("api_key", "base_url", "models", "modelName", "localModelName", "llm.model", "model_url",
                      "model_key", "model_path", "llm_url", "endpoint_url", "credentials", "provider_name",
                      "judgeName", "judge_id", "evaluatorLLMModel", "data_provider")
#: settings and column roles whose last word is not a selector
SETTINGS = ("date_feature", "interest_features", "model_input_columns", "features", "label_mappings", "frequency",
            "window_size", "model_temperature", "use_llm", "evaluator", "evaluator_name", "cache_key")
#: the fields of the twelve catalogue plugins that select no model
CATALOGUE_SETTINGS = ("jailbreaks", "evaluator", "dataset", "max_prompts", "history", "language", "nRetries",
                      "nTemplates", "requirements", "temperature", "tokens", "useLLMEval", "features",
                      "target_probability_field", "target_calls_at_once", "target_row_limit", "mode",
                      "max_concurrency", "promptfoo_email", "purpose", "attack_categories", "strategies",
                      "num_tests_per_category", "custom_adversarial_prompts", "raw_yaml", "answer", "batch_size",
                      "batch_size_judge", "enable_top_p", "enable_top_p_judge", "max_new_tokens",
                      "max_new_tokens_judge", "prompt", "prompt_template", "regex_pattern", "retries_judge",
                      "temperature_judge", "top_p", "top_p_judge", "max_workers", "prompt_language", "attack",
                      "defense", "injection_tasks", "suite", "task_source", "user_tasks", "label_mappings")
#: helper words with a setting after the selector, or a column: the integrator's not-helper list
HELPER_SETTINGS = ("judge_threshold", "judging_rubric", "generator_temperature", "num_attackers",
                   "model_key_column", "generator_seed", "embedding_dim", "grader_threshold", "judge_rubric",
                   "judge_prompt_template", "grader_key_column", "judge_key_points", "generator_models_count",
                   "judge_url_timeout", "judge_model_temperature", "judge_model_max_tokens")
#: helper fields the model rule catches too
HELPER_FIELDS_ALSO_MODEL = ("judge_api_key", "judgeModel", "attacker_base_url", "grader_model_id",
                            "embedder_endpoint", "generator_credentials", "llm.judge_model", "judge_models",
                            "judge_model_id", "judge_provider", "embedding_model_id", "attackerModel", "judgeAPIKey")
#: helper fields only the integrator's helper rule catches
HELPER_ONLY_FIELDS = ("helper_key", "helper_keys", "judge_llm")


@pytest.mark.parametrize("field", BARE_MODEL_FIELDS + OLD_HELPER_FIELDS + OTHER_MODEL_FIELDS + TARGET_NAMED
                         + HELPER_FIELDS_ALSO_MODEL)
def test_a_model_field_asked_of_a_person_fails_in_an_adopted_test(field):
    assert check(declared(config_fields=["rounds", field])) == [("FAIL", m1(field))]


@pytest.mark.parametrize("field", BARE_MODEL_FIELDS + OLD_HELPER_FIELDS)
def test_a_model_field_asked_of_a_person_warns_in_a_test_that_has_not_adopted(field):
    assert check(unadopted(config_fields=["rounds", field])) == [NOTHING, ("WARN", m1(field))]


@pytest.mark.parametrize("field", NOT_TARGET_NAMED + SETTINGS + CATALOGUE_SETTINGS + HELPER_SETTINGS
                         + HELPER_ONLY_FIELDS)
def test_a_setting_or_a_column_role_is_not_a_model_field(field):
    assert check(declared(config_fields=["rounds", field])) == []


@pytest.mark.parametrize("field", ("target_model_id", "target_api_key", "target_base_url", "model", "endpoint",
                                   "judge_api_key", "evaluator_llm_api_key", "embeddings_model",
                                   "model_judge_name"))
def test_a_hidden_model_field_with_an_empty_default_passes(field):
    assert check(declared(hidden_config_fields={field: True})) == []


@pytest.mark.parametrize("field", ("target_model_id", "model_name", "endpoint", "evaluator_llm_model",
                                   "judge_api_key"))
def test_a_hidden_model_field_with_a_default_of_its_own_fails_in_an_adopted_test(field):
    assert check(declared(hidden_config_fields={field: False})) == [("FAIL", m2(field))]


@pytest.mark.parametrize("field", ("endpoint", "model_name"))
def test_a_hidden_model_field_with_a_default_of_its_own_warns_in_a_test_that_has_not_adopted(field):
    assert check(unadopted(hidden_config_fields={field: False})) == [NOTHING, ("WARN", m2(field))]


@pytest.mark.parametrize("field", ("target_feature", "date_feature", "page_size"))
def test_a_hidden_setting_with_a_default_of_its_own_passes(field):
    assert check(declared(hidden_config_fields={field: False})) == []


@pytest.mark.parametrize("field", ("target_model", "model_name"))
def test_a_model_field_fails_in_a_test_that_assesses_only_a_local_model(field):
    assert check(declared(target_kinds=["local_model"], config_fields=["rounds", field])) == [("FAIL", m1(field))]


def test_a_model_field_fails_beside_a_missing_target_kind():
    assert check(declared(target_kinds=[], config_fields=["rounds", "model"])) == [NO_KIND, ("FAIL", m1("model"))]


def test_every_model_field_is_named_in_one_finding_in_the_forms_order():
    assert check(declared(config_fields=["rounds", "model_name", "endpoint"])) == [
        ("FAIL", m1("model_name, endpoint"))]


def test_a_helper_field_only_the_integrator_catches_is_left_out_of_the_finding():
    assert check(declared(config_fields=["rounds", "evaluator_llm_model", "helper_key"])) == [
        ("FAIL", m1("evaluator_llm_model"))]


def test_an_asked_and_a_hidden_model_field_are_two_findings():
    assert check(declared(config_fields=["rounds", "model"], hidden_config_fields={"endpoint": False})) == [
        ("FAIL", m1("model")), ("FAIL", m2("endpoint"))]


def test_a_test_that_has_not_adopted_with_an_unknown_helper_and_a_model_field_fails_once_and_warns_twice():
    levels = sorted(level for level, _ in check(unadopted(config_fields=["rounds", "model"],
                                                          helper_roles=["critic"])))
    assert levels == ["FAIL", "WARN", "WARN"]


#: the declarations the engine builds for the four plugins that adopted @assesses, field names as read
ADOPTED_PLUGINS = {
    "StrongRejectPlugin": declared(
        name="strongreject", target_kinds=["card"], helper_roles=["judge", "attacker"],
        config_fields=["dataset", "evaluator", "jailbreaks", "max_prompts"],
        hidden_config_fields={"target_api_key": True, "target_base_url": True, "target_model_id": True}),
    "LangBiteEvaluationPlugin": declared(
        name="langbite", target_kinds=["card"], helper_roles=["judge"],
        config_fields=["history", "language", "nRetries", "nTemplates", "requirements", "temperature", "tokens",
                       "useLLMEval"],
        hidden_config_fields={}),
    "ClassificationPerformancePlugin": declared(
        name="performance", target_kinds=["card", "local_model"], helper_roles=[],
        config_fields=["features", "target_probability_field"],
        hidden_config_fields={"date_feature": True, "frequency": True, "target_feature": True,
                              "window_size": True}),
    "DataAnomalyPlugin": declared(
        name="data-evaluation", target_kinds=["card"], helper_roles=[],
        config_fields=["features", "target_calls_at_once", "target_row_limit"],
        hidden_config_fields={"date_feature": True, "frequency": True, "target_feature": True,
                              "window_size": True}),
}


@pytest.mark.parametrize("plugin", sorted(ADOPTED_PLUGINS))
def test_the_adopted_catalogue_plugins_conform(plugin):
    assert check(ADOPTED_PLUGINS[plugin]) == []


#: the catalogue plugins that have not adopted and ask for their models, with the model fields named
UNADOPTED_PLUGINS = {
    "PromptfooPlugin": (
        unadopted(config_fields=["attack_categories", "custom_adversarial_prompts", "max_concurrency", "mode",
                                 "num_tests_per_category", "promptfoo_email", "purpose", "raw_yaml", "strategies",
                                 "target_endpoint", "target_model", "target_provider", "temperature"],
                  hidden_config_fields={"target_credential": True}),
        "target_endpoint, target_model, target_provider"),
    "LLMEvaluationPlugin": (
        unadopted(config_fields=["answer", "batch_size", "batch_size_judge", "enable_top_p", "enable_top_p_judge",
                                 "endpoint", "max_new_tokens", "max_new_tokens_judge", "model_judge_name",
                                 "model_name", "prompt", "prompt_template", "regex_pattern", "retries_judge",
                                 "temperature", "temperature_judge", "top_p", "top_p_judge"]),
        "endpoint, model_judge_name, model_name"),
    "RagasPlugin": (
        unadopted(config_fields=["embeddings_model", "embeddings_provider", "evaluator_llm_api_key",
                                 "evaluator_llm_model", "evaluator_llm_provider", "max_workers",
                                 "prompt_language"]),
        "embeddings_model, embeddings_provider, evaluator_llm_api_key, evaluator_llm_model, evaluator_llm_provider"),
    "AgentDojoPlugin": (
        unadopted(config_fields=["attack", "defense", "injection_tasks", "model", "model_credential", "provider",
                                 "suite", "task_source", "user_tasks"]),
        "model, model_credential, provider"),
}


@pytest.mark.parametrize("plugin", sorted(UNADOPTED_PLUGINS))
def test_the_unadopted_catalogue_plugins_that_ask_for_a_model_are_warned_naming_the_fields(plugin):
    declaration, fields = UNADOPTED_PLUGINS[plugin]
    assert check(declaration) == [NOTHING, ("WARN", m1(fields))]


# the shell wiring: the check's Python, its functions only, with a stubbed engine route

def _load(monkeypatch):
    from test_verify_plugins import _answer, _load as load

    monkeypatch.chdir(ROOT)
    return load(_answer(""))


class Engine:
    def __init__(self, status, body):
        self.status, self.body, self.asked = status, body, []

    def call(self, method, path, body=None, project=None, timeout=60):
        self.asked.append((method, path, project))
        return self.status, self.body


def test_the_conformance_group_prints_a_line_per_installed_test(monkeypatch):
    ns, lines = _load(monkeypatch)
    engine = Engine(200, [declared(), declared(name="judge", helper_roles=["critic"]),
                          declared(name="plain", adopted=False, target_kinds=[], helper_roles=[])])
    ns["conformance"](engine, "project-pid")
    assert engine.asked == [("GET", "/api/v1/plugins/declarations", "project-pid")]
    assert [(k, c, t.split()[0]) for k, c, t in lines] == [
        ("PASS", "conformance", "aisc-chat/chat"), ("FAIL", "conformance", "aisc-chat/judge"),
        ("WARN", "conformance", "aisc-chat/plain")]


def test_the_conformance_group_fails_when_the_route_does_not_answer_and_warns_with_no_test(monkeypatch):
    ns, lines = _load(monkeypatch)
    ns["conformance"](Engine(502, "bad gateway"), "project-pid")
    assert [(k, c) for k, c, _ in lines] == [("FAIL", "conformance")] and "502" in lines[0][2]
    ns, lines = _load(monkeypatch)
    ns["conformance"](Engine(200, []), "project-pid")
    assert [(k, c) for k, c, _ in lines] == [("WARN", "conformance")]


def test_the_check_runs_the_conformance_group_and_lists_it_in_its_header():
    text = (ROOT / "scripts/verify-plugins.sh").read_text()
    assert re.search(r"^#\s+conformance\s", text, re.M)
    assert re.search(r"^\s+conformance\(session, pid\)$", text, re.M)
