"""The composer's client for the renderer's v2 routes (it has no `languages()` and no
`coverage_choices`). No network: httpx is replaced by a recorder."""
import pytest

from conftest import need


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


