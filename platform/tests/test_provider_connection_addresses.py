"""A provider connection's own address (a self-hosted model server) is checked against the project's network
rule when it is saved: an internal, metadata or unspecified address is refused, naming base_url. Runs on the
throwaway."""
from __future__ import annotations

import pytest

from tests.conftest import needs_database
from tests.test_connections import _env, put, stub  # noqa: F401  (fixtures)

pytestmark = needs_database


@pytest.mark.parametrize("url", ["http://10.1.2.3:8000/v1", "http://169.254.169.254/v1", "http://0.0.0.0:11434"])
def test_a_provider_connection_to_an_internal_address_is_refused(client, admin, project, url):
    r = put(client, project, "own-llm", admin, {"label": "Own", "kind": "provider",
                                                "provider": "compatible", "base_url": url})
    assert r.status_code == 422, r.text
    assert "base_url" in r.text
