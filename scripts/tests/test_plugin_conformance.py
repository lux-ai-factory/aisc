"""scripts/lib/plugin_conformance.py: what each installed test declares it assesses, and its helper models.

verify-plugins.sh reads the engine's GET /api/v1/plugins/declarations in its own project and checks each
test: one that adopted @assesses must declare a target kind, may not ask a person for its target in its
config form while it declares an AI card target (the platform reaches the target), and every helper role
must be one the interface knows. A test that has not adopted yet is a WARN naming what is missing.
"""
import ast
import importlib.util
import re

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
           "card_needs_connection": True, "adopted": True, "helper_roles": ["judge"], "config_fields": ["rounds"]}
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
                "targetBaseUrl", "modelUnderTest", "aisc_target_model", "llm.target_api_key")
#: a dataset's column roles and other names that only start like one
NOT_TARGET_NAMED = ("target_feature", "target_column", "target_probability_field", "targetFeature",
                    "target_row_limit", "target_calls_at_once", "target_label", "model", "api_key", "base_url",
                    "target", "model_name", "target_models_dir")


def test_asking_for_the_target_in_the_config_while_declaring_card_fails_naming_the_fields():
    for field in TARGET_NAMED:
        [(level, text)] = check(declared(config_fields=["rounds", field]))
        assert level == "FAIL" and field in text, field
    # only a local model file: there is no card target the platform would reach
    assert check(declared(target_kinds=["local_model"], config_fields=["target_model"])) == []


def test_column_roles_and_other_target_words_are_not_the_model_under_test():
    for field in NOT_TARGET_NAMED:
        assert check(declared(config_fields=["rounds", field])) == [], field


def test_the_failure_says_on_its_own_what_to_do():
    [(_, text)] = check(declared(config_fields=["target_model_id"]))
    assert "remove the field" in text and "hide it with an empty default" in text and "platform fills it" in text


def test_a_test_that_has_not_adopted_warns_naming_what_is_missing():
    [(level, text)] = check(declared(adopted=False, target_kinds=[], card_protocols=[], helper_roles=[]))
    assert level == "WARN" and "@assesses" in text and "nothing" in text
    [(level, text)] = check(declared(adopted=False, helper_roles=[]))
    assert level == "WARN" and "@assesses" in text and "older declaration" in text


def test_a_test_that_has_not_adopted_still_fails_on_an_unknown_helper_role():
    levels = sorted(level for level, _ in check(declared(adopted=False, helper_roles=["critic"])))
    assert levels == ["FAIL", "WARN"]


def test_an_engine_whose_declarations_lack_the_new_keys_is_a_warn_not_a_guess():
    old = {k: v for k, v in declared().items() if k not in ("adopted", "helper_roles", "config_fields")}
    [(level, text)] = check(old)
    assert level == "WARN" and "engine" in text


def test_the_known_helper_roles_are_the_interface_s():
    tree = ast.parse(HELPERS.read_text())
    roles = next(ast.literal_eval(node.value) for node in tree.body
                 if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "HELPER_ROLES")
    assert tuple(conformance().HELPER_ROLES) == roles


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
