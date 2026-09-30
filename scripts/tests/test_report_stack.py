"""How the report joins the stack (report run 2026-09-23: 01-specs R4.1.2, R4.1.3, R5.4.1, R7.3.5;
02 D3, D6, D10, D11, D13, O1). Static: the compose files are copied to a scratch directory and
resolved with `docker compose config`; nothing is started, stopped or built. The last test runs
scripts/guard-frozen.sh, which uses its own throwaway postgres containers.

Run from the repo root:

    uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests/test_report_stack.py
"""

import json
import os
import re
import shutil
import subprocess

import pytest

from conftest import ROOT

FILES = ["docker-compose-infra.development.yml", "docker-compose.development.yml"]
RAW_APP = (ROOT / "docker-compose.development.yml").read_text()
RAW_INFRA = (ROOT / "docker-compose-infra.development.yml").read_text()


@pytest.fixture(scope="module")
def compose(tmp_path_factory):
    d = tmp_path_factory.mktemp("compose-report")
    args, required = [], set()
    for f in FILES:
        shutil.copy(ROOT / f, d / f)
        args += ["-f", str(d / f)]
        required |= set(re.findall(r"\$\{([A-Z0-9_]+):\?", (ROOT / f).read_text()))
    # secrets the files demand are given dummy values; env.secrets is never read
    env = {**os.environ, **{k: "dummy" for k in required}}
    base = ["docker", "compose", "-p", "aisc-t-config", "--project-directory", str(ROOT),
            "--env-file", str(ROOT / "env.development"), *args]
    j = subprocess.run(base + ["config", "--format", "json"], env=env, capture_output=True, text=True)
    assert j.returncode == 0, j.stderr[-2000:]
    return json.loads(j.stdout)


def service(cfg, name):
    svc = cfg["services"].get(name)
    assert svc, f"missing feature: no compose service {name}"
    return svc


def env_of(svc):
    return svc.get("environment") or {}


def volumes_of(svc):
    return svc.get("volumes") or []


# ── report-composer ──────────────────────────────────────────────────────────


def test_r4_1_2_composer_service_is_internal_only(compose):
    """R4.1.2: report-composer is reached through Caddy only: no published port, on backend and
    frontend, exposing 8095."""
    svc = service(compose, "report-composer")
    assert not svc.get("ports"), "the composer must not publish a port"
    nets = set(svc.get("networks") or {})
    assert {"backend", "frontend"} <= nets
    assert "8095" in [str(e) for e in (svc.get("expose") or [])]


def test_r4_1_2_composer_builds_the_app_folder(compose):
    """R4.1.2: built from apps/report-composer (a plain folder), image never pulled."""
    svc = service(compose, "report-composer")
    ctx = svc["build"]["context"] if isinstance(svc.get("build"), dict) else svc.get("build", "")
    assert str(ctx).rstrip("/").endswith("apps/report-composer")
    assert svc.get("pull_policy") == "never"


def test_r4_1_3_composer_connects_with_its_own_role(compose):
    """R4.1.3, D13: the composer's database URL uses report_composer_rw on the platform database."""
    e = env_of(service(compose, "report-composer"))
    url = e.get("REPORT_COMPOSER_DATABASE_URL", "")
    assert "report_composer_rw" in url and url.rstrip("/").endswith("/platform"), url


def test_r4_4_1_composer_sign_in_settings(compose):
    """R4.4.1, R4.4.6, R5.4.1: auth on, Keycloak issuer + JWKS, root path, launcher, the renderer's
    internal URL and token, and the origin the same-origin check compares with."""
    e = env_of(service(compose, "report-composer"))
    assert str(e.get("AUTH_ENABLED")).lower() == "true"
    for name in ("KEYCLOAK_ISSUER", "KEYCLOAK_JWKS_URL", "LAUNCHER_URL", "REPORT_SERVICE_TOKEN",
                 "PLATFORM_ORIGIN"):
        assert e.get(name), f"missing {name}"
    assert e.get("REPORT_COMPOSER_ROOT_PATH") == "/report-composer"
    assert e.get("REPORT_RENDERER_URL") == "http://report-renderer:8001"


def test_r4_4_1_composer_mounts_the_shared_identity_read_only(compose):
    """R4.4.1: aisc_identity is mounted from shared/identity, read-only, as in control-objectives."""
    vols = volumes_of(service(compose, "report-composer"))
    hits = [v for v in vols if str(v.get("source", "")).rstrip("/").endswith("shared/identity")]
    assert hits, "shared/identity is not mounted"
    assert all(v.get("read_only") for v in hits)


# ── report-renderer ──────────────────────────────────────────────────────────


def test_r5_4_1_renderer_is_not_exposed(compose):
    """R5.4.1: the renderer is called only by the composer: no published port, backend network
    only (not frontend, where Caddy routes), exposing 8001."""
    svc = service(compose, "report-renderer")
    assert not svc.get("ports")
    assert set(svc.get("networks") or {}) == {"backend"}
    assert "8001" in [str(e) for e in (svc.get("expose") or [])]


def test_r6_1_renderer_reads_as_report_ro(compose):
    """R6.1, D1: platform and superset as report_ro; the project database URL is a template with
    {database}, also as report_ro."""
    e = env_of(service(compose, "report-renderer"))
    plat = e.get("REPORT_PLATFORM_DATABASE_URL", "")
    sup = e.get("REPORT_SUPERSET_DATABASE_URL", "")
    proj = e.get("REPORT_PROJECT_DB_URL", "")
    assert "report_ro" in plat and plat.rstrip("/").endswith("/platform"), plat
    assert "report_ro" in sup and sup.rstrip("/").endswith("/superset"), sup
    assert "report_ro" in proj and "{database}" in proj, proj


def test_r5_4_1_renderer_has_the_service_token(compose):
    """R5.4.1: the renderer reads REPORT_SERVICE_TOKEN from its environment."""
    assert env_of(service(compose, "report-renderer")).get("REPORT_SERVICE_TOKEN")


def test_r7_3_5_service_token_is_required_from_the_secrets(compose):
    """R7.3.5: the token comes from env.secrets (`${REPORT_SERVICE_TOKEN:?...}`), never a literal."""
    uses = re.findall(r"REPORT_SERVICE_TOKEN:\s*(.+)", RAW_APP)
    assert uses, "missing feature: REPORT_SERVICE_TOKEN is not in docker-compose.development.yml"
    for u in uses:
        assert "${REPORT_SERVICE_TOKEN:?" in u, u


def test_d3_renderer_mounts_vocab_and_objectives_read_only(compose):
    """D3, R2.3.3, R2.4.2: airo_vocab.json and the objectives CSV are bind-mounted read-only, and
    the env paths point at the mount targets."""
    svc = service(compose, "report-renderer")
    e = env_of(svc)
    vols = volumes_of(svc)
    for src_end, var in (("apps/qualification/src/data/airo_vocab.json", "REPORT_AIRO_VOCAB_PATH"),
                         # the form speaks VAIR (2026-09-30): the labels of its terms
                         ("apps/qualification/src/data/vair_vocab.json", "REPORT_VAIR_VOCAB_PATH"),
                         ("aisc_control_objectives/data/ai_act_control_objectives.csv",
                          "REPORT_OBJECTIVES_CSV_PATH")):
        hit = [v for v in vols if str(v.get("source", "")).endswith(src_end)]
        assert hit, f"{src_end} is not mounted"
        assert hit[0].get("read_only"), f"{src_end} must be read-only"
        assert e.get(var) == hit[0]["target"], f"{var} must point at {hit[0]['target']}"


def test_d10_renderer_builds_with_the_interface_only(compose):
    """D10, revised 2026-09-29: the renderer image is built from the report-generator submodule with one
    additional context, the report plugin interface; no evaluation tool's report plugin."""
    svc = service(compose, "report-renderer")
    b = svc.get("build")
    assert isinstance(b, dict), "the renderer must have a build section"
    ctxs = b.get("additional_contexts") or {}
    assert set(ctxs) == {"interface"}, ctxs
    assert str(b.get("context", "")).rstrip("/").endswith("apps/report-generator")


def test_o1_chart_images_off_tonight(compose):
    """O1: REPORT_CHART_IMAGES is not `superset` (NoImageProvider)."""
    e = env_of(service(compose, "report-renderer"))
    assert str(e.get("REPORT_CHART_IMAGES", "")).lower() != "superset"


def test_o1_no_superset_worker(compose):
    """O1: no compose change for Superset: there is no dashboard-worker service. (Already true.)"""
    assert "dashboard-worker" not in compose["services"]


# ── report-grants ────────────────────────────────────────────────────────────


def test_d6_report_grants_one_shot(compose):
    """D6 (b)(c): a postgres:15-alpine one-shot that runs /setup/report-grants.sh with both files
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


def test_d6_report_grants_files_exist():
    """D6: init/report-ro-grants.sql and scripts/report-grants.sh exist."""
    for p in ("init/report-ro-grants.sql", "scripts/report-grants.sh"):
        assert (ROOT / p).exists(), f"missing feature: {p}"


# ── infra: report-roles.sql ──────────────────────────────────────────────────


def test_d6a_report_roles_in_initdb_after_superset(compose):
    """D6 (a), D13: init/report-roles.sql runs on a fresh volume, after 50-superset-db.sql (it
    grants CONNECT on the superset database)."""
    pg = service(compose, "postgres")
    hit = [v for v in volumes_of(pg) if str(v.get("source", "")).endswith("init/report-roles.sql")]
    assert hit, "missing feature: init/report-roles.sql is not in postgres' initdb"
    target = hit[0]["target"]
    assert target.startswith("/docker-entrypoint-initdb.d/")
    assert os.path.basename(target) > "50-superset-db.sql", target


def test_d6a_report_roles_run_by_postgres_setup(compose):
    """D6 (a): postgres-setup mounts report-roles.sql and runs it on every start."""
    svc = service(compose, "postgres-setup")
    hit = [v for v in volumes_of(svc) if str(v.get("source", "")).endswith("init/report-roles.sql")]
    assert hit, "missing feature: postgres-setup does not mount report-roles.sql"
    cmd = svc.get("command")
    cmd = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
    assert hit[0]["target"] in cmd


def test_d6_guard_init_files_do_not_mention_report_roles():
    """D6, R7.3.6: the report grants are outside the two init files the guard dumps (G1/G2), so
    the frozen-schema verdict cannot change. (Already true.)"""
    for p in ("init/platform-db.sql", "init/project-databases.sql"):
        text = (ROOT / p).read_text()
        assert "report_ro" not in text and "report_composer" not in text, p


def test_d6c_project_template_file_exists():
    """D6 (c): platform/project-template/0003_report.sql exists and names report_ro."""
    p = ROOT / "platform/project-template/0003_report.sql"
    assert p.exists(), "missing feature: platform/project-template/0003_report.sql"
    assert "report_ro" in p.read_text()


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


def test_r4_1_2_caddy_routes_the_composer_behind_sign_in():
    """R4.1.2: `handle_path /report-composer* { import protect; reverse_proxy report-composer:8095 }`."""
    text = (ROOT / "Caddyfile").read_text()
    block = _caddy_block(text, "handle_path /report-composer*")
    assert block, "missing feature: no handle_path /report-composer* in the Caddyfile"
    assert "import protect" in block
    assert re.search(r"reverse_proxy\s+report-composer:8095", block)


def test_r5_4_1_caddy_never_routes_the_renderer():
    """R5.4.1: the renderer is not routed through Caddy. (Already true.)"""
    assert "report-renderer" not in (ROOT / "Caddyfile").read_text()


def test_r4_1_2_launcher_card_seven():
    """R4.1.2, D11: homepage/project.html has the report card (id report-composer-card) and an inProject
    entry that rewrites it to /report-composer/p/{pid}. It is step 6 since the launcher (2026-09-25)
    shows controls and test execution as the two ways into one "Evidence" step (4)."""
    html = (ROOT / "homepage/project.html").read_text()
    m = re.search(r'<a class="card" id="report-composer-card"[^>]*>(.*?)</a>', html, re.S)
    assert m, "missing feature: no report-composer-card on the launcher"
    assert re.search(r'<span class="n">6</span>', m.group(1))
    assert re.search(r"'report-composer-card':\s*'http://localhost/report-composer/p/'", html)


def test_r7_3_5_secrets_script_makes_the_report_secrets():
    """R7.3.5, D6, D13: scripts/secrets.sh writes REPORT_SERVICE_TOKEN, REPORT_RO_PASSWORD and
    REPORT_COMPOSER_PASSWORD."""
    text = (ROOT / "scripts/secrets.sh").read_text()
    for name in ("REPORT_SERVICE_TOKEN", "REPORT_RO_PASSWORD", "REPORT_COMPOSER_PASSWORD"):
        assert re.search(rf"^{name}=", text, re.M), f"missing feature: secrets.sh does not write {name}"


# ── the final check ──────────────────────────────────────────────────────────


def test_final_guard_frozen_passes(tmp_path):
    """RULES "FROZEN", R7.3.6: scripts/guard-frozen.sh (G1..G5) still passes. Throwaway containers
    only. Passes today; it is the check stage 5 must keep green."""
    r = subprocess.run([str(ROOT / "scripts/guard-frozen.sh")], cwd=ROOT, capture_output=True,
                       text=True, env={**os.environ, "GUARD_OUT": str(tmp_path)}, timeout=1200)
    assert r.returncode == 0, (r.stdout + r.stderr)[-3000:]
    assert "GUARD PASS" in r.stdout
