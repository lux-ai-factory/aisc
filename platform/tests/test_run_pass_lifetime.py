"""The worker names how long a run's pass lasts, as long as a test may run and no longer; a lifetime out of
range is refused. Runs on the throwaway."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tests.conftest import needs_database
from tests.connection_support import CONNECTIONS_TOKEN
from tests.test_run_passes import _env, made_with_endpoints, stub  # noqa: F401  (fixtures)

pytestmark = needs_database


@pytest.fixture
def project(make_project, client, admin, stub):  # noqa: F811
    return made_with_endpoints(make_project, client, admin, stub)


def mint_for(client, project, ttl_s):
    return client.post("/internal/run-passes",
                       json={"refs": [f"target:{project['pid']}/system"], "project": project["pid"], "ttl_s": ttl_s},
                       headers={"X-AISC-Service-Token": CONNECTIONS_TOKEN})


def test_the_worker_names_how_long_its_pass_lasts(client, project):
    r = mint_for(client, project, 600)
    assert r.status_code == 201, r.text
    left = (datetime.fromisoformat(r.json()["expires_at"]) - datetime.now(timezone.utc)).total_seconds()
    assert 540 < left <= 600


@pytest.mark.parametrize("ttl_s", [0, 59, True, "600", 10**9])
def test_a_pass_lifetime_out_of_range_is_refused(client, project, ttl_s):
    r = mint_for(client, project, ttl_s)
    assert r.status_code == 422, r.text
