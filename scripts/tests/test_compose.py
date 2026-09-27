"""Compose file rules (03 WP6a, WP2). Read-only: the compose files are copied to a scratch
directory and resolved with `docker compose config`; nothing is started, stopped or built."""

import json
import os
import re
import shutil
import subprocess

import pytest

from conftest import ROOT

FILES = ["docker-compose-infra.development.yml", "docker-compose.development.yml"]


@pytest.fixture(scope="module")
def compose(tmp_path_factory):
    d = tmp_path_factory.mktemp("compose")
    args, required = [], set()
    for f in FILES:
        shutil.copy(ROOT / f, d / f)
        args += ["-f", str(d / f)]
        required |= set(re.findall(r"\$\{([A-Z0-9_]+):\?", (ROOT / f).read_text()))
    # secrets the files demand are given dummy values; env.secrets is never read
    env = {**os.environ, **{k: "dummy" for k in required}}
    base = ["docker", "compose", "-p", "aisc-t-config", "--project-directory", str(ROOT),
            "--env-file", str(ROOT / "env.development"), *args]
    q = subprocess.run(base + ["config", "-q"], env=env, capture_output=True, text=True)
    j = subprocess.run(base + ["config", "--format", "json"], env=env, capture_output=True, text=True)
    return q, (json.loads(j.stdout) if j.returncode == 0 else None)


def test_s6a_compose_config_is_valid(compose):
    """WP6a: `docker compose -f <copy> config -q` passes."""
    q, cfg = compose
    assert q.returncode == 0, q.stderr[-2000:]


def test_s6a_qualification_agents_service(compose):
    """WP6a: service qualification-agents builds services/agents, on network backend, with
    LLM_SERVICE_URL=http://qualification-llm:4000."""
    q, cfg = compose
    svc = cfg["services"].get("qualification-agents")
    assert svc, "no service qualification-agents"
    ctx = svc["build"]["context"] if isinstance(svc.get("build"), dict) else svc.get("build", "")
    assert str(ctx).rstrip("/").endswith("apps/qualification/services/agents")
    assert "backend" in (svc.get("networks") or {})
    assert (svc.get("environment") or {}).get("LLM_SERVICE_URL") == "http://qualification-llm:4000"


def test_s6a_qualification_web_reaches_the_agents(compose):
    """WP6a: qualification-web gets AGENT_SERVICE_URL on the port service.py is served on."""
    q, cfg = compose
    dockerfile = (ROOT / "apps/qualification/services/agents/Dockerfile").read_text()
    port = re.search(r'"--port", "(\d+)"', dockerfile).group(1)
    value = (cfg["services"]["qualification-web"].get("environment") or {}).get("AGENT_SERVICE_URL")
    assert value == f"http://qualification-agents:{port}"


def test_wp2_aisc_backend_has_no_platform_url(compose):
    """WP2 code: PLATFORM_URL (from c0f460e) is gone from aisc-backend."""
    q, cfg = compose
    names = set(cfg["services"]["aisc-backend"].get("environment") or {})
    assert "PLATFORM_URL" not in names


# ── LLM keys (pipeline 2026-09-24-llm-keys, 01-specs.md S6.1, S6.2, S6.7) ─────
# A secret given as `${NAME:?...}` is in the fixture's `required` set and so resolves to "dummy":
# that value proves the `:?` form (D9) without reading env.secrets.


def _extra_hosts(svc):
    hosts = svc.get("extra_hosts") or []
    if isinstance(hosts, dict):
        return {f"{k}:{v}" for k, v in hosts.items()}
    return {h.replace("=", ":", 1) for h in hosts}


def test_s6_1_platform_gets_the_two_secrets_and_the_ollama_default(compose):
    q, cfg = compose
    env = cfg["services"]["platform"].get("environment") or {}
    assert env.get("PLATFORM_SECRETS_KEY") == "dummy", "PLATFORM_SECRETS_KEY is not a required `:?` variable"
    for name in ("PLATFORM_CARD_AGENT_TOKEN", "PLATFORM_RISK_MAPPER_TOKEN"):
        assert env.get(name) == "dummy", f"{name} is not a required `:?` variable"
    assert "PLATFORM_INTERNAL_TOKEN" not in env, "the platform takes one token per system, not a shared one"
    assert env.get("PLATFORM_OLLAMA_BASE_URL") == "http://host.docker.internal:11434"
    assert "host.docker.internal:host-gateway" in _extra_hosts(cfg["services"]["platform"])


def test_s6_2_the_card_agent_reaches_the_platform_with_the_token(compose):
    q, cfg = compose
    svc = cfg["services"]["qualification-agents"]
    env = svc.get("environment") or {}
    assert env.get("PLATFORM_URL") == "http://platform:8000"
    assert env.get("PLATFORM_INTERNAL_TOKEN") == "dummy"
    assert "host.docker.internal:host-gateway" in _extra_hosts(svc)
    assert "backend" in (svc.get("networks") or {})


def test_s6_2_the_risk_mapper_gets_the_token(compose):
    q, cfg = compose
    svc = cfg["services"]["control-objectives"]
    env = svc.get("environment") or {}
    assert env.get("PLATFORM_INTERNAL_TOKEN") == "dummy"
    assert env.get("PLATFORM_URL")
    assert "backend" in (svc.get("networks") or {})
    assert "backend" in (cfg["services"]["platform"].get("networks") or {})


def test_s6_7_the_compose_files_stay_valid_with_the_new_variables(compose):
    q, cfg = compose
    assert q.returncode == 0, q.stderr[-2000:]
    names = {n for s in ("platform", "qualification-agents", "control-objectives")
             for n in (cfg["services"][s].get("environment") or {})}
    assert {"PLATFORM_SECRETS_KEY", "PLATFORM_CARD_AGENT_TOKEN", "PLATFORM_RISK_MAPPER_TOKEN",
            "PLATFORM_INTERNAL_TOKEN", "PLATFORM_OLLAMA_BASE_URL", "PLATFORM_URL"} <= names
    assert not (cfg["services"]["platform"].get("ports")), "the platform must publish no port (S5.5)"


def test_each_agent_gets_the_token_of_its_own_system_only(tmp_path):
    """The card agent holds the card agent's token and the risk mapper the risk mapper's, so
    neither can resolve the other's key (2026-09-25)."""
    args, required = [], set()
    for f in FILES:
        shutil.copy(ROOT / f, tmp_path / f)
        args += ["-f", str(tmp_path / f)]
        required |= set(re.findall(r"\$\{([A-Z0-9_]+):\?", (ROOT / f).read_text()))
    env = {**os.environ, **{k: "dummy" for k in required},
           "PLATFORM_CARD_AGENT_TOKEN": "card-token", "PLATFORM_RISK_MAPPER_TOKEN": "risk-token"}
    j = subprocess.run(["docker", "compose", "-p", "aisc-t-config", "--project-directory", str(ROOT),
                        "--env-file", str(ROOT / "env.development"), *args, "config", "--format", "json"],
                       env=env, capture_output=True, text=True)
    assert j.returncode == 0, j.stderr[-2000:]
    services = json.loads(j.stdout)["services"]
    assert services["qualification-agents"]["environment"]["PLATFORM_INTERNAL_TOKEN"] == "card-token"
    assert services["control-objectives"]["environment"]["PLATFORM_INTERNAL_TOKEN"] == "risk-token"
    platform = services["platform"]["environment"]
    assert (platform["PLATFORM_CARD_AGENT_TOKEN"], platform["PLATFORM_RISK_MAPPER_TOKEN"]) == ("card-token", "risk-token")
    holders = [name for name, svc in services.items()
               if any(v in ("card-token", "risk-token") for v in (svc.get("environment") or {}).values())]
    assert sorted(holders) == ["control-objectives", "platform", "qualification-agents"]


HOSTED_CATALOGUE = "https://sandboxconfigurator.aifactory.lu/catalogue"
HOSTED_CATALOGUE_API = "https://sandboxconfigurator.aifactory.lu/api/api"
HOSTED_ORIGIN = "https://sandboxconfigurator.aifactory.lu"


def test_controls_fetches_packages_from_the_hosted_catalogue(compose):
    """The catalogue is the hosted one only (the user's decision of 2026-09-27): the launcher and
    the engine open it, and controls fetch a control's package from its API server-side
    (GET {CATALOGUE_URL}/control/{slug}/export); only that origin's install pages are trusted."""
    q, cfg = compose
    env = cfg["services"]["controls-web"].get("environment") or {}
    assert env.get("CATALOGUE_URL") == HOSTED_CATALOGUE_API
    assert env.get("CATALOGUE_ORIGIN") == HOSTED_ORIGIN
    webapp = cfg["services"]["aisc-webapp"].get("environment") or {}
    assert webapp.get("APP_CATALOG_URL") == HOSTED_CATALOGUE
    launcher = (ROOT / "homepage" / "project.html").read_text()
    assert f'id="catalogue-card" data-engine="http://localhost/" href="{HOSTED_CATALOGUE}"' in launcher


def test_no_local_catalogue_only_its_package_index(compose):
    """No catalogue runs in the stack: no backend, frontend, migration or Caddy site for it, and no
    host port. The package index (devpi) stays: tests are installed from it."""
    q, cfg = compose
    services = cfg["services"]
    for gone in ("catalogue-backend", "catalogue-frontend", "catalogue-migrate"):
        assert gone not in services, f"{gone} is still in the stack"
    assert "devpi" in services and "plugin-publisher" in services
    caddyfile = (ROOT / "Caddyfile").read_text()
    assert "catalogue-backend" not in caddyfile and "catalogue-frontend" not in caddyfile
    ports = [str(p) for p in (services["caddy"].get("ports") or [])]
    assert not any("8007" in p for p in ports), f"caddy still publishes the catalogue listener: {ports}"


def test_the_runtime_env_points_at_the_hosted_catalogue():
    """scripts/secrets.sh builds env.runtime, what the stack runs on, from env.plugin_downloader:
    that file must name the hosted catalogue too, and no local catalogue port."""
    base = re.search(r"^cat (\S+) \"\$OUT\"", (ROOT / "scripts" / "secrets.sh").read_text(), re.M).group(1)
    env = dict(l.split("=", 1) for l in (ROOT / base).read_text().splitlines()
               if "=" in l and not l.lstrip().startswith("#"))
    env = {k.strip(): v.strip() for k, v in env.items()}
    assert env.get("CATALOGUE_EXTERNAL_URL") == HOSTED_CATALOGUE, base
    assert env.get("CATALOGUE_API_URL") == HOSTED_CATALOGUE_API, base
    assert env.get("CATALOGUE_ORIGIN") == HOSTED_ORIGIN, base
    assert "CATALOGUE_PORT_EXTERNAL" not in env, base


def test_the_report_renderer_has_every_build_context_its_dockerfile_copies_from(compose):
    """The renderer's Dockerfile (aisc-report-generator) copies from five named contexts; compose
    must give all five, or `up --build` fails on a fresh machine (it did on 2026-09-27: promptfoo)."""
    q, cfg = compose
    contexts = (cfg["services"]["report-renderer"].get("build") or {}).get("additional_contexts") or {}
    assert set(contexts) >= {"interface", "mlareject", "langbite", "strongreject", "promptfoo"}, sorted(contexts)


def test_the_plugin_downloader_fills_what_the_publisher_publishes(tmp_path):
    """With docker-compose.plugin_downloader.yml (the full run), the downloader clones the default
    plugins into ./def_plugins, the folder plugin-publisher builds and uploads to the index, and the
    publisher waits for it: on a fresh clone def_plugins holds only its README (2026-09-27: the
    publisher found nothing to upload, so no test could be installed)."""
    files = FILES + ["docker-compose.plugin_downloader.yml"]
    args, required = [], set()
    for f in files:
        shutil.copy(ROOT / f, tmp_path / f)
        args += ["-f", str(tmp_path / f)]
        required |= set(re.findall(r"\$\{([A-Z0-9_]+):\?", (ROOT / f).read_text()))
    env = {**os.environ, **{k: "dummy" for k in required}}
    j = subprocess.run(["docker", "compose", "-p", "aisc-t-config", "--project-directory", str(ROOT),
                        "--env-file", str(ROOT / "env.plugin_downloader"), *args, "config", "--format", "json"],
                       env=env, capture_output=True, text=True)
    assert j.returncode == 0, j.stderr[-2000:]
    services = json.loads(j.stdout)["services"]
    targets = [v["source"] for v in services["plugin-downloader"]["volumes"] if v["target"] == "/downloads"]
    sources = [v["source"] for v in services["plugin-publisher"]["volumes"] if v["target"] == "/src"]
    assert targets == sources == [str(ROOT / "def_plugins")], (targets, sources)
    wait = services["plugin-publisher"].get("depends_on", {}).get("plugin-downloader", {})
    assert wait.get("condition") == "service_completed_successfully"


def test_keycloak_may_read_the_realm_secrets_sh_renders():
    """scripts/secrets.sh writes the rendered realm (client secrets) mode 600, and Keycloak runs as
    uid 1000: without a read grant for that uid it fails with Permission denied at import."""
    text = (ROOT / "scripts" / "secrets.sh").read_text()
    assert re.search(r"setfacl -m u:1000:r\S* \"?\$RENDERED\"?", text), "no read grant for Keycloak's uid"


def test_every_variable_compose_takes_without_a_default_is_in_the_runtime_env():
    """A ${VAR} with no default in the compose files becomes an empty string when the env file lacks
    it, which a strict parser refuses (2026-09-27: MODEL_LISTING_SSL_VERIFY='' stopped the engine's
    migration, 'Not a valid boolean'). env.runtime is env.plugin_downloader plus the secrets."""
    bare = set()
    for f in FILES + ["docker-compose.plugin_downloader.yml"]:
        # $${VAR} is escaped: the container's shell expands it, not compose
        bare |= set(re.findall(r"(?<!\$)\$\{([A-Z0-9_]+)\}", (ROOT / f).read_text()))
    env = {l.split("=", 1)[0].strip() for l in (ROOT / "env.plugin_downloader").read_text().splitlines()
           if "=" in l and not l.lstrip().startswith("#")}
    secrets = set(re.findall(r"^\s*(?:echo\s+\"?)?([A-Z0-9_]+)=", (ROOT / "scripts" / "secrets.sh").read_text(), re.M))
    assert sorted(bare - env - secrets) == []


def test_the_dashboard_healthcheck_asks_where_superset_listens(compose):
    """Superset listens only on SUPERSET_BIND_ADDRESS (the Docker host address), so the image's own
    check on localhost always failed and a working dashboard showed as unhealthy."""
    q, cfg = compose
    svc = cfg["services"]["dashboard"]
    test = " ".join(svc.get("healthcheck", {}).get("test") or [])
    assert "$${SUPERSET_BIND_ADDRESS}" in test or "${SUPERSET_BIND_ADDRESS}" in test, test
    assert "localhost" not in test, test


def test_the_eval_healthchecks_ask_the_right_node(compose):
    """The worker's image check pinged "celery@$$HOSTNAME", which in a Dockerfile is the shell's
    pid followed by the word HOSTNAME, and flower's pinged a worker named after flower's own
    container: both were unhealthy while working. The worker pings itself by its real hostname,
    with time to answer; flower answers its own /healthcheck."""
    q, cfg = compose
    worker = cfg["services"]["aisc-eval-worker"].get("healthcheck") or {}
    flower = cfg["services"]["aisc-eval-flower"].get("healthcheck") or {}
    wtest = " ".join(worker.get("test") or [])
    assert ("celery@${HOSTNAME}" in wtest or "celery@$${HOSTNAME}" in wtest) and "-t " in wtest, wtest
    assert "/healthcheck" in " ".join(flower.get("test") or []), flower


# ── Engine deployment modes (pipeline 2026-09-27, task 9: the Configurator wires the mode
# and the platform list) ──────────────────────────────────────────────────────────────────

def test_the_engine_runs_in_configurator_mode(compose):
    """Ruling: the engine (backend, backend-migrate, eval worker, eval flower) is told it runs
    inside the Configurator; the webapp gets the matching APP_DEPLOYMENT."""
    q, cfg = compose
    for name in ("aisc-backend", "aisc-backend-migrate", "aisc-eval-worker", "aisc-eval-flower"):
        assert (cfg["services"][name].get("environment") or {}).get("AISC_DEPLOYMENT") == "configurator", name
    assert cfg["services"]["aisc-webapp"]["environment"].get("APP_DEPLOYMENT") == "configurator"


def test_the_engine_site_serves_the_callers_platform_projects_behind_the_gateway():
    """Ruling 3: on the engine's own site (not the launcher's), GET /platform/api/projects is
    protected then proxied to platform:8000, and it is placed before the catch-all handlers of
    that site so it wins. GET only: no other method is routed to the platform this way."""
    text = (ROOT / "Caddyfile").read_text()
    block = text[text.index("{$CADDY_DOMAIN}:{$CADDY_PORT}"):text.index("{$CADDY_DOMAIN}:{$HOMEPAGE_PORT}")]
    assert "/platform/api/projects" in block and "reverse_proxy platform:8000" in block

    matcher = re.search(r"@platformProjects\s*\{([^}]*)\}", block)
    assert matcher, "no @platformProjects matcher on the engine's site"
    assert re.search(r"\bmethod\s+GET\b", matcher.group(1)), matcher.group(1)
    assert "/platform/api/projects" in matcher.group(1)

    handle_start = block.index("handle @platformProjects")
    route = block[handle_start:]
    assert route.index("import protect") < route.index("reverse_proxy platform:8000")

    # It wins over the catch-all: it appears before every plain `handle {` of that site.
    handle_platform = block.index("handle @platformProjects")
    for m in re.finditer(r"\n  handle \{", block):
        assert handle_platform < m.start(), "the platform route must come before the catch-all"


def test_the_standalone_compose_names_no_configurator_setting():
    """Ruling 4: the standalone compose never turns the Configurator on, never carries the
    per-request project header, and never talks to the platform service."""
    text = (ROOT / "docker-compose.engine-standalone.yml").read_text()
    assert "AISC_DEPLOYMENT: configurator" not in text
    assert "X-AISC-Project" not in text and "platform:8000" not in text


def test_the_migrations_run_through_the_one_shot_not_the_long_running_service():
    """Rulings 13/21: in the Configurator, the engine's schema is migrated by the compose
    one-shot aisc-backend-migrate (migrate_projects, one database per project), never by a
    plain `manage.py migrate` on the long-running aisc-backend service."""
    text = (ROOT / "docker-compose.development.yml").read_text()
    backend_start = text.index("\n  aisc-backend:\n")
    backend_migrate_start = text.index("\n  aisc-backend-migrate:\n")
    backend_block = text[backend_start:backend_migrate_start]
    assert "manage.py migrate " not in backend_block and not backend_block.rstrip().endswith("manage.py migrate")
    assert "migrate_projects" not in backend_block

    next_service = re.search(r"\n  [a-zA-Z0-9_-]+:\n", text[backend_migrate_start + 1:])
    migrate_block = text[backend_migrate_start:backend_migrate_start + 1 + next_service.start()] \
        if next_service else text[backend_migrate_start:]
    assert "migrate_projects" in migrate_block


def test_the_webapp_gets_the_launcher_url(compose):
    """Ruling 31: APP_LAUNCHER_URL must be set on aisc-webapp (where the project was chosen and
    where the other five steps are), defaulting to the launcher's own external URL."""
    q, cfg = compose
    value = cfg["services"]["aisc-webapp"]["environment"].get("APP_LAUNCHER_URL")
    assert value, "APP_LAUNCHER_URL is not set on aisc-webapp"
