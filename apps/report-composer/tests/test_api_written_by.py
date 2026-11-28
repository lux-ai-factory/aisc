"""Who wrote each text of a layout, kept by every save and sent with the report.

A save stamps each written text (a block's commentary, a free text, a chapter's introduction, a tool's commentary)
whose content changed with the saver's name and the time; unchanged texts keep their stamp, and the revision keeps
the stamps it was saved with. The renderer is sent them with each block (`written`). Database tests, v2 fake
renderer; project alpha, where alice and olga may edit."""
import pytest

from conftest import FIXED_NOW, IDS, new_layout, pdb_of, put_layout
from v2_fakes import client_v2, fake_v2, v2blk  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]

AT = FIXED_NOW.isoformat()


def anna(auth):
    return auth("alice", username="Anna")


def luca(auth):
    return auth("olga", username="Luca")


def generate(client, auth, lay, who):
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={"system_id": IDS["A_V2"]}, headers=who(auth))
    assert r.status_code == 201, r.text[:500]


def sent_written(fake):
    return {b["instance_id"]: b.get("written") for b in fake.snapshots[-1]["blocks"]}


def test_each_commentary_says_who_wrote_it(client_v2, auth, fake_v2):
    a = v2blk("ai_card", commentary="Commentary A")
    lay = new_layout(client_v2, auth, who="alice", blocks=[a])
    client_v2.put(f"/api/p/alpha/layouts/{lay['id']}", headers=anna(auth), json={
        "name": lay["name"], "revision": lay["revision"], "template_id": lay["template_id"],
        "blocks": [{**a, "options": {"commentary": "Commentary A by Anna"}}]}).raise_for_status()
    saved = client_v2.get(f"/api/p/alpha/layouts/{lay['id']}", headers=anna(auth)).json()
    b = v2blk("test_results", commentary="Commentary B")
    r = client_v2.put(f"/api/p/alpha/layouts/{lay['id']}", headers=luca(auth), json={
        "name": saved["name"], "revision": saved["revision"], "template_id": saved["template_id"],
        "blocks": saved["blocks"] + [b]})
    assert r.status_code == 200, r.text[:500]
    generate(client_v2, auth, r.json(), luca)
    assert sent_written(fake_v2) == {a["instance_id"]: {"commentary": {"by": "Anna", "at": AT}},
                                     b["instance_id"]: {"commentary": {"by": "Luca", "at": AT}}}


def test_a_new_layout_stamps_its_creator_and_the_revision_keeps_the_stamps(client_v2, auth, fake_v2, bed):
    f = v2blk("free_text", text="Our words.")
    ch = v2blk("chapter", title="Tests", intro="Why we tested.")
    lay = client_v2.post("/api/p/alpha/layouts", headers=anna(auth),
                         json={"name": "Stamped", "blocks": [ch, f]}).json()
    r = put_layout(client_v2, auth, lay, who="olga", blocks=[ch, {**f, "options": {"text": "Luca's words."}}])
    assert r.status_code == 200, r.text[:500]
    rows = bed.rows(pdb_of("A"), "SELECT revision, written FROM report_composer.layout_revision"
                                 f" WHERE layout_id = '{lay['id']}' ORDER BY revision")
    first, second = rows[0]["written"], rows[1]["written"]
    assert first[f["instance_id"]]["text"]["sub"] == "alice" and first[ch["instance_id"]]["intro"]["by"] == "Anna"
    assert second[f["instance_id"]]["text"]["sub"] == "olga" and second[ch["instance_id"]]["intro"]["by"] == "Anna"


def test_a_text_written_before_stamps_were_kept_is_sent_without_one(client_v2, auth, fake_v2, bed):
    a = v2blk("ai_card", commentary="Old words")
    lay = new_layout(client_v2, auth, who="alice", blocks=[a])
    # as a layout saved before this change: its revision has no stamps
    bed.psql(pdb_of("A"), "SET session_replication_role = replica;"
                          " UPDATE report_composer.layout_revision SET written = NULL"
                          f" WHERE layout_id = '{lay['id']}';")
    b = v2blk("ai_card", commentary="New words")
    r = put_layout(client_v2, auth, lay, who="olga", blocks=[a, b])
    assert r.status_code == 200, r.text[:500]
    generate(client_v2, auth, r.json(), luca)
    assert sent_written(fake_v2) == {a["instance_id"]: None, b["instance_id"]: {"commentary": {"by": "olga", "at": AT}}}


def test_a_duplicate_keeps_who_wrote_each_text(client_v2, auth, fake_v2):
    a = v2blk("ai_card", commentary="Commentary A")
    lay = client_v2.post("/api/p/alpha/layouts", headers=anna(auth), json={"name": "Source", "blocks": [a]}).json()
    copy = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/duplicate", json={"name": "Copy"}, headers=luca(auth))
    assert copy.status_code == 201, copy.text[:500]
    generate(client_v2, auth, copy.json(), luca)
    assert list(sent_written(fake_v2).values()) == [{"commentary": {"by": "Anna", "at": AT}}]


def test_a_layout_from_a_file_stamps_nobody(client_v2, auth, fake_v2):
    a = v2blk("ai_card", commentary="Commentary A")
    lay = client_v2.post("/api/p/alpha/layouts", headers=anna(auth), json={"name": "Source", "blocks": [a]}).json()
    exported = client_v2.get(f"/api/p/alpha/layouts/{lay['id']}/export?keep_text=true", headers=anna(auth))
    assert exported.status_code == 200, exported.text[:500]
    made = client_v2.post("/api/p/alpha/layouts", headers=luca(auth), json={"name": "From file", "file": exported.json()})
    assert made.status_code == 201, made.text[:500]
    generate(client_v2, auth, made.json(), luca)
    assert list(sent_written(fake_v2).values()) == [None]


def test_the_draft_preview_names_the_editor_for_the_texts_they_changed(client_v2, auth, fake_v2):
    a = v2blk("ai_card", commentary="Commentary A")
    lay = client_v2.post("/api/p/alpha/layouts", headers=anna(auth), json={"name": "Draft", "blocks": [a]}).json()
    b = v2blk("ai_card", commentary="Unsaved B")
    r = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/preview", headers=luca(auth),
                       json={"preview_with": {"system_id": IDS["A_V2"]}, "blocks": [a, b]})
    assert r.status_code == 200, r.text[:500]
    assert sent_written(fake_v2) == {a["instance_id"]: {"commentary": {"by": "Anna", "at": AT}},
                                     b["instance_id"]: {"commentary": {"by": "Luca", "at": AT}}}


def test_a_text_is_stamped_with_the_writers_display_name(client_v2, auth, fake_v2):
    # one name per person (docs/specs/who-does-what.md, section 7): the display name first, then the user name
    a = v2blk("ai_card", commentary="Commentary A")
    lay = new_layout(client_v2, auth, who="alice", blocks=[a])
    r = client_v2.put(f"/api/p/alpha/layouts/{lay['id']}", headers=auth("alice", username="anna", name="Anna Rossi"),
                      json={"name": lay["name"], "revision": lay["revision"], "template_id": lay["template_id"],
                            "blocks": [{**a, "options": {"commentary": "Commentary A by Anna"}}]})
    assert r.status_code == 200, r.text[:500]
    generate(client_v2, auth, r.json(), anna)
    assert sent_written(fake_v2)[a["instance_id"]]["commentary"]["by"] == "Anna Rossi"
