"""How many wrong passwords the realm takes before it locks an account for a while. Keycloak counts wrong
passwords only when brute-force protection is on, so the failure factor alone locks nobody."""
import json

from conftest import ROOT

REALM = json.loads((ROOT / "keycloak/aisc-realm.json").read_text())


def test_an_account_locks_after_five_wrong_passwords():
    assert REALM["bruteForceProtected"] is True
    assert REALM["failureFactor"] == 5
