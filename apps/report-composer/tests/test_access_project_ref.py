"""A project reference in a URL is its pid or its slug, resolved by aisc_identity.access (whose
truth table covers every spelling). These check the composer serves the project that rule names."""
import pytest

from conftest import IDS

pytestmark = pytest.mark.db

SHAPED = "0f0f0f0f-0000-4000-8000-00000000d3d3"
OTHER = "0e0e0e0e-0000-4000-8000-00000000d3d3"


@pytest.fixture
def admin(auth):
    return auth("root-admin", roles=("admin",))


@pytest.fixture
def id_shaped_slugs(bed):
    """Two projects whose slugs look like pids: one names no project, one names alpha's pid."""
    bed.psql("platform", "INSERT INTO core.project (pid, name, slug) VALUES"
                         f" ('{OTHER}', 'shaped project', '{SHAPED}'),"
                         f" ('{OTHER[:-4]}d4d4', 'alpha look-alike', '{IDS['A']}')")
    yield
    bed.psql("platform", f"DELETE FROM core.project WHERE pid IN ('{OTHER}', '{OTHER[:-4]}d4d4')")


def test_an_id_shaped_slug_is_not_served(client, admin, id_shaped_slugs):
    assert client.get(f"/api/p/{SHAPED}/layouts", headers=admin).status_code == 404


def test_a_pid_serves_its_own_project_even_when_another_slug_spells_it(client, admin, id_shaped_slugs):
    by_pid = client.get(f"/api/p/{IDS['A']}/layouts", headers=admin)
    by_slug = client.get("/api/p/alpha/layouts", headers=admin)
    assert by_pid.status_code == 200
    assert by_pid.json() == by_slug.json()
