"""End to end: composer API -> real renderer -> PDF (report run 2026-09-23, stage 3 task; R7.4.1).

A throwaway bed with every module schema; project Echo has two system versions, a card each, an
objectives assessment each, one evaluation per version with measurements, one checklist with answers
of both versions, and one chart with a comment. The real renderer (aisc-report-generator, found via
REPORT_GENERATOR_DIR, default ../../../aisc-report-generator) runs as a subprocess on a free port with
its own environment; the composer talks to it with HttpRendererClient.

Erin (owner of Echo) builds a layout with every block type in a chosen order, pinned to version 2,
previews it and generates the PDF. The blocks appear in that order, only version 2 data is shown, and
pinned to version 1 the newer-results notices appear.
"""
import base64
import io
import os
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from conftest import IDS, blk, lazily, need, new_template, report_bed, report_bed_isolated, some_template

pytestmark = [pytest.mark.db, pytest.mark.e2e]
GENERATOR = Path(os.environ.get("REPORT_GENERATOR_DIR", Path(__file__).resolve().parents[4] / "aisc-report-generator"))
TOKEN = "e2e-token-" + "0" * 24


@pytest.fixture(scope="module")
def full_bed():
    report_bed.check_dsn_env()
    # isolation S-D13: the renderer and the composer read one database per project
    b = report_bed_isolated.build_isolated("e2e", modules=True)
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
def e2e_client(full_bed, renderer_url, make_client, monkeypatch):
    url, log = renderer_url
    if url is None:
        from conftest import Missing

        yield Missing("missing feature: the renderer service did not start:\n" + log.read_text()[-1500:])
        return
    monkeypatch.setenv("REPORT_COMPOSER_DATABASE_URL", full_bed.dsn("report_composer_rw", "platform"))
    monkeypatch.setenv("REPORT_COMPOSER_PROJECT_DATABASE_URL", full_bed.project_db_template("report_composer_rw"))
    Http = need("report_composer.renderer_client", "HttpRendererClient")
    from fastapi.testclient import TestClient

    from conftest import FIXED_NOW, ISSUER

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


ORDER = ["cover", "summary_coverage", "free_text", "dashboard_chart", "control_answers", "test_results",
         "risk_classification", "ai_card", "control_objectives"]


def blocks():
    options = {
        "cover": {"report_title": "Echo end-to-end"},
        "summary_coverage": {"links": [{"objective_id": "R1.1", "tests": ["LangBiTe"], "checklists": ["cl-e"]}]},
        "free_text": {"text": "Written by the editor."},
        "dashboard_chart": {"chart_id": IDS["CHART_E"]},
    }
    return [blk(t, title=f"S-{i:02d}", **options.get(t, {})) for i, t in enumerate(ORDER)]


def test_e2e_compose_preview_and_generate(e2e_client, auth):
    c = e2e_client
    erin = auth("erin")
    look = new_template(c, auth, slug="echo", who="erin", name="Echo look", font="liberation-serif",
                        primary_color="#123456", accent_color="#abcdef")
    r = c.post("/api/p/echo/layouts", json={"name": "Echo pack", "system_id": IDS["E_V2"], "blocks": blocks(),
                                           "template_id": look["id"]}, headers=erin)
    assert r.status_code == 201, r.text[:800]
    lay = r.json()
    assert [b["block_type"] for b in lay["blocks"]] == ORDER

    html = c.get(f"/api/p/echo/layouts/{lay['id']}/preview", headers=erin).text
    positions = [html.index(f'id="block-{b["instance_id"]}"') for b in lay["blocks"]]
    assert positions == sorted(positions)
    assert "E1MARK" not in html
    for marker in ("echo card E2MARK", "Answer E2MARK", "accuracy_E2MARK", "Echo comment", "Written by the editor."):
        assert marker in html, marker
    assert "is newer" not in html
    assert "--l-aif-primary: #123456" in html and "Liberation Serif" in html      # the template's look

    r = c.post(f"/api/p/echo/layouts/{lay['id']}/reports", json={}, headers=erin)
    assert r.status_code == 201, r.text[:800]
    report = r.json()
    assert report["status"] in ("done", "partial")
    assert [s["block_type"] for s in report["block_statuses"]] == ORDER
    pdf = c.get(f"/api/p/echo/reports/{report['id']}/pdf", headers=erin)
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    from pypdf import PdfReader  # noqa: installed with the generator's dev extra only when present

    full = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    last = [full.rindex(f"S-{i:02d}") for i in range(1, len(ORDER))]
    assert last == sorted(last) and "E1MARK" not in full


def test_e2e_pinned_to_version_1(e2e_client, auth):
    c = e2e_client
    erin = auth("erin")
    lay = c.post("/api/p/echo/layouts", json={"name": "Echo v1", "system_id": IDS["E_V1"],
                                             "blocks": [b for b in blocks() if b["block_type"] != "summary_coverage"],
                                             "template_id": some_template(c, auth, slug="echo", who="erin")},
                 headers=erin).json()
    html = c.get(f"/api/p/echo/layouts/{lay['id']}/preview", headers=erin).text
    assert "E2MARK" not in html
    assert "This report covers version 1. Version 2 is newer." in html
    assert "Newer results exist for version 2." in html
