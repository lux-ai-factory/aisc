"""End to end, report run v2: composer API -> real renderer -> PDF and DOCX (R-V1.3, R-V8.9,
R-V8.14, R-V8.15, R-U2.1, R-U3.1, R-V5.14, R-V5.15, R-S.3; part 2: R2-C.1, R2-D1.10, R2-D1.12, R2-D3.8.4).

A full throwaway bed (aisc-t-e2e2-*), project Mike (seed_tools.sql: the three Mijke tools on version 2).
The real renderer (aisc-report-generator via REPORT_GENERATOR_DIR, default the apps/report-generator submodule)
runs as a subprocess on a free port; the composer talks to it with HttpRendererClient.

Mia (owner of Mike) duplicates the built-in layout "eu-ai-act" on the platform default look,
sends a French language and a coverage map (which an older client may still do; both are ignored: all reports
are English, and the links come from step 4, evidence links 2026-09-30), previews a draft, generates a PDF and
a DOCX and downloads both. The preset's unwritten free text
("Write this section.") is left out of both documents.
"""
import io
import json
import os
import re
import socket
import subprocess
import time
import zipfile
from pathlib import Path

import httpx
import pytest

from conftest import FIXED_NOW, ISSUER, IDS, Missing, lazily, need, report_bed, report_bed_isolated

pytestmark = [pytest.mark.db, pytest.mark.e2e]
GENERATOR = Path(os.environ.get("REPORT_GENERATOR_DIR", Path(__file__).resolve().parents[2] / "report-generator"))
TOKEN = "e2e-v2-token-" + "0" * 24
EU = ["cover", "free_text", "key_figures", "chapter", "ai_card", "risk_classification", "chapter", "control_objectives", "control_answers", "summary_coverage", "chapter", "test_runs", "test_results", "chart", "changes_since", "free_text", "appendix", "free_text"]      # the built-in layout eu-ai-act (report modules 2026-09-28)


@pytest.fixture(scope="module")
def full_bed():
    report_bed.check_dsn_env()
    # isolation S-D13: the renderer and the composer read one database per project
    b = report_bed_isolated.build_isolated("e2e2", modules=True)
    yield b
    b.stop()


@pytest.fixture(scope="module")
def renderer_url(full_bed, tmp_path_factory):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert port != 5432
    env = {**os.environ, **full_bed.env(), "REPORT_SERVICE_TOKEN": TOKEN}
    env.pop("REPORT_CHART_IMAGES", None)
    log = tmp_path_factory.mktemp("renderer") / "renderer.log"
    proc = subprocess.Popen(["uv", "run", "--extra", "dev", "uvicorn", "report_service:app", "--host", "127.0.0.1",
                             "--port", str(port)], cwd=GENERATOR, env=env, stdout=log.open("w"),
                            stderr=subprocess.STDOUT)
    url, up = f"http://127.0.0.1:{port}", False
    for _ in range(60):
        if proc.poll() is not None:
            break
        try:
            if httpx.get(f"{url}/health", headers={"X-Report-Token": TOKEN}, timeout=1).status_code == 200:
                up = True
                break
        except httpx.HTTPError:
            pass
        time.sleep(1)
    yield url if up else None, log
    proc.terminate()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture
def e2e(full_bed, renderer_url, make_client, monkeypatch):
    url, log = renderer_url
    if url is None:
        yield Missing("missing feature: the renderer service did not start:\n" + log.read_text()[-1500:])
        return
    monkeypatch.setenv("REPORT_COMPOSER_DATABASE_URL", full_bed.dsn("report_composer_rw", "platform"))
    monkeypatch.setenv("REPORT_COMPOSER_PROJECT_DATABASE_URL", full_bed.project_db_template("report_composer_rw"))
    Http = need("report_composer.renderer_client", "HttpRendererClient")
    from fastapi.testclient import TestClient

    def build():
        app = need("report_composer.app", "create_app")(
            database_url=full_bed.dsn("report_composer_rw", "platform"),
            project_database_url=full_bed.project_db_template("report_composer_rw"), renderer=Http(url, token=TOKEN),
            clock=lambda: FIXED_NOW)
        c = TestClient(app, base_url="http://localhost")
        c.__enter__()
        return c

    c = lazily(build)
    yield c
    if type(c).__name__ != "Missing":
        c.__exit__(None, None, None)


def test_e2e_v2_preset_coverage_draft_pdf_and_docx(e2e, auth, full_bed):
    c, mia = e2e, auth("mia")
    r = c.post("/api/p/mike/layouts/builtin-eu-ai-act/duplicate", json={"name": "Mijke conformity"}, headers=mia)
    assert r.status_code == 201, r.text[:800]
    lay = r.json()
    assert [b["block_type"] for b in lay["blocks"]] == EU
    coverage = [{"objective_id": "R1.1", "tests": ["LangBiTe"], "checklists": ["cl-m1"]}]
    # the project's step 4 links, as the platform's Collect evidence page saves them
    full_bed.psql(report_bed.project_db(IDS["M"]),
                  "DELETE FROM evidence.link; INSERT INTO evidence.link (objective_id, kind, item_key, created_by)"
                  " VALUES ('R1.1', 'test', 'aisc-plugin-langbite', 'mia'), ('R1.1', 'control', 'cl-m1', 'mia')")
    links = [{"objective_id": "R1.1", "tests": ["aisc-plugin-langbite"], "checklists": ["cl-m1"]}]
    body = {k: lay[k] for k in ("name", "template_id", "revision", "blocks")}
    body.update(language="fr", coverage=coverage)
    saved = c.put(f"/api/p/mike/layouts/{lay['id']}", json=body, headers=mia)
    assert saved.status_code == 200, saved.text[:800]
    lay = saved.json()
    assert "language" not in lay and "coverage" not in lay

    # a draft preview: the saved blocks plus an unsaved free text
    draft_blocks = lay["blocks"] + [{"instance_id": "40000000-0000-4000-8000-000000000001",
                                     "block_type": "free_text", "options": {"text": "Unsaved DRAFTMARK",
                                                                            "format": "markdown"}}]
    d = c.post(f"/api/p/mike/layouts/{lay['id']}/preview",
               json={"preview_with": {"system_id": IDS["M_V2"]}, "template_id": None, "language": "fr",
                     "show_index": lay["show_index"], "numbering": lay["numbering"], "coverage": coverage,
                     "blocks": draft_blocks}, headers=mia)
    assert d.status_code == 200, d.text[:800]
    html = d.json()["html"]
    assert re.search(r'<html[^>]*\blang="en"', html)
    assert "DRAFTMARK" in html and "Content-Security-Policy" in html
    assert "gpt-4o-mini" in html                         # LangBiTe's group table, from the version's data
    assert "HARMFULPROMPTCONTENT" not in html
    # version 1's data shows only where the layout compares with it: its Changes since section
    from bs4 import BeautifulSoup
    doc = BeautifulSoup(html, "html.parser")
    changes = next(b["instance_id"] for b in lay["blocks"] if b["block_type"] == "changes_since")
    doc.find(id=f"block-{changes}").decompose()
    assert "M1MARK" not in str(doc)

    # PDF
    r = c.post(f"/api/p/mike/layouts/{lay['id']}/reports", json={"format": "pdf", "system_id": IDS["M_V2"]}, headers=mia)
    assert r.status_code == 201, r.text[:800]
    pdf_id = r.json()["id"]
    pdf = c.get(f"/api/p/mike/reports/{pdf_id}/download", headers=mia)
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    from pypdf import PdfReader

    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "The AI system" in text and "DRAFTMARK" not in text         # only the saved revision is generated
    assert "Write this section." not in text                           # R2-D3.8.4

    # DOCX
    r = c.post(f"/api/p/mike/layouts/{lay['id']}/reports", json={"format": "docx", "system_id": IDS["M_V2"]}, headers=mia)
    assert r.status_code == 201, r.text[:800]
    docx_id = r.json()["id"]
    docx = c.get(f"/api/p/mike/reports/{docx_id}/download", headers=mia)
    assert docx.status_code == 200
    assert docx.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    with zipfile.ZipFile(io.BytesIO(docx.content)) as z:
        body_xml = z.read("word/document.xml").decode("utf-8")
    assert "The AI system" in body_xml and "Evidence" in body_xml
    assert "Write this section." not in body_xml                       # R2-D3.8.4

    # what was stored: format, fingerprint, the v2 snapshot with the document id
    for rid, fmt in ((pdf_id, "pdf"), (docx_id, "docx")):
        stored = json.loads(full_bed.scalar(
            report_bed.project_db(IDS["M"]), "SELECT row_to_json(t)::text FROM (SELECT format, fingerprint, snapshot FROM"
                        f" report_composer.generated_report WHERE id = '{rid}') t"))
        assert stored["format"] == fmt
        assert re.fullmatch(r"[0-9a-f]{64}", stored["fingerprint"] or "")
        snap = stored["snapshot"]
        assert snap["snapshot_version"] == 3 and "language" not in snap and snap["mode"] == fmt
        assert snap["system_id"] == IDS["M_V2"] and snap["selection"]["other_versions"] is False
        assert snap["document"]["id"] == rid and snap["coverage_links"] == links
    listed = c.get(f"/api/p/mike/layouts/{lay['id']}/reports", headers=mia).json()
    assert sorted(x["format"] for x in listed) == ["docx", "pdf"]
