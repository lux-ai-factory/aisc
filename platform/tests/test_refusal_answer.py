"""The platform answers a refusal as `detail`, with the status of its code.

The refusal object is the same in every app (shared/identity/refusal-cases.json); each app keeps its own
error envelope, and the platform's is `detail`. platform_service.refusals.raise_refusal raises the HTTP error.
The route here is added to the platform's own app for the test and removed after it, so the answer goes
through the app's real error handling.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aisc_identity.refusal import Refusal
from platform_service.refusals import raise_refusal

CASES = json.loads((Path(__file__).resolve().parents[2] / "shared/identity/refusal-cases.json").read_text())
EXAMPLE = CASES["valid"][0]["refusal"]
PATH = "/refusal-under-test"


@pytest.fixture
def refusing(client):
    """refusing(refusal) -> the platform's answer to a request whose route raised it."""
    app, added = client.app, []

    def answer(refusal: dict):
        def route():
            raise_refusal(Refusal.from_dict(refusal))

        app.add_api_route(PATH, route, methods=["GET"])
        added.append(app.router.routes[-1])
        return client.get(PATH)

    yield answer
    for route in added:
        app.router.routes.remove(route)


def test_a_refusal_is_answered_as_detail(refusing):
    answer = refusing(EXAMPLE)
    assert answer.json() == {"detail": EXAMPLE}


@pytest.mark.parametrize("code, status", [(c["code"], c["http"]) for c in CASES["codes"]])
def test_a_refusal_is_answered_with_the_status_of_its_code(refusing, code, status):
    answer = refusing({**EXAMPLE, "code": code})
    assert answer.status_code == status, f"{code} answered {answer.status_code}"
