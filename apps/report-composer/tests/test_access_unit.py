"""Writes must come from the platform's own pages."""
import pytest

from conftest import need


@pytest.mark.parametrize("headers,ok", [
    ({"origin": "http://localhost"}, True),
    ({"origin": "http://evil.example"}, False),
    ({"origin": "http://localhost:8100"}, False),
    ({}, False),
    ({"referer": "http://localhost/report-composer/p/alpha/"}, True),
    ({"referer": "http://evil.example/x"}, False),
])
def test_same_origin(headers, ok):
    assert need("report_composer.guards", "same_origin")(headers, "http://localhost") is ok
