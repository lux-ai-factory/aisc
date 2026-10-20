"""The renderer's limits on /v1/render: a snapshot over its size cap is 413 and a
render past its concurrency slots is 503 with code busy. The composer tells the person which one it is
instead of "renderer unavailable". No network: httpx is replaced by a stub."""
import pytest

from conftest import need


@pytest.fixture
def answer(monkeypatch):
    def install(status, body):
        import httpx

        monkeypatch.setattr(httpx.Client, "request", lambda self, method, url, **kw: httpx.Response(
            status, json=body, request=httpx.Request(method, url)))

    return install


def client():
    return need("report_composer.renderer_client", "HttpRendererClient")("http://renderer:8001", token="t" * 32)


def error(code, message="m"):
    return {"error": {"code": code, "message": message}}


def test_a_413_is_too_large(answer):
    TooLarge = need("report_composer.renderer_client", "RendererTooLarge")
    answer(413, error("too_large"))
    with pytest.raises(TooLarge):
        client().render({"blocks": []})


def test_a_503_busy_is_busy(answer):
    Busy = need("report_composer.renderer_client", "RendererBusy")
    answer(503, error("busy"))
    with pytest.raises(Busy):
        client().render({"blocks": []})


def test_a_503_that_is_not_busy_stays_unavailable(answer):
    from report_composer.renderer_client import RendererUnavailable

    Busy = need("report_composer.renderer_client", "RendererBusy")
    answer(503, error("down"))
    with pytest.raises(RendererUnavailable) as exc:
        client().render({"blocks": []})
    assert not isinstance(exc.value, Busy)


def test_renderer_call_answers_413_report_too_large():
    from report_composer.errors import ApiError
    from report_composer.renderer_calls import renderer_call

    TooLarge = need("report_composer.renderer_client", "RendererTooLarge")

    def fn():
        raise TooLarge("413")

    with pytest.raises(ApiError) as exc:
        renderer_call(fn)
    assert (exc.value.status, exc.value.code) == (413, "report_too_large")
    assert "too large" in exc.value.message


def test_renderer_call_answers_503_renderer_busy():
    from report_composer.errors import ApiError
    from report_composer.renderer_calls import renderer_call

    Busy = need("report_composer.renderer_client", "RendererBusy")

    def fn():
        raise Busy("busy")

    with pytest.raises(ApiError) as exc:
        renderer_call(fn)
    assert (exc.value.status, exc.value.code) == (503, "renderer_busy")
    assert "busy" in exc.value.message and "try again" in exc.value.message


def test_a_2xx_that_is_not_json_is_unavailable():
    # E.g. a proxy answering 200 with an HTML page; the JSONDecodeError escaped every
    # RendererError handler and answered 500
    Client = need("report_composer.renderer_client", "HttpRendererClient")
    Unavailable = need("report_composer.renderer_client", "RendererUnavailable")
    with pytest.raises(Unavailable):
        Client._answer(200, b"<html>a proxy page</html>")
