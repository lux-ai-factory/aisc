"""End to end, report run v2: composer API -> real renderer -> PDF and DOCX (R-V1.3, R-V8.1, R-V8.9,
R-V8.14, R-V8.15, R-U2.1, R-U3.1, R-V5.14, R-V5.15, R-S.3).

A full throwaway bed (aisc-t-e2e2-*), project Mike (seed_tools.sql: the three Mijke tools on version 2).
The real renderer (aisc-report-generator via REPORT_GENERATOR_DIR, default ../../../aisc-report-generator)
runs as a subprocess on a free port; the composer talks to it with HttpRendererClient.

Mia (owner of Mike) starts a layout from the built-in preset "eu-ai-act" on the platform default look,
sets French and a coverage map, previews a draft, generates a PDF and a DOCX and downloads both.
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

from conftest import FIXED_NOW, ISSUER, IDS, Missing, lazily, need, report_bed

pytestmark = [pytest.mark.db, pytest.mark.e2e]
GENERATOR = Path(os.environ.get("REPORT_GENERATOR_DIR", Path(__file__).resolve().parents[4] / "aisc-report-generator"))
TOKEN = "e2e-v2-token-" + "0" * 24
EU = ["cover", "key_figures", "chapter", "ai_card", "risk_classification", "chapter", "control_objectives",
      "summary_coverage", "chapter", "test_results", "control_answers", "appendix", "free_text"]


@pytest.fixture(scope="module")
def full_bed():
    report_bed.check_dsn_env()
    b = report_bed.build("e2e2")
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
    Http = need("report_composer.renderer_client", "HttpRendererClient")
    from fastapi.testclient import TestClient

    def build():
        app = need("report_composer.app", "create_app")(
            database_url=full_bed.dsn("report_composer_rw", "platform"), renderer=Http(url, token=TOKEN),
            clock=lambda: FIXED_NOW)
        c = TestClient(app, base_url="http://localhost")
        c.__enter__()
        return c

    c = lazily(build)
    yield c
    if type(c).__name__ != "Missing":
        c.__exit__(None, None, None)


def test_e2e_v2_preset_french_coverage_draft_pdf_and_docx(e2e, auth, full_bed):
    c, mia = e2e, auth("mia")
    r = c.post("/api/p/mike/layouts", json={"name": "Mijke conformity", "system_id": IDS["M_V2"],
                                           "template_id": None, "preset": "eu-ai-act"}, headers=mia)
    assert r.status_code == 201, r.text[:800]
    lay = r.json()
    assert [b["block_type"] for b in lay["blocks"]] == EU
    coverage = [{"objective_id": "R1.1", "tests": ["LangBiTe"], "checklists": ["cl-m1"]}]
    body = {k: lay[k] for k in ("name", "system_id", "template_id", "revision", "blocks")}
    body.update(language="fr", coverage=coverage)
    saved = c.put(f"/api/p/mike/layouts/{lay['id']}", json=body, headers=mia)
    assert saved.status_code == 200, saved.text[:800]
    lay = saved.json()
    assert lay["language"] == "fr" and lay["coverage"] == coverage

    # a draft preview: the saved blocks plus an unsaved free text
    draft_blocks = lay["blocks"] + [{"instance_id": "40000000-0000-4000-8000-000000000001",
                                     "block_type": "free_text", "options": {"text": "Unsaved DRAFTMARK",
                                                                            "format": "markdown"}}]
    d = c.post(f"/api/p/mike/layouts/{lay['id']}/preview",
               json={"system_id": lay["system_id"], "template_id": None, "language": "fr", "toc": lay["toc"],
                     "numbering": lay["numbering"], "coverage": coverage, "blocks": draft_blocks}, headers=mia)
    assert d.status_code == 200, d.text[:800]
    html = d.json()["html"]
    assert re.search(r'<html[^>]*\blang="fr"', html)
    assert "DRAFTMARK" in html and "Content-Security-Policy" in html
    assert "gpt-4o-mini" in html                         # LangBiTe's group table, from the version's data
    assert "M1MARK" not in html and "HARMFULPROMPTCONTENT" not in html

    # PDF
    r = c.post(f"/api/p/mike/layouts/{lay['id']}/reports", json={"format": "pdf"}, headers=mia)
    assert r.status_code == 201, r.text[:800]
    pdf_id = r.json()["id"]
    pdf = c.get(f"/api/p/mike/reports/{pdf_id}/download", headers=mia)
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    from pypdf import PdfReader

    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "System and risks" in text and "DRAFTMARK" not in text      # only the saved revision is generated

    # DOCX
    r = c.post(f"/api/p/mike/layouts/{lay['id']}/reports", json={"format": "docx"}, headers=mia)
    assert r.status_code == 201, r.text[:800]
    docx_id = r.json()["id"]
    docx = c.get(f"/api/p/mike/reports/{docx_id}/download", headers=mia)
    assert docx.status_code == 200
    assert docx.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    with zipfile.ZipFile(io.BytesIO(docx.content)) as z:
        body_xml = z.read("word/document.xml").decode("utf-8")
    assert "System and risks" in body_xml and "Evidence" in body_xml

    # what was stored: format, fingerprint, the v2 snapshot with the document id
    for rid, fmt in ((pdf_id, "pdf"), (docx_id, "docx")):
        stored = json.loads(full_bed.scalar(
            "platform", "SELECT row_to_json(t)::text FROM (SELECT format, fingerprint, snapshot FROM"
                        f" report_composer.generated_report WHERE id = '{rid}') t"))
        assert stored["format"] == fmt
        assert re.fullmatch(r"[0-9a-f]{64}", stored["fingerprint"] or "")
        snap = stored["snapshot"]
        assert snap["snapshot_version"] == 2 and snap["language"] == "fr" and snap["mode"] == fmt
        assert snap["document"]["id"] == rid and snap["coverage_links"] == coverage
    listed = c.get(f"/api/p/mike/layouts/{lay['id']}/reports", headers=mia).json()
    assert sorted(x["format"] for x in listed) == ["docx", "pdf"]
