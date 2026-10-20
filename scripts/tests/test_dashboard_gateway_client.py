"""The dashboard takes only the gateway's tokens.

dashboard-gateway/gateway_identity.py verifies the token Caddy copies from the gateway and checks that it
was issued to the gateway's own Keycloak client (`azp`, the audience Keycloak gives an access token), as
shared/identity does for every other module. The client comes from the dashboard's settings: the same
client oauth2-proxy signs people in with, never a value written in the code."""
import re

import yaml

from conftest import ROOT

INFRA = yaml.safe_load((ROOT / "docker-compose-infra.development.yml").read_text())["services"]
APP = yaml.safe_load((ROOT / "docker-compose.development.yml").read_text())["services"]
CONFIG = (ROOT / "dashboard-gateway/superset_gateway_config.py").read_text()
IDENTITY = (ROOT / "dashboard-gateway/gateway_identity.py").read_text()


def gateway_client():
    flags = [a for a in INFRA["oauth2-proxy"]["command"] if str(a).startswith("--client-id=")]
    assert len(flags) == 1, flags
    return flags[0].split("=", 1)[1]


def test_the_dashboard_is_told_the_gateways_client():
    assert APP["dashboard"]["environment"]["AISC_GATEWAY_CLIENT_ID"] == gateway_client()


def test_the_gateway_config_passes_it_from_the_settings():
    assert re.search(r'client_id=os\.environ\["AISC_GATEWAY_CLIENT_ID"\]', CONFIG)


def test_the_client_is_not_written_in_the_code():
    assert "aisc-gateway" not in IDENTITY and "aisc-gateway" not in CONFIG
