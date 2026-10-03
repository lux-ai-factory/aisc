"""M1-M3 (phase 9): the report composer's events, in the shapes its handlers send
(apps/report-composer/report_composer/api.py, pages.py, reports.py), are accepted by the relay against the
REAL registry, each citing the witnessed request of the route it is posted to, as report_composer_rw.
The composer's API is served at /report-composer/api/p/<slug>/..., its pages at /report-composer/p/<slug>/...:
the witness finds the project in both. A report prints the log's head (GET /projects/{slug}/ledger/head),
and an export of the log proves both the head and the report's document offline (the drill)."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from tests.ledger.conftest import MEMBER, OWNER, STRANGER, entries, log_of, needs_db, relay_all
from tests.ledger.test_ledger_outbox import emit

pytestmark = needs_db
L, R, T = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
CHECKER = Path(__file__).resolve().parents[3] / "scripts" / "verify-ledger-export.py"


@pytest.fixture(autouse=True)
def _enforce(mode):
    mode("enforce")


def body(request_id, action, item_type, item_id, **over):
    e = {"event_id": str(uuid.uuid4()), "request_id": request_id, "action": action, "item_type": item_type,
         "item_id": item_id, "details": {}}
    e.update(over)
    return e


def rejected(store, pid):
    return [e.details["reason"] for e in entries(store, log_of(pid)) if e.action == "ledger.rejected"]


LAYOUT = {"name": "Annex IV", "description": "", "template_id": None, "revision": 1, "show_index": True,
          "numbering": True, "blocks": [{"instance_id": str(uuid.uuid4()), "block_type": "free_text",
                                         "options": {"text": "x"}}]}
LOOK = {"name": "House", "font": "inter", "font_size_pt": 10.0, "primary_color": "#000000",
        "accent_color": "#ffffff", "header_text": None, "footer_text": None, "marking": "none",
        "show_document_id": False, "logo_mime": None, "logo_sha256": None}
DOC = hashlib.sha256(b"%PDF-1.7 fake").hexdigest()
CASES = [
    ("POST", "/api/p/{slug}/layouts", "report.layout.created", "layout", L,
     {"item_version": "1", "details": {"from": "empty"}, "content": LAYOUT, "after": LAYOUT}),
    ("POST", f"/api/p/{{slug}}/layouts/{L}/duplicate", "report.layout.created", "layout", str(uuid.uuid4()),
     {"item_version": "1", "details": {"from": "duplicate"}, "content": {**LAYOUT, "source": L}, "after": LAYOUT}),
    ("PUT", f"/api/p/{{slug}}/layouts/{L}", "report.layout.updated", "layout", L,
     {"item_version": "2", "details": {"revision": 2}, "content": LAYOUT, "before": LAYOUT,
      "after": {**LAYOUT, "revision": 2}}),
    ("DELETE", f"/api/p/{{slug}}/layouts/{L}", "report.layout.deleted", "layout", L,
     {"details": {"reports": 1}, "before": LAYOUT, "content": {"layout": LAYOUT, "reports": [{"id": R}]}}),
    ("POST", "/api/p/{slug}/templates", "report.template.created", "template", T,
     {"details": {"from": "form"}, "content": LOOK, "after": LOOK}),
    ("POST", "/api/p/{slug}/templates/import", "report.template.created", "template", T,
     {"details": {"from": "file"}, "content": LOOK, "after": LOOK}),
    ("PUT", f"/api/p/{{slug}}/templates/{T}", "report.template.updated", "template", T,
     {"content": LOOK, "before": LOOK, "after": LOOK}),
    ("DELETE", f"/api/p/{{slug}}/templates/{T}", "report.template.deleted", "template", T,
     {"content": LOOK, "before": LOOK}),
    ("POST", f"/api/p/{{slug}}/layouts/{L}/reports", "report.generated", "report", R,
     {"card_version": str(uuid.uuid4()),
      "details": {"card_version": str(uuid.uuid4()), "ledger_head": 7, "blocks": 1, "document_sha256": DOC,
                  "format": "pdf"},
      "content": {"anchor": {"seq": 7, "entry_sha256": "ab" * 32}, "layout": {"id": L, "revision": 1}}}),
    ("POST", f"/p/{{slug}}/layouts/{L}/generate", "report.generated", "report", R,
     {"details": {"card_version": None, "ledger_head": None, "blocks": 0, "document_sha256": DOC, "format": "docx"},
      "content": {"anchor": None, "layout": {"id": L, "revision": 1}}}),
    ("POST", f"/api/p/{{slug}}/layouts/{L}/reports", "report.failed", "report", R,
     {"details": {"error": "renderer_unavailable", "format": "pdf"}, "content": {"layout": {"id": L, "revision": 1}}}),
    ("GET", f"/api/p/{{slug}}/reports/{R}/download", "report.downloaded", "report", R,
     {"details": {"document_sha256": DOC}}),
    ("GET", f"/api/p/{{slug}}/reports/{R}/pdf", "report.downloaded", "report", R,
     {"details": {"document_sha256": DOC}}),
]


@pytest.mark.parametrize("method, tail, action, item_type, item_id, over", CASES,
                         ids=[f"{c[2]}@{c[0]} {c[1]}" for c in CASES])
def test_an_event_as_the_composer_sends_it_is_accepted(project, memory_ledger, witnessed, method, tail, action,
                                                       item_type, item_id, over):
    request_id = witnessed(MEMBER, method, "report_composer", "/report-composer" + tail.format(slug=project["slug"]))
    emit(project["pid"], "report_composer_rw", body(request_id, action, item_type, item_id, **over))
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == []
    [e] = [x for x in entries(memory_ledger, log_of(project["pid"])) if x.action == action]
    assert (e.source_app, e.item_id) == ("report_composer", item_id)


def test_the_composers_api_names_its_project_to_the_witness(project, witnessed):
    from tests.ledger.conftest import record

    request_id = witnessed(MEMBER, "POST", "report_composer", f"/report-composer/api/p/{project['slug']}/layouts")
    assert str(record(request_id).project_pid) == str(project["pid"])


def test_a_member_reads_the_head_a_report_prints(client, as_user, project, memory_ledger, witnessed):
    from platform_service.ledger.canonical import canonical

    request_id = witnessed(MEMBER, "POST", "report_composer", f"/report-composer/api/p/{project['slug']}/layouts")
    emit(project["pid"], "report_composer_rw", body(request_id, "report.layout.created", "layout", L,
                                                     item_version="1", details={"from": "empty"}, content=LAYOUT,
                                                     after=LAYOUT))
    relay_all(project["pid"])
    r = client.get(f"/projects/{project['slug']}/ledger/head", headers=as_user(MEMBER))
    assert r.status_code == 200, r.text
    head = r.json()
    newest = entries(memory_ledger, log_of(project["pid"]))[-1]
    assert head == {"seq": newest.seq, "entry_sha256": hashlib.sha256(canonical(newest.as_dict())).hexdigest()}
    assert client.get(f"/projects/{project['slug']}/ledger/head", headers=as_user(STRANGER)).status_code == 404


def _checker(tmp_path, export_text, key_pem, *args):
    path, key = tmp_path / "export.jsonl", tmp_path / "k.pub"
    path.write_text(export_text)
    key.write_text(key_pem)
    return subprocess.run([sys.executable, str(CHECKER), "--public-key", str(key), *args, str(path)],
                          capture_output=True, text=True)


def test_drill_a_report_is_verified_offline(client, as_user, project, memory_ledger, witnessed, tmp_path):
    """The phase 9 drill: a report prints the head it was generated under; with only the PDF, an export of
    the log and the signing key, a reader proves both that the head is in the log and that the log
    recorded this very document, generated under that head."""
    page = f"/report-composer/api/p/{project['slug']}/layouts"
    made = witnessed(MEMBER, "POST", "report_composer", page)
    emit(project["pid"], "report_composer_rw", body(made, "report.layout.created", "layout", L, item_version="1",
                                                     details={"from": "empty"}, content=LAYOUT, after=LAYOUT))
    relay_all(project["pid"])
    head = client.get(f"/projects/{project['slug']}/ledger/head", headers=as_user(MEMBER)).json()
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.7 the generated report, printing its anchor\n")
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    generated = witnessed(MEMBER, "POST", "report_composer", f"{page}/{L}/reports")
    emit(project["pid"], "report_composer_rw", body(
        generated, "report.generated", "report", R,
        details={"card_version": None, "ledger_head": head["seq"], "blocks": 1, "document_sha256": sha,
                 "format": "pdf"},
        content={"anchor": head, "layout": {"id": L, "revision": 1}}))
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == []
    export = client.get(f"/projects/{project['slug']}/ledger/export", headers=as_user(OWNER)).text
    printed = f"{head['seq']}:{head['entry_sha256'][:16]}"            # what the report's footer shows
    ok = _checker(tmp_path, export, memory_ledger.public_key_pem(), "--anchor", printed, "--document", str(pdf))
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert f"anchor: entry {head['seq']}" in ok.stdout and "document: recorded by entry" in ok.stdout
    wrong_anchor = _checker(tmp_path, export, memory_ledger.public_key_pem(), "--anchor",
                            f"{head['seq']}:{'0' * 16}")
    assert wrong_anchor.returncode == 1 and "anchor" in wrong_anchor.stdout
    other = tmp_path / "other.pdf"
    other.write_bytes(b"%PDF-1.7 another document\n")
    wrong_doc = _checker(tmp_path, export, memory_ledger.public_key_pem(), "--document", str(other))
    assert wrong_doc.returncode == 1 and "no report.generated entry" in wrong_doc.stdout
    later = _checker(tmp_path, export, memory_ledger.public_key_pem(), "--anchor", f"{head['seq'] + 1}:"
                     + hashlib.sha256(json.dumps(head).encode()).hexdigest()[:16], "--document", str(pdf))
    assert later.returncode == 1                                       # the anchor the document's entry names
