"""The Configurator's Caddy, as a real caddy:2.10.2 reads it (`caddy adapt` in a throwaway container).

The Configurator serves each part at its own host name on 443: the engine, the launcher, the dashboard and the
sign-in (Keycloak, without its administration), and 80 only redirects to https. Its Caddyfile
(infra/caddy/Caddyfile.configurator) imports the development Caddyfile unchanged, whose three sites then listen
inside the container only, and puts one TLS site per host name in front of them. The development compose's Caddy
keeps the development Caddyfile and serves the same sites on the same ports as before.

Read-only: nothing but `docker compose config` and `caddy adapt` runs; no port is opened.
"""
import json
import shutil
import subprocess

import pytest

import compose_cfg
from conftest import ROOT

CONFIGURATOR_CADDYFILE = ROOT / "infra/caddy/Caddyfile.configurator"
CONF = compose_cfg.FILES + ["docker-compose.https.yml", "docker-compose.configurator.yml"]
SETTINGS = ROOT / "env.configurator.example"
HOSTS = {"engine": "app.example.org", "launcher": "home.example.org", "dashboard": "dashboard.example.org",
         "sign-in": "auth.example.org"}
#: the settings that name them, as env.configurator.example sets them (compose's test helper would otherwise give
#: every required setting a dummy value)
HOST_SETTINGS = {"ENGINE_HOST": HOSTS["engine"], "LAUNCHER_HOST": HOSTS["launcher"],
                 "DASHBOARD_HOST": HOSTS["dashboard"], "SIGN_IN_HOST": HOSTS["sign-in"]}
#: inside Caddy's container: the TLS sites (published as 443) and the redirect to them (published as 80)
TLS_LISTENER, REDIRECT_LISTENER = ":8443", ":8080"
#: the development sites' own listeners: the engine, the launcher and the dashboard
DEVELOPMENT_LISTENERS = [":8005", ":8006", ":8008"]


def _adapt(mounts: dict, env: dict) -> dict:
    if not shutil.which("docker"):
        pytest.skip("docker is not available")
    volumes = [a for target, source in mounts.items() for a in ("-v", f"{source}:{target}:ro")]
    envs = [a for k, v in env.items() for a in ("-e", f"{k}={v}")]
    r = subprocess.run(["docker", "run", "--rm", "--network", "none", *envs, *volumes, "caddy:2.10.2", "caddy",
                        "adapt", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout)


def _caddy(tmp_path, files, settings_file, **env) -> tuple[dict, dict]:
    """Caddy's Caddyfile mounts and environment as compose resolves them for these files."""
    caddy = compose_cfg.config(tmp_path, files=files, settings_file=settings_file,
                               env={**HOST_SETTINGS, **env})["services"]["caddy"]
    mounts = {m["target"]: m["source"] for m in caddy["volumes"] if m["target"].startswith("/etc/caddy/Caddyfile")}
    return mounts, {k: v for k, v in caddy["environment"].items() if v is not None}


def _servers(config: dict) -> dict:
    return config["apps"]["http"]["servers"]


def _by_listener(config: dict) -> dict:
    return {listen: server for server in _servers(config).values() for listen in server["listen"]}


def _hosts(server: dict) -> set:
    return {h for route in server.get("routes") or [] for m in route.get("match") or [] for h in m.get("host") or []}


def _route_for(server: dict, host: str) -> dict:
    return next(r for r in server["routes"] if any(host in (m.get("host") or []) for m in r.get("match") or []))


def test_the_development_caddy_serves_the_same_sites_on_the_same_ports(tmp_path):
    mounts, env = _caddy(tmp_path, compose_cfg.FILES, compose_cfg.SETTINGS, AISC_IMAGE_TAG="sha-0123abc")
    assert mounts == {"/etc/caddy/Caddyfile": str(ROOT / "Caddyfile")}
    ports = compose_cfg.config(tmp_path, files=compose_cfg.FILES)["services"]["caddy"]["ports"]
    assert sorted((str(p["published"]), p["target"]) for p in ports) == [("80", 8005), ("8100", 8006), ("8188", 8008)]
    listeners = _by_listener(_adapt(mounts, env))
    assert sorted(listeners) == DEVELOPMENT_LISTENERS
    assert all(_hosts(server) == {"localhost"} for server in listeners.values())


def test_the_configurator_serves_each_part_by_host_name_on_one_tls_listener(tmp_path):
    mounts, env = _caddy(tmp_path, CONF, SETTINGS, AISC_IMAGE_TAG="sha-0123abc")
    assert mounts["/etc/caddy/Caddyfile"] == str(CONFIGURATOR_CADDYFILE)
    listeners = _by_listener(_adapt(mounts, env))
    assert sorted(listeners) == sorted([*DEVELOPMENT_LISTENERS, TLS_LISTENER, REDIRECT_LISTENER])
    assert _hosts(listeners[TLS_LISTENER]) == set(HOSTS.values())
    # the development sites, behind the TLS ones: plain http on the container's own ports, for any name
    assert all(_hosts(listeners[port]) == set() for port in DEVELOPMENT_LISTENERS)
    ports = compose_cfg.config(tmp_path, files=CONF, settings_file=SETTINGS,
                               env={"AISC_IMAGE_TAG": "sha-0123abc", **HOST_SETTINGS})["services"]["caddy"]["ports"]
    assert sorted((str(p["published"]), p["target"]) for p in ports) == [("443", 8443), ("80", 8080)]


def test_each_tls_site_reaches_its_part(tmp_path):
    mounts, env = _caddy(tmp_path, CONF, SETTINGS, AISC_IMAGE_TAG="sha-0123abc")
    tls = _by_listener(_adapt(mounts, env))[TLS_LISTENER]
    upstreams = {part: {u["dial"] for u in _dials(_route_for(tls, host))} for part, host in HOSTS.items()}
    assert upstreams["engine"] == {"127.0.0.1:8005", "oauth2-proxy:4180"}
    assert upstreams["launcher"] == {"127.0.0.1:8006", "oauth2-proxy:4180"}
    assert upstreams["dashboard"] == {"127.0.0.1:8008", "oauth2-proxy:4180"}
    assert upstreams["sign-in"] == {"keycloak:8080"}


def test_the_sign_in_gateway_is_told_the_browser_came_over_https(tmp_path):
    mounts, env = _caddy(tmp_path, CONF, SETTINGS, AISC_IMAGE_TAG="sha-0123abc")
    tls = _by_listener(_adapt(mounts, env))[TLS_LISTENER]
    for part in ("engine", "launcher", "dashboard"):
        proxies = [h for h in _handlers(_route_for(tls, HOSTS[part]))
                   if h.get("handler") == "reverse_proxy" and h["upstreams"] == [{"dial": "oauth2-proxy:4180"}]]
        assert proxies, part
        assert all(p["headers"]["request"]["set"]["X-Forwarded-Proto"] == ["https"] for p in proxies), part


def test_keycloak_administration_is_closed_on_the_public_sign_in_name(tmp_path):
    mounts, env = _caddy(tmp_path, CONF, SETTINGS, AISC_IMAGE_TAG="sha-0123abc")
    route = _route_for(_by_listener(_adapt(mounts, env))[TLS_LISTENER], HOSTS["sign-in"])
    text = json.dumps(route)
    closed = [r for r in _subroutes(route) if any(h.get("handler") == "static_response" for h in r["handle"])]
    paths = {p for r in closed for m in r.get("match") or [] for p in m.get("path") or []}
    assert {"/admin", "/admin/*", "/realms/master", "/realms/master/*"} <= paths
    assert all(str(h.get("status_code")) == "404" for r in closed for h in r["handle"])
    # the closing routes come before the one that reaches Keycloak
    assert text.index('"static_response"') < text.index('"keycloak:8080"')


def test_plain_http_only_redirects_to_https(tmp_path):
    mounts, env = _caddy(tmp_path, CONF, SETTINGS, AISC_IMAGE_TAG="sha-0123abc")
    redirect = _by_listener(_adapt(mounts, env))[REDIRECT_LISTENER]
    handlers = [h for r in redirect["routes"] for h in r["handle"]]
    assert [h["handler"] for h in handlers] == ["static_response"]
    assert handlers[0]["headers"]["Location"] == ["https://{http.request.host}{http.request.uri}"]
    assert str(handlers[0]["status_code"]) in ("301", "308")


def _subroutes(node):
    if isinstance(node, dict):
        if "handle" in node and isinstance(node["handle"], list):
            yield node
        for v in node.values():
            yield from _subroutes(v)
    elif isinstance(node, list):
        for v in node:
            yield from _subroutes(v)


def _handlers(node):
    for r in _subroutes(node):
        yield from (h for h in r["handle"] if isinstance(h, dict))


def _dials(route):
    return [u for h in _handlers(route) if h.get("handler") == "reverse_proxy" for u in h.get("upstreams") or []]
