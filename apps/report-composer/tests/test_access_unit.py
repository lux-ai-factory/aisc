"""Rights, without a database (report run 2026-09-23: R4.4.3 to R4.4.6). `report_composer.access`,
on the pattern of control-objectives' access.py, with admin as viewer everywhere (R4.4.5)."""
import pytest

from conftest import need

A = "report_composer.access"


def access(role, admin=False):
    return need(A, "Access")(role=role, admin=admin)


def decide(method, a):
    return need(A, "decide")(method, a)


# R4.4.3
def test_r4_4_3_a_stranger_is_told_nothing_exists():
    for m in ("GET", "POST", "PUT", "DELETE"):
        assert decide(m, access(None)) == "not-found"


# R4.4.4
def test_r4_4_4_a_viewer_reads_and_changes_nothing():
    assert decide("GET", access("viewer")) == "allow"
    for m in ("POST", "PUT", "DELETE"):
        assert decide(m, access("viewer")) == "forbidden"


@pytest.mark.parametrize("role", ["editor", "owner"])
def test_r4_4_4_editors_and_owners_write(role):
    for m in ("GET", "POST", "PUT", "DELETE"):
        assert decide(m, access(role)) == "allow"


def test_r4_4_4_no_answer_fails_closed():
    assert decide("GET", None) == "unavailable"


# R4.4.5
def test_r4_4_5_an_admin_outside_the_project_is_a_viewer():
    a = access(None, admin=True)
    assert decide("GET", a) == "allow"
    assert decide("PUT", a) == "forbidden"


def test_r4_4_5_an_admin_who_is_an_editor_edits():
    assert decide("PUT", access("editor", admin=True)) == "allow"


# R4.4.6
@pytest.mark.parametrize("headers,ok", [
    ({"origin": "http://localhost"}, True),
    ({"origin": "http://evil.example"}, False),
    ({"origin": "http://localhost:8100"}, False),
    ({}, False),
    ({"referer": "http://localhost/report-composer/p/alpha/"}, True),
    ({"referer": "http://evil.example/x"}, False),
])
def test_r4_4_6_same_origin(headers, ok):
    assert need(A, "same_origin")(headers, "http://localhost") is ok
