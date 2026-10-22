"""The gateway's session cookie is the one every module trusts: served over HTTPS it is Secure, so a
browser never sends it over plain HTTP. Caddy serves HTTPS when CADDY_DOMAIN starts with https://, and
GATEWAY_COOKIE_SECURE follows it; compose refuses to start without the setting."""
import re

import yaml

from conftest import ROOT


def test_the_gateway_takes_cookie_secure_from_the_setting():
    proxy = yaml.safe_load((ROOT / "docker-compose-infra.development.yml").read_text())["services"]["oauth2-proxy"]
    flags = [a for a in proxy["command"] if a.startswith("--cookie-secure")]
    assert len(flags) == 1 and re.fullmatch(r"--cookie-secure=\$\{GATEWAY_COOKIE_SECURE:\?[^}]+\}", flags[0]), flags


def test_the_tracked_settings_make_the_cookie_secure_exactly_when_caddy_serves_https():
    lines = dict(line.split("=", 1) for line in (ROOT / "env.plugin_downloader").read_text().splitlines()
                 if "=" in line and not line.startswith("#"))
    https = lines["CADDY_DOMAIN"].strip('"').startswith("https://")
    assert lines["GATEWAY_COOKIE_SECURE"] == ("true" if https else "false")
