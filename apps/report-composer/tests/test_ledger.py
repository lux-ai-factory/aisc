"""Step 6 in the ledger. Every composer write records its event with the project
database's ledger.emit (platform template 0020), in the write's own transaction, citing the witnessed
request and naming nobody; a layout keeps every revision it had (layout_revision, append-only); a
generated report records the ledger anchor it prints and its document's sha256. Database tests on the
bed, with a fake renderer."""
from __future__ import annotations

import hashlib
import json

import pytest

from conftest import IDS, PDF, blk, new_layout, new_template, pdb_of, put_layout

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]

REQUEST = "a9a9a9a9-0000-4000-8000-000000000001"


@pytest.fixture(autouse=True)
def ledger_on(monkeypatch):
    monkeypatch.setenv("LEDGER_MODE", "record")


def outbox(bed, item=None, key="A"):
    where = f"WHERE item_id = '{item}'" if item else ""
    rows = bed.rows(pdb_of(key), "SELECT json_build_object('action', action, 'item_type', item_type, 'item_id', item_id,"
                                 " 'request_id', request_id, 'db_role', db_role, 'details', details, 'content', content,"
                                 " 'before', before, 'after', after, 'item_version', item_version) AS e"
                                 f" FROM ledger.outbox {where} ORDER BY occurred_at, event_id")
    return [r["e"] if isinstance(r["e"], dict) else json.loads(r["e"]) for r in rows]


def headers(auth, who="alice"):
    return {**auth(who), "X-AISC-Request-Id": REQUEST}


def test_a_layouts_life_is_recorded_in_its_transactions(client, auth, bed):
    lay = new_layout(client, auth, name="Ledger layout", blocks=[blk("free_text", text="first")])
    r = put_layout(client, auth, lay, name="Ledger layout", blocks=[blk("free_text", text="second")])
    assert r.status_code == 200, r.text
    dup = client.post(f"/api/p/alpha/layouts/{lay['id']}/duplicate", json={"name": "Copy"}, headers=headers(auth))
    assert dup.status_code == 201
    assert client.delete(f"/api/p/alpha/layouts/{lay['id']}", headers=headers(auth)).status_code == 204
    mine = outbox(bed, lay["id"])
    assert [e["action"] for e in mine] == ["report.layout.created", "report.layout.updated", "report.layout.deleted"]
    assert {e["db_role"] for e in mine} == {"report_composer_rw"}
    created, updated, deleted = mine
    assert created["after"]["blocks"][0]["options"]["text"] == "first"
    assert updated["before"] == created["after"]                      # the item's chain holds
    assert updated["after"]["blocks"][0]["options"]["text"] == "second"
    assert (updated["item_version"], updated["details"]) == ("2", {"revision": 2})
    assert deleted["before"] == updated["after"]
    [copied] = outbox(bed, dup.json()["id"])
    assert copied["action"] == "report.layout.created" and copied["details"] == {"from": "duplicate"}
    assert "alice" not in json.dumps(mine + [copied])                 # never who: the witness says


def test_m1_every_revision_of_a_layout_is_kept(client, auth, bed):
    lay = new_layout(client, auth, name="Kept", blocks=[blk("free_text", text="one")])
    put_layout(client, auth, lay, blocks=[blk("free_text", text="two")])
    assert client.delete(f"/api/p/alpha/layouts/{lay['id']}", headers=auth("alice")).status_code == 204
    kept = bed.rows(pdb_of("A"), "SELECT revision, state FROM report_composer.layout_revision"
                                 f" WHERE layout_id = '{lay['id']}' ORDER BY revision")
    texts = [(r["revision"], (r["state"] if isinstance(r["state"], dict) else json.loads(r["state"]))
              ["blocks"][0]["options"]["text"]) for r in kept]
    assert texts == [(1, "one"), (2, "two")]                         # after the layout itself is gone


@pytest.mark.parametrize("change", [
    "UPDATE report_composer.layout_revision SET revision = revision + 10",
    "DELETE FROM report_composer.layout_revision",
    "TRUNCATE report_composer.layout_revision",
])
def test_m1_the_revisions_are_append_only(client, auth, bed, change):
    new_layout(client, auth, name="Locked")
    r = bed.psql(pdb_of("A"), change, check=False)
    assert r.returncode != 0 and "append-only" in (r.stderr or "") + (r.stdout or "")


def test_templates_are_recorded_with_their_logo_as_a_digest(client, auth, bed):
    logo = {"mime": "image/png", "data_base64": "iVBORw0KGgo="}
    t = new_template(client, auth, name="Ledger look", logo=logo)
    body = {"name": "Ledger look 2", "font": "inter", "font_size_pt": 11, "primary_color": "#000000",
            "accent_color": "#ffffff", "keep_logo": True}
    assert client.put(f"/api/p/alpha/templates/{t['id']}", json=body, headers=headers(auth)).status_code == 200
    assert client.delete(f"/api/p/alpha/templates/{t['id']}", headers=headers(auth)).status_code == 204
    mine = outbox(bed, t["id"])
    assert [e["action"] for e in mine] == ["report.template.created", "report.template.updated",
                                           "report.template.deleted"]
    assert mine[0]["after"]["logo_sha256"] == hashlib.sha256(bytes.fromhex("89504e470d0a1a0a")).hexdigest()
    assert "iVBOR" not in json.dumps(mine)                           # the image itself is not in the ledger
    assert mine[1]["before"] == mine[0]["after"] and mine[2]["before"] == mine[1]["after"]


def _generate(client, auth, layout_id, **body):
    return client.post(f"/api/p/alpha/layouts/{layout_id}/reports", json={"system_id": IDS["A_V2"], **body},
                       headers=headers(auth))


def test_m3_a_generated_report_records_its_document_and_the_anchor_it_prints(client, auth, bed, fake_renderer,
                                                                            monkeypatch):
    from report_composer import anchor

    monkeypatch.setattr(anchor, "fetch", lambda request, project: {"seq": 41, "entry_sha256": "ab" * 32})
    lay = new_layout(client, auth, name="Anchored", blocks=[blk("free_text", text="x")])
    r = _generate(client, auth, lay["id"])
    assert r.status_code == 201, r.text
    report_id = r.json()["id"]
    assert fake_renderer.snapshots[-1]["document"]["ledger_anchor"] == {"seq": 41, "entry_sha256": "ab" * 32}
    [generated] = outbox(bed, report_id)
    assert generated["action"] == "report.generated" and generated["request_id"] == REQUEST
    assert generated["details"] == {"card_version": IDS["A_V2"], "ledger_head": 41, "blocks": 1,
                                    "document_sha256": hashlib.sha256(PDF).hexdigest(), "format": "pdf"}
    assert generated["content"]["anchor"] == {"seq": 41, "entry_sha256": "ab" * 32}
    assert generated["content"]["layout"] == {"id": lay["id"], "revision": 1}


def test_m3_without_a_ledger_head_the_report_prints_none(client, auth, bed, fake_renderer, monkeypatch):
    from report_composer import anchor

    monkeypatch.setattr(anchor, "fetch", lambda request, project: None)
    lay = new_layout(client, auth, name="No head", blocks=[blk("free_text", text="x")])
    assert _generate(client, auth, lay["id"]).status_code == 201
    assert "ledger_anchor" not in fake_renderer.snapshots[-1]["document"]


def test_a_failed_report_is_recorded_with_its_code(client, auth, bed, fake_renderer):
    from report_composer.renderer_client import RendererUnavailable

    fake_renderer.fail = RendererUnavailable("down at http://renderer?token=secret")
    lay = new_layout(client, auth, name="Fails", blocks=[blk("free_text", text="x")])
    r = _generate(client, auth, lay["id"])
    assert r.status_code == 502
    report_id = r.json()["error"]["details"][0]["report_id"]
    [failed] = outbox(bed, report_id)
    assert failed["action"] == "report.failed" and failed["details"]["error"] == "renderer_unavailable"
    assert "secret" not in json.dumps(failed)


def test_a_download_is_recorded(client, auth, bed, monkeypatch):
    from report_composer import anchor

    monkeypatch.setattr(anchor, "fetch", lambda request, project: None)
    lay = new_layout(client, auth, name="Downloaded", blocks=[blk("free_text", text="x")])
    report_id = _generate(client, auth, lay["id"]).json()["id"]
    assert client.get(f"/api/p/alpha/reports/{report_id}/download", headers=headers(auth, "victor")).status_code == 200
    downloaded = [e for e in outbox(bed, report_id) if e["action"] == "report.downloaded"]
    assert [d["details"] for d in downloaded] == [{"document_sha256": hashlib.sha256(PDF).hexdigest()}]


def test_a_failure_after_the_event_leaves_neither(client, auth, bed, monkeypatch):
    from report_composer import ledger

    real = ledger.emit

    def then_fail(conn, action, **fields):
        real(conn, action, **fields)
        if action == "report.layout.created":
            raise RuntimeError("a failure right after the event (test)")
    monkeypatch.setattr(ledger, "emit", then_fail)
    with pytest.raises(RuntimeError):
        client.post("/api/p/alpha/layouts", json={"name": "Never"}, headers=headers(auth))
    assert bed.scalar(pdb_of("A"), "SELECT count(*) FROM report_composer.layout WHERE name = 'Never'") == "0"
    assert [e for e in outbox(bed) if (e["after"] or {}).get("name") == "Never"] == []


def test_with_the_ledger_off_nothing_is_written(client, auth, bed, monkeypatch):
    monkeypatch.setenv("LEDGER_MODE", "off")
    lay = new_layout(client, auth, name="Off")
    assert outbox(bed, lay["id"]) == []


def test_a_request_id_that_is_not_a_uuid_is_never_cited(client, auth, bed):
    r = client.post("/api/p/alpha/layouts", json={"name": "Odd id"}, headers={**auth("alice"),
                                                                             "X-AISC-Request-Id": "x; DROP"})
    assert r.status_code == 201
    assert [e["request_id"] for e in outbox(bed, r.json()["id"])] == [None]


def test_m1_review_deleting_a_template_records_each_layout_it_leaves(client, auth, bed):
    """The layouts of a deleted template lose it (they draw in the platform look); each
    gets its next revision, kept, and an event in the delete's transaction, so its chain holds."""
    t = new_template(client, auth, name="Going away")
    lay = new_layout(client, auth, name="Uses it", template_id=t["id"], blocks=[blk("free_text", text="x")])
    assert client.delete(f"/api/p/alpha/templates/{t['id']}", headers=headers(auth)).status_code == 204
    now = client.get(f"/api/p/alpha/layouts/{lay['id']}", headers=auth("alice")).json()
    assert (now["template_id"], now["revision"]) == (None, 2)
    created, removed = outbox(bed, lay["id"])
    assert removed["action"] == "report.layout.template_removed" and removed["request_id"] == REQUEST
    assert removed["before"] == created["after"] and removed["after"]["template_id"] is None
    assert (removed["item_version"], removed["details"]) == ("2", {"revision": 2, "template": t["id"]})
    kept = bed.rows(pdb_of("A"), "SELECT revision FROM report_composer.layout_revision"
                                 f" WHERE layout_id = '{lay['id']}' ORDER BY revision")
    assert [r["revision"] for r in kept] == [1, 2]
    r = put_layout(client, auth, now, blocks=now["blocks"])                 # the next save continues it
    assert r.status_code == 200
    assert outbox(bed, lay["id"])[-1]["before"] == removed["after"]


def _fail_after(monkeypatch, wanted):
    from report_composer import ledger

    real = ledger.emit

    def then_fail(conn, action, **fields):
        real(conn, action, **fields)
        if action == wanted:
            raise RuntimeError("a failure right after the event (test)")
    monkeypatch.setattr(ledger, "emit", then_fail)


def test_m1_review_an_update_that_fails_after_its_event_leaves_neither(client, auth, bed, monkeypatch):
    lay = new_layout(client, auth, name="Stays", blocks=[blk("free_text", text="one")])
    _fail_after(monkeypatch, "report.layout.updated")
    with pytest.raises(RuntimeError):
        put_layout(client, auth, lay, blocks=[blk("free_text", text="two")])
    assert bed.scalar(pdb_of("A"), f"SELECT revision FROM report_composer.layout WHERE id = '{lay['id']}'") == "1"
    assert [e["action"] for e in outbox(bed, lay["id"])] == ["report.layout.created"]


def test_m1_review_a_delete_that_fails_after_its_event_leaves_neither(client, auth, bed, monkeypatch):
    lay = new_layout(client, auth, name="Not gone")
    _fail_after(monkeypatch, "report.layout.deleted")
    with pytest.raises(RuntimeError):
        client.delete(f"/api/p/alpha/layouts/{lay['id']}", headers=headers(auth))
    assert bed.scalar(pdb_of("A"), f"SELECT deleted_at IS NULL FROM report_composer.layout WHERE id = '{lay['id']}'") == "t"
    assert [e["action"] for e in outbox(bed, lay["id"])] == ["report.layout.created"]


def test_m1_review_a_template_save_that_fails_after_its_event_leaves_neither(client, auth, bed, monkeypatch):
    t = new_template(client, auth, name="Kept look")
    _fail_after(monkeypatch, "report.template.updated")
    body = {"name": "Changed look", "font": "inter", "font_size_pt": 11, "primary_color": "#000000",
            "accent_color": "#ffffff"}
    with pytest.raises(RuntimeError):
        client.put(f"/api/p/alpha/templates/{t['id']}", json=body, headers=headers(auth))
    assert bed.scalar(pdb_of("A"), f"SELECT name FROM report_composer.template WHERE id = '{t['id']}'") == "Kept look"


def test_m1_review_a_finished_report_that_fails_after_its_event_stays_running(client, auth, bed, monkeypatch):
    from report_composer import anchor

    monkeypatch.setattr(anchor, "fetch", lambda request, project: None)
    lay = new_layout(client, auth, name="Half done", blocks=[blk("free_text", text="x")])
    _fail_after(monkeypatch, "report.generated")
    with pytest.raises(RuntimeError):
        _generate(client, auth, lay["id"])
    statuses = bed.rows(pdb_of("A"), "SELECT status FROM report_composer.generated_report"
                                     f" WHERE layout_id = '{lay['id']}'")
    assert [s["status"] for s in statuses] == ["running"]               # not finished, and no event
    assert [e for e in outbox(bed) if e["action"] == "report.generated"
            and (e["content"] or {}).get("layout", {}).get("id") == lay["id"]] == []


def test_m7_review_a_copy_name_ignores_deleted_layouts(client, auth):
    lay = new_layout(client, auth, name="Source")
    first = client.post(f"/api/p/alpha/layouts/{lay['id']}/duplicate", json={}, headers=auth("alice")).json()
    assert client.delete(f"/api/p/alpha/layouts/{first['id']}", headers=auth("alice")).status_code == 204
    again = client.post(f"/api/p/alpha/layouts/{lay['id']}/duplicate", json={}, headers=auth("alice")).json()
    assert again["name"] == first["name"]                               # the hidden copy frees its name
