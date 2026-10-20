"""A built-in layout generates reports exactly like the project's own: Download report on its
page, PDF or Word, its reports listed under it with Download PDF and Download Word. A report belongs to a
layout of the project, so each built-in has one record per project, made at its first report and kept in
step with the built-in at every report; it is not one of the project's layouts (not listed, its name stays
free, never edited). Database tests, fake renderer."""
import pytest

from conftest import IDS, PDF, new_layout, pdb_of
from v2_fakes import DOCX, client_v2, fake_v2  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]

B = "builtin-summary"


def generate(client_v2, auth, fmt="pdf", who="alice"):
    return client_v2.post(f"/api/p/alpha/layouts/{B}/reports", json={"system_id": IDS["A_V2"], "format": fmt},
                       headers=auth(who))


def test_a_built_in_generates_a_pdf_report_listed_under_it(client_v2, auth):
    r = generate(client_v2, auth)
    assert r.status_code == 201, r.text
    listed = client_v2.get(f"/api/p/alpha/layouts/{B}/reports", headers=auth("victor")).json()
    assert [x["id"] for x in listed] == [r.json()["id"]] and listed[0]["has_pdf"] is True
    pdf = client_v2.get(f"/api/p/alpha/reports/{r.json()['id']}/pdf", headers=auth("victor"))
    assert pdf.status_code == 200 and pdf.content == PDF


def test_a_built_in_generates_a_word_report_with_its_pdf(client_v2, auth):
    made = generate(client_v2, auth, "docx").json()
    assert client_v2.get(f"/api/p/alpha/reports/{made['id']}/download", headers=auth("victor")).content == DOCX
    assert client_v2.get(f"/api/p/alpha/reports/{made['id']}/pdf", headers=auth("victor")).content == PDF


def test_its_reports_share_one_record_that_is_not_a_project_layout(client_v2, auth, bed):
    generate(client_v2, auth)
    generate(client_v2, auth, "docx")
    rows = bed.rows(pdb_of("A"), "SELECT name FROM report_composer.layout WHERE builtin_id = 'builtin-summary'")
    assert len(rows) == 1
    assert [x["name"] for x in client_v2.get("/api/p/alpha/layouts", headers=auth("alice")).json()] == []
    # its name stays free for a layout of the project's own
    assert new_layout(client_v2, auth, name=rows[0]["name"])["name"] == rows[0]["name"]


def test_the_record_cannot_be_changed_or_deleted_as_a_layout(client_v2, auth, bed):
    generate(client_v2, auth)
    lid = bed.rows(pdb_of("A"), "SELECT id FROM report_composer.layout WHERE builtin_id = 'builtin-summary'")[0]["id"]
    assert client_v2.get(f"/api/p/alpha/layouts/{lid}", headers=auth("alice")).status_code == 404
    assert client_v2.delete(f"/api/p/alpha/layouts/{lid}", headers=auth("alice")).status_code == 404


def test_a_viewer_cannot_generate_one(client_v2, auth):
    assert generate(client_v2, auth, who="victor").status_code == 403


def test_the_built_ins_page_has_generate_and_its_reports(client_v2, auth):
    made = generate(client_v2, auth, "docx").json()
    page = client_v2.get(f"/p/alpha/layouts/{B}", headers=auth("alice")).text
    assert f"/layouts/{B}/download-report" in page and "Generate and download" in page
    assert f'/api/p/alpha/reports/{made["id"]}/pdf"' in page and "Download PDF" in page and "Download Word" in page
    assert "Generate and download" not in client_v2.get(f"/p/alpha/layouts/{B}", headers=auth("victor")).text


def test_the_generate_form_works_for_a_built_in(client_v2, auth):
    assert client_v2.get(f"/p/alpha/layouts/{B}/generate", headers=auth("alice")).status_code == 200
    r = client_v2.post(f"/p/alpha/layouts/{B}/generate", headers=auth("alice"), follow_redirects=False,
                    data={"system_id": IDS["A_V2"], "format": "pdf"})
    assert r.status_code == 303 and r.headers["location"].endswith(f"/p/alpha/layouts/{B}#reports")


def test_the_layouts_page_shows_a_built_ins_last_report(client_v2, auth):
    generate(client_v2, auth)
    page = client_v2.get("/p/alpha/", headers=auth("victor")).text
    row = page[page.index(f'data-layout="{B}"'):]
    row = row[:row.index("</tr>")]
    assert "(done)" in row


def test_two_first_reports_of_a_built_in_at_once_share_one_record(client_v2, auth, bed, fake_v2):
    """Both see no record yet; the second insert waits on the first's uncommitted row and, once that
    commits, must use it (the unique index on builtin_id) instead of failing with a 500."""
    import threading
    import time

    import psycopg
    from psycopg.rows import dict_row

    from conftest import FIXED_NOW
    from report_composer import builtin_layouts, builtin_reports

    assert client_v2.get("/api/p/alpha/layouts", headers=auth("alice")).status_code == 200   # migrated
    builtin = builtin_layouts.get(B, fake_v2.block_types())
    dsn = bed.dsn("report_composer_rw", pdb_of("A"))
    first = psycopg.connect(dsn, row_factory=dict_row)
    held = builtin_reports.record_for(first, builtin, "alice", FIXED_NOW)          # not committed yet
    second = {}

    def other():
        try:
            with psycopg.connect(dsn, row_factory=dict_row) as conn:
                second["id"] = builtin_reports.record_for(conn, builtin, "bob", FIXED_NOW)
        except Exception as exc:                                                   # noqa: BLE001
            second["error"] = exc

    thread = threading.Thread(target=other)
    thread.start()
    with psycopg.connect(dsn, autocommit=True) as watch:
        for _ in range(200):
            if watch.execute("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'"
                             " AND datname = current_database()").fetchone()[0]:
                break
            time.sleep(0.05)
        else:
            pytest.fail("the second record_for never waited on the first")
    first.commit()
    first.close()
    thread.join(timeout=30)
    assert "error" not in second, second.get("error")
    assert second["id"] == held
    assert len(bed.rows(pdb_of("A"), "SELECT id FROM report_composer.layout WHERE builtin_id = 'builtin-summary'")) == 1


def test_its_record_is_created_and_changed_with_ledger_events(client_v2, auth, bed, monkeypatch):
    # The record and its revisions were written with no event, so report.generated could
    # name a layout revision the ledger had never seen
    import json

    from report_composer import builtin_layouts

    monkeypatch.setenv("LEDGER_MODE", "record")
    assert generate(client_v2, auth).status_code == 201
    view = builtin_layouts._view
    monkeypatch.setattr(builtin_layouts, "_view",
                        lambda slug, types: {**view(slug, types), "description": "Changed by a deploy"})
    assert generate(client_v2, auth).status_code == 201
    [record] = bed.rows(pdb_of("A"), f"SELECT id::text AS id FROM report_composer.layout WHERE builtin_id = '{B}'")
    rows = bed.rows(pdb_of("A"), "SELECT json_build_object('action', action, 'item_version', item_version,"
                                 " 'details', details, 'before', before, 'after', after) AS e FROM ledger.outbox"
                                 f" WHERE item_id = '{record['id']}' ORDER BY occurred_at, event_id")
    events = [r["e"] if isinstance(r["e"], dict) else json.loads(r["e"]) for r in rows]
    assert [(e["action"], e["item_version"]) for e in events] == [("report.layout.created", "1"),
                                                                  ("report.layout.updated", "2")]
    created, updated = events
    assert created["details"] == {"from": "builtin", "builtin_id": B}
    assert updated["before"] == created["after"] and updated["after"]["description"] == "Changed by a deploy"
