"""The service the dashboard calls: one caller (the dashboard) by its token; a conversation per project; a proposal
validated only by its fingerprint. It holds no credential of a project database (R1)."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from chart_assistant.app import ModelUnavailable, Settings, create_app
from chart_assistant.conversation_store import MemoryStore
from test_loop import CHART, GOOD, StandIn, tool

TOKEN = "dashboard-token"
PID = "0b5446b0-3bcf-4747-9a47-996747111b86"
OTHER = "a796ca53-f5d5-4eb8-9f58-83db0f095577"
DESCRIPTION = {"targets": ["OpenAI back-end"], "metrics": [{"name": "Conversation", "dimensions": {
    "category": {"type": "text", "values": ["AGE"]}}}]}


class Mocks:
    def __init__(self):
        self.made = []

    def runner(self, pid, description):
        self.made.append((pid, json.dumps(description, sort_keys=True)))
        return lambda sql: {"columns": ["category", "series", "value"], "rows": [["Age", "all", 0.5]]}


SETTINGS = Settings(dashboard_token=TOKEN, platform_url="http://platform", platform_token="t",
                    mock_database_url="postgresql://assistant_mock@postgres/postgres")


class KeepsNothing(MemoryStore):
    """A store that remembers nothing: what the service holds in memory is all there is."""
    def save(self, *a):
        pass


def no_model(pid):
    raise ModelUnavailable("no model is chosen for the chart assistant in this project (Manage > Connectivity)")


def client(*script, token=TOKEN, store=None):
    mocks = Mocks()
    app = create_app(Settings(dashboard_token=token, platform_url="http://platform", platform_token="t",
                              mock_database_url="postgresql://assistant_mock@postgres/postgres"),
                     model_for=lambda pid: StandIn(*script), mocks=mocks,
                     store=MemoryStore() if store is None else store)
    return TestClient(app), mocks


def start(c, pid=PID):
    return c.post(f"/v1/projects/{pid}/conversations", json={"description": DESCRIPTION},
                  headers={"X-AISC-Service-Token": TOKEN})


def say(c, cid, text):
    return c.post(f"/v1/conversations/{cid}/messages", json={"text": text}, headers={"X-AISC-Service-Token": TOKEN})


def test_without_the_dashboards_token_nothing_answers():
    c, _ = client()
    assert c.post(f"/v1/projects/{PID}/conversations", json={"description": DESCRIPTION}).status_code == 401
    assert c.post(f"/v1/projects/{PID}/conversations", json={"description": DESCRIPTION},
                  headers={"X-AISC-Service-Token": "wrong"}).status_code == 401


def test_with_no_token_configured_the_service_is_closed():
    c, _ = client(token="")
    assert start(c).status_code == 503


def test_a_conversation_builds_the_projects_mock_from_its_description():
    c, mocks = client()
    r = start(c)
    assert r.status_code == 201 and r.json()["conversation"]
    assert mocks.made == [(PID, json.dumps(DESCRIPTION, sort_keys=True))]


def test_a_request_answers_with_the_proposal_and_its_mock_rows():
    c, _ = client(tool("propose_chart", sql=GOOD, chart=CHART, description="the mean"))
    cid = start(c).json()["conversation"]
    p = say(c, cid, "radar by category").json()["proposal"]
    assert p["sql"] == GOOD and p["chart"] == CHART and p["mock"]["rows"] == [["Age", "all", 0.5]]
    assert p["mock_data"] is True and len(p["fingerprint"]) == 64


def test_validation_returns_exactly_the_proposed_query():
    c, _ = client(tool("propose_chart", sql=GOOD, chart=CHART, description="the mean"))
    cid = start(c).json()["conversation"]
    fp = say(c, cid, "x").json()["proposal"]["fingerprint"]
    v = c.post(f"/v1/conversations/{cid}/validate", json={"fingerprint": fp}, headers={"X-AISC-Service-Token": TOKEN})
    assert v.status_code == 200 and v.json()["sql"] == GOOD and v.json()["project"] == PID


def test_a_fingerprint_no_proposal_has_is_refused():
    c, _ = client(tool("propose_chart", sql=GOOD, chart=CHART, description="d"))
    cid = start(c).json()["conversation"]
    say(c, cid, "x")
    v = c.post(f"/v1/conversations/{cid}/validate", json={"fingerprint": "0" * 64}, headers={"X-AISC-Service-Token": TOKEN})
    assert v.status_code == 409


def test_an_unknown_conversation_id_is_not_found():
    c, _ = client()
    r = say(c, "no-such-conversation", "x")
    assert r.status_code == 404


def test_a_spent_budget_is_said_as_such():
    c, _ = client(*[tool("run_on_mock", sql=GOOD)] * 20)
    cid = start(c).json()["conversation"]
    r = say(c, cid, "x")
    assert r.status_code == 429 and "steps" in r.json()["detail"]


def test_the_service_has_no_setting_that_could_reach_a_project_database():
    names = set(Settings.__dataclass_fields__)
    assert names == {"dashboard_token", "platform_url", "platform_token", "mock_database_url"}
    assert "project_" not in Settings.from_env({"MOCK_DATABASE_URL": "postgresql://assistant_mock@postgres/postgres"}).mock_database_url


def test_a_mock_database_url_naming_a_project_database_is_refused():
    with pytest.raises(ValueError, match="mock"):
        Settings.from_env({"MOCK_DATABASE_URL": "postgresql://dashboard_ro@postgres/project_0b5446b03bcf47479a47996747111b86"})


def test_the_real_model_call_requires_a_tool_so_the_model_cannot_answer_in_free_text(monkeypatch):
    import httpx

    from chart_assistant import app as module

    class Answer:
        def __init__(self, status, body):
            self.status_code, self._body = status, body

        def json(self):
            return self._body

    sent = {}
    monkeypatch.setattr(httpx, "get", lambda *a, **k: Answer(200, {"configured": True, "provider": "openai",
                                                                    "model": "m", "chat_base_url": "http://llm/v1"}))

    def post(url, **kw):
        sent.update(kw["json"])
        return Answer(200, {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": []}}]})
    monkeypatch.setattr(httpx, "post", post)
    settings = module.Settings(dashboard_token="t" * 32, platform_url="http://platform", platform_token="p" * 32,
                               mock_database_url="postgresql://assistant_mock@db/postgres")
    module.platform_model(settings)("pid")([{"role": "user", "content": "x"}], [])
    assert sent["tool_choice"] == "required"


MADE = [{"id": 12, "title": "Mean score by category", "kind": "radar", "sql": GOOD}]


def test_a_removal_is_answered_as_such_with_the_plot_it_names():
    c, _ = client(tool("remove_chart", chart=12))
    cid = start(c).json()["conversation"]
    r = c.post(f"/v1/conversations/{cid}/messages", json={"text": "delete the radar", "charts": MADE},
               headers={"X-AISC-Service-Token": TOKEN})
    assert r.json() == {"remove": [{"chart": 12, "title": "Mean score by category"}]}


def test_a_replacing_proposal_says_what_it_replaces_and_validation_carries_it():
    c, _ = client(tool("propose_chart", sql=GOOD, chart=CHART, description="d", replaces=12))
    cid = start(c).json()["conversation"]
    p = c.post(f"/v1/conversations/{cid}/messages", json={"text": "as bars", "charts": MADE},
               headers={"X-AISC-Service-Token": TOKEN}).json()["proposal"]
    assert p["replaces"] == {"chart": 12, "title": "Mean score by category"}
    v = c.post(f"/v1/conversations/{cid}/validate", json={"fingerprint": p["fingerprint"]},
               headers={"X-AISC-Service-Token": TOKEN}).json()
    assert v["replaces"] == 12


def test_two_proposals_with_the_same_query_are_validated_as_the_one_the_person_clicked():
    c, _ = client(tool("propose_chart", sql=GOOD, chart=CHART, description="bars"),
                  tool("propose_chart", sql=GOOD, chart={**CHART, "kind": "line"}, description="lines"))
    cid = start(c).json()["conversation"]
    first = say(c, cid, "bars").json()["proposal"]
    second = say(c, cid, "as lines").json()["proposal"]
    assert first["fingerprint"] == second["fingerprint"] and first["id"] != second["id"]

    def validate(**body):
        return c.post(f"/v1/conversations/{cid}/validate", json=body, headers={"X-AISC-Service-Token": TOKEN}).json()
    assert validate(fingerprint=second["fingerprint"], proposal=second["id"])["chart"]["kind"] == "line"
    assert validate(fingerprint=first["fingerprint"], proposal=first["id"])["chart"]["kind"] == "radar"
    assert validate(fingerprint=second["fingerprint"])["chart"]["kind"] == "line"      # no number: the latest


class Reply:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


CHOSEN = Reply(200, {"configured": True, "provider": "openai", "model": "m", "chat_base_url": "http://llm/v1"})


def real_model_client():
    from chart_assistant import app as module
    settings = Settings(dashboard_token=TOKEN, platform_url="http://platform", platform_token="p",
                        mock_database_url="postgresql://assistant_mock@postgres/postgres")
    return TestClient(create_app(settings, model_for=module.platform_model(settings), mocks=Mocks(), store=MemoryStore()))


def failing(exc):
    def call(*a, **k):
        raise exc
    return call


@pytest.mark.parametrize("platform", [failing(httpx.ConnectError("refused")), failing(httpx.ReadTimeout("slow")),
                                      lambda *a, **k: Reply(200, ValueError("not JSON")),
                                      lambda *a, **k: Reply(200, ["not", "an", "object"])])
def test_a_platform_that_cannot_be_reached_or_answers_nonsense_means_no_model(monkeypatch, platform):
    monkeypatch.setattr(httpx, "get", platform)
    r = start(real_model_client())
    assert r.status_code == 409


@pytest.mark.parametrize("chat", [failing(httpx.ConnectError("refused")), failing(httpx.ReadTimeout("slow")),
                                  lambda *a, **k: Reply(200, {"error": "no choices"}),
                                  lambda *a, **k: Reply(200, {"choices": []}),
                                  lambda *a, **k: Reply(200, ValueError("not JSON"))])
def test_a_model_that_cannot_be_reached_or_answers_nonsense_is_a_bad_gateway(monkeypatch, chat):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: CHOSEN)
    monkeypatch.setattr(httpx, "post", chat)
    c = real_model_client()
    r = say(c, start(c).json()["conversation"], "radar by category")
    assert r.status_code == 502


def test_two_messages_to_one_conversation_are_answered_one_after_the_other():
    import threading
    import time

    inside, most = [0], [0]
    guard = threading.Lock()

    def model(messages, tools):
        with guard:
            inside[0] += 1
            most[0] = max(most[0], inside[0])
        time.sleep(0.2)
        with guard:
            inside[0] -= 1
        return tool("ask_question", question="Which one?")
    app = create_app(Settings(dashboard_token=TOKEN, platform_url="http://platform", platform_token="t",
                              mock_database_url="postgresql://assistant_mock@postgres/postgres"),
                     model_for=lambda pid: model, mocks=Mocks(), store=MemoryStore())
    c = TestClient(app)
    cid = start(c).json()["conversation"]
    answers = []
    threads = [threading.Thread(target=lambda: answers.append(say(c, cid, "radar").status_code)) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert answers == [200, 200] and most[0] == 1


def test_old_conversations_are_let_go_beyond_the_cap(monkeypatch):
    from chart_assistant import app as module
    monkeypatch.setattr(module, "MAX_CONVERSATIONS", 3)
    c, _ = client(*[tool("ask_question", question="Which one?")] * 10, store=KeepsNothing())
    cids = [start(c).json()["conversation"] for _ in range(3)]
    assert say(c, cids[0], "x").status_code == 200                  # used last: kept
    start(c)
    assert say(c, cids[1], "x").status_code == 404                  # used least recently: let go
    assert say(c, cids[0], "x").status_code == 200 and say(c, cids[2], "x").status_code == 200


def test_conversations_idle_too_long_are_let_go(monkeypatch):
    from chart_assistant import app as module
    now = [1000.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    c, _ = client(*[tool("ask_question", question="Which one?")] * 10)
    old = start(c).json()["conversation"]
    now[0] += module.MAX_IDLE_SECONDS + 1
    fresh = start(c).json()["conversation"]
    assert say(c, old, "x").status_code == 404 and say(c, fresh, "x").status_code == 200


def test_a_started_conversation_tells_the_model_about_the_results_view_and_the_targets():
    model = StandIn(tool("ask_question", question="Which one?"))
    app = create_app(Settings(dashboard_token=TOKEN, platform_url="http://platform", platform_token="t",
                              mock_database_url="postgresql://assistant_mock@postgres/postgres"),
                     model_for=lambda pid: model, mocks=Mocks(), store=MemoryStore())
    c = TestClient(app)
    cid = start(c).json()["conversation"]
    say(c, cid, "anything")
    system_message = model.sent[0][0]["content"]
    assert "## results:" in system_message and "'OpenAI back-end'" in system_message


def test_a_connection_that_fails_names_the_host_only():
    from chart_assistant.app import explain
    text = explain(httpx.ConnectError("Temporary failure in name resolution"), "https://user:secret@api.example.com/v1")
    assert text == ("the model's address api.example.com could not be reached (ConnectError): "
                    "check the network of the chart assistant")
    assert "secret" not in text


def test_a_model_that_is_slow_says_so():
    from chart_assistant.app import explain
    assert explain(httpx.ReadTimeout("t"), "https://api.example.com/v1") == \
        "the model at api.example.com did not answer within 120 seconds"


def test_anything_else_keeps_the_kind_of_error():
    from chart_assistant.app import explain
    assert explain(KeyError("choices"), "https://api.example.com/v1") == \
        "the model at api.example.com gave no usable answer (KeyError)"


def test_through_the_service_a_key_the_project_does_not_have_goes_back_to_the_model():
    bad = "SELECT dimensions->>'model' AS category, 'a' AS series, avg(score) AS value FROM results GROUP BY 1"
    model = StandIn(tool("propose_chart", sql=bad, chart=CHART, description="d"),
                    tool("ask_question", question="Which grouping?"))
    app = create_app(Settings(dashboard_token=TOKEN, platform_url="http://platform", platform_token="t",
                              mock_database_url="postgresql://assistant_mock@postgres/postgres"),
                     model_for=lambda pid: model, mocks=Mocks(), store=MemoryStore())
    c = TestClient(app)
    cid = start(c).json()["conversation"]
    assert say(c, cid, "by model").json() == {"question": "Which grouping?"}
    refusal = model.sent[1][-1]["content"]
    assert refusal.startswith("Refused:") and "'model'" in refusal and "The keys are: category" in refusal


def test_a_model_call_that_cannot_connect_says_which_host(monkeypatch):
    from chart_assistant.app import ModelUnavailable, platform_model

    class Answer:
        status_code = 200

        def json(self):
            return {"configured": True, "provider": "compatible", "model": "m", "base_url": "https://api.example.com/v1",
                    "api_key": "k"}

    def refuse(*args, **kwargs):
        raise httpx.ConnectError("Temporary failure in name resolution")
    monkeypatch.setattr("chart_assistant.app.httpx.get", lambda *a, **k: Answer())
    monkeypatch.setattr("chart_assistant.app.httpx.post", refuse)
    call = platform_model(Settings(dashboard_token=TOKEN, platform_url="http://platform", platform_token="t",
                                   mock_database_url="postgresql://assistant_mock@postgres/postgres"))(PID)
    with pytest.raises(ModelUnavailable, match="the model's address api.example.com could not be reached"):
        call([], [])


def test_a_validated_proposal_says_which_plot_it_belongs_beside():
    c, _ = client(tool("propose_chart", sql=GOOD, chart=CHART, description="the mean", near=7))
    cid = start(c).json()["conversation"]
    p = c.post(f"/v1/conversations/{cid}/messages", json={"text": "x", "charts": [{"id": 7, "title": "t", "kind": "bar"}]},
               headers={"X-AISC-Service-Token": TOKEN}).json()["proposal"]
    assert p["near"] == 7
    v = c.post(f"/v1/conversations/{cid}/validate", json={"fingerprint": p["fingerprint"]},
               headers={"X-AISC-Service-Token": TOKEN})
    assert v.json()["near"] == 7


def _system_and_refusal(script):
    model = StandIn(*script)
    app = create_app(Settings(dashboard_token=TOKEN, platform_url="http://platform", platform_token="t",
                              mock_database_url="postgresql://assistant_mock@postgres/postgres"),
                     model_for=lambda pid: model, mocks=Mocks(), store=MemoryStore())
    c = TestClient(app)
    cid = start(c).json()["conversation"]
    say(c, cid, "anything")
    return model.sent[0][0]["content"], (model.sent[1][-1]["content"] if len(model.sent) > 1 else "")


def test_a_project_with_conversation_results_is_offered_the_conversations_view_only():
    system_message, _ = _system_and_refusal([tool("ask_question", question="Which?")])
    assert "## conversations:" in system_message and "## jailbreak_attempts:" not in system_message


def test_a_query_on_a_view_the_project_does_not_have_is_refused():
    sql = "SELECT category, 'a' AS series, AVG(worked) AS value FROM jailbreak_attempts GROUP BY 1"
    _, refusal = _system_and_refusal([tool("propose_chart", sql=sql, chart=CHART, description="d"),
                                      tool("ask_question", question="Which?")])
    assert "table jailbreak_attempts is not one the assistant may read" in refusal


def test_a_conversation_goes_on_in_a_service_that_was_restarted():
    store = MemoryStore()
    first, _ = client(tool("propose_chart", sql=GOOD, chart=CHART, description="d"), store=store)
    cid = start(first).json()["conversation"]
    proposal = say(first, cid, "mean by category").json()["proposal"]
    second, _ = client(tool("ask_question", question="Which runs?"), store=store)        # a new service, same store
    assert say(second, cid, "and by run").json() == {"question": "Which runs?"}
    validated = second.post(f"/v1/conversations/{cid}/validate", json={"fingerprint": proposal["fingerprint"]},
                            headers={"X-AISC-Service-Token": TOKEN})
    assert validated.status_code == 200 and validated.json()["sql"] == proposal["sql"]


def test_a_proposal_made_before_the_restart_is_validated_after_it_without_a_message():
    store = MemoryStore()
    first, _ = client(tool("propose_chart", sql=GOOD, chart=CHART, description="d"), store=store)
    cid = start(first).json()["conversation"]
    proposal = say(first, cid, "mean by category").json()["proposal"]
    second, _ = client(store=store)
    validated = second.post(f"/v1/conversations/{cid}/validate",
                            json={"fingerprint": proposal["fingerprint"], "proposal": proposal["id"]},
                            headers={"X-AISC-Service-Token": TOKEN})
    assert validated.status_code == 200 and validated.json()["project"] == PID


def test_a_restored_conversation_whose_project_has_no_model_any_more_says_so():
    store = MemoryStore()
    first, _ = client(tool("ask_question", question="Which?"), store=store)
    cid = start(first).json()["conversation"]
    app = create_app(SETTINGS, model_for=no_model, mocks=Mocks(), store=store)
    answer = TestClient(app).post(f"/v1/conversations/{cid}/messages", json={"text": "x"},
                                  headers={"X-AISC-Service-Token": TOKEN})
    assert answer.status_code == 409 and "no model is chosen" in answer.json()["detail"]


def test_a_conversation_the_store_does_not_have_either_is_not_found():
    second, _ = client(store=MemoryStore())
    assert say(second, "never-started", "x").status_code == 404


def test_a_conversation_let_go_from_memory_beyond_the_cap_comes_back_from_the_store(monkeypatch):
    from chart_assistant import app as module
    monkeypatch.setattr(module, "MAX_CONVERSATIONS", 1)
    c, _ = client(*[tool("ask_question", question="Which one?")] * 10)
    first = start(c).json()["conversation"]
    start(c)
    assert say(c, first, "x").json() == {"question": "Which one?"}


def test_a_store_that_fails_does_not_stop_a_conversation(caplog):
    class Broken(MemoryStore):
        def save(self, *a):
            raise OSError("down")

        def load(self, *a):
            raise OSError("down")

        def drop_idle(self, *a):
            raise OSError("down")
    c, _ = client(*[tool("ask_question", question="Which?")] * 3, store=Broken())
    cid = start(c).json()["conversation"]
    assert say(c, cid, "x").json() == {"question": "Which?"} and say(c, cid, "y").json() == {"question": "Which?"}
    start(c)
    assert say(c, "unknown", "x").status_code == 404
    assert sum("conversation store" in r.getMessage() for r in caplog.records) == 1     # said once in the log


def test_a_stored_conversation_holds_the_description_and_messages_and_no_token():
    store = MemoryStore()
    c, _ = client(tool("propose_chart", sql=GOOD, chart=CHART, description="d"), store=store)
    cid = start(c).json()["conversation"]
    say(c, cid, "x")
    pid, description, state = store.load(cid, 60)
    assert pid == PID and description == DESCRIPTION
    kept = json.dumps(state)
    assert TOKEN not in kept and "api_key" not in kept and state["messages"][0]["role"] == "system"
