"""The organisation's controls: what the add-controls service (aisc-add-controls-catalogue, CATALOGUE_TARGET=local)
publishes, one control a file with an extra "_published_by" key, into a folder the platform reads as
ORG_CONTROLS_DIR (default /app/org_controls, the org_controls volume, read-only here). It is read after
LOCAL_CONTROLS_DIR with the same rules, and a slug is taken once, the repository folder's first. These tests
need no database (test_catalogue_local_controls.py has the ones that do)."""
from __future__ import annotations

import json
import os

import pytest

from platform_service import catalogue as cat
from platform_service import local_controls as lc
from tests.test_catalogue_choice import SAMPLE
from tests.test_catalogue_local_controls import control


def published(slug, **extra):
    """A control as the add-controls service writes it."""
    return {**control(slug, **extra), "_published_by": "aisc-add-controls-catalogue"}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    path = tmp_path / "repo"
    path.mkdir()
    monkeypatch.setenv("LOCAL_CONTROLS_DIR", str(path))
    return path


@pytest.fixture
def org(tmp_path, monkeypatch):
    path = tmp_path / "org"
    path.mkdir()
    monkeypatch.setenv("ORG_CONTROLS_DIR", str(path))
    return path


def test_o1_the_org_folder_is_read_after_the_repository_folder(repo, org):
    (repo / "repo.json").write_text(json.dumps([control("a"), control("b")]))
    (org / "c.json").write_text(json.dumps(published("c")))
    (org / "aa.json").write_text(json.dumps(published("aa")))
    assert [c["slug"] for c in cat.local_controls()] == ["a", "b", "aa", "c"]


def test_o2_a_slug_in_both_folders_is_the_repository_folders(repo, org):
    (repo / "repo.json").write_text(json.dumps([control("same", name="from the repository")]))
    (org / "same.json").write_text(json.dumps(published("same", name="from the organisation")))
    assert [c["name"] for c in cat.local_controls()] == ["from the repository"]


def test_o3_the_published_by_key_is_harmless(repo, org):
    (org / "c.json").write_text(json.dumps(published("c")))
    [found] = cat.local_controls()
    entry = cat.local_control_entry(found, SAMPLE["tags"], 0)
    assert "_published_by" not in entry and "_published_by" not in entry["metadata"]
    assert [q["text"] for q in cat.checklist_package(entry)["questions"]] == ["First?", "Second?"]


def test_o4_the_org_folder_alone_or_neither_folder(repo, org, monkeypatch):
    (org / "c.json").write_text(json.dumps(published("c")))
    monkeypatch.setenv("LOCAL_CONTROLS_DIR", str(repo / "missing"))
    assert [c["slug"] for c in cat.local_controls()] == ["c"]
    monkeypatch.setenv("ORG_CONTROLS_DIR", str(org / "missing"))
    assert cat.local_controls() == []


def test_o5_a_missing_org_folder_leaves_the_repository_folder(repo, monkeypatch):
    (repo / "repo.json").write_text(json.dumps([control("a")]))
    monkeypatch.setenv("ORG_CONTROLS_DIR", str(repo / "missing"))
    assert [c["slug"] for c in cat.local_controls()] == ["a"]


def test_o6_the_org_folder_defaults_to_app_org_controls(repo, monkeypatch):
    assert lc.ORG_CONTROLS_DIR == "/app/org_controls"
    monkeypatch.delenv("ORG_CONTROLS_DIR", raising=False)
    seen = []
    real = lc.Path

    def spy(p, *a):
        seen.append(str(p))
        return real(p, *a)

    monkeypatch.setattr(lc, "Path", spy)
    lc.local_controls()
    assert "/app/org_controls" in seen


def test_o7_an_unreadable_org_file_is_skipped_not_fatal(repo, org, caplog):
    (org / "good.json").write_text(json.dumps(published("good")))
    (org / "broken.json").write_text("{ not json")
    (org / "half.json").write_text(json.dumps({"slug": "half", "_published_by": "aisc-add-controls-catalogue"}))
    locked = org / "locked.json"
    locked.write_text(json.dumps(published("locked")))
    locked.chmod(0)
    try:
        slugs = [c["slug"] for c in cat.local_controls()]
    finally:
        locked.chmod(0o600)
    assert slugs == (["good"] if os.geteuid() != 0 else ["good", "locked"])  # root reads a 000 file
    assert "broken.json" in caplog.text and "half" in caplog.text
    if os.geteuid() != 0:
        assert "locked.json" in caplog.text
