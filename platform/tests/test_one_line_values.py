"""A header value is one line: a `secret_header` or a plain header value with a newline or a carriage return
is refused at save with 422 naming the field, never stored (stored, it made every call a 500 whose text held
the decrypted key). And a project id is checked whole: one with a trailing newline is a 404 on the internal
routes and the doors, never a 500 from the database. Runs on the throwaway; the system under test is a local
stub."""
from __future__ import annotations

import uuid

import pytest

from platform_service import projects
from tests.conftest import needs_database
from tests.connection_support import CONNECTIONS_TOKEN, engine_component, new_secret
from tests.test_connection_facades import _env, stub  # noqa: F401  (fixtures)

SERVICE = {"X-AISC-Service-Token": CONNECTIONS_TOKEN}


def rest(stub, **over):  # noqa: F811
    body = {"label": "N", "kind": "rest", "base_url": stub.base, "path": "/chat",
            "body_template": {"q": "{{input}}"}, "response_path": "answer", "timeout_s": 5, "secret": new_secret()}
    body.update(over)
    return body


def names(client, admin, project):
    r = client.get(f"/projects/{project['slug']}/connections", headers=admin)
    assert r.status_code == 200, r.text
    return [c["name"] for c in r.json()["connections"]]


# header values

@needs_database
@pytest.mark.parametrize("field, value", [
    ("secret_header", "Authorization: Bearer {{secret}}\nX-Evil: 1"),
    ("secret_header", "Authorization: Bearer {{secret}}\rX-Evil: 1"),
    ("secret_header", "Authorization: Bearer {{secret}}\r\nX-Evil: 1"),
    ("headers", {"X-Client": "aisc\nX-Evil: 1"}),
    ("headers", {"X-Client": "aisc\rX-Evil: 1"}),
    ("headers", {"X-Client": "aisc\r\nX-Evil: 1"}),
], ids=["secret_header-LF", "secret_header-CR", "secret_header-CRLF", "headers-LF", "headers-CR", "headers-CRLF"])
def test_a_header_value_with_a_line_break_is_a_422_naming_the_field(client, admin, project, stub, field, value):  # noqa: F811
    engine_component(stub, project["pid"])
    r = client.put(f"/projects/{project['slug']}/connections/broken", json=rest(stub, **{field: value}), headers=admin)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert isinstance(detail, str) and detail.startswith(f"{field}:"), detail
    assert "one line" in detail, detail
    assert names(client, admin, project) == []


@needs_database
@pytest.mark.parametrize("field, value", [
    ("secret_header", "Authorization: Bearer {{secret}}\nX-Evil: 1"),
    ("headers", {"X-Client": "aisc\nX-Evil: 1"}),
])
def test_an_existing_connection_keeps_its_headers_when_a_line_break_is_refused(
        client, admin, project, stub, field, value):  # noqa: F811
    engine_component(stub, project["pid"])
    good = rest(stub, secret_header="Authorization: Bearer {{secret}}", headers={"X-Client": "aisc"})
    assert client.put(f"/projects/{project['slug']}/connections/kept", json=good, headers=admin).status_code == 200
    r = client.put(f"/projects/{project['slug']}/connections/kept", json={**good, field: value}, headers=admin)
    assert r.status_code == 422, r.text
    [row] = [c for c in client.get(f"/projects/{project['slug']}/connections", headers=admin).json()["connections"]
             if c["name"] == "kept"]
    assert row["secret_header"] == "Authorization: Bearer {{secret}}"
    assert row["headers"] == {"X-Client": "aisc"}


@needs_database
def test_header_values_on_one_line_are_still_saved(client, admin, project, stub):  # noqa: F811
    engine_component(stub, project["pid"])
    r = client.put(f"/projects/{project['slug']}/connections/fine", headers=admin, json=rest(
        stub, secret_header="Authorization: Bearer {{secret}}", headers={"X-Client": "aisc tools: v1"}))
    assert r.status_code == 200, r.text
    assert names(client, admin, project) == ["fine"]


# project ids

def test_a_project_id_with_a_trailing_newline_does_not_look_like_one():
    pid = str(uuid.uuid4())
    assert projects.looks_like_pid(pid)
    assert not projects.looks_like_pid(pid + "\n")
    assert not projects.looks_like_pid("\n" + pid)


@needs_database
def test_the_internal_routes_and_the_doors_answer_a_project_id_with_a_newline_with_a_404(
        client, admin, project, stub):  # noqa: F811
    engine_component(stub, project["pid"])
    stub.route("POST", "/chat", (200, {"answer": "ok"}))
    assert client.put(f"/projects/{project['slug']}/connections/sys", json=rest(stub), headers=admin).status_code == 200
    key = client.post(f"/internal/projects/{project['pid']}/connections/sys/run-keys", headers=SERVICE).json()["key"]
    pid = project["pid"] + "%0A"
    before = len(stub.seen)
    for method, path, kw in [
        ("GET", f"/internal/projects/{pid}/connections/sys", {"headers": SERVICE}),
        ("POST", f"/internal/projects/{pid}/connections/sys/run-keys", {"headers": SERVICE}),
        ("POST", f"/internal/facade/{pid}/sys/aisc/ask",
         {"headers": {"Authorization": f"Bearer {key}"}, "json": {"input": "q"}}),
        ("POST", f"/internal/facade/{pid}/sys/openai/v1/chat/completions",
         {"headers": {"Authorization": f"Bearer {key}"}, "json": {"messages": [{"role": "user", "content": "q"}]}}),
    ]:
        try:
            r = client.request(method, path, **kw)
        except Exception as exc:  # the test client re-raises what the server raised: a 500
            pytest.fail(f"{method} {path} raised {type(exc).__name__}: {str(exc)[:160]}")
        assert r.status_code == 404, f"{method} {path}: {r.status_code} {r.text[:200]}"
    assert len(stub.seen) == before
