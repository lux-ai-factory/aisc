"""The bodies of the project, member and AI system routes take only their own fields, as strings, each with
an upper bound on its length; an unknown field or an overlong text is a 422, never stored."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from platform_service.routes.projects import DeleteProjectIn, MemberIn, MemberRoleIn, ProjectIn, SystemIn
from tests.conftest import ALICE

BOUNDS = [
    (ProjectIn, "name", 200), (ProjectIn, "slug", 64), (ProjectIn, "description", 2000),
    (DeleteProjectIn, "confirm_name", 200),
    (MemberIn, "subject", 255), (MemberIn, "email", 320), (MemberIn, "role", 32),
    (MemberRoleIn, "role", 32),
    (SystemIn, "name", 200), (SystemIn, "version", 100), (SystemIn, "provider", 200), (SystemIn, "description", 2000),
]
REQUIRED = {"name": "x", "confirm_name": "x", "subject": "s", "role": "viewer"}


def _body(model, **fields):
    body = {k: v for k, v in REQUIRED.items() if k in model.model_fields}
    body.update(fields)
    return body


@pytest.mark.parametrize("model,body", [
    (ProjectIn, {"name": "x", "owner": "eve"}), (DeleteProjectIn, {"confirm_name": "x", "force": True}),
    (MemberIn, {"subject": "s", "admin": True}), (MemberRoleIn, {"role": "viewer", "x": 1}),
    (SystemIn, {"name": "x", "extra": 1}),
])
def test_a_body_with_an_unknown_field_is_refused(model, body):
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        model.model_validate(body)


@pytest.mark.parametrize("model,field,limit", BOUNDS, ids=[f"{m.__name__}.{f}" for m, f, _ in BOUNDS])
def test_text_longer_than_its_bound_is_refused(model, field, limit):
    assert model.model_validate(_body(model, **{field: "a" * limit}))
    with pytest.raises(ValidationError):
        model.model_validate(_body(model, **{field: "a" * (limit + 1)}))


@pytest.mark.parametrize("model,field", [(ProjectIn, "name"), (MemberIn, "subject"), (SystemIn, "name")])
def test_a_text_field_does_not_take_a_number(model, field):
    with pytest.raises(ValidationError):
        model.model_validate(_body(model, **{field: 12345}))


def test_the_api_answers_422_for_an_unknown_field(client, as_user):
    r = client.post("/projects", json={"name": "strict-body-probe", "owner": "eve"}, headers=as_user(ALICE))
    assert r.status_code == 422, r.text
