"""Compose wiring of the isolated stack (01-specs.md I3.6, I3.8, I5.5, I7.6, I8.1, I8.4, I9.1, I9.2, I10.2,
I16.4, I18.1). Read-only: the compose files are copied and resolved with `docker compose config` (the fixture of
test_compose.py); nothing is started, stopped or built. DSN values are never printed, only which
database they name.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest

from conftest import ROOT
from test_compose import FILES, compose  # noqa: F401  (the resolved-config fixture)

DSN = re.compile(r"^postgres(ql)?(\+\w+)?://")


def _env(cfg, name) -> dict:
    svc = cfg["services"].get(name)
    assert svc is not None, f"no service {name}"
    env = svc.get("environment") or {}
    return env if isinstance(env, dict) else dict(e.split("=", 1) for e in env)


def _database(url: str) -> str:
    """The database part of a DSN, never the credentials."""
    return url.split("@", 1)[-1].split("/", 1)[-1].split("?", 1)[0] if "/" in url.split("@", 1)[-1] else ""


def _command(svc) -> str:
    c = svc.get("command") or svc.get("entrypoint") or ""
    return " ".join(c) if isinstance(c, list) else str(c)


def _depends(svc) -> set:
    d = svc.get("depends_on") or {}
    return set(d) if isinstance(d, (dict, list)) else set()


# ── qualification (I3.6, I3.8, I4.2) ─────────────────────────────────────────


@pytest.mark.parametrize("name", ["qualification-web", "qualification-migrate"])
def test_i3_8_qualification_gets_a_project_database_template(compose, name):  # noqa: F811
    q, cfg = compose
    url = _env(cfg, name).get("PROJECT_DATABASE_URL", "")
    assert "{database}" in url, f"I3.8: {name} PROJECT_DATABASE_URL has no {{database}}"
    assert "schema=qualification" in url, f"I3.8: {name} PROJECT_DATABASE_URL lacks schema=qualification"


@pytest.mark.parametrize("name", ["qualification-web", "qualification-migrate"])
def test_i3_8_qualification_reaches_platform_only_for_the_form_library(compose, name):  # noqa: F811
    q, cfg = compose
    env = _env(cfg, name)
    assert _database(env.get("FORM_LIBRARY_DATABASE_URL", "")) == "platform", \
        f"I3.8, I4.2: {name} FORM_LIBRARY_DATABASE_URL is not on platform"
    assert "DATABASE_URL" not in env, f"I3.8: {name} still has DATABASE_URL"


def test_i3_6_qualification_migrate_runs_migrate_projects_after_the_platform(compose):  # noqa: F811
    q, cfg = compose
    svc = cfg["services"]["qualification-migrate"]
    assert "migrate-projects.mjs" in _command(svc), "I3.6: qualification-migrate does not run migrate-projects.mjs"
    assert "platform" in _depends(svc), "I3.6: qualification-migrate does not depend on platform"
    assert "exit 2" in _command(svc) or "-eq 2" in _command(svc), "I3.6: exit 2 (permanent error) is not honoured"


# ── control objectives (I5.1, I5.5) ──────────────────────────────────────────


def test_i5_5_control_objectives_migrate_runs_migrate_projects(compose):  # noqa: F811
    q, cfg = compose
    svc = cfg["services"]["control-objectives-migrate"]
    assert "aisc_control_objectives.migrate_projects" in _command(svc), \
        "I5.5: control-objectives-migrate does not run python -m aisc_control_objectives.migrate_projects"


@pytest.mark.parametrize("name", ["control-objectives", "control-objectives-migrate"])
def test_i5_1_control_objectives_has_a_project_database_template(compose, name):  # noqa: F811
    q, cfg = compose
    env = _env(cfg, name)
    assert any("{database}" in str(v) for v in env.values() if DSN.match(str(v))), \
        f"I5.1: {name} has no per-project DSN template with {{database}}"


# ── engine (I7.1, I7.6) ──────────────────────────────────────────────────────


def test_i7_6_aisc_backend_no_longer_migrates_platform(compose):  # noqa: F811
    q, cfg = compose
    cmd = _command(cfg["services"]["aisc-backend"])
    assert not re.search(r"manage\.py migrate(\s|$|&|;)", cmd), "I7.6: aisc-backend still runs manage.py migrate"


def test_i7_6_aisc_backend_migrate_one_shot_runs_migrate_projects(compose):  # noqa: F811
    q, cfg = compose
    svc = cfg["services"].get("aisc-backend-migrate")
    assert svc, "I7.6: no service aisc-backend-migrate"
    assert "migrate_projects" in _command(svc), "I7.6: aisc-backend-migrate does not run manage.py migrate_projects"
    assert svc.get("restart") in (None, "no"), "I7.6: aisc-backend-migrate is not a one-shot"
    assert "aisc-backend-migrate" in _depends(cfg["services"]["aisc-backend"]), \
        "I7.6: aisc-backend does not wait for aisc-backend-migrate"


# ── report composer and renderer (I8.1, I8.4, I9.1, I9.2) ─────────────────────


def test_i8_1_composer_has_a_project_database_template_and_platform_for_the_library(compose):  # noqa: F811
    q, cfg = compose
    env = _env(cfg, "report-composer")
    assert "{database}" in env.get("REPORT_COMPOSER_PROJECT_DATABASE_URL", ""), \
        "I8.1: report-composer REPORT_COMPOSER_PROJECT_DATABASE_URL missing or without {database}"
    assert _database(env.get("REPORT_COMPOSER_DATABASE_URL", "")) == "platform"


def test_i9_2_renderer_reads_projects_from_their_database(compose):  # noqa: F811
    q, cfg = compose
    env = _env(cfg, "report-renderer")
    assert "{database}" in env.get("REPORT_PROJECT_DB_URL", ""), "I9.2: REPORT_PROJECT_DB_URL"
    assert _database(env.get("REPORT_PLATFORM_DATABASE_URL", "")) == "platform", "I9.2: REPORT_PLATFORM_DATABASE_URL"


def test_i9_1_renderer_builds_from_report_generator_dir(tmp_path):
    """I9.1, D9: isolation builds set REPORT_GENERATOR_DIR to ~/aisc-isolation-report-generator and the
    renderer's build context follows it."""
    args, required = [], set()
    for f in FILES:
        shutil.copy(ROOT / f, tmp_path / f)
        args += ["-f", str(tmp_path / f)]
        required |= set(re.findall(r"\$\{([A-Z0-9_]+):\?", (ROOT / f).read_text()))
    wanted = str(os.path.expanduser("~/aisc-isolation-report-generator"))
    env = {**os.environ, **{k: "dummy" for k in required}, "REPORT_GENERATOR_DIR": wanted}
    r = subprocess.run(["docker", "compose", "-p", "aisc-t-config", "--project-directory", str(ROOT),
                        "--env-file", str(ROOT / "env.development"), *args, "config", "--format", "json"],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1000:]
    build = json.loads(r.stdout)["services"]["report-renderer"]["build"]
    ctx = build["context"] if isinstance(build, dict) else build
    assert str(ctx).rstrip("/") == wanted


# ── dashboard (I10.2) ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["dashboard", "dashboard-migrate"])
def test_i10_2_dashboard_reads_memberships_over_a_plain_dsn_and_registers_no_platform_connection(compose, name):  # noqa: F811
    q, cfg = compose
    env = _env(cfg, name)
    assert "AISC_RESULTS_DB_URI" not in env, f"I10.2: {name} still has AISC_RESULTS_DB_URI (the AISC Results connection)"
    if name == "dashboard":
        url = env.get("AISC_MEMBERSHIP_DB_URI", "")
        assert _database(url) == "platform" and "dashboard_ro" in url, \
            "I10.2: dashboard AISC_MEMBERSHIP_DB_URI missing or not dashboard_ro on platform"


# ── I16.4: the only platform DSNs are the membership and library ones ───────────


ALLOWED_PLATFORM = {
    "qualification-web": {"FORM_LIBRARY_DATABASE_URL"},
    "qualification-migrate": {"FORM_LIBRARY_DATABASE_URL"},
    "control-objectives": {"DATABASE_URL"},
    "control-objectives-migrate": {"DATABASE_URL"},
    "report-composer": {"REPORT_COMPOSER_DATABASE_URL"},
    "report-renderer": {"REPORT_PLATFORM_DATABASE_URL"},
    "dashboard": {"AISC_MEMBERSHIP_DB_URI"},
}


@pytest.mark.parametrize("name", sorted(ALLOWED_PLATFORM))
def test_i16_4_every_module_dsn_names_a_project_database_except_the_allowed_platform_ones(compose, name):  # noqa: F811
    q, cfg = compose
    env = _env(cfg, name)
    dsns = {k: str(v) for k, v in env.items() if DSN.match(str(v))}
    project = [k for k, v in dsns.items() if "{database}" in v or "/project_" in v]
    # the dashboard builds each project's Superset connection from AISC_PROJECT_DB_HOSTPORT (bridge), not a DSN
    assert project or name == "dashboard", f"I16.4: {name} has no project database DSN"
    stray = sorted(k for k, v in dsns.items() if _database(v) == "platform" and k not in ALLOWED_PLATFORM[name])
    assert not stray, f"I16.4: {name} has platform DSNs beyond the allowed ones: {stray}"


# ── I18.1 service tokens survive ───────────────────────────────────────────


def _required_tokens(text: str) -> set[str]:
    return {v for v in re.findall(r"\$\{([A-Z0-9_]*TOKEN[A-Z0-9_]*):\?", text)}


@pytest.mark.parametrize("path", FILES)
def test_i18_1_every_service_token_required_before_isolation_is_still_required(path):
    """I18.1: per-caller service tokens stay `:?`-required in compose; isolation drops none of them.
    Compared with the file as committed at the start of the isolation branch (f01288a, stage 1)."""
    before = subprocess.run(["git", "show", f"f01288a:{path}"], cwd=ROOT, capture_output=True, text=True)
    assert before.returncode == 0, before.stderr
    lost = sorted(_required_tokens(before.stdout) - _required_tokens((ROOT / path).read_text()))
    assert not lost, f"I18.1: {path} no longer requires {lost}"
