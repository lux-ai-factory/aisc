"""A helper model resolved for a run comes with its project's network rule (allowed hosts, denied addresses
and the floor), so the worker checks the helper's address at the call. Runs on the throwaway."""
from __future__ import annotations

from tests.conftest import needs_database
from tests.test_helper_models_internal import _env, project, resolving  # noqa: F401  (fixtures)

pytestmark = needs_database


def test_resolve_hands_the_run_its_projects_rule(client, project):  # noqa: F811
    r = resolving(client, project["pid"])
    assert r.status_code == 200, r.text
    assert set(r.json()) >= {"endpoint_url", "api_key", "allowed_hosts", "denied_addresses", "floor_hosts"}, \
        sorted(set(r.json()) - {"api_key"})
