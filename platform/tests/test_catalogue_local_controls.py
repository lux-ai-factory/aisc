"""Local controls: checklists kept in the stack (LOCAL_CONTROLS_DIR, the repo's local_controls/), in the public
catalogue's own seed format (catalogue branch `dev`, backend/controls_seed.json), join every private copy when
the project chooses it and on each update, and install like any other control. A public entry with the same slug
wins, so a control the public catalogue later publishes replaces its local copy. A public project reads the
public catalogue live and gets them too (workshop, 2026-10-07), from the folder. The organisation's folder
(ORG_CONTROLS_DIR) is in test_catalogue_org_controls.py."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from platform_service import catalogue as cat
from tests.conftest import needs_database
from tests.test_catalogue_choice import SAMPLE, admin, choose, engine, public, public_routes, url  # noqa: F401
from tests.test_evidence import ALICE, VERA, _reader, catalogue, project, sql  # noqa: F401

REPO_LOCAL_CONTROLS = Path(__file__).resolve().parents[2] / "local_controls"
FAIRNESS = "diversity-non-discrimination-fairness"


def control(slug="local-fairness-check", **extra):
    entry = {
        "name": "Local fairness check", "slug": slug, "description": "A checklist kept in this stack",
        "licensing": "Open_Source", "completion_status": "full", "dimension_slug": FAIRNESS,
        "controls_subdim_slugs": ["sampling-strategies"],
        "metadata": {"provider": "Somebody", "link": "https://example.org/fair", "project_maturity": "",
                     "control_topic": "Fairness", "target_legal_requirements": "",
                     "scientific_reference": "Somebody, 2026. Licence: CC0."},
        "questions": [{"order": 2, "text": "Second?", "article": None, "category": "B"},
                      {"order": 1, "text": "First?", "article": None, "category": "A"}],
    }
    entry.update(extra)
    return entry


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_CONTROLS_DIR", str(tmp_path))
    monkeypatch.setenv("ORG_CONTROLS_DIR", str(tmp_path / "no-org-folder"))  # the organisation's: none here
    return tmp_path


# ── reading the folder (no database) ────────────────────────────────────────

def test_l1_a_file_holds_a_list_or_one_control_and_other_files_are_ignored(folder):
    (folder / "many.json").write_text(json.dumps([control("a"), control("b")]))
    (folder / "one.json").write_text(json.dumps(control("c")))
    (folder / "README.md").write_text("not a control")
    assert [c["slug"] for c in cat.local_controls()] == ["a", "b", "c"]


def test_l1_a_broken_file_is_skipped_not_fatal(folder, caplog):
    (folder / "a.json").write_text(json.dumps([control("a")]))
    (folder / "b.json").write_text("{ not json")
    (folder / "c.json").write_text(json.dumps([{"slug": "no-name-no-questions"}]))
    assert [c["slug"] for c in cat.local_controls()] == ["a"]
    assert "b.json" in caplog.text and "no-name-no-questions" in caplog.text


def test_l1_a_slug_is_taken_once_and_no_folder_means_none(folder, monkeypatch):
    (folder / "a.json").write_text(json.dumps([control("a", name="first"), control("a", name="second")]))
    assert [c["name"] for c in cat.local_controls()] == ["first"]
    monkeypatch.setenv("LOCAL_CONTROLS_DIR", str(folder / "missing"))
    assert cat.local_controls() == []


def test_l2_a_local_control_is_a_catalogue_control_with_its_tags_and_package():
    entry = cat.local_control_entry(control(), SAMPLE["tags"], 0)
    slugs = [t["slug"] for t in entry["tags"]]
    assert slugs[0] == cat.LOCAL_SOURCE and {"control", FAIRNESS, "sampling-strategies"} <= set(slugs)
    assert cat.is_export_control(entry) and entry["id"] >= cat.LOCAL_CONTROL_ID_BASE
    assert set(entry) >= set(cat.TOOL_KEYS)
    pkg = cat.checklist_package(entry)
    assert [q["text"] for q in pkg["questions"]] == ["First?", "Second?"]
    assert pkg["meta"]["sourceName"] == "Somebody" and pkg["meta"]["regulationIds"] == []
    assert pkg["meta"]["catalogueId"] == "local-fairness-check"


def test_l2_a_tag_the_copy_does_not_have_is_left_out():
    entry = cat.local_control_entry(control(controls_subdim_slugs=["no-such-subdim"]), SAMPLE["tags"], 0)
    assert "no-such-subdim" not in [t["slug"] for t in entry["tags"]]


def test_l3_the_repos_local_controls_are_the_four_fairness_checklists_and_all_build():
    import os

    os.environ["LOCAL_CONTROLS_DIR"] = str(REPO_LOCAL_CONTROLS)
    try:
        found = cat.local_controls()
    finally:
        del os.environ["LOCAL_CONTROLS_DIR"]
    assert {c["slug"] for c in found} >= {
        "altai-diversity-non-discrimination-and-fairness", "fraia-non-discrimination-and-equal-treatment",
        "nist-ai-rmf-fairness-and-bias", "ai-verify-fairness-process-checks"}
    for n, c in enumerate(found):
        entry = cat.local_control_entry(c, SAMPLE["tags"], n)
        assert FAIRNESS in [t["slug"] for t in entry["tags"]], c["slug"]
        assert cat.checklist_package(entry)["questions"], c["slug"]


# ── in a project ────────────────────────────────────────────────────────────

def listed(client, as_user, project):
    r = client.get(url(project, "/api/tool/?detailed=true"), headers=as_user(VERA))
    assert r.status_code == 200, r.text
    return {t["slug"]: t for t in r.json()}


@needs_database
def test_l4_a_private_copy_has_the_local_controls_and_exports_them(client, as_user, project, public, engine, folder):
    (folder / "fair.json").write_text(json.dumps([control()]))
    assert choose(client, as_user, project, "private").status_code == 200
    tools = listed(client, as_user, project)
    assert tools["local-fairness-check"]["aisc_local"] is True
    assert all(not t["aisc_local"] for s, t in tools.items() if s in {e["slug"] for e in SAMPLE["tool_detailed"]})
    r = client.get(f"/projects/{project['slug']}/catalogue/control/local-fairness-check/export", headers=as_user(VERA))
    assert r.status_code == 200, r.text
    assert [q["text"] for q in r.json()["questions"]] == ["First?", "Second?"]


@needs_database
def test_l5_update_follows_the_folder_and_a_public_entry_wins(client, as_user, project, public, engine, folder):
    (folder / "fair.json").write_text(json.dumps([control("gone-later"), control("published-later")]))
    assert choose(client, as_user, project, "private").status_code == 200
    (folder / "fair.json").write_text(json.dumps([control("published-later"), control("new-later")]))
    upstream = copy.deepcopy(SAMPLE)
    published = copy.deepcopy(upstream["tool_detailed"][0])
    published.update(id=4242, slug="published-later", name="Published upstream")
    upstream["tool_detailed"].append(published)
    public.routes.clear()
    public_routes(public, upstream)
    assert client.post(url(project, "/update"), headers=admin(as_user)).status_code == 200
    tools = listed(client, as_user, project)
    assert "gone-later" not in tools and tools["new-later"]["aisc_local"] is True
    assert tools["published-later"]["name"] == "Published upstream" and tools["published-later"]["aisc_local"] is False


@needs_database
def test_l6_a_public_project_lists_the_local_controls_too_and_a_public_entry_wins(
        client, as_user, project, public, engine, folder):
    """For the workshop: the hosted catalogue lacks the fairness checklists, and a project that reads it live
    must still offer them. One the hosted catalogue publishes under the same slug is its own entry."""
    taken = SAMPLE["tool_detailed"][0]["slug"]
    (folder / "fair.json").write_text(json.dumps([control(), control(taken, name="Local copy")]))
    assert choose(client, as_user, project, "public").status_code == 200
    tools = listed(client, as_user, project)
    assert tools["local-fairness-check"]["aisc_local"] is True
    assert FAIRNESS in [t["slug"] for t in tools["local-fairness-check"]["tags"]]
    assert tools[taken]["aisc_local"] is False and tools[taken]["name"] != "Local copy"
    assert len([s for s in tools if s == taken]) == 1


@needs_database
def test_l6_a_public_project_exports_a_local_control_from_the_folder(client, as_user, project, public, engine, folder):
    (folder / "fair.json").write_text(json.dumps([control()]))
    assert choose(client, as_user, project, "public").status_code == 200
    r = client.get(f"/projects/{project['slug']}/catalogue/control/local-fairness-check/export", headers=as_user(VERA))
    assert r.status_code == 200, r.text
    assert [q["text"] for q in r.json()["questions"]] == ["First?", "Second?"]
    assert not public.requests("GET", "/control/local-fairness-check/export")


def test_l8_the_evidence_page_knows_a_local_controls_dimension(folder, monkeypatch):
    """An installed local checklist links to objectives of its dimension (evidence's same-dimension rule)."""
    from platform_service import evidence
    from tests.connection_support import Stub

    (folder / "fair.json").write_text(json.dumps([control(), control("gov", dimension_slug="safety")]))
    stub = Stub()
    stub.route("GET", "/tool/", (200, [{"slug": "gov", "package_name": None, "tags": [
        {"slug": "societal-environmental-wellbeing", "section": "dimension", "parent_dimension_slug": None}]}]))
    monkeypatch.setenv("CATALOGUE_URL", stub.base)
    evidence.forget_dimensions()
    try:
        by_slug, _ = evidence.tool_dimensions()
    finally:
        stub.stop()
        evidence.forget_dimensions()
    # the ids as evidence names them (R5 or REQ5): fairness, and the catalogue's own for "gov"
    assert by_slug["local-fairness-check"] == [evidence._BY_SLUG[FAIRNESS]]
    assert by_slug["gov"] == [evidence._BY_SLUG["societal-environmental-wellbeing"]]


def test_l7_the_module_lists_the_local_controls_one_slug_a_line(folder):
    """What scripts/start.sh prints at the end of a start (python -m platform_service.catalogue)."""
    import subprocess
    import sys

    (folder / "fair.json").write_text(json.dumps([control("a"), control("b")]))
    (folder / "broken.json").write_text("{")
    r = subprocess.run([sys.executable, "-m", "platform_service.catalogue"], capture_output=True, text=True,
                       env={**__import__("os").environ, "LOCAL_CONTROLS_DIR": str(folder)}, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["a", "b"] and "broken.json" in r.stderr
