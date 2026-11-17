"""The Configurator's own deployment: an override on the two development files that turns every hardening setting
on. Postgres speaks TLS only and every client requires it; every long-running service has a healthcheck and a
restart policy, and nothing starts before what it needs is healthy (or, for a one-shot, finished). No development
convenience is left: Keycloak runs `start`, Caddy publishes 80 and 443 only, the inspection tools stay off, the
ledger is enforced and every image is one tagged build. The settings template names every variable and holds no
secret; start refuses a Configurator served over plain http.

Read-only: `docker compose config` on copies of the files, the template and hba file as text, scripts/aisc.py
asked for its refusal in a scratch copy of the checkout. Nothing is started.
"""

import os
import re
import subprocess
import sys

import compose_cfg
from conftest import ROOT, aisc_py, copy_install_scripts

OVERRIDE = "docker-compose.configurator.yml"
CONF = compose_cfg.FILES + ["docker-compose.https.yml", OVERRIDE]
SETTINGS = ROOT / "env.configurator.example"
HBA = ROOT / "infra/postgres/pg_hba.configurator.conf"
#: services that run once and exit
ONE_SHOT = {"make_buckets", "postgres-setup", "immudb-key", "ledger-pool", "report-grants", "aisc-backend-migrate",
            "controls-migrate", "qualification-migrate", "control-objectives-migrate", "report-composer-migrate",
            "dashboard-migrate", "minio-data-owner", "devpi-data-owner", "rabbitmq-setup", "postgres-tls"}
DB_CLIENT_KEYS = ("DB_PASSWORD", "DATABASE_URL", "PGPASSWORD", "KC_DB_PASSWORD")


def _conf(tmp_path) -> dict:
    assert (ROOT / OVERRIDE).is_file(), "no docker-compose.configurator.yml: the Configurator has no deployment file"
    assert SETTINGS.is_file(), "no env.configurator.example"
    return compose_cfg.config(tmp_path, files=CONF, settings_file=SETTINGS,
                              env={"AISC_IMAGE_TAG": "sha-0123abc", "CADDY_DOMAIN": "https://aisc.example"})["services"]


def test_every_long_running_service_has_a_healthcheck_and_restarts(tmp_path):
    conf = _conf(tmp_path)
    long = {n: v for n, v in conf.items() if n not in ONE_SHOT}
    assert sorted(n for n, v in long.items() if not v.get("healthcheck")) == []
    assert sorted(n for n, v in long.items() if v.get("restart") != "unless-stopped") == []


def test_nothing_starts_before_what_it_needs_is_healthy(tmp_path):
    conf = _conf(tmp_path)
    bad = sorted((n, d, c["condition"]) for n, v in conf.items() for d, c in (v.get("depends_on") or {}).items()
                 if c["condition"] != ("service_completed_successfully" if d in ONE_SHOT else "service_healthy"))
    assert bad == []


def test_postgres_talks_tls_only_and_every_client_requires_it(tmp_path):
    conf = _conf(tmp_path)
    cmd = " ".join(conf["postgres"]["command"])
    assert "ssl=on" in cmd and "hba_file=" in cmd
    assert HBA.is_file(), "no pg_hba file for the Configurator"
    hba = HBA.read_text()
    assert "hostssl all all all scram-sha-256" in hba and "host all all all reject" in hba
    clients = {n for n, v in conf.items() if any(k in (v.get("environment") or {}) for k in DB_CLIENT_KEYS)}
    plain = sorted(n for n in clients if conf[n]["environment"].get("PGSSLMODE") != "require"
                   and not any("sslmode=require" in str(x) for x in conf[n]["environment"].values()))
    assert plain == []


def test_no_development_convenience_is_left(tmp_path):
    conf = _conf(tmp_path)
    assert conf["keycloak"]["command"][0] == "start"
    assert {str(p["published"]) for p in conf["caddy"]["ports"]} == {"80", "443"}
    assert not {"pgadmin", "schema-docs", "aisc-eval-flower"} & set(conf)
    assert sorted(n for n, v in conf.items() if str(v.get("image", "")).endswith(":latest")) == []
    modes = {(n, v["environment"]["LEDGER_MODE"]) for n, v in conf.items()
             if "LEDGER_MODE" in (v.get("environment") or {})}
    assert modes and {m for _, m in modes} == {"enforce"}


def test_the_template_names_every_variable_and_holds_no_secret():
    assert SETTINGS.is_file(), "no env.configurator.example"
    assert (ROOT / OVERRIDE).is_file(), "no docker-compose.configurator.yml"
    text = SETTINGS.read_text()
    names = set(re.findall(r"^#?\s*([A-Z0-9_]+)=", text, re.M))
    assert sorted(compose_cfg.required(CONF) - names) == []
    assert not re.search(r"^(?!#)\s*[A-Z0-9_]*(PASSWORD|SECRET|TOKEN|KEY)=\S", text, re.M)


def test_start_refuses_a_configurator_over_plain_http(tmp_path):
    copy_install_scripts(tmp_path)
    (tmp_path / "env.plugin_downloader").write_text("CADDY_DOMAIN=http://aisc.example\n")
    env = {**os.environ, "CADDY_DOMAIN": "http://aisc.example", "PATH": "/nonexistent"}
    r = subprocess.run([sys.executable, str(tmp_path / "scripts/aisc.py"), "start", "--configurator"],
                       cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    said = r.stdout + r.stderr
    assert r.returncode != 0
    # refused for the address before anything asks for docker (none is on PATH here, so asking would be refused
    # for that instead)
    assert "https" in said and "Docker is not running" not in said, said[-800:]


def test_start_refuses_a_configurator_without_its_settings_file(tmp_path):
    copy_install_scripts(tmp_path)
    env = {**os.environ, "CADDY_DOMAIN": "https://aisc.example", "PATH": "/nonexistent"}
    r = subprocess.run([sys.executable, str(tmp_path / "scripts/aisc.py"), "start", "--configurator"],
                       cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    said = r.stdout + r.stderr
    assert r.returncode != 0
    assert "env.configurator.example" in said and "Docker is not running" not in said, said[-800:]


def test_the_configurator_takes_its_own_settings_and_compose_files(tmp_path, monkeypatch):
    copy_install_scripts(tmp_path)
    (tmp_path / "env.plugin_downloader").write_text("CADDY_DOMAIN=http://localhost\nCADDY_ENVIRONMENT=development\n")
    (tmp_path / "env.configurator").write_text("CADDY_DOMAIN=https://aisc.example\nCADDY_ENVIRONMENT=production\n")
    (tmp_path / "env.secrets").write_text("POSTGRES_PASSWORD=not-a-real-one\n")
    monkeypatch.delenv("CADDY_DOMAIN", raising=False)
    monkeypatch.chdir(tmp_path)
    m = aisc_py(tmp_path)
    m.settings.use_configurator()
    assert m.settings.settings_file() == "env.configurator" and m.settings.served_over_https()
    files = [m.settings.COMPOSE[i + 1] for i, arg in enumerate(m.settings.COMPOSE) if arg == "-f"]
    assert files[-2:] == ["docker-compose.https.yml", OVERRIDE]
    m.secrets.write_runtime()
    runtime = (tmp_path / "env.runtime").read_text()
    assert "CADDY_ENVIRONMENT=production" in runtime and "CADDY_ENVIRONMENT=development" not in runtime


def test_the_postgres_key_and_certificate_are_made_once_private_and_kept(tmp_path):
    copy_install_scripts(tmp_path)
    # cryptography is the install script's own dependency (its header), not the suite's
    make = ("import sys; sys.path.insert(0, 'scripts'); import importlib.util as u; "
            "s = u.spec_from_file_location('install', 'scripts/aisc.py'); m = u.module_from_spec(s); "
            "sys.modules['install'] = m; s.loader.exec_module(m); m.secrets.make_postgres_tls()")
    first = subprocess.run(["uv", "run", "--quiet", "--no-project", "--with", "cryptography>=42", "python", "-c", make],
                           cwd=tmp_path, capture_output=True, text=True, timeout=300)
    assert first.returncode == 0, first.stderr[-800:]
    key, cert = tmp_path / "postgres-tls/server.key", tmp_path / "postgres-tls/server.crt"
    assert "PRIVATE KEY" in key.read_text() and "BEGIN CERTIFICATE" in cert.read_text()
    if os.name != "nt":
        assert key.stat().st_mode & 0o777 == 0o600
    made = key.read_bytes(), cert.read_bytes()
    again = subprocess.run(["uv", "run", "--quiet", "--no-project", "--with", "cryptography>=42", "python", "-c", make],
                           cwd=tmp_path, capture_output=True, text=True, timeout=300)
    assert again.returncode == 0, again.stderr[-800:]
    assert (key.read_bytes(), cert.read_bytes()) == made
