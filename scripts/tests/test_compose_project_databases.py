"""Compose wiring of the per-project databases that test_compose_isolation.py does not check: image tags,
and the migration one-shots. Read-only: the compose files are copied and resolved with
`docker compose config`; nothing is started, stopped or built. No value of a credential is printed.
"""

from __future__ import annotations

import re
import subprocess

import pytest

import compose_cfg
from compose_cfg import FILES
from conftest import ROOT

BEFORE = "f01288a"  # the last commit before the per-project databases, whose image names must hold


def _resolve(tmp_path, extra_env: dict, *profiles: str, files=FILES) -> dict:
    """Under project `aisc`, as the stack names its images; the host's own AISC_IMAGE_TAG left out."""
    return compose_cfg.config(tmp_path, *profiles, files=files, env=extra_env, drop=("AISC_IMAGE_TAG",),
                              project="aisc")["services"]


@pytest.fixture(scope="module")
def default_tag(tmp_path_factory):
    return _resolve(tmp_path_factory.mktemp("w1-default"), {})


@pytest.fixture(scope="module")
def inspect_tag(tmp_path_factory):
    """With the `inspect` profile, which Flower runs under."""
    return _resolve(tmp_path_factory.mktemp("w1-inspect"), {}, "inspect")


@pytest.fixture(scope="module")
def isolation_tag(tmp_path_factory):
    return _resolve(tmp_path_factory.mktemp("w1-isolation"), {"AISC_IMAGE_TAG": "isolation"}, "isolation")


def _built(services: dict) -> list[str]:
    return sorted(n for n, s in services.items() if s.get("build"))


def _before_images(tmp_path) -> dict[str, str]:
    """Image name of every built service at f01288a, as compose names it under project `aisc`."""
    old = tmp_path / "before"
    old.mkdir()
    files = []
    for f in FILES:
        text = subprocess.run(["git", "show", f"{BEFORE}:{f}"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout
        # A module's settings file that no longer exists (qualification's, removed with its own repo's
        # history) is read as empty: only the image names are compared here.
        for name in set(re.findall(r"env_file:\s*(\S+)", text)):
            if not (ROOT / name).exists():
                (tmp_path / "empty.env").write_text("")
                text = text.replace(f"env_file: {name}", f"env_file: {tmp_path / 'empty.env'}")
        (old / f).write_text(text)
        files.append(old / f)
    services = _resolve(tmp_path, {}, files=files)
    return {n: s.get("image") or f"aisc-{n}" for n, s in services.items() if s.get("build")}


def test_every_built_service_is_tagged_by_aisc_image_tag(isolation_tag):
    """With AISC_IMAGE_TAG=isolation no built image resolves to :latest, and none is pulled."""
    wrong = {n: s.get("image") for n, s in isolation_tag.items()
             if (s.get("build") or str(s.get("image", "")).startswith("aisc-"))
             and not str(s.get("image", "")).endswith(":isolation")}
    assert not wrong, f"images not following AISC_IMAGE_TAG: {wrong}"
    loose = sorted(n for n in _built(isolation_tag) if isolation_tag[n].get("pull_policy") != "never")
    assert not loose, f"built services without pull_policy never: {loose}"


#: one-shot services that since run the image a sibling builds, so one tag is built once
RUNS_SIBLINGS_IMAGE = {"controls-migrate": "controls-web"}


def test_with_the_tag_unset_every_image_name_is_as_before(default_tag, inspect_tag, tmp_path):
    """With AISC_IMAGE_TAG unset, every built service keeps the image name the running stack uses, or
    the name of the sibling whose image it now runs."""
    before = {n: img if ":" in img else f"{img}:latest" for n, img in _before_images(tmp_path).items()}
    for n, sibling in RUNS_SIBLINGS_IMAGE.items():
        assert default_tag[n].get("image") == default_tag[sibling].get("image"), n
        before[n] = default_tag[sibling]["image"]
    changed = {n: (img, default_tag[n].get("image")) for n, img in before.items()
               if n in default_tag and default_tag[n].get("image") != img}
    assert not changed, f"image names changed with AISC_IMAGE_TAG unset: {changed}"
    assert inspect_tag["aisc-eval-flower"]["image"] == "aisc-eval:latest"


def test_report_composer_migrate_one_shot(default_tag):
    """The composer migrates the library and every project database in a one-shot the composer waits for,
    with the composer's own environment."""
    svc = default_tag.get("report-composer-migrate")
    assert svc, "no service report-composer-migrate"
    cmd = svc.get("command") or []
    text = " ".join(cmd) if isinstance(cmd, list) else cmd
    assert "python -m report_composer.migrate" in text
    # the migrate one-shots' convention: exit 2 is permanent and stops the loop, any other failure
    # is retried
    assert "until python -m report_composer.migrate;" in text, text
    assert re.search(r"\[ \$\$?s -eq 2 \] && exit 2", text), text
    assert svc.get("restart") in (None, "no")
    assert svc["image"] == default_tag["report-composer"]["image"]
    assert svc.get("environment") == default_tag["report-composer"].get("environment")
    deps = default_tag["report-composer"].get("depends_on") or {}
    assert deps.get("report-composer-migrate", {}).get("condition") == "service_completed_successfully"
    assert "platform" in deps


def test_report_grants_waits_for_the_engine_one_shot(default_tag):
    """report-grants runs after aisc-backend-migrate has made the engine tables."""
    deps = default_tag["report-grants"].get("depends_on") or {}
    assert deps.get("aisc-backend-migrate", {}).get("condition") == "service_completed_successfully"


def test_the_engine_one_shot_has_the_backend_environment(default_tag):
    """aisc-backend-migrate connects exactly as aisc-backend does, but for what only serving takes: the
    engine's own immudb account (the migration never uses immudb), the clients whose tokens it accepts, and
    the ledger mode its changes are written under."""
    svc = default_tag["aisc-backend-migrate"]
    engine = dict(default_tag["aisc-backend"].get("environment") or {})
    immudb = {k: engine.pop(k) for k in list(engine) if k.startswith("IMMUDB_")}
    assert set(immudb) == {"IMMUDB_URL", "IMMUDB_USER", "IMMUDB_PASSWORD", "IMMUDB_DATABASE"}
    serving = {k: engine.pop(k) for k in ("ENGINE_ACCEPTED_CLIENTS", "LEDGER_MODE")}
    assert serving["ENGINE_ACCEPTED_CLIENTS"] == "aisc-gateway"
    assert svc.get("environment") == engine
    assert svc["image"] == default_tag["aisc-backend"]["image"]
