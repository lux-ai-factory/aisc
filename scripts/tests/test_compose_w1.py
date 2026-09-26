"""Compose wiring of WP W1 that test_compose_isolation.py does not pin (03-coding-plan.md W1 4.0, 4.4, 4.6;
G9, I8.4, D5). Read-only: the compose files are copied and resolved with `docker compose config`; nothing is
started, stopped or built. No value of a credential is printed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest

from conftest import ROOT
from test_compose import FILES

BEFORE = "f01288a"  # stage 1 commit: the pre-isolation reference (G3)


def _resolve(tmp_path, extra_env: dict, *profiles: str) -> dict:
    args, required = [], set()
    for f in FILES:
        shutil.copy(ROOT / f, tmp_path / f)
        args += ["-f", str(tmp_path / f)]
        required |= set(re.findall(r"\$\{([A-Z0-9_]+):\?", (ROOT / f).read_text()))
    env = {k: v for k, v in os.environ.items() if k != "AISC_IMAGE_TAG"}
    env.update({k: "dummy" for k in required}, **extra_env)
    prof = [a for p in profiles for a in ("--profile", p)]
    r = subprocess.run(["docker", "compose", "-p", "aisc", "--project-directory", str(ROOT),
                        "--env-file", str(ROOT / "env.development"), *prof, *args, "config", "--format", "json"],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1000:]
    return json.loads(r.stdout)["services"]


@pytest.fixture(scope="module")
def default_tag(tmp_path_factory):
    return _resolve(tmp_path_factory.mktemp("w1-default"), {})


@pytest.fixture(scope="module")
def isolation_tag(tmp_path_factory):
    return _resolve(tmp_path_factory.mktemp("w1-isolation"), {"AISC_IMAGE_TAG": "isolation"}, "isolation")


def _built(services: dict) -> list[str]:
    return sorted(n for n, s in services.items() if s.get("build"))


def _before_images(tmp_path) -> dict[str, str]:
    """Image name of every built service at f01288a, as compose names it under project `aisc`."""
    args, required = [], set()
    for f in FILES:
        text = subprocess.run(["git", "show", f"{BEFORE}:{f}"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout
        (tmp_path / f).write_text(text)
        args += ["-f", str(tmp_path / f)]
        required |= set(re.findall(r"\$\{([A-Z0-9_]+):\?", text))
    env = {k: v for k, v in os.environ.items() if k != "AISC_IMAGE_TAG"}
    env.update({k: "dummy" for k in required})
    r = subprocess.run(["docker", "compose", "-p", "aisc", "--project-directory", str(ROOT),
                        "--env-file", str(ROOT / "env.development"), *args, "config", "--format", "json"],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1000:]
    services = json.loads(r.stdout)["services"]
    return {n: s.get("image") or f"aisc-{n}" for n, s in services.items() if s.get("build")}


def test_g9_every_built_service_is_tagged_by_aisc_image_tag(isolation_tag):
    """G9, W1 4.0: with AISC_IMAGE_TAG=isolation no built image resolves to :latest, and none is pulled."""
    wrong = {n: s.get("image") for n, s in isolation_tag.items()
             if (s.get("build") or str(s.get("image", "")).startswith("aisc-"))
             and not str(s.get("image", "")).endswith(":isolation")}
    assert not wrong, f"G9: images not following AISC_IMAGE_TAG: {wrong}"
    loose = sorted(n for n in _built(isolation_tag) if isolation_tag[n].get("pull_policy") != "never")
    assert not loose, f"G9: built services without pull_policy never: {loose}"


def test_g9_with_the_tag_unset_every_image_name_is_as_before(default_tag, tmp_path):
    """G9, W1 4.0: unset, every service built before keeps the image name the running stack uses."""
    before = {n: img if ":" in img else f"{img}:latest" for n, img in _before_images(tmp_path).items()}
    changed = {n: (img, default_tag[n].get("image")) for n, img in before.items()
               if n in default_tag and default_tag[n].get("image") != img}
    assert not changed, f"G9: image names changed with AISC_IMAGE_TAG unset: {changed}"
    assert default_tag["aisc-eval-flower"]["image"] == "aisc-eval:latest"


def test_i8_4_report_composer_migrate_one_shot(default_tag):
    """I8.4, W1 4.4: the composer migrates the library and every project database in a one-shot the composer
    waits for, with the composer's own environment."""
    svc = default_tag.get("report-composer-migrate")
    assert svc, "I8.4: no service report-composer-migrate"
    cmd = svc.get("command") or []
    text = " ".join(cmd) if isinstance(cmd, list) else cmd
    assert "python -m report_composer.migrate" in text
    # the migrate one-shots' convention (orchestrator's decision for V1): exit 2 is permanent and
    # stops the loop, any other failure is retried
    assert "until python -m report_composer.migrate;" in text, text
    assert re.search(r"\[ \$\$?s -eq 2 \] && exit 2", text), text
    assert svc.get("restart") in (None, "no")
    assert svc["image"] == default_tag["report-composer"]["image"]
    assert svc.get("environment") == default_tag["report-composer"].get("environment")
    deps = default_tag["report-composer"].get("depends_on") or {}
    assert deps.get("report-composer-migrate", {}).get("condition") == "service_completed_successfully"
    assert "platform" in deps


def test_i7_6_report_grants_waits_for_the_engine_one_shot(default_tag):
    """W1 4.4: report-grants runs after aisc-backend-migrate has made the engine tables."""
    deps = default_tag["report-grants"].get("depends_on") or {}
    assert deps.get("aisc-backend-migrate", {}).get("condition") == "service_completed_successfully"


def test_i7_6_the_engine_one_shot_has_the_backend_environment(default_tag):
    """W1 4.3: aisc-backend-migrate connects exactly as aisc-backend does (DB_NAME=platform is E1's template)."""
    svc = default_tag["aisc-backend-migrate"]
    assert svc.get("environment") == default_tag["aisc-backend"].get("environment")
    assert svc["image"] == default_tag["aisc-backend"]["image"]


def test_d5_isolate_one_shot_is_never_started_by_up(default_tag, isolation_tag):
    """D5, W1 4.6: the move tool runs as a separate one-shot behind profile `isolation`, as the superuser, with
    the password only in PGPASSWORD (never inside the URL), from the platform image."""
    assert "isolate" not in default_tag, "D5: isolate must not start without --profile isolation"
    svc = isolation_tag["isolate"]
    assert svc.get("profiles") == ["isolation"]
    assert svc.get("entrypoint") == ["python", "-m", "platform_service.isolate"]
    assert svc["image"] == "aisc-platform:isolation"
    assert not svc.get("build"), "D5: isolate reuses the platform image, it does not build one"
    env = svc.get("environment") or {}
    url = env.get("ISOLATE_SUPERUSER_URL", "")
    assert re.match(r"^postgresql://[^:@/]+@postgres:5432/platform$", url), \
        "D5: ISOLATE_SUPERUSER_URL must name the superuser on platform without a password"
    assert env.get("PGPASSWORD"), "D5: PGPASSWORD is not set"
    assert svc.get("restart") in (None, "no")
    assert "PGPASSWORD" not in (isolation_tag["platform"].get("environment") or {}), \
        "D5: the long-running platform service must not hold the superuser password"
