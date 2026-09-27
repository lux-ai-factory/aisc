"""Preview and generation (report run 2026-09-23: R3.8, R3.12, R4.2.4, R4.2.5, R4.3.3 to R4.3.5,
R7.2.2, R7.2.5, R7.2.6, R7.3.4, R7.3.5, D12). Database tests, fake renderer."""
import re

import pytest

from conftest import FIXED_NOW, IDS, PDF, blk, error_code, need, new_layout, put_layout

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def layout(client, auth, blocks=None):
    return new_layout(client, auth, name="Quarterly report", system_id=IDS["A_V2"],
                      blocks=blocks if blocks is not None else [blk("cover"), blk("free_text", text="x")])


# R4.2.4, R7.3.4
def test_r4_2_4_preview_is_of_the_saved_revision_with_a_strict_csp(client, auth, fake_renderer):
    lay = layout(client, auth)
    r = client.get(f"/api/p/alpha/layouts/{lay['id']}/preview", headers=auth("victor"))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert r.headers["content-security-policy"] == "default-src 'none'; img-src data:; style-src 'unsafe-inline'"
    sent = fake_renderer.snapshots[-1]
    assert sent["mode"] == "preview" and [b["instance_id"] for b in sent["blocks"]] == [b["instance_id"] for b in lay["blocks"]]
    assert sent["project_id"] == IDS["A"] and sent["system_id"] == IDS["A_V2"]
    assert sent["layout"] == {"id": lay["id"], "name": "Quarterly report", "revision": 1}


# R4.2.5, R7.2.6, R3.12, D12
def test_r4_2_5_generate_stores_the_snapshot_and_the_pdf(client, auth, fake_renderer, bed):
    lay = layout(client, auth)
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={}, headers=auth("alice", username="Alice Editor"))
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "done" and len(body["block_statuses"]) == 2
    sent = fake_renderer.snapshots[-1]
    assert sent["mode"] == "pdf" and sent["requested_by"] == "Alice Editor"
    stored = bed.rows("platform", f"SELECT layout_revision, status, size_bytes, sha256, snapshot FROM report_composer.generated_report WHERE id = '{body['id']}'")[0]
    assert stored["layout_revision"] == 1 and stored["size_bytes"] == len(PDF)
    assert [b["instance_id"] for b in stored["snapshot"]["blocks"]] == [b["instance_id"] for b in lay["blocks"]]


# R3.12: later edits do not change the stored snapshot
def test_r3_12_the_snapshot_survives_edits(client, auth, bed):
    lay = layout(client, auth)
    rid = client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={}, headers=auth("alice")).json()["id"]
    put_layout(client, auth, lay, blocks=[blk("ai_card")])
    snap = bed.rows("platform", f"SELECT snapshot FROM report_composer.generated_report WHERE id = '{rid}'")[0]["snapshot"]
    assert [b["block_type"] for b in snap["blocks"]] == ["cover", "free_text"]


# R4.3 download, R4.3.4
def test_r4_3_4_download(client, auth):
    lay = layout(client, auth)
    rid = client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={}, headers=auth("alice")).json()["id"]
    r = client.get(f"/api/p/alpha/reports/{rid}/pdf", headers=auth("victor"))
    assert r.status_code == 200 and r.content == PDF
    assert r.headers["content-type"] == "application/pdf"
    assert 'attachment; filename="alpha-v2-quarterly-report-20260920-1030.pdf"' in r.headers["content-disposition"]


def test_r4_3_reports_list(client, auth):
    lay = layout(client, auth)
    client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={}, headers=auth("alice"))
    rows = client.get(f"/api/p/alpha/layouts/{lay['id']}/reports", headers=auth("victor")).json()
    assert len(rows) == 1
    assert set(rows[0]) >= {"id", "layout_revision", "status", "created_at", "created_by", "size_bytes"}


# R3.8
def test_r3_8_an_empty_layout_is_not_generated(client, auth):
    lay = layout(client, auth, blocks=[])
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={}, headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) == "empty_layout"


# R4.3.5
def test_r4_3_5_some_blocks_in_error_is_partial_and_downloadable(client, auth, fake_renderer):
    lay = layout(client, auth)
    fake_renderer.error_blocks = {lay["blocks"][1]["instance_id"]}
    body = client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={}, headers=auth("alice")).json()
    assert body["status"] == "partial"
    assert client.get(f"/api/p/alpha/reports/{body['id']}/pdf", headers=auth("alice")).status_code == 200


def test_r4_3_5_the_renderer_failing_is_502_and_failed(client, auth, fake_renderer, bed):
    Unavailable = need("report_composer.renderer_client", "RendererUnavailable")
    lay = layout(client, auth)
    fake_renderer.fail = Unavailable("down")
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={}, headers=auth("alice"))
    assert r.status_code == 502 and error_code(r) == "renderer_unavailable"
    row = bed.rows("platform", f"SELECT status, pdf IS NULL AS no_pdf, error_ref FROM report_composer.generated_report WHERE layout_id = '{lay['id']}'")[0]
    assert row["status"] == "failed" and row["no_pdf"] and re.fullmatch(r"[0-9a-f]{8}", row["error_ref"])
    assert row["error_ref"] in r.text


# R7.2.2
def test_r7_2_2_a_renderer_timeout_is_504_and_failed(client, auth, fake_renderer, bed):
    Timeout = need("report_composer.renderer_client", "RendererTimeout")
    lay = layout(client, auth)
    fake_renderer.fail = Timeout("120 s")
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={}, headers=auth("alice"))
    assert r.status_code == 504 and error_code(r) == "renderer_timeout"
    assert bed.scalar("platform", f"SELECT status FROM report_composer.generated_report WHERE layout_id = '{lay['id']}'") == "failed"


def test_r7_2_2_the_http_client_times_out_at_120_seconds():
    client = need("report_composer.renderer_client", "HttpRendererClient")("http://report-renderer:8001", token="t")
    assert client.timeout == 120.0


# R7.2.5
def test_r7_2_5_a_pdf_over_25_mb_is_not_stored(client, auth, fake_renderer, bed):
    lay = layout(client, auth)
    fake_renderer.pdf = b"%PDF-" + b"0" * (25 * 1024 * 1024)
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={}, headers=auth("alice"))
    assert "pdf_too_large" in r.text
    row = bed.rows("platform", f"SELECT status, pdf IS NULL AS no_pdf FROM report_composer.generated_report WHERE layout_id = '{lay['id']}'")[0]
    assert row == {"status": "failed", "no_pdf": True}


# R4.3.3
def test_r4_3_3_one_generation_at_a_time(client, auth, bed):
    lay = layout(client, auth)
    bed.psql("platform", "INSERT INTO report_composer.generated_report (id, layout_id, layout_revision, project_id, "
                         "system_id, snapshot, status, created_by, created_at) VALUES (gen_random_uuid(), "
                         f"'{lay['id']}', 1, '{IDS['A']}', '{IDS['A_V2']}', '{{}}', 'running', 'olga', now())")
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={}, headers=auth("alice"))
    assert r.status_code == 409 and error_code(r) == "generation_running"


# R4.3.2, R7.3.1
def test_r4_3_2_a_report_of_another_project_is_404(client, auth):
    lay = layout(client, auth)
    rid = client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={}, headers=auth("alice")).json()["id"]
    r = client.get(f"/api/p/beta/reports/{rid}/pdf", headers=auth("bob"))
    assert r.status_code == 404


# R7.3.5
def test_r7_3_5_the_service_token_never_reaches_a_response(client, auth, fake_renderer):
    lay = layout(client, auth)
    texts = [client.get(f"/api/p/alpha/layouts/{lay['id']}/preview", headers=auth("alice")).text,
             client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={}, headers=auth("alice")).text,
             client.get("/api/block-types", headers=auth("alice")).text,
             client.get("/p/alpha/", headers=auth("alice")).text]
    assert not any("composer-test-token-0123456789" in t for t in texts)
