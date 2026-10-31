"""A service that answers 2xx with something other than JSON (a proxy's HTML page, a truncated body) is
treated like a service that did not answer, with the client's own error, never a bare decoding error."""
from __future__ import annotations

import pytest

from platform_service import engine_components, reports
from tests.http_stub import Stub

PAGE = b"<html><body>Bad gateway, but with a 200</body></html>"


@pytest.fixture
def stub():
    s = Stub()
    yield s
    s.stop()


def test_an_engine_answer_that_is_not_json_is_an_unavailable_engine(stub, monkeypatch):
    monkeypatch.setenv("ENGINE_URL", stub.base)
    stub.route("GET", "/api/v1/plugins", (200, PAGE))
    with pytest.raises(engine_components.EngineUnavailable) as caught:
        engine_components.available_plugins("p1", "token")
    assert caught.value.status == 200
    assert "not JSON" in str(caught.value)


def test_a_composer_answer_that_is_not_json_is_an_unavailable_composer(stub, monkeypatch):
    monkeypatch.setenv("REPORT_COMPOSER_URL", stub.base)
    stub.route("GET", "/api/p/alpha/reports", (200, PAGE))
    with pytest.raises(reports.ComposerUnavailable) as caught:
        reports.of_version("alpha", "v1", "token")
    assert "not JSON" in str(caught.value)
