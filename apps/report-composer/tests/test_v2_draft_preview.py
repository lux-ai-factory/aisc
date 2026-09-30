"""U3: a preview of unsaved changes (report run v2, 01-specs.md section 10: R-U3.1 to R-U3.6).

POST /api/p/{ref}/layouts/{id}/preview takes the editor's state and stores nothing. The debounce,
single-flight and "older answer ignored" behaviour of composer.js (R-U3.4) is browser behaviour: the
static checks below pin its visible parts; the timing itself is checked by hand (see 02-tests.md).
"""
from pathlib import Path

import pytest

from conftest import IDS, error_code, new_layout, new_template
from v2_fakes import client_v2, fake_v2, unique, v2blk  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]
JS = Path(__file__).resolve().parents[1] / "report_composer/static/composer.js"
CSP_META = "default-src 'none'; img-src data:; style-src 'unsafe-inline'"


def layout(client, auth):
    return new_layout(client, auth, name=unique("Draft"), system_id=IDS["A_V2"],
                      blocks=[v2blk("cover"), v2blk("free_text", text="saved text")])


def draft(lay, **over):
    body = {"template_id": lay["template_id"], "show_index": True,
            "numbering": False, "coverage": [], "blocks": lay["blocks"],
            "preview_with": {"system_id": IDS["A_V2"]}}
    body.update(over)
    return body


def post(client, auth, lay, body, who="alice", **kw):
    return client.post(f"/api/p/alpha/layouts/{lay['id']}/preview", json=body, headers=auth(who, **kw))


# ── R-U3.1 ──────────────────────────────────────────────────────────────────

def test_r_u3_1_the_draft_is_rendered_and_nothing_is_stored(client_v2, auth, fake_v2):
    lay = layout(client_v2, auth)
    blocks = [v2blk("ai_card"), v2blk("free_text", text="unsaved text")]
    r = post(client_v2, auth, lay, draft(lay, blocks=blocks, language="fr", show_index=True, numbering=True))
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert set(body) >= {"html", "problems", "block_statuses"}
    sent = fake_v2.snapshots[-1]
    assert sent["mode"] == "preview" and [b["instance_id"] for b in sent["blocks"]] == [b["instance_id"] for b in blocks]
    # R2-D1.10, R2-D1.12: the draft's language is accepted and ignored; the snapshot carries none
    assert "language" not in sent and (sent.get("document") or {}).get("toc") == "on"
    again = client_v2.get(f"/api/p/alpha/layouts/{lay['id']}", headers=auth("alice")).json()
    assert again["revision"] == 1 and again["blocks"] == lay["blocks"]


def test_r_u3_1_problems_are_returned_but_do_not_stop_the_preview(client_v2, auth, fake_v2):
    lay = layout(client_v2, auth)
    bad = v2blk("dashboard_chart", width=5)
    # an old client's coverage map is ignored (evidence links 2026-09-30, D5), so it raises no problem
    r = post(client_v2, auth, lay, draft(lay, blocks=[bad], coverage=[{"objective_id": "R9.9", "tests": [],
                                                                        "checklists": ["cl-1"]}]))
    assert r.status_code == 200
    pointers = {p["pointer"] for p in r.json()["problems"]}
    assert "/width" in pointers and not any(p.startswith("/coverage") for p in pointers)
    assert fake_v2.snapshots[-1]["blocks"][0]["instance_id"] == bad["instance_id"]


def test_r_u3_1_a_viewer_cannot_post_a_draft(client_v2, auth):
    lay = layout(client_v2, auth)
    assert post(client_v2, auth, lay, draft(lay), who="victor").status_code == 403


def test_r_u3_1_a_draft_needs_the_same_origin(client_v2, auth):
    lay = layout(client_v2, auth)
    assert post(client_v2, auth, lay, draft(lay), origin="http://evil.example").status_code == 403


# ── R-U3.2 ──────────────────────────────────────────────────────────────────

def test_r_u3_2_a_version_of_another_project_is_never_previewed(client_v2, auth, fake_v2):
    """Report modules 2026-09-28: the preview's version is not stored; one that is not the project's
    falls back to the project's latest, never to the other project's."""
    lay = layout(client_v2, auth)
    r = post(client_v2, auth, lay, draft(lay, preview_with={"system_id": IDS["B_V1"]}))
    assert r.status_code == 200, r.text[:300]
    assert fake_v2.snapshots[-1]["system_id"] == IDS["A_V3"]


def test_r_u3_2_the_template_must_be_of_the_project(client_v2, auth):
    lay = layout(client_v2, auth)
    other = new_template(client_v2, auth, slug="gamma", name=unique("Gamma"))
    r = post(client_v2, auth, lay, draft(lay, template_id=other["id"]))
    assert r.status_code == 422 and error_code(r) == "template_not_in_project"


def test_r_u3_2_a_body_over_1_mb_is_413(client_v2, auth):
    lay = layout(client_v2, auth)
    r = post(client_v2, auth, lay, draft(lay, blocks=[v2blk("free_text", text="x" * (1024 * 1024 + 10))]))
    assert r.status_code == 413 and error_code(r) == "too_large"


@pytest.mark.parametrize("failure,status", [("unavailable", 502), ("timeout", 504)])
def test_r_u3_2_renderer_failures(client_v2, auth, fake_v2, failure, status):
    from report_composer.renderer_client import RendererTimeout, RendererUnavailable

    lay = layout(client_v2, auth)
    fake_v2.fail = RendererTimeout("slow") if failure == "timeout" else RendererUnavailable("down")
    assert post(client_v2, auth, lay, draft(lay)).status_code == status


# ── R-U3.3 ──────────────────────────────────────────────────────────────────

def test_r_u3_3_the_html_has_the_csp_meta_as_first_head_element(client_v2, auth):
    from bs4 import BeautifulSoup

    lay = layout(client_v2, auth)
    r = post(client_v2, auth, lay, draft(lay))
    assert r.status_code == 200
    head = BeautifulSoup(r.json()["html"], "html.parser").find("head")
    first = head.find(True)
    assert first.name == "meta" and first.get("http-equiv") == "Content-Security-Policy"
    assert first.get("content") == CSP_META


def test_r_u3_3_the_iframe_keeps_an_empty_sandbox(client_v2, auth):
    from bs4 import BeautifulSoup

    lay = layout(client_v2, auth)
    iframe = BeautifulSoup(client_v2.get(f"/p/alpha/layouts/{lay['id']}", headers=auth("alice")).text,
                           "html.parser").find("iframe")
    assert iframe is not None and iframe.has_attr("sandbox") and not iframe.get("sandbox")


# ── R-U3.4, R-U3.5 composer.js (static; timing is browser only) ──────────────

def test_r_u3_4_composer_js_posts_drafts_with_a_1_5_s_pause():
    js = JS.read_text()
    assert '"/preview"' in js and "POST" in js and "1500" in js, "missing feature: draft preview in composer.js"
    assert "srcdoc" in js


def test_r_u3_4_refresh_button_and_auto_refresh_checkbox(client_v2, auth):
    from bs4 import BeautifulSoup

    lay = layout(client_v2, auth)
    doc = BeautifulSoup(client_v2.get(f"/p/alpha/layouts/{lay['id']}", headers=auth("alice")).text, "html.parser")
    refresh = doc.find(attrs={"data-control": "refresh-preview"})
    assert refresh is not None and refresh.get_text(strip=True) == "Refresh preview"
    auto = doc.find("input", attrs={"data-control": "auto-refresh"})
    assert auto is not None and auto.get("type") == "checkbox" and auto.has_attr("checked")
    assert "Auto-refresh" in doc.get_text()


def test_r_u3_4_auto_refresh_is_remembered_in_local_storage_inside_try_catch():
    js = JS.read_text()
    i = js.find("localStorage")
    assert i >= 0, "missing feature: auto-refresh remembered per browser"
    assert "try" in js[max(0, i - 200):i]


def test_r_u3_5_preview_labels():
    js = JS.read_text()
    assert "Preview of unsaved changes" in js and "Preview of revision" in js


def test_r_u3_5_the_label_is_on_the_page(client_v2, auth):
    from bs4 import BeautifulSoup

    lay = layout(client_v2, auth)
    doc = BeautifulSoup(client_v2.get(f"/p/alpha/layouts/{lay['id']}", headers=auth("alice")).text, "html.parser")
    label = doc.find(attrs={"data-preview-label": True})
    assert label is not None and label.get_text(strip=True) == "Preview of revision 1"


# ── R-U3.6 ──────────────────────────────────────────────────────────────────

def test_r_u3_6_viewers_keep_the_get_preview_and_generate_uses_the_saved_revision(client_v2, auth, fake_v2):
    lay = layout(client_v2, auth)
    post(client_v2, auth, lay, draft(lay, blocks=[v2blk("ai_card")]))
    assert client_v2.get(f"/api/p/alpha/layouts/{lay['id']}/preview", headers=auth("victor")).status_code == 200
    r = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={"system_id": IDS["A_V2"]}, headers=auth("alice"))
    assert r.status_code == 201
    pdf_snaps = [s for s in fake_v2.snapshots if s["mode"] == "pdf"]
    assert [b["instance_id"] for b in pdf_snaps[-1]["blocks"]] == [b["instance_id"] for b in lay["blocks"]]
    assert any(s["mode"] == "preview" and s["blocks"][0]["block_type"] == "ai_card" for s in fake_v2.snapshots), \
        "missing feature: the draft preview never reached the renderer"
