"""A plugin of the install's own (a folder in local_plugins/, mounted read-only at LOCAL_PLUGINS_DIR) is published
like a repo: found by the package its pyproject.toml names, built from a copy without the folder's git, virtual
environment or old build output, checked and uploaded."""
import os
from pathlib import Path

import pytest

from plugin_publisher.service import Publisher

PACKAGE = "aisc-plugin-homegrown"


@pytest.fixture
def local_plugins(tmp_path, monkeypatch):
    """The local_plugins folder the publisher reads, and make(folder, package, version, files={path: text})."""
    root = tmp_path / "local_plugins"
    root.mkdir()
    (root / "README.md").write_text("drop plugins here\n")
    monkeypatch.setenv("LOCAL_PLUGINS_DIR", str(root))

    def make(folder, package=PACKAGE, version="0.3.0", files=None):
        path = root / folder
        path.mkdir()
        (path / "pyproject.toml").write_text(f'[project]\nname = "{package}"\nversion = "{version}"\n')
        for name, text in (files or {}).items():
            (path / name).parent.mkdir(parents=True, exist_ok=True)
            (path / name).write_text(text)
        return path

    return make


def test_a_local_plugin_is_built_from_its_folder_and_uploaded(client, local_plugins, index, build, workdir):
    local_plugins("homegrown")
    status, body = client.post("/publish", {"local": True, "package": PACKAGE})
    assert status == 200, body
    assert body == {"package": PACKAGE, "version": "0.3.0", "published": True, "replaced": False}
    assert index.uploads == [["aisc_plugin_homegrown-0.3.0-py3-none-any.whl"]]
    assert list(workdir.iterdir()) == []


def test_the_folder_is_found_by_its_package_whatever_the_folder_is_called(client, local_plugins, index, build):
    local_plugins("my-work-in-progress", package="aisc-plugin-other")
    local_plugins("anything", package="AISC_Plugin_Homegrown")
    status, body = client.post("/publish", {"local": True, "package": PACKAGE})
    assert status == 200, body
    assert index.uploads == [["AISC_Plugin_Homegrown-0.3.0-py3-none-any.whl"]]


def test_an_unchanged_local_plugin_is_not_uploaded_twice(client, local_plugins, index, build):
    local_plugins("homegrown")
    assert client.post("/publish", {"local": True, "package": PACKAGE})[1]["published"] is True
    status, body = client.post("/publish", {"local": True, "package": PACKAGE})
    assert status == 200 and body["published"] is False
    assert len(index.uploads) == 1


def test_no_folder_for_the_package_is_404_naming_local_plugins(client, local_plugins, index, build):
    local_plugins("homegrown", package="aisc-plugin-other")
    status, body = client.post("/publish", {"local": True, "package": PACKAGE})
    assert status == 404 and "local_plugins" in body["detail"] and PACKAGE in body["detail"]
    assert build.calls == 0 and index.uploads == []


def test_two_folders_with_one_package_are_refused(client, local_plugins, index, build):
    local_plugins("first")
    local_plugins("second")
    status, body = client.post("/publish", {"local": True, "package": PACKAGE})
    assert status == 409 and "first" in body["detail"] and "second" in body["detail"]
    assert build.calls == 0


def test_without_a_local_plugins_folder_it_is_404(client, monkeypatch, index, build):
    monkeypatch.delenv("LOCAL_PLUGINS_DIR", raising=False)
    status, body = client.post("/publish", {"local": True, "package": PACKAGE})
    assert status == 404 and "local_plugins" in body["detail"]


def test_local_and_repo_together_or_local_not_true_is_400(client, local_plugins):
    local_plugins("homegrown")
    assert client.post("/publish", {"local": True, "repo": "aisc-plugin-demo", "package": PACKAGE})[0] == 400
    assert client.post("/publish", {"local": "yes", "package": PACKAGE})[0] == 400


def test_the_build_sees_a_copy_without_git_venv_or_old_build_output(start, local_plugins, index, workdir):
    folder = local_plugins("homegrown", files={
        "src/aisc_plugin_homegrown/__init__.py": "", ".git/HEAD": "ref", ".venv/bin/python": "",
        "dist/old.whl": "old", "build/lib/x.py": "", "src/aisc_plugin_homegrown/__pycache__/a.pyc": ""})
    seen = {}

    def build(source, outdir):
        seen["source"] = Path(source)
        seen["files"] = sorted(str(p.relative_to(source)) for p in Path(source).rglob("*") if p.is_file())
        (Path(outdir) / "aisc_plugin_homegrown-0.3.0-py3-none-any.whl").write_bytes(b"wheel")

    client = start(Publisher(upload=index.upload, versions_on_index=index.versions_on_index,
                             wheel_on_index=index.wheel_on_index, build=build, workdir=workdir))
    status, body = client.post("/publish", {"local": True, "package": PACKAGE})
    assert status == 200, body
    assert seen["files"] == ["pyproject.toml", "src/aisc_plugin_homegrown/__init__.py"]
    assert folder not in seen["source"].parents and seen["source"] != folder


def test_a_link_in_the_folder_is_refused_before_building(client, local_plugins, index, build, tmp_path):
    folder = local_plugins("homegrown")
    secret = tmp_path / "outside.txt"
    secret.write_text("not the plugin's")
    os.symlink(secret, folder / "linked.txt")
    status, body = client.post("/publish", {"local": True, "package": PACKAGE})
    assert status == 409 and "link" in body["detail"]
    assert build.calls == 0 and index.uploads == []


def _copied(start, local_plugins, index, workdir, files):
    """The files the build is given for a folder holding `files`."""
    local_plugins("homegrown", files=files)
    seen = {}

    def build(source, outdir):
        seen["files"] = sorted(str(p.relative_to(source)) for p in Path(source).rglob("*") if p.is_file())
        (Path(outdir) / "aisc_plugin_homegrown-0.3.0-py3-none-any.whl").write_bytes(b"wheel")

    client = start(Publisher(upload=index.upload, versions_on_index=index.versions_on_index,
                             wheel_on_index=index.wheel_on_index, build=build, workdir=workdir))
    status, body = client.post("/publish", {"local": True, "package": PACKAGE})
    assert status == 200, body
    return seen["files"]


def test_environment_files_are_never_copied(start, local_plugins, index, workdir):
    files = _copied(start, local_plugins, index, workdir, {
        ".env": "API_KEY=x", ".env.local": "API_KEY=y", "src/aisc_plugin_homegrown/.env": "API_KEY=z",
        "src/aisc_plugin_homegrown/__init__.py": ""})
    assert files == ["pyproject.toml", "src/aisc_plugin_homegrown/__init__.py"]


def test_build_output_is_left_out_only_at_the_top_so_a_subpackage_named_build_stays(start, local_plugins, index, workdir):
    files = _copied(start, local_plugins, index, workdir, {
        "build/lib/old.py": "", "dist/old.whl": "", "venv/bin/python": "",
        "src/aisc_plugin_homegrown/build/__init__.py": "", "src/aisc_plugin_homegrown/dist/__init__.py": "",
        "src/aisc_plugin_homegrown/__pycache__/x.pyc": ""})
    assert files == ["pyproject.toml", "src/aisc_plugin_homegrown/build/__init__.py",
                     "src/aisc_plugin_homegrown/dist/__init__.py"]
