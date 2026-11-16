"""The realm asks for passwords of 12 characters or more that are not the user name or e-mail and not one of the
last three; every start applies it, and the lockout, to realms made before (the master realm included). Staging
imports a realm with no accounts and no client secret, the development realm otherwise unchanged.

Read-only: the realm files and the staging compose file as text, scripts/aisc.py loaded as a module.
"""

import json
import re

import yaml

from conftest import ROOT, aisc_py

POLICY = "length(12) and notUsername and notEmail and passwordHistory(3)"
REALM = json.loads((ROOT / "keycloak/aisc-realm.json").read_text())
STAGING_REALM = ROOT / "keycloak/aisc-realm.staging.json"


def test_the_realm_asks_for_long_passwords():
    assert REALM.get("passwordPolicy") == POLICY


def test_the_staging_realm_is_the_development_realm_without_its_accounts():
    assert STAGING_REALM.is_file(), "no staging realm: staging imports the development accounts admin and user"
    staging = json.loads(STAGING_REALM.read_text())
    dev = json.loads(json.dumps(REALM))
    dev.pop("users", None)
    for client in dev["clients"]:
        if client["clientId"] == "aisc-gateway":
            client.pop("secret", None)
    assert staging == dev
    # no secret is filled in at its import: no client secret, no account password (Keycloak's own message keys
    # and the address placeholders, ${role_...} and ${API_URL_EXTERNAL}, stay as in the development realm)
    assert not re.search(r"\$\{(GATEWAY_CLIENT_SECRET|AISC_[A-Z_]*PASSWORD)\}", json.dumps(staging))


def test_staging_imports_the_realm_without_accounts():
    kc = yaml.safe_load((ROOT / "docker-compose-infra.staging.yml").read_text())["services"]["keycloak"]
    assert "./keycloak/aisc-realm.staging.json:/opt/keycloak/data/import/aisc-realm.json:ro" in kc["volumes"]


def test_every_start_applies_the_policy_and_the_lockout_to_existing_realms():
    m = aisc_py()
    assert hasattr(m, "realm_hardening_commands"), \
        "start applies no password policy, and no lockout to the master realm, on a realm made before"
    calls = m.realm_hardening_commands()
    assert ["update", "realms/aisc", "-s", "bruteForceProtected=true", "-s", "passwordPolicy=" + POLICY] in calls
    assert ["update", "realms/master", "-s", "bruteForceProtected=true"] in calls
