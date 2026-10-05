"""Compose file rules, and what the README must say about them. Read-only: the compose files are
copied to a scratch directory and resolved with `docker compose config`; nothing is started, stopped
or built."""

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
    """`docker compose -f <copy> config -q` passes."""
    q, cfg = compose
    assert q.returncode == 0, q.stderr[-2000:]


def test_s6a_qualification_agents_service(compose):
    """Service qualification-agents builds services/agents, on network backend, with
    LLM_SERVICE_URL=http://qualification-llm:4000."""
    q, cfg = compose
    svc = cfg["services"].get("qualification-agents")
    assert svc, "no service qualification-agents"
    ctx = svc["build"]["context"] if isinstance(svc.get("build"), dict) else svc.get("build", "")
    assert str(ctx).rstrip("/").endswith("apps/qualification/services/agents")
    assert "backend" in (svc.get("networks") or {})
    assert (svc.get("environment") or {}).get("LLM_SERVICE_URL") == "http://qualification-llm:4000"


def test_s6a_qualification_web_reaches_the_agents(compose):
    """qualification-web gets AGENT_SERVICE_URL on the port service.py is served on."""
    q, cfg = compose
    dockerfile = (ROOT / "apps/qualification/services/agents/Dockerfile").read_text()
    port = re.search(r'"--port", "(\d+)"', dockerfile).group(1)
    value = (cfg["services"]["qualification-web"].get("environment") or {}).get("AGENT_SERVICE_URL")
    assert value == f"http://qualification-agents:{port}"


def test_wp2_aisc_backend_has_no_platform_url(compose):
    """aisc-backend has no PLATFORM_URL."""
    q, cfg = compose
    names = set(cfg["services"]["aisc-backend"].get("environment") or {})
    assert "PLATFORM_URL" not in names


# LLM keys. A secret given as `${NAME:?...}` is in the fixture's `required` set and so resolves to
# "dummy": that value proves the `:?` form without reading env.secrets.


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
    neither can resolve the other's key."""
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


def test_controls_gets_packages_from_the_platform_and_trusts_the_catalogue_pages(compose):
    """A control's package comes from the platform, which reads the project's own catalogue (plan
    2026-10-04 D2): the platform holds the hosted catalogue's address and bridge token, controls neither.
    Controls' install API trusts the hosted catalogue's pages and the launcher's, where the stack serves
    the catalogue's pages."""
    q, cfg = compose
    env = cfg["services"]["controls-web"].get("environment") or {}
    assert "CATALOGUE_URL" not in env and "CATALOGUE_TOKEN" not in env
    assert env.get("PLATFORM_URL") == "http://platform:8000"
    assert env.get("CATALOGUE_ORIGIN") == HOSTED_ORIGIN
    assert env.get("LAUNCHER_URL") == "http://localhost:8100/"
    platform = cfg["services"]["platform"].get("environment") or {}
    assert platform.get("CATALOGUE_URL") == HOSTED_CATALOGUE_API
    assert "CATALOGUE_TOKEN" in platform
    webapp = cfg["services"]["aisc-webapp"].get("environment") or {}
    assert webapp.get("APP_CATALOG_URL") == HOSTED_CATALOGUE   # the engine's own button, untouched


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
    """The renderer's Dockerfile (apps/report-generator) copies from named contexts; compose must give
    each one, or `up --build` fails on a fresh machine. The only one is the report plugin interface
    (test_report_submodules.py)."""
    q, cfg = compose
    contexts = (cfg["services"]["report-renderer"].get("build") or {}).get("additional_contexts") or {}
    assert set(contexts) == {"interface"}, sorted(contexts)


def test_the_plugin_downloader_fills_what_the_publisher_publishes(tmp_path):
    """With docker-compose.plugin_downloader.yml (the full run), the downloader clones the default
    plugins into ./def_plugins, the folder plugin-publisher builds and uploads to the index, and the
    publisher waits for it: on a fresh clone def_plugins holds only its README, and without the wait
    the publisher finds nothing to upload, so no test can be installed."""
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


#: every plugin repo of github.com/lux-ai-factory (aisc-plugin-builder, -integrator, -interface and -manager
#: are the plugin tooling, not plugins)
PLUGIN_REPOS = {f"aisc-plugin-{n}" for n in (
    "agentdojo", "agentseal", "counterfactual", "data-evaluation", "evasion", "example", "explitest",
    "fairness", "langbite", "llm-eval", "luxeval", "performance", "promptfoo", "ragas", "strongreject",
    "uncertainty")}


def test_the_plugin_downloader_clones_every_lux_ai_factory_plugin():
    """The stack's index holds what the downloader clones, and the engine installs only from that
    index: a plugin left out of the list can't be installed in any project."""
    text = (ROOT / "docker-compose.plugin_downloader.yml").read_text()
    listed = set(re.findall(r"^\s+(aisc-plugin-[a-z0-9-]+)\s*\\?$", text, flags=re.M))
    assert listed == PLUGIN_REPOS, (sorted(PLUGIN_REPOS - listed), sorted(listed - PLUGIN_REPOS))


def test_the_plugin_publisher_says_why_a_plugin_did_not_build():
    """A plugin that fails to build is skipped; its build output must reach the log, or nobody can
    tell why the plugin is missing from the index."""
    text = (ROOT / "docker-compose.development.yml").read_text()
    command = text.split("container_name: plugin-publisher", 1)[1].split("depends_on:", 1)[0]
    assert "could not build" in command
    assert "tail" in command.split("could not build", 1)[1].split("continue", 1)[0], command


def test_keycloak_may_read_the_realm_secrets_sh_renders():
    """scripts/secrets.sh writes the rendered realm (client secrets) mode 600, and Keycloak runs as
    uid 1000: without a read grant for that uid it fails with Permission denied at import."""
    text = (ROOT / "scripts" / "secrets.sh").read_text()
    assert re.search(r"setfacl -m u:1000:r\S* \"?\$RENDERED\"?", text), "no read grant for Keycloak's uid"


def test_every_variable_compose_takes_without_a_default_is_in_the_runtime_env():
    """A ${VAR} with no default in the compose files becomes an empty string when the env file lacks
    it, which a strict parser refuses (MODEL_LISTING_SSL_VERIFY='' stops the engine's migration with
    'Not a valid boolean'). env.runtime is env.plugin_downloader plus the secrets."""
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
    check on localhost always fails and a working dashboard shows as unhealthy."""
    q, cfg = compose
    svc = cfg["services"]["dashboard"]
    test = " ".join(svc.get("healthcheck", {}).get("test") or [])
    assert "$${SUPERSET_BIND_ADDRESS}" in test or "${SUPERSET_BIND_ADDRESS}" in test, test
    assert "localhost" not in test, test


def test_the_eval_healthchecks_ask_the_right_node(compose):
    """The worker's image check pings "celery@$$HOSTNAME", which in a Dockerfile is the shell's
    pid followed by the word HOSTNAME, and flower's pings a worker named after flower's own
    container: both show unhealthy while working. So the worker pings itself by its real hostname,
    with time to answer, and flower answers its own /healthcheck."""
    q, cfg = compose
    worker = cfg["services"]["aisc-eval-worker"].get("healthcheck") or {}
    flower = cfg["services"]["aisc-eval-flower"].get("healthcheck") or {}
    wtest = " ".join(worker.get("test") or [])
    assert ("celery@${HOSTNAME}" in wtest or "celery@$${HOSTNAME}" in wtest) and "-t " in wtest, wtest
    assert "/healthcheck" in " ".join(flower.get("test") or []), flower


# Engine deployment modes: the Configurator sets the mode and serves the engine the platform's
# project list.

def test_the_engine_runs_in_configurator_mode(compose):
    """The engine (backend, backend-migrate, eval worker, eval flower) is told it runs
    inside the Configurator; the webapp gets the matching APP_DEPLOYMENT."""
    q, cfg = compose
    for name in ("aisc-backend", "aisc-backend-migrate", "aisc-eval-worker", "aisc-eval-flower"):
        assert (cfg["services"][name].get("environment") or {}).get("AISC_DEPLOYMENT") == "configurator", name
    assert cfg["services"]["aisc-webapp"]["environment"].get("APP_DEPLOYMENT") == "configurator"


def test_the_engine_site_serves_the_callers_platform_projects_behind_the_gateway():
    """On the engine's own site (not the launcher's), GET /platform/api/projects is
    protected then proxied to platform:8000, and it is placed before the catch-all handlers of
    that site so it wins. GET only: no other method is routed to the platform this way."""
    text = (ROOT / "Caddyfile").read_text()
    block = text[text.index("{$CADDY_DOMAIN}:{$CADDY_PORT}"):text.index("{$CADDY_DOMAIN}:{$HOMEPAGE_PORT}")]
    assert "/platform/api/projects" in block and "reverse_proxy platform:8000" in block

    matcher = re.search(r"@platformProjects\s*\{([^}]*)\}", block)
    assert matcher, "no @platformProjects matcher on the engine's site"
    assert re.search(r"\bmethod\s+GET\b", matcher.group(1)), matcher.group(1)
    assert "/platform/api/projects" in matcher.group(1)
    # the target is a constant, and nothing strips a /platform prefix onto another path
    assert re.search(r"^\s*rewrite \* /projects\s*$", block, re.M), "no `rewrite * /projects`"
    assert "handle_path /platform" not in text

    handle_start = block.index("handle @platformProjects")
    route = block[handle_start:]
    assert route.index("import protect") < route.index("reverse_proxy platform:8000")

    # It wins over the catch-all: it appears before every plain `handle {` of that site.
    handle_platform = block.index("handle @platformProjects")
    for m in re.finditer(r"\n  handle \{", block):
        assert handle_platform < m.start(), "the platform route must come before the catch-all"


def test_the_standalone_compose_names_no_configurator_setting():
    """The standalone compose never turns the Configurator on, never carries the
    per-request project header, and never talks to the platform service."""
    text = (ROOT / "docker-compose.engine-standalone.yml").read_text()
    assert "AISC_DEPLOYMENT: configurator" not in text
    assert "X-AISC-Project" not in text and "platform:8000" not in text


def test_the_migrations_run_through_the_one_shot_not_the_long_running_service():
    """In the Configurator, the engine's schema is migrated by the compose
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
    """APP_LAUNCHER_URL must be set on aisc-webapp (where the project was chosen and
    where the other five steps are), defaulting to the launcher's own external URL."""
    q, cfg = compose
    value = cfg["services"]["aisc-webapp"]["environment"].get("APP_LAUNCHER_URL")
    assert value, "APP_LAUNCHER_URL is not set on aisc-webapp"


# Where the engine installs from: the stack's own devpi, which plugin-publisher fills from
# def_plugins/ with exactly the packages and versions the hosted catalogue names. The online index
# at 10.50.3.47 lacks most of them, so nothing may point there. The catalogue sends a package name
# and version, and any index holding them works.

LOCAL_INDEX = "http://devpi:3141"
ONLINE_HOST = "10.50.3.47"


def _runtime_env():
    base = re.search(r"^cat (\S+) \"\$OUT\"", (ROOT / "scripts" / "secrets.sh").read_text(), re.M).group(1)
    env = dict(l.split("=", 1) for l in (ROOT / base).read_text().splitlines()
               if "=" in l and not l.lstrip().startswith("#"))
    return base, {k.strip(): v.strip() for k, v in env.items()}


def test_the_runtime_env_installs_from_the_stacks_own_index():
    """env.runtime (built from env.plugin_downloader) names the local devpi as the registry:
    PACKAGE_REGISTRY_URL alone decides where the engine installs from.
    CATALOGUE_TRUSTED_INDEXES has no consumer; it is kept, with a comment saying it is not enforced."""
    base, env = _runtime_env()
    assert env.get("PACKAGE_REGISTRY_URL") == LOCAL_INDEX, base
    assert env.get("PACKAGE_REGISTRY_INDEX") == "root/public", base
    for f in ("env.plugin_downloader", "env.development"):
        text = (ROOT / f).read_text()
        assert ONLINE_HOST not in text, f
        before = text[:text.index("CATALOGUE_TRUSTED_INDEXES=")].splitlines()[-1]
        assert "not enforced by the engine; PACKAGE_REGISTRY_URL decides where installs come from" in before, f


def test_the_engine_installs_from_the_index_the_publisher_fills(compose):
    """The engine (backend, migrate, eval worker) installs from the very index plugin-publisher
    uploads def_plugins/ to, so every package the catalogue names can be installed."""
    q, cfg = compose
    twine = (cfg["services"]["plugin-publisher"].get("environment") or {}).get("TWINE_REPOSITORY_URL", "")
    assert twine.startswith(LOCAL_INDEX + "/"), twine
    for name in ("aisc-backend", "aisc-backend-migrate", "aisc-eval-worker"):
        env = cfg["services"][name].get("environment") or {}
        url, index = env.get("PACKAGE_REGISTRY_URL", ""), env.get("PACKAGE_REGISTRY_INDEX", "")
        assert url.rstrip("/") == LOCAL_INDEX and index, (name, url, index)
        assert twine.rstrip("/") == f"{LOCAL_INDEX}/{index}", (name, twine, index)


def test_postgres_is_15(compose):
    """The backend requires PostgreSQL 15; moving from 14 needs fresh volumes, there is no data migration."""
    q, cfg = compose
    image = cfg["services"]["postgres"]["image"]
    assert re.match(r"postgres:15(\D|$)", image), image


def test_every_compose_file_runs_postgres_15():
    """The backend does not support postgres:14, so every compose file that runs a postgres image,
    staging and the plain infra file included, runs 15."""
    import yaml
    found = {}
    for path in sorted(ROOT.glob("docker-compose*.yml")):
        for name, svc in (yaml.safe_load(path.read_text()).get("services") or {}).items():
            image = str((svc or {}).get("image") or "")
            if image.startswith("postgres:"):
                found[f"{path.name}:{name}"] = image
    assert "docker-compose-infra.staging.yml:postgres" in found and "docker-compose-infra.yml:postgres" in found, found
    assert {k: v for k, v in found.items() if not re.match(r"postgres:15(\D|$)", v)} == {}


def test_the_readme_says_staging_needs_fresh_volumes_too():
    readme = (ROOT / "docs" / "guide.md").read_text()
    section = readme.split("### PostgreSQL 15", 1)[1].split("\n## ", 1)[0]
    assert "staging" in section and "fresh volumes" in section, section


def test_the_eval_worker_does_not_log_at_debug(compose):
    """At debug the worker prints each message, run ticket included."""
    q, cfg = compose
    command = cfg["services"]["aisc-eval-worker"]["command"]
    command = " ".join(command) if isinstance(command, list) else command
    assert "--loglevel=info" in command and "debug" not in command, command



# the standalone compose

SECRET_NAME = re.compile(r"PASSWORD|SECRET|KEY|TOKEN")
# an empty default is no shipped secret: the registry is a public index read without login
EMPTY_ALLOWED = {"PACKAGE_REGISTRY_USER", "PACKAGE_REGISTRY_PASSWORD"}


def _standalone():
    import yaml
    text = (ROOT / "docker-compose.engine-standalone.yml").read_text()
    return text, yaml.safe_load(text)["services"]


def test_the_standalone_compose_ships_no_default_secret():
    """Port 8000 is published with no gateway: a default INTERNAL_API_KEY would let anyone call
    /api/v1/internal/*. Every PASSWORD/SECRET/KEY/TOKEN variable is required (`${VAR:?...}`)."""
    text, _ = _standalone()
    refs = re.findall(r"\$\{([A-Z0-9_]+)(:?[-?])?([^}]*)\}", text)
    bad = [f"${{{v}{op}{rest}}}" for v, op, rest in refs if SECRET_NAME.search(v)
           and op != ":?" and not (v in EMPTY_ALLOWED and op == ":-" and rest == "")]
    assert bad == [], bad
    for v in ("DB_PASSWORD", "S3_PASSWORD", "RABBITMQ_PASSWORD", "DJANGO_SECRET_KEY", "INTERNAL_API_KEY"):
        assert f"${{{v}:?" in text, v
    readme = (ROOT / "docs" / "guide.md").read_text()
    assert "--env-file" in readme and "INTERNAL_API_KEY" in readme


def test_the_standalone_registry_user_is_empty_by_default():
    """The backend's settings turn an empty password into None; a user without one makes
    DevpiClient refuse to start the backend. The user is empty unless given."""
    text, _ = _standalone()
    assert "${PACKAGE_REGISTRY_USER:-root}" not in text
    for f in ("env.plugin_downloader", "env.development"):
        line = [l for l in (ROOT / f).read_text().splitlines() if l.replace(" ", "").startswith("PACKAGE_REGISTRY_USER=")]
        assert line and line[0].split("=", 1)[1].strip() == "", f


def test_the_standalone_compose_uses_seans_settings_names_pg15_and_the_mounted_plugins():
    """The backend's settings read BACKEND_CRSF_TRUSTED_ORIGINS (that spelling); postgres 15;
    PLUGIN_PATH is where the service mounts the plugins."""
    text, services = _standalone()
    backend = services["aisc-backend"]["environment"]
    assert "BACKEND_CRSF_TRUSTED_ORIGINS" in backend and "BACKEND_CSRF_TRUSTED_ORIGINS" not in backend
    assert re.match(r"postgres:15(\D|$)", services["postgres"]["image"]), services["postgres"]["image"]
    for name in ("aisc-backend", "aisc-eval-worker"):
        svc = services[name]
        targets = [m.group(1) for v in svc.get("volumes") or []
                   if (m := re.search(r":(/[^:]+)(:[a-z,]+)?$", str(v)))]
        assert svc["environment"]["PLUGIN_PATH"] == "/app/plugins" and "/app/plugins" in targets, name
    assert "\u2014" not in text, "em dash in the standalone compose"
    assert "one project, one database" not in text


def test_the_readme_says_where_tests_install_from_and_what_pg15_needs():
    """README: configurator installs from the stack's own devpi, which plugin-publisher fills;
    standalone is one database holding all projects; PG15 needs fresh volumes."""
    readme = (ROOT / "docs" / "guide.md").read_text()
    assert ONLINE_HOST not in readme
    assert "the engine does not install from it" not in readme
    assert "installed into the engine from the stack's own package index" in readme
    assert "one project, one database" not in readme
    assert "one database holding all projects" in readme
    assert "fresh volumes" in readme and "PostgreSQL 15" in readme


def test_the_plugin_publisher_also_publishes_the_shared_plugin_interface():
    """A plugin's run installs its dependencies from PyPI and the stack's index; uv takes a package from
    the first index that has it, devpi first. With the shared plugin-interface on devpi a run gets this
    stack's library (its connector, the declarations), not PyPI's release of the same name."""
    text = (ROOT / "docker-compose.development.yml").read_text()
    block = text.split("  plugin-publisher:", 1)[1].split("\n  # ", 1)[0]
    assert re.search(r"- \./shared/plugin-interface:/interface:ro", block), block
    command = block.split("command:", 1)[1]
    assert "/interface" in command and "python -m build" in command, command


def test_every_service_that_uses_postgres_waits_until_it_is_ready_and_set_up():
    """postgres-setup waits for pg_isready and makes the databases (init/, superset-db.sql among them). A
    service that only waits for the postgres container to start races it: dashboard-migrate lost that race
    on a fresh clone (connection refused) and the whole `up` failed."""
    args, required = [], set()
    files = FILES + ["docker-compose.plugin_downloader.yml"]
    for f in files:
        args += ["-f", str(ROOT / f)]
        required |= set(re.findall(r"\$\{([A-Z0-9_]+):\?", (ROOT / f).read_text()))
    env = {**os.environ, **{k: "dummy" for k in required}}
    j = subprocess.run(["docker", "compose", "-p", "aisc-t-config", "--project-directory", str(ROOT),
                        "--env-file", str(ROOT / "env.plugin_downloader"), *args, "config", "--format", "json"],
                       env=env, capture_output=True, text=True)
    assert j.returncode == 0, j.stderr[-2000:]
    services = json.loads(j.stdout)["services"]

    def waits_for_setup(name, seen=()):
        deps = services[name].get("depends_on") or {}
        if deps.get("postgres-setup", {}).get("condition") == "service_completed_successfully":
            return True
        return any(waits_for_setup(d, seen + (name,)) for d, how in deps.items()
                   if d not in seen and d in services and how.get("condition") in
                   ("service_completed_successfully", "service_healthy"))

    users = [n for n, s in services.items() if n not in ("postgres", "postgres-setup")
             and "@postgres:5432" in json.dumps(s.get("environment") or {})]
    assert users, "no service found that uses postgres"
    racing = sorted(n for n in users if not waits_for_setup(n))
    assert not racing, f"these start without waiting for postgres-setup: {racing}"
