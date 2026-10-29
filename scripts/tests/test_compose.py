"""Compose file rules, and what the README must say about them. Read-only: the compose files are
copied to a scratch directory and resolved with `docker compose config`; nothing is started, stopped
or built."""

import json
import re

import pytest

import compose_cfg
from compose_cfg import FILES
from conftest import ROOT, aisc_py


def _config(d, *profiles):
    """(the `config -q` result, the resolved config or None), as compose_cfg resolves them."""
    q = compose_cfg.run(d, *profiles, quiet=True)
    j = compose_cfg.run(d, *profiles)
    return q, (json.loads(j.stdout) if j.returncode == 0 else None)


@pytest.fixture(scope="module")
def compose(tmp_path_factory):
    """The config `up` resolves: no profile."""
    return _config(tmp_path_factory.mktemp("compose"))


@pytest.fixture(scope="module")
def compose_inspect(tmp_path_factory):
    """With the `inspect` profile, which the developer tools (pgAdmin, the diagrams, Flower) run under."""
    return _config(tmp_path_factory.mktemp("compose-inspect"), "inspect")


def test_s6a_compose_config_is_valid(compose):
    """`docker compose -f <copy> config -q` passes."""
    q, cfg = compose
    assert q.returncode == 0, q.stderr[-2000:]


def test_s6a_qualification_agents_service(compose):
    """Service qualification-agents builds services/agents, on network backend."""
    q, cfg = compose
    svc = cfg["services"].get("qualification-agents")
    assert svc, "no service qualification-agents"
    ctx = svc["build"]["context"] if isinstance(svc.get("build"), dict) else svc.get("build", "")
    assert str(ctx).rstrip("/").endswith("apps/qualification/services/agents")
    assert "backend" in (svc.get("networks") or {})


def test_s6a_qualification_web_reaches_the_agents(compose):
    """qualification-web gets AGENT_SERVICE_URL on the port service.py is served on."""
    q, cfg = compose
    dockerfile = (ROOT / "apps/qualification/services/agents/Dockerfile.stack").read_text()   # what compose builds
    port = re.search(r'"--port", "(\d+)"', dockerfile).group(1)
    value = (cfg["services"]["qualification-web"].get("environment") or {}).get("AGENT_SERVICE_URL")
    assert value == f"http://qualification-agents:{port}"


def test_aisc_backend_reaches_the_platform_with_the_engine_token_only(compose):
    """aisc-backend asks the platform one thing, whether a card target has a connection, with its own
    token: it imports plugin code, so it holds no ledger or connections token."""
    q, cfg = compose
    env = cfg["services"]["aisc-backend"].get("environment") or {}
    assert env.get("PLATFORM_URL") == "http://platform:8000"
    platform_tokens = {n for n in env if n.startswith("PLATFORM_") and n.endswith(("_TOKEN", "_KEY", "_KEYS"))}
    assert platform_tokens == {"PLATFORM_ENGINE_TOKEN"}


# LLM keys. A secret given as `${NAME:?...}` is in the fixture's `required` set and so resolves to
# "dummy": that value proves the `:?` form without reading env.secrets.


def _extra_hosts(svc):
    hosts = svc.get("extra_hosts") or []
    if isinstance(hosts, dict):
        return {f"{k}:{v}" for k, v in hosts.items()}
    return {h.replace("=", ":", 1) for h in hosts}


def test_platform_gets_the_two_secrets_and_the_ollama_default(compose):
    q, cfg = compose
    env = cfg["services"]["platform"].get("environment") or {}
    assert env.get("PLATFORM_SECRETS_KEY") == "dummy", "PLATFORM_SECRETS_KEY is not a required `:?` variable"
    for name in ("PLATFORM_CARD_AGENT_TOKEN", "PLATFORM_RISK_MAPPER_TOKEN"):
        assert env.get(name) == "dummy", f"{name} is not a required `:?` variable"
    assert "PLATFORM_INTERNAL_TOKEN" not in env, "the platform takes one token per system, not a shared one"
    assert env.get("PLATFORM_OLLAMA_BASE_URL") == "http://host.docker.internal:11434"
    assert "host.docker.internal:host-gateway" in _extra_hosts(cfg["services"]["platform"])


def test_the_card_agent_reaches_the_platform_with_the_token(compose):
    q, cfg = compose
    svc = cfg["services"]["qualification-agents"]
    env = svc.get("environment") or {}
    assert env.get("PLATFORM_URL") == "http://platform:8000"
    assert env.get("PLATFORM_INTERNAL_TOKEN") == "dummy"
    assert "host.docker.internal:host-gateway" in _extra_hosts(svc)
    assert "backend" in (svc.get("networks") or {})


def test_the_risk_mapper_gets_the_token(compose):
    q, cfg = compose
    svc = cfg["services"]["control-objectives"]
    env = svc.get("environment") or {}
    assert env.get("PLATFORM_INTERNAL_TOKEN") == "dummy"
    assert env.get("PLATFORM_URL")
    assert "backend" in (svc.get("networks") or {})
    assert "backend" in (cfg["services"]["platform"].get("networks") or {})


def test_the_compose_files_stay_valid_with_the_new_variables(compose):
    q, cfg = compose
    assert q.returncode == 0, q.stderr[-2000:]
    names = {n for s in ("platform", "qualification-agents", "control-objectives")
             for n in (cfg["services"][s].get("environment") or {})}
    assert {"PLATFORM_SECRETS_KEY", "PLATFORM_CARD_AGENT_TOKEN", "PLATFORM_RISK_MAPPER_TOKEN",
            "PLATFORM_INTERNAL_TOKEN", "PLATFORM_OLLAMA_BASE_URL", "PLATFORM_URL"} <= names
    assert not (cfg["services"]["platform"].get("ports")), "the platform must publish no port"


def test_each_agent_gets_the_token_of_its_own_system_only(tmp_path):
    """The card agent holds the card agent's token and the risk mapper the risk mapper's, so
    neither can resolve the other's key."""
    services = compose_cfg.config(tmp_path, env={"PLATFORM_CARD_AGENT_TOKEN": "card-token",
                                                 "PLATFORM_RISK_MAPPER_TOKEN": "risk-token"})["services"]
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
    """A control's package comes from the platform, which reads the project's own catalogue: the
    platform holds the hosted catalogue's address and bridge token, controls neither.
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
    base = aisc_py().TRACKED
    env = dict(line.split("=", 1) for line in (ROOT / base).read_text().splitlines()
               if "=" in line and not line.lstrip().startswith("#"))
    env = {k.strip(): v.strip() for k, v in env.items()}
    assert env.get("CATALOGUE_EXTERNAL_URL") == HOSTED_CATALOGUE, base
    assert env.get("CATALOGUE_API_URL") == HOSTED_CATALOGUE_API, base
    assert env.get("CATALOGUE_ORIGIN") == HOSTED_ORIGIN, base
    assert "CATALOGUE_PORT_EXTERNAL" not in env, base


def _compose_files_start_runs_with():
    """The -f files of scripts/aisc.py's COMPOSE: what start builds and brings up."""
    compose = aisc_py().COMPOSE
    return [compose[i + 1] for i, arg in enumerate(compose) if arg == "-f"]


def test_start_clones_no_plugin():
    """Start fetches no plugin: a plugin is fetched and built when an admin installs it, by the publisher.
    No compose file start runs with defines a service that clones, and the downloader's file is gone."""
    import yaml

    assert not (ROOT / "docker-compose.plugin_downloader.yml").exists()
    files = _compose_files_start_runs_with()
    assert "docker-compose.plugin_downloader.yml" not in files
    for f in files:
        for name, spec in (yaml.safe_load((ROOT / f).read_text()).get("services") or {}).items():
            run = json.dumps([spec.get("command"), spec.get("entrypoint")])
            assert "git clone" not in run and "git -c" not in run, f"{f}:{name} clones at start"


def test_the_publisher_is_a_service_on_the_backend_network_with_a_healthcheck(compose):
    """It waits for the platform's requests: it comes back after a restart, says when it is up, builds
    nothing from def_plugins/ and still publishes the shared plugin interface it is given read-only."""
    q, cfg = compose
    svc = cfg["services"]["plugin-publisher"]
    assert svc.get("restart") == "unless-stopped"
    assert svc.get("healthcheck", {}).get("test"), "no healthcheck"
    assert "/health" in " ".join(svc["healthcheck"]["test"])
    assert "backend" in (svc.get("networks") or {})
    assert svc.get("init") is True, "orphaned build processes would stay as zombies"
    volumes = svc.get("volumes") or []
    assert not [v for v in volumes if "def_plugins" in v["source"]], volumes
    interface = [v for v in volumes if v["target"] == "/interface"]
    assert interface and interface[0]["source"] == str(ROOT / "shared/plugin-interface") \
        and interface[0].get("read_only") is True, volumes
    # the image's own command runs the service: no one-shot shell loop over a folder
    assert not svc.get("command") and not svc.get("entrypoint"), (svc.get("entrypoint"), svc.get("command"))
    assert "working_dir" not in svc
    # Only started, never healthy: a slow machine (Windows, WSL) can take minutes to get devpi
    # healthy, and a healthy condition then fails the whole `up` with "dependency failed to start".
    # The publisher waits for devpi itself, retrying the interface publish in the background.
    assert svc.get("depends_on", {}).get("devpi", {}).get("condition") == "service_started"
    # devpi's healthcheck stays, for information
    assert cfg["services"]["devpi"].get("healthcheck", {}).get("test"), "devpi has no healthcheck"


def test_every_variable_compose_takes_without_a_default_is_in_the_runtime_env():
    """A ${VAR} with no default in the compose files becomes an empty string when the env file lacks
    it, which a strict parser refuses (MODEL_LISTING_SSL_VERIFY='' stops the engine's migration with
    'Not a valid boolean'). env.runtime is env.plugin_downloader plus the secrets."""
    bare = set()
    for f in FILES:
        # $${VAR} is escaped: the container's shell expands it, not compose
        bare |= set(re.findall(r"(?<!\$)\$\{([A-Z0-9_]+)\}", (ROOT / f).read_text()))
    env = {line.split("=", 1)[0].strip() for line in (ROOT / "env.plugin_downloader").read_text().splitlines()
           if "=" in line and not line.lstrip().startswith("#")}
    secrets = {name for name, _ in aisc_py().SECRETS}
    assert sorted(bare - env - secrets) == []


def test_the_dashboard_healthcheck_asks_where_superset_listens(compose):
    """Superset listens on every address of its own container on the compose network (it was on the
    Docker host address while on the host network, see test_no_host_network), so the check asks
    localhost on SUPERSET_PORT."""
    q, cfg = compose
    svc = cfg["services"]["dashboard"]
    test = " ".join(svc.get("healthcheck", {}).get("test") or [])
    assert "localhost:$${SUPERSET_PORT}" in test or "localhost:${SUPERSET_PORT}" in test, test
    assert svc["environment"]["SUPERSET_BIND_ADDRESS"] == "0.0.0.0"


def test_the_eval_healthchecks_ask_the_right_node(compose_inspect):
    """The worker's image check pings "celery@$$HOSTNAME", which in a Dockerfile is the shell's
    pid followed by the word HOSTNAME, and flower's pings a worker named after flower's own
    container: both show unhealthy while working. So the worker pings itself by its real hostname,
    with time to answer, and flower answers its own /healthcheck."""
    q, cfg = compose_inspect
    worker = cfg["services"]["aisc-eval-worker"].get("healthcheck") or {}
    flower = cfg["services"]["aisc-eval-flower"].get("healthcheck") or {}
    wtest = " ".join(worker.get("test") or [])
    assert ("celery@${HOSTNAME}" in wtest or "celery@$${HOSTNAME}" in wtest) and "-t " in wtest, wtest
    assert "/healthcheck" in " ".join(flower.get("test") or []), flower


# Engine deployment modes: the Configurator sets the mode and serves the engine the platform's
# project list.

def test_the_engine_runs_in_configurator_mode(compose_inspect):
    """The engine (backend, backend-migrate, eval worker, eval flower) is told it runs
    inside the Configurator; the webapp gets the matching APP_DEPLOYMENT."""
    q, cfg = compose_inspect
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


# Where the engine installs from: the stack's own devpi, which plugin-publisher fills, a plugin when
# an admin installs it, with exactly the packages and versions the hosted catalogue names. The online index
# at 10.50.3.47 lacks most of them, so nothing may point there. The catalogue sends a package name
# and version, and any index holding them works.

LOCAL_INDEX = "http://devpi:3141"
ONLINE_HOST = "10.50.3.47"


def _runtime_env():
    base = aisc_py().TRACKED
    env = dict(line.split("=", 1) for line in (ROOT / base).read_text().splitlines()
               if "=" in line and not line.lstrip().startswith("#"))
    return base, {k.strip(): v.strip() for k, v in env.items()}


def test_the_runtime_env_installs_from_the_stacks_own_index():
    """env.runtime (built from env.plugin_downloader) names the local devpi as the registry:
    PACKAGE_REGISTRY_URL alone decides where the engine installs from.
    CATALOGUE_TRUSTED_INDEXES has no consumer; it is kept, with a comment saying it is not enforced."""
    base, env = _runtime_env()
    assert env.get("PACKAGE_REGISTRY_URL") == LOCAL_INDEX, base
    assert env.get("PACKAGE_REGISTRY_INDEX") == "root/public", base
    text = (ROOT / "env.plugin_downloader").read_text()
    assert ONLINE_HOST not in text
    before = text[:text.index("CATALOGUE_TRUSTED_INDEXES=")].splitlines()[-1]
    assert "not enforced by the engine; PACKAGE_REGISTRY_URL decides where installs come from" in before


def test_the_engine_installs_from_the_index_the_publisher_fills(compose):
    """The engine (backend, migrate, eval worker) installs from the very index plugin-publisher
    uploads plugins to, so every package the catalogue names can be installed."""
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
    staging included, runs 15."""
    import yaml
    found = {}
    for path in sorted(ROOT.glob("docker-compose*.yml")):
        for name, svc in (yaml.safe_load(path.read_text()).get("services") or {}).items():
            image = str((svc or {}).get("image") or "")
            if image.startswith("postgres:"):
                found[f"{path.name}:{name}"] = image
    assert "docker-compose-infra.staging.yml:postgres" in found, found
    assert {k: v for k, v in found.items() if not re.match(r"postgres:15(\D|$)", v)} == {}


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


def test_the_standalone_compose_publishes_on_loopback_only(tmp_path):
    """The standalone engine has no sign-in; on every interface anyone on the network could
    create projects and run plugins against any URL. Loopback only, and the guide says why."""
    cfg = compose_cfg.config(tmp_path, files=["docker-compose.engine-standalone.yml"], settings_file=None)
    published = [(n, p) for n, svc in cfg["services"].items() for p in svc.get("ports") or []]
    assert published, "the standalone compose publishes nothing at all"
    assert [(n, p) for n, p in published if p.get("host_ip") != "127.0.0.1"] == []
    assert "no sign-in" in (ROOT / "docs" / "guide.md").read_text()


def test_the_standalone_registry_user_is_empty_by_default():
    """The backend's settings turn an empty password into None; a user without one makes
    DevpiClient refuse to start the backend. The user is empty unless given."""
    text, _ = _standalone()
    assert "${PACKAGE_REGISTRY_USER:-root}" not in text
    line = [line for line in (ROOT / "env.plugin_downloader").read_text().splitlines()
            if line.replace(" ", "").startswith("PACKAGE_REGISTRY_USER=")]
    assert line and line[0].split("=", 1)[1].strip() == ""


def test_the_standalone_compose_uses_the_engines_settings_names_pg15_and_the_mounted_plugins():
    """Postgres 15; PLUGIN_PATH is where the service mounts the plugins."""
    text, services = _standalone()
    assert re.match(r"postgres:15(\D|$)", services["postgres"]["image"]), services["postgres"]["image"]
    for name in ("aisc-backend", "aisc-eval-worker"):
        svc = services[name]
        targets = [m.group(1) for v in svc.get("volumes") or []
                   if (m := re.search(r":(/[^:]+)(:[a-z,]+)?$", str(v)))]
        assert svc["environment"]["PLUGIN_PATH"] == "/app/plugins" and "/app/plugins" in targets, name
    assert "\u2014" not in text, "em dash in the standalone compose"
    assert "one project, one database" not in text


def test_the_plugin_publisher_also_publishes_the_shared_plugin_interface(compose):
    """A plugin's run installs its dependencies from PyPI and the stack's index; uv takes a package from
    the first index that has it, devpi first. With the shared plugin-interface on devpi a run gets this
    stack's library (its connector, the declarations), not PyPI's release of the same name. The publisher
    publishes it from /interface (INTERFACE_PATH) at its start."""
    text = (ROOT / "docker-compose.development.yml").read_text()
    block = text.split("  plugin-publisher:", 1)[1].split("\n  # ", 1)[0]
    assert re.search(r"- \./shared/plugin-interface:/interface:ro", block), block
    q, cfg = compose
    env = cfg["services"]["plugin-publisher"].get("environment") or {}
    assert env.get("INTERFACE_PATH", "/interface") == "/interface"


def test_every_service_that_uses_postgres_waits_until_it_is_ready_and_set_up(tmp_path):
    """postgres-setup waits for pg_isready and makes the databases (init/, superset-db.sql among them). A
    service that only waits for the postgres container to start races it: dashboard-migrate lost that race
    on a fresh clone (connection refused) and the whole `up` failed."""
    services = compose_cfg.config(tmp_path)["services"]

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


def test_an_image_is_built_by_one_service_only():
    """Two services that build the same image tag race when compose builds in parallel (compose v5,
    bake): whichever finishes second fails with 'image "...:latest": already exists', at random,
    one day control-objectives, the next the dashboard. One service builds an
    image; the others that run it (a migrate job, the bucket job) only name it, pull_policy never."""
    import yaml

    groups = [["docker-compose-infra.development.yml", "docker-compose.development.yml"]]
    groups += [[p.name] for p in sorted(ROOT.glob("docker-compose*.yml"))]
    for files in groups:
        builders = {}
        for f in files:
            for name, spec in (yaml.safe_load((ROOT / f).read_text()).get("services") or {}).items():
                if spec and spec.get("build") and spec.get("image"):
                    builders.setdefault(spec["image"], []).append(f"{f}:{name}")
        twice = {image: who for image, who in builders.items() if len(who) > 1}
        assert not twice, f"built by more than one service: {twice}"


def test_the_platform_reads_the_local_controls_read_only(compose):
    """Every private catalogue gets the checklists in local_controls/ (local_controls/README.md)."""
    q, cfg = compose
    mounts = [(v.get("source", ""), v.get("target"), v.get("read_only")) for v in cfg["services"]["platform"]["volumes"]]
    assert any(src.endswith("/local_controls") and tgt == "/app/local_controls" and ro for src, tgt, ro in mounts), mounts


def test_the_publisher_reads_local_plugins_read_only(compose):
    """A catalogue install of a plugin of local_plugins/ has the publisher build it from there
    (local_plugins/README.md)."""
    q, cfg = compose
    publisher = cfg["services"]["plugin-publisher"]
    mounts = [(v.get("source", ""), v.get("target"), v.get("read_only")) for v in publisher["volumes"]]
    # under a folder only root (the service) can enter: the builds run as another user and must not read it
    assert any(src.rstrip("/").endswith("/local_plugins") and tgt == "/srv/private/local-plugins" and ro
               for src, tgt, ro in mounts), mounts
    assert publisher["environment"]["LOCAL_PLUGINS_DIR"] == "/srv/private/local-plugins"
    dockerfile = (ROOT / "infra/plugin-publisher/Dockerfile").read_text()
    assert "install -d -m 700 /srv/private" in dockerfile


def test_the_platform_reads_the_adapters_read_only(compose):
    """The protocols adapters add (adapters/README.md): the folder mounted read-only where the platform looks."""
    q, cfg = compose
    platform = cfg["services"]["platform"]
    mounts = [(v.get("source", ""), v.get("target"), v.get("read_only")) for v in platform["volumes"]]
    assert any(src.endswith("/adapters") and tgt == "/app/adapters" and ro for src, tgt, ro in mounts), mounts
    assert platform["environment"]["PLATFORM_ADAPTERS_DIR"] == "/app/adapters"


def test_report_grants_waits_for_the_superset_tables(compose):
    """report-ro-grants.sql skips a Superset table that does not exist yet, and
    dashboard-migrate (superset db upgrade) makes them. On a fresh volume report-grants ran first and
    report_ro got no SELECT on them until the next full start."""
    _, cfg = compose
    dep = cfg["services"]["report-grants"]["depends_on"].get("dashboard-migrate")
    assert dep and dep["condition"] == "service_completed_successfully", dep


def test_the_engine_checks_tls_when_it_lists_a_providers_models(compose):
    """The settings file said the engine checks TLS there and set False, so the engine sent
    the project's provider key over unverified TLS. staging and the standalone engine already say True."""
    _, cfg = compose
    assert cfg["services"]["aisc-backend"]["environment"]["MODEL_LISTING_SSL_VERIFY"] == "True"


GATEWAY_ISSUER = "/realms/aisc"
GATEWAY_JWKS = "/realms/aisc/protocol/openid-connect/certs"


@pytest.mark.parametrize("service", ["qualification-web", "controls-web", "report-composer", "control-objectives"])
def test_every_app_that_cites_the_gateways_request_id_can_verify_its_token(compose, service):
    """An app keeps X-AISC-Request-Id only with a valid gateway token, which it verifies itself
    (gatewayToken.ts in qualification and controls, aisc_identity in the Python services). Without the
    realm's issuer and keys it cites no request, and in enforce mode the platform refuses its events."""
    _, cfg = compose
    env = cfg["services"][service]["environment"]
    assert env.get("AUTH_ENABLED") == "true", service
    assert env.get("KEYCLOAK_ISSUER", "").endswith(GATEWAY_ISSUER), service
    assert env.get("KEYCLOAK_JWKS_URL", "").endswith(GATEWAY_JWKS) and "keycloak:8080" in env["KEYCLOAK_JWKS_URL"], service


def test_the_dashboard_verifies_the_gateways_token(compose):
    """In the dashboard, dashboard-gateway/gateway_identity.py verifies the token (its own names)."""
    _, cfg = compose
    env = cfg["services"]["dashboard"]["environment"]
    assert env["GATEWAY_TOKEN_ISSUER"].endswith(GATEWAY_ISSUER)
    assert env["GATEWAY_JWKS_URL"].endswith(GATEWAY_JWKS)
    assert env["AISC_GATEWAY_CLIENT_ID"] == "aisc-gateway"


def test_no_file_passes_the_engine_a_csrf_origin_list_it_does_not_read():
    """The engine sets no CSRF trusted origins: its API is reached through the gateway with bearer tokens."""
    files = ["docker-compose.development.yml", "docker-compose.staging.yml", "docker-compose.engine-standalone.yml",
             "env.plugin_downloader", "env.staging", "apps/backend/env.development"]
    assert [f for f in files if re.search(r"BACKEND_C[RS]{2}F_TRUSTED_ORIGINS", (ROOT / f).read_text())] == []


# The engine's port and address follow the install's settings (env.local, written by aisc.py start)

MOVED = {"ENGINE_PORT": "8080", "ENGINE_HTTPS_PORT": "8443", "API_URL_EXTERNAL": "http://localhost:8080"}


def _published(service):
    return {(int(p["published"]), int(p["target"])) for p in service.get("ports") or []}


#: the stack as an install served over https starts it, and with the infrastructure published for the host's tools
WITH_HTTPS = [*FILES, "docker-compose.https.yml"]
WITH_ADMIN_PORTS = [*FILES, "docker-compose.admin-ports.yml"]
#: the launcher, the dashboard and the sign-in moved off their usual ports, as aisc.py start moves them
BROWSER_MOVED = {"HOMEPAGE_PORT_EXTERNAL": "8110", "DASHBOARD_PORT_EXTERNAL": "8198", "KEYCLOAK_PORT_EXTERNAL": "8091",
                 "LAUNCHER_EXTERNAL_URL": "http://localhost:8110/", "DASHBOARD_EXTERNAL_URL": "http://localhost:8198",
                 "KEYCLOAK_URL_EXTERNAL": "http://localhost:8091"}


def _host_ports(services):
    """(service, host address, host port) of every published port."""
    return {(name, p.get("host_ip") or "0.0.0.0", int(p["published"]))
            for name, service in services.items() for p in service.get("ports") or []}


def test_only_the_browser_ports_are_published_by_default(tmp_path):
    """A port nobody's browser needs is one more a new install can find taken."""
    services = compose_cfg.config(tmp_path)["services"]
    assert {port for _, _, port in _host_ports(services)} == {80, 8100, 8188, 8081}


def test_the_admin_ports_file_publishes_the_infrastructure_on_loopback(tmp_path):
    services = compose_cfg.config(tmp_path, files=WITH_ADMIN_PORTS)["services"]
    published = _host_ports(services)
    for port in (5432, 6379, 5672, 9000, 3322):
        hosts = {host for _, host, p in published if p == port}
        assert hosts == {"127.0.0.1"}, port


def test_443_only_with_the_https_file(tmp_path):
    (tmp_path / "plain").mkdir()
    (tmp_path / "https").mkdir()
    plain = compose_cfg.config(tmp_path / "plain")["services"]["caddy"]
    assert 443 not in {published for published, _ in _published(plain)}
    https = compose_cfg.config(tmp_path / "https", files=WITH_HTTPS)["services"]["caddy"]
    assert (443, 8005) in _published(https)


def test_every_browser_port_follows_its_variable(tmp_path):
    services = compose_cfg.config(tmp_path, env=BROWSER_MOVED)["services"]
    assert {(8110, 8006), (8198, 8008)} <= _published(services["caddy"])
    keycloak = [(p.get("host_ip"), int(p["published"]), int(p["target"])) for p in services["keycloak"]["ports"]]
    assert keycloak == [("127.0.0.1", 8091, 8080)]


def test_every_issuer_follows_the_sign_in_address(tmp_path):
    services = compose_cfg.config(tmp_path, env=BROWSER_MOVED)["services"]
    issuers = {name: (s.get("environment") or {})["KEYCLOAK_ISSUER"] for name, s in services.items()
               if "KEYCLOAK_ISSUER" in (s.get("environment") or {})}
    assert issuers
    assert {name: i for name, i in issuers.items() if not i.startswith("http://localhost:8091")} == {}
    assert services["keycloak"]["environment"]["KC_HOSTNAME"] == "http://localhost:8091"
    command = services["oauth2-proxy"]["command"]
    for flag in ("--oidc-issuer-url=", "--login-url="):
        value = next(c for c in command if c.startswith(flag))
        assert value.startswith(flag + "http://localhost:8091"), value


def test_every_link_back_to_the_launcher_follows_its_address(tmp_path):
    services = compose_cfg.config(tmp_path, env=BROWSER_MOVED)["services"]
    links = {(name, key): (s.get("environment") or {})[key] for name, s in services.items()
             for key in ("LAUNCHER_URL", "APP_LAUNCHER_URL") if key in (s.get("environment") or {})}
    assert {"dashboard", "aisc-webapp", "controls-web"} <= {name for name, _ in links}
    assert {k: v for k, v in links.items() if v != "http://localhost:8110/"} == {}


def test_the_gateway_whitelists_every_browser_port(tmp_path):
    command = compose_cfg.config(tmp_path, env=BROWSER_MOVED)["services"]["oauth2-proxy"]["command"]
    assert {"--whitelist-domain=localhost:8110", "--whitelist-domain=localhost:8198"} <= set(command)


def test_keycloak_gets_every_address_its_realm_names(tmp_path):
    environment = compose_cfg.config(tmp_path, env=BROWSER_MOVED)["services"]["keycloak"]["environment"]
    assert environment["LAUNCHER_EXTERNAL_URL"] == "http://localhost:8110/"
    assert environment["DASHBOARD_EXTERNAL_URL"] == "http://localhost:8198"


def test_the_engine_ports_follow_the_install_settings(tmp_path):
    (tmp_path / "moved").mkdir()
    (tmp_path / "default").mkdir()
    moved = compose_cfg.config(tmp_path / "moved", env=MOVED, files=WITH_HTTPS)["services"]["caddy"]
    assert {(8080, 8005), (8443, 8005)} <= _published(moved)
    default = compose_cfg.config(tmp_path / "default", files=WITH_HTTPS)["services"]["caddy"]
    assert {(80, 8005), (443, 8005)} <= _published(default)


def test_the_report_composer_accepts_requests_from_the_engine_address(tmp_path):
    services = compose_cfg.config(tmp_path, env=MOVED)["services"]
    assert services["report-composer"]["environment"]["PLATFORM_ORIGIN"] == "http://localhost:8080"


def test_the_gateway_lets_sign_in_return_to_the_engine_port(tmp_path):
    command = compose_cfg.config(tmp_path, env=MOVED)["services"]["oauth2-proxy"]["command"]
    assert "--whitelist-domain=localhost:8080" in command


def test_keycloak_gets_the_engine_address_for_its_realm(tmp_path):
    keycloak = compose_cfg.config(tmp_path, env=MOVED)["services"]["keycloak"]
    assert keycloak["environment"]["API_URL_EXTERNAL"] == "http://localhost:8080"


# What runs once and exits: these must not come back after a restart.
ONE_SHOT = ("aisc-backend-migrate", "control-objectives-migrate", "controls-migrate", "dashboard-migrate",
            "immudb-key", "ledger-pool", "make_buckets", "postgres-setup",
            "qualification-migrate", "report-composer-migrate", "report-grants")


#: the file sets an install runs with: the default ones, and with the https and admin-ports files added
RUN_FILES = [FILES, FILES + ["docker-compose.https.yml", "docker-compose.admin-ports.yml"]]


@pytest.mark.parametrize("files", RUN_FILES, ids=["default", "https-and-admin-ports"])
def test_every_long_running_service_comes_back_after_a_restart(tmp_path, files):
    """After a Docker or computer restart a service with no restart policy stays down (keycloak, immudb,
    rabbitmq, minio, the backend, the eval worker and the webapp did), and the install looks broken."""
    services = compose_cfg.config(tmp_path, files=files)["services"]
    stays_down = sorted(n for n, s in services.items()
                        if n not in ONE_SHOT and s.get("restart") not in ("always", "unless-stopped"))
    assert not stays_down, f"these do not come back after a restart: {stays_down}"


@pytest.mark.parametrize("files", RUN_FILES, ids=["default", "https-and-admin-ports"])
def test_no_one_shot_runs_again_after_a_restart(tmp_path, files):
    """A migration or a job that exits when done, brought back by a restart policy, runs again at every Docker
    restart (and one that is always brought back never stays done)."""
    services = compose_cfg.config(tmp_path, files=files)["services"]
    assert set(ONE_SHOT) <= set(services), f"not services: {sorted(set(ONE_SHOT) - set(services))}"
    again = sorted(n for n in ONE_SHOT if services[n].get("restart") not in (None, "no", "on-failure"))
    assert not again, f"these one-shots come back after a restart: {again}"


@pytest.mark.parametrize("files", RUN_FILES, ids=["default", "https-and-admin-ports"])
def test_a_service_stopped_on_purpose_stays_stopped(tmp_path, files):
    """`restart: always` brings a service back by itself when Docker restarts, even one a person stopped on
    purpose (caddy came back alone after `docker compose stop`); unless-stopped does not."""
    services = compose_cfg.config(tmp_path, files=files)["services"]
    assert not sorted(n for n, s in services.items() if s.get("restart") == "always")


def test_every_container_name_carries_the_install_prefix():
    """Each container_name starts with ${CONTAINER_PREFIX:-}, so an install's containers are its own."""
    import yaml
    for f in ROOT.glob("docker-compose*.yml"):
        for svc, spec in (yaml.safe_load(f.read_text()).get("services") or {}).items():
            name = (spec or {}).get("container_name")
            if name:
                assert name.startswith("${CONTAINER_PREFIX:-}"), (f.name, svc)


def test_the_card_agent_gets_a_model_when_the_project_chose_none(compose):
    """As for control objectives: a local Ollama model by default (no key), overridable from the install's
    settings (QUALIFICATION_AGENTS_LLM_*), and the provider keys passed through; the project's own choice
    under Manage > AI assistants wins over all of these."""
    _, cfg = compose
    env = cfg["services"]["qualification-agents"]["environment"]
    assert env["BAF_LLM_PROVIDER"] == "ollama"
    assert env["BAF_LLM_MODEL"] == "mistral:latest"
    assert env["BAF_LLM_BASE_URL"] == "http://host.docker.internal:11434"
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "MISTRAL_API_KEY"):
        assert key in env, key


def test_the_stack_tells_the_engine_where_it_mounts_the_plugins(compose):
    """PLUGIN_PATH in the install's settings is the host folder; inside the engine's containers the folder is
    mounted at /app/plugins, and that is the path they are told, as in the standalone compose."""
    _, cfg = compose
    for name in ("aisc-backend", "aisc-eval-worker"):
        svc = cfg["services"][name]
        targets = [v["target"] if isinstance(v, dict) else str(v).split(":")[1] for v in svc.get("volumes") or []]
        assert svc["environment"]["PLUGIN_PATH"] == "/app/plugins" and "/app/plugins" in targets, name
