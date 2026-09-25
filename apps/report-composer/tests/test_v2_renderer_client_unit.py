"""The composer's client for the renderer's v2 routes (R-U2.7, R-V8.9): stage 4 added
`coverage_choices(project_id, system_id)` to HttpRendererClient (`languages()` goes, R2-D1.9). No network: httpx
is replaced by a recorder."""
import pytest

from conftest import IDS, need


class Recorder:
    def __init__(self, answer):
        self.calls, self.answer = [], answer

    def __call__(self, client_self, method, url, json=None, headers=None, **kw):
        import httpx

        self.calls.append((method, url, json, dict(headers or {})))
        return httpx.Response(200, json=self.answer, request=httpx.Request(method, url))


@pytest.fixture
def http(monkeypatch):
    def install(answer):
        import httpx

        rec = Recorder(answer)
        # a callable instance is not bound as a method, so it is wrapped in a function that is
        monkeypatch.setattr(httpx.Client, "request", lambda self, *a, **k: rec(self, *a, **k))
        return rec

    return install


def client():
    Http = need("report_composer.renderer_client", "HttpRendererClient")
    return Http("http://renderer:8001", token="t" * 32)


def test_r_u2_7_coverage_choices_is_post_v1_coverage_choices(http):
    rec = http({"objectives": [], "tests": [], "checklists": []})
    c = client()
    if not hasattr(c, "coverage_choices"):
        pytest.fail("missing feature: HttpRendererClient.coverage_choices", pytrace=False)
    c.coverage_choices(IDS["A"], IDS["A_V2"])
    method, url, body, _ = rec.calls[-1]
    assert (method, url) == ("POST", "http://renderer:8001/v1/coverage-choices")
    assert body == {"project_id": IDS["A"], "system_id": IDS["A_V2"]}
