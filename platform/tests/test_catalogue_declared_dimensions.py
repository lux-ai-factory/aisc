"""A local test shows the dimensions its package declares until an admin saves a choice, which then wins,
an explicit choice of none included."""
from __future__ import annotations

import pytest

from tests.conftest import needs_database
from tests.test_catalogue_choice import SAMPLE, admin, choose, engine, public, public_routes, url  # noqa: F401
from tests.test_evidence import ALICE, VERA, _reader, catalogue, evidence_project, sql  # noqa: F401

pytestmark = needs_database
FAIRNESS = "diversity-non-discrimination-fairness"
ROBUSTNESS = "technical-robustness-safety"


@pytest.fixture
def declaring_engine(engine):
    engine.route("GET", "/api/v1/plugins", (200, [
        {"package_name": "aisc-plugin-langbite", "version": "0.1.0", "source": "registry"},
        {"package_name": "my-probe", "version": "0.2.0+local", "source": "local", "dimensions": ["REQ5"]},
    ]))
    return engine


def probe_dimensions(client, as_user, project):
    tools = client.get(url(project, "/api/tool/?detailed=true"), headers=as_user(VERA)).json()
    probe = next(t for t in tools if t["slug"] == "local-my-probe")
    return {g["slug"] for g in probe["tags"] if g["section"] == "dimension"}


def put(client, as_user, project, dimensions):
    return client.put(url(project, "/local/my-probe/dimensions"), json={"dimensions": dimensions},
                      headers=admin(as_user))


def test_a_local_test_shows_its_declared_dimension(client, as_user, evidence_project, public, declaring_engine):
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    assert probe_dimensions(client, as_user, evidence_project) == {FAIRNESS}


def test_an_admin_choice_replaces_the_declared_one(client, as_user, evidence_project, public, declaring_engine):
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    assert put(client, as_user, evidence_project, ["REQ2"]).status_code == 200
    assert probe_dimensions(client, as_user, evidence_project) == {ROBUSTNESS}


def test_an_admin_choice_of_no_dimension_stays_empty(client, as_user, evidence_project, public, declaring_engine):
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    assert put(client, as_user, evidence_project, []).status_code == 200
    assert probe_dimensions(client, as_user, evidence_project) == set()


def test_choosing_dimensions_after_choosing_none_replaces_the_none(client, as_user, evidence_project, public,
                                                                    declaring_engine):
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    assert put(client, as_user, evidence_project, []).status_code == 200
    assert put(client, as_user, evidence_project, ["REQ2"]).status_code == 200
    assert probe_dimensions(client, as_user, evidence_project) == {ROBUSTNESS}
