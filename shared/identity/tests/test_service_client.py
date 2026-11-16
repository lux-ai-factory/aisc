"""One way for a service to call another: aisc_service_client.ServiceClient. A timeout is always given, a redirect is
never followed, only a connection that could not be made is tried again (never an answer), a name that does not
resolve says so, and the request id of the call being served travels on.

No network: httpx's transport is replaced by a function that answers or fails as each test says."""

import importlib
import importlib.util

import httpx
import pytest


def _client_module():
    assert importlib.util.find_spec("aisc_service_client") is not None, \
        "no aisc_service_client module: each service calls the others in its own way"
    return importlib.import_module("aisc_service_client")


@pytest.fixture
def answers(monkeypatch):
    """Each request is handed to the next of `script` (a response, or an exception to raise); sent requests kept."""
    state = {"script": [], "sent": []}

    def handle(self, request):
        state["sent"].append(request)
        step = state["script"].pop(0) if len(state["script"]) > 1 else state["script"][0]
        if isinstance(step, Exception):
            raise step
        return step

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    return state


def test_a_client_without_a_timeout_cannot_be_made():
    m = _client_module()
    with pytest.raises(TypeError):
        m.ServiceClient("http://platform:8000")


def test_a_redirect_is_never_followed(answers):
    m = _client_module()
    answers["script"] = [httpx.Response(302, headers={"location": "http://169.254.169.254/"})]
    r = m.ServiceClient("http://platform:8000", timeout=5).get("/a")
    assert r.status_code == 302 and len(answers["sent"]) == 1


def test_a_name_that_does_not_resolve_says_so(answers):
    m = _client_module()
    answers["script"] = [httpx.ConnectError("[Errno -2] Name or service not known")]
    with pytest.raises(m.ServiceUnreachable, match="cannot resolve platform"):
        m.ServiceClient("http://platform:8000", timeout=5).get("/x")


def test_connection_errors_are_retried_and_answers_are_not(answers):
    m = _client_module()
    answers["script"] = [httpx.ConnectError("refused"), httpx.Response(500)]
    r = m.ServiceClient("http://platform:8000", timeout=5, retries=(0, 0)).get("/x")
    assert r.status_code == 500 and len(answers["sent"]) == 2


def test_every_error_is_a_service_error():
    m = _client_module()
    for name in ("ServiceUnreachable", "ServiceTimeout", "ServiceRefused"):
        assert issubclass(getattr(m, name), m.ServiceError), name
    assert issubclass(m.ServiceError, RuntimeError)


def test_the_request_id_travels(answers):
    m = _client_module()
    assert importlib.util.find_spec("aisc_identity.logs") is not None, "no aisc_identity.logs to hold the request id"
    logs = importlib.import_module("aisc_identity.logs")
    answers["script"] = [httpx.Response(200)]
    token = logs.request_id.set("req-fake-1")
    try:
        m.ServiceClient("http://platform:8000", timeout=5).get("/x")
    finally:
        logs.request_id.reset(token)
    assert answers["sent"][0].headers.get("X-AISC-Request-Id") == "req-fake-1"
