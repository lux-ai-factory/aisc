"""The ledger anchor a report prints, asked of the platform as the person generating it (phase 9 review m3):
a stub platform behind httpx's MockTransport, no bed."""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from report_composer import anchor

PROJECT = {"pid": "0f8fad5b-d9cb-469f-a165-70867728950e", "slug": "alpha"}
HEAD = {"seq": 41, "entry_sha256": "ab" * 32}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("LEDGER_MODE", "record")
    monkeypatch.setenv("PLATFORM_URL", "http://platform:8000")


def platform(monkeypatch, answer):
    seen = []

    def handler(request):
        seen.append(request)
        return answer(request)
    real = httpx.Client
    monkeypatch.setattr(anchor.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return seen


def asking(headers):
    return SimpleNamespace(headers=httpx.Headers(headers))


def test_the_head_is_asked_with_the_persons_gateway_token(monkeypatch):
    seen = platform(monkeypatch, lambda r: httpx.Response(200, json=HEAD))
    got = anchor.fetch(asking({"X-Auth-Request-Access-Token": "gateway-token", "Authorization": "Bearer other"}),
                       PROJECT)
    assert got == HEAD
    assert str(seen[0].url) == "http://platform:8000/projects/alpha/ledger/head"
    assert seen[0].headers["authorization"] == "Bearer gateway-token"


def test_without_the_gateway_header_the_bearer_token_is_used(monkeypatch):
    seen = platform(monkeypatch, lambda r: httpx.Response(200, json=HEAD))
    assert anchor.fetch(asking({"Authorization": "Bearer person"}), PROJECT) == HEAD
    assert seen[0].headers["authorization"] == "Bearer person"


@pytest.mark.parametrize("answer", [
    lambda r: httpx.Response(404, json={"detail": "this project has no ledger yet"}),
    lambda r: httpx.Response(403),
    lambda r: httpx.Response(200, json={"seq": "41", "entry_sha256": "ab" * 32}),
    lambda r: httpx.Response(200, json={"seq": 41, "entry_sha256": "zz"}),
    lambda r: httpx.Response(200, text="not json"),
])
def test_anything_but_a_head_prints_no_anchor(monkeypatch, answer):
    platform(monkeypatch, answer)
    assert anchor.fetch(asking({"Authorization": "Bearer person"}), PROJECT) is None


def test_a_platform_that_does_not_answer_prints_no_anchor(monkeypatch):
    def down(request):
        raise httpx.ConnectTimeout("no answer")
    platform(monkeypatch, down)
    assert anchor.fetch(asking({"Authorization": "Bearer person"}), PROJECT) is None


def test_with_the_ledger_off_nothing_is_asked(monkeypatch):
    monkeypatch.setenv("LEDGER_MODE", "off")
    platform(monkeypatch, lambda r: pytest.fail("asked with the ledger off"))
    assert anchor.fetch(asking({"Authorization": "Bearer person"}), PROJECT) is None
