"""The realm names the engine by its address setting, so an install whose engine moved off port 80 signs in
there too. Keycloak fills ${API_URL_EXTERNAL} from its environment when it imports the realm."""
import json

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
