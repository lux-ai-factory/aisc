"""Installing a test on the engine has the eval worker install it and read its manifest in its sandbox (the
engine never imports plugin code): the platform waits for that longer than the engine waits for the worker
(PLUGIN_MANIFEST_TIMEOUT_S, 900 seconds by default), so the engine's named reason reaches the person when the
worker does not answer, and every other engine call keeps its short limit."""
import httpx

from platform_service import engine_components

#: the engine's default wait for the worker (aisc_backend.plugin_declarations.WAIT_DEFAULT_S)
ENGINE_WAITS_S = 900


class _Answer:
    status_code = 200

    @staticmethod
    def json():
        return {"pid": "e1"}


def test_an_install_waits_longer_than_the_engine_waits_for_the_worker(monkeypatch):
    seen = []

    def request(method, url, **kwargs):
        seen.append((method, url.rsplit("/api/v1", 1)[1], kwargs["timeout"]))
        return _Answer()

    monkeypatch.setattr(httpx.Client, "request", lambda self, method, url, **kw: request(method, url, **kw))
    engine_components.install_plugin("p1", "token", "demo-pkg", "1.0", "demo")
    timeouts = {path: timeout for method, path, timeout in seen}
    assert timeouts["/plugins"] >= ENGINE_WAITS_S + 60
    assert timeouts["/projects/for-platform/p1"] == engine_components.TIMEOUT_S == 20
