"""The realm names the engine by its address setting, so an install whose engine moved off port 80 signs in
there too. Keycloak fills ${API_URL_EXTERNAL} from its environment when it imports the realm."""
import json
import re
import shutil

import pytest

import compose_cfg
from conftest import ROOT

REALM = json.loads((ROOT / "keycloak/aisc-realm.json").read_text())
ENGINE_CLIENTS = ("aisc-gateway", "aisc-webapp")


def addresses(client):
    logout = client.get("attributes", {}).get("post.logout.redirect.uris", "")
    return [client.get("baseUrl") or "", *client.get("redirectUris", []), *client.get("webOrigins", []),
            *[a for a in logout.split("##") if a]]


def test_the_engine_address_in_the_realm_is_a_placeholder():
    clients = {c["clientId"]: c for c in REALM["clients"]}
    for name in ENGINE_CLIENTS:
        found = [a for a in addresses(clients[name]) if a]
        assert not [a for a in found if a == "http://localhost" or a.startswith("http://localhost/")], name
        assert any(a.startswith("${API_URL_EXTERNAL}") for a in found), name


def test_the_realm_names_every_browser_address_by_its_setting():
    """The launcher and the dashboard may move off 8100 and 8188 too; Keycloak fills their addresses in."""
    gateway = next(c for c in REALM["clients"] if c["clientId"] == "aisc-gateway")
    found = addresses(gateway)
    assert [a for a in found if "localhost:8100" in a or "localhost:8188" in a] == []
    assert "${LAUNCHER_EXTERNAL_URL}oauth2/callback" in gateway["redirectUris"]
    assert "${DASHBOARD_EXTERNAL_URL}/oauth2/callback" in gateway["redirectUris"]
    webapp = next(c for c in REALM["clients"] if c["clientId"] == "aisc-webapp")
    assert "http://localhost:5173/*" in webapp["redirectUris"]


def test_every_placeholder_of_the_realm_is_in_keycloak_s_environment(tmp_path):
    """Keycloak fills a ${NAME} of the realm file from its own environment at import; one compose does not give
    it stays in the realm as written, and the sign-in or the account it names then does not work."""
    if shutil.which("docker") is None:
        pytest.skip("docker is not installed")
    placeholders = set(re.findall(r"\$\{([A-Z0-9_]+)\}", (ROOT / "keycloak/aisc-realm.json").read_text()))
    environment = compose_cfg.config(tmp_path)["services"]["keycloak"]["environment"]
    assert placeholders and not sorted(placeholders - set(environment))
