"""A layout write whose checks ran in an earlier transaction than the write: a delete that
commits in between must not end in a 500. A layout deleted meanwhile is 404 and gets no new revision;
a template deleted meanwhile is 422 template_not_in_project, for a save and for a new layout. The
interleaving is forced by doing the other request's write inside chosen_template, which runs between
the checks and the write. Database tests, fake renderer."""
import pytest

from conftest import blk, error_code, new_layout, new_template, pdb_of, put_layout

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


@pytest.fixture
def meanwhile(monkeypatch):
    """meanwhile(sql): run sql on alpha's database just after the template is checked."""
    from report_composer import api

    def arm(bed, sql):
        checked = api.chosen_template

        def then_the_other_request(conn, template_id):
            found = checked(conn, template_id)
            bed.psql(pdb_of("A"), sql)
            return found

        monkeypatch.setattr(api, "chosen_template", then_the_other_request)

    return arm


def revisions(bed, layout_id):
    return int(bed.scalar(pdb_of("A"), "SELECT count(*) FROM report_composer.layout_revision"
                                       f" WHERE layout_id = '{layout_id}'"))


def test_a_layout_deleted_while_it_is_saved_is_404(client, auth, bed, meanwhile):
    lay = new_layout(client, auth, blocks=[blk("free_text", text="one")])
    before = revisions(bed, lay["id"])
    meanwhile(bed, f"UPDATE report_composer.layout SET deleted_at = now() WHERE id = '{lay['id']}'")
    r = put_layout(client, auth, lay, blocks=[blk("free_text", text="two")])
    assert r.status_code == 404 and error_code(r) == "not_found"
    assert revisions(bed, lay["id"]) == before


def test_a_template_deleted_while_a_layout_is_saved_is_422(client, auth, bed, meanwhile):
    lay = new_layout(client, auth, blocks=[blk("free_text", text="one")])
    other = new_template(client, auth)
    meanwhile(bed, f"DELETE FROM report_composer.template WHERE id = '{other['id']}'")
    r = put_layout(client, auth, lay, template_id=other["id"])
    assert r.status_code == 422 and error_code(r) == "template_not_in_project"


def test_a_template_deleted_while_a_layout_is_made_is_422(client, auth, bed, meanwhile):
    other = new_template(client, auth)
    meanwhile(bed, f"DELETE FROM report_composer.template WHERE id = '{other['id']}'")
    r = client.post("/api/p/alpha/layouts", json={"name": "Raced", "template_id": other["id"]},
                    headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) == "template_not_in_project"
