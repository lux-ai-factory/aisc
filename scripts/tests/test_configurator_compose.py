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
#: the Configurator's own Caddy sites: one per part, by host name, on 443 (it imports the development Caddyfile)
CONFIGURATOR_CADDYFILE = ROOT / "infra/caddy/Caddyfile.configurator"
#: the setting that names each part's host, and the example.org-style name the template gives it
HOSTS = {"ENGINE_HOST": "app.example.org", "LAUNCHER_HOST": "home.example.org",
         "DASHBOARD_HOST": "dashboard.example.org", "SIGN_IN_HOST": "auth.example.org"}
#: services that run once and exit
ONE_SHOT = {"make_buckets", "postgres-setup", "immudb-key", "ledger-pool", "report-grants", "aisc-backend-migrate",
            "controls-migrate", "qualification-migrate", "control-objectives-migrate", "report-composer-migrate",
            "dashboard-migrate", "minio-data-owner", "devpi-data-owner", "rabbitmq-setup", "postgres-tls"}
DB_CLIENT_KEYS = ("DB_PASSWORD", "DATABASE_URL", "PGPASSWORD", "KC_DB_PASSWORD")


def _conf(tmp_path) -> dict:
    assert (ROOT / OVERRIDE).is_file(), "no docker-compose.configurator.yml: the Configurator has no deployment file"
    assert SETTINGS.is_file(), "no env.configurator.example"
    return compose_cfg.config(tmp_path, files=CONF, settings_file=SETTINGS,
                              env={"AISC_IMAGE_TAG": "sha-0123abc", **HOSTS})["services"]


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


def test_only_caddy_publishes_and_only_80_and_443(tmp_path):
    conf = _conf(tmp_path)
    published = {n: sorted(str(p["published"]) for p in v.get("ports") or []) for n, v in conf.items()}
    assert {n: p for n, p in published.items() if p} == {"caddy": ["443", "80"]}


def test_the_template_gives_each_part_an_example_host_name():
    text = SETTINGS.read_text()
    for name, host in HOSTS.items():
        assert re.search(rf"^{name}={re.escape(host)}$", text, re.M), f"env.configurator.example lacks {name}={host}"
    # every public address is made from those names: no other name of this install's own is written there
    public = re.findall(r"^(?:CADDY_DOMAIN|API_URL_EXTERNAL|LAUNCHER_EXTERNAL_URL|DASHBOARD_EXTERNAL_URL|"
                        r"KEYCLOAK_URL_EXTERNAL|BACKEND_CORS_ALLOWED_ORIGINS|CORS_ORIGINS)=(.*)$", text, re.M)
    assert len(public) == 7 and all(re.fullmatch(r"https://\$\{[A-Z_]+_HOST\}/?", v) for v in public), public


def test_every_public_address_takes_its_host_from_those_settings(tmp_path):
    conf = _conf(tmp_path)
    engine, launcher, dashboard, sign_in = (f"https://{HOSTS[n]}" for n in HOSTS)
    for service in ("caddy", "keycloak"):
        env = conf[service]["environment"]
        assert env["API_URL_EXTERNAL"] == engine
        assert env["DASHBOARD_EXTERNAL_URL"] == dashboard
    assert conf["keycloak"]["environment"]["LAUNCHER_EXTERNAL_URL"] == launcher + "/"
    assert conf["caddy"]["environment"]["KEYCLOAK_URL_EXTERNAL"] == sign_in
    assert conf["keycloak"]["environment"]["KC_HOSTNAME"] == sign_in
    proxy = conf["oauth2-proxy"]["command"]
    assert f"--oidc-issuer-url={sign_in}/realms/aisc" in proxy
    assert f"--login-url={sign_in}/realms/aisc/protocol/openid-connect/auth" in proxy
    assert sorted(a.split("=", 1)[1] for a in proxy if a.startswith("--whitelist-domain=")) == sorted(HOSTS.values())
    # one sign-in cookie per host name: none set for localhost, none shared with the parent domain
    assert [a for a in proxy if a.startswith("--cookie-domain")] == []
    # nothing a browser is sent to, or that names the install to the outside, is still on this machine
    local = sorted((n, str(x)) for n, v in conf.items()
                   for x in [*(v.get("environment") or {}).values(), *(v.get("command") or [])]
                   if re.search(r"https?://(localhost|127\.0\.0\.1)\b", str(x)))
    assert local == []


def test_apart_from_its_public_names_the_sign_in_gateway_runs_as_in_development(tmp_path):
    conf = _conf(tmp_path)
    # the development files with the same settings, so every address they name is the same
    (tmp_path / "development").mkdir()
    development = compose_cfg.config(tmp_path / "development", settings_file=SETTINGS,
                                     env={"AISC_IMAGE_TAG": "sha-0123abc", **HOSTS})["services"]

    def flags(command):
        return sorted(a for a in command if not a.startswith(("--cookie-domain", "--whitelist-domain")))

    assert flags(conf["oauth2-proxy"]["command"]) == flags(development["oauth2-proxy"]["command"])


def test_caddy_serves_the_configurator_sites_beside_the_development_file(tmp_path):
    conf = _conf(tmp_path)
    mounts = {m["target"]: m["source"] for m in conf["caddy"]["volumes"]}
    assert mounts["/etc/caddy/Caddyfile"] == str(CONFIGURATOR_CADDYFILE)
    assert mounts["/etc/caddy/Caddyfile.development"] == str(ROOT / "Caddyfile")
    env = conf["caddy"]["environment"]
    assert {n: env.get(n) for n in HOSTS} == HOSTS


def test_start_refuses_a_configurator_without_a_host_name(tmp_path):
    copy_install_scripts(tmp_path)
    text = SETTINGS.read_text().replace("SIGN_IN_HOST=auth.example.org", "SIGN_IN_HOST=")
    (tmp_path / "env.configurator").write_text(text)
    said, code = _start_configurator(tmp_path)
    assert code != 0 and "SIGN_IN_HOST" in said and "Docker is not running" not in said, said[-800:]


def test_start_refuses_a_configurator_part_served_over_plain_http(tmp_path):
    copy_install_scripts(tmp_path)
    text = SETTINGS.read_text()
    assert "KEYCLOAK_URL_EXTERNAL=https://${SIGN_IN_HOST}" in text
    (tmp_path / "env.configurator").write_text(
        text.replace("KEYCLOAK_URL_EXTERNAL=https://${SIGN_IN_HOST}", "KEYCLOAK_URL_EXTERNAL=http://${SIGN_IN_HOST}"))
    said, code = _start_configurator(tmp_path)
    assert code != 0 and "KEYCLOAK_URL_EXTERNAL" in said and "https" in said, said[-800:]
    assert "Docker is not running" not in said, said[-800:]


def test_start_accepts_the_template_host_names_and_goes_on_to_docker(tmp_path):
    copy_install_scripts(tmp_path)
    (tmp_path / "env.configurator").write_text(SETTINGS.read_text())
    said, code = _start_configurator(tmp_path)
    # past every check of the settings: the next step asks for Docker, which is not on PATH here
    assert code != 0 and "Docker is not running" in said, said[-800:]


def test_the_settings_read_back_as_compose_reads_them(tmp_path, monkeypatch):
    copy_install_scripts(tmp_path)
    (tmp_path / "env.runtime").write_text("LAUNCHER_HOST=home.example.org\n"
                                          "LAUNCHER_EXTERNAL_URL=https://${LAUNCHER_HOST}/\n")
    monkeypatch.chdir(tmp_path)
    m = aisc_py(tmp_path)
    assert m.settings.effective("LAUNCHER_EXTERNAL_URL") == "https://home.example.org/"


def test_the_configurator_start_waits_for_the_realm_on_443_by_the_sign_in_name(tmp_path, monkeypatch):
    copy_install_scripts(tmp_path)
    (tmp_path / "env.configurator").write_text(SETTINGS.read_text())
    (tmp_path / "env.runtime").write_text(SETTINGS.read_text())
    monkeypatch.delenv("START_SIGN_IN_URL", raising=False)
    monkeypatch.delenv("CADDY_DOMAIN", raising=False)
    monkeypatch.chdir(tmp_path)
    m = aisc_py(tmp_path)
    m.settings.use_configurator()
    asked = []
    monkeypatch.setattr(m.stack, "answer_over_tls", lambda port, name, path="/": asked.append((port, name, path)) or 200)
    assert m.stack.realm_answer() == 200
    assert asked == [(443, "auth.example.org", "/realms/aisc")]


def _start_configurator(folder):
    env = {k: v for k, v in os.environ.items() if not k.endswith("_HOST") and k != "CADDY_DOMAIN"}
    r = subprocess.run([sys.executable, str(folder / "scripts/aisc.py"), "start", "--configurator"],
                       cwd=folder, env={**env, "PATH": "/nonexistent"}, capture_output=True, text=True, timeout=60)
    return r.stdout + r.stderr, r.returncode


def test_compose_finds_every_setting_it_reads_in_the_template(tmp_path):
    r = compose_cfg.run(tmp_path, files=CONF, settings_file=SETTINGS,
                        env={"AISC_IMAGE_TAG": "sha-0123abc", **HOSTS})
    assert r.returncode == 0, r.stderr[-800:]
    unset = set(re.findall(r'The \\?"(\w+)\\?" variable is not set', r.stderr))
    # the secrets come from env.secrets: the template names them in comments only
    secrets = set(re.findall(r"^# ([A-Z0-9_]+)=$", SETTINGS.read_text(), re.M))
    assert sorted(unset - secrets) == []
