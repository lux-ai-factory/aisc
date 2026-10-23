"""What the 2026-10 simplification pass tightened stays that way. Read-only unless a test says so."""

import json
import re
import subprocess

import yaml

from conftest import ROOT
from test_dashboard_bridge_token import scratch  # noqa: F401 (fixture: scripts/secrets.sh, realm, env.plugin_downloader)
from test_llm_keys import run_secrets, secrets_of


def test_the_platform_runner_runs_the_database_tests_instead_of_skipping_them():
    """test_authz_schema.py needs the database: without one, every test in it skips."""
    r = subprocess.run(["bash", str(ROOT / "scripts/test-platform.sh"), "-q", "-rs",
                        "tests/test_authz_schema.py"],
                       cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert "SKIPPED" not in r.stdout and "skipped" not in r.stdout.splitlines()[-1]


def test_only_the_compose_files_something_starts_are_left():
    left = {f.name for f in ROOT.glob("docker-compose*.yml")}
    assert not left & {"docker-compose.yml", "docker-compose-infra.yml", "docker-compose.demo.nbg.yml",
                       "docker-compose.plugin_downloader.yml"}
    assert {"docker-compose-infra.development.yml", "docker-compose.development.yml",
            "docker-compose.engine-standalone.yml"} <= left
    # the MQ_* aliases fed only docker-compose-infra.yml's ${MQ_*}: the eval worker takes CELERY_BROKER_URL,
    # and an env file here only fills compose's ${...}, it is not handed to a container
    for f in ("docker-compose-infra.development.yml", "docker-compose.development.yml", "env.plugin_downloader"):
        assert not re.search(r"(?<![A-Z_])MQ_[A-Z_]+", (ROOT / f).read_text()), f


def test_the_realm_has_no_client_for_controls_or_qualification():
    realm = json.loads((ROOT / "keycloak/aisc-realm.json").read_text())
    ids = {c["clientId"] for c in realm["clients"]}
    assert "controls" not in ids and "qualification" not in ids
    assert {"aisc-gateway", "aisc-webapp"} <= ids


def test_an_env_secrets_that_still_has_a_removed_secret_keeps_working(scratch):  # noqa: F811
    """An existing install keeps the line; secrets.sh neither fails nor drops it."""
    (scratch / "env.secrets").write_text("DASHBOARD_ADMIN_PASSWORD=kept\n")
    run_secrets(scratch)
    assert secrets_of(scratch).get("DASHBOARD_ADMIN_PASSWORD") == "kept"


def test_the_inspection_tools_run_only_under_their_profile():
    services = yaml.safe_load((ROOT / "docker-compose-infra.development.yml").read_text())["services"]
    for svc in ("pgadmin", "schema-docs"):
        assert services[svc].get("profiles") == ["inspect"], svc


def test_caddy_says_the_inspection_tools_are_off_instead_of_a_bare_502():
    """With the inspection tools off, Caddy answers with a page naming the profile that starts them."""
    caddy = (ROOT / "Caddyfile").read_text()
    assert "handle_errors" in caddy
    assert "{http.request.orig_uri.path}" in caddy
    assert "--profile inspect" in caddy


def test_keycloak_and_superset_do_not_connect_as_the_superuser():
    infra = yaml.safe_load((ROOT / "docker-compose-infra.development.yml").read_text())
    assert infra["services"]["keycloak"]["environment"]["KC_DB_USERNAME"] == "keycloak_app"
    assert infra["services"]["keycloak"]["depends_on"]["postgres-setup"] == \
        {"condition": "service_completed_successfully"}
    dev = (ROOT / "docker-compose.development.yml").read_text()
    uris = re.findall(r"SUPERSET_DB_URI:\s*(\S+)", dev)
    assert uris and all(u.startswith("postgresql+psycopg2://superset_app:") for u in uris), uris


def test_the_plugin_publisher_does_not_install_its_tools_at_every_start():
    """Build and twine come in its image, pinned, instead of a pip install on each bring-up."""
    dev = (ROOT / "docker-compose.development.yml").read_text()
    assert "pip install --quiet build twine" not in dev
    svc = yaml.safe_load(dev)["services"]["plugin-publisher"]
    assert svc["build"] == "infra/plugin-publisher"
    assert svc["image"] == "aisc-plugin-publisher:${AISC_IMAGE_TAG:-latest}" and svc["pull_policy"] == "never"
    dockerfile = (ROOT / "infra/plugin-publisher/Dockerfile").read_text()
    assert re.search(r"\bbuild==\d", dockerfile) and re.search(r"\btwine==\d", dockerfile)


def test_controls_builds_one_image_for_its_two_services():
    """Controls-migrate runs the image controls-web builds, as control-objectives-migrate does: the
    runner stage holds scripts/, prisma/ and node_modules, so the migration needs nothing else."""
    services = yaml.safe_load((ROOT / "docker-compose.development.yml").read_text())["services"]
    web, migrate = services["controls-web"], services["controls-migrate"]
    assert "build" not in migrate
    assert migrate["image"] == web["image"] and migrate["pull_policy"] == "never"


def test_test_only_packages_stay_out_of_the_sidecar_images():
    """Pytest and httpx are for the tests, so requirements-dev.txt, never the image's requirements.txt."""
    for svc in ("prefill", "ontology", "system_card_renderer"):
        d = ROOT / "apps/qualification/services" / svc
        names = lambda f: {re.split(r"[<>=!~\[ ;]", line.strip(), maxsplit=1)[0].lower()  # noqa: E731
                           for line in (d / f).read_text().splitlines() if line.strip() and not line.startswith(("#", "-"))}
        assert not names("requirements.txt") & {"pytest", "httpx"}, svc
        assert {"pytest", "httpx"} <= names("requirements-dev.txt"), svc
    verify = (ROOT / "scripts/verify.sh").read_text()
    for module in ("qualification prefill|", "qualification ontology|", "qualification pdf|"):
        line = next(line for line in verify.splitlines() if line.startswith(module))
        assert "-r requirements-dev.txt" in line, module


def test_flower_runs_only_under_the_inspect_profile():
    """The Celery monitor is a developer tool too; the engine site says so when it is off.
    No eval code reads CORS_ORIGINS, so compose stops setting it for flower and the worker."""
    services = yaml.safe_load((ROOT / "docker-compose.development.yml").read_text())["services"]
    assert services["aisc-eval-flower"].get("profiles") == ["inspect"]
    for name in ("aisc-eval-flower", "aisc-eval-worker"):
        assert "CORS_ORIGINS" not in (services[name].get("environment") or {}), name
    caddy = (ROOT / "Caddyfile").read_text()
    engine_site = caddy.split("{$CADDY_DOMAIN}:{$CADDY_PORT} {", 1)[1].split("\n}\n", 1)[0]
    assert "handle_errors" in engine_site and "/flower/" in engine_site and "--profile inspect" in engine_site
