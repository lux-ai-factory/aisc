"""The unspecified address and loopback written as an IPv6-mapped address are loopback too, so a project can
never allow them; and the rule a run gets names the floor (the deployment's own hosts plus the operator's,
such as the default local model server), the only hosts that may reach loopback. Runs on the throwaway."""
from __future__ import annotations

import pytest

from platform_service import connection_allowlist
from tests.conftest import needs_database
from tests.test_connection_allowlist import ALICE, _env, hosts, names, stub  # noqa: F401  (fixtures)

pytestmark = needs_database


@pytest.mark.parametrize("denied", ["0.0.0.0", "0.0.0.0:11434", "[::]", "[::ffff:127.0.0.1]"])
def test_the_unspecified_and_mapped_loopback_addresses_are_never_allowed(client, as_user, project, names, denied):  # noqa: F811
    r = client.put(f"{hosts(project)}/{denied}", json={}, headers=as_user(ALICE))
    assert r.status_code == 422 and "never" in r.json()["detail"], (denied, r.text)


def test_the_rule_names_the_floor_and_the_operators_hosts(names, monkeypatch, project):  # noqa: F811
    monkeypatch.setenv("CONNECTIONS_ALLOWED_HOSTS", "model-server:8080")
    try:
        got = connection_allowlist.rule(project["pid"], operator_hosts=["host.docker.internal:11434"])
    except TypeError as exc:
        pytest.fail(f"the rule takes no operator hosts: {exc}")
    assert got.get("floor_hosts") == ["model-server:8080", "host.docker.internal:11434"], got
    assert "host.docker.internal:11434" in got["allowed_hosts"]


def test_a_rule_without_operator_hosts_still_names_its_floor(names, monkeypatch, project):  # noqa: F811
    monkeypatch.setenv("CONNECTIONS_ALLOWED_HOSTS", "model-server:8080")
    assert connection_allowlist.rule(project["pid"]).get("floor_hosts") == ["model-server:8080"]
