"""How the report joins the stack: the composer, the renderer, their roles, secrets and routes.
Static: the compose files are copied to a scratch directory and
resolved with `docker compose config`; nothing is started, stopped or built. The last test reads the
session's full scripts/guard-frozen.sh run, which uses its own throwaway postgres containers.

Run from the repo root:

    uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests/test_report_stack.py
"""

import os
import re

import pytest

import compose_cfg
from conftest import ROOT, aisc_py

RAW_APP = (ROOT / "docker-compose.development.yml").read_text()
RAW_INFRA = (ROOT / "docker-compose-infra.development.yml").read_text()


@pytest.fixture(scope="module")
def compose(tmp_path_factory):
    return compose_cfg.config(tmp_path_factory.mktemp("compose-report"))


def service(cfg, name):
    svc = cfg["services"].get(name)
    assert svc, f"missing feature: no compose service {name}"
    return svc


def env_of(svc):
    return svc.get("environment") or {}


def volumes_of(svc):
    return svc.get("volumes") or []


# ── report-composer ──────────────────────────────────────────────────────────


def test_composer_service_is_internal_only(compose):
    """Report-composer is reached through Caddy only: no published port, on backend and
    frontend, exposing 8095."""
    svc = service(compose, "report-composer")
    assert not svc.get("ports"), "the composer must not publish a port"
    nets = set(svc.get("networks") or {})
    assert {"backend", "frontend"} <= nets
    assert "8095" in [str(e) for e in (svc.get("expose") or [])]


def test_composer_builds_the_app_folder(compose):
    """Built from apps/report-composer (a plain folder), image never pulled."""
    svc = service(compose, "report-composer")
    ctx = svc["build"]["context"] if isinstance(svc.get("build"), dict) else svc.get("build", "")
    assert str(ctx).rstrip("/").endswith("apps/report-composer")
    assert svc.get("pull_policy") == "never"


def test_composer_connects_with_its_own_role(compose):
    """The composer's database URL uses report_composer_rw on the platform database."""
    e = env_of(service(compose, "report-composer"))
    url = e.get("REPORT_COMPOSER_DATABASE_URL", "")
    assert "report_composer_rw" in url and url.rstrip("/").endswith("/platform"), url


def test_composer_sign_in_settings(compose):
    """Auth on, Keycloak issuer + JWKS, root path, launcher, the renderer's
    internal URL and token, and the origin the same-origin check compares with."""
    e = env_of(service(compose, "report-composer"))
    assert str(e.get("AUTH_ENABLED")).lower() == "true"
    for name in ("KEYCLOAK_ISSUER", "KEYCLOAK_JWKS_URL", "LAUNCHER_URL", "REPORT_SERVICE_TOKEN",
                 "PLATFORM_ORIGIN"):
        assert e.get(name), f"missing {name}"
    assert e.get("REPORT_COMPOSER_ROOT_PATH") == "/report-composer"
    assert e.get("REPORT_RENDERER_URL") == "http://report-renderer:8001"


def test_composer_mounts_the_shared_identity_read_only(compose):
    """aisc_identity is mounted from shared/identity, read-only, as in control-objectives."""
    vols = volumes_of(service(compose, "report-composer"))
    hits = [v for v in vols if str(v.get("source", "")).rstrip("/").endswith("shared/identity")]
    assert hits, "shared/identity is not mounted"
    assert all(v.get("read_only") for v in hits)


# ── report-renderer ──────────────────────────────────────────────────────────


def test_renderer_is_not_exposed(compose):
    """The renderer is called only by the composer: no published port, backend network
    only (not frontend, where Caddy routes), exposing 8001."""
    svc = service(compose, "report-renderer")
    assert not svc.get("ports")
    assert set(svc.get("networks") or {}) == {"backend"}
    assert "8001" in [str(e) for e in (svc.get("expose") or [])]


def test_renderer_reads_as_report_ro(compose):
    """Platform and superset as report_ro; the project database URL is a template with
    {database}, also as report_ro."""
    e = env_of(service(compose, "report-renderer"))
    plat = e.get("REPORT_PLATFORM_DATABASE_URL", "")
    sup = e.get("REPORT_SUPERSET_DATABASE_URL", "")
    proj = e.get("REPORT_PROJECT_DB_URL", "")
    assert "report_ro" in plat and plat.rstrip("/").endswith("/platform"), plat
    assert "report_ro" in sup and sup.rstrip("/").endswith("/superset"), sup
    assert "report_ro" in proj and "{database}" in proj, proj


def test_renderer_has_the_service_token(compose):
    """The renderer reads REPORT_SERVICE_TOKEN from its environment."""
    assert env_of(service(compose, "report-renderer")).get("REPORT_SERVICE_TOKEN")


def test_service_token_is_required_from_the_secrets(compose):
    """The token comes from env.secrets (`${REPORT_SERVICE_TOKEN:?...}`), never a literal."""
    uses = re.findall(r"REPORT_SERVICE_TOKEN:\s*(.+)", RAW_APP)
    assert uses, "missing feature: REPORT_SERVICE_TOKEN is not in docker-compose.development.yml"
    for u in uses:
        assert "${REPORT_SERVICE_TOKEN:?" in u, u


def test_renderer_mounts_vocab_and_objectives_read_only(compose):
    """airo_vocab.json and the objectives CSV are bind-mounted read-only, and
    the env paths point at the mount targets."""
    svc = service(compose, "report-renderer")
    e = env_of(svc)
    vols = volumes_of(svc)
    for src_end, var in (("apps/qualification/src/data/airo_vocab.json", "REPORT_AIRO_VOCAB_PATH"),
                         # the form speaks VAIR: the labels of its terms
                         ("apps/qualification/src/data/vair_vocab.json", "REPORT_VAIR_VOCAB_PATH"),
                         ("aisc_control_objectives/data/ai_act_control_objectives.csv",
                          "REPORT_OBJECTIVES_CSV_PATH")):
        hit = [v for v in vols if str(v.get("source", "")).endswith(src_end)]
        assert hit, f"{src_end} is not mounted"
        assert hit[0].get("read_only"), f"{src_end} must be read-only"
        assert e.get(var) == hit[0]["target"], f"{var} must point at {hit[0]['target']}"


def test_chart_images_are_off(compose):
    """The renderer ships with Superset chart screenshots off. report_renderer/superset.py takes the
    screenshot provider only for REPORT_CHART_IMAGES=superset, so anything else gives NoImageProvider."""
    e = env_of(service(compose, "report-renderer"))
    assert str(e.get("REPORT_CHART_IMAGES", "")).lower() != "superset"


# ── report-grants ────────────────────────────────────────────────────────────


def test_report_grants_one_shot(compose):
    """A postgres:15-alpine one-shot that runs /setup/report-grants.sh with both files
    mounted under /setup, after the three module migrations have completed."""
    svc = service(compose, "report-grants")
    assert str(svc.get("image", "")).startswith("postgres:15")
    assert str(svc.get("restart", "")) in ("no", '"no"')
    targets = {v.get("target") for v in volumes_of(svc)}
    assert {"/setup/report-grants.sh", "/setup/report-ro-grants.sql"} <= targets, targets
    cmd = svc.get("command")
    cmd = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
    assert "/setup/report-grants.sh" in cmd
    deps = svc.get("depends_on") or {}
    for m in ("qualification-migrate", "control-objectives-migrate", "controls-migrate"):
        assert m in deps, f"report-grants must wait for {m}"
        assert deps[m].get("condition") == "service_completed_successfully", m


# ── infra: report-roles.sql ──────────────────────────────────────────────────


def test_d6a_report_roles_in_initdb_after_superset(compose):
    """init/report-roles.sql runs on a fresh volume, after 50-superset-db.sql (it
    grants CONNECT on the superset database)."""
    pg = service(compose, "postgres")
    hit = [v for v in volumes_of(pg) if str(v.get("source", "")).endswith("init/report-roles.sql")]
    assert hit, "missing feature: init/report-roles.sql is not in postgres' initdb"
    target = hit[0]["target"]
    assert target.startswith("/docker-entrypoint-initdb.d/")
    assert os.path.basename(target) > "50-superset-db.sql", target


def test_d6a_report_roles_run_by_postgres_setup(compose):
    """postgres-setup mounts report-roles.sql and runs it on every start."""
    svc = service(compose, "postgres-setup")
    hit = [v for v in volumes_of(svc) if str(v.get("source", "")).endswith("init/report-roles.sql")]
    assert hit, "missing feature: postgres-setup does not mount report-roles.sql"
    cmd = svc.get("command")
    cmd = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
    assert hit[0]["target"] in cmd


# ── Caddy, launcher, secrets ─────────────────────────────────────────────────


def _caddy_block(text, opener):
    i = text.find(opener)
    if i < 0:
        return None
    depth, j = 0, text.index("{", i)
    for k in range(j, len(text)):
        if text[k] == "{":
            depth += 1
        elif text[k] == "}":
            depth -= 1
            if depth == 0:
                return text[j:k + 1]
    return None


def test_caddy_routes_the_composer_behind_sign_in():
    """Caddy: `handle_path /report-composer* { import protect; reverse_proxy report-composer:8095 }`."""
    text = (ROOT / "Caddyfile").read_text()
    block = _caddy_block(text, "handle_path /report-composer*")
    assert block, "missing feature: no handle_path /report-composer* in the Caddyfile"
    assert "import protect" in block
    assert re.search(r"reverse_proxy\s+report-composer:8095", block)


def test_caddy_never_routes_the_renderer():
    """The renderer is not routed through Caddy. (Already true.)"""
    assert "report-renderer" not in (ROOT / "Caddyfile").read_text()


def test_launcher_card_seven():
    """The report composer is the Report button of the AI Assessment Sandbox page, rewritten to
    /report-composer/p/{pid}; the project page has no report card any more."""
    page = (ROOT / "homepage/evidence.html").read_text()
    assert re.search(r'<a class="way" id="write-report" data-origin="engine" data-path="/report-composer/">Report</a>', page)
    assert re.search(r"aiscLink\(\$\('write-report'\), 'engine', '/report-composer/p/'\s*\+\s*enc\(p\.pid\)\)", page)
    assert 'id="report-composer-card"' not in (ROOT / "homepage/project.html").read_text()


def test_secrets_script_makes_the_report_secrets():
    """scripts/secrets.sh writes REPORT_SERVICE_TOKEN, REPORT_RO_PASSWORD and
    REPORT_COMPOSER_PASSWORD."""
    generated = {name for name, _ in aisc_py().SECRETS}
    for name in ("REPORT_SERVICE_TOKEN", "REPORT_RO_PASSWORD", "REPORT_COMPOSER_PASSWORD"):
        assert name in generated, f"missing feature: the install script does not write {name}"


# ── the final check ──────────────────────────────────────────────────────────


def test_final_guard_frozen_passes(guard_all):
    """The frozen files stay frozen: scripts/guard-frozen.sh (its checks G3 and G4) still passes. Reads the
    session's one full guard run (conftest.guard_all, throwaway containers only); it is the check every change
    must keep green."""
    r, _ = guard_all
    assert r.returncode == 0, (r.stdout + r.stderr)[-3000:]
    assert "GUARD PASS" in r.stdout
