"""Coverage comes from step 4.

A layout has no coverage map: which tests and controls give evidence for which objective is set
once per project on the platform's Collect evidence page (evidence.link in the project's database,
template 0016). Every snapshot, preview or generated report, carries those links as coverage_links,
grouped per objective (tests by plugin package, checklists by id), so a generated report keeps the
links it was made with. Links stored in a summary block's own options are not sent, and an old
client's `coverage` is ignored like its `language`.
"""
import json

import pytest

from conftest import IDS, new_layout, pdb_of
from v2_fakes import client_v2, fake_v2, unique, v2blk  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]

OLD_MAP = [{"objective_id": "O1", "tests": ["LangBiTe"], "checklists": ["cl-1"]}]
EXPECTED = [{"objective_id": "O1", "tests": ["aisc-plugin-langbite"], "checklists": ["cl-1"]},
            {"objective_id": "O5", "tests": ["aisc-plugin-langbite", "aisc-plugin-promptfoo"], "checklists": []}]


@pytest.fixture
def links(bed):
    db = pdb_of("A")
    bed.psql(db, "DELETE FROM evidence.link")
    v1, v2 = IDS["A_V1"], IDS["A_V2"]
    # version 2's links; one of version 1's, which a report of version 2 does not carry
    bed.psql(db, "INSERT INTO evidence.link (system_id, objective_id, kind, item_key, created_by) VALUES"
                 f" ('{v2}', 'O1', 'test', 'aisc-plugin-langbite', 'alice'), ('{v2}', 'O1', 'control', 'cl-1', 'alice'),"
                 f" ('{v2}', 'O5', 'test', 'aisc-plugin-promptfoo', 'alice'), ('{v2}', 'O5', 'test', 'aisc-plugin-langbite', 'bob'),"
                 f" ('{v1}', 'O3', 'test', 'aisc-plugin-langbite', 'alice')")
    yield
    bed.psql(db, "DELETE FROM evidence.link")


def soup(html):
    from bs4 import BeautifulSoup

    return BeautifulSoup(html, "html.parser")


def lay(client, auth, **body):
    body.setdefault("name", unique("Evidence"))
    body.setdefault("blocks", [v2blk("cover"), v2blk("summary_coverage")])
    return new_layout(client, auth, **body)


def generate(client, auth, layout):
    r = client.post(f"/api/p/alpha/layouts/{layout['id']}/reports", json={"system_id": IDS["A_V2"]},
                    headers=auth("alice"))
    assert r.status_code == 201, r.text[:300]
    return r.json()["id"]


def test_a_generated_report_carries_the_step_4_links(client_v2, auth, fake_v2, bed, links):
    rid = generate(client_v2, auth, lay(client_v2, auth))
    assert fake_v2.snapshots[-1]["coverage_links"] == EXPECTED
    stored = json.loads(bed.scalar(pdb_of("A"), "SELECT snapshot::text FROM report_composer.generated_report"
                                                f" WHERE id = '{rid}'"))
    assert stored["coverage_links"] == EXPECTED


def test_a_preview_carries_them_too(client_v2, auth, fake_v2, links):
    layout = lay(client_v2, auth)
    r = client_v2.get(f"/api/p/alpha/layouts/{layout['id']}/preview?system_id={IDS['A_V2']}", headers=auth("alice"))
    assert r.status_code == 200, r.text[:300]
    assert fake_v2.snapshots[-1]["coverage_links"] == EXPECTED


def test_a_project_without_links_sends_none(client_v2, auth, fake_v2, bed):
    bed.psql(pdb_of("A"), "DELETE FROM evidence.link")
    generate(client_v2, auth, lay(client_v2, auth))
    assert fake_v2.snapshots[-1]["coverage_links"] == []


def test_a_map_left_in_the_layout_row_is_not_sent(client_v2, auth, fake_v2, bed, links):
    layout = lay(client_v2, auth)
    bed.psql(pdb_of("A"), f"UPDATE report_composer.layout SET coverage = '{json.dumps(OLD_MAP)}'"
                          f" WHERE id = '{layout['id']}'")
    generate(client_v2, auth, layout)
    assert fake_v2.snapshots[-1]["coverage_links"] == EXPECTED


def test_a_summary_blocks_own_links_are_not_sent(client_v2, auth, fake_v2, links):
    own = v2blk("summary_coverage", links=OLD_MAP, show_uncovered_only=True)
    generate(client_v2, auth, lay(client_v2, auth, blocks=[own]))
    sent = next(b for b in fake_v2.snapshots[-1]["blocks"] if b["instance_id"] == own["instance_id"])
    assert "links" not in sent["options"] and sent["options"]["show_uncovered_only"] is True


def test_the_layout_has_no_coverage_map_and_an_old_clients_is_ignored(client_v2, auth, fake_v2):
    layout = lay(client_v2, auth, coverage=OLD_MAP)
    assert "coverage" not in layout
    got = client_v2.get(f"/api/p/alpha/layouts/{layout['id']}", headers=auth("alice")).json()
    assert "coverage" not in got
    generate(client_v2, auth, layout)
    assert fake_v2.coverage_calls == []


def test_the_editor_has_no_coverage_map(client_v2, auth):
    legacy = v2blk("summary_coverage", links=OLD_MAP)
    layout = lay(client_v2, auth, blocks=[legacy])
    doc = soup(client_v2.get(f"/p/alpha/layouts/{layout['id']}?system_id={IDS['A_V2']}", headers=auth("alice")).text)
    assert doc.find("details", attrs={"data-coverage-map": True}) is None
    assert doc.find(attrs={"data-control": "use-coverage-map"}) is None
    assert "Collect evidence" in doc.get_text(" ", strip=True)



def test_a_report_carries_the_links_of_the_card_version_it_is_of(client_v2, auth, fake_v2, bed, links):
    layout = lay(client_v2, auth)
    r = client_v2.post(f"/api/p/alpha/layouts/{layout['id']}/reports", json={"system_id": IDS["A_V1"]},
                       headers=auth("alice"))
    assert r.status_code == 201, r.text[:300]
    assert fake_v2.snapshots[-1]["coverage_links"] == [
        {"objective_id": "O3", "tests": ["aisc-plugin-langbite"], "checklists": []}]
