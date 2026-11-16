"""A test installed from the catalogue cites the request the person made.

The platform installs through the engine's own API. The engine's plugin.installed event is accepted by the
ledger only when it cites a witnessed request, so the platform passes on the id of the request it is
serving (X-AISC-Request-Id) on every engine call it makes on the person's behalf.
"""
from __future__ import annotations

import uuid

import httpx

from platform_service import engine_components
from platform_service.ledger import outbox


class _Answer:
    status_code = 200

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def test_catalogue_install_forwards_the_witnessed_request(monkeypatch):
    sent = []

    def fake_request(method, url, **kw):
        sent.append((method, url, kw.get("headers") or {}))
        return _Answer({"pid": str(uuid.uuid4())})

    monkeypatch.setattr(httpx.Client, "request", lambda self, method, url, **kw: fake_request(method, url, **kw))
    witnessed = str(uuid.uuid4())
    token = outbox.current_request.set(witnessed)
    try:
        engine_components.install_plugin(str(uuid.uuid4()), "person-token", "aisc-plugin-demo", "1.0.0", "demo")
    finally:
        outbox.current_request.reset(token)
    install = [h for m, url, h in sent if m == "POST" and url.endswith("/api/v1/plugins")]
    assert install, "no install call reached the engine"
    assert install[-1].get("X-AISC-Request-Id") == witnessed, (
        "the engine's install call does not cite the request the person made")


def test_an_engine_call_outside_a_request_sends_no_request_id(monkeypatch):
    sent = []
    monkeypatch.setattr(httpx.Client, "request",
                        lambda self, method, url, **kw: sent.append(kw.get("headers") or {}) or _Answer([]))
    engine_components.available_plugins(str(uuid.uuid4()), "person-token")
    assert "X-AISC-Request-Id" not in sent[-1]
