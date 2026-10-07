"""A project's catalogue serves its controls as checklist packages, and a public project reads the
public catalogue live (docs/superpowers/control-install-2026-10-04/01-plan.md P1).

The controls app installs a checklist from the package the platform gives for the project: a private
project's is built from its copy, by the public catalogue's own rules (apps/catalogue/backend/
controls_export.py), and a public project's is the public catalogue's export as it is. The rules are
held to the public catalogue's exports (tests/fixtures/control_exports_2026-10-04.json)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from platform_service import catalogue as cat
from tests.conftest import needs_database
from tests.connection_support import Stub
from tests.test_catalogue_choice import EXTRA, SAMPLE, admin, choose, engine, index, public_routes, url  # noqa: F401
from tests.test_evidence import ALICE, VERA, _reader, catalogue, project, sql  # noqa: F401

EXPORTS = json.loads((Path(__file__).parent / "fixtures" / "control_exports_2026-10-04.json").read_text())
STRANGER = "00000000-0000-0000-0000-00000000dead"
CONTROL = next(t["slug"] for t in SAMPLE["tool_detailed"] if any(g["slug"] == "control" for g in t["tags"]))


# ── the package, as the public catalogue builds it (no database) ────────────

@pytest.mark.parametrize("entry", EXPORTS["entries"], ids=lambda e: e["slug"])
def test_c1_1_a_package_built_from_a_detailed_entry_equals_the_public_export(entry):
    assert cat.checklist_package(entry) == EXPORTS["exports"][entry["slug"]]


def test_c1_1_article_references_imply_the_ai_act_and_order_decides_the_questions():
    entry = {"slug": "x", "name": "X", "description": "", "metadata": None, "tags": [{"slug": "control"}],
             "questions": [{"order": 2, "text": "second", "article": "Article 9", "category": None},
                           {"order": 1, "text": "first", "article": None, "category": "c"}]}
    pkg = cat.checklist_package(entry)
    assert [q["text"] for q in pkg["questions"]] == ["first", "second"]
    assert pkg["meta"]["regulationIds"] == ["ai-act"]
    assert pkg["meta"]["sourceName"] == "Unknown" and pkg["meta"]["controlTopic"] == "X"
    assert pkg["meta"]["description"] is None


# ── the route, for either mode ──────────────────────────────────────────────

@pytest.fixture
def online(monkeypatch):
    """The public catalogue, with its export of one control."""
    stub = Stub()
    public_routes(stub, SAMPLE)
    stub.route("GET", f"/control/{CONTROL}/export", (200, {"meta": {"catalogueId": CONTROL}, "questions": []}))
    monkeypatch.setenv("CATALOGUE_URL", stub.base)
    yield stub
    stub.stop()


def export(client, as_user, project, slug, who=VERA, key="slug"):
    return client.get(f"/projects/{project[key]}/catalogue/control/{slug}/export", headers=as_user(who))


@needs_database
def test_c1_2_a_private_project_gives_the_package_of_its_copy(client, as_user, project, online, engine):
    assert choose(client, as_user, project, "private").status_code == 200
    online.seen.clear()
    entry = next(t for t in SAMPLE["tool_detailed"] if t["slug"] == CONTROL)
    for key in ("slug", "pid"):                                # the controls app names the project by pid
        r = export(client, as_user, project, CONTROL, key=key)
        assert r.status_code == 200, r.text
        assert r.json() == cat.checklist_package(entry)
    assert not online.requests(prefix="/control/")           # the copy, not the public catalogue


@needs_database
def test_c1_3_a_public_project_gives_the_public_export_with_the_bridge_token(client, as_user, project, online,
                                                                            monkeypatch):
    monkeypatch.setenv("CATALOGUE_TOKEN", "bridge-secret")
    assert choose(client, as_user, project, "public").status_code == 200
    r = export(client, as_user, project, CONTROL)
    assert r.status_code == 200 and r.json() == {"meta": {"catalogueId": CONTROL}, "questions": []}
    sent = online.requests("GET", f"/control/{CONTROL}/export")[-1]
    assert sent["headers"]["authorization"] == "Bearer bridge-secret"


@needs_database
def test_c1_4_no_choice_yet_is_409_and_says_so(client, as_user, project, online):
    r = export(client, as_user, project, CONTROL)
    assert r.status_code == 409 and "catalogue" in r.json()["detail"]


@needs_database
def test_c1_5_a_test_or_an_unknown_entry_is_404_in_a_private_project(client, as_user, project, online, engine):
    assert choose(client, as_user, project, "private").status_code == 200
    assert export(client, as_user, project, "langbite").status_code == 404
    assert export(client, as_user, project, "no-such-control").status_code == 404


@needs_database
def test_c1_5_and_in_a_public_project_the_public_catalogues_404(client, as_user, project, online):
    online.route("GET", "/control/langbite/export", (404, {"detail": "no control 'langbite'"}))
    assert choose(client, as_user, project, "public").status_code == 200
    assert export(client, as_user, project, "langbite").status_code == 404


@needs_database
def test_c1_6_a_stranger_gets_404_and_an_unanswering_public_catalogue_is_503(client, as_user, project, online,
                                                                             monkeypatch):
    assert choose(client, as_user, project, "public").status_code == 200
    assert export(client, as_user, project, CONTROL, who=STRANGER).status_code == 404
    down = Stub()
    monkeypatch.setenv("CATALOGUE_URL", down.base)
    down.route("GET", f"/control/{CONTROL}/export", (500, {"detail": "boom"}))
    assert export(client, as_user, project, CONTROL).status_code == 503
    down.stop()


# ── a public project reads the public catalogue live (D1, D5) ───────────────

@needs_database
def test_c2_1_a_public_project_reads_the_public_catalogue_live_without_local_entries(client, as_user, project,
                                                                                   online, engine):
    assert choose(client, as_user, project, "public").status_code == 200
    get = lambda tail: client.get(url(project, "/api/" + tail), headers=as_user(VERA))
    detailed = get("tool/?detailed=true")
    assert detailed.status_code == 200, detailed.text
    assert [t["slug"] for t in detailed.json()] == [t["slug"] for t in SAMPLE["tool_detailed"]]
    assert all(set(t) == set(SAMPLE["tool_detailed"][0]) | EXTRA for t in detailed.json())
    assert not any(t["aisc_local"] for t in detailed.json())
    assert all(set(t) == set(SAMPLE["tool"][0]) | EXTRA for t in get("tool/").json())
    assert get("tags/").json() == SAMPLE["tags"]               # no "Local" source: there are no local entries
    assert get("metric/").json() == SAMPLE["metric"] and get("metadata/").json() == SAMPLE["metadata"]
    first = SAMPLE["tool_detailed"][0]
    assert get(f"tool/{first['id']}/tags/").json() == first["tags"]
    assert get("project-dimensions").json() == ["human-agency-oversight", "societal-environmental-wellbeing"]


@needs_database
def test_c2_2_a_public_project_says_what_it_installed_and_what_this_stack_can_install(client, as_user, project,
                                                                                    dsn, online, engine, index):
    assert choose(client, as_user, project, "public").status_code == 200
    sql(dsn, project["pid"], "INSERT INTO controls.checklist (id, \"catalogueId\", title) VALUES ('ck8', %s, 'x')",
        (CONTROL,))
    tools = {t["slug"]: t for t in client.get(url(project, "/api/tool/?detailed=true"), headers=as_user(VERA)).json()}
    assert tools[CONTROL]["aisc_installed"] is True and tools["langbite"]["aisc_installed"] is True
    assert tools["langbite"]["completion_status"] == "full"   # on this stack's index
    info = client.get(url(project, "/api/tool/langbite/install-info"), headers=as_user(VERA))
    assert info.status_code == 200 and info.json()["installable"] is True


@needs_database
def test_c2_3_live_reads_are_kept_a_short_while(client, as_user, project, online, engine):
    assert choose(client, as_user, project, "public").status_code == 200
    for _ in range(3):
        assert client.get(url(project, "/api/tool/?detailed=true"), headers=as_user(VERA)).status_code == 200
    assert len(online.requests("GET", "/tool/")) == 1


@needs_database
def test_c2_4_updating_and_local_dimensions_stay_private(client, as_user, project, online):
    assert choose(client, as_user, project, "public").status_code == 200
    assert client.post(url(project, "/update"), headers=admin(as_user)).status_code == 409
    r = client.put(url(project, "/local/my-probe/dimensions"), json={"dimensions": ["REQ1"]}, headers=admin(as_user))
    assert r.status_code == 409
