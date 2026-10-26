"""A run pass names only its run's project. The worker says which project the evaluation is of; a pass
asked for with a target or connection of another project is refused and nothing is stored, so a member
of one project cannot reach another project's connection by naming it in a run. Runs on the throwaway;
the system under test is a local stub."""
from __future__ import annotations

import pytest

from platform_service import db, run_passes
from tests.conftest import needs_database
from tests.connection_support import CONNECTIONS_TOKEN
from tests.test_run_passes import _env, made_with_endpoints, stub, with_pass  # noqa: F401  (fixtures)

pytestmark = needs_database
NO_PROJECT = "project: the platform pid of the evaluation's project"
NOBODY = "00000000-0000-4000-8000-0000000000aa"


@pytest.fixture
def two(make_project, client, admin, stub):  # noqa: F811
    """Projects A and B, each with a connection `spare` and a system target with its endpoint."""
    return (made_with_endpoints(make_project, client, admin, stub),
            made_with_endpoints(make_project, client, admin, stub))


def ask(client, body):
    return client.post("/internal/run-passes", json=body, headers={"X-AISC-Service-Token": CONNECTIONS_TOKEN})


def passes() -> int:
    with db.pool().connection() as conn:
        return conn.execute("SELECT count(*) AS n FROM core.run_pass").fetchone()["n"]


def test_a_pass_for_the_runs_own_project_opens_its_references(client, two):
    a, _ = two
    r = ask(client, {"refs": [f"target:{a['pid']}/system", f"connection:{a['pid']}/spare"], "project": a["pid"]})
    assert r.status_code == 201, r.text
    assert r.json()["pass"] and r.json()["expires_at"]
    assert with_pass(client, r.json()["pass"], a, "connections/spare").status_code == 200


def test_another_projects_connection_is_refused_and_nothing_stored(client, two):
    a, b = two
    before = passes()
    r = ask(client, {"refs": [f"connection:{b['pid']}/spare"], "project": a["pid"]})
    assert r.status_code == 403, r.text
    assert r.json() == {"detail": f"'connection:{b['pid']}/spare' is not of the run's project {a['pid']}"}
    assert passes() == before


def test_one_foreign_reference_among_own_ones_refuses_the_whole_pass(client, two):
    a, b = two
    before = passes()
    r = ask(client, {"refs": [f"target:{a['pid']}/system", f"target:{b['pid']}/system"], "project": a["pid"]})
    assert r.status_code == 403, r.text
    assert r.json() == {"detail": f"'target:{b['pid']}/system' is not of the run's project {a['pid']}"}
    assert passes() == before


def test_a_pass_without_a_project_is_refused(client, two):
    a, _ = two
    r = ask(client, {"refs": [f"target:{a['pid']}/system"]})
    assert r.status_code == 422, r.text
    assert r.json() == {"detail": NO_PROJECT}


@pytest.mark.parametrize("project", ["not-a-pid", 5, None])
def test_a_project_that_is_not_a_pid_is_refused(client, two, project):
    a, _ = two
    r = ask(client, {"refs": [f"target:{a['pid']}/system"], "project": project})
    assert r.status_code == 422, r.text
    assert r.json() == {"detail": NO_PROJECT}


def test_a_project_that_does_not_exist_is_404(client, two):
    r = ask(client, {"refs": [f"target:{NOBODY}/system"], "project": NOBODY})
    assert r.status_code == 404, r.text
    assert r.json() == {"detail": f"no project '{NOBODY}'"}


def test_pids_are_compared_as_uuids(client, two):
    a, _ = two
    r = ask(client, {"refs": [f"target:{a['pid'].lower()}/system"], "project": a["pid"].upper()})
    assert r.status_code == 201, r.text


def test_the_project_is_a_required_keyword_of_mint(client, two):
    a, _ = two
    run_pass, expires = run_passes.mint([f"target:{a['pid']}/system"], ttl_s=60, project=a["pid"])
    assert run_pass and expires
    with pytest.raises(TypeError):
        run_passes.mint([f"target:{a['pid']}/system"])
    with pytest.raises(TypeError):
        run_passes.mint([f"target:{a['pid']}/system"], 60, None, a["pid"])


def test_a_direct_mint_with_a_foreign_reference_is_refused_with_403(client, two):
    a, b = two
    with pytest.raises(run_passes.Refused) as refused:
        run_passes.mint([f"connection:{b['pid']}/spare"], project=a["pid"])
    assert refused.value.status == 403
