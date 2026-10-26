"""An image built from apps/backend/Dockerfile or apps/eval/Dockerfile alone, with no compose mount and no
editable reinstall, holds this checkout's plugin interface (0.4.0), plugin-manager and aisc_identity, and the
backend's Django app loads in it.

These build images, which takes minutes, network and disk, so they run only when asked:

    AISC_IMAGE_CHECK=1 uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider \
        scripts/tests/test_engine_images.py

Each image is built under a throwaway tag (aisc-backend:interface-check, aisc-eval:interface-check), never
:latest, and removed afterwards. The build refuses to start with less than 30 GB free on /.
"""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import ROOT

pytestmark = pytest.mark.skipif(os.environ.get("AISC_IMAGE_CHECK") != "1",
                                reason="builds images: set AISC_IMAGE_CHECK=1 to run")

TAGS = {"apps/backend": "aisc-backend:interface-check", "apps/eval": "aisc-eval:interface-check"}
FREE_BYTES_NEEDED = 30 * 1024**3

#: the import name of each local package and the folder holding its source in this checkout
LOCAL_SOURCES = {
    "aisc_plugin_interface": ROOT / "shared/plugin-interface/src/aisc_plugin_interface",
    "aisc_plugin_manager": ROOT / "shared/plugin-manager/src/aisc_plugin_manager",
    "aisc_identity": ROOT / "shared/identity/aisc_identity",
}

#: run inside the image: the version of the interface and the sha256 of every file of each local package
PROBE = """
import hashlib, importlib, importlib.metadata as m, inspect, json, pathlib
# the package re-exports the decorator ``assesses``, which shadows the submodule of the same name,
# so ``import aisc_plugin_interface.assesses as a`` would bind the function: take the module itself
a = importlib.import_module("aisc_plugin_interface.assesses")
import aisc_plugin_interface.helpers
out = {"version": m.version("aisc-plugin-interface"),
       "strict": "strict" in inspect.signature(a.model_session).parameters,
       "required": "required" in inspect.signature(a.dataset_through_target_access).parameters,
       "files": {}}
for name in %r:
    root = pathlib.Path(importlib.import_module(name).__file__).parent
    out["files"][name] = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in root.rglob("*")
                          if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
print(json.dumps(out))
""" % (sorted(LOCAL_SOURCES),)


#: run inside the backend image: the app loads, and Django's checks import its URLs, routers and auth
DJANGO_PROBE = ("import django; django.setup(); from django.core.management import call_command; "
                "call_command('check'); print('django ok')")


def _docker(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


@pytest.fixture(scope="module", params=sorted(TAGS))
def image(request):
    app = request.param
    tag = TAGS[app]
    assert not tag.endswith(":latest")
    free = shutil.disk_usage("/").free
    assert free >= FREE_BYTES_NEEDED, f"only {free // 1024**3} GB free on /: not building {tag}"
    build = _docker("build", "-t", tag, str(ROOT / app), timeout=3600)
    try:
        assert build.returncode == 0, build.stdout[-4000:] + build.stderr[-4000:]
        yield app, tag
    finally:
        _docker("image", "rm", tag, timeout=300)


def _source_hashes(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}


def test_the_image_holds_this_checkouts_interface_plugin_manager_and_identity(image):
    app, tag = image
    r = _docker("run", "--rm", "--entrypoint", "/app/.venv/bin/python", tag, "-c", PROBE, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    found = json.loads(r.stdout.strip().splitlines()[-1])
    assert found["version"] == "0.4.0"
    assert found["strict"] and found["required"]
    for name, folder in LOCAL_SOURCES.items():
        assert found["files"][name] == _source_hashes(folder), f"{tag}: {name} is not this checkout's"


def test_the_backends_django_app_loads(image):
    app, tag = image
    if app != "apps/backend":
        pytest.skip("the eval worker is not a Django app")
    r = _docker("run", "--rm", "-e", "DJANGO_SETTINGS_MODULE=config.settings", "--entrypoint",
                "/app/.venv/bin/python", tag, "-c", DJANGO_PROBE, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "django ok" in r.stdout
