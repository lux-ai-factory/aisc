"""Compose wiring of the stack with one database per project. Read-only: the compose files are copied and
resolved with `docker compose config` (the fixture of test_compose.py); nothing is started, stopped or built.
DSN values are never printed, only which database they name.
"""

from __future__ import annotations

import os
import re
import subprocess

import pytest

from conftest import ROOT
import compose_cfg
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


# qualification


@pytest.mark.parametrize("name", ["qualification-web", "qualification-migrate"])
def test_qualification_gets_a_project_database_template(compose, name):  # noqa: F811
    q, cfg = compose
    url = _env(cfg, name).get("PROJECT_DATABASE_URL", "")
    assert "{database}" in url, f"{name} PROJECT_DATABASE_URL has no {{database}}"
    assert "schema=qualification" in url, f"{name} PROJECT_DATABASE_URL lacks schema=qualification"


@pytest.mark.parametrize("name", ["qualification-web", "qualification-migrate"])
def test_qualification_has_no_platform_database(compose, name):  # noqa: F811
    """Qualification's only database DSN is the project template (forms are per project; there is no form
    library in platform)."""
    q, cfg = compose
    env = _env(cfg, name)
    assert "FORM_LIBRARY_DATABASE_URL" not in env, f"{name} still names a form library"
    assert "DATABASE_URL" not in env, f"{name} still has DATABASE_URL"


def test_qualification_migrate_runs_migrate_projects_after_the_platform(compose):  # noqa: F811
    q, cfg = compose
    svc = cfg["services"]["qualification-migrate"]
    assert "migrate-projects.mjs" in _command(svc), "qualification-migrate does not run migrate-projects.mjs"
    assert "platform" in _depends(svc), "qualification-migrate does not depend on platform"
    assert "exit 2" in _command(svc) or "-eq 2" in _command(svc), "exit 2 (permanent error) is not honoured"


# control objectives


def test_control_objectives_migrate_runs_migrate_projects(compose):  # noqa: F811
    q, cfg = compose
    svc = cfg["services"]["control-objectives-migrate"]
    assert "aisc_control_objectives.migrate_projects" in _command(svc), \
        "control-objectives-migrate does not run python -m aisc_control_objectives.migrate_projects"


@pytest.mark.parametrize("name", ["control-objectives", "control-objectives-migrate"])
def test_control_objectives_has_a_project_database_template(compose, name):  # noqa: F811
    q, cfg = compose
    env = _env(cfg, name)
    assert any("{database}" in str(v) for v in env.values() if DSN.match(str(v))), \
        f"{name} has no per-project DSN template with {{database}}"


# engine


def test_aisc_backend_migrate_one_shot_runs_migrate_projects(compose):  # noqa: F811
    q, cfg = compose
    svc = cfg["services"].get("aisc-backend-migrate")
    assert svc, "no service aisc-backend-migrate"
    assert "migrate_projects" in _command(svc), "aisc-backend-migrate does not run manage.py migrate_projects"
    assert svc.get("restart") in (None, "no"), "aisc-backend-migrate is not a one-shot"
    assert "aisc-backend-migrate" in _depends(cfg["services"]["aisc-backend"]), \
        "aisc-backend does not wait for aisc-backend-migrate"


# report composer and renderer


def test_composer_has_a_project_database_template_and_platform_for_the_library(compose):  # noqa: F811
    q, cfg = compose
    env = _env(cfg, "report-composer")
    assert "{database}" in env.get("REPORT_COMPOSER_PROJECT_DATABASE_URL", ""), \
        "report-composer REPORT_COMPOSER_PROJECT_DATABASE_URL missing or without {database}"
    assert _database(env.get("REPORT_COMPOSER_DATABASE_URL", "")) == "platform"


def test_renderer_reads_projects_from_their_database(compose):  # noqa: F811
    q, cfg = compose
    env = _env(cfg, "report-renderer")
    assert "{database}" in env.get("REPORT_PROJECT_DB_URL", ""), "REPORT_PROJECT_DB_URL"
    assert _database(env.get("REPORT_PLATFORM_DATABASE_URL", "")) == "platform", "REPORT_PLATFORM_DATABASE_URL"


def test_renderer_builds_from_report_generator_dir(tmp_path):
    """When REPORT_GENERATOR_DIR is set (here to ~/aisc-isolation-report-generator), the renderer's build
    context follows it."""
    wanted = str(os.path.expanduser("~/aisc-isolation-report-generator"))
    build = compose_cfg.config(tmp_path, env={"REPORT_GENERATOR_DIR": wanted})["services"]["report-renderer"]["build"]
    ctx = build["context"] if isinstance(build, dict) else build
    assert str(ctx).rstrip("/") == wanted


# dashboard


@pytest.mark.parametrize("name", ["dashboard", "dashboard-migrate"])
def test_dashboard_reads_memberships_over_a_plain_dsn_and_registers_no_platform_connection(compose, name):  # noqa: F811
    q, cfg = compose
    env = _env(cfg, name)
    assert "AISC_RESULTS_DB_URI" not in env, f"{name} still has AISC_RESULTS_DB_URI (the AISC Results connection)"
    if name == "dashboard":
        url = env.get("AISC_MEMBERSHIP_DB_URI", "")
        assert _database(url) == "platform" and "dashboard_ro" in url, \
            "dashboard AISC_MEMBERSHIP_DB_URI missing or not dashboard_ro on platform"


# the only platform DSNs are the membership and report library ones


ALLOWED_PLATFORM = {
    "qualification-web": set(),
    "qualification-migrate": set(),
    "control-objectives": {"DATABASE_URL"},
    "control-objectives-migrate": {"DATABASE_URL"},
    "report-composer": {"REPORT_COMPOSER_DATABASE_URL"},
    "report-renderer": {"REPORT_PLATFORM_DATABASE_URL"},
    "dashboard": {"AISC_MEMBERSHIP_DB_URI"},
}


@pytest.mark.parametrize("name", sorted(ALLOWED_PLATFORM))
def test_every_module_dsn_names_a_project_database_except_the_allowed_platform_ones(compose, name):  # noqa: F811
    q, cfg = compose
    env = _env(cfg, name)
    dsns = {k: str(v) for k, v in env.items() if DSN.match(str(v))}
    project = [k for k, v in dsns.items() if "{database}" in v or "/project_" in v]
    # the dashboard builds each project's Superset connection from AISC_PROJECT_DB_HOSTPORT (bridge), not a DSN
    assert project or name == "dashboard", f"{name} has no project database DSN"
    stray = sorted(k for k, v in dsns.items() if _database(v) == "platform" and k not in ALLOWED_PLATFORM[name])
    assert not stray, f"{name} has platform DSNs beyond the allowed ones: {stray}"


# service tokens are still required


def _required_tokens(text: str) -> set[str]:
    return {v for v in re.findall(r"\$\{([A-Z0-9_]*TOKEN[A-Z0-9_]*):\?", text)}


#: tokens whose service is gone: qualification-llm was removed
REMOVED_TOKENS = {"QUALIFICATION_WEB_TO_LLM_TOKEN"}


@pytest.mark.parametrize("path", FILES)
def test_every_service_token_required_before_isolation_is_still_required(path):
    """Per-caller service tokens stay `:?`-required in compose. Compared with the file at f01288a, the
    last commit before the per-project databases."""
    before = subprocess.run(["git", "show", f"f01288a:{path}"], cwd=ROOT, capture_output=True, text=True)
    assert before.returncode == 0, before.stderr
    lost = sorted(_required_tokens(before.stdout) - _required_tokens((ROOT / path).read_text()) - REMOVED_TOKENS)
    assert not lost, f"{path} no longer requires {lost}"
